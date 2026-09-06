import pytest

from rlmgraph.project_task_graph import ProjectTaskGraph


def graph(tmp_path) -> ProjectTaskGraph:
    value = ProjectTaskGraph(tmp_path / "tasks.db")
    value.initialize([
        {"task_id": 1, "objective": "first", "acceptance": "first passes"},
        {"task_id": 2, "objective": "second", "acceptance": "second passes", "dependencies": [1]},
    ])
    return value


def test_scheduler_does_not_repeat_done_tasks_and_unlocks_dependencies(tmp_path) -> None:
    tasks = graph(tmp_path)
    first = tasks.claim_next()
    assert first is not None and first.task_id == 1
    tasks.begin_verification(first, result={"changed": True}, memory_refs=["memory-1"])
    tasks.complete(first, evidence=[{"check": "first passes", "passed": True}])

    second = tasks.claim_next()
    assert second is not None and second.task_id == 2
    assert tasks.snapshot()[0]["status"] == "DONE"
    assert tasks.snapshot()[0]["memory_refs"] == ["memory-1"]


def test_failed_task_gets_bounded_repair_then_blocks(tmp_path) -> None:
    tasks = graph(tmp_path)
    first = tasks.claim_next(max_attempts=2)
    assert first is not None
    tasks.begin_verification(first, result={}, memory_refs=[])
    tasks.fail(first, reason="check failed", evidence=[{"passed": False}])
    repair = tasks.claim_next(max_attempts=2)
    assert repair is not None and repair.task_id == 1 and repair.attempt == 2
    assert repair.prior_failure == "check failed"
    tasks.begin_verification(repair, result={}, memory_refs=[])
    tasks.fail(repair, reason="still failed", evidence=[{"passed": False}])
    assert tasks.block_exhausted(max_attempts=2) == 1
    assert tasks.claim_next(max_attempts=2) is None


def test_completion_requires_evidence_and_leases_are_enforced(tmp_path) -> None:
    tasks = graph(tmp_path)
    lease = tasks.claim_next()
    assert lease is not None
    with pytest.raises(ValueError):
        tasks.complete(lease, evidence=[])
    tasks.begin_verification(lease, result={}, memory_refs=[])
    tasks.complete(lease, evidence=[{"passed": True}])
    with pytest.raises(RuntimeError):
        tasks.complete(lease, evidence=[{"passed": True}])


def test_state_persists_and_done_tasks_can_be_explicitly_invalidated(tmp_path) -> None:
    tasks = graph(tmp_path)
    lease = tasks.claim_next()
    assert lease is not None
    tasks.begin_verification(lease, result={}, memory_refs=[])
    tasks.complete(lease, evidence=[{"passed": True}])
    reopened = ProjectTaskGraph(tmp_path / "tasks.db")
    assert reopened.progress()["DONE"] == 1
    reopened.invalidate(1, "regression")
    assert reopened.snapshot()[0]["status"] == "INVALIDATED"
    repair = reopened.claim_next()
    assert repair is not None and repair.task_id == 1


def test_invalidation_propagates_and_interrupted_leases_recover(tmp_path) -> None:
    tasks = graph(tmp_path)
    first = tasks.claim_next()
    assert first is not None
    tasks.begin_verification(first, result={}, memory_refs=[])
    tasks.complete(first, evidence=[{"passed": True}])
    second = tasks.claim_next()
    assert second is not None
    tasks.begin_verification(second, result={}, memory_refs=[])
    tasks.complete(second, evidence=[{"passed": True}])
    tasks.invalidate(1, "contract changed")
    assert [task["status"] for task in tasks.snapshot()] == ["INVALIDATED", "INVALIDATED"]

    repair = tasks.claim_next()
    assert repair is not None and repair.task_id == 1
    assert tasks.recover_interrupted() == 1
    recovered = tasks.claim_next()
    assert recovered is not None and recovered.task_id == 1


def test_final_evidence_can_reconcile_a_blocked_task_without_another_attempt(tmp_path) -> None:
    tasks = graph(tmp_path)
    lease = tasks.claim_next(max_attempts=1)
    assert lease is not None
    tasks.begin_verification(lease, result={}, memory_refs=[])
    tasks.fail(lease, reason="initial check failed", evidence=[{"passed": False}])
    tasks.block_exhausted(max_attempts=1)

    assert tasks.reconcile_complete(
        1, evidence={"kind": "final_validation", "passed": True}
    )
    assert tasks.snapshot()[0]["status"] == "DONE"
    assert tasks.snapshot()[0]["attempt_count"] == 1
