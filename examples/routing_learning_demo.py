"""Prove evidence-gated routing learning and held-out self-evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rlmgraph.execution import AdaptiveInvestigator, ExecutionLedger, WorkerSpec
from rlmgraph.followup import FollowUpExecutor
from rlmgraph.models import (
    ExecutionOutcome,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    Task,
    TaskKind,
    TaskRoute,
    TaskStatus,
)
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore

PREFIX = "ROUTING-LEARNING-"


class LearningLocal:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The local result remains uncertain.",
            confidence=0.3,
            unresolved_questions=["Escalate for authoritative repository evidence."],
        )


class LearningCodex:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The authoritative contract selects alpha.",
            confidence=0.98,
            files_examined=["contract.txt"],
        )


def make_task(store, root: Task, project: Path, suffix: str) -> Task:
    item = Task(
        id=f"{PREFIX}{suffix}",
        question=f"Resolve medium-difficulty routing case {suffix}.",
        fingerprint=f"routing-learning-{suffix}",
        project_fingerprint=root.project_fingerprint,
        project_root=str(project.resolve()),
        kind=TaskKind.FOLLOW_UP,
        parent_task_id=root.id,
        difficulty=0.6,
        uncertainty=0.9,
        route=TaskRoute.LOCAL_MODEL,
    )
    store.save_task(item)
    store.save_edge(GraphEdge(source=root.id, relation=GraphRelation.SPAWNED, target=item.id))
    return item


def clear_neo4j(store: Neo4jGraphStore) -> None:
    store.driver.execute_query(
        "MATCH (prediction:RoutePrediction)-[:EVALUATES_PREDICTION]->"
        "(evaluation:RouteEvaluation) WHERE prediction.task_id STARTS WITH $prefix "
        "DETACH DELETE evaluation",
        prefix=PREFIX,
    )
    for label, property_name in (
        ("RoutePrediction", "task_id"),
        ("ExecutionAttempt", "task_id"),
        ("RoutingPolicyUpdate", "triggering_task_id"),
    ):
        store.driver.execute_query(
            f"MATCH (node:{label}) WHERE node.{property_name} STARTS WITH $prefix "
            "DETACH DELETE node",
            prefix=PREFIX,
        )
    store.driver.execute_query(
        "MATCH (task:Task) WHERE task.id STARTS WITH $prefix DETACH DELETE task",
        prefix=PREFIX,
    )


def run(store, project: Path, root: Task) -> dict:
    ledger = ExecutionLedger(store)
    for index in range(3):
        training = make_task(store, root, project, f"TRAIN-{index}")
        ledger.record(
            training,
            planned_route=TaskRoute.LOCAL_MODEL,
            actual_route=TaskRoute.LOCAL_MODEL,
            worker="LearningLocal",
            outcome=ExecutionOutcome.LOW_CONFIDENCE,
            input_tokens=12,
            output_tokens=18,
            estimated_cost_usd=0.00001,
            latency_ms=8,
            confidence=0.3,
        )
        ledger.record(
            training,
            planned_route=TaskRoute.LOCAL_MODEL,
            actual_route=TaskRoute.CODEX,
            worker="LearningCodex",
            outcome=ExecutionOutcome.SUCCEEDED,
            input_tokens=12,
            output_tokens=28,
            estimated_cost_usd=0.001,
            latency_ms=90,
            confidence=0.98,
            fallback_reason="Static policy required escalation.",
        )
        training.status = TaskStatus.DONE
        store.save_task(training)

    held_out = make_task(store, root, project, "HELD-OUT")
    local = LearningLocal()
    codex = LearningCodex()
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LearningLocal", 0.05, 0.1),
            WorkerSpec(TaskRoute.CODEX, codex, "LearningCodex", 2.0, 8.0),
        ],
    )
    adaptive.configure_budget(max_calls=2, max_retrieval_tokens=2000)
    FollowUpExecutor(store, adaptive).execute(held_out.id)
    prediction = store.route_predictions(held_out.id)[0]
    evaluation = next(
        item for item in store.route_evaluations() if item.prediction_id == prediction.id
    )
    update = next(
        item
        for item in store.routing_policy_updates()
        if item.triggering_task_id == held_out.id
    )
    result = {
        "policy_version": update.version,
        "training_examples_per_worker": 3,
        "minimum_evidence": update.minimum_evidence,
        "required_success_probability": update.required_success_probability,
        "static_route": prediction.static_route.value,
        "learned_route": prediction.chosen_route.value,
        "local_calls": local.calls,
        "codex_calls": codex.calls,
        "static_baseline_worker_calls": 2,
        "learned_worker_calls": evaluation.worker_calls,
        "worker_calls_saved": 2 - evaluation.worker_calls,
        "correctness_preserved": evaluation.actual_success,
        "fallbacks": evaluation.fallback_count,
        "predicted_cost_usd": evaluation.predicted_cost_usd,
        "actual_cost_usd": evaluation.actual_cost_usd,
        "predicted_latency_ms": evaluation.predicted_latency_ms,
        "actual_latency_ms": evaluation.actual_latency_ms,
        "evidence_execution_ids": update.evidence_execution_ids,
        "fixed_safety_limits": update.fixed_safety_limits,
    }
    assert result["static_route"] == "LOCAL_MODEL"
    assert result["learned_route"] == "CODEX"
    assert result["local_calls"] == 0 and result["codex_calls"] == 1
    assert result["worker_calls_saved"] == 1 and result["fallbacks"] == 0
    assert result["correctness_preserved"]
    assert len(result["evidence_execution_ids"]) == 3
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "neo4j"), default="sqlite")
    parser.add_argument("--observer", action="store_true")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="rlmgraph-demo")
    args = parser.parse_args()
    project = Path(__file__).parent / "planner_fixture"
    if args.backend == "neo4j":
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        store.initialize()
        clear_neo4j(store)
        root_id = "LIVE-DEMO-ROOT" if args.observer else f"{PREFIX}ROOT"
        root = store.get_task(root_id)
        if root is None:
            root = Task(
                id=root_id,
                question="Routing-learning fixture root",
                fingerprint="routing-learning-root",
                project_fingerprint="routing-learning-fixture",
                project_root=str(project.resolve()),
                status=TaskStatus.DONE,
            )
            store.save_task(root)
    else:
        database = project / "routing-learning-demo.db"
        database.unlink(missing_ok=True)
        store = SQLiteGraphStore(database)
        store.initialize()
        root = Task(
            id=f"{PREFIX}ROOT",
            question="Routing-learning fixture root",
            fingerprint="routing-learning-root",
            project_fingerprint="routing-learning-fixture",
            project_root=str(project.resolve()),
            status=TaskStatus.DONE,
        )
        store.save_task(root)
    print(json.dumps({"backend": args.backend, "result": run(store, project, root)}, indent=2))


if __name__ == "__main__":
    main()
