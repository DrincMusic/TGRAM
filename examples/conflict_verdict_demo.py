"""Deterministic conflict -> verdict -> later reuse acceptance proof."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rlmgraph.models import (
    Assertion,
    Evidence,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    PursuitConfig,
    ResolutionChoice,
    ResolutionResult,
    Task,
    TaskStatus,
)
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.runner import RecursiveRunner
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.supervisor import Supervisor

PREFIX = "LIVE-DEMO-"
KEY = "discounted_price.discount_percent.interpretation"


class Findings:
    def __init__(self) -> None:
        self.values = iter(("percentage", "fixed amount"))
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"discount_percent is interpreted as {value}.",
            confidence=0.9,
            evidence=[Evidence(path="pricing.py", line=1, detail=f"Worker reported {value}.")],
            files_examined=["pricing.py"],
            assertions=[Assertion(key=KEY, value=value)],
        )


class ContractResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, task, left, right, project_root, context):
        self.calls += 1
        return ResolutionResult(
            selected_claim=ResolutionChoice.LEFT,
            resolved_assertion=left.assertions[0],
            rationale="pricing.py divides discount_percent by 100.",
            evidence=[
                Evidence(
                    path="pricing.py",
                    line=1,
                    detail="The implementation divides the input by 100.",
                )
            ],
            confidence=0.97,
        )


class NoCall:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        raise AssertionError("held-out task repeated the original investigation")


def reset_observer(store: Neo4jGraphStore) -> None:
    tasks = store.tasks()
    task_ids = {task.id for task in tasks if task.id.startswith(PREFIX)}
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task.parent_task_id in task_ids and task.id not in task_ids:
                task_ids.add(task.id)
                changed = True
    if not task_ids:
        return
    artifact_ids = {
        node_id
        for edge in store.edges()
        if edge.source in task_ids or edge.target in task_ids
        for node_id in (edge.source, edge.target)
        if node_id not in task_ids
    }
    store.driver.execute_query(
        "MATCH (n) WHERE n.id IN $ids DETACH DELETE n",
        ids=sorted(task_ids | artifact_ids),
    )


def run(store, project: Path, *, observer: bool) -> dict[str, object]:
    store.initialize()
    if observer:
        reset_observer(store)
    root = Task(
        id=f"{PREFIX}ROOT" if observer else "VERDICT-DEMO-ROOT",
        question="Resolve and remember discount_percent semantics.",
        fingerprint="conflict-verdict-demo-root",
        project_root=str(project.resolve()),
        status=TaskStatus.RECURSE,
    )
    store.save_task(root)

    findings = Findings()
    supervisor = Supervisor(store, findings)
    first = supervisor.run("What does discount_percent mean?", project)
    second = supervisor.run(
        "What does discount_percent mean?", project, force_investigation=True
    )
    for task in (first.task, second.task):
        task.parent_task_id = root.id
        store.save_task(task)
        store.save_edge(
            GraphEdge(source=root.id, relation=GraphRelation.SPAWNED, target=task.id)
        )

    resolver = ContractResolver()
    config = PursuitConfig(max_codex_calls=1, max_retries_per_task=1)
    pursued = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        config,
    ).pursue(second.task.id)
    verdict = store.conflict_verdicts(second.resolution_tasks[0].id)[0]

    no_call = NoCall()
    heldout = Supervisor(store, no_call).run(
        "How does discounted_price interpret discount_percent?", project
    )
    heldout.task.parent_task_id = root.id
    store.save_task(heldout.task)
    store.save_edge(
        GraphEdge(source=root.id, relation=GraphRelation.SPAWNED, target=heldout.task.id)
    )
    root.status = TaskStatus.DONE
    store.save_task(root)

    resolution_tasks = [
        task for task in store.tasks() if task.kind.value == "RESOLUTION" and task.id in {t.id for t in pursued.tasks}
    ]
    assert len(resolution_tasks) == 1
    assert resolver.calls == 1 and verdict.max_resolution_attempts == 1
    assert verdict.status.value == "RESOLVED"
    assert verdict.supporting_claim_ids == [first.claim.id]
    assert verdict.contradicting_claim_ids == [second.claim.id]
    assert heldout.cache_hit and heldout.investigation_calls == 0 and no_call.calls == 0
    assert heldout.task.reused_verdict_id == verdict.id
    return {
        "path": ["CONFLICT", "ONE_BOUNDED_RESOLVER", "VERDICT", "HELDOUT_REUSE"],
        "root_task_id": root.id,
        "resolution_tasks": len(resolution_tasks),
        "resolver_calls": resolver.calls,
        "maximum_resolution_attempts": verdict.max_resolution_attempts,
        "verdict": verdict.model_dump(mode="json"),
        "heldout_investigation_calls": heldout.investigation_calls,
        "heldout_reused_verdict_id": heldout.task.reused_verdict_id,
        "original_worker_calls": findings.calls,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j", action="store_true")
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).parent / "evidence_gap"
    if args.neo4j or args.observer:
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        result = run(store, project, observer=args.observer)
    else:
        with TemporaryDirectory(prefix="rlmgraph-verdict-") as directory:
            result = run(SQLiteGraphStore(Path(directory) / "graph.db"), project, observer=False)
            gc.collect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
