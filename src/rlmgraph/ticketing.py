from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .fingerprint import file_content_hash, indexed_project_fingerprint
from .governance import ProjectGovernance
from .models import (
    Evidence,
    GraphEdge,
    GraphRelation,
    ImplementationSandboxAttempt,
    ProjectExecutionMode,
    ProjectTicket,
    TicketAcceptanceCriterion,
    TicketBudget,
    TicketClosureDecision,
    TicketConstraint,
    TicketCriterionClosureGate,
    TicketDependencyScope,
    TicketEvent,
    TicketEvidenceAssessment,
    TicketValidationResult,
)
from .provenance import assess_claim_from_index, record_validity

TICKET_STATUSES = {
    "DRAFT",
    "READY",
    "ACTIVE",
    "BLOCKED",
    "AWAITING_REVIEW",
    "SATISFIED",
    "REJECTED",
    "CLOSED",
}
CRITERION_STATUSES = {"PENDING", "EVIDENCED", "WAIVED", "BLOCKED"}
PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}
VALIDATION_STATUSES = {"PASSED", "FAILED", "BLOCKED"}


class TicketManager:
    def __init__(self, store) -> None:
        self.store = store

    def create(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        acceptance_criteria: list[str],
        constraints: list[str],
        priority: str,
        dependency_ticket_ids: list[str],
        budget: TicketBudget,
        created_by: str,
        source_claim_ids: list[str] | None = None,
    ) -> ProjectTicket:
        title = " ".join(title.split())
        description = " ".join(description.split())
        criteria = [" ".join(item.split()) for item in acceptance_criteria if item.strip()]
        constraint_values = [" ".join(item.split()) for item in constraints if item.strip()]
        if not title:
            raise ValueError("Ticket title is required.")
        if not description:
            raise ValueError("Ticket description is required.")
        if not criteria:
            raise ValueError("At least one acceptance criterion is required.")
        priority = priority.upper()
        if priority not in PRIORITIES:
            raise ValueError(f"Priority must be one of: {', '.join(sorted(PRIORITIES))}.")
        project = next((item for item in self.store.projects() if item.id == project_id), None)
        if not project or not project.read_only or not project.explicitly_selected:
            raise ValueError("Ticket project must be explicitly registered read-only.")
        if project.execution_mode == ProjectExecutionMode.READ_ONLY:
            raise ValueError("Read-only projects cannot create implementation tickets.")
        source_claim_ids = list(dict.fromkeys(source_claim_ids or []))
        self._assert_current_claims(project, source_claim_ids)
        tickets = {item.id: item for item in self.store.project_tickets()}
        missing = sorted(set(dependency_ticket_ids) - set(tickets))
        if missing:
            raise ValueError(f"Unknown ticket dependencies: {', '.join(missing)}")
        governance = ProjectGovernance(self.store)
        policy = governance.policy(project.id)
        governance.assert_budget(policy, budget)
        dependency_scopes = [
            TicketDependencyScope(
                ticket_id=dependency_id,
                project_id=tickets[dependency_id].project_id,
                read_only=tickets[dependency_id].project_id != project.id,
                separately_authorized=False,
            )
            for dependency_id in dict.fromkeys(dependency_ticket_ids)
        ]
        ticket = ProjectTicket(
            project_id=project.id,
            project_root=str(Path(project.root).resolve()),
            title=title,
            description=description,
            priority=priority,
            acceptance_criteria=[
                TicketAcceptanceCriterion(description=item) for item in criteria
            ],
            constraints=[TicketConstraint(description=item) for item in constraint_values],
            dependency_ticket_ids=list(dict.fromkeys(dependency_ticket_ids)),
            dependency_scopes=dependency_scopes,
            source_claim_ids=source_claim_ids,
            governance_policy_id=policy.id,
            governance_policy_version=policy.version,
            budget=budget,
            created_by=created_by,
        )
        self.store.save_project_ticket(ticket)
        for claim_id in source_claim_ids:
            self.store.save_edge(
                GraphEdge(
                    source=ticket.id, relation=GraphRelation.DERIVED_FROM, target=claim_id
                )
            )
        self._event(ticket.id, "CREATED", "Ticket created with explicit scope and budget.", created_by)
        return ticket

    def assert_current_source_claims(self, ticket: ProjectTicket) -> None:
        project = next(
            (item for item in self.store.projects() if item.id == ticket.project_id), None
        )
        if project is None:
            raise ValueError("Ticket project is no longer registered.")
        self._assert_current_claims(project, ticket.source_claim_ids)

    def _assert_current_claims(self, project, source_claim_ids: list[str]) -> None:
        claims = [self.store.get_claim(claim_id) for claim_id in source_claim_ids]
        indexed_files = self.store.project_files(project.id)
        project_state = indexed_project_fingerprint(
            Path(project.root), [(item.path, item.content_hash) for item in indexed_files]
        )
        for claim in (
            item for item in claims
            if item is not None and item.validity_status.value == "CURRENT"
        ):
            valid, reason = assess_claim_from_index(claim, indexed_files, project_state)
            if record_validity(claim, valid, project_state, reason):
                self.store.update_claim(claim)
        invalid_claims = [
            claim_id for claim_id, claim in zip(source_claim_ids, claims, strict=True)
            if claim is None or claim.validity_status.value != "CURRENT"
            or not claim.project_root
            or Path(claim.project_root).resolve() != Path(project.root).resolve()
        ]
        if invalid_claims:
            raise ValueError(
                "Ticket source claims must be current and belong to the selected project: "
                + ", ".join(invalid_claims)
            )

    def transition(self, ticket_id: str, status: str, *, actor: str, reason: str) -> ProjectTicket:
        ticket = self.get(ticket_id)
        status = status.upper()
        if status not in TICKET_STATUSES:
            raise ValueError(f"Unknown ticket status: {status}")
        if status in {"SATISFIED", "CLOSED"}:
            if not actor.strip() or not reason.strip():
                raise ValueError("Ticket closure requires an actor and explicit reason.")
            decision = self._closure_decision(ticket, status, actor=actor, reason=reason)
            created = self._persist_closure_decision(ticket, decision)
            if not decision.allowed:
                raise ValueError(f"Ticket cannot be {status}: " + "; ".join(decision.failures))
            if not created and ticket.status == status:
                return ticket
            if ticket.satisfied_at is None:
                ticket.satisfied_at = datetime.now(UTC)
        ticket.status = status
        ticket.updated_at = datetime.now(UTC)
        ticket.execution_authorized = False
        self.store.save_project_ticket(ticket)
        self._event(ticket.id, "STATUS_CHANGED", f"Status set to {status}: {reason}", actor)
        return ticket

    def resolve_criterion(
        self,
        ticket_id: str,
        criterion_id: str,
        *,
        status: str,
        evidence_ids: list[str],
        reason: str,
        actor: str,
    ) -> ProjectTicket:
        ticket = self.get(ticket_id)
        criterion = next(
            (item for item in ticket.acceptance_criteria if item.id == criterion_id), None
        )
        if not criterion:
            raise ValueError(f"Acceptance criterion not found: {criterion_id}")
        status = status.upper()
        if status not in CRITERION_STATUSES:
            raise ValueError(f"Unknown criterion status: {status}")
        if status != "PENDING" and not actor.strip():
            raise ValueError("Criterion resolution requires an actor.")
        assessments = [self.assess_evidence(ticket, evidence_id) for evidence_id in evidence_ids]
        invalid = [item for item in assessments if not item.eligible]
        if invalid:
            raise ValueError("Criterion evidence is ineligible: " + "; ".join(
                f"{item.evidence_id}: {item.reason}" for item in invalid
            ))
        if status == "EVIDENCED" and not evidence_ids:
            raise ValueError("EVIDENCED criteria require at least one attached evidence artifact.")
        if status in {"WAIVED", "BLOCKED"} and not reason.strip():
            raise ValueError(f"{status} criteria require an explicit reason.")
        criterion.status = status
        criterion.evidence_ids = list(dict.fromkeys(evidence_ids))
        criterion.waiver_reason = reason.strip() if status == "WAIVED" else None
        criterion.blocker_reason = reason.strip() if status == "BLOCKED" else None
        criterion.resolved_by = actor
        criterion.resolved_at = datetime.now(UTC) if status != "PENDING" else None
        criterion.evidence_assessments = assessments if status == "EVIDENCED" else []
        ticket.updated_at = datetime.now(UTC)
        ticket.execution_authorized = False
        self.store.save_project_ticket(ticket)
        self._event(
            ticket.id,
            "CRITERION_RESOLVED",
            f"{criterion.description} → {status}. {reason}".strip(),
            actor,
            evidence_ids,
        )
        return ticket

    def record_validation(
        self,
        ticket_id: str,
        *,
        name: str,
        status: str,
        detail: str,
        evidence: list[Evidence],
        workspace_record_id: str | None,
        recorded_by: str,
    ) -> TicketValidationResult:
        ticket = self.get(ticket_id)
        status = status.upper()
        if status not in VALIDATION_STATUSES:
            raise ValueError(f"Unknown validation status: {status}")
        if workspace_record_id:
            record = next(
                (
                    item
                    for item in self.store.project_workspace_records()
                    if item.id == workspace_record_id and item.ticket_id == ticket.id
                ),
                None,
            )
            if not record:
                raise ValueError("Validation workspace record must belong to this ticket.")
            assessment = self.assess_evidence(ticket, workspace_record_id)
            if not assessment.eligible:
                raise ValueError(
                    f"Validation workspace record is ineligible: {assessment.reason}"
                )
        result = TicketValidationResult(
            ticket_id=ticket.id,
            project_id=ticket.project_id,
            project_root=ticket.project_root,
            name=" ".join(name.split()),
            status=status,
            detail=" ".join(detail.split()),
            evidence=evidence,
            workspace_record_id=workspace_record_id,
            recorded_by=recorded_by,
            execution_authorized=False,
        )
        self.store.save_ticket_validation_result(result)
        self._event(
            ticket.id,
            "VALIDATION_RECORDED",
            f"{result.name}: {result.status} — {result.detail}",
            recorded_by,
            [result.id, *([workspace_record_id] if workspace_record_id else [])],
        )
        return result

    def approve_plan(
        self, ticket_id: str, plan_record_id: str, *, actor: str, reason: str,
        decision: str = "APPROVED",
    ):
        ticket = self.get(ticket_id)
        policy = ProjectGovernance(self.store).policy(ticket.project_id)
        ProjectGovernance.assert_actor(policy.plan_approvers, actor, "Plan approval")
        plan = next(
            (
                item
                for item in self.store.project_workspace_records()
                if item.id == plan_record_id and item.ticket_id == ticket.id
            ),
            None,
        )
        if not plan or plan.kind != "CHANGE_PLAN" or not plan.approval_required:
            raise ValueError("Plan approval requires a ticket-attached change plan.")
        if plan.project_id != ticket.project_id or ProjectGovernance.canonical_root(plan.project_root) != ProjectGovernance.canonical_root(ticket.project_root):
            raise ValueError("Plan approval cannot cross the ticket's project boundary.")
        if not reason.strip():
            raise ValueError("Plan approval requires an explicit review reason.")
        if not plan.source_integrity_verified or not plan.read_only_verified:
            raise ValueError("Plan approval requires current, read-only source evidence.")
        governance = ProjectGovernance(self.store)
        binding, requirements_sha, evidence_sha = governance.plan_binding(policy, plan)
        records = governance.record_decisions(
            policy,
            action="PLAN",
            artifact_id=plan.id,
            artifact_kinds=governance.artifact_kinds(plan.affected_paths),
            decision=decision,
            actor=actor,
            reason=reason,
            binding_sha256=binding,
            source_manifest_sha256=plan.final_manifest_sha256,
            requirements_sha256=requirements_sha,
            evidence_sha256=evidence_sha,
        )
        plan.approval_history.extend(records)
        approved, missing, expired = governance.evaluate(
            policy,
            action="PLAN",
            artifact_kinds=governance.artifact_kinds(plan.affected_paths),
            binding_sha256=binding,
            history=plan.approval_history,
        )
        plan.approval_missing = missing
        plan.approval_expiration_reasons = expired
        plan.approval_status = "DENIED" if decision.upper() == "DENIED" else (
            "APPROVED" if approved else "PENDING"
        )
        plan.execution_authorized = False
        self.store.save_project_workspace_record(plan)
        self._event(
            ticket.id,
            "PLAN_DECISION_RECORDED",
            f"Plan {plan.id} {decision.upper()} under policy {policy.id} v{policy.version}; "
            f"rules {', '.join(item.rule_id for item in records)}. {reason.strip()}",
            actor,
            [plan.id],
        )
        return plan

    def attach_sandbox_attempt(self, ticket_id: str, attempt) -> None:
        ticket = self.get(ticket_id)
        if attempt.ticket_id != ticket.id or attempt.project_id != ticket.project_id:
            raise ValueError("Sandbox attempt does not match its originating ticket.")
        if ProjectGovernance.canonical_root(attempt.project_root) != ProjectGovernance.canonical_root(ticket.project_root):
            raise ValueError("Sandbox attempt root does not match its originating ticket.")
        normalized_authorized = {self._safe_relative_path(path) for path in attempt.authorized_paths}
        normalized_changes = {self._safe_relative_path(change.path) for change in attempt.changes}
        outside = sorted(normalized_changes - normalized_authorized)
        if outside:
            raise ValueError(
                "Sandbox attempt contains changes outside its authorized path boundary: "
                + ", ".join(outside)
            )
        attempt.execution_authorized = False
        self.store.save_implementation_sandbox(attempt)
        ticket.usage.model_calls += attempt.model_calls
        ticket.usage.worker_calls += attempt.worker_calls
        ticket.usage.wall_time_seconds += attempt.elapsed_seconds
        ticket.updated_at = datetime.now(UTC)
        ticket.execution_authorized = False
        self.store.save_project_ticket(ticket)
        self._event(
            ticket.id,
            "SANDBOX_ATTEMPT_ATTACHED",
            f"Sandbox {attempt.id} finished as {attempt.status} with {len(attempt.changes)} reviewable changes.",
            "Observer sandbox",
            [attempt.id, attempt.plan_record_id],
        )

    @staticmethod
    def _safe_relative_path(value: str) -> str:
        normalized = str(value).replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or path.is_absolute()
            or ".." in path.parts
            or (path.parts and ":" in path.parts[0])
        ):
            raise ValueError(f"Sandbox path is outside the authorized project boundary: {value}")
        return path.as_posix()

    def attach_workspace_record(self, ticket_id: str, record) -> None:
        ticket = self.get(ticket_id)
        if record.project_id != ticket.project_id:
            raise ValueError("Workspace result project does not match its originating ticket.")
        if ProjectGovernance.canonical_root(record.project_root) != ProjectGovernance.canonical_root(ticket.project_root):
            raise ValueError("Workspace result root does not match its originating ticket.")
        record.ticket_id = ticket.id
        record.execution_authorized = False
        self.store.save_project_workspace_record(record)
        ticket.usage.tokens += record.tokens_used
        ticket.usage.model_calls += record.model_calls_used
        ticket.usage.worker_calls += record.worker_calls_used
        ticket.usage.wall_time_seconds += record.elapsed_seconds
        ticket.usage.deepest_branch = max(ticket.usage.deepest_branch, record.branch_depth_used)
        ticket.updated_at = datetime.now(UTC)
        ticket.execution_authorized = False
        self.store.save_project_ticket(ticket)
        self._event(
            ticket.id,
            "WORKSPACE_RESULT_ATTACHED",
            f"{record.kind} result attached with {len(record.evidence)} evidence items.",
            "Observer workspace",
            [record.id, *([record.source_result_id] if record.source_result_id else [])],
        )

    def check_budget(self, ticket_id: str) -> ProjectTicket:
        ticket = self.get(ticket_id)
        policy = ProjectGovernance(self.store).policy(ticket.project_id)
        ProjectGovernance(self.store).assert_budget(policy, ticket.budget)
        checks = (
            (ticket.usage.tokens, ticket.budget.max_tokens, "token"),
            (ticket.usage.model_calls, ticket.budget.max_model_calls, "model-call"),
            (ticket.usage.worker_calls, ticket.budget.max_worker_calls, "worker-call"),
            (
                ticket.usage.wall_time_seconds,
                ticket.budget.max_wall_time_seconds,
                "wall-time",
            ),
            (ticket.usage.deepest_branch, ticket.budget.max_branch_depth, "branch-depth"),
        )
        exhausted = [name for used, limit, name in checks if used >= limit]
        if exhausted:
            raise RuntimeError("Ticket compute budget exhausted: " + ", ".join(exhausted))
        return ticket

    def satisfaction_failures(self, ticket: ProjectTicket) -> list[str]:
        _, failures = self.closure_report(ticket)
        return failures

    def closure_report(
        self, ticket: ProjectTicket
    ) -> tuple[list[TicketCriterionClosureGate], list[str]]:
        failures: list[str] = []
        gates: list[TicketCriterionClosureGate] = []
        for criterion in ticket.acceptance_criteria:
            assessments = [
                self.assess_evidence(ticket, evidence_id)
                for evidence_id in criterion.evidence_ids
            ]
            if criterion.status == "EVIDENCED":
                resolved = bool(assessments) and all(item.eligible for item in assessments)
                if resolved:
                    explanation = f"Current implementation evidence accepted ({len(assessments)} artifact(s))."
                else:
                    reasons = [item.reason for item in assessments if not item.eligible]
                    explanation = (
                        "No evidence is attached."
                        if not assessments
                        else "Evidence is no longer eligible: " + "; ".join(reasons)
                    )
                    failures.append(
                        f"criterion lacks current eligible evidence: {criterion.description}"
                    )
            elif criterion.status == "WAIVED":
                resolved = bool(criterion.waiver_reason and criterion.resolved_by)
                explanation = (
                    f"Explicitly waived by {criterion.resolved_by}: {criterion.waiver_reason}"
                    if resolved
                    else "Waiver requires a reason and attribution."
                )
                if not resolved:
                    failures.append(f"criterion lacks attributed waiver: {criterion.description}")
            elif criterion.status == "BLOCKED":
                resolved = bool(criterion.blocker_reason and criterion.resolved_by)
                explanation = (
                    f"Explicitly blocked by {criterion.resolved_by}: {criterion.blocker_reason}"
                    if resolved
                    else "Blocker requires a reason and attribution."
                )
                if not resolved:
                    failures.append(f"criterion lacks attributed blocker: {criterion.description}")
            else:
                resolved = False
                explanation = "Criterion remains pending."
                failures.append(f"criterion remains pending: {criterion.description}")
            gates.append(TicketCriterionClosureGate(
                criterion_id=criterion.id,
                description=criterion.description,
                status=criterion.status,
                resolved=resolved,
                explanation=explanation,
                resolved_by=criterion.resolved_by,
                resolved_at=criterion.resolved_at,
                evidence_assessments=assessments,
            ))
        tickets = {item.id: item for item in self.store.project_tickets()}
        for dependency_id in ticket.dependency_ticket_ids:
            dependency = tickets.get(dependency_id)
            if not dependency or dependency.status not in {"SATISFIED", "CLOSED"}:
                failures.append(f"dependency is not satisfied: {dependency_id}")
        return gates, failures

    def get(self, ticket_id: str) -> ProjectTicket:
        ticket = next((item for item in self.store.project_tickets() if item.id == ticket_id), None)
        if not ticket:
            raise ValueError(f"Ticket not found: {ticket_id}")
        project = ProjectGovernance(self.store).project(ticket.project_id)
        if ProjectGovernance.canonical_root(ticket.project_root) != ProjectGovernance.canonical_root(project.root):
            raise ValueError("Ticket project identity does not match its registered root.")
        dependency_projects = {item.id: item.project_id for item in self.store.project_tickets()}
        for scope in ticket.dependency_scopes:
            if dependency_projects.get(scope.ticket_id) != scope.project_id:
                raise ValueError("Ticket dependency project identity is stale or mismatched.")
            if scope.project_id != ticket.project_id and not scope.read_only:
                raise ValueError("Cross-project ticket dependencies must remain read-only.")
        return ticket

    def assess_evidence(
        self, ticket: ProjectTicket, evidence_id: str
    ) -> TicketEvidenceAssessment:
        records = {item.id: item for item in self.store.project_workspace_records()}
        validations = {item.id: item for item in self.store.ticket_validation_results()}
        attempts = list(self.store.implementation_sandboxes())
        record = records.get(evidence_id)
        if record:
            reason = self._scope_reason(ticket, record.ticket_id, record.project_id)
            if not reason and record.status.upper() != "COMPLETED":
                reason = f"workspace result status is {record.status}, not COMPLETED"
            if not reason and (not record.source_integrity_verified or not record.read_only_verified):
                reason = "workspace result lacks source-integrity or read-only verification"
            if not reason and record.indexed_manifest_sha256 != record.final_manifest_sha256:
                reason = "workspace result is stale because its source manifests differ"
            return self._assessment(
                evidence_id, "PROJECT_WORKSPACE_RECORD", record.ticket_id, record.project_id,
                record.status, reason, record.final_manifest_sha256,
            )
        validation = validations.get(evidence_id)
        if validation:
            owner = next((item for item in self.store.project_tickets() if item.id == validation.ticket_id), None)
            validation_project_id = validation.project_id or (owner.project_id if owner else None)
            reason = self._scope_reason(
                ticket, validation.ticket_id, validation_project_id
            )
            if not reason and validation.project_root and ProjectGovernance.canonical_root(validation.project_root) != ProjectGovernance.canonical_root(ticket.project_root):
                reason = "validation project root does not match its ticket boundary"
            if not reason and validation.status != "PASSED":
                reason = f"validation status is {validation.status}, not PASSED"
            if not reason and validation.workspace_record_id:
                linked = self.assess_evidence(ticket, validation.workspace_record_id)
                if not linked.eligible:
                    reason = f"linked workspace result is ineligible: {linked.reason}"
            return self._assessment(
                evidence_id, "TICKET_VALIDATION_RESULT", validation.ticket_id,
                validation_project_id, validation.status, reason,
            )
        for attempt in attempts:
            found = self._assess_sandbox_artifact(ticket, attempt, evidence_id)
            if found:
                return found
        return self._assessment(
            evidence_id, "UNKNOWN", None, None, None,
            "artifact does not belong to this ticket or is not an accepted implementation-evidence type",
        )

    def evidence_catalog(self, ticket: ProjectTicket) -> list[TicketEvidenceAssessment]:
        ids = [
            item.id for item in self.store.project_workspace_records()
            if item.ticket_id == ticket.id
        ]
        ids.extend(
            item.id for item in self.store.ticket_validation_results()
            if item.ticket_id == ticket.id
        )
        for attempt in self.store.implementation_sandboxes(ticket.id):
            ids.append(attempt.id)
            ids.extend(item.id for item in attempt.validation_decisions)
            ids.extend(item.id for item in attempt.validation_worker_executions)
            ids.extend(item.id for item in attempt.external_validation_reports)
            if attempt.promotion:
                ids.append(attempt.promotion.id)
                if attempt.promotion.reconciliation:
                    ids.append(attempt.promotion.reconciliation.id)
        return [self.assess_evidence(ticket, item) for item in dict.fromkeys(ids)]

    def _assess_sandbox_artifact(
        self, ticket: ProjectTicket, attempt: ImplementationSandboxAttempt, evidence_id: str
    ) -> TicketEvidenceAssessment | None:
        artifact_type = None
        status = attempt.status
        source_manifest = attempt.initial_manifest_sha256
        patch_sha = attempt.patch_sha256
        artifact = None
        if attempt.id == evidence_id:
            artifact_type, artifact = "IMPLEMENTATION_SANDBOX_ATTEMPT", attempt
        else:
            for candidate, kind in [
                *((item, "SANDBOX_VALIDATION_DECISION") for item in attempt.validation_decisions),
                *((item, "SANDBOX_VALIDATION_WORKER_EXECUTION") for item in attempt.validation_worker_executions),
                *((item, "SANDBOX_EXTERNAL_VALIDATION_REPORT") for item in attempt.external_validation_reports),
            ]:
                if candidate.id == evidence_id:
                    artifact_type, artifact = kind, candidate
                    break
            if artifact is None and attempt.promotion and attempt.promotion.id == evidence_id:
                artifact_type, artifact = "SANDBOX_PROMOTION", attempt.promotion
            if (
                artifact is None and attempt.promotion and attempt.promotion.reconciliation
                and attempt.promotion.reconciliation.id == evidence_id
            ):
                artifact_type, artifact = "SANDBOX_RECONCILIATION", attempt.promotion.reconciliation
        if artifact is None:
            return None
        reason = self._scope_reason(ticket, attempt.ticket_id, attempt.project_id)
        terminal_bad = {"FAILED", "REJECTED", "DISCARDED", "PROMOTION_REJECTED"}
        if not reason and attempt.status in terminal_bad:
            reason = f"originating sandbox is {attempt.status.lower()}"
        if not reason and attempt.status not in {"READY_FOR_REVIEW", "PROMOTED"}:
            reason = f"originating sandbox status {attempt.status} is not reviewable or promoted"
        if not reason and attempt.status == "READY_FOR_REVIEW":
            reason = "sandbox proposal has not been promoted and reconciled"
        if not reason and attempt.status == "READY_FOR_REVIEW" and (
            not attempt.original_unchanged
            or attempt.final_manifest_sha256 != attempt.initial_manifest_sha256
        ):
            reason = "sandbox source-integrity evidence is stale or incomplete"
        if not reason and attempt.status == "PROMOTED" and (
            not attempt.promotion or attempt.promotion.status != "PROMOTED"
        ):
            reason = "sandbox promotion is missing or not successful"
        if not reason and attempt.status == "PROMOTED" and (
            not attempt.promotion
            or not attempt.promotion.reconciliation
            or attempt.promotion.reconciliation.status != "RECONCILED"
        ):
            reason = "promoted sandbox has not been reconciled with the current graph"
        if not reason and artifact_type == "IMPLEMENTATION_SANDBOX_ATTEMPT":
            if attempt.status not in {"READY_FOR_REVIEW", "PROMOTED"}:
                reason = f"sandbox status {attempt.status} is not reviewable or promoted"
            elif not attempt.patch_sha256 or not attempt.changes:
                reason = "sandbox has no current implementation patch"
        elif not reason and artifact_type == "SANDBOX_VALIDATION_DECISION":
            status = artifact.status
            if status not in {"PASSED", "SATISFIED"}:
                reason = f"validation decision status is {status}, not PASSED or SATISFIED"
            elif artifact.worker_execution_id:
                linked = self._assess_sandbox_artifact(ticket, attempt, artifact.worker_execution_id)
                if not linked or not linked.eligible:
                    reason = "validation decision's worker evidence is ineligible"
            elif artifact.external_report_id:
                linked = self._assess_sandbox_artifact(ticket, attempt, artifact.external_report_id)
                if not linked or not linked.eligible:
                    reason = "validation decision's external report is ineligible"
        elif not reason and artifact_type == "SANDBOX_VALIDATION_WORKER_EXECUTION":
            status = artifact.status
            source_manifest = artifact.source_manifest_sha256
            patch_sha = artifact.patch_sha256
            if status != "PASSED":
                reason = f"worker execution status is {status}, not PASSED"
            elif source_manifest != attempt.initial_manifest_sha256 or patch_sha != attempt.patch_sha256:
                reason = "worker execution is stale or bound to a superseded patch"
        elif not reason and artifact_type == "SANDBOX_EXTERNAL_VALIDATION_REPORT":
            status = artifact.status
            source_manifest = artifact.source_manifest_sha256
            patch_sha = artifact.patch_sha256
            if status != "PASSED":
                reason = f"external report status is {status}, not PASSED"
            elif source_manifest != attempt.initial_manifest_sha256 or patch_sha != attempt.patch_sha256:
                reason = "external report is stale or bound to a superseded patch"
        elif not reason and artifact_type == "SANDBOX_PROMOTION":
            status = artifact.status
            source_manifest = artifact.final_manifest_sha256
            if status != "PROMOTED":
                reason = f"promotion status is {status}, not PROMOTED"
        elif not reason and artifact_type == "SANDBOX_RECONCILIATION":
            status = artifact.status
            source_manifest = artifact.new_manifest_sha256
            if status != "RECONCILED" or not artifact.source_unchanged_during_reconciliation:
                reason = "reconciliation is incomplete or source integrity was not verified"
        if not reason and attempt.status == "READY_FOR_REVIEW":
            newer = any(
                item.ticket_id == attempt.ticket_id
                and item.id != attempt.id
                and item.created_at > attempt.created_at
                and item.status in {"READY_FOR_REVIEW", "PROMOTED"}
                for item in self.store.implementation_sandboxes(attempt.ticket_id)
            )
            if newer:
                reason = "sandbox evidence was superseded by a newer implementation attempt"
        if not reason:
            expected_manifest = (
                attempt.promotion.final_manifest_sha256
                if attempt.status == "PROMOTED" and attempt.promotion
                else attempt.initial_manifest_sha256
            )
            current_manifest = self._current_project_manifest(ticket)
            if current_manifest and expected_manifest != current_manifest:
                reason = "implementation evidence is stale against the current project manifest"
        return self._assessment(
            evidence_id, artifact_type, attempt.ticket_id, attempt.project_id,
            status, reason, source_manifest, patch_sha,
        )

    @staticmethod
    def _scope_reason(
        ticket: ProjectTicket, artifact_ticket_id: str | None, artifact_project_id: str | None
    ) -> str:
        if artifact_ticket_id != ticket.id:
            return f"artifact belongs to ticket {artifact_ticket_id or 'unknown'}, not {ticket.id}"
        if artifact_project_id != ticket.project_id:
            return f"artifact belongs to project {artifact_project_id or 'unknown'}, not {ticket.project_id}"
        return ""

    @staticmethod
    def _assessment(
        evidence_id: str, artifact_type: str, ticket_id: str | None,
        project_id: str | None, status: str | None, reason: str,
        source_manifest_sha256: str | None = None, patch_sha256: str | None = None,
    ) -> TicketEvidenceAssessment:
        return TicketEvidenceAssessment(
            evidence_id=evidence_id, artifact_type=artifact_type, eligible=not reason,
            reason=reason or "eligible current implementation evidence",
            ticket_id=ticket_id, project_id=project_id, status=status,
            source_manifest_sha256=source_manifest_sha256, patch_sha256=patch_sha256,
        )

    def _closure_decision(
        self, ticket: ProjectTicket, requested_status: str, *, actor: str, reason: str
    ) -> TicketClosureDecision:
        gates, failures = self.closure_report(ticket)
        state = {
            "ticket_id": ticket.id, "requested_status": requested_status,
            "actor": actor, "reason": reason, "failures": failures,
            "gates": [item.model_dump(mode="json", exclude={"evidence_assessments": {"__all__": {"assessed_at"}}}) for item in gates],
        }
        fingerprint = hashlib.sha256(
            json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return TicketClosureDecision(
            ticket_id=ticket.id, project_id=ticket.project_id,
            requested_status=requested_status, allowed=not failures,
            actor=actor, reason=reason.strip(), fingerprint=fingerprint,
            failures=failures, criterion_gates=gates,
        )

    def _persist_closure_decision(
        self, ticket: ProjectTicket, decision: TicketClosureDecision
    ) -> bool:
        existing = next(
            (item for item in ticket.closure_decisions if item.fingerprint == decision.fingerprint),
            None,
        )
        if existing:
            return False
        ticket.closure_decisions.append(decision)
        for gate in decision.criterion_gates:
            criterion = next(item for item in ticket.acceptance_criteria if item.id == gate.criterion_id)
            criterion.evidence_assessments = gate.evidence_assessments
        ticket.updated_at = datetime.now(UTC)
        ticket.execution_authorized = False
        self.store.save_project_ticket(ticket)
        self._event(
            ticket.id, "CLOSURE_DECIDED",
            f"{decision.requested_status} {'allowed' if decision.allowed else 'blocked'}: "
            + ("all completion gates resolved" if decision.allowed else "; ".join(decision.failures)),
            decision.actor,
            [item.evidence_id for gate in decision.criterion_gates for item in gate.evidence_assessments],
        )
        return True

    def _current_project_manifest(self, ticket: ProjectTicket) -> str | None:
        try:
            root = Path(ticket.project_root).resolve(strict=True)
            entries = []
            for item in self.store.project_files(ticket.project_id):
                path = (root / item.path).resolve(strict=True)
                path.relative_to(root)
                entries.append((item.path, file_content_hash(path)))
            return indexed_project_fingerprint(root, entries)
        except (OSError, ValueError):
            return None

    def _event(
        self,
        ticket_id: str,
        kind: str,
        detail: str,
        actor: str,
        artifact_ids: list[str] | None = None,
    ) -> None:
        ticket = next((item for item in self.store.project_tickets() if item.id == ticket_id), None)
        self.store.save_ticket_event(
            TicketEvent(
                ticket_id=ticket_id,
                project_id=ticket.project_id if ticket else None,
                project_root=ticket.project_root if ticket else None,
                kind=kind,
                detail=detail,
                actor=actor,
                artifact_ids=artifact_ids or [],
            )
        )
