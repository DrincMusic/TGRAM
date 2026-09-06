from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from .adapters import (
    CodexCliInvestigator,
    CodexProjectIdeaSuggester,
    HttpStructuredLanguageAdapter,
)
from .automatic_tickets import AutomaticTicketRunner
from .conversation_benchmark import (
    ConversationBenchmarkController,
    ConversationBenchmarkStore,
    PairedConversationBenchmark,
)
from .governance import ProjectGovernance
from .implementation_sandbox import (
    CodexPlanImplementationWorker,
    ImplementationSandboxManager,
    InteractiveSandboxController,
)
from .interactive_workspace import InteractiveProjectWorkspaceController
from .local_profiles import LocalProfileStore
from .model_call_ledger import configure_model_call_ledger, model_call_ledger
from .model_settings import ModelSettingsManager
from .models import (
    ApprovalPolicyRule,
    BenchmarkRun,
    Claim,
    CodexReadOnlyProof,
    ConflictCluster,
    ConflictVerdict,
    EvaluationRun,
    Evidence,
    ExecutionAttempt,
    GenericCodexEvaluation,
    GraphEdge,
    ImplementationSandboxAttempt,
    InvestigationSession,
    MaintenanceWorkflow,
    PathwayBenchmarkResult,
    PathwayPromotionDecision,
    PlanDecision,
    PlanningRun,
    PostRepairReconciliation,
    ProjectDependency,
    ProjectExecutionMode,
    ProjectFile,
    ProjectIdea,
    ProjectIdeaStatus,
    ProjectLease,
    ProjectRecord,
    ProjectScan,
    ProjectSymbol,
    ProjectTest,
    ProjectTicket,
    ProjectWorkspaceRecord,
    PromotionDecision,
    ReconstructionSession,
    RecursiveCodexDelegationProof,
    RepairApproval,
    RepairPromotion,
    RepairProposal,
    RepairValidation,
    ResolutionAttempt,
    ResumableSessionEvaluation,
    RouteEvaluation,
    RoutePrediction,
    RoutingPolicyUpdate,
    ScheduledWorkItem,
    SchedulerLimits,
    Task,
    TaskKind,
    TaskStatus,
    TicketBudget,
    TicketEvent,
    TicketValidationResult,
    UnrealArtifact,
    UnrealDependency,
    UnrealIndexScan,
    VirtualMemoryPathway,
)
from .observer_chat import ObserverChat
from .onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from .operations import TicketAuditExporter
from .project_goal_benchmark import (
    PairedProjectGoalBenchmark,
    ProjectGoalBenchmarkController,
    ProjectGoalBenchmarkStore,
)
from .scheduler import ResourceAwareScheduler
from .store import Neo4jGraphStore, SQLiteGraphStore
from .ticketing import TicketManager

DEMO_ROOT_ID = "LIVE-DEMO-ROOT"
DEMO_RESOLUTION_ID = "LIVE-DEMO-RESOLUTION"


class DashboardStore(Protocol):
    def tasks(self) -> list[Task]: ...
    def claims(self) -> list[Claim]: ...
    def edges(self) -> list[GraphEdge]: ...
    def resolution_attempts(self, task_id: str) -> list[ResolutionAttempt]: ...
    def conflict_clusters(self) -> list[ConflictCluster]: ...
    def conflict_verdicts(self, task_id: str | None = None) -> list[ConflictVerdict]: ...
    def reconstructions(self) -> list[ReconstructionSession]: ...
    def promotion_decisions(self) -> list[PromotionDecision]: ...
    def benchmark_runs(self) -> list[BenchmarkRun]: ...
    def pathways(self) -> list[VirtualMemoryPathway]: ...
    def pathway_decisions(self) -> list[PathwayPromotionDecision]: ...
    def pathway_benchmarks(self) -> list[PathwayBenchmarkResult]: ...
    def plan_decisions(self, root_task_id: str | None = None) -> list[PlanDecision]: ...
    def planning_runs(self, root_task_id: str | None = None) -> list[PlanningRun]: ...
    def execution_attempts(self, task_id: str | None = None) -> list[ExecutionAttempt]: ...
    def route_predictions(self, task_id: str | None = None) -> list[RoutePrediction]: ...
    def routing_policy_updates(self) -> list[RoutingPolicyUpdate]: ...
    def route_evaluations(self) -> list[RouteEvaluation]: ...
    def repair_proposals(self, task_id: str | None = None) -> list[RepairProposal]: ...
    def repair_validations(self, task_id: str | None = None) -> list[RepairValidation]: ...
    def repair_approvals(self, proposal_id: str | None = None) -> list[RepairApproval]: ...
    def repair_promotions(self, proposal_id: str | None = None) -> list[RepairPromotion]: ...
    def post_repair_reconciliations(
        self, promotion_id: str | None = None
    ) -> list[PostRepairReconciliation]: ...
    def maintenance_workflows(self) -> list[MaintenanceWorkflow]: ...
    def project_leases(self) -> list[ProjectLease]: ...
    def evaluation_runs(self) -> list[EvaluationRun]: ...
    def codex_readonly_proofs(self) -> list[CodexReadOnlyProof]: ...
    def recursive_codex_proofs(self) -> list[RecursiveCodexDelegationProof]: ...
    def generic_codex_evaluations(self) -> list[GenericCodexEvaluation]: ...
    def investigation_sessions(self) -> list[InvestigationSession]: ...
    def resumable_session_evaluations(self) -> list[ResumableSessionEvaluation]: ...
    def unreal_index_scans(self) -> list[UnrealIndexScan]: ...
    def unreal_artifacts(self, project_id: str | None = None) -> list[UnrealArtifact]: ...
    def unreal_dependencies(self, project_id: str | None = None) -> list[UnrealDependency]: ...
    def project_workspace_records(self) -> list[ProjectWorkspaceRecord]: ...
    def project_tickets(self) -> list[ProjectTicket]: ...
    def ticket_events(self, ticket_id: str | None = None) -> list[TicketEvent]: ...
    def ticket_validation_results(
        self, ticket_id: str | None = None
    ) -> list[TicketValidationResult]: ...
    def implementation_sandboxes(
        self, ticket_id: str | None = None
    ) -> list[ImplementationSandboxAttempt]: ...
    def observer_activities(self) -> list: ...
    def scheduled_work(self) -> list[ScheduledWorkItem]: ...
    def project_governance_policies(self) -> list: ...
    def save_project_record(self, project: ProjectRecord) -> None: ...
    def projects(self) -> list[ProjectRecord]: ...
    def project_scans(self, project_id: str | None = None) -> list[ProjectScan]: ...
    def project_files(
        self, project_id: str | None = None, *, include_deleted: bool = False
    ) -> list[ProjectFile]: ...
    def project_symbols(self, project_id: str | None = None) -> list[ProjectSymbol]: ...
    def project_tests(self, project_id: str | None = None) -> list[ProjectTest]: ...
    def project_dependencies(self, project_id: str | None = None) -> list[ProjectDependency]: ...


def _lineage_tasks(tasks: list[Task], root_id: str) -> list[Task]:
    included = {root_id}
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task.parent_task_id in included and task.id not in included:
                included.add(task.id)
                changed = True
    return [task for task in tasks if task.id in included]


def _ticket_work_item(ticket, records, attempts, manager: TicketManager) -> dict:
    ticket_records = [item for item in records if item.ticket_id == ticket.id]
    ticket_attempts = sorted(
        (item for item in attempts if item.ticket_id == ticket.id),
        key=lambda item: item.created_at,
    )
    plans = [item for item in ticket_records if item.kind == "CHANGE_PLAN"]
    latest_plan = max(plans, key=lambda item: item.created_at) if plans else None
    latest_attempt = ticket_attempts[-1] if ticket_attempts else None
    closure_gates, closure_failures = manager.closure_report(ticket)
    action, label, detail, urgency = (
        "INVESTIGATE", "Investigate or plan", "Start with current project evidence.", "NORMAL"
    )
    if ticket.status == "SATISFIED":
        action, label, detail, urgency = (
            "CLOSE", "Close completed ticket", "The acceptance gates are satisfied.", "NORMAL"
        )
    elif ticket.status in {"CLOSED", "REJECTED"}:
        action, label, detail, urgency = (
            "DONE", "No action required", f"Ticket is {ticket.status.lower()}.", "NONE"
        )
    elif latest_attempt and latest_attempt.promotion and latest_attempt.promotion.mutation_journal \
            and not latest_attempt.promotion.mutation_journal.terminal:
        action, label, detail, urgency = (
            "RECOVER", "Recover interrupted promotion",
            latest_attempt.promotion.mutation_journal.stage, "URGENT",
        )
    elif latest_attempt and latest_attempt.status == "PROMOTED" \
            and latest_attempt.promotion and not latest_attempt.promotion.reconciliation:
        action, label, detail, urgency = (
            "RECONCILE", "Reconcile promoted changes",
            "Update the graph from the promoted files.", "HIGH",
        )
    elif latest_attempt and latest_attempt.status == "READY_FOR_REVIEW":
        unmet = [
            item for item in latest_attempt.validation_decisions
            if item.status not in {"PASSED", "SATISFIED"}
        ]
        if unmet:
            action, label, detail, urgency = (
                "VALIDATE", "Complete validation",
                f"{len(unmet)} validation requirement(s) remain.", "HIGH",
            )
        elif not latest_attempt.promotion_approval:
            action, label, detail, urgency = (
                "APPROVE_PROMOTION", "Review promotion",
                "All validations passed; a human promotion decision is required.", "HIGH",
            )
        elif latest_attempt.promotion_approval.decision == "APPROVED" \
                and not latest_attempt.promotion:
            action, label, detail, urgency = (
                "PROMOTE", "Promote approved patch",
                "Apply the exact approved bytes inside the fenced write boundary.", "HIGH",
            )
    elif latest_plan and latest_plan.approval_status != "APPROVED":
        action, label, detail, urgency = (
            "APPROVE_PLAN", "Review implementation plan",
            "A human plan decision is required before implementation.", "HIGH",
        )
    elif latest_plan and not any(
        item.plan_record_id == latest_plan.id for item in ticket_attempts
    ):
        action, label, detail, urgency = (
            "IMPLEMENT", "Create isolated implementation",
            "The approved plan is ready for a disposable sandbox.", "NORMAL",
        )
    elif not closure_failures:
        action, label, detail, urgency = (
            "COMPLETE", "Complete ticket",
            "Every acceptance gate is resolved.", "HIGH",
        )
    elif ticket_records or ticket_attempts:
        action, label, detail, urgency = (
            "RESOLVE_CRITERIA", "Resolve acceptance gates",
            f"{len(closure_failures)} completion gate(s) remain.", "NORMAL",
        )
    if ticket.status == "BLOCKED" and urgency == "NORMAL":
        action, label, detail, urgency = (
            "RESOLVE_BLOCKER",
            "Review ticket blocker",
            "This ticket is explicitly blocked; review its recorded blocker before continuing.",
            "HIGH",
        )
    budget_checks = (
        (ticket.usage.tokens, ticket.budget.max_tokens, "token"),
        (ticket.usage.model_calls, ticket.budget.max_model_calls, "model-call"),
        (ticket.usage.worker_calls, ticket.budget.max_worker_calls, "worker-call"),
        (ticket.usage.wall_time_seconds, ticket.budget.max_wall_time_seconds, "wall-time"),
        (ticket.usage.deepest_branch, ticket.budget.max_branch_depth, "branch-depth"),
    )
    exhausted = [name for used, limit, name in budget_checks if used >= limit]
    if exhausted and urgency != "URGENT" and action not in {"DONE", "CLOSE"}:
        action, label, detail, urgency = (
            "BUDGET_BLOCKED",
            "Review exhausted budget",
            "No further work can start: " + ", ".join(exhausted) + " budget exhausted.",
            "HIGH",
        )
    return {
        "ticket_id": ticket.id,
        "project_id": ticket.project_id,
        "title": ticket.title,
        "priority": ticket.priority,
        "status": ticket.status,
        "action": action,
        "action_label": label,
        "detail": detail,
        "urgency": urgency,
        "closure_ready": not closure_failures,
        "resolved_criteria": sum(item.resolved for item in closure_gates),
        "total_criteria": len(closure_gates),
        "exhausted_budgets": exhausted,
        "updated_at": ticket.updated_at.isoformat(),
    }


