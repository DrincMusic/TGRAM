from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.implementation_sandbox import (
    ImplementationSandboxManager,
    InteractiveSandboxController,
)
from rlmgraph.interactive_workspace import InteractiveProjectWorkspaceController
from rlmgraph.models import Claim, ProjectLeaseStatus, RepairWorkerResult, Task, TicketBudget
from rlmgraph.models import TestExecution as ExecutionRecord
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.reconciliation import SandboxPromotionReconciler
from rlmgraph.scheduler import ResourceAwareScheduler
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


class ChangeWorker:
    def __init__(self):
        self.roots = []
        self.files_seen = []

    def implement(self, request, evidence, sandbox_root):
        self.roots.append(sandbox_root.resolve())
        self.files_seen.append(sorted(item.relative_to(sandbox_root).as_posix() for item in sandbox_root.rglob("*") if item.is_file()))
        target = sandbox_root / "src" / "service.py"
        target.write_text(target.read_text(encoding="utf-8").replace("* 2", "* 3"), encoding="utf-8")
        test = sandbox_root / "tests" / "test_service.py"
        test.write_text(test.read_text(encoding="utf-8").replace("== 4", "== 6"), encoding="utf-8")
        return RepairWorkerResult(
            rationale="Implement the approved multiplier change.",
            confidence=0.99,
            files_changed=["src/service.py", "tests/test_service.py"],
            file_change_reasons={"src/service.py": "Use the requested multiplier.", "tests/test_service.py": "Verify the new expected result."},
        )


class OutsideWorker:
    def implement(self, request, evidence, sandbox_root):
        (sandbox_root / "unauthorized.py").write_text("BAD = True\n", encoding="utf-8")
        return RepairWorkerResult(
            rationale="Unauthorized expansion.", confidence=0.99,
            files_changed=["unauthorized.py"],
        )


class ReportedOutsideReadWorker:
    def implement(self, request, evidence, sandbox_root):
        return RepairWorkerResult(
            rationale="Report a read outside the capability slice.",
            confidence=0.99,
            files_read=["../secret.txt"],
            files_changed=[],
        )


class SourceOnlyWorker:
    def implement(self, request, evidence, sandbox_root):
        target = sandbox_root / "src" / "service.py"
        target.write_text(
            target.read_text(encoding="utf-8").replace("value * 2", "value + value"),
            encoding="utf-8",
        )
        return RepairWorkerResult(
            rationale="Change only the implementation.",
            confidence=0.99,
            files_changed=["src/service.py"],
        )


