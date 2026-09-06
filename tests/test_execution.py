from pathlib import Path

from rlmgraph.execution import AdaptiveInvestigator, WorkerSpec
from rlmgraph.followup import FollowUpExecutor
from rlmgraph.models import (
    ExecutionOutcome,
    InvestigationResult,
    Task,
    TaskKind,
    TaskRoute,
)
from rlmgraph.store import SQLiteGraphStore


class ResultWorker:
    def __init__(self, confidence: float, unresolved: bool = False) -> None:
        self.confidence = confidence
        self.unresolved = unresolved
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion=f"{type(self).__name__} answered {question}",
            confidence=self.confidence,
            unresolved_questions=["Need stronger evidence"] if self.unresolved else [],
        )


class FailingWorker:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        raise RuntimeError("local worker unavailable")


def follow_up(store: SQLiteGraphStore, project: Path, route: TaskRoute) -> Task:
    task = Task(
        question=f"Investigate with {route.value}",
        fingerprint=f"fingerprint-{route.value}",
        project_fingerprint="fixture-state",
        project_root=str(project.resolve()),
        kind=TaskKind.FOLLOW_UP,
        route=route,
    )
    store.save_task(task)
    return task


def test_planned_local_route_executes_local_worker_and_persists_metrics(
    tmp_path: Path,
) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = follow_up(store, tmp_path, TaskRoute.LOCAL_MODEL)
    local = ResultWorker(0.92)
    codex = ResultWorker(0.99)
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel", 0.1, 0.2),
            WorkerSpec(TaskRoute.CODEX, codex, "Codex", 2.0, 8.0),
        ],
    )

    FollowUpExecutor(store, adaptive).execute(task.id)

    attempts = store.execution_attempts(task.id)
    assert local.calls == 1 and codex.calls == 0
    assert len(attempts) == 1
    assert attempts[0].planned_route == TaskRoute.LOCAL_MODEL
    assert attempts[0].actual_route == TaskRoute.LOCAL_MODEL
    assert attempts[0].worker == "LocalModel"
    assert attempts[0].outcome == ExecutionOutcome.SUCCEEDED
    assert attempts[0].total_tokens > 0
    assert attempts[0].estimated_cost_usd > 0
    assert attempts[0].latency_ms >= 0
    assert attempts[0].confidence == 0.92


def test_weak_local_result_falls_back_to_codex_with_linked_reason(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = follow_up(store, tmp_path, TaskRoute.LOCAL_MODEL)
    local = ResultWorker(0.3, unresolved=True)
    codex = ResultWorker(0.97)
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel"),
            WorkerSpec(TaskRoute.CODEX, codex, "Codex"),
        ],
    )

    executor = FollowUpExecutor(store, adaptive)
    executor.execute(task.id)

    attempts = store.execution_attempts(task.id)
    assert executor.follow_up_calls == 2
    assert [attempt.actual_route for attempt in attempts] == [
        TaskRoute.LOCAL_MODEL,
        TaskRoute.CODEX,
    ]
    assert [attempt.outcome for attempt in attempts] == [
        ExecutionOutcome.LOW_CONFIDENCE,
        ExecutionOutcome.SUCCEEDED,
    ]
    assert attempts[1].fallback_from_attempt_id == attempts[0].id
    assert "confidence 0.300" in attempts[1].fallback_reason
    assert any(edge.relation.value == "FALLBACK_TO" for edge in store.edges())


def test_failed_local_worker_falls_back_to_codex(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = follow_up(store, tmp_path, TaskRoute.LOCAL_MODEL)
    local = FailingWorker()
    codex = ResultWorker(0.96)
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel"),
            WorkerSpec(TaskRoute.CODEX, codex, "Codex"),
        ],
    )

    FollowUpExecutor(store, adaptive).execute(task.id)

    attempts = store.execution_attempts(task.id)
    assert attempts[0].outcome == ExecutionOutcome.FAILED
    assert attempts[0].error == "local worker unavailable"
    assert attempts[1].actual_route == TaskRoute.CODEX
    assert attempts[1].fallback_from_attempt_id == attempts[0].id


def test_planned_codex_route_bypasses_local_worker(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = follow_up(store, tmp_path, TaskRoute.CODEX)
    local = ResultWorker(0.99)
    codex = ResultWorker(0.98)
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel"),
            WorkerSpec(TaskRoute.CODEX, codex, "Codex"),
        ],
    )

    FollowUpExecutor(store, adaptive).execute(task.id)

    attempt = store.execution_attempts(task.id)[0]
    assert local.calls == 0 and codex.calls == 1
    assert attempt.planned_route == attempt.actual_route == TaskRoute.CODEX


def test_fallback_never_exceeds_configured_worker_call_budget(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = follow_up(store, tmp_path, TaskRoute.LOCAL_MODEL)
    local = ResultWorker(0.2, unresolved=True)
    codex = ResultWorker(0.99)
    adaptive = AdaptiveInvestigator(
        store,
        [
            WorkerSpec(TaskRoute.LOCAL_MODEL, local, "LocalModel"),
            WorkerSpec(TaskRoute.CODEX, codex, "Codex"),
        ],
    )
    adaptive.configure_budget(max_calls=1, max_retrieval_tokens=1000)

    result = adaptive.investigate(task.question, tmp_path)

    assert result.confidence == 0.2
    assert local.calls == 1 and codex.calls == 0
    assert adaptive.last_call_count == 1
    assert len(store.execution_attempts(task.id)) == 1
