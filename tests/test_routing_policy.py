from pathlib import Path

from rlmgraph.execution import AdaptiveInvestigator, ExecutionLedger, WorkerSpec
from rlmgraph.models import (
    ExecutionOutcome,
    InvestigationResult,
    Task,
    TaskKind,
    TaskRoute,
)
from rlmgraph.routing_policy import LearnedRoutingPolicy, RoutingPolicyConfig
from rlmgraph.store import SQLiteGraphStore


class CountingWorker:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(conclusion="correct", confidence=self.confidence)


def task(store: SQLiteGraphStore, project: Path, name: str) -> Task:
    item = Task(
        question=f"Classify difficult contract {name}",
        fingerprint=f"routing-{name}",
        project_fingerprint="routing-fixture",
        project_root=str(project.resolve()),
        kind=TaskKind.FOLLOW_UP,
        difficulty=0.6,
        uncertainty=0.9,
        route=TaskRoute.LOCAL_MODEL,
    )
    store.save_task(item)
    return item


def seed_history(store: SQLiteGraphStore, project: Path) -> None:
    ledger = ExecutionLedger(store)
    for index in range(3):
        item = task(store, project, f"training-{index}")
        ledger.record(
            item,
            planned_route=TaskRoute.LOCAL_MODEL,
            actual_route=TaskRoute.LOCAL_MODEL,
            worker="LocalModel",
            outcome=ExecutionOutcome.LOW_CONFIDENCE,
            input_tokens=10,
            output_tokens=10,
            estimated_cost_usd=0.00001,
            latency_ms=10,
            confidence=0.3,
        )
        ledger.record(
            item,
            planned_route=TaskRoute.LOCAL_MODEL,
            actual_route=TaskRoute.CODEX,
            worker="Codex",
            outcome=ExecutionOutcome.SUCCEEDED,
            input_tokens=10,
            output_tokens=20,
            estimated_cost_usd=0.001,
            latency_ms=100,
            confidence=0.95,
        )


def test_policy_requires_evidence_then_versions_route_change(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    local = CountingWorker(0.3)
    codex = CountingWorker(0.95)
    workers = {
        TaskRoute.LOCAL_MODEL: WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel"),
        TaskRoute.CODEX: WorkerSpec(TaskRoute.CODEX, codex, "Codex"),
    }
    policy = LearnedRoutingPolicy(store, RoutingPolicyConfig(minimum_evidence=3))
    before = task(store, tmp_path, "before-training")

    baseline = policy.predict(before, workers, TaskRoute.LOCAL_MODEL, {"max_calls": 2})

    assert baseline.chosen_route == TaskRoute.LOCAL_MODEL
    assert baseline.policy_version == 0
    assert not baseline.changed_static_route
    assert store.routing_policy_updates() == []

    seed_history(store, tmp_path)
    held_out = task(store, tmp_path, "held-out")
    learned = policy.predict(held_out, workers, TaskRoute.LOCAL_MODEL, {"max_calls": 2})

    assert learned.chosen_route == TaskRoute.CODEX
    assert learned.changed_static_route
    assert learned.policy_version == 1
    local_profile = next(c for c in learned.candidates if c.route == TaskRoute.LOCAL_MODEL)
    codex_profile = next(c for c in learned.candidates if c.route == TaskRoute.CODEX)
    assert local_profile.sample_count == 3 and not local_profile.eligible
    assert local_profile.calibration_error == 0.3
    assert codex_profile.sample_count == 3 and codex_profile.eligible
    assert codex_profile.predicted_success_probability == 0.8
    update = store.routing_policy_updates()[0]
    assert update.version == 1 and update.previous_version == 0
    assert update.evidence_execution_ids == codex_profile.evidence_execution_ids
    assert update.fixed_safety_limits == {"max_calls": 2}

    ledger = ExecutionLedger(store)
    for index in range(11):
        recovered = task(store, tmp_path, f"local-recovery-{index}")
        ledger.record(
            recovered,
            planned_route=TaskRoute.LOCAL_MODEL,
            actual_route=TaskRoute.LOCAL_MODEL,
            worker="LocalModel",
            outcome=ExecutionOutcome.SUCCEEDED,
            input_tokens=10,
            output_tokens=10,
            estimated_cost_usd=0.00001,
            latency_ms=10,
            confidence=0.95,
        )
    reversal_task = task(store, tmp_path, "reversal")
    reversal = policy.predict(
        reversal_task, workers, TaskRoute.LOCAL_MODEL, {"max_calls": 2}
    )
    updates = store.routing_policy_updates()
    assert reversal.chosen_route == TaskRoute.LOCAL_MODEL
    assert reversal.policy_version == 2
    assert updates[-1].from_route == TaskRoute.CODEX
    assert updates[-1].to_route == TaskRoute.LOCAL_MODEL


def test_held_out_task_routes_directly_to_learned_worker_and_self_evaluates(
    tmp_path: Path,
) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    seed_history(store, tmp_path)
    held_out = task(store, tmp_path, "held-out")
    local = CountingWorker(0.3)
    codex = CountingWorker(0.98)
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel", 0.1, 0.2),
            WorkerSpec(TaskRoute.CODEX, codex, "Codex", 2.0, 8.0),
        ],
    )

    result = adaptive.investigate(held_out.question, tmp_path)

    assert result.confidence == 0.98
    assert local.calls == 0 and codex.calls == 1
    prediction = store.route_predictions(held_out.id)[0]
    attempt = store.execution_attempts(held_out.id)[0]
    evaluation = store.route_evaluations()[0]
    assert prediction.chosen_route == TaskRoute.CODEX
    assert attempt.actual_route == TaskRoute.CODEX
    assert attempt.route_prediction_id == prediction.id
    assert evaluation.prediction_id == prediction.id
    assert evaluation.actual_success
    assert evaluation.worker_calls == 1
    assert evaluation.fallback_count == 0
    assert evaluation.actual_final_route == TaskRoute.CODEX
    relations = {edge.relation.value for edge in store.edges()}
    assert {"HAS_ROUTE_PREDICTION", "PREDICTED_EXECUTION", "EVALUATES_PREDICTION"} <= relations
