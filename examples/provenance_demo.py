from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rlmgraph.models import Assertion, Evidence, GraphEdge, GraphRelation, InvestigationResult
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class ContractInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        value = (project_root / "contract.txt").read_text().strip()
        return InvestigationResult(
            conclusion=f"The authoritative contract value is {value}.",
            confidence=1.0,
            evidence=[Evidence(path="contract.txt", line=1, detail="Authoritative value")],
            files_examined=["contract.txt", "notes.txt"],
            assertions=[Assertion(key="demo.contract.value", value=value)],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j", action="store_true")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="rlmgraph-demo")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    demo_root = root / ".rlmgraph" / "provenance-demo"
    if demo_root.exists():
        shutil.rmtree(demo_root)
    project = demo_root / "project"
    project.mkdir(parents=True)
    database = demo_root / "memory.db"
    contract = project / "contract.txt"
    notes = project / "notes.txt"
    contract.write_text("alpha\n")
    notes.write_text("initial notes\n")

    if args.neo4j:
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        store.initialize()
        old_task_ids = [
            task.id
            for task in store.tasks()
            if Path(task.project_root) == project.resolve()
        ]
        if old_task_ids:
            store.driver.execute_query(
                "MATCH (task:Task) WHERE task.id IN $task_ids "
                "MATCH (task)-[:HAS_RECONSTRUCTION]->"
                "(:Reconstruction)-[:HAS_STEP]->(step) DETACH DELETE step",
                task_ids=old_task_ids,
            )
            store.driver.execute_query(
                "MATCH (task:Task) WHERE task.id IN $task_ids "
                "MATCH (task)-[:HAS_RECONSTRUCTION]->(session) DETACH DELETE session",
                task_ids=old_task_ids,
            )
            old_claim_ids = [
                edge.target
                for edge in store.edges()
                if edge.source in old_task_ids and edge.relation.value == "DISCOVERED"
            ]
            store.driver.execute_query(
                "MATCH (node) WHERE node.id IN $ids DETACH DELETE node",
                ids=[*old_task_ids, *old_claim_ids],
            )
    else:
        store = SQLiteGraphStore(database)
    investigator = ContractInvestigator()
    supervisor = Supervisor(store, investigator)
    question = "What is the authoritative contract value?"

    first = supervisor.run(question, project)
    notes.write_text("unrelated notes changed\n")
    unrelated = supervisor.run(question, project)
    contract.write_text("beta\n")
    replacement = supervisor.run(question, project)
    contract.write_text("alpha\n")
    restored = supervisor.run(question, project)
    old = store.get_claim(first.claim.id)

    if args.neo4j:
        observer_root = store.get_task("LIVE-DEMO-ROOT")
        if observer_root is not None:
            for task in store.tasks():
                if Path(task.project_root) != project.resolve():
                    continue
                task.parent_task_id = observer_root.id
                task.depth = 1
                store.save_task(task)
                store.save_edge(
                    GraphEdge(
                        source=observer_root.id,
                        relation=GraphRelation.SPAWNED,
                        target=task.id,
                    )
                )

    assert unrelated.cache_hit and unrelated.claim.id == first.claim.id
    assert not replacement.cache_hit and replacement.claim.id != first.claim.id
    assert restored.cache_hit and restored.claim.id == first.claim.id
    assert investigator.calls == 2
    assert old is not None

    print(
        json.dumps(
            {
                "database": str(database),
                "backend": "neo4j" if args.neo4j else "sqlite",
                "investigation_calls": investigator.calls,
                "unrelated_change_reused": unrelated.cache_hit,
                "changed_evidence_rejected_stale_claim": not replacement.cache_hit,
                "replacement_claim_id": replacement.claim.id,
                "supersedes_edge_persisted": any(
                    edge.source == replacement.claim.id
                    and edge.relation.value == "SUPERSEDES"
                    and edge.target == first.claim.id
                    for edge in store.edges()
                ),
                "historical_state_reused": restored.claim.id == first.claim.id,
                "historical_status": old.validity_status.value,
                "validity_transitions": [
                    event.status.value for event in old.validity_history
                ],
                "source_files": [
                    source.model_dump(mode="json") for source in old.source_files
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