def fixture(tmp_path: Path):
    root = tmp_path / "Project"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src/service.py").write_text(
        "def calculate(value):\n    return value * 2\n", encoding="utf-8"
    )
    (root / "src/unrelated.py").write_text("UNCHANGED = True\n", encoding="utf-8")
    (root / "tests/test_service.py").write_text(
        "from src.service import calculate\n\ndef test_value():\n    assert calculate(2) == 4\n",
        encoding="utf-8",
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    project = store.projects()[0]
    tickets = TicketManager(store)
    ticket = tickets.create(
        project_id=project.id,
        title="Change multiplier",
        description="Prepare a reviewable multiplier patch.",
        acceptance_criteria=["A reviewable diff is produced."],
        constraints=["Do not modify registered source."],
        priority="MEDIUM",
        dependency_ticket_ids=[],
        budget=TicketBudget(max_worker_calls=5, max_model_calls=2),
        created_by="test",
    )
    controller = InteractiveProjectWorkspaceController(store)
    controller.start_change_plan(
        project.id,
        "Change calculate to multiply by three.",
        ["The proposed change is reviewable."],
        ticket.id,
    )
    import time

    deadline = time.monotonic() + 5
    while controller.snapshot()["status"] not in {"COMPLETED", "FAILED"}:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    plan = store.project_workspace_records()[0]
    return root, store, tickets, ticket, plan


def tree(root: Path):
    return {
        item.relative_to(root).as_posix(): item.read_bytes()
        for item in root.rglob("*")
        if item.is_file()
    }


def test_approved_plan_runs_only_in_disposable_authorized_mirror(tmp_path: Path) -> None:
    root, store, tickets, ticket, plan = fixture(tmp_path)
    original = tree(root)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Authorized paths reviewed.")

    worker = ChangeWorker()
    attempt = ImplementationSandboxManager(store, worker).run(ticket.id, plan.id)

    assert attempt.status == "READY_FOR_REVIEW"
    assert attempt.filesystem_disposed and attempt.original_unchanged
    assert tree(root) == original
    assert all(not worker_root.is_relative_to(root) for worker_root in worker.roots)
    assert worker.files_seen == [sorted(plan.affected_paths)]
    assert [change.path for change in attempt.changes] == [
        "src/service.py", "tests/test_service.py"
    ]
    assert "-    return value * 2" in attempt.changes[0].unified_diff
    assert "+    return value * 3" in attempt.changes[0].unified_diff
    assert attempt.changes[0].change_reason == "Use the requested multiplier."
    assert store.implementation_sandboxes(ticket.id)[0].changes[0].change_reason == "Use the requested multiplier."
    assert attempt.execution_authorized is False
    assert attempt.validations and all(item.exit_code == 0 for item in attempt.validations)
    assert attempt.validations[0].command[3] == "tests/test_service.py"
    assert [item.stage for item in attempt.checkpoints] == [
        "CREATED", "ISOLATED", "PATCH_CAPTURED", "VALIDATION_ROUTED", "VALIDATED", "DISPOSED"
    ]
    assert {item.path: item.status for item in attempt.validation_decisions} == {
        "src/service.py": "REQUIRED",
        "tests/test_service.py": "PASSED",
    }
    assert attempt.validation_evidence
    assert attempt.validation_worker_executions[0].worker_id == "BUILTIN-PYTHON-PYTEST"
    assert attempt.validation_worker_executions[0].status == "PASSED"
    assert store.implementation_sandboxes(ticket.id)[0].id == attempt.id
    updated = tickets.get(ticket.id)
    assert updated.usage.worker_calls == 2
    assert updated.usage.model_calls == 1
    assert updated.execution_authorized is False
    assert any(event.kind == "SANDBOX_ATTEMPT_ATTACHED" for event in store.ticket_events(ticket.id))
    reopened = SQLiteGraphStore(tmp_path / "graph.db")
    assert reopened.implementation_sandboxes(ticket.id)[0].changes == attempt.changes
    snapshot = build_dashboard_snapshot(store, running=False)
    node = next(item for item in snapshot["nodes"] if item["id"] == attempt.id)
    assert node["node_type"] == "implementation_sandbox"
    assert snapshot["metrics"]["reviewable_sandbox_patches"] == 1
    assert node["validation_decisions"][1]["execution_index"] == 0


def test_interactive_sandbox_runs_through_durable_scheduler(tmp_path: Path) -> None:
    root, store, tickets, ticket, plan = fixture(tmp_path)
    original = tree(root)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Authorized paths reviewed.")
    scheduler = ResourceAwareScheduler(store)
    controller = InteractiveSandboxController(
        ImplementationSandboxManager(store, ChangeWorker()), scheduler=scheduler
    )
    controller.start(ticket.id, plan.id)
    import time

    deadline = time.monotonic() + 15
    while controller.snapshot()["status"] not in {"READY_FOR_REVIEW", "FAILED", "CANCELLED"}:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    state = controller.snapshot()
    scheduled = store.scheduled_work()[0]
    assert state["status"] == "READY_FOR_REVIEW"
    assert scheduled.status == "COMPLETED"
    assert scheduled.evidence_ids == [state["attempt_id"]]
    assert scheduled.checkpoints[-1].stage == "COMPLETED"
    assert tree(root) == original

def test_artifact_aware_validation_routes_cover_unreal_and_python_types(tmp_path: Path) -> None:
    _, store, _, _, _ = fixture(tmp_path)
    manager = ImplementationSandboxManager(store, ChangeWorker())
    paths = [
        "Source/Game/Actor.cpp",
        "Source/Game/Actor.h",
        "Source/Game/Game.Build.cs",
        "Content/Blueprints/BP_Actor.uasset",
        "Content/Maps/Arena.umap",
        "Content/Meshes/Tree.uasset",
        "Config/DefaultGame.ini",
        "tools/generate.py",
        "tests/test_generate.py",
    ]
    commands = [["python", "-m", "pytest", "tests/test_generate.py"]]

    decisions = manager._validation_decisions(store.projects()[0].id, paths, commands)
    by_path = {item.path: item for item in decisions}

    assert by_path["Source/Game/Actor.cpp"].category == "COMPILE"
    assert by_path["Source/Game/Actor.h"].category == "COMPILE"
    assert by_path["Source/Game/Game.Build.cs"].artifact_kind == "MODULE_RULES"
    for path in [
        "Content/Blueprints/BP_Actor.uasset",
        "Content/Maps/Arena.umap",
        "Content/Meshes/Tree.uasset",
        "Config/DefaultGame.ini",
    ]:
        assert by_path[path].requires_unreal_editor
        assert by_path[path].status == "REQUIRED"
    assert by_path["tools/generate.py"].category == "PYTHON_TEST"
    assert by_path["tools/generate.py"].status == "REQUIRED"
    assert by_path["tests/test_generate.py"].status == "PENDING"
    assert all(item.evidence and item.evidence[0].path == item.path for item in decisions)


def test_unapproved_or_stale_plan_cannot_start(tmp_path: Path) -> None:
    root, store, tickets, ticket, plan = fixture(tmp_path)
    with pytest.raises(ValueError, match="explicit plan approval"):
        ImplementationSandboxManager(store, ChangeWorker()).run(ticket.id, plan.id)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Reviewed.")
    (root / "src/service.py").write_text("CHANGED = True\n", encoding="utf-8")
    with pytest.raises(Exception, match="changed after planning"):
        ImplementationSandboxManager(store, ChangeWorker()).run(ticket.id, plan.id)
    assert not store.implementation_sandboxes(ticket.id)


def test_unauthorized_worker_change_fails_and_is_discarded_without_source_write(
    tmp_path: Path,
) -> None:
    root, store, tickets, ticket, plan = fixture(tmp_path)
    original = tree(root)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Reviewed.")

    attempt = ImplementationSandboxManager(store, OutsideWorker()).run(ticket.id, plan.id)

    assert attempt.status == "FAILED"
    assert "unauthorized.py" in (attempt.failure_reason or "")
    assert attempt.filesystem_disposed and attempt.original_unchanged
    assert tree(root) == original
    discarded = ImplementationSandboxManager(store, OutsideWorker()).discard(
        ticket.id, attempt.id
    )
    assert discarded.status == "DISCARDED" and discarded.discarded_at
    assert tree(root) == original


def test_worker_reported_read_outside_authorized_slice_fails_closed(tmp_path: Path) -> None:
    root, store, tickets, ticket, plan = fixture(tmp_path)
    original = tree(root)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Reviewed.")

    attempt = ImplementationSandboxManager(store, ReportedOutsideReadWorker()).run(ticket.id, plan.id)

    assert attempt.status == "FAILED"
    assert "reported reads outside authorized paths" in (attempt.failure_reason or "")
    assert attempt.original_unchanged and tree(root) == original


def test_ticket_budget_blocks_worker_before_sandbox_creation(tmp_path: Path) -> None:
    root, store, tickets, ticket, plan = fixture(tmp_path)
    original = tree(root)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Reviewed.")
    ticket = tickets.get(ticket.id)
    ticket.budget.max_worker_calls = 0
    store.save_project_ticket(ticket)

    with pytest.raises(RuntimeError, match="worker-call"):
        ImplementationSandboxManager(store, ChangeWorker()).run(ticket.id, plan.id)

    assert not store.implementation_sandboxes(ticket.id)
    assert tree(root) == original


def reviewable_attempt(tmp_path: Path):
    root, store, tickets, ticket, plan = fixture(tmp_path)
    tickets.approve_plan(ticket.id, plan.id, actor="planner", reason="Plan reviewed.")
    manager = ImplementationSandboxManager(store, ChangeWorker())
    attempt = manager.run(ticket.id, plan.id)
    return root, store, tickets, ticket, plan, manager, attempt


def satisfy_manual_gates(manager, ticket, attempt):
    for decision in attempt.validation_decisions:
        if decision.status == "REQUIRED":
            if decision.category == "PYTHON_TEST":
                attempt = manager.run_validation_worker(
                    ticket.id, attempt.id, decision.id, "BUILTIN-PYTHON-SYNTAX"
                )
            else:
                attempt = manager.satisfy_validation(
                    ticket.id,
                    attempt.id,
                    decision.id,
                    actor="validator",
                    detail=f"Reviewed {decision.path} against the required validation procedure.",
                )
    return attempt


def test_promotion_approval_is_separate_and_requires_every_validation_gate(tmp_path: Path) -> None:
    root, store, _, ticket, plan, manager, attempt = reviewable_attempt(tmp_path)
    original = tree(root)

    with pytest.raises(ValueError, match="every validation"):
        manager.approve_promotion(
            ticket.id, attempt.id, actor="promoter", reason="Ready.", decision="APPROVED"
        )

    attempt = satisfy_manual_gates(manager, ticket, attempt)
    attempt = manager.approve_promotion(
        ticket.id,
        attempt.id,
        actor="promoter",
        reason="Exact diff and all validation evidence reviewed.",
        decision="APPROVED",
    )

    persisted_plan = next(item for item in store.project_workspace_records() if item.id == plan.id)
    assert persisted_plan.approval_status == "APPROVED"
    assert attempt.promotion_approval is not None
    assert attempt.promotion_approval.approved_by == "promoter"
    assert attempt.promotion_approval.id != plan.id
    assert attempt.promotion is None
    assert tree(root) == original


def test_approved_promotion_applies_exact_paths_with_bounded_validation_and_lease_history(
    tmp_path: Path,
) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(
        ticket.id, attempt.id, actor="promoter", reason="Validated patch approved."
    )

    promoted = manager.promote(ticket.id, attempt.id)

    assert promoted.status == "PROMOTED"
    assert "return value * 3" in (root / "src/service.py").read_text()
    assert "== 6" in (root / "tests/test_service.py").read_text()
    assert promoted.promotion is not None
    assert promoted.promotion.status == "PROMOTED"
    assert promoted.promotion.validations[0].exit_code == 0
    assert promoted.promotion.rollback_verified is None
    assert promoted.promotion.lease_id and promoted.promotion.fencing_token
    assert [item.stage for item in promoted.promotion.checkpoints] == [
        "LEASE_ACQUIRED", "PRECONDITIONS_VERIFIED", "APPLIED", "PROMOTED", "LEASE_RELEASED"
    ]
    assert store.project_leases()[0].status.value == "RELEASED"
    assert store.project_files(ticket.project_id)[0].content_hash != promoted.changes[0].after_hash
    reopened = SQLiteGraphStore(tmp_path / "graph.db")
    persisted = reopened.implementation_sandboxes(ticket.id)[0]
    assert persisted.promotion == promoted.promotion
    node = next(
        item for item in build_dashboard_snapshot(store)["nodes"] if item["id"] == attempt.id
    )
    assert node["promotion"]["status"] == "PROMOTED"


def test_scheduled_promotion_waits_durably_for_lease_then_runs(tmp_path: Path) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(
        ticket.id, attempt.id, actor="promoter", reason="Validated patch approved."
    )
    lease = store.acquire_project_lease(
        str(root), "other-workflow", "OTHER", ttl_seconds=300
    ).lease
    scheduler = ResourceAwareScheduler(store)
    controller = InteractiveSandboxController(manager, scheduler=scheduler)
    response = controller.promote(ticket.id, attempt.id)
    scheduled_id = response["id"]
    import time

    deadline = time.monotonic() + 5
    while scheduler.get(scheduled_id).status != "WAITING_FOR_LEASE":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    waiting = scheduler.get(scheduled_id)
    assert "other-workflow" in waiting.blocked_reason
    store.release_project_lease(str(root), lease.holder_id, lease.fencing_token)

    deadline = time.monotonic() + 15
    while controller.snapshot()["status"] not in {"PROMOTED", "FAILED", "CANCELLED"}:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert controller.snapshot()["status"] == "PROMOTED"
    assert scheduler.get(scheduled_id).status == "COMPLETED"
    assert scheduler.get(scheduled_id).evidence_ids


def test_stale_source_after_promotion_approval_is_rejected_before_writes(tmp_path: Path) -> None:
    root, _, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Reviewed.")
    (root / "src/service.py").write_text("STALE = True\n", encoding="utf-8")
    stale = (root / "src/service.py").read_bytes()

    result = manager.promote(ticket.id, attempt.id)

    assert result.status == "PRECONDITION_FAILED"
    assert result.promotion is not None and result.promotion.rollback_verified
    assert "approval is stale" in (result.promotion.failure_reason or "")
    assert (root / "src/service.py").read_bytes() == stale


def test_promotion_rejects_changed_path_outside_approved_slice(tmp_path: Path) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Reviewed.")
    attempt = store.implementation_sandboxes(ticket.id)[0]
    attempt.authorized_paths.remove("src/service.py")
    store.save_implementation_sandbox(attempt)
    original = tree(root)

    result = manager.promote(ticket.id, attempt.id)

    assert result.status == "PRECONDITION_FAILED"
    assert "not authorized" in (result.promotion.failure_reason or "")
    assert tree(root) == original


class FailingPromotionManager(ImplementationSandboxManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.execution_count = 0

    def _execute(self, command, cwd, timeout):
        self.execution_count += 1
        if self.execution_count == 1:
            return ExecutionRecord(command=command, exit_code=1, stderr="simulated failure")
        return super()._execute(command, cwd, timeout)


def test_failed_post_application_validation_restores_exact_original_bytes(tmp_path: Path) -> None:
    root, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    manager = FailingPromotionManager(store, ChangeWorker())
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Rollback test.")

    result = manager.promote(ticket.id, attempt.id)

    assert result.status == "ROLLED_BACK"
    assert result.promotion is not None
    assert result.promotion.validations[0].exit_code == 1
    assert result.promotion.rollback_verified is True
    assert result.promotion.rollback_validations[0].exit_code == 0
    assert tree(root) == original
    reopened = SQLiteGraphStore(tmp_path / "graph.db")
    persisted = reopened.implementation_sandboxes(ticket.id)[0]
    assert persisted.promotion is not None
    assert persisted.promotion.rollback_verified is True
    assert persisted.promotion.rollback_validations[0].exit_code == 0


class InterruptedPromotionManager(ImplementationSandboxManager):
    @classmethod
    def _replace_bytes(cls, paths, changes, modes):
        paths[0].write_bytes(cls._change_bytes(changes[0], True))
        raise OSError("simulated interrupted replacement")


def test_interrupted_multi_file_application_rolls_back_every_original_byte(tmp_path: Path) -> None:
    root, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    manager = InterruptedPromotionManager(store, ChangeWorker())
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Atomicity test.")

    result = manager.promote(ticket.id, attempt.id)

    assert result.status == "ROLLED_BACK"
    assert result.promotion is not None and result.promotion.rollback_verified
    assert "interrupted replacement" in (result.promotion.failure_reason or "")
    assert tree(root) == original


def test_ticket_budget_is_rechecked_before_promotion_lease_or_source_write(tmp_path: Path) -> None:
    root, store, tickets, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Budget test.")
    exhausted = tickets.get(ticket.id)
    exhausted.usage.worker_calls = exhausted.budget.max_worker_calls
    store.save_project_ticket(exhausted)

    with pytest.raises(RuntimeError, match="worker-call"):
        manager.promote(ticket.id, attempt.id)

    assert tree(root) == original
    assert store.project_leases() == []


def promoted_source_only_attempt(tmp_path: Path):
    root, store, tickets, ticket, plan = fixture(tmp_path)
    task = Task.create("Describe calculate.", root, "claim-task", plan.indexed_manifest_sha256)
    store.save_task(task)
    stale_claim = Claim(
        fingerprint="old-calculate-claim",
        project_fingerprint=plan.indexed_manifest_sha256,
        project_root=str(root),
        subject="calculate behavior",
        producer="test",
        conclusion="calculate doubles values",
        confidence=1,
        files_examined=["src/service.py"],
    )
    store.save_claim(task, stale_claim)
    tickets.approve_plan(ticket.id, plan.id, actor="planner", reason="Plan reviewed.")
    manager = ImplementationSandboxManager(store, SourceOnlyWorker())
    attempt = manager.run(ticket.id, plan.id)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Validated.")
    attempt = manager.promote(ticket.id, attempt.id)
    return root, store, ticket, plan, attempt, stale_claim


def test_promoted_sandbox_reconciliation_is_incremental_idempotent_and_persisted(
    tmp_path: Path,
) -> None:
    root, store, ticket, plan, attempt, stale_claim = promoted_source_only_attempt(tmp_path)
    promoted_bytes = tree(root)

    result = SandboxPromotionReconciler(store).reconcile(ticket.id, attempt.id)

    assert result.changed_paths == ["src/service.py"]
    assert result.dependent_paths == ["tests/test_service.py"]
    assert result.parsed_paths == ["src/service.py", "tests/test_service.py"]
    unrelated = next(
        item for item in store.project_files(ticket.project_id) if item.path == "src/unrelated.py"
    )
    assert unrelated.id in result.reused_file_ids
    assert stale_claim.id in result.invalidated_claim_ids
    obsolete = store.get_claim(stale_claim.id)
    assert obsolete is not None and obsolete.validity_status.value == "SUPERSEDED"
    assert obsolete.superseded_by_claim_id in result.replacement_claim_ids
    replacement = store.get_claim(result.replacement_claim_ids[0])
    assert replacement is not None
    assert replacement.project_fingerprint == result.new_manifest_sha256
    assert replacement.source_files[0].content_hash == attempt.changes[0].after_hash
    stale_plan = next(item for item in store.project_workspace_records() if item.id == plan.id)
    assert stale_plan.status == "STALE" and stale_plan.approval_status == "SUPERSEDED"
    assert result.superseded_validation_decision_ids
    assert result.source_unchanged_during_reconciliation
    assert tree(root) == promoted_bytes
    assert [item.stage for item in result.checkpoints] == ["CREATED", "INDEXED", "RECONCILED"]
    assert any(
        item.kind == "SANDBOX_PROMOTION_RECONCILED" for item in store.ticket_events(ticket.id)
    )
    repeated = SandboxPromotionReconciler(store).reconcile(ticket.id, attempt.id)
    assert repeated == result
    assert len(
        [item for item in store.ticket_events(ticket.id) if item.kind == "SANDBOX_PROMOTION_RECONCILED"]
    ) == 1
    reopened = SQLiteGraphStore(tmp_path / "graph.db")
    persisted = reopened.implementation_sandboxes(ticket.id)[0]
    assert persisted.promotion is not None and persisted.promotion.reconciliation == result


class SimulatedProcessLoss(BaseException):
    pass


@pytest.mark.parametrize(
    ("stage", "expected_status"),
    [
        ("PREPARED", "ROLLED_BACK"),
        ("REPLACEMENT_STARTED", "ROLLED_BACK"),
        ("REPLACEMENT_COMPLETED", "ROLLED_BACK"),
        ("APPLIED", "PROMOTED"),
        ("VALIDATION_RECORDED", "PROMOTED"),
    ],
)
def test_crash_recovery_is_durable_at_every_application_stage(
    tmp_path: Path, stage: str, expected_status: str
) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Recovery test.")

    def crash(observed: str) -> None:
        if observed == stage:
            raise SimulatedProcessLoss(stage)

    crashing = ImplementationSandboxManager(store, ChangeWorker(), fault_injector=crash)
    with pytest.raises(SimulatedProcessLoss):
        crashing.promote(ticket.id, attempt.id)

    persisted = SQLiteGraphStore(store.path).implementation_sandboxes(ticket.id)[0]
    assert persisted.promotion is not None
    assert persisted.promotion.mutation_journal is not None
    assert not persisted.promotion.mutation_journal.terminal
    with pytest.raises(RuntimeError, match="recover it before"):
        store.acquire_project_lease(str(root), "unrelated", "other")

    recovery = ImplementationSandboxManager(SQLiteGraphStore(store.path), ChangeWorker())
    recovered = recovery.recover_promotion(ticket.id, attempt.id)
    assert recovered.status == expected_status
    assert recovered.promotion is not None
    journal = recovered.promotion.mutation_journal
    assert journal is not None and journal.terminal and journal.recovery_count == 1
    if expected_status == "ROLLED_BACK":
        assert tree(root) == original
    else:
        for change in recovered.changes:
            assert (root / change.path).read_bytes() == recovery._change_bytes(change, True)
        assert (root / "src/unrelated.py").read_bytes() == original["src/unrelated.py"]
    checkpoint_count = len(journal.checkpoints)
    validation_count = len(recovered.promotion.validations)
    again = recovery.recover_promotion(ticket.id, attempt.id)
    assert len(again.promotion.mutation_journal.checkpoints) == checkpoint_count
    assert len(again.promotion.validations) == validation_count
    assert again.promotion.reconciliation is None


def test_recovery_rejects_stale_fence_and_unverifiable_source_without_writes(tmp_path: Path) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Recovery safety.")

    def crash(stage: str) -> None:
        if stage == "PREPARED":
            raise SimulatedProcessLoss(stage)

    with pytest.raises(SimulatedProcessLoss):
        ImplementationSandboxManager(store, ChangeWorker(), fault_injector=crash).promote(
            ticket.id, attempt.id
        )
    persisted = store.implementation_sandboxes(ticket.id)[0]
    persisted.promotion.mutation_journal.fencing_token += 10
    store.save_implementation_sandbox(persisted)
    with pytest.raises(RuntimeError, match="stale fencing token"):
        manager.recover_promotion(ticket.id, attempt.id)
    changed = b"external change\n"
    (root / "src/service.py").write_bytes(changed)
    persisted = store.implementation_sandboxes(ticket.id)[0]
    persisted.promotion.mutation_journal.fencing_token -= 10
    store.save_implementation_sandbox(persisted)
    failed = manager.recover_promotion(ticket.id, attempt.id)
    assert failed.status == "RECOVERY_FAILED"
    assert (root / "src/service.py").read_bytes() == changed
    assert failed.promotion.mutation_journal.failure_reason


def test_recovery_rollback_failure_is_persisted_and_can_be_resumed(tmp_path: Path) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Rollback recovery.")

    def crash(stage: str) -> None:
        if stage == "REPLACEMENT_COMPLETED":
            raise SimulatedProcessLoss(stage)

    with pytest.raises(SimulatedProcessLoss):
        ImplementationSandboxManager(store, ChangeWorker(), fault_injector=crash).promote(
            ticket.id, attempt.id
        )
    recovery = ImplementationSandboxManager(store, ChangeWorker())
    original_replacer = recovery._replace_single
    recovery._replace_single = lambda *args: (_ for _ in ()).throw(OSError("locked source"))
    failed = recovery.recover_promotion(ticket.id, attempt.id)
    assert failed.status == "RECOVERY_FAILED"
    assert failed.promotion.mutation_journal.rollback_state == "FAILED"
    assert not failed.promotion.mutation_journal.terminal
    recovery._replace_single = original_replacer
    resumed = recovery.recover_promotion(ticket.id, attempt.id)
    assert resumed.status == "ROLLED_BACK"
    assert resumed.promotion.mutation_journal.recovery_count == 2
    assert tree(root) == original


def test_expired_promotion_lease_is_reclaimed_before_recovery_and_reuse(tmp_path: Path) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    attempt = satisfy_manual_gates(manager, ticket, attempt)
    manager.approve_promotion(ticket.id, attempt.id, actor="promoter", reason="Expired recovery.")

    def crash(stage: str) -> None:
        if stage == "PREPARED":
            raise SimulatedProcessLoss(stage)

    with pytest.raises(SimulatedProcessLoss):
        ImplementationSandboxManager(store, ChangeWorker(), fault_injector=crash).promote(
            ticket.id, attempt.id
        )
    lease = store.project_leases()[0]
    lease.status = ProjectLeaseStatus.ACTIVE
    lease.released_at = None
    lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with store.connect() as db:
        db.execute(
            "UPDATE project_leases SET payload=? WHERE project_root=?",
            (lease.model_dump_json(), str(root.resolve()).casefold()),
        )
    recovered = manager.recover_promotion(ticket.id, attempt.id)
    assert recovered.status == "ROLLED_BACK"
    assert recovered.promotion.mutation_journal.fencing_token == lease.fencing_token + 1
    kinds = [event.kind.value for event in store.project_leases()[0].events]
    assert "RECLAIMED" in kinds
    assert "RECOVERY_STARTED" in kinds
    assert "RECOVERY_COMPLETED" in kinds


def test_neo4j_persists_sandbox_reconciliation_and_provenance_links(tmp_path: Path) -> None:
    _, store, ticket, _, attempt, _ = promoted_source_only_attempt(tmp_path)
    SandboxPromotionReconciler(store).reconcile(ticket.id, attempt.id)
    attempt = store.implementation_sandboxes(ticket.id)[0]

    class RecordingDriver:
        def __init__(self):
            self.calls = []

        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    driver = RecordingDriver()
    neo = object.__new__(Neo4jGraphStore)
    neo.driver = driver
    neo.save_implementation_sandbox(attempt)
    cypher = "\n".join(query for query, _ in driver.calls)

    assert "SandboxPromotionReconciliation" in cypher
    assert "RECONCILED_BY" in cypher
    assert "RECONCILIATION_SCAN" in cypher
    assert "RECORDED_REPAIRED_STATE" in cypher
    promotion_payloads = [
        parameters["payload"]
        for query, parameters in driver.calls
        if "SandboxPromotion {id:$id}" in query
    ]
    assert promotion_payloads and '"mutation_journal"' in promotion_payloads[0]


def test_reconciliation_rejects_post_promotion_source_drift_before_graph_scan(
    tmp_path: Path,
) -> None:
    root, store, ticket, _, attempt, _ = promoted_source_only_attempt(tmp_path)
    scans_before = len(store.project_scans(ticket.project_id))
    (root / "src/unrelated.py").write_text("DRIFTED = True\n", encoding="utf-8")

    with pytest.raises(Exception, match="reconcile is stale"):
        SandboxPromotionReconciler(store).reconcile(ticket.id, attempt.id)

    assert len(store.project_scans(ticket.project_id)) == scans_before
    persisted = store.implementation_sandboxes(ticket.id)[0]
    assert persisted.promotion is not None and persisted.promotion.reconciliation is None


@pytest.mark.parametrize(
    ("attempt_status", "promotion_status"),
    [
        ("PROMOTION_REJECTED", "PROMOTED"),
        ("PRECONDITION_FAILED", "PRECONDITION_FAILED"),
        ("ROLLED_BACK", "ROLLED_BACK"),
        ("ROLLBACK_FAILED", "ROLLBACK_FAILED"),
        ("DISCARDED", "PROMOTED"),
    ],
)
def test_reconciliation_rejects_every_non_promoted_terminal_state(
    tmp_path: Path, attempt_status: str, promotion_status: str
) -> None:
    root, store, ticket, _, attempt, _ = promoted_source_only_attempt(tmp_path)
    promoted_bytes = tree(root)
    attempt.status = attempt_status
    assert attempt.promotion is not None
    attempt.promotion.status = promotion_status
    store.save_implementation_sandbox(attempt)

    with pytest.raises(ValueError, match="successfully promoted"):
        SandboxPromotionReconciler(store).reconcile(ticket.id, attempt.id)

    assert tree(root) == promoted_bytes
