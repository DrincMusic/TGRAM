from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_graph_debugging import DiagnosisSynthesizer, SliceWorker, fixture
from test_promotion import FailingFinalValidator
from test_repair import ValidRepairWorker

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.models import (
    ApprovalDecision,
    MaintenanceWorkflowStatus,
    ProjectLeaseEventKind,
    PromotionStatus,
    RepairApproval,
    RepairPromotion,
)
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.workflow import MaintenanceWorkflowRunner, ProjectLeaseContended

QUESTION = "Why does test_discounted fail?"
TEST_PATH = "tests/test_pricing.py"


def setup_workflow(tmp_path: Path):
    project = fixture(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    return project, store


def runner(store, worker, repair_worker, **kwargs):
    return MaintenanceWorkflowRunner(
        store,
        worker,
        DiagnosisSynthesizer(),
        repair_worker,
        **kwargs,
    )


def test_workflow_resumes_each_completed_stage_without_repeating_work(tmp_path: Path) -> None:
    project, store = setup_workflow(tmp_path)
    first_worker, first_repair = SliceWorker(), ValidRepairWorker()
    first_runner = runner(store, first_worker, first_repair)

    diagnosed = first_runner.start(
        QUESTION, project, TEST_PATH, max_transitions=1
    )
    assert diagnosed.status == MaintenanceWorkflowStatus.DIAGNOSED
    assert diagnosed.diagnosis_worker_calls == first_worker.calls == 3
    diagnosis_ids = (diagnosed.diagnosis_task_id, diagnosed.diagnosis_claim_id)

    resumed_worker, resumed_repair = SliceWorker(), ValidRepairWorker()
    reopened = SQLiteGraphStore(store.path)
    waiting = runner(reopened, resumed_worker, resumed_repair).advance(
        diagnosed.id, max_transitions=1
    )
    assert waiting.status == MaintenanceWorkflowStatus.WAITING_FOR_APPROVAL
    assert (waiting.diagnosis_task_id, waiting.diagnosis_claim_id) == diagnosis_ids
    assert resumed_worker.calls == 0
    assert resumed_repair.calls == 1
    repair_ids = (
        waiting.repair_task_id,
        waiting.proposal_id,
        waiting.sandbox_validation_id,
    )

    idle_worker, idle_repair = SliceWorker(), ValidRepairWorker()
    reopened = SQLiteGraphStore(store.path)
    still_waiting = runner(reopened, idle_worker, idle_repair).advance(waiting.id)
    assert still_waiting.status == MaintenanceWorkflowStatus.WAITING_FOR_APPROVAL
    assert idle_worker.calls == idle_repair.calls == 0
    assert (
        still_waiting.repair_task_id,
        still_waiting.proposal_id,
        still_waiting.sandbox_validation_id,
    ) == repair_ids
    waiting_snapshot = build_dashboard_snapshot(
        store, root_id=still_waiting.diagnosis_task_id
    )
    assert waiting_snapshot["metrics"]["waiting_maintenance_workflows"] == 1

    completed = runner(reopened, idle_worker, idle_repair).decide(
        waiting.id,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Reviewed the complete sandbox proof.",
    )
    assert completed.status == MaintenanceWorkflowStatus.COMPLETED
    assert completed.follow_up_worker_calls == 0
    terminal_ids = (
        completed.approval_id,
        completed.promotion_id,
        completed.reconciliation_id,
        completed.follow_up_task_id,
        completed.follow_up_claim_id,
    )
    counts = {
        "tasks": len(store.tasks()),
        "proposals": len(store.repair_proposals()),
        "validations": len(store.repair_validations()),
        "approvals": len(store.repair_approvals()),
        "promotions": len(store.repair_promotions()),
        "reconciliations": len(store.post_repair_reconciliations()),
    }

    restarted = runner(SQLiteGraphStore(store.path), SliceWorker(), ValidRepairWorker())
    replay = restarted.advance(completed.id)
    duplicate_start = restarted.start(QUESTION, project, TEST_PATH)
    duplicate_decision = restarted.decide(
        completed.id,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Repeated request must be a no-op.",
    )
    assert replay.id == duplicate_start.id == duplicate_decision.id == completed.id
    assert (
        replay.approval_id,
        replay.promotion_id,
        replay.reconciliation_id,
        replay.follow_up_task_id,
        replay.follow_up_claim_id,
    ) == terminal_ids
    assert counts == {
        "tasks": len(store.tasks()),
        "proposals": len(store.repair_proposals()),
        "validations": len(store.repair_validations()),
        "approvals": len(store.repair_approvals()),
        "promotions": len(store.repair_promotions()),
        "reconciliations": len(store.post_repair_reconciliations()),
    }
    assert [event.status for event in replay.events] == [
        MaintenanceWorkflowStatus.CREATED,
        MaintenanceWorkflowStatus.DIAGNOSED,
        MaintenanceWorkflowStatus.WAITING_FOR_APPROVAL,
        MaintenanceWorkflowStatus.COMPLETED,
    ]
    with pytest.raises(ValueError, match="different human decision"):
        restarted.decide(
            completed.id,
            decision=ApprovalDecision.REJECTED,
            approved_by="Test reviewer",
            reason="Contradict the immutable decision.",
        )
    snapshot = build_dashboard_snapshot(store, root_id=completed.diagnosis_task_id)
    assert snapshot["metrics"]["maintenance_workflows"] == 1
    assert snapshot["metrics"]["completed_maintenance_workflows"] == 1
    assert any(
        node["node_type"] == "maintenance_workflow"
        and node["id"] == completed.id
        for node in snapshot["nodes"]
    )


def test_rejected_workflow_is_terminal_and_never_changes_source(tmp_path: Path) -> None:
    project, store = setup_workflow(tmp_path)
    original = (project / TEST_PATH).read_bytes()
    workflow = runner(store, SliceWorker(), ValidRepairWorker()).start(
        QUESTION, project, TEST_PATH
    )

    rejected = runner(store, SliceWorker(), ValidRepairWorker()).decide(
        workflow.id,
        decision=ApprovalDecision.REJECTED,
        approved_by="Test reviewer",
        reason="Do not change this project.",
    )

    assert rejected.status == MaintenanceWorkflowStatus.REJECTED
    assert rejected.promotion_id is None
    assert rejected.reconciliation_id is None
    assert (project / TEST_PATH).read_bytes() == original
    assert runner(store, SliceWorker(), ValidRepairWorker()).advance(rejected.id) == rejected


def test_failed_final_validation_rolls_back_and_workflow_stays_terminal(
    tmp_path: Path,
) -> None:
    project, store = setup_workflow(tmp_path)
    original = (project / TEST_PATH).read_bytes()
    workflow = runner(store, SliceWorker(), ValidRepairWorker()).start(
        QUESTION, project, TEST_PATH
    )
    rollback_runner = runner(
        store,
        SliceWorker(),
        ValidRepairWorker(),
        promoter_factory=FailingFinalValidator,
    )

    rolled_back = rollback_runner.decide(
        workflow.id,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Exercise final validation rollback.",
    )

    assert rolled_back.status == MaintenanceWorkflowStatus.ROLLED_BACK
    assert rolled_back.reconciliation_id is None
    assert (project / TEST_PATH).read_bytes() == original
    assert store.repair_promotions()[0].rollback_verified is True
    assert rollback_runner.advance(rolled_back.id) == rolled_back


def test_resume_adopts_persisted_approval_without_creating_a_duplicate(tmp_path: Path) -> None:
    project, store = setup_workflow(tmp_path)
    workflow = runner(store, SliceWorker(), ValidRepairWorker()).start(
        QUESTION, project, TEST_PATH
    )
    proposal = store.repair_proposals(workflow.repair_task_id)[0]
    validation = store.repair_validations(workflow.repair_task_id)[0]
    approval = RepairApproval(
        proposal_id=proposal.id,
        validation_id=validation.id,
        project_root=str(project.resolve()),
        proposal_signature=proposal.signature,
        source_tree_fingerprint=proposal.source_tree_fingerprint,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Decision persisted immediately before a simulated process stop.",
    )
    store.save_repair_approval(approval)

    resumed = runner(store, SliceWorker(), ValidRepairWorker()).advance(workflow.id)

    assert resumed.status == MaintenanceWorkflowStatus.COMPLETED
    assert resumed.approval_id == approval.id
    assert len(store.repair_approvals(proposal.id)) == 1
    assert len(store.repair_promotions(proposal.id)) == 1
    assert len(store.post_repair_reconciliations(resumed.promotion_id)) == 1


def test_resume_automatically_rolls_back_an_interrupted_promotion(tmp_path: Path) -> None:
    project, store = setup_workflow(tmp_path)
    original = (project / TEST_PATH).read_bytes()
    workflow = runner(store, SliceWorker(), ValidRepairWorker()).start(
        QUESTION, project, TEST_PATH
    )
    proposal = store.repair_proposals(workflow.repair_task_id)[0]
    validation = store.repair_validations(workflow.repair_task_id)[0]
    approval = RepairApproval(
        proposal_id=proposal.id,
        validation_id=validation.id,
        project_root=str(project.resolve()),
        proposal_signature=proposal.signature,
        source_tree_fingerprint=proposal.source_tree_fingerprint,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Simulate a process stop during atomic application.",
    )
    store.save_repair_approval(approval)
    interrupted = RepairPromotion(
        proposal_id=proposal.id,
        validation_id=validation.id,
        approval_id=approval.id,
        project_root=str(project.resolve()),
        status=PromotionStatus.APPLYING,
        changes=proposal.changes,
        original_tree_fingerprint=proposal.source_tree_fingerprint,
    )
    store.save_repair_promotion(interrupted)
    (project / TEST_PATH).write_text(
        proposal.changes[0].after_content or "", newline=""
    )

    resumed = runner(store, SliceWorker(), ValidRepairWorker()).advance(workflow.id)

    assert resumed.status == MaintenanceWorkflowStatus.ROLLED_BACK
    recovered = store.repair_promotions(proposal.id)[0]
    assert recovered.id == interrupted.id
    assert recovered.status == PromotionStatus.ROLLED_BACK
    assert recovered.rollback_verified is True
    assert "during resume" in (recovered.failure_reason or "")
    assert (project / TEST_PATH).read_bytes() == original
    assert len(store.repair_approvals(proposal.id)) == 1
    assert len(store.repair_promotions(proposal.id)) == 1


def test_live_project_lease_prevents_a_competing_workflow_decision(tmp_path: Path) -> None:
    project, store = setup_workflow(tmp_path)
    workflow = runner(store, SliceWorker(), ValidRepairWorker()).start(
        QUESTION, project, TEST_PATH
    )
    store.acquire_project_lease(str(project), "other-process", "other-workflow")

    with pytest.raises(ProjectLeaseContended, match="leased by other-process"):
        runner(
            SQLiteGraphStore(store.path), SliceWorker(), ValidRepairWorker(),
            holder_id="competing-process",
        ).decide(
            workflow.id,
            decision=ApprovalDecision.APPROVED,
            approved_by="Test reviewer",
            reason="This process must not duplicate the decision.",
        )

    assert store.repair_approvals(workflow.proposal_id) == []
    assert store.repair_promotions(workflow.proposal_id) == []
    assert store.project_leases()[0].events[-1].kind == ProjectLeaseEventKind.CONTENDED


def test_reclaimed_lease_recovers_interrupted_promotion_before_resuming(
    tmp_path: Path,
) -> None:
    project, store = setup_workflow(tmp_path)
    original = (project / TEST_PATH).read_bytes()
    workflow = runner(store, SliceWorker(), ValidRepairWorker()).start(
        QUESTION, project, TEST_PATH
    )
    proposal = store.repair_proposals(workflow.repair_task_id)[0]
    validation = store.repair_validations(workflow.repair_task_id)[0]
    approval = RepairApproval(
        proposal_id=proposal.id,
        validation_id=validation.id,
        project_root=str(project.resolve()),
        proposal_signature=proposal.signature,
        source_tree_fingerprint=proposal.source_tree_fingerprint,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Persisted before simulated abandonment.",
    )
    store.save_repair_approval(approval)
    interrupted = RepairPromotion(
        proposal_id=proposal.id,
        validation_id=validation.id,
        approval_id=approval.id,
        project_root=str(project.resolve()),
        status=PromotionStatus.APPLIED,
        changes=proposal.changes,
        original_tree_fingerprint=proposal.source_tree_fingerprint,
    )
    store.save_repair_promotion(interrupted)
    (project / TEST_PATH).write_text(proposal.changes[0].after_content or "", newline="")
    store.acquire_project_lease(
        str(project), "dead-process", workflow.id,
        ttl_seconds=1, now=datetime(2020, 1, 1, tzinfo=UTC),
    )

    recovered = runner(
        SQLiteGraphStore(store.path), SliceWorker(), ValidRepairWorker(),
        holder_id="recovery-process",
    ).advance(workflow.id)

    assert recovered.status == MaintenanceWorkflowStatus.ROLLED_BACK
    assert (project / TEST_PATH).read_bytes() == original
    kinds = [event.kind for event in store.project_leases()[0].events]
    assert ProjectLeaseEventKind.RECLAIMED in kinds
    assert ProjectLeaseEventKind.RECOVERY_STARTED in kinds
    assert ProjectLeaseEventKind.RECOVERY_COMPLETED in kinds
    assert kinds[-1] == ProjectLeaseEventKind.RELEASED