def build_dashboard_snapshot(
    store: DashboardStore, root_id: str = DEMO_ROOT_ID, *, running: bool = False
) -> dict[str, Any]:
    """Turn persisted graph records into a browser-ready, JSON-free view model."""
    all_tasks = store.tasks()
    projects = store.projects()
    project_roots = {str(Path(project.root).resolve()).casefold() for project in projects}
    lineage = _lineage_tasks(all_tasks, root_id)
    tasks_by_id = {task.id: task for task in lineage}
    tasks_by_id.update(
        {
            task.id: task
            for task in all_tasks
            if str(Path(task.project_root).resolve()).casefold() in project_roots
        }
    )
    tasks = list(tasks_by_id.values())
    task_ids = {task.id for task in tasks}
    all_edges = store.edges()
    attempts = [
        attempt
        for task in tasks
        if task.kind == TaskKind.RESOLUTION
        for attempt in store.resolution_attempts(task.id)
    ]
    attempt_ids = {attempt.id for attempt in attempts}
    cluster_ids = {task.conflict_cluster_id for task in tasks if task.conflict_cluster_id}
    clusters = [cluster for cluster in store.conflict_clusters() if cluster.id in cluster_ids]
    verdicts = [
        verdict for verdict in store.conflict_verdicts() if verdict.resolution_task_id in task_ids
    ]
    verdict_ids = {verdict.id for verdict in verdicts}
    reconstructions = [
        session for session in store.reconstructions() if session.task_id in task_ids
    ]
    reconstruction_ids = {session.id for session in reconstructions}
    reconstruction_step_ids = {step.id for session in reconstructions for step in session.steps}
    promotions = [
        decision for decision in store.promotion_decisions() if decision.task_id in task_ids
    ]
    promotion_ids = {decision.id for decision in promotions}
    benchmarks = [run for run in store.benchmark_runs() if run.task_id in task_ids]
    benchmark_ids = {run.id for run in benchmarks}
    pathways = [
        pathway for pathway in store.pathways() if set(pathway.supporting_task_ids) & task_ids
    ]
    pathway_ids = {pathway.id for pathway in pathways}
    pathway_decisions = [
        decision
        for decision in store.pathway_decisions()
        if set(decision.candidate_task_ids) & task_ids
    ]
    pathway_decision_ids = {decision.id for decision in pathway_decisions}
    pathway_benchmarks = [
        result for result in store.pathway_benchmarks() if result.pathway_id in pathway_ids
    ]
    pathway_benchmark_ids = {result.id for result in pathway_benchmarks}
    plan_decisions = store.plan_decisions(root_id)
    plan_decision_ids = {decision.id for decision in plan_decisions}
    planning_runs = store.planning_runs(root_id)
    planning_run_ids = {run.id for run in planning_runs}
    execution_attempts = [
        attempt
        for attempt in store.execution_attempts()
        if attempt.root_task_id == root_id and attempt.task_id in task_ids
    ]
    execution_attempt_ids = {attempt.id for attempt in execution_attempts}
    route_predictions = [
        prediction
        for prediction in store.route_predictions()
        if prediction.root_task_id == root_id and prediction.task_id in task_ids
    ]
    route_prediction_ids = {prediction.id for prediction in route_predictions}
    policy_updates = [
        update for update in store.routing_policy_updates() if update.root_task_id == root_id
    ]
    policy_update_ids = {update.id for update in policy_updates}
    route_evaluations = [
        evaluation
        for evaluation in store.route_evaluations()
        if evaluation.prediction_id in route_prediction_ids
    ]
    route_evaluation_ids = {evaluation.id for evaluation in route_evaluations}
    repair_proposals = [
        proposal
        for proposal in getattr(store, "repair_proposals", list)()
        if proposal.repair_task_id in task_ids
    ]
    repair_proposal_ids = {proposal.id for proposal in repair_proposals}
    repair_validations = [
        validation
        for validation in getattr(store, "repair_validations", list)()
        if validation.proposal_id in repair_proposal_ids
    ]
    repair_validation_ids = {validation.id for validation in repair_validations}
    repair_approvals = [
        approval
        for approval in getattr(store, "repair_approvals", list)()
        if approval.proposal_id in repair_proposal_ids
    ]
    repair_approval_ids = {approval.id for approval in repair_approvals}
    repair_promotions = [
        promotion
        for promotion in getattr(store, "repair_promotions", list)()
        if promotion.proposal_id in repair_proposal_ids
    ]
    repair_promotion_ids = {promotion.id for promotion in repair_promotions}
    post_repair_reconciliations = [
        reconciliation
        for reconciliation in getattr(store, "post_repair_reconciliations", list)()
        if reconciliation.promotion_id in repair_promotion_ids
    ]
    post_repair_reconciliation_ids = {
        reconciliation.id for reconciliation in post_repair_reconciliations
    }
    maintenance_workflows = [
        workflow
        for workflow in getattr(store, "maintenance_workflows", list)()
        if workflow.diagnosis_task_id in task_ids
        or str(Path(workflow.project_root).resolve()).casefold() in project_roots
    ]
    maintenance_workflow_ids = {workflow.id for workflow in maintenance_workflows}
    project_leases = [
        lease
        for lease in getattr(store, "project_leases", list)()
        if str(Path(lease.project_root).resolve()).casefold() in project_roots
    ]
    project_lease_ids = {lease.id for lease in project_leases}
    evaluation_runs = list(getattr(store, "evaluation_runs", list)())
    evaluation_run_ids = {run.id for run in evaluation_runs}
    evaluation_results = [result for run in evaluation_runs for result in run.results]
    evaluation_result_ids = {result.id for result in evaluation_results}
    codex_readonly_proofs = list(getattr(store, "codex_readonly_proofs", list)())
    recursive_codex_proofs = list(getattr(store, "recursive_codex_proofs", list)())
    generic_codex_evaluations = list(
        getattr(store, "generic_codex_evaluations", list)()
    )
    investigation_sessions = list(getattr(store, "investigation_sessions", list)())
    resumable_session_evaluations = list(
        getattr(store, "resumable_session_evaluations", list)()
    )
    unreal_index_scans = list(getattr(store, "unreal_index_scans", list)())
    unreal_artifacts = list(getattr(store, "unreal_artifacts", list)())
    unreal_dependencies = list(getattr(store, "unreal_dependencies", list)())
    project_workspace_records = list(getattr(store, "project_workspace_records", list)())
    project_tickets = list(getattr(store, "project_tickets", list)())
    ticket_events = list(getattr(store, "ticket_events", list)())
    ticket_validations = list(getattr(store, "ticket_validation_results", list)())
    implementation_sandboxes = list(getattr(store, "implementation_sandboxes", list)())
    project_ids = {project.id for project in projects}
    project_scans = [scan for scan in store.project_scans() if scan.project_id in project_ids]
    project_scan_ids = {scan.id for scan in project_scans}
    project_files = [
        item for item in store.project_files(include_deleted=True) if item.project_id in project_ids
    ]
    project_symbols = [item for item in store.project_symbols() if item.project_id in project_ids]
    project_tests = [item for item in store.project_tests() if item.project_id in project_ids]
    project_dependencies = [
        item for item in store.project_dependencies() if item.project_id in project_ids
    ]
    relevant_project_paths = {
        path.replace("\\", "/") for task in tasks for path in task.relevant_files
    }
    if not relevant_project_paths:
        relevant_project_paths = {
            item.path for item in sorted(project_files, key=lambda candidate: candidate.path)[:200]
        }
    visible_project_files = [
        item
        for item in project_files
        if item.path in relevant_project_paths or item.lifecycle.value != "ACTIVE"
    ]
    visible_project_file_ids = {item.id for item in visible_project_files}
    visible_project_dependencies = [
        item
        for item in project_dependencies
        if item.source_file_id in visible_project_file_ids
        or item.target_file_id in visible_project_file_ids
    ]
    visible_project_dependency_ids = {item.id for item in visible_project_dependencies}
    visible_project_symbols = [
        item for item in project_symbols if item.file_id in visible_project_file_ids
    ]
    visible_project_symbol_ids = {item.id for item in visible_project_symbols}
    visible_project_tests = [
        item for item in project_tests if item.file_id in visible_project_file_ids
    ]
    visible_project_test_ids = {item.id for item in visible_project_tests}
    all_claims = store.claims()
    all_claim_ids = {claim.id for claim in all_claims}
    claim_ids = {
        node_id
        for edge in all_edges
        if edge.source in task_ids or edge.target in task_ids
        for node_id in (edge.source, edge.target)
        if node_id not in task_ids and node_id not in attempt_ids
    }
    claim_ids.update(claim_id for cluster in clusters for claim_id in cluster.claim_ids)
    claim_ids.update(
        claim_id
        for verdict in verdicts
        for claim_id in verdict.claim_ids + verdict.evidence_claim_ids
    )
    claim_ids.update(claim_id for scan in project_scans for claim_id in scan.invalidated_claim_ids)
    claim_ids.update(
        claim_id for session in reconstructions for claim_id in session.baseline_node_ids
    )
    claim_ids.update(claim_id for pathway in pathways for claim_id in pathway.source_claim_ids)
    claim_ids.update(
        claim_id
        for decision in promotions
        for claim_id in (
            decision.candidate_claim_ids
            + ([decision.promoted_claim_id] if decision.promoted_claim_id else [])
        )
    )
    changed = True
    while changed:
        expanded = {
            node_id
            for edge in all_edges
            if edge.source in claim_ids or edge.target in claim_ids
            for node_id in (edge.source, edge.target)
            if node_id in all_claim_ids
        }
        changed = not expanded.issubset(claim_ids)
        claim_ids.update(expanded)
    claims = [claim for claim in all_claims if claim.id in claim_ids]
    node_ids = (
        task_ids
        | claim_ids
        | attempt_ids
        | cluster_ids
        | verdict_ids
        | reconstruction_ids
        | reconstruction_step_ids
        | promotion_ids
        | benchmark_ids
        | pathway_ids
        | pathway_decision_ids
        | pathway_benchmark_ids
        | plan_decision_ids
        | planning_run_ids
        | execution_attempt_ids
        | route_prediction_ids
        | policy_update_ids
        | route_evaluation_ids
        | repair_proposal_ids
        | repair_validation_ids
        | repair_approval_ids
        | repair_promotion_ids
        | post_repair_reconciliation_ids
        | maintenance_workflow_ids
        | project_lease_ids
        | evaluation_run_ids
        | evaluation_result_ids
        | project_ids
        | project_scan_ids
        | visible_project_file_ids
        | visible_project_symbol_ids
        | visible_project_test_ids
        | visible_project_dependency_ids
    )
    edges = [
        edge.model_dump(mode="json")
        for edge in all_edges
        if edge.source in node_ids and edge.target in node_ids
    ]
    edges.extend(
        {
            "source": lease.id,
            "relation": "LEASES_WORKFLOW",
            "target": lease.workflow_id,
        }
        for lease in project_leases
        if lease.workflow_id in maintenance_workflow_ids
    )
    edges.extend(
        {"source": run.id, "relation": "HAS_EVALUATION_RESULT", "target": result.id}
        for run in evaluation_runs
        for result in run.results
    )

    task_nodes = [
        {
            "id": task.id,
            "node_type": "task",
            "kind": task.kind.value,
            "title": task.question,
            "status": task.status.value,
            "depth": task.depth,
            "parent_id": task.parent_task_id,
            "attempt_count": task.attempt_count,
            "stopping_reason": task.stopping_reason.value if task.stopping_reason else None,
            "last_error": task.last_error,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "evidence_gap": task.evidence_gap,
            "output_claim_id": task.output_claim_id,
            "conflict_cluster_id": task.conflict_cluster_id,
            "conflict_verdict_id": task.conflict_verdict_id,
            "reused_verdict_id": task.reused_verdict_id,
            "reused_claim_id": task.reused_claim_id,
            "reuse_type": task.reuse_type,
            "relevance_score": task.relevance_score,
            "reuse_reason": task.reuse_reason,
            "files": task.relevant_files,
            "source_claim_ids": task.source_claim_ids,
            "project_root": task.project_root,
        }
        for task in tasks
    ]
    claim_nodes = [
        {
            "id": claim.id,
            "node_type": "claim",
            "kind": claim.kind.value,
            "title": claim.conclusion,
            "status": claim.validity_status.value,
            "confidence": claim.confidence,
            "conclusion": claim.conclusion,
            "producer": claim.producer,
            "evidence": [item.model_dump(mode="json") for item in claim.evidence],
            "files": claim.files_examined,
            "assertions": [item.model_dump(mode="json") for item in claim.assertions],
            "unresolved_questions": claim.unresolved_questions,
            "source_task_id": claim.source_task_id,
            "source_claim_ids": claim.source_claim_ids,
            "source_files": [item.model_dump(mode="json") for item in claim.source_files],
            "source_commit": claim.source_commit,
            "learned_at": claim.learned_at.isoformat(),
            "valid_from": claim.valid_from,
            "valid_until": claim.valid_until,
            "validity_reason": claim.validity_reason,
            "validity_history": [item.model_dump(mode="json") for item in claim.validity_history],
            "superseded_by_claim_id": claim.superseded_by_claim_id,
            "memory_tier": claim.memory_tier.value,
            "memory_lifecycle": claim.memory_lifecycle.value,
            "tier_history": [item.model_dump(mode="json") for item in claim.tier_history],
            "promoted_to_claim_id": claim.promoted_to_claim_id,
            "successful_reuse_count": claim.successful_reuse_count,
            "memory_policy_decision_id": claim.memory_policy_decision_id,
            "conflict_verdict_id": claim.conflict_verdict_id,
        }
        for claim in claims
    ]
    attempt_nodes = [
        {
            "id": attempt.id,
            "node_type": "attempt",
            "kind": "RESOLUTION_ATTEMPT",
            "title": attempt.result.rationale,
            "status": attempt.result.selected_claim.value.upper(),
            "confidence": attempt.result.confidence,
            "selected_claim": attempt.result.selected_claim.value,
            "rationale": attempt.result.rationale,
            "evidence": [item.model_dump(mode="json") for item in attempt.result.evidence],
            "evidence_claim_ids": attempt.evidence_claim_ids,
            "unresolved_questions": attempt.result.unresolved_questions,
            "created_at": attempt.created_at.isoformat(),
        }
        for attempt in attempts
    ]
    cluster_nodes = [
        {
            "id": cluster.id,
            "node_type": "cluster",
            "kind": "CONFLICT_CLUSTER",
            "title": cluster.assertion_key,
            "status": cluster.status.value,
            "claim_ids": cluster.claim_ids,
            "interpretations": [item.model_dump(mode="json") for item in cluster.interpretations],
            "corroborated_claim_ids": cluster.corroborated_claim_ids,
            "outlier_claim_ids": cluster.outlier_claim_ids,
            "selected_value": cluster.selected_value,
            "resolved_claim_id": cluster.resolved_claim_id,
        }
        for cluster in clusters
    ]
    verdict_nodes = [
        {
            "id": verdict.id,
            "node_type": "conflict_verdict",
            "kind": "CONFLICT_VERDICT",
            "title": verdict.rationale,
            "status": verdict.status.value,
            **verdict.model_dump(mode="json"),
        }
        for verdict in verdicts
    ]
    reconstruction_nodes = [
        {
            "id": session.id,
            "node_type": "reconstruction",
            "kind": "ACTIVE_RECONSTRUCTION",
            "title": session.query,
            "status": session.status.value,
            "seed_node_ids": session.seed_node_ids,
            "selected_node_ids": session.selected_node_ids,
            "pruned_node_ids": session.pruned_node_ids,
            "baseline_node_ids": session.baseline_node_ids,
            "reconstructed_tokens": session.reconstructed_token_estimate,
            "baseline_tokens": session.baseline_token_estimate,
            "required_evidence_ids": session.required_evidence_ids,
            "evidence_preserved": session.evidence_preserved,
            "created_at": session.created_at.isoformat(),
        }
        for session in reconstructions
    ]
    reconstruction_step_nodes = [
        {
            "id": step.id,
            "node_type": "reconstruction_step",
            "kind": step.action.value,
            "title": step.reason,
            "status": step.action.value,
            "sequence": step.sequence,
            "action": step.action.value,
            "claim_id": step.node_id,
            "frontier_node_id": step.frontier_node_id,
            "relation": step.relation.value if step.relation else None,
            "score": step.score,
            "reason": step.reason,
            "token_estimate": step.token_estimate,
            "created_at": step.created_at.isoformat(),
        }
        for session in reconstructions
        for step in session.steps
    ]
    promotion_nodes = [
        {
            "id": decision.id,
            "node_type": "promotion",
            "kind": f"{decision.from_tier.value}_TO_{decision.to_tier.value}",
            "title": decision.reason,
            "status": decision.outcome.value,
            "assertion_key": decision.assertion_key,
            "from_tier": decision.from_tier.value,
            "to_tier": decision.to_tier.value,
            "candidate_claim_ids": decision.candidate_claim_ids,
            "accepted_claim_ids": decision.accepted_claim_ids,
            "rejected_claim_ids": decision.rejected_claim_ids,
            "contradictory_claim_ids": decision.contradictory_claim_ids,
            "stale_claim_ids": decision.stale_claim_ids,
            "promoted_claim_id": decision.promoted_claim_id,
            "policy_version": decision.policy_version,
            "minimum_support": decision.minimum_support,
            "minimum_confidence": decision.minimum_confidence,
            "observed_support": decision.observed_support,
            "observed_confidence": decision.observed_confidence,
            "reason": decision.reason,
            "created_at": decision.created_at.isoformat(),
        }
        for decision in promotions
    ]
    benchmark_nodes = [
        {
            "id": run.id,
            "node_type": "benchmark",
            "kind": "TOKEN_BENCHMARK",
            "title": run.question,
            "status": "PASSED" if run.passed else "FAILED",
            "case_id": run.case_id,
            "expected_answer": run.expected_answer,
            "required_evidence_ids": run.required_evidence_ids,
            "fixed": run.fixed.model_dump(mode="json"),
            "active": run.active.model_dump(mode="json"),
            "traversal_node_ids": run.traversal_node_ids,
            "traversal_edges": [edge.model_dump(mode="json") for edge in run.traversal_edges],
            "token_reduction": run.token_reduction,
            "correctness_preserved": run.correctness_preserved,
            "benchmark_evidence_preserved": run.evidence_preserved,
            "created_at": run.created_at.isoformat(),
        }
        for run in benchmarks
    ]
    pathway_nodes = [
        {
            "id": pathway.id,
            "node_type": "pathway",
            "kind": "VIRTUAL_MEMORY_PATHWAY",
            "title": pathway.token,
            "status": pathway.lifecycle.value,
            **pathway.model_dump(mode="json"),
        }
        for pathway in pathways
    ]
    pathway_decision_nodes = [
        {
            "id": decision.id,
            "node_type": "pathway_decision",
            "kind": "PATHWAY_PROMOTION_POLICY",
            "title": decision.reason,
            "status": decision.outcome.value,
            **decision.model_dump(mode="json"),
        }
        for decision in pathway_decisions
    ]
    pathway_benchmark_nodes = [
        {
            "id": result.id,
            "node_type": "pathway_benchmark",
            "kind": "VIRTUAL_TOKEN_BENCHMARK",
            "title": result.token,
            "status": (
                "PASSED"
                if result.correct and result.evidence_preserved and result.expansion_complete
                else "FAILED"
            ),
            **result.model_dump(mode="json"),
        }
        for result in pathway_benchmarks
    ]
    plan_decision_nodes = [
        {
            "id": decision.id,
            "node_type": "plan_decision",
            "kind": decision.action.value,
            "title": decision.reason,
            "status": decision.stopping_reason.value if decision.stopping_reason else "RECORDED",
            **decision.model_dump(mode="json"),
        }
        for decision in plan_decisions
    ]
    planning_run_nodes = [
        {
            "id": run.id,
            "node_type": "planning_run",
            "kind": "PLANNING_RUN",
            "title": "Recursive planning budget ledger",
            "status": run.status.value,
            **run.model_dump(mode="json"),
        }
        for run in planning_runs
    ]
    execution_nodes = [
        {
            "id": attempt.id,
            "node_type": "execution_attempt",
            "kind": attempt.actual_route.value,
            "title": attempt.worker,
            "status": attempt.outcome.value,
            **attempt.model_dump(mode="json"),
        }
        for attempt in execution_attempts
    ]
    route_prediction_nodes = [
        {
            "id": prediction.id,
            "node_type": "route_prediction",
            "kind": "ROUTE_PREDICTION",
            "title": f"{prediction.static_route.value} → {prediction.chosen_route.value}",
            "status": "CHANGED" if prediction.changed_static_route else "RETAINED",
            **prediction.model_dump(mode="json"),
        }
        for prediction in route_predictions
    ]
    policy_update_nodes = [
        {
            "id": update.id,
            "node_type": "routing_policy_update",
            "kind": f"ROUTING_POLICY_V{update.version}",
            "title": f"{update.from_route.value} → {update.to_route.value}",
            "status": "ACCEPTED" if update.accepted else "REJECTED",
            **update.model_dump(mode="json"),
        }
        for update in policy_updates
    ]
    route_evaluation_nodes = [
        {
            "id": evaluation.id,
            "node_type": "route_evaluation",
            "kind": "PREDICTION_EVALUATION",
            "title": f"Predicted {evaluation.predicted_route.value}",
            "status": "CORRECT" if evaluation.actual_success else "FAILED",
            **evaluation.model_dump(mode="json"),
        }
        for evaluation in route_evaluations
    ]
    project_nodes = [
        {
            "id": project.id,
            "node_type": "project",
            "kind": "READ_ONLY_PROJECT",
            "title": project.root,
            "status": "READ_ONLY" if project.read_only else "UNSAFE",
            **project.model_dump(mode="json"),
        }
        for project in projects
    ]
    project_scan_nodes = [
        {
            "id": scan.id,
            "node_type": "project_scan",
            "kind": "INCREMENTAL_SCAN",
            "title": f"{scan.file_count} files · {scan.parsed_file_count} parsed",
            "status": scan.status.value,
            **scan.model_dump(mode="json"),
        }
        for scan in project_scans
    ]
    project_file_nodes = [
        {
            "id": item.id,
            "node_type": "project_file",
            "kind": "TEST_FILE" if item.is_test else "SOURCE_FILE",
            "title": item.path,
            "status": item.lifecycle.value,
            **item.model_dump(mode="json"),
        }
        for item in visible_project_files
    ]
    project_symbol_nodes = [
        {
            "id": item.id,
            "node_type": "project_symbol",
            "kind": item.kind.value,
            "title": item.qualified_name,
            "status": "INDEXED",
            **item.model_dump(mode="json"),
        }
        for item in visible_project_symbols
    ]
    project_test_nodes = [
        {
            "id": item.id,
            "node_type": "project_test",
            "kind": "TEST",
            "title": item.qualified_name,
            "status": "INDEXED",
            **item.model_dump(mode="json"),
        }
        for item in visible_project_tests
    ]
    project_dependency_nodes = [
        {
            "id": item.id,
            "node_type": "project_dependency",
            "kind": "DEPENDENCY",
            "title": item.import_name,
            "status": "RESOLVED" if item.target_file_id else "EXTERNAL",
            **item.model_dump(mode="json"),
        }
        for item in visible_project_dependencies
    ]
    repair_proposal_nodes = [
        {
            "id": item.id,
            "node_type": "repair_proposal",
            "kind": "SANDBOXED_PATCH",
            "title": f"{len(item.changes)} file patch",
            "status": item.status.value,
            **item.model_dump(mode="json"),
        }
        for item in repair_proposals
    ]
    repair_validation_nodes = [
        {
            "id": item.id,
            "node_type": "repair_validation",
            "kind": "BEFORE_AFTER_TEST",
            "title": f"exit {item.before.exit_code} → {item.after.exit_code}",
            "status": item.status.value,
            **item.model_dump(mode="json"),
        }
        for item in repair_validations
    ]
    repair_approval_nodes = [
        {
            "id": item.id,
            "node_type": "repair_approval",
            "kind": "HUMAN_DECISION",
            "title": f"{item.decision.value} by {item.approved_by}",
            "status": item.decision.value,
            **item.model_dump(mode="json"),
        }
        for item in repair_approvals
    ]
    repair_promotion_nodes = [
        {
            "id": item.id,
            "node_type": "repair_promotion",
            "kind": "REAL_PROJECT_PROMOTION",
            "title": item.status.value.replace("_", " "),
            "status": item.status.value,
            **item.model_dump(mode="json"),
        }
        for item in repair_promotions
    ]
    post_repair_reconciliation_nodes = [
        {
            "id": item.id,
            "node_type": "post_repair_reconciliation",
            "kind": "POST_REPAIR_RECONCILIATION",
            "title": f"{len(item.affected_paths)} affected file reconciled",
            "status": item.status.value,
            **item.model_dump(mode="json"),
        }
        for item in post_repair_reconciliations
    ]
    maintenance_workflow_nodes = [
        {
            "id": item.id,
            "node_type": "maintenance_workflow",
            "kind": "DURABLE_MAINTENANCE_WORKFLOW",
            "title": item.question,
            "status": item.status.value,
            **item.model_dump(mode="json"),
        }
        for item in maintenance_workflows
    ]
    project_lease_nodes = [
        {
            "id": item.id,
            "node_type": "project_lease",
            "kind": "PROJECT_MUTATION_LEASE",
            "title": f"Fence {item.fencing_token} · {item.holder_id}",
            "status": item.status.value,
            **item.model_dump(mode="json"),
        }
        for item in project_leases
    ]
    evaluation_run_nodes = [
        {
            "id": item.id,
            "node_type": "evaluation_run",
            "kind": (
                "DETERMINISTIC_EVALUATION"
            ),
            "title": item.suite_version,
            "status": "PASSED" if item.passed else "FAILED",
            **item.model_dump(mode="json"),
        }
        for item in evaluation_runs
    ]
    evaluation_result_nodes = [
        {
            "id": item.id,
            "node_type": "evaluation_result",
            "kind": (
                item.strategy.value
            ),
            "title": f"{item.case_id} · repeat {item.repetition}",
            "status": "PASSED" if item.correct else "FAILED",
            **item.model_dump(mode="json"),
        }
        for item in evaluation_results
    ]
    codex_readonly_proof_nodes = [
        {
            "id": item.id,
            "node_type": "codex_readonly_proof",
            "kind": "BOUNDED_CODEX_READ_ONLY",
            "title": f"Codex initial → replay · {Path(item.test_path).name}",
            "status": "PASSED" if item.passed else "FAILED",
            **item.model_dump(mode="json"),
        }
        for item in codex_readonly_proofs
    ]
    recursive_codex_proof_nodes = [
        {
            "id": item.id,
            "node_type": "recursive_codex_proof",
            "kind": "RECURSIVE_CODEX_DELEGATION",
            "title": f"Recursive Codex · {len(item.branch_results)} branches",
            "status": "PASSED" if item.passed else "FAILED",
            **item.model_dump(mode="json"),
        }
        for item in recursive_codex_proofs
    ]
    generic_codex_evaluation_nodes = [
        {
            "id": item.id,
            "node_type": "generic_codex_evaluation",
            "kind": "GENERIC_DELEGATION_EVALUATION",
            "title": f"Generic delegation · {item.subsystem_count} subsystems",
            "status": "PASSED" if item.passed else "FAILED",
            **item.model_dump(mode="json"),
        }
        for item in generic_codex_evaluations
    ]
    investigation_session_nodes = [
        {
            "id": item.id,
            "node_type": "investigation_session",
            "kind": "DURABLE_INVESTIGATION_SESSION",
            "title": f"Session · {Path(item.test_path).name}",
            "status": item.status,
            **item.model_dump(mode="json"),
        }
        for item in investigation_sessions
    ]
    resumable_session_evaluation_nodes = [
        {
            "id": item.id,
            "node_type": "resumable_session_evaluation",
            "kind": "RESUMABLE_SESSION_EVALUATION",
            "title": f"Recovery evaluation · {item.subsystem_count} subsystems",
            "status": "PASSED" if item.passed else "FAILED",
            **item.model_dump(mode="json"),
        }
        for item in resumable_session_evaluations
    ]
    unreal_index_scan_nodes = [{"id": item.id, "node_type": "unreal_index_scan", "kind": "UNREAL_READ_ONLY_INDEX", "title": f"Unreal project index · {item.artifact_count} artifacts", "status": "PASSED" if item.source_integrity_verified else "FAILED", **item.model_dump(mode="json"), "scope_name": "Unreal project source"} for item in unreal_index_scans]
    unreal_artifact_nodes = [{"id": item.id, "node_type": "unreal_artifact", "kind": item.kind, "title": item.path, "status": "INDEXED", **item.model_dump(mode="json")} for item in unreal_artifacts]
    unreal_dependency_nodes = [{"id": item.id, "node_type": "unreal_dependency", "kind": item.relation, "title": f"{item.source_path} → {item.target_reference}", "status": "RESOLVED" if item.target_artifact_id else "EXTERNAL", **item.model_dump(mode="json")} for item in unreal_dependencies]
    project_workspace_nodes = [{"id": item.id, "node_type": "project_workspace_result", "kind": "PROJECT_WORKSPACE_RESULT", "title": item.prompt, "status": item.status, **item.model_dump(mode="json"), "workspace_steps": item.steps, "workspace_risks": item.risks, "workspace_validations": item.validation_requirements} for item in project_workspace_records]
    ticket_manager = TicketManager(store)
    ticket_nodes = []
    for item in project_tickets:
        item = ticket_manager.get(item.id)
        closure_gates, closure_failures = ticket_manager.closure_report(item)
        evidence_catalog = ticket_manager.evidence_catalog(item)
        ticket_nodes.append({
            "id": item.id,
            "node_type": "ticket",
            "kind": "PROJECT_TICKET",
            "title": item.title,
            "status": item.status,
            **item.model_dump(mode="json"),
            "ticket_criteria": [
                criterion.model_dump(mode="json") for criterion in item.acceptance_criteria
            ],
            "ticket_constraints": [
                constraint.model_dump(mode="json") for constraint in item.constraints
            ],
            "ticket_budget": item.budget.model_dump(mode="json"),
            "ticket_usage": item.usage.model_dump(mode="json"),
            "closure_ready": not closure_failures,
            "closure_failures": closure_failures,
            "closure_gates": [gate.model_dump(mode="json") for gate in closure_gates],
            "eligible_ticket_evidence": [
                evidence.model_dump(mode="json")
                for evidence in evidence_catalog if evidence.eligible
            ],
            "ineligible_ticket_evidence": [
                evidence.model_dump(mode="json")
                for evidence in evidence_catalog if not evidence.eligible
            ],
        })
    ticket_event_nodes = [{"id": item.id, "node_type": "ticket_event", "kind": item.kind, "title": item.detail, "status": "RECORDED", **item.model_dump(mode="json")} for item in ticket_events]
    ticket_validation_nodes = [{"id": item.id, "node_type": "ticket_validation", "kind": "TICKET_VALIDATION", "title": item.name, "status": item.status, **item.model_dump(mode="json")} for item in ticket_validations]
    implementation_sandbox_nodes = [{"id": item.id, "node_type": "implementation_sandbox", "kind": "DISPOSABLE_IMPLEMENTATION_SANDBOX", "title": f"Sandbox patch · {len(item.changes)} files", "status": item.status, **item.model_dump(mode="json")} for item in implementation_sandboxes]
    nodes = (
        task_nodes
        + reconstruction_nodes
        + reconstruction_step_nodes
        + promotion_nodes
        + benchmark_nodes
        + pathway_nodes
        + pathway_decision_nodes
        + pathway_benchmark_nodes
        + planning_run_nodes
        + plan_decision_nodes
        + execution_nodes
        + route_prediction_nodes
        + policy_update_nodes
        + route_evaluation_nodes
        + cluster_nodes
        + verdict_nodes
        + project_nodes
        + project_scan_nodes
        + project_file_nodes
        + project_symbol_nodes
        + project_test_nodes
        + project_dependency_nodes
        + repair_proposal_nodes
        + repair_validation_nodes
        + repair_approval_nodes
        + repair_promotion_nodes
        + post_repair_reconciliation_nodes
        + maintenance_workflow_nodes
        + project_lease_nodes
        + evaluation_run_nodes
        + evaluation_result_nodes
        + codex_readonly_proof_nodes
        + recursive_codex_proof_nodes
        + generic_codex_evaluation_nodes
        + investigation_session_nodes
        + resumable_session_evaluation_nodes
        + unreal_index_scan_nodes
        + unreal_artifact_nodes
        + unreal_dependency_nodes
        + project_workspace_nodes
        + ticket_nodes
        + ticket_event_nodes
        + ticket_validation_nodes
        + implementation_sandbox_nodes
        + claim_nodes
        + attempt_nodes
    )
    root = next((task for task in tasks if task.id == root_id), None)
    follow_ups = [task for task in tasks if task.kind == TaskKind.FOLLOW_UP]
    confidence_values = [claim.confidence for claim in claims if claim.evidence]
    codex_calls = len(attempts) + sum(task.attempt_count for task in follow_ups)
    work_items = [
        _ticket_work_item(
            ticket, project_workspace_records, implementation_sandboxes, ticket_manager
        )
        for ticket in project_tickets
    ]
    urgency_order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "NONE": 3}
    work_items.sort(
        key=lambda item: (
            urgency_order[item["urgency"]],
            {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(
                item["priority"], 4
            ),
            item["updated_at"],
        )
    )
    durable_activities = [
        item.model_dump(mode="json")
        for item in getattr(store, "observer_activities", list)()
    ]
    scheduled_work = [
        item.model_dump(mode="json")
        for item in getattr(store, "scheduled_work", list)()
    ]
    governance_policies = [
        item.model_dump(mode="json")
        for item in getattr(store, "project_governance_policies", list)()
    ]
    actionable = [item for item in work_items if item["action"] != "DONE"]
    activity_focus = next(
        (
            item.get("ticket_id") for item in durable_activities
            if item.get("ticket_id")
            and item.get("status") in {"QUEUED", "RUNNING", "INTERRUPTED"}
        ),
        None,
    )

    call_ledger = model_call_ledger()
    measurement_started_at = call_ledger.measurement_started_at if call_ledger else ""

    def measured_now(item) -> bool:
        created = getattr(item, "created_at", None)
        if not measurement_started_at or created is None:
            return not measurement_started_at
        return created.isoformat() >= measurement_started_at

    measured_benchmarks = [item for item in benchmarks if measured_now(item)]
    measured_pathway_benchmarks = [item for item in pathway_benchmarks if measured_now(item)]
    measured_codex_proofs = [item for item in codex_readonly_proofs if measured_now(item)]
    measured_generic_evaluations = [item for item in generic_codex_evaluations if measured_now(item)]
    measured_resumable_evaluations = [item for item in resumable_session_evaluations if measured_now(item)]
    comparison_baseline_tokens = sum(item.fixed.total_tokens for item in measured_benchmarks)
    comparison_rlm_tokens = sum(item.active.total_tokens for item in measured_benchmarks)
    comparison_baseline_tokens += sum(
        item.active_input_tokens for item in measured_pathway_benchmarks
    )
    comparison_rlm_tokens += sum(item.token_input_tokens for item in measured_pathway_benchmarks)
    comparison_baseline_tokens += sum(
        item.fresh_baseline_input_tokens + item.fresh_baseline_output_tokens
        for item in measured_codex_proofs
    )
    comparison_rlm_tokens += sum(
        item.input_tokens + item.output_tokens for item in measured_codex_proofs
    )
    comparison_baseline_tokens += sum(
        item.fresh_input_tokens for item in measured_generic_evaluations
    )
    comparison_rlm_tokens += sum(
        item.reuse_input_tokens for item in measured_generic_evaluations
    )
    comparison_baseline_tokens += sum(
        item.avoided_input_tokens for item in measured_resumable_evaluations
    )
    measured_avoided_tokens = max(
        0, comparison_baseline_tokens - comparison_rlm_tokens
    )
    token_comparison_count = (
        len(measured_benchmarks)
        + len(measured_pathway_benchmarks)
        + len(measured_codex_proofs)
        + len(measured_generic_evaluations)
        + len(measured_resumable_evaluations)
    )
    legacy_unmetered_model_calls = sum(item.model_calls for item in implementation_sandboxes)
    call_metrics = call_ledger.summary() if call_ledger is not None else {
        "model_call_count": 0,
        "metered_total_tokens": 0,
        "provider_measured_tokens": 0,
        "estimated_tokens": 0,
        "provider_measured_calls": 0,
        "estimated_call_count": 0,
        "failed_model_calls": 0,
        "local_observed_input_tokens": 0,
        "provider_unexplained_input_tokens": 0,
        "provider_cached_input_tokens": 0,
        "provider_uncached_input_tokens": 0,
        "provider_unexplained_uncached_input_tokens": 0,
        "provider_measurement_coverage_percent": 0.0,
        "measurement_started_at": "",
        "excluded_historical_calls": 0,
        "excluded_historical_tokens": 0,
    }
    token_diagnostics = call_ledger.diagnostics() if call_ledger is not None else []
    runtime_token_usage = (
        int(call_metrics["metered_total_tokens"])
        if call_ledger is not None
        else sum(item.total_tokens for item in execution_attempts)
        + sum(item.retrieval_tokens_used for item in planning_runs)
        + sum(item.tokens_used for item in project_workspace_records)
    )
    potential_token_usage = runtime_token_usage + measured_avoided_tokens

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "connected": True,
        "running": running,
        "root_id": root_id,
        "root_status": root.status.value if root else "NOT_SEEDED",
        "nodes": nodes,
        "edges": edges,
        "workspace": {
            "focus_ticket_id": (
                activity_focus
                or (actionable[0]["ticket_id"] if actionable else None)
            ),
            "work_items": work_items,
            "needs_attention": sum(
                item["urgency"] in {"URGENT", "HIGH"} for item in actionable
            ),
            "in_progress": sum(
                item["status"] in {"ACTIVE", "AWAITING_REVIEW", "BLOCKED"}
                for item in work_items
            ),
            "completed": sum(item["action"] == "DONE" for item in work_items),
            "durable_activities": durable_activities,
            "scheduled_work": scheduled_work,
            "governance_policies": governance_policies,
            "leases": [
                {
                    "id": item.id,
                    "project_id": item.project_id,
                    "project_root": item.project_root,
                    "status": item.status.value,
                    "holder_id": item.holder_id,
                    "fencing_token": item.fencing_token,
                    "expires_at": item.expires_at.isoformat(),
                    "events": len(item.events),
                }
                for item in project_leases
            ],
        },
        "metrics": {
            "tasks": len(tasks),
            "codex_calls": codex_calls,
            "resolution_attempts": len(attempts),
            "evidence_claims": sum(bool(claim.evidence) for claim in claims),
            "average_evidence_confidence": (
                sum(confidence_values) / len(confidence_values) if confidence_values else None
            ),
            "active_tasks": sum(task.status == TaskStatus.OPEN for task in tasks),
            "stopped_tasks": sum(task.status == TaskStatus.STOPPED for task in tasks),
            "conflict_clusters": len(clusters),
            "conflict_verdicts": len(verdicts),
            "resolved_verdicts": sum(verdict.status.value == "RESOLVED" for verdict in verdicts),
            "unresolved_verdicts": sum(
                verdict.status.value == "UNRESOLVED" for verdict in verdicts
            ),
            "verdict_reuses": sum(bool(task.reused_verdict_id) for task in tasks),
            "onboarded_projects": len(projects),
            "project_scans": len(project_scans),
            "project_files": sum(item.lifecycle.value == "ACTIVE" for item in project_files),
            "project_symbols": len(project_symbols),
            "project_tests": len(project_tests),
            "project_dependencies": len(project_dependencies),
            "scan_parsed_files": sum(scan.parsed_file_count for scan in project_scans),
            "scan_reused_files": sum(len(scan.reused_file_ids) for scan in project_scans),
            "scan_model_calls": sum(scan.model_calls for scan in project_scans),
            "scan_invalidated_claims": sum(
                len(scan.invalidated_claim_ids) for scan in project_scans
            ),
            "read_only_projects": sum(project.read_only for project in projects),
            "repair_proposals": len(repair_proposals),
            "repair_validations": len(repair_validations),
            "verified_repairs": sum(item.status.value == "VERIFIED" for item in repair_validations),
            "rejected_repairs": sum(item.status.value == "REJECTED" for item in repair_validations),
            "repair_model_calls": sum(item.model_calls for item in repair_proposals),
            "repair_approvals": len(repair_approvals),
            "approved_repairs": sum(item.decision.value == "APPROVED" for item in repair_approvals),
            "repair_promotions": len(repair_promotions),
            "promoted_repairs": sum(item.status.value == "VERIFIED" for item in repair_promotions),
            "rolled_back_repairs": sum(
                item.status.value == "ROLLED_BACK" for item in repair_promotions
            ),
            "post_repair_reconciliations": len(post_repair_reconciliations),
            "reconciled_affected_files": sum(
                len(item.affected_paths) for item in post_repair_reconciliations
            ),
            "reconciled_invalidated_claims": sum(
                len(item.invalidated_claim_ids) for item in post_repair_reconciliations
            ),
            "reconciled_follow_up_worker_calls": sum(
                item.follow_up_worker_calls for item in post_repair_reconciliations
            ),
            "maintenance_workflows": len(maintenance_workflows),
            "waiting_maintenance_workflows": sum(
                item.status.value == "WAITING_FOR_APPROVAL" for item in maintenance_workflows
            ),
            "completed_maintenance_workflows": sum(
                item.status.value == "COMPLETED" for item in maintenance_workflows
            ),
            "rolled_back_maintenance_workflows": sum(
                item.status.value == "ROLLED_BACK" for item in maintenance_workflows
            ),
            "project_leases": len(project_leases),
            "active_project_leases": sum(
                item.status.value == "ACTIVE" and item.expires_at > datetime.now(UTC)
                for item in project_leases
            ),
            "lease_contentions": sum(
                event.kind.value == "CONTENDED" for item in project_leases for event in item.events
            ),
            "lease_reclaims": sum(
                event.kind.value == "RECLAIMED" for item in project_leases for event in item.events
            ),
            "lease_recoveries": sum(
                event.kind.value == "RECOVERY_COMPLETED"
                for item in project_leases
                for event in item.events
            ),
            "scheduled_work": len(scheduled_work),
            "queued_scheduled_work": sum(
                item["status"] in {"QUEUED", "WAITING_FOR_CAPACITY", "WAITING_FOR_LEASE"}
                for item in scheduled_work
            ),
            "active_scheduled_work": sum(
                item["status"] in {"RUNNING", "CANCELLATION_REQUESTED"}
                for item in scheduled_work
            ),
            "cancelled_scheduled_work": sum(
                item["status"] == "CANCELLED" for item in scheduled_work
            ),
            "evaluation_runs": len(evaluation_runs),
            "passed_evaluation_runs": sum(item.passed for item in evaluation_runs),
            "evaluation_results": len(evaluation_results),
            "evaluation_worker_calls": sum(item.worker_calls for item in evaluation_results),
            "evaluation_model_calls": sum(item.model_calls for item in evaluation_results),
            "evaluation_retrieved_tokens": sum(
                item.retrieved_tokens for item in evaluation_results
            ),
            "evaluation_latency_ms": sum(item.latency_ms for item in evaluation_results),
            "evaluation_observed_latency_ms": sum(
                item.observed_latency_ms for item in evaluation_results
            ),
            "evaluation_duplicate_investigations": sum(
                item.duplicate_investigations for item in evaluation_results
            ),
            "evaluation_memory_reuses": sum(item.memory_reuses for item in evaluation_results),
            "codex_readonly_proofs": len(codex_readonly_proofs),
            "passed_codex_readonly_proofs": sum(
                item.passed for item in codex_readonly_proofs
            ),
            "bounded_codex_calls": sum(
                item.initial_codex_calls + item.replay_codex_calls
                for item in codex_readonly_proofs
            ),
            "recursive_codex_proofs": len(recursive_codex_proofs),
            "passed_recursive_codex_proofs": sum(
                item.passed for item in recursive_codex_proofs
            ),
            "delegated_codex_branches": sum(
                len(item.branch_results) for item in recursive_codex_proofs
            ),
            "delegation_initial_calls": sum(
                item.initial_codex_calls for item in recursive_codex_proofs
            ),
            "delegation_replay_calls": sum(
                item.replay_codex_calls for item in recursive_codex_proofs
            ),
            "generic_codex_evaluations": len(generic_codex_evaluations),
            "passed_generic_codex_evaluations": sum(
                item.passed for item in generic_codex_evaluations
            ),
            "generic_codex_subsystems": sum(
                item.subsystem_count for item in generic_codex_evaluations
            ),
            "generic_codex_abstentions": sum(
                item.abstention_verified for item in generic_codex_evaluations
            ),
            "investigation_sessions": len(investigation_sessions),
            "recovered_investigation_sessions": sum(
                item.recovered for item in investigation_sessions
            ),
            "session_checkpoints": sum(
                len(item.checkpoints) for item in investigation_sessions
            ),
            "session_avoided_codex_calls": sum(
                item.avoided_codex_calls for item in investigation_sessions
            ),
            "resumable_session_evaluations": len(resumable_session_evaluations),
            "passed_resumable_session_evaluations": sum(
                item.passed for item in resumable_session_evaluations
            ),
            "unreal_index_scans": len(unreal_index_scans),
            "unreal_artifacts": len(unreal_artifacts),
            "unreal_dependencies": len(unreal_dependencies),
            "project_workspace_results": len(project_workspace_records),
            "project_tickets": len(project_tickets),
            "active_project_tickets": sum(item.status in {"READY", "ACTIVE", "AWAITING_REVIEW"} for item in project_tickets),
            "satisfied_project_tickets": sum(item.status == "SATISFIED" for item in project_tickets),
            "blocked_project_tickets": sum(item.status == "BLOCKED" for item in project_tickets),
            "pending_ticket_criteria": sum(item.status == "PENDING" for ticket in project_tickets for item in ticket.acceptance_criteria),
            "ticket_validations": len(ticket_validations),
            "implementation_sandboxes": len(implementation_sandboxes),
            "reviewable_sandbox_patches": sum(item.status == "READY_FOR_REVIEW" for item in implementation_sandboxes),
            "discarded_sandboxes": sum(item.status == "DISCARDED" for item in implementation_sandboxes),
            "sandbox_mutation_journals": sum(
                bool(item.promotion and item.promotion.mutation_journal)
                for item in implementation_sandboxes
            ),
            "sandbox_promotions_requiring_recovery": sum(
                bool(
                    item.promotion
                    and item.promotion.mutation_journal
                    and not item.promotion.mutation_journal.terminal
                )
                for item in implementation_sandboxes
            ),
            "sandbox_promotion_recoveries": sum(
                item.promotion.mutation_journal.recovery_count
                for item in implementation_sandboxes
                if item.promotion and item.promotion.mutation_journal
            ),
            "sandbox_validation_worker_executions": sum(
                len(item.validation_worker_executions) for item in implementation_sandboxes
            ),
            "passed_sandbox_validation_workers": sum(
                execution.status == "PASSED"
                for item in implementation_sandboxes
                for execution in item.validation_worker_executions
            ),
            "external_sandbox_validation_reports": sum(
                len(item.external_validation_reports) for item in implementation_sandboxes
            ),
            "outlier_claims": sum(len(cluster.outlier_claim_ids) for cluster in clusters),
            "current_claims": sum(claim.validity_status.value == "CURRENT" for claim in claims),
            "invalidated_claims": sum(
                claim.validity_status.value == "INVALIDATED" for claim in claims
            ),
            "superseded_claims": sum(
                claim.validity_status.value == "SUPERSEDED" for claim in claims
            ),
            "reconstructions": len(reconstructions),
            "reconstructed_nodes": sum(
                len(session.selected_node_ids) for session in reconstructions
            ),
            "baseline_nodes": sum(len(session.baseline_node_ids) for session in reconstructions),
            "reconstructed_tokens": sum(
                session.reconstructed_token_estimate for session in reconstructions
            ),
            "baseline_tokens": sum(session.baseline_token_estimate for session in reconstructions),
            "pruned_nodes": sum(len(session.pruned_node_ids) for session in reconstructions),
            "evidence_preserved": all(
                session.evidence_preserved is not False for session in reconstructions
            ),
            "working_memories": sum(claim.memory_tier.value == "WORKING" for claim in claims),
            "episodic_memories": sum(claim.memory_tier.value == "EPISODIC" for claim in claims),
            "semantic_memories": sum(claim.memory_tier.value == "SEMANTIC" for claim in claims),
            "procedural_memories": sum(claim.memory_tier.value == "PROCEDURAL" for claim in claims),
            "promotion_decisions": len(promotions),
            "accepted_promotions": sum(
                decision.outcome.value == "ACCEPTED" for decision in promotions
            ),
            "rejected_promotions": sum(
                decision.outcome.value == "REJECTED" for decision in promotions
            ),
            "benchmark_runs": len(benchmarks),
            "benchmark_passes": sum(run.passed for run in benchmarks),
            "fixed_benchmark_tokens": sum(run.fixed.input_tokens for run in benchmarks),
            "active_benchmark_tokens": sum(run.active.input_tokens for run in benchmarks),
            "benchmark_token_reduction": (
                1
                - sum(run.active.input_tokens for run in benchmarks)
                / sum(run.fixed.input_tokens for run in benchmarks)
                if sum(run.fixed.input_tokens for run in benchmarks)
                else None
            ),
            "benchmark_correctness_preserved": all(run.correctness_preserved for run in benchmarks),
            "benchmark_evidence_preserved": all(run.evidence_preserved for run in benchmarks),
            "benchmark_duplicate_retrievals": sum(
                run.active.duplicate_retrievals for run in benchmarks
            ),
            "virtual_pathways": len(pathways),
            "active_virtual_pathways": sum(
                pathway.lifecycle.value == "ACTIVE" for pathway in pathways
            ),
            "invalidated_virtual_pathways": sum(
                pathway.lifecycle.value == "INVALIDATED" for pathway in pathways
            ),
            "pathway_decisions": len(pathway_decisions),
            "accepted_pathway_promotions": sum(
                decision.outcome.value == "ACCEPTED" for decision in pathway_decisions
            ),
            "pathway_benchmarks": len(pathway_benchmarks),
            "average_pathway_token_reduction": (
                sum(result.additional_reduction for result in pathway_benchmarks)
                / len(pathway_benchmarks)
                if pathway_benchmarks
                else None
            ),
            "plan_decisions": len(plan_decisions),
            "replanning_decisions": sum(
                decision.action.value == "REPLANNED" for decision in plan_decisions
            ),
            "planning_model_calls": sum(run.model_calls_used for run in planning_runs),
            "planning_retrieval_tokens": sum(run.retrieval_tokens_used for run in planning_runs),
            "duplicate_investigations": sum(run.duplicate_investigations for run in planning_runs),
            "execution_attempts": len(execution_attempts),
            "execution_fallbacks": sum(
                bool(attempt.fallback_from_attempt_id) for attempt in execution_attempts
            ),
            "execution_tokens": sum(attempt.total_tokens for attempt in execution_attempts),
            "execution_cost_usd": sum(attempt.estimated_cost_usd for attempt in execution_attempts),
            "execution_latency_ms": sum(attempt.latency_ms for attempt in execution_attempts),
            "total_token_usage": runtime_token_usage,
            "potential_total_token_usage": potential_token_usage,
            "measured_avoided_tokens": measured_avoided_tokens,
            "token_comparison_count": token_comparison_count,
            "unmetered_model_calls": int(call_metrics["estimated_call_count"]),
            "legacy_unmetered_model_calls": legacy_unmetered_model_calls,
            **call_metrics,
            "token_diagnostics": token_diagnostics,
            "route_predictions": len(route_predictions),
            "learned_route_changes": sum(
                prediction.changed_static_route for prediction in route_predictions
            ),
            "routing_policy_version": max((update.version for update in policy_updates), default=0),
            "route_evaluations": len(route_evaluations),
            "route_prediction_success_rate": (
                sum(evaluation.actual_success for evaluation in route_evaluations)
                / len(route_evaluations)
                if route_evaluations
                else None
            ),
            "mean_route_cost_error_usd": (
                sum(evaluation.cost_error_usd for evaluation in route_evaluations)
                / len(route_evaluations)
                if route_evaluations
                else None
            ),
            "mean_route_latency_error_ms": (
                sum(evaluation.latency_error_ms for evaluation in route_evaluations)
                / len(route_evaluations)
                if route_evaluations
                else None
            ),
        },
    }


