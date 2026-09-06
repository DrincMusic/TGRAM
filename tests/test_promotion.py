from __future__ import annotations

from pathlib import Path

import pytest
from test_repair import ValidRepairWorker, diagnosed_fixture

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.models import (
    ApprovalDecision,
    GraphRelation,
    PromotionStatus,
)
from rlmgraph.models import (
    TestExecution as ExecutionRecord,
)
from rlmgraph.onboarding import ReadOnlyViolation
from rlmgraph.promotion import RepairPromoter
from rlmgraph.reconciliation import PostRepairReconciler
from rlmgraph.repair import SandboxedRepairValidator


def verified_proposal(tmp_path: Path):
    project, store, _task, diagnosis = diagnosed_fixture(tmp_path)
    repair = SandboxedRepairValidator(store, ValidRepairWorker()).validate(
        diagnosis.id, "tests/test_pricing.py"
    )
    return project, store, repair


def test_approved_verified_repair_is_applied_and_finally_validated(tmp_path: Path) -> None:
    project, store, repair = verified_proposal(tmp_path)

    result = RepairPromoter(store).decide(
        repair.proposal.id,
        project,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Reviewed the exact diff and sandbox evidence.",
    )

    assert result.approval.decision == ApprovalDecision.APPROVED
    assert result.promotion is not None
    assert result.promotion.status == PromotionStatus.VERIFIED
    assert result.promotion.final_validation is not None
    assert result.promotion.final_validation.exit_code == 0
    assert result.promotion.rollback_validation is None
    assert "== 90" in (project / "tests" / "test_pricing.py").read_text()
    assert [event.status for event in result.promotion.events] == [
        PromotionStatus.APPROVED,
        PromotionStatus.APPLYING,
        PromotionStatus.APPLIED,
        PromotionStatus.VERIFIED,
    ]
    assert store.repair_approvals(repair.proposal.id) == [result.approval]
    assert store.repair_promotions(repair.proposal.id) == [result.promotion]
    relations = {edge.relation for edge in store.edges()}
    assert GraphRelation.HAS_APPROVAL in relations
    assert GraphRelation.APPROVES_REPAIR in relations
    assert GraphRelation.HAS_PROMOTION_RUN in relations
    assert GraphRelation.APPLIED_REPAIR in relations
    assert GraphRelation.FINAL_VALIDATED_BY in relations
    reconciliation = store.post_repair_reconciliations(result.promotion.id)[0]
    assert reconciliation.affected_paths == ["tests/test_pricing.py"]
    assert reconciliation.parsed_paths == ["tests/test_pricing.py"]
    assert reconciliation.parsed_file_count == 1
    assert reconciliation.content_read_file_count == 1
    assert reconciliation.new_project_fingerprint != reconciliation.previous_project_fingerprint
    assert reconciliation.follow_up_worker_calls == 0
    assert reconciliation.follow_up_reuse_type == "reconciled-repair"
    assert reconciliation.follow_up_claim_id == reconciliation.replacement_claim_id
    assert repair.proposal.diagnosis_claim_id in reconciliation.invalidated_claim_ids
    obsolete = store.get_claim(repair.proposal.diagnosis_claim_id)
    assert obsolete is not None
    assert obsolete.validity_status.value == "SUPERSEDED"
    assert obsolete.superseded_by_claim_id == reconciliation.replacement_claim_id
    assert any(
        edge.source == reconciliation.replacement_claim_id
        and edge.relation == GraphRelation.SUPERSEDES
        and edge.target == obsolete.id
        for edge in store.edges()
    )
    replacement = store.get_claim(reconciliation.replacement_claim_id)
    assert replacement is not None
    assert replacement.project_fingerprint == reconciliation.new_project_fingerprint
    assert replacement.valid_from == reconciliation.new_project_fingerprint
    assert [source.path for source in replacement.source_files] == [
        "tests/test_pricing.py"
    ]
    assert replacement.source_files[0].content_hash == repair.proposal.changes[0].after_hash
    follow_up = store.get_task(reconciliation.follow_up_task_id)
    assert follow_up is not None and follow_up.attempt_count == 0
    assert follow_up.reused_claim_id == reconciliation.replacement_claim_id
    assert PostRepairReconciler(store).reconcile(result.promotion.id) == reconciliation
    relations = {edge.relation for edge in store.edges()}
    assert GraphRelation.RECONCILED_BY in relations
    assert GraphRelation.RECONCILIATION_SCAN in relations
    assert GraphRelation.RECORDED_REPAIRED_STATE in relations
    assert GraphRelation.PROVED_FOLLOWUP_REUSE in relations
    snapshot = build_dashboard_snapshot(store, root_id=repair.repair_task.parent_task_id)
    assert snapshot["metrics"]["repair_approvals"] == 1
    assert snapshot["metrics"]["promoted_repairs"] == 1
    assert snapshot["metrics"]["post_repair_reconciliations"] == 1
    assert snapshot["metrics"]["reconciled_follow_up_worker_calls"] == 0
    assert {node["node_type"] for node in snapshot["nodes"]} >= {
        "repair_approval",
        "repair_promotion",
        "post_repair_reconciliation",
    }


