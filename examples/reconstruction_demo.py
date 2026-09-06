from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rlmgraph.models import (
    Claim,
    Evidence,
    GraphEdge,
    GraphRelation,
    Task,
    TaskStatus,
)
from rlmgraph.reconstruction import ActiveMemoryReconstructor
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore

PREFIX = "RECON-DEMO-"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j", action="store_true")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="rlmgraph-demo")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    demo_root = root / ".rlmgraph" / "reconstruction-demo"
    if demo_root.exists():
        shutil.rmtree(demo_root)
    project = demo_root / "project"
    project.mkdir(parents=True)
    (project / "contract.txt").write_text("Sampling requires continuous face coordinates.\n")

    if args.neo4j:
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        store.initialize()
        store.driver.execute_query(
            "MATCH (:Task {id: $task_id})-[:HAS_RECONSTRUCTION]->"
            "(:Reconstruction)-[:HAS_STEP]->(step) DETACH DELETE step",
            task_id=f"{PREFIX}TASK",
        )
        store.driver.execute_query(
            "MATCH (:Task {id: $task_id})-[:HAS_RECONSTRUCTION]->(session) "
            "DETACH DELETE session",
            task_id=f"{PREFIX}TASK",
        )
        store.driver.execute_query(
            "MATCH (node) WHERE node.id STARTS WITH $prefix DETACH DELETE node",
            prefix=PREFIX,
        )
    else:
        store = SQLiteGraphStore(demo_root / "memory.db")
        store.initialize()

    task = Task(
        id=f"{PREFIX}TASK",
        question="Why does terrain sampling require face continuity?",
        fingerprint=f"{PREFIX}QUERY",
        project_fingerprint=f"{PREFIX}STATE",
        project_root=str(project.resolve()),
        status=TaskStatus.DONE,
    )
    store.save_task(task)
    seed = Claim(
        id=f"{PREFIX}ANSWER",
        fingerprint=f"{PREFIX}ANSWER",
        project_fingerprint=task.project_fingerprint,
        subject=task.question,
        producer="ReconstructionFixture",
        conclusion="Terrain sampling requires face continuity.",
        confidence=1.0,
        source_claim_ids=[f"{PREFIX}CONTRACT"],
    )
    contract = Claim(
        id=f"{PREFIX}CONTRACT",
        fingerprint=f"{PREFIX}CONTRACT",
        project_fingerprint=task.project_fingerprint,
        subject="Terrain sampling contract",
        producer="ReconstructionFixture",
        conclusion="The contract requires continuous face coordinates.",
        confidence=1.0,
        evidence=[Evidence(path="contract.txt", line=1, detail="Continuity requirement")],
        source_claim_ids=[f"{PREFIX}OBSERVATION"],
    )
    observation = Claim(
        id=f"{PREFIX}OBSERVATION",
        fingerprint=f"{PREFIX}OBSERVATION",
        project_fingerprint=task.project_fingerprint,
        subject="Seam test observation",
        producer="ReconstructionFixture",
        conclusion="The seam test passes only with continuous coordinates.",
        confidence=1.0,
        evidence=[Evidence(path="contract.txt", line=1, detail="Observed behavior")],
    )
    claims = [seed, contract, observation]
    for claim in claims:
        store.save_claim(task, claim)
    for source, target in ((seed, contract), (contract, observation)):
        store.save_edge(
            GraphEdge(
                source=source.id,
                relation=GraphRelation.DERIVED_FROM,
                target=target.id,
            )
        )
    distractors: list[Claim] = []
    for index in range(12):
        distractor = Claim(
            id=f"{PREFIX}NOISE-{index}",
            fingerprint=f"{PREFIX}NOISE-{index}",
            project_fingerprint=task.project_fingerprint,
            subject=f"Unrelated subsystem history {index}",
            producer="ReconstructionFixture",
            conclusion=("Editor UI, character animation, and packaging history. " * 12),
            confidence=0.9,
        )
        distractors.append(distractor)
        store.save_claim(task, distractor)
        store.save_edge(
            GraphEdge(
                source=seed.id,
                relation=GraphRelation.SUPPORTS,
                target=distractor.id,
            )
        )
    session = ActiveMemoryReconstructor(store, seed_count=1).reconstruct(
        task,
        [*claims, *distractors],
        required_evidence_ids=[contract.id, observation.id],
    )
    store.save_reconstruction(session)
    task.reconstruction_id = session.id
    store.save_task(task)
    if args.neo4j:
        observer_root = store.get_task("LIVE-DEMO-ROOT")
        if observer_root is not None:
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

    reduction = round(
        100 * (1 - session.reconstructed_token_estimate / session.baseline_token_estimate),
        1,
    )
    assert session.evidence_preserved is True
    assert session.reconstructed_token_estimate < session.baseline_token_estimate
    print(
        json.dumps(
            {
                "backend": "neo4j" if args.neo4j else "sqlite",
                "reconstruction_id": session.id,
                "seed_nodes": session.seed_node_ids,
                "selected_nodes": session.selected_node_ids,
                "baseline_nodes": len(session.baseline_node_ids),
                "pruned_nodes": len(session.pruned_node_ids),
                "reconstructed_tokens": session.reconstructed_token_estimate,
                "baseline_tokens": session.baseline_token_estimate,
                "token_reduction_percent": reduction,
                "required_evidence_preserved": session.evidence_preserved,
                "steps": [
                    {
                        "action": step.action.value,
                        "node_id": step.node_id,
                        "reason": step.reason,
                    }
                    for step in session.steps
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