@dataclass
class DemoController:
    project_root: Path
    process: subprocess.Popen[str] | None = None
    last_output: str = ""
    last_error: str = ""

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _command(self, *arguments: str) -> list[str]:
        return [
            sys.executable,
            str(self.project_root / "examples" / "live_neo4j_demo.py"),
            *arguments,
        ]

    def start(self) -> None:
        if self.running:
            raise RuntimeError("The demonstration is already running")
        self.last_output = ""
        self.last_error = ""
        self.process = subprocess.Popen(
            self._command(),
            cwd=self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        threading.Thread(target=self._collect, daemon=True).start()

    def reset(self) -> None:
        if self.running:
            raise RuntimeError("Wait for the current demonstration to finish before resetting")
        completed = subprocess.run(
            self._command("--reset-only"),
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        self.last_output = completed.stdout
        self.last_error = completed.stderr
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Demo reset failed")

    def _collect(self) -> None:
        assert self.process is not None
        stdout, stderr = self.process.communicate()
        self.last_output = stdout
        self.last_error = stderr


class DashboardApplication:
    def __init__(
        self,
        store: DashboardStore,
        controller: DemoController,
        diagnostic_controller: Any | None = None,
        conflict_controller: Any | None = None,
        workspace_controller: InteractiveProjectWorkspaceController | None = None,
        ticket_manager: TicketManager | None = None,
        sandbox_controller: InteractiveSandboxController | None = None,
        scheduler: ResourceAwareScheduler | None = None,
        automatic_ticket_runner: AutomaticTicketRunner | None = None,
        observer_chat: ObserverChat | None = None,
        model_settings: ModelSettingsManager | None = None,
        conversation_benchmark: ConversationBenchmarkController | None = None,
        project_goal_benchmark: ProjectGoalBenchmarkController | None = None,
        local_profiles: LocalProfileStore | None = None,
        unreal_benchmark: Any | None = None,
    ) -> None:
        self.store = store
        self.controller = controller
        self.diagnostic_controller = diagnostic_controller
        self.conflict_controller = conflict_controller
        self.workspace_controller = workspace_controller
        self.ticket_manager = ticket_manager
        self.sandbox_controller = sandbox_controller
        self.scheduler = scheduler
        self.automatic_ticket_runner = automatic_ticket_runner
        self.observer_chat = observer_chat
        self.model_settings = model_settings
        self.conversation_benchmark = conversation_benchmark
        self.project_goal_benchmark = project_goal_benchmark
        self.local_profiles = local_profiles
        self.unreal_benchmark = unreal_benchmark
        self._snapshot_cache: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self._snapshot_lock = threading.Lock()
        self._chat_progress: dict[str, dict[str, Any]] = {}
        self._chat_progress_lock = threading.Lock()

    def update_chat_progress(self, activity_id: str, stage: str, detail: str) -> None:
        with self._chat_progress_lock:
            prior = self._chat_progress.get(activity_id, {})
            self._chat_progress[activity_id] = {
                "activity_id": activity_id,
                "stage": stage,
                "detail": detail,
                "status": "FAILED" if stage == "FAILED" else "COMPLETE" if stage == "COMPLETE" else "ACTIVE",
                "sequence": int(prior.get("sequence", 0)) + 1,
                "updated_at": datetime.now(UTC).isoformat(),
            }

    def chat_progress(self, activity_id: str) -> dict[str, Any]:
        with self._chat_progress_lock:
            return dict(self._chat_progress.get(activity_id, {
                "activity_id": activity_id,
                "stage": "QUEUED",
                "detail": "The request is waiting to enter the chat pipeline.",
                "status": "ACTIVE",
                "sequence": 0,
            }))

    def invalidate(self) -> None:
        with self._snapshot_lock:
            self._snapshot_cache = None
            self._snapshot_at = 0.0

    def _refresh_durable_activities(self, result: dict[str, Any]) -> None:
        workspace = result.get("workspace")
        if isinstance(workspace, dict):
            workspace["durable_activities"] = [
                item.model_dump(mode="json")
                for item in getattr(self.store, "observer_activities", list)()
            ]
            workspace["scheduled_work"] = [
                item.model_dump(mode="json")
                for item in getattr(self.store, "scheduled_work", list)()
            ]
            if self.scheduler is not None:
                active = [
                    item for item in getattr(self.store, "scheduled_work", list)()
                    if item.status in {"RUNNING", "CANCELLATION_REQUESTED"}
                ]
                workspace["scheduler_limits"] = {
                    **self.scheduler.limits.model_dump(mode="json"),
                    "active_jobs": len(active),
                    "used_capacity_units": sum(item.capacity_units for item in active),
                }

    def _add_conversation_benchmark(self, result: dict[str, Any]) -> None:
        if self.conversation_benchmark is None:
            return
        state = self.conversation_benchmark.snapshot()
        result["conversation_benchmark"] = state
        benchmark = state.get("result")
        if not isinstance(benchmark, dict) or benchmark.get("status") != "COMPLETED":
            return
        ledger = model_call_ledger()
        if ledger and str(benchmark.get("created_at", "")) < ledger.measurement_started_at:
            return
        metrics = dict(result.get("metrics", {}))
        savings = max(0, int(benchmark.get("tokens_saved", 0)))
        metrics["measured_avoided_tokens"] = savings
        metrics["token_comparison_count"] = 1
        metrics["potential_total_token_usage"] = int(
            metrics.get("total_token_usage", 0)
        ) + savings
        result["metrics"] = metrics

    def _add_project_goal_benchmark(self, result: dict[str, Any]) -> None:
        if self.project_goal_benchmark is None:
            return
        state = self.project_goal_benchmark.snapshot()
        result["project_goal_benchmark"] = state
        benchmark = state.get("result")
        if not isinstance(benchmark, dict) or benchmark.get("status") != "COMPLETED":
            return
        ledger = model_call_ledger()
        if ledger and str(benchmark.get("created_at", "")) < ledger.measurement_started_at:
            return
        metrics = dict(result.get("metrics", {}))
        savings = max(0, int(benchmark.get("tokens_saved", 0)))
        metrics["measured_avoided_tokens"] = savings
        metrics["token_comparison_count"] = 1
        metrics["potential_total_token_usage"] = int(
            metrics.get("total_token_usage", 0)
        ) + savings
        result["metrics"] = metrics

    def _add_system_workspace(self, result: dict[str, Any]) -> None:
        if self.observer_chat is None:
            return
        result["system_workspace"] = (
            self.observer_chat.architecture_projector.system_workspace().model_dump(mode="json")
        )

    def snapshot(self) -> dict[str, Any]:
        running = self.controller.running
        workspace_state = (
            self.workspace_controller.snapshot() if self.workspace_controller is not None else None
        )
        with self._snapshot_lock:
            if (
                self._snapshot_cache is not None
                and time.monotonic() - self._snapshot_at < 5.0
                and self._snapshot_cache["running"] == running
                and (
                    not workspace_state
                    or not workspace_state.get("result_id")
                    or any(
                        item["id"] == workspace_state["result_id"]
                        for item in self._snapshot_cache["nodes"]
                    )
                )
            ):
                result = dict(self._snapshot_cache)
                if self.diagnostic_controller is not None:
                    result["diagnostic"] = self.diagnostic_controller.snapshot()
                if self.conflict_controller is not None:
                    result["conflict"] = self.conflict_controller.snapshot()
                if self.workspace_controller is not None:
                    result["project_workspace"] = workspace_state
                if self.sandbox_controller is not None:
                    result["implementation_sandbox"] = self.sandbox_controller.snapshot()
                if self.automatic_ticket_runner is not None:
                    result["automatic_tickets"] = self.automatic_ticket_runner.snapshot()
                self._add_conversation_benchmark(result)
                self._add_project_goal_benchmark(result)
                if self.unreal_benchmark is not None:
                    result["unreal_benchmark"] = self.unreal_benchmark.snapshot()
                self._add_system_workspace(result)
                self._refresh_durable_activities(result)
                return result
            result = build_dashboard_snapshot(self.store, running=running)
            result["control"] = {
                "last_output": self.controller.last_output,
                "last_error": self.controller.last_error,
            }
            self._snapshot_cache = result
            self._snapshot_at = time.monotonic()
            if self.diagnostic_controller is not None:
                result = dict(result)
                result["diagnostic"] = self.diagnostic_controller.snapshot()
            if self.conflict_controller is not None:
                result = dict(result)
                result["conflict"] = self.conflict_controller.snapshot()
            if self.workspace_controller is not None:
                result = dict(result)
                result["project_workspace"] = workspace_state
            if self.sandbox_controller is not None:
                result = dict(result)
                result["implementation_sandbox"] = self.sandbox_controller.snapshot()
            if self.automatic_ticket_runner is not None:
                result = dict(result)
                result["automatic_tickets"] = self.automatic_ticket_runner.snapshot()
            self._add_conversation_benchmark(result)
            self._add_project_goal_benchmark(result)
            if self.unreal_benchmark is not None:
                result["unreal_benchmark"] = self.unreal_benchmark.snapshot()
            self._add_system_workspace(result)
            self._refresh_durable_activities(result)
            return result


def select_project_directory() -> str | None:
    """Open a local directory chooser without reading or registering the selection."""
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(
            "Folder browsing is unavailable on this machine; enter the absolute path instead."
        ) from exc

    dialog_root = None
    try:
        dialog_root = tkinter.Tk()
        dialog_root.withdraw()
        dialog_root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=dialog_root,
            title="Select project root",
            mustexist=True,
        )
    except tkinter.TclError as exc:
        raise RuntimeError(
            "Folder browsing is unavailable in this desktop session; enter the absolute path instead."
        ) from exc
    finally:
        if dialog_root is not None:
            dialog_root.destroy()

    if not selected:
        return None
    return str(ProjectSelection.explicit(selected).root)


def default_observer_database() -> Path:
    """Keep Observer state outside repositories so any repository can be connected."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        state_root = Path(os.environ["LOCALAPPDATA"]) / "RLMGraph"
    else:
        state_root = (
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "rlmgraph"
        )
    return state_root / "observer.db"


def _chat_turn_payload(store, turn, tasks=None) -> dict[str, Any]:
    payload = turn.model_dump(mode="json")
    if turn.claim_id:
        claim = store.get_claim(turn.claim_id)
        if claim and claim.project_root:
            project = next(
                (
                    item for item in store.projects()
                    if Path(item.root).resolve() == Path(claim.project_root).resolve()
                ),
                None,
            )
            payload["work_project_id"] = project.id if project else None
    if not turn.task_id:
        return payload
    tasks = list(tasks if tasks is not None else store.tasks())
    selected_ids = {turn.task_id}
    changed = True
    while changed:
        before = len(selected_ids)
        selected_ids.update(task.id for task in tasks if task.parent_task_id in selected_ids)
        changed = len(selected_ids) != before
    payload["task_tree"] = [
        {
            "id": task.id, "parent_task_id": task.parent_task_id,
            "question": task.question, "depth": task.depth,
            "status": task.status.value,
            "route": task.route.value if task.route else None,
            "reused_claim_id": task.reused_claim_id,
            "output_claim_id": task.output_claim_id,
            "stopping_reason": task.stopping_reason.value if task.stopping_reason else None,
        }
        for task in tasks if task.id in selected_ids
    ]
    return payload


def _handler(application: DashboardApplication):
    class Handler(BaseHTTPRequestHandler):
        def _request_json(self, max_bytes: int = 4096) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > max_bytes:
                raise ValueError(f"Request body must be between 1 and {max_bytes} bytes.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise TypeError("Request body must be a JSON object.")
            return payload

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _download(self, filename: str, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self._json(HTTPStatus.NO_CONTENT, {})

        def _profile_token(self) -> str:
            value = self.headers.get("Authorization", "").strip()
            return value[7:].strip() if value.lower().startswith("bearer ") else ""

        def _authenticated_profile(self) -> dict[str, Any]:
            if application.local_profiles is None:
                raise RuntimeError("Local profiles are unavailable.")
            return application.local_profiles.authenticate(self._profile_token())

        def do_GET(self) -> None:
            try:
                request = urlparse(self.path)
                if request.path == "/api/snapshot":
                    self._json(HTTPStatus.OK, application.snapshot())
                elif request.path == "/api/tickets/export":
                    ticket_id = parse_qs(request.query).get("ticket_id", [""])[0]
                    package = TicketAuditExporter(application.store).build(ticket_id)
                    self._download(f"{ticket_id}-audit.json", package)
                elif request.path == "/api/diagnostics/options":
                    if application.diagnostic_controller is None:
                        raise RuntimeError("Interactive diagnostics are unavailable.")
                    self._json(HTTPStatus.OK, application.diagnostic_controller.options())
                elif self.path == "/api/workspace/options":
                    if application.workspace_controller is None:
                        raise RuntimeError("The project workspace is unavailable.")
                    self._json(HTTPStatus.OK, application.workspace_controller.options())
                elif self.path == "/api/health":
                    self._json(HTTPStatus.OK, {"status": "ok"})
                elif self.path == "/api/profiles":
                    if application.local_profiles is None:
                        raise RuntimeError("Local profiles are unavailable.")
                    self._json(HTTPStatus.OK, {
                        "profiles": application.local_profiles.public_profiles()
                    })
                elif self.path == "/api/profiles/me":
                    self._json(HTTPStatus.OK, {"profile": self._authenticated_profile()})
                elif request.path == "/api/lessons":
                    self._authenticated_profile()
                    from .learning import LessonLibrary
                    project_id = parse_qs(request.query).get("project_id", [""])[0]
                    self._json(HTTPStatus.OK, {"lessons": LessonLibrary(application.store).list(project_id)})
                elif request.path == "/api/learning/documents":
                    from .document_learning import DocumentLearning
                    self._authenticated_profile()
                    project_id = parse_qs(request.query).get("project_id", [""])[0]
                    self._json(HTTPStatus.OK, {"documents": DocumentLearning(application.store, None).history(project_id)})
                elif self.path == "/api/models":
                    if application.model_settings is None:
                        raise RuntimeError("Model settings are unavailable.")
                    self._json(HTTPStatus.OK, application.model_settings.snapshot())
                elif self.path == "/api/benchmarks/conversation":
                    if application.conversation_benchmark is None:
                        raise RuntimeError("Conversation comparison is unavailable.")
                    self._json(HTTPStatus.OK, application.conversation_benchmark.snapshot())
                elif self.path == "/api/benchmarks/project-goal":
                    if application.project_goal_benchmark is None:
                        raise RuntimeError("Project-goal comparison is unavailable.")
                    self._json(HTTPStatus.OK, application.project_goal_benchmark.snapshot())
                elif request.path == "/api/chat/sessions":
                    profile = self._authenticated_profile()
                    allowed_profiles = {profile["id"]}
                    if profile["owns_legacy_memory"]:
                        allowed_profiles.add("LOCAL-LEGACY")
                    sessions = [
                        item for item in application.store.chat_sessions()
                        if item.profile_id in allowed_profiles
                    ]
                    tasks = application.store.tasks()
                    self._json(HTTPStatus.OK, {
                        "sessions": [
                            {
                                **item.model_dump(mode="json"),
                                "interpretations": [
                                    interpretation.model_dump(mode="json")
                                    for interpretation in application.store.conversation_interpretations(
                                        item.id
                                    )
                                ],
                                "conversation_facts": [
                                    fact.model_dump(mode="json")
                                    for fact in getattr(
                                        application.store, "conversation_facts", lambda _: []
                                    )(item.id)
                                ],
                                "memory_associations": [
                                    association.model_dump(mode="json")
                                    for association in getattr(
                                        application.store, "memory_associations", lambda _: []
                                    )(item.id)
                                ],
                                "memory_relationship_interpretations": [
                                    interpretation.model_dump(mode="json")
                                    for interpretation in getattr(
                                        application.store,
                                        "memory_relationship_interpretations",
                                        lambda _: [],
                                    )(item.id)
                                ],
                                "memory_clusters": [
                                    cluster.model_dump(mode="json")
                                    for cluster in getattr(
                                        application.store, "memory_clusters", lambda _: []
                                    )(item.id)
                                ],
                                "concept_branches": [
                                    branch.model_dump(mode="json")
                                    for branch in getattr(
                                        application.store, "concept_branches", lambda _: []
                                    )(item.id)
                                ],
                                "autonomous_decisions": [
                                    decision.model_dump(mode="json")
                                    for decision in getattr(
                                        application.store, "autonomous_decisions", lambda _: []
                                    )(item.id)
                                ],
                                "autonomous_inquiries": [
                                    inquiry.model_dump(mode="json")
                                    for inquiry in getattr(
                                        application.store, "autonomous_inquiries", lambda _: []
                                    )(item.id)
                                ],
                                "concept_branch_outcomes": [
                                    outcome.model_dump(mode="json")
                                    for outcome in getattr(
                                        application.store, "concept_branch_outcomes", lambda _: []
                                    )(item.id)
                                ],
                                "autonomous_work_policy": next((
                                    policy.model_dump(mode="json")
                                    for policy in getattr(
                                        application.store, "autonomous_work_policies", list
                                    )()
                                    if policy.session_id == item.id
                                ), None),
                                "autonomous_tasks": [
                                    task.model_dump(mode="json")
                                    for task in getattr(
                                        application.store, "autonomous_tasks", lambda _: []
                                    )(item.id)
                                ],
                                "autonomous_task_plans": [
                                    plan.model_dump(mode="json")
                                    for plan in getattr(
                                        application.store, "autonomous_task_plans", lambda _: []
                                    )(item.id)
                                ],
                                "deductive_theories": [
                                    theory.model_dump(mode="json")
                                    for theory in getattr(
                                        application.store, "deductive_theories", lambda _: []
                                    )(item.id)
                                ],
                                "self_assessment_reports": [
                                    report.model_dump(mode="json")
                                    for report in getattr(
                                        application.store, "self_assessment_reports", lambda _: []
                                    )(item.id)
                                ],
                                "work_requests": [
                                    request.model_dump(mode="json")
                                    for request in getattr(
                                        application.store,
                                        "conversation_work_requests",
                                        lambda _: [],
                                    )(item.id)
                                ],
                                "work_results": [
                                    result.model_dump(mode="json")
                                    for result in getattr(
                                        application.store,
                                        "conversation_work_results",
                                        lambda _: [],
                                    )(item.id)
                                ],
                                "self_improvement_proposals": [
                                    proposal.model_dump(mode="json")
                                    for proposal in getattr(
                                        application.store,
                                        "self_improvement_proposals",
                                        list,
                                    )()
                                    if proposal.session_id == item.id
                                ],
                                "turns": [
                                    _chat_turn_payload(application.store, turn, tasks)
                                    for turn in application.store.chat_turns(item.id)
                                ],
                            }
                            for item in sessions
                        ]
                    })
                elif request.path.startswith("/api/chat/progress/"):
                    activity_id = request.path.rsplit("/", 1)[-1]
                    self._json(HTTPStatus.OK, application.chat_progress(activity_id))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            except Exception as exc:  # noqa: BLE001 - API boundary
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

        def do_POST(self) -> None:
            try:
                origin = self.headers.get("Origin")
                if origin not in (None, "http://localhost:3000"):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "Origin is not allowed"})
                    return
                if self.path == "/api/profiles/create":
                    if application.local_profiles is None:
                        raise RuntimeError("Local profiles are unavailable.")
                    payload = self._request_json()
                    self._json(HTTPStatus.CREATED, application.local_profiles.create(
                        str(payload.get("name", "")),
                        str(payload.get("password", "")),
                        str(payload.get("response_style", "BALANCED")),
                    ))
                    return
                elif self.path == "/api/profiles/login":
                    if application.local_profiles is None:
                        raise RuntimeError("Local profiles are unavailable.")
                    payload = self._request_json()
                    self._json(HTTPStatus.OK, application.local_profiles.login(
                        str(payload.get("profile_id", "")),
                        str(payload.get("password", "")),
                    ))
                    return
                elif self.path == "/api/profiles/logout":
                    self._authenticated_profile()
                    application.local_profiles.logout(self._profile_token())
                    self._json(HTTPStatus.OK, {"status": "logged_out"})
                    return
                elif self.path in {"/api/lessons", "/api/lessons/report"}:
                    from .learning import ApplicationReport, LessonDraft, LessonLibrary
                    profile = self._authenticated_profile()
                    payload = self._request_json(max_bytes=32_768)
                    library = LessonLibrary(application.store)
                    project_id = str(payload.get("project_id", ""))
                    if self.path.endswith("/report"):
                        lesson = library.report(project_id, str(payload.get("lesson_id", "")),
                            ApplicationReport.model_validate(payload.get("report", {})), profile["id"])
                    else:
                        lesson = library.learn(project_id,
                            LessonDraft.model_validate(payload.get("lesson", {})), profile["id"])
                    self._json(HTTPStatus.OK, {"lesson": lesson})
                    return
                elif self.path == "/api/world-memory/link":
                    from .project_world_memory import ProjectWorldMemory
                    profile = self._authenticated_profile()
                    payload = self._request_json()
                    result = ProjectWorldMemory(application.store).link(
                        str(payload.get("project_id", "")), str(payload.get("session_id", "")),
                        str(payload.get("fact_id", "")), profile["id"],
                        owns_legacy=bool(profile.get("owns_legacy_memory")),
                    )
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/learning/documents":
                    from .document_learning import DocumentInput, DocumentLearning
                    profile = self._authenticated_profile()
                    if application.observer_chat is None:
                        raise ValueError("The conversation interpreter is unavailable.")
                    payload = self._request_json(max_bytes=160_000)
                    receipt = DocumentLearning(application.store, application.observer_chat.interpreter).ingest(
                        str(payload.get("project_id", "")),
                        DocumentInput.model_validate(payload.get("document", {})), profile["id"],
                    )
                    self._json(HTTPStatus.OK, {"document": receipt})
                    return
                elif self.path == "/api/demo/start":
                    application.controller.start()
                elif self.path == "/api/demo/reset":
                    application.controller.reset()
                elif self.path == "/api/diagnostics/start":
                    if application.diagnostic_controller is None:
                        raise RuntimeError("Interactive diagnostics are unavailable.")
                    payload = self._request_json()
                    result = application.diagnostic_controller.start(
                        str(payload.get("question", "")),
                        str(payload.get("test_path", "")),
                    )
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/conflicts/start":
                    if application.conflict_controller is None:
                        raise RuntimeError("Interactive conflict proofs are unavailable.")
                    payload = self._request_json()
                    result = application.conflict_controller.start(
                        str(payload.get("question", "")),
                        str(payload.get("test_path", "")),
                    )
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/workspace/diagnose":
                    if application.workspace_controller is None:
                        raise RuntimeError("The project workspace is unavailable.")
                    payload = self._request_json()
                    result = application.workspace_controller.start_diagnostic(
                        str(payload.get("project_id", "")),
                        str(payload.get("question", "")),
                        str(payload.get("ticket_id", "")) or None,
                    )
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/workspace/plan":
                    if application.workspace_controller is None:
                        raise RuntimeError("The project workspace is unavailable.")
                    payload = self._request_json()
                    result = application.workspace_controller.start_change_plan(
                        str(payload.get("project_id", "")),
                        str(payload.get("request", "")),
                        payload.get("acceptance_criteria", []),
                        str(payload.get("ticket_id", "")) or None,
                    )
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/workspace/resume":
                    if application.workspace_controller is None:
                        raise RuntimeError("The project workspace is unavailable.")
                    result = application.workspace_controller.resume()
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/workspace/cancel":
                    if application.workspace_controller is None:
                        raise RuntimeError("The project workspace is unavailable.")
                    payload = self._request_json()
                    result = application.workspace_controller.cancel(
                        actor=str(payload.get("actor", "Observer user")),
                        reason=str(payload.get("reason", "")),
                    )
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/tickets/create":
                    if application.ticket_manager is None:
                        raise RuntimeError("Ticket handling is unavailable.")
                    payload = self._request_json()
                    result = application.ticket_manager.create(
                        project_id=str(payload.get("project_id", "")), title=str(payload.get("title", "")),
                        description=str(payload.get("description", "")), acceptance_criteria=payload.get("acceptance_criteria", []),
                        constraints=payload.get("constraints", []), priority=str(payload.get("priority", "MEDIUM")),
                        dependency_ticket_ids=payload.get("dependency_ticket_ids", []),
                        budget=TicketBudget.model_validate(payload.get("budget", {})), created_by="Observer user",
                        source_claim_ids=[str(item) for item in payload.get("source_claim_ids", [])],
                    )
                    application.invalidate()
                    self._json(HTTPStatus.CREATED, result.model_dump(mode="json"))
                    return
                elif self.path == "/api/tickets/automatic/start":
                    if application.automatic_ticket_runner is None:
                        raise RuntimeError("Automatic disposable ticket execution is unavailable.")
                    payload = self._request_json()
                    result = application.automatic_ticket_runner.start(
                        str(payload.get("project_id", ""))
                    )
                    application.invalidate()
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/tickets/automatic/stop":
                    if application.automatic_ticket_runner is None:
                        raise RuntimeError("Automatic disposable ticket execution is unavailable.")
                    result = application.automatic_ticket_runner.stop()
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/chat/retry":
                    profile = self._authenticated_profile()
                    payload = self._request_json()
                    activity_id = str(payload.get("activity_id", "")).strip()
                    result = application.observer_chat.retry_answer(
                        str(payload.get("session_id", "")), str(payload.get("turn_id", "")),
                        profile_id=profile["id"],
                        include_legacy_memory=profile["owns_legacy_memory"],
                        progress=(lambda stage, detail: application.update_chat_progress(
                            activity_id, stage, detail
                        )) if activity_id else None,
                    )
                    if activity_id:
                        application.update_chat_progress(activity_id, "COMPLETE" if result.get("replaces_turn_id") else "FAILED",
                                                         "Answer replaced." if result.get("replaces_turn_id") else "Previous answer retained.")
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/chat":
                    if application.observer_chat is None:
                        raise RuntimeError("Observer chat is unavailable.")
                    profile = self._authenticated_profile()
                    payload = self._request_json(65_536)
                    activity_id = str(payload.get("activity_id", "")).strip()
                    if activity_id:
                        application.update_chat_progress(
                            activity_id, "RECEIVED", "The backend accepted the complete prompt."
                        )
                    progress = (
                        lambda stage, detail: application.update_chat_progress(
                            activity_id, stage, detail
                        )
                        if activity_id else None
                    )
                    result = application.observer_chat.safe_reply(
                        payload.get("message"),
                        list(payload.get("history", [])),
                        payload.get("project_id") if isinstance(payload.get("project_id"), str) else None,
                        payload.get("ticket_id") if isinstance(payload.get("ticket_id"), str) else None,
                        payload.get("session_id") if isinstance(payload.get("session_id"), str) else None,
                        str(payload.get("scope", "AUTO")),
                        str(payload.get("investigation_mode", "AUTO")),
                        progress,
                        profile_id=profile["id"],
                        include_legacy_memory=profile["owns_legacy_memory"],
                    )
                    if activity_id:
                        application.update_chat_progress(
                            activity_id,
                            "FAILED" if result.get("route") == "RLM_RECOVERY" else "COMPLETE",
                            str(result.get("answer")) if result.get("route") == "RLM_RECOVERY"
                            else "The response was returned and persisted.",
                        )
                    result["activity_id"] = activity_id or None
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/models":
                    if application.model_settings is None:
                        raise RuntimeError("Model settings are unavailable.")
                    payload = self._request_json()
                    result = application.model_settings.update(
                        str(payload.get("role", "")), str(payload.get("model", "")),
                        str(payload.get("provider", "")), str(payload.get("base_url", "")),
                        str(payload.get("api_key_environment", "OPENAI_API_KEY")),
                    )
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/benchmarks/conversation/start":
                    if application.conversation_benchmark is None:
                        raise RuntimeError("Conversation comparison is unavailable.")
                    self._json(
                        HTTPStatus.ACCEPTED, application.conversation_benchmark.start()
                    )
                    return
                elif self.path == "/api/benchmarks/project-goal/start":
                    if application.project_goal_benchmark is None:
                        raise RuntimeError("Project-goal comparison is unavailable.")
                    self._json(
                        HTTPStatus.ACCEPTED, application.project_goal_benchmark.start()
                    )
                    return
                elif self.path == "/api/projects/browse":
                    selected_root = select_project_directory()
                    self._json(
                        HTTPStatus.OK,
                        {
                            "root": selected_root,
                            "cancelled": selected_root is None,
                        },
                    )
                    return
                elif self.path == "/api/projects/connect":
                    payload = self._request_json()
                    root = payload.get("root")
                    if not isinstance(root, str) or not root.strip():
                        raise ValueError("Select a local project folder before connecting.")
                    selection = ProjectSelection.explicit(root.strip())
                    scan = ReadOnlyProjectOnboarder(application.store).scan(selection)
                    application.invalidate()
                    project = next(
                        item for item in application.store.projects() if item.id == scan.project_id
                    )
                    self._json(
                        HTTPStatus.CREATED,
                        {
                            "project": project.model_dump(mode="json"),
                            "scan": scan.model_dump(mode="json"),
                        },
                    )
                    return
                elif self.path == "/api/projects/create":
                    payload = self._request_json()
                    root = payload.get("root")
                    if not isinstance(root, str) or not root.strip():
                        raise ValueError("Enter a folder path for the new project.")
                    project_root = Path(root.strip()).expanduser()
                    if project_root.exists():
                        raise ValueError("That path already exists. Connect it instead, or choose a new folder path.")
                    parent = project_root.parent.resolve()
                    if not parent.is_dir():
                        raise ValueError("The parent folder must already exist before creating a project.")
                    project_root.mkdir()
                    (project_root / "manifest.md").write_text(
                        f"# {project_root.name}\n\nDescribe this project here.\n",
                        encoding="utf-8",
                    )
                    (project_root / "goals.json").write_text("[]\n", encoding="utf-8")
                    selection = ProjectSelection.explicit(project_root)
                    scan = ReadOnlyProjectOnboarder(application.store).scan(selection)
                    application.invalidate()
                    project = next(
                        item for item in application.store.projects() if item.id == scan.project_id
                    )
                    self._json(
                        HTTPStatus.CREATED,
                        {
                            "project": project.model_dump(mode="json"),
                            "scan": scan.model_dump(mode="json"),
                            "created_files": ["manifest.md", "goals.json"],
                        },
                    )
                    return
                elif self.path == "/api/projects/organization":
                    payload = self._request_json()
                    project_id = str(payload.get("project_id", ""))
                    organization = " ".join(str(payload.get("organization", "")).split())
                    if not organization:
                        raise ValueError("Organization name is required.")
                    if len(organization) > 120:
                        raise ValueError("Organization name is limited to 120 characters.")
                    project = next(
                        (item for item in application.store.projects() if item.id == project_id),
                        None,
                    )
                    if project is None:
                        raise ValueError("Select a registered project.")
                    project.organization = organization
                    application.store.save_project_record(project)
                    application.invalidate()
                    self._json(HTTPStatus.OK, project.model_dump(mode="json"))
                    return
                elif self.path == "/api/projects/access":
                    payload = self._request_json()
                    project_id = str(payload.get("project_id", ""))
                    try:
                        execution_mode = ProjectExecutionMode(str(payload.get("execution_mode", "")))
                    except ValueError as exc:
                        raise ValueError("Select a valid project execution mode.") from exc
                    project = next(
                        (item for item in application.store.projects() if item.id == project_id),
                        None,
                    )
                    if project is None or not project.explicitly_selected:
                        raise ValueError("Select a registered project.")
                    project.execution_mode = execution_mode
                    # Source inspection remains technically read-only in every mode. Mutation
                    # authority is controlled independently by execution_mode.
                    project.read_only = True
                    application.store.save_project_record(project)
                    application.invalidate()
                    self._json(HTTPStatus.OK, project.model_dump(mode="json"))
                    return
                elif self.path == "/api/projects/intent":
                    payload = self._request_json(32_768)
                    project_id = str(payload.get("project_id", ""))
                    project = next(
                        (item for item in application.store.projects() if item.id == project_id),
                        None,
                    )
                    if project is None:
                        raise ValueError("Select a registered project.")
                    project_manifest = str(payload.get("project_manifest", ""))
                    if len(project_manifest) > 12_000:
                        raise ValueError("Project manifest is limited to 12,000 characters.")
                    manifest_path = Path(project.root).resolve() / "manifest.md"
                    manifest_path.write_text(project_manifest, encoding="utf-8")
                    project.project_manifest = project_manifest
                    application.store.save_project_record(project)
                    application.invalidate()
                    self._json(HTTPStatus.OK, project.model_dump(mode="json"))
                    return
                elif self.path == "/api/projects/goals":
                    payload = self._request_json(16_384)
                    project_id = str(payload.get("project_id", ""))
                    project = next(
                        (item for item in application.store.projects() if item.id == project_id),
                        None,
                    )
                    if project is None:
                        raise ValueError("Select a registered project.")
                    goals_path = Path(project.root).resolve() / "goals.json"
                    try:
                        stored = json.loads(goals_path.read_text(encoding="utf-8")) if goals_path.is_file() else (
                            [{"title": "Imported project goals", "goal": project.project_goals}]
                            if project.project_goals.strip() else []
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                        raise ValueError("goals.json is not valid readable JSON.") from exc
                    goals = stored if isinstance(stored, list) else []
                    action = str(payload.get("action", "add"))
                    if action == "add":
                        title = " ".join(str(payload.get("title", "")).split())
                        goal = str(payload.get("goal", "")).strip()
                        if not title or not goal:
                            raise ValueError("A goal title and description are required.")
                        if len(title) > 160 or len(goal) > 2_000:
                            raise ValueError("Goal titles are limited to 160 characters and descriptions to 2,000.")
                        if len(goals) >= 100:
                            raise ValueError("A project can retain at most 100 goals.")
                        goals.append({"title": title, "goal": goal})
                    elif action == "delete":
                        index = int(payload.get("index", -1))
                        if index < 0 or index >= len(goals):
                            raise ValueError("Select an existing goal.")
                        goals.pop(index)
                    else:
                        raise ValueError("Unsupported goal action.")
                    goals_path.write_text(json.dumps(goals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    application.invalidate()
                    self._json(HTTPStatus.OK, {"project_id": project.id, "goals": goals})
                    return
                elif self.path == "/api/projects/ideas":
                    payload = self._request_json()
                    project_id = str(payload.get("project_id", ""))
                    project = next(
                        (item for item in application.store.projects() if item.id == project_id),
                        None,
                    )
                    if project is None:
                        raise ValueError("Select a registered project.")
                    if len(project.ideas) >= 100:
                        raise ValueError("A project can retain at most 100 ideas.")
                    idea = ProjectIdea(
                        title=" ".join(str(payload.get("title", "")).split()),
                        detail=" ".join(str(payload.get("detail", "")).split()),
                    )
                    project.ideas.append(idea)
                    application.store.save_project_record(project)
                    application.invalidate()
                    self._json(HTTPStatus.CREATED, idea.model_dump(mode="json"))
                    return
                elif self.path == "/api/projects/ideas/suggest":
                    if application.workspace_controller is None:
                        raise RuntimeError("The project workspace is unavailable.")
                    payload = self._request_json()
                    result = application.workspace_controller.suggest_ideas(
                        str(payload.get("project_id", ""))
                    )
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/projects/ideas/status":
                    payload = self._request_json()
                    project_id = str(payload.get("project_id", ""))
                    idea_id = str(payload.get("idea_id", ""))
                    project = next(
                        (item for item in application.store.projects() if item.id == project_id),
                        None,
                    )
                    if project is None:
                        raise ValueError("Select a registered project.")
                    idea = next((item for item in project.ideas if item.id == idea_id), None)
                    if idea is None:
                        raise ValueError("Select an idea from this project.")
                    idea.status = ProjectIdeaStatus(str(payload.get("status", "")))
                    application.store.save_project_record(project)
                    application.invalidate()
                    self._json(HTTPStatus.OK, idea.model_dump(mode="json"))
                    return
                elif self.path == "/api/projects/policy":
                    payload = self._request_json()
                    result = ProjectGovernance(application.store).configure(
                        str(payload.get("project_id", "")),
                        permitted_worker_ids=payload.get("permitted_worker_ids", []),
                        required_validation_categories=payload.get("required_validation_categories", []),
                        plan_approvers=payload.get("plan_approvers", []),
                        promotion_approvers=payload.get("promotion_approvers", []),
                        max_ticket_budget=TicketBudget.model_validate(payload.get("max_ticket_budget", {})),
                        actor=str(payload.get("actor", "Observer user")),
                        reason=str(payload.get("reason", "")),
                        actor_roles={
                            str(key): [str(role) for role in value]
                            for key, value in payload.get("actor_roles", {}).items()
                        } if "actor_roles" in payload else None,
                        approval_rules=[
                            ApprovalPolicyRule.model_validate(item)
                            for item in payload.get("approval_rules", [])
                        ] if "approval_rules" in payload else None,
                        artifact_validation_requirements={
                            str(key): [str(category) for category in value]
                            for key, value in payload.get("artifact_validation_requirements", {}).items()
                        } if "artifact_validation_requirements" in payload else None,
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result.model_dump(mode="json"))
                    return
                elif self.path == "/api/tickets/transition":
                    if application.ticket_manager is None:
                        raise RuntimeError("Ticket handling is unavailable.")
                    payload = self._request_json()
                    result = application.ticket_manager.transition(
                        str(payload.get("ticket_id", "")), str(payload.get("status", "")),
                        actor="Observer user", reason=str(payload.get("reason", "")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result.model_dump(mode="json"))
                    return
                elif self.path == "/api/tickets/criterion":
                    if application.ticket_manager is None:
                        raise RuntimeError("Ticket handling is unavailable.")
                    payload = self._request_json()
                    result = application.ticket_manager.resolve_criterion(
                        str(payload.get("ticket_id", "")), str(payload.get("criterion_id", "")),
                        status=str(payload.get("status", "")), evidence_ids=payload.get("evidence_ids", []),
                        reason=str(payload.get("reason", "")), actor="Observer user",
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result.model_dump(mode="json"))
                    return
                elif self.path == "/api/tickets/validation":
                    if application.ticket_manager is None:
                        raise RuntimeError("Ticket handling is unavailable.")
                    payload = self._request_json()
                    result = application.ticket_manager.record_validation(
                        str(payload.get("ticket_id", "")), name=str(payload.get("name", "")),
                        status=str(payload.get("status", "")), detail=str(payload.get("detail", "")),
                        evidence=[Evidence.model_validate(item) for item in payload.get("evidence", [])],
                        workspace_record_id=str(payload.get("workspace_record_id", "")) or None,
                        recorded_by="Observer user",
                    )
                    application.invalidate()
                    self._json(HTTPStatus.CREATED, result.model_dump(mode="json"))
                    return
                elif self.path == "/api/tickets/approve-plan":
                    if application.ticket_manager is None:
                        raise RuntimeError("Ticket handling is unavailable.")
                    payload = self._request_json()
                    result = application.ticket_manager.approve_plan(
                        str(payload.get("ticket_id", "")), str(payload.get("plan_record_id", "")),
                        actor=str(payload.get("actor", "Observer user")),
                        reason=str(payload.get("reason", "")),
                        decision=str(payload.get("decision", "APPROVED")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result.model_dump(mode="json"))
                    return
                elif self.path == "/api/sandboxes/start":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.start(
                        str(payload.get("ticket_id", "")), str(payload.get("plan_record_id", "")),
                    )
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/sandboxes/resume":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    result = application.sandbox_controller.resume()
                    self._json(HTTPStatus.ACCEPTED, result)
                    return
                elif self.path == "/api/sandboxes/cancel":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.cancel(
                        actor=str(payload.get("actor", "Observer user")),
                        reason=str(payload.get("reason", "")),
                    )
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/discard":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.discard(
                        str(payload.get("ticket_id", "")), str(payload.get("attempt_id", "")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/satisfy-validation":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.satisfy_validation(
                        str(payload.get("ticket_id", "")),
                        str(payload.get("attempt_id", "")),
                        str(payload.get("decision_id", "")),
                        str(payload.get("actor", "Observer user")),
                        str(payload.get("detail", "")),
                        str(payload.get("decision", "APPROVED")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/run-validation-worker":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.run_validation_worker(
                        str(payload.get("ticket_id", "")),
                        str(payload.get("attempt_id", "")),
                        str(payload.get("decision_id", "")),
                        str(payload.get("worker_id", "")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/import-validation-report":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.import_external_validation_report(
                        str(payload.get("ticket_id", "")),
                        str(payload.get("attempt_id", "")),
                        str(payload.get("decision_id", "")),
                        actor=str(payload.get("actor", "Observer user")),
                        report_kind=str(payload.get("report_kind", "")),
                        artifact_path=str(payload.get("artifact_path", "")),
                        source_manifest_sha256=str(payload.get("source_manifest_sha256", "")),
                        patch_sha256=str(payload.get("patch_sha256", "")),
                        report_bytes_base64=str(payload.get("report_bytes_base64", "")),
                        report_sha256=str(payload.get("report_sha256", "")),
                        status=str(payload.get("status", "")),
                        detail=str(payload.get("detail", "")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/approve-promotion":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.approve_promotion(
                        str(payload.get("ticket_id", "")),
                        str(payload.get("attempt_id", "")),
                        str(payload.get("actor", "Observer user")),
                        str(payload.get("reason", "")),
                        str(payload.get("decision", "APPROVED")),
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/promote":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.promote(
                        str(payload.get("ticket_id", "")), str(payload.get("attempt_id", ""))
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/recover":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.recover(
                        str(payload.get("ticket_id", "")), str(payload.get("attempt_id", ""))
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                elif self.path == "/api/sandboxes/reconcile":
                    if application.sandbox_controller is None:
                        raise RuntimeError("Implementation sandboxes are unavailable.")
                    payload = self._request_json()
                    result = application.sandbox_controller.reconcile(
                        str(payload.get("ticket_id", "")), str(payload.get("attempt_id", ""))
                    )
                    application.invalidate()
                    self._json(HTTPStatus.OK, result)
                    return
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                    return
                application.invalidate()
                self._json(HTTPStatus.ACCEPTED, application.snapshot())
            except Exception as exc:  # noqa: BLE001 - API boundary
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787, store=None) -> None:
    project_root = Path(__file__).resolve().parents[2]
    if store is None:
        backend = os.environ.get("RLMGRAPH_BACKEND", "sqlite").strip().lower()
        if backend == "neo4j":
            store = Neo4jGraphStore(
                os.environ.get("RLMGRAPH_NEO4J_URI", "bolt://localhost:7687"),
                os.environ.get("RLMGRAPH_NEO4J_USER", "neo4j"),
                os.environ.get("RLMGRAPH_NEO4J_PASSWORD", "rlmgraph-demo"),
            )
        elif backend == "sqlite":
            database = Path(os.environ.get("RLMGRAPH_DATABASE", default_observer_database()))
            database.parent.mkdir(parents=True, exist_ok=True)
            store = SQLiteGraphStore(database)
        else:
            raise ValueError("RLMGRAPH_BACKEND must be sqlite or neo4j.")
    store.initialize()
    governance = ProjectGovernance(store)
    for project in store.projects():
        if not project.read_only:
            # Migrate the former binary "write enabled" setting into the
            # explicit mode while restoring the invariant used by safe indexing.
            project.execution_mode = ProjectExecutionMode.AUTONOMOUS_PROJECT
            project.read_only = True
            store.save_project_record(project)
        governance.policy(project.id)
    interactive_guard = threading.Lock()
    scheduler = ResourceAwareScheduler(
        store,
        limits=SchedulerLimits(
            global_concurrency=int(os.environ.get("RLMGRAPH_GLOBAL_CONCURRENCY", "2")),
            per_project_concurrency=int(os.environ.get("RLMGRAPH_PROJECT_CONCURRENCY", "1")),
            per_ticket_concurrency=int(os.environ.get("RLMGRAPH_TICKET_CONCURRENCY", "1")),
            capacity_units=int(os.environ.get("RLMGRAPH_CAPACITY_UNITS", "2")),
        ),
    )
    workspace_controller = InteractiveProjectWorkspaceController(
        store,
        run_guard=interactive_guard,
        scheduler=scheduler,
        idea_suggester=CodexProjectIdeaSuggester(
            model=os.environ.get("RLMGRAPH_IDEA_MODEL") or "gpt-5.6-sol"
        ),
    )
    ticket_manager = TicketManager(store)
    implementation_executable = os.environ.get("RLMGRAPH_IMPLEMENTATION_EXECUTABLE")
    if not implementation_executable and os.name == "nt":
        bridge = project_root / "scripts" / "codex_wsl_bridge.cmd"
        implementation_executable = str(bridge) if bridge.is_file() else "codex"
    sandbox_controller = InteractiveSandboxController(
        ImplementationSandboxManager(
            store,
            CodexPlanImplementationWorker(
                implementation_executable or "codex",
                model=os.environ.get("RLMGRAPH_IMPLEMENTATION_MODEL") or "gpt-5.6-sol",
                reasoning_effort=(
                    os.environ.get("RLMGRAPH_IMPLEMENTATION_REASONING_EFFORT") or "max"
                ),
            ),
        ),
        run_guard=interactive_guard,
        scheduler=scheduler,
    )
    automatic_ticket_runner = AutomaticTicketRunner(
        store, workspace_controller, sandbox_controller, ticket_manager
    )
    from .conversation_tasks import ConversationTaskController

    observer_chat = ObserverChat(
        store, model=os.environ.get("RLMGRAPH_CHAT_MODEL") or "gpt-5.6-sol",
        task_controller=ConversationTaskController(
            store, ticket_manager, workspace_controller, automatic_ticket_runner
        ),
        system_root=project_root,
        interpreter=CodexCliInvestigator(
            model=(
                os.environ.get("RLMGRAPH_INTERPRETER_MODEL")
                or os.environ.get("RLMGRAPH_CHAT_MODEL")
                or "gpt-5.6-sol"
            ),
            sandbox="read-only",
        ),
    )
    chat_default = os.environ.get("RLMGRAPH_CHAT_MODEL") or "gpt-5.6-sol"
    interpreter_default = os.environ.get("RLMGRAPH_INTERPRETER_MODEL") or chat_default
    idea_default = os.environ.get("RLMGRAPH_IDEA_MODEL") or "gpt-5.6-sol"
    implementation_default = (
        os.environ.get("RLMGRAPH_IMPLEMENTATION_MODEL") or "gpt-5.6-sol"
    )

    def apply_conversation(config: dict[str, str]) -> None:
        if config["provider"] == "codex_cli":
            adapter = CodexCliInvestigator(model=config["model"], sandbox="read-only")
        else:
            adapter = HttpStructuredLanguageAdapter(
                config["model"], provider=config["provider"],
                base_url=config["base_url"],
                api_key_environment=config["api_key_environment"] or "OPENAI_API_KEY",
            )
        observer_chat.interpreter = adapter
        observer_chat.conversation_memory.associations.interpreter = adapter

    def apply_evidence(config: dict[str, str]) -> None:
        observer_chat.model = config["model"]
        observer_chat.supervisor.investigator.model = config["model"]
        observer_chat.recursive_supervisor.investigator.model = config["model"]

    model_state_root = (
        Path(store.path).parent if getattr(store, "path", None)
        else default_observer_database().parent
    )
    call_ledger = configure_model_call_ledger(model_state_root / "model-calls.db")
    model_settings = ModelSettingsManager(
        model_state_root / "models.json",
        defaults={
            "conversation": {
                "provider": "codex_cli", "model": interpreter_default,
                "base_url": "", "api_key_environment": "",
            },
            "evidence": {
                "provider": "codex_cli", "model": chat_default,
                "base_url": "", "api_key_environment": "",
            },
            "ideas": {
                "provider": "codex_cli", "model": idea_default,
                "base_url": "", "api_key_environment": "",
            },
            "implementation": {
                "provider": "codex_cli", "model": implementation_default,
                "base_url": "", "api_key_environment": "",
            },
        },
        appliers={
            "conversation": apply_conversation,
            "evidence": apply_evidence,
            "ideas": lambda config: setattr(
                workspace_controller.idea_suggester, "model", config["model"]
            ),
            "implementation": lambda config: setattr(
                sandbox_controller.manager.worker.adapter, "model", config["model"]
            ),
        },
    )
    conversation_benchmark = ConversationBenchmarkController(
        PairedConversationBenchmark(
            observer_chat,
            call_ledger,
            ConversationBenchmarkStore(model_state_root / "conversation-benchmarks.db"),
            project_root,
        )
    )
    project_goal_benchmark = ProjectGoalBenchmarkController(
        PairedProjectGoalBenchmark(
            sandbox_controller.manager.worker,
            call_ledger,
            ProjectGoalBenchmarkStore(model_state_root / "project-goal-benchmarks.db"),
            model_state_root / "benchmark-runs",
        )
    )
    local_profiles = LocalProfileStore(project_root / ".rlmgraph" / "local-profiles.json")
    application = DashboardApplication(
        store,
        DemoController(project_root),
        None,
        None,
        workspace_controller,
        ticket_manager,
        sandbox_controller,
        scheduler,
        automatic_ticket_runner,
        observer_chat,
        model_settings,
        conversation_benchmark,
        project_goal_benchmark,
        local_profiles,
        None,
    )
    ThreadingHTTPServer((host, port), _handler(application)).serve_forever()


if __name__ == "__main__":
    serve()
