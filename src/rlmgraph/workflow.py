from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .adapters import Investigator
from .fingerprint import indexed_project_fingerprint
from .graph_debugging import DebugSynthesizer, GraphDirectedDebugger
from .models import (
    ApprovalDecision,
    MaintenanceWorkflow,
    MaintenanceWorkflowEvent,
    MaintenanceWorkflowStatus,
    ProjectLeaseEventKind,
    PromotionStatus,
    RepairStatus,
    TaskStatus,
)
from .onboarding import ProjectSelection
from .promotion import RepairPromoter
from .repair import RepairWorker, SandboxedRepairValidator
from .store import GraphStore

TERMINAL_WORKFLOW_STATUSES = {
    MaintenanceWorkflowStatus.REJECTED,
    MaintenanceWorkflowStatus.COMPLETED,
    MaintenanceWorkflowStatus.ROLLED_BACK,
    MaintenanceWorkflowStatus.FAILED,
}


class ProjectLeaseContended(RuntimeError):
    """Another live process owns the selected project's mutation lease."""


class MaintenanceWorkflowRunner:
    """Durable orchestration across diagnosis, repair, approval, and reconciliation."""

    def __init__(
        self,
        store: GraphStore,
        investigator: Investigator,
        synthesizer: DebugSynthesizer,
        repair_worker: RepairWorker,
        *,
        repair_max_attempts: int = 2,
        promoter_factory: Callable[[GraphStore], RepairPromoter] = RepairPromoter,
        lease_ttl_seconds: float = 120,
        holder_id: str | None = None,
    ) -> None:
        self.store = store
        self.investigator = investigator
        self.synthesizer = synthesizer
        self.repair_worker = repair_worker
        self.repair_max_attempts = repair_max_attempts
        self.promoter_factory = promoter_factory
        self.lease_ttl_seconds = lease_ttl_seconds
        self.holder_id = holder_id or f"workflow-runner-{uuid4().hex}"
        self.store.initialize()

    def start(
        self,
        question: str,
        project_root: str | Path,
        test_path: str,
        *,
        max_transitions: int | None = None,
    ) -> MaintenanceWorkflow:
        selection = ProjectSelection.explicit(project_root)
        normalized_test = test_path.replace("\\", "/")
        signature = self._signature(question, selection.root, normalized_test)
        existing = next(
            (
                item
                for item in self.store.maintenance_workflows()
                if item.signature == signature
            ),
            None,
        )
        if existing is not None:
            return self.advance(existing.id, max_transitions=max_transitions)
        project = next(
            (
                item
                for item in self.store.projects()
                if Path(item.root).resolve() == selection.root
            ),
            None,
        )
        if project is None:
            raise ValueError("Maintenance workflow requires an indexed project.")
        files = self.store.project_files(project.id)
        state = indexed_project_fingerprint(
            selection.root, [(item.path, item.content_hash) for item in files]
        )
        workflow = MaintenanceWorkflow(
            signature=signature,
            question=question,
            project_root=str(selection.root),
            test_path=normalized_test,
            initial_project_fingerprint=state,
            events=[
                MaintenanceWorkflowEvent(
                    status=MaintenanceWorkflowStatus.CREATED,
                    detail="Durable maintenance workflow created from the indexed project state.",
                )
            ],
        )
        self.store.save_maintenance_workflow(workflow)
        return self.advance(workflow.id, max_transitions=max_transitions)

    def advance(
        self, workflow_id: str, *, max_transitions: int | None = None
    ) -> MaintenanceWorkflow:
        workflow = self._workflow(workflow_id)
        transitions = 0
        while workflow.status not in TERMINAL_WORKFLOW_STATUSES:
            if max_transitions is not None and transitions >= max_transitions:
                break
            if workflow.status == MaintenanceWorkflowStatus.CREATED:
                self._diagnose(workflow)
            elif workflow.status == MaintenanceWorkflowStatus.DIAGNOSED:
                self._validate_repair(workflow)
            elif workflow.status == MaintenanceWorkflowStatus.WAITING_FOR_APPROVAL:
                if not self._recover_decision(workflow):
                    break
            else:
                break
            transitions += 1
        return workflow

    def decide(
        self,
        workflow_id: str,
        *,
        decision: ApprovalDecision,
        approved_by: str,
        reason: str,
    ) -> MaintenanceWorkflow:
        workflow = self.advance(workflow_id)
        if workflow.status in TERMINAL_WORKFLOW_STATUSES:
            if workflow.approval_id:
                persisted = next(
                    (
                        item
                        for item in self.store.repair_approvals()
                        if item.id == workflow.approval_id
                    ),
                    None,
                )
                if persisted is not None and persisted.decision != decision:
                    raise ValueError("A different human decision is already persisted.")
            return workflow
        if workflow.status != MaintenanceWorkflowStatus.WAITING_FOR_APPROVAL:
            raise ValueError(f"Workflow is not awaiting approval: {workflow.status.value}")
        assert workflow.proposal_id is not None
        acquisition = self.store.acquire_project_lease(
            workflow.project_root,
            self.holder_id,
            workflow.id,
            ttl_seconds=self.lease_ttl_seconds,
        )
        if not acquisition.acquired:
            raise ProjectLeaseContended(
                f"Project mutation is leased by {acquisition.lease.holder_id} "
                f"until {acquisition.lease.expires_at.isoformat()}."
            )
        lease = acquisition.lease
        try:
            if acquisition.reclaimed:
                self._recover_abandoned_promotions(workflow, lease.fencing_token)
            self.store.renew_project_lease(
                workflow.project_root,
                self.holder_id,
                lease.fencing_token,
                ttl_seconds=self.lease_ttl_seconds,
            )
            existing = self.store.repair_approvals(workflow.proposal_id)
            if existing:
                approval = existing[-1]
                if approval.decision != decision:
                    raise ValueError("A different human decision is already persisted.")
                result = self.promoter_factory(self.store).resume_approval(approval.id)
            else:
                result = self.promoter_factory(self.store).decide(
                    workflow.proposal_id,
                    workflow.project_root,
                    decision=decision,
                    approved_by=approved_by,
                    reason=reason,
                )
        finally:
            self.store.release_project_lease(
                workflow.project_root, self.holder_id, lease.fencing_token
            )
        workflow.approval_id = result.approval.id
        workflow.promotion_attempts = max(workflow.promotion_attempts, int(result.promotion is not None))
        if result.promotion is not None:
            workflow.promotion_id = result.promotion.id
        self._finish_decision(workflow, result.approval.decision)
        return workflow

    def _diagnose(self, workflow: MaintenanceWorkflow) -> None:
        recovered = next(
            (
                task
                for task in reversed(self.store.tasks())
                if task.project_root == workflow.project_root
                and task.project_fingerprint == workflow.initial_project_fingerprint
                and task.question == workflow.question
                and task.status == TaskStatus.DONE
                and task.output_claim_id
            ),
            None,
        )
        if recovered is not None:
            diagnosis = self.store.get_claim(recovered.output_claim_id or "")
            if diagnosis is not None:
                workflow.diagnosis_task_id = recovered.id
                workflow.diagnosis_claim_id = diagnosis.id
                workflow.diagnosis_worker_calls = 0
                self._transition(
                    workflow,
                    MaintenanceWorkflowStatus.DIAGNOSED,
                    "Recovered an already completed graph-directed diagnosis.",
                    [recovered.id, diagnosis.id],
                )
                return
        result = GraphDirectedDebugger(
            self.store, self.investigator, self.synthesizer
        ).debug(workflow.question, workflow.project_root, workflow.test_path)
        workflow.diagnosis_task_id = result.root_task.id
        workflow.diagnosis_claim_id = result.diagnosis.id
        workflow.diagnosis_worker_calls += result.worker_calls
        self._transition(
            workflow,
            MaintenanceWorkflowStatus.DIAGNOSED,
            f"Diagnosis completed with {result.worker_calls} worker calls.",
            [result.root_task.id, result.diagnosis.id],
        )

    def _validate_repair(self, workflow: MaintenanceWorkflow) -> None:
        assert workflow.diagnosis_claim_id is not None
        proposal = next(
            (
                item
                for item in reversed(self.store.repair_proposals())
                if item.diagnosis_claim_id == workflow.diagnosis_claim_id
                and item.project_root == workflow.project_root
                and item.test_path == workflow.test_path
                and item.status == RepairStatus.VERIFIED
            ),
            None,
        )
        validation = (
            next(
                (
                    item
                    for item in reversed(self.store.repair_validations())
                    if proposal is not None
                    and item.proposal_id == proposal.id
                    and item.status == RepairStatus.VERIFIED
                ),
                None,
            )
            if proposal is not None
            else None
        )
        if proposal is None or validation is None:
            result = SandboxedRepairValidator(
                self.store,
                self.repair_worker,
                max_attempts=self.repair_max_attempts,
            ).validate(workflow.diagnosis_claim_id, workflow.test_path)
            workflow.repair_worker_calls += result.worker_calls
            workflow.repair_model_calls += result.model_calls
            proposal, validation = result.proposal, result.validation
            workflow.repair_task_id = result.repair_task.id
        else:
            workflow.repair_task_id = proposal.repair_task_id
        workflow.proposal_id = proposal.id
        workflow.sandbox_validation_id = validation.id
        if validation.status != RepairStatus.VERIFIED:
            workflow.last_error = validation.failure_reason
            self._transition(
                workflow,
                MaintenanceWorkflowStatus.FAILED,
                "Sandbox repair attempts were exhausted without verification.",
                [proposal.id, validation.id],
            )
            return
        self._transition(
            workflow,
            MaintenanceWorkflowStatus.WAITING_FOR_APPROVAL,
            "Verified sandbox patch is persisted and waiting for an explicit human decision.",
            [proposal.id, validation.id],
        )

    def _recover_decision(self, workflow: MaintenanceWorkflow) -> bool:
        assert workflow.proposal_id is not None
        approvals = self.store.repair_approvals(workflow.proposal_id)
        if not approvals:
            return False
        acquisition = self.store.acquire_project_lease(
            workflow.project_root, self.holder_id, workflow.id,
            ttl_seconds=self.lease_ttl_seconds,
        )
        if not acquisition.acquired:
            return False
        try:
            if acquisition.reclaimed:
                self._recover_abandoned_promotions(workflow, acquisition.lease.fencing_token)
            self.store.renew_project_lease(
                workflow.project_root, self.holder_id, acquisition.lease.fencing_token,
                ttl_seconds=self.lease_ttl_seconds,
            )
            result = self.promoter_factory(self.store).resume_approval(approvals[-1].id)
        finally:
            self.store.release_project_lease(
                workflow.project_root, self.holder_id, acquisition.lease.fencing_token
            )
        workflow.approval_id = result.approval.id
        if result.promotion is not None:
            workflow.promotion_id = result.promotion.id
            workflow.promotion_attempts = max(workflow.promotion_attempts, 1)
        self._finish_decision(workflow, result.approval.decision)
        return True

    def _recover_abandoned_promotions(
        self, workflow: MaintenanceWorkflow, fencing_token: int
    ) -> None:
        incomplete = [
            item for item in self.store.repair_promotions()
            if Path(item.project_root).resolve() == Path(workflow.project_root).resolve()
            and item.status in {
                PromotionStatus.APPROVED,
                PromotionStatus.APPLYING,
                PromotionStatus.APPLIED,
            }
        ]
        if not incomplete:
            return
        self.store.record_project_lease_event(
            workflow.project_root, self.holder_id, fencing_token,
            ProjectLeaseEventKind.RECOVERY_STARTED,
            f"Recovering {len(incomplete)} abandoned promotion(s) before mutation.",
            workflow_id=workflow.id,
        )
        for promotion in incomplete:
            self.promoter_factory(self.store).resume_approval(promotion.approval_id)
        self.store.record_project_lease_event(
            workflow.project_root, self.holder_id, fencing_token,
            ProjectLeaseEventKind.RECOVERY_COMPLETED,
            f"Recovered {len(incomplete)} abandoned promotion(s); mutation may proceed.",
            workflow_id=workflow.id,
        )

    def _finish_decision(
        self, workflow: MaintenanceWorkflow, decision: ApprovalDecision
    ) -> None:
        assert workflow.approval_id is not None
        if decision == ApprovalDecision.REJECTED:
            self._transition(
                workflow,
                MaintenanceWorkflowStatus.REJECTED,
                "Human reviewer rejected the verified sandbox repair; no source was changed.",
                [workflow.approval_id],
            )
            return
        promotion = next(
            (
                item
                for item in self.store.repair_promotions(workflow.proposal_id)
                if item.id == workflow.promotion_id
            ),
            None,
        )
        if promotion is None:
            raise RuntimeError("Approved workflow has no persisted promotion result.")
        if promotion.status == PromotionStatus.VERIFIED:
            reconciliation = self.store.post_repair_reconciliations(promotion.id)
            if not reconciliation:
                raise RuntimeError("Verified promotion has no post-repair reconciliation.")
            current = reconciliation[-1]
            workflow.reconciliation_id = current.id
            workflow.follow_up_task_id = current.follow_up_task_id
            workflow.follow_up_claim_id = current.follow_up_claim_id
            workflow.follow_up_worker_calls = current.follow_up_worker_calls
            self._transition(
                workflow,
                MaintenanceWorkflowStatus.COMPLETED,
                "Approved repair was promoted, reconciled, and verified by zero-call follow-up.",
                [
                    workflow.approval_id,
                    promotion.id,
                    current.id,
                    current.follow_up_task_id,
                ],
            )
        elif promotion.status == PromotionStatus.ROLLED_BACK:
            workflow.last_error = promotion.failure_reason
            self._transition(
                workflow,
                MaintenanceWorkflowStatus.ROLLED_BACK,
                "Final validation failed and the original project bytes were restored.",
                [workflow.approval_id, promotion.id],
            )
        else:
            workflow.last_error = promotion.failure_reason
            self._transition(
                workflow,
                MaintenanceWorkflowStatus.FAILED,
                "Promotion failed and requires human inspection.",
                [workflow.approval_id, promotion.id],
            )

    def _transition(
        self,
        workflow: MaintenanceWorkflow,
        status: MaintenanceWorkflowStatus,
        detail: str,
        artifact_ids: list[str],
    ) -> None:
        workflow.status = status
        workflow.updated_at = datetime.now(UTC)
        if status in TERMINAL_WORKFLOW_STATUSES:
            workflow.completed_at = workflow.updated_at
        workflow.events.append(
            MaintenanceWorkflowEvent(
                status=status,
                detail=detail,
                artifact_ids=artifact_ids,
            )
        )
        self.store.save_maintenance_workflow(workflow)

    def _workflow(self, workflow_id: str) -> MaintenanceWorkflow:
        workflow = next(
            (item for item in self.store.maintenance_workflows() if item.id == workflow_id),
            None,
        )
        if workflow is None:
            raise ValueError(f"Maintenance workflow not found: {workflow_id}")
        return workflow

    @staticmethod
    def _signature(question: str, project_root: Path, test_path: str) -> str:
        payload = {
            "question": " ".join(question.casefold().split()),
            "project_root": str(project_root.resolve()).casefold(),
            "test_path": test_path,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
