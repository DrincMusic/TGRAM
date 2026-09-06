from __future__ import annotations

from pathlib import Path

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.evaluation import DeterministicEvaluationHarness
from rlmgraph.models import EvaluationScenario, EvaluationStrategy
from rlmgraph.store import SQLiteGraphStore


def test_deterministic_three_strategy_evaluation_passes_every_gate(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "evaluation.db")
    run = DeterministicEvaluationHarness(store, tmp_path / "fixture", repetitions=2).run()

    assert run.passed is True
    assert run.correctness_preserved is True
    assert run.evidence_preserved is True
    assert run.fewer_repeat_worker_calls is True
    assert run.fewer_tokens_than_static is True
    assert run.stale_or_conflicting_memory_blocked is True
    assert run.recovery_verified is True
    assert run.reproducible is True
    assert len(run.results) == 15
    assert {item.strategy for item in run.results} == set(EvaluationStrategy)
    assert {item.scenario for item in run.results} == set(EvaluationScenario)

    repeated = [
        item for item in run.results
        if item.scenario == EvaluationScenario.REPEATED_DEBUGGING
        and item.repetition == 2
    ]
    by_strategy = {item.strategy: item for item in repeated}
    assert by_strategy[EvaluationStrategy.MEMORYLESS].worker_calls > 0
    assert by_strategy[EvaluationStrategy.MEMORYLESS].duplicate_investigations > 0
    assert by_strategy[EvaluationStrategy.RLMGRAPH].worker_calls == 0
    assert by_strategy[EvaluationStrategy.RLMGRAPH].model_calls == 0
    assert by_strategy[EvaluationStrategy.RLMGRAPH].memory_reuses > 0
    assert (
        by_strategy[EvaluationStrategy.RLMGRAPH].retrieved_tokens
        < by_strategy[EvaluationStrategy.STATIC_RETRIEVAL].retrieved_tokens
    )

    conflict = [
        item for item in run.results
        if item.scenario == EvaluationScenario.CONFLICT and item.repetition == 2
    ]
    conflict_by_strategy = {item.strategy: item for item in conflict}
    assert conflict_by_strategy[EvaluationStrategy.RLMGRAPH].conflict_resolved is True
    assert "EVAL-CONFLICT-STALE" not in conflict_by_strategy[
        EvaluationStrategy.RLMGRAPH
    ].retrieved_claim_ids
    assert conflict_by_strategy[EvaluationStrategy.STATIC_RETRIEVAL].correct is False
    assert conflict_by_strategy[EvaluationStrategy.STATIC_RETRIEVAL].conflict_resolved is False

    persisted = SQLiteGraphStore(store.path).evaluation_runs()
    assert persisted == [run]
    snapshot = build_dashboard_snapshot(SQLiteGraphStore(store.path))
    assert snapshot["metrics"]["evaluation_runs"] == 1
    assert snapshot["metrics"]["passed_evaluation_runs"] == 1
    assert snapshot["metrics"]["evaluation_results"] == 15
    assert any(node["node_type"] == "evaluation_run" for node in snapshot["nodes"])
    assert sum(node["node_type"] == "evaluation_result" for node in snapshot["nodes"]) == 15


def test_two_isolated_runs_have_identical_logical_results(tmp_path: Path) -> None:
    first = DeterministicEvaluationHarness(
        SQLiteGraphStore(tmp_path / "first.db"), tmp_path / "first"
    ).run()
    second = DeterministicEvaluationHarness(
        SQLiteGraphStore(tmp_path / "second.db"), tmp_path / "second"
    ).run()

    assert first.passed and second.passed
    fields = {
        "id",
        "run_id",
        "created_at",
        "observed_latency_ms",
    }
    assert [item.model_dump(exclude=fields) for item in first.results] == [
        item.model_dump(exclude=fields) for item in second.results
    ]