def test_rejection_is_persisted_and_never_modifies_project(tmp_path: Path) -> None:
    project, store, repair = verified_proposal(tmp_path)
    original = (project / "tests" / "test_pricing.py").read_bytes()

    result = RepairPromoter(store).decide(
        repair.proposal.id,
        project,
        decision=ApprovalDecision.REJECTED,
        approved_by="Test reviewer",
        reason="The behavior change is not desired.",
    )

    assert result.promotion is None
    assert result.approval.decision == ApprovalDecision.REJECTED
    assert (project / "tests" / "test_pricing.py").read_bytes() == original
    assert store.repair_promotions() == []


class FailingFinalValidator(RepairPromoter):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.executions = 0

    def _execute(self, command: list[str], cwd: Path) -> ExecutionRecord:
        self.executions += 1
        if self.executions == 1:
            return ExecutionRecord(
                command=command,
                exit_code=1,
                stdout="simulated integration failure",
            )
        return super()._execute(command, cwd)


def test_failed_real_validation_automatically_rolls_back_and_persists_proof(
    tmp_path: Path,
) -> None:
    project, store, repair = verified_proposal(tmp_path)
    original = (project / "tests" / "test_pricing.py").read_bytes()

    result = FailingFinalValidator(store).decide(
        repair.proposal.id,
        project,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Exercise rollback behavior.",
    )

    assert result.promotion is not None
    assert result.promotion.status == PromotionStatus.ROLLED_BACK
    assert result.promotion.final_validation is not None
    assert result.promotion.final_validation.exit_code == 1
    assert result.promotion.rollback_verified is True
    assert result.promotion.rollback_validation is not None
    assert result.promotion.rollback_validation.exit_code != 0
    assert (project / "tests" / "test_pricing.py").read_bytes() == original
    assert any(
        edge.relation == GraphRelation.ROLLED_BACK_REPAIR for edge in store.edges()
    )
    assert store.post_repair_reconciliations() == []


class InterruptedApplicationPromoter(RepairPromoter):
    @staticmethod
    def _replace_all(paths, proposal, modes) -> None:
        paths[0].write_text(proposal.changes[0].after_content or "", newline="")
        raise OSError("simulated replacement interruption")


def test_interrupted_application_is_all_or_nothing_and_rolled_back(tmp_path: Path) -> None:
    project, store, repair = verified_proposal(tmp_path)
    original = (project / "tests" / "test_pricing.py").read_bytes()

    result = InterruptedApplicationPromoter(store).decide(
        repair.proposal.id,
        project,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Exercise atomic replacement recovery.",
    )

    assert result.promotion is not None
    assert result.promotion.status == PromotionStatus.ROLLED_BACK
    assert "application failed" in (result.promotion.failure_reason or "")
    assert result.promotion.rollback_verified is True
    assert (project / "tests" / "test_pricing.py").read_bytes() == original


def test_promotion_requires_exact_explicit_project_and_unchanged_source(tmp_path: Path) -> None:
    project, store, repair = verified_proposal(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    promoter = RepairPromoter(store)

    with pytest.raises(ReadOnlyViolation, match="does not match"):
        promoter.decide(
            repair.proposal.id,
            other,
            decision=ApprovalDecision.APPROVED,
            approved_by="Test reviewer",
            reason="Wrong project test.",
        )

    (project / "pkg" / "unrelated.py").write_text("UNRELATED = False\n")
    with pytest.raises(ReadOnlyViolation, match="changed after sandbox validation"):
        promoter.decide(
            repair.proposal.id,
            project,
            decision=ApprovalDecision.APPROVED,
            approved_by="Test reviewer",
            reason="Stale proposal test.",
        )
    failed = store.repair_promotions(repair.proposal.id)
    assert failed[-1].status == PromotionStatus.APPLICATION_FAILED
    assert "before source writes" in failed[-1].events[-1].detail


class FailedRollbackPromoter(FailingFinalValidator):
    @staticmethod
    def _restore_all(originals, modes) -> None:
        raise OSError("simulated rollback failure")


def test_rollback_failure_is_durably_marked_for_human_recovery(tmp_path: Path) -> None:
    project, store, repair = verified_proposal(tmp_path)

    result = FailedRollbackPromoter(store).decide(
        repair.proposal.id,
        project,
        decision=ApprovalDecision.APPROVED,
        approved_by="Test reviewer",
        reason="Exercise rollback failure history.",
    )

    assert result.promotion is not None
    assert result.promotion.status == PromotionStatus.APPLICATION_FAILED
    assert result.promotion.rollback_verified is False
    assert "rollback failed" in (result.promotion.failure_reason or "")
    assert store.repair_promotions(repair.proposal.id)[-1] == result.promotion


def test_promotion_cannot_happen_without_human_identity_and_reason(tmp_path: Path) -> None:
    project, store, repair = verified_proposal(tmp_path)

    with pytest.raises(ValueError, match="human identity"):
        RepairPromoter(store).decide(
            repair.proposal.id,
            project,
            decision=ApprovalDecision.APPROVED,
            approved_by="",
            reason="",
        )
