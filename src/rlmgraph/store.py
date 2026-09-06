from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from .models import (
    AutonomousDecision,
    AutonomousInquiry,
    AutonomousTask,
    AutonomousTaskPlan,
    AutonomousWorkPolicy,
    BenchmarkRun,
    ChatSession,
    ChatTurn,
    Claim,
    CodexReadOnlyProof,
    ConceptBranch,
    ConceptBranchOutcome,
    ConflictCluster,
    ConflictVerdict,
    ConversationFact,
    ConversationInterpretationRecord,
    ConversationWorkRequest,
    ConversationWorkResult,
    DeductiveTheory,
    EvaluationRun,
    ExecutionAttempt,
    GenericCodexEvaluation,
    GraphEdge,
    GraphRelation,
    ImplementationSandboxAttempt,
    InvestigationSession,
    MaintenanceWorkflow,
    MemoryAssociation,
    MemoryCluster,
    MemoryRelationshipInterpretation,
    ObserverActivityState,
    PathwayBenchmarkResult,
    PathwayPromotionDecision,
    PlanDecision,
    PlanningRun,
    PostRepairReconciliation,
    ProjectDependency,
    ProjectFile,
    ProjectGovernancePolicy,
    ProjectLease,
    ProjectLeaseAcquisition,
    ProjectLeaseEvent,
    ProjectLeaseEventKind,
    ProjectLeaseStatus,
    ProjectRecord,
    ProjectScan,
    ProjectSymbol,
    ProjectTest,
    ProjectTicket,
    ProjectWorkspaceRecord,
    PromotionDecision,
    PromotionOutcome,
    ReconstructionAction,
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
    SelfAssessmentReport,
    SelfImprovementProposal,
    Task,
    TicketEvent,
    TicketValidationResult,
    UnrealArtifact,
    UnrealDependency,
    UnrealIndexScan,
    VirtualMemoryPathway,
)
from .provenance import initialize_provenance
from .sqlite_utils import ClosingSQLiteConnection


class GraphStore(Protocol):
    def initialize(self) -> None: ...
    def save_chat_session(self, session: ChatSession) -> None: ...
    def chat_sessions(self) -> list[ChatSession]: ...
    def save_chat_turn(self, turn: ChatTurn) -> None: ...
    def chat_turns(self, session_id: str) -> list[ChatTurn]: ...
    def save_conversation_interpretation(
        self, interpretation: ConversationInterpretationRecord
    ) -> None: ...
    def conversation_interpretations(
        self, session_id: str
    ) -> list[ConversationInterpretationRecord]: ...
    def save_conversation_fact(self, fact: ConversationFact) -> None: ...
    def conversation_facts(self, session_id: str) -> list[ConversationFact]: ...
    def save_memory_association(self, association: MemoryAssociation) -> None: ...
    def memory_associations(self, session_id: str) -> list[MemoryAssociation]: ...
    def save_memory_relationship_interpretation(
        self, interpretation: MemoryRelationshipInterpretation
    ) -> None: ...
    def memory_relationship_interpretations(
        self, session_id: str
    ) -> list[MemoryRelationshipInterpretation]: ...
    def save_memory_cluster(self, cluster: MemoryCluster) -> None: ...
    def memory_clusters(self, session_id: str) -> list[MemoryCluster]: ...
    def save_concept_branch(self, branch: ConceptBranch) -> None: ...
    def concept_branches(self, session_id: str) -> list[ConceptBranch]: ...
    def save_autonomous_decision(self, decision: AutonomousDecision) -> None: ...
    def autonomous_decisions(self, session_id: str) -> list[AutonomousDecision]: ...
    def save_autonomous_inquiry(self, inquiry: AutonomousInquiry) -> None: ...
    def autonomous_inquiries(self, session_id: str) -> list[AutonomousInquiry]: ...
    def save_concept_branch_outcome(self, outcome: ConceptBranchOutcome) -> None: ...
    def concept_branch_outcomes(self, session_id: str) -> list[ConceptBranchOutcome]: ...
    def save_autonomous_work_policy(self, policy: AutonomousWorkPolicy) -> None: ...
    def autonomous_work_policies(self) -> list[AutonomousWorkPolicy]: ...
    def save_autonomous_task(self, task: AutonomousTask) -> None: ...
    def autonomous_tasks(self, session_id: str) -> list[AutonomousTask]: ...
    def save_autonomous_task_plan(self, plan: AutonomousTaskPlan) -> None: ...
    def autonomous_task_plans(self, session_id: str) -> list[AutonomousTaskPlan]: ...
    def save_deductive_theory(self, theory: DeductiveTheory) -> None: ...
    def deductive_theories(self, session_id: str) -> list[DeductiveTheory]: ...
    def save_self_assessment_report(self, report: SelfAssessmentReport) -> None: ...
    def self_assessment_reports(self, session_id: str) -> list[SelfAssessmentReport]: ...
    def save_conversation_work_request(self, request: ConversationWorkRequest) -> None: ...
    def conversation_work_requests(self, session_id: str) -> list[ConversationWorkRequest]: ...
    def save_conversation_work_result(self, result: ConversationWorkResult) -> None: ...
    def conversation_work_results(self, session_id: str) -> list[ConversationWorkResult]: ...
    def save_self_improvement_proposal(self, proposal: SelfImprovementProposal) -> None: ...
    def self_improvement_proposals(self) -> list[SelfImprovementProposal]: ...
    def save_task(self, task: Task) -> None: ...
    def save_claim(self, task: Task, claim: Claim) -> None: ...
    def update_claim(self, claim: Claim) -> None: ...
    def find_claim(self, fingerprint: str) -> Claim | None: ...
    def find_claims(self, project_fingerprint: str) -> list[Claim]: ...
    def get_task(self, task_id: str) -> Task | None: ...
    def get_claim(self, claim_id: str) -> Claim | None: ...
    def save_edge(self, edge: GraphEdge) -> None: ...
    def edges(self) -> list[GraphEdge]: ...
    def tasks(self) -> list[Task]: ...
    def claims(self) -> list[Claim]: ...
    def save_resolution_attempt(self, attempt: ResolutionAttempt) -> None: ...
    def resolution_attempts(self, task_id: str) -> list[ResolutionAttempt]: ...
    def save_conflict_cluster(self, cluster: ConflictCluster) -> None: ...
    def get_conflict_cluster(self, cluster_id: str) -> ConflictCluster | None: ...
    def conflict_clusters(self) -> list[ConflictCluster]: ...
    def save_conflict_verdict(self, verdict: ConflictVerdict) -> None: ...
    def conflict_verdicts(self, task_id: str | None = None) -> list[ConflictVerdict]: ...
    def save_reconstruction(self, session: ReconstructionSession) -> None: ...
    def get_reconstruction(self, session_id: str) -> ReconstructionSession | None: ...
    def reconstructions(self) -> list[ReconstructionSession]: ...
    def save_promotion_decision(self, decision: PromotionDecision) -> None: ...
    def promotion_decisions(self) -> list[PromotionDecision]: ...
    def save_benchmark_run(self, run: BenchmarkRun) -> None: ...
    def benchmark_runs(self) -> list[BenchmarkRun]: ...
    def save_pathway(self, pathway: VirtualMemoryPathway) -> None: ...
    def pathways(self) -> list[VirtualMemoryPathway]: ...
    def save_pathway_decision(self, decision: PathwayPromotionDecision) -> None: ...
    def pathway_decisions(self) -> list[PathwayPromotionDecision]: ...
    def save_pathway_benchmark(self, result: PathwayBenchmarkResult) -> None: ...
    def pathway_benchmarks(self) -> list[PathwayBenchmarkResult]: ...
    def save_plan_decision(self, decision: PlanDecision) -> None: ...
    def plan_decisions(self, root_task_id: str | None = None) -> list[PlanDecision]: ...
    def save_planning_run(self, run: PlanningRun) -> None: ...
    def planning_runs(self, root_task_id: str | None = None) -> list[PlanningRun]: ...
    def save_execution_attempt(self, attempt: ExecutionAttempt) -> None: ...
    def execution_attempts(self, task_id: str | None = None) -> list[ExecutionAttempt]: ...
    def save_route_prediction(self, prediction: RoutePrediction) -> None: ...
    def route_predictions(self, task_id: str | None = None) -> list[RoutePrediction]: ...
    def save_routing_policy_update(self, update: RoutingPolicyUpdate) -> None: ...
    def routing_policy_updates(self) -> list[RoutingPolicyUpdate]: ...
    def save_route_evaluation(self, evaluation: RouteEvaluation) -> None: ...
    def route_evaluations(self) -> list[RouteEvaluation]: ...
    def save_repair_proposal(self, proposal: RepairProposal) -> None: ...
    def repair_proposals(self, task_id: str | None = None) -> list[RepairProposal]: ...
    def save_repair_validation(self, validation: RepairValidation) -> None: ...
    def repair_validations(self, task_id: str | None = None) -> list[RepairValidation]: ...
    def save_repair_approval(self, approval: RepairApproval) -> None: ...
    def repair_approvals(self, proposal_id: str | None = None) -> list[RepairApproval]: ...
    def save_repair_promotion(self, promotion: RepairPromotion) -> None: ...
    def repair_promotions(self, proposal_id: str | None = None) -> list[RepairPromotion]: ...
    def save_post_repair_reconciliation(self, reconciliation: PostRepairReconciliation) -> None: ...
    def post_repair_reconciliations(
        self, promotion_id: str | None = None
    ) -> list[PostRepairReconciliation]: ...
    def save_maintenance_workflow(self, workflow: MaintenanceWorkflow) -> None: ...
    def maintenance_workflows(self) -> list[MaintenanceWorkflow]: ...
    def acquire_project_lease(
        self,
        project_root: str,
        holder_id: str,
        workflow_id: str | None,
        *,
        ttl_seconds: float = 120,
        now: datetime | None = None,
        recovery_journal_id: str | None = None,
    ) -> ProjectLeaseAcquisition: ...
    def renew_project_lease(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        *,
        ttl_seconds: float = 120,
        now: datetime | None = None,
    ) -> ProjectLease: ...
    def release_project_lease(
        self, project_root: str, holder_id: str, fencing_token: int, *, now: datetime | None = None
    ) -> ProjectLease: ...
    def record_project_lease_event(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        kind: ProjectLeaseEventKind,
        detail: str,
        *,
        workflow_id: str | None = None,
        now: datetime | None = None,
    ) -> ProjectLease: ...
    def project_leases(self) -> list[ProjectLease]: ...
    def save_evaluation_run(self, run: EvaluationRun) -> None: ...
    def evaluation_runs(self) -> list[EvaluationRun]: ...
    def save_codex_readonly_proof(self, proof: CodexReadOnlyProof) -> None: ...
    def codex_readonly_proofs(self) -> list[CodexReadOnlyProof]: ...
    def save_recursive_codex_proof(self, proof: RecursiveCodexDelegationProof) -> None: ...
    def recursive_codex_proofs(self) -> list[RecursiveCodexDelegationProof]: ...
    def save_generic_codex_evaluation(self, evaluation: GenericCodexEvaluation) -> None: ...
    def generic_codex_evaluations(self) -> list[GenericCodexEvaluation]: ...
    def save_investigation_session(self, session: InvestigationSession) -> None: ...
    def investigation_sessions(self) -> list[InvestigationSession]: ...
    def save_resumable_session_evaluation(self, evaluation: ResumableSessionEvaluation) -> None: ...
    def resumable_session_evaluations(self) -> list[ResumableSessionEvaluation]: ...
    def save_unreal_index(self, scan: UnrealIndexScan, artifacts: list[UnrealArtifact], dependencies: list[UnrealDependency]) -> None: ...
    def unreal_index_scans(self) -> list[UnrealIndexScan]: ...
    def unreal_artifacts(self, project_id: str | None = None) -> list[UnrealArtifact]: ...
    def unreal_dependencies(self, project_id: str | None = None) -> list[UnrealDependency]: ...
    def save_project_workspace_record(self, record: ProjectWorkspaceRecord) -> None: ...
    def project_workspace_records(self) -> list[ProjectWorkspaceRecord]: ...
    def save_project_ticket(self, ticket: ProjectTicket) -> None: ...
    def project_tickets(self) -> list[ProjectTicket]: ...
    def save_ticket_event(self, event: TicketEvent) -> None: ...
    def ticket_events(self, ticket_id: str | None = None) -> list[TicketEvent]: ...
    def save_ticket_validation_result(self, result: TicketValidationResult) -> None: ...
    def ticket_validation_results(
        self, ticket_id: str | None = None
    ) -> list[TicketValidationResult]: ...
    def save_implementation_sandbox(self, attempt: ImplementationSandboxAttempt) -> None: ...
    def implementation_sandboxes(
        self, ticket_id: str | None = None
    ) -> list[ImplementationSandboxAttempt]: ...
    def save_observer_activity(self, state: ObserverActivityState) -> None: ...
    def observer_activities(self) -> list[ObserverActivityState]: ...
    def save_scheduled_work(self, item: ScheduledWorkItem) -> None: ...
    def scheduled_work(self) -> list[ScheduledWorkItem]: ...
    def save_project_governance_policy(self, policy: ProjectGovernancePolicy) -> None: ...
    def project_governance_policies(self) -> list[ProjectGovernancePolicy]: ...
    def save_project_record(self, project: ProjectRecord) -> None: ...
    def save_project_snapshot(
        self,
        project: ProjectRecord,
        scan: ProjectScan,
        files: list[ProjectFile],
        symbols: list[ProjectSymbol],
        tests: list[ProjectTest],
        dependencies: list[ProjectDependency],
    ) -> None: ...
    def projects(self) -> list[ProjectRecord]: ...
    def project_scans(self, project_id: str | None = None) -> list[ProjectScan]: ...
    def project_files(
        self, project_id: str | None = None, *, include_deleted: bool = False
    ) -> list[ProjectFile]: ...
    def project_symbols(self, project_id: str | None = None) -> list[ProjectSymbol]: ...
    def project_tests(self, project_id: str | None = None) -> list[ProjectTest]: ...
    def project_dependencies(self, project_id: str | None = None) -> list[ProjectDependency]: ...


class SQLiteGraphStore:
    """Small durable graph projection used by the standalone prototype."""

    def __init__(self, path: str | Path = ".rlmgraph.db") -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, factory=ClosingSQLiteConnection)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    source TEXT NOT NULL, relation TEXT NOT NULL, target TEXT NOT NULL,
                    PRIMARY KEY (source, relation, target)
                );
                CREATE INDEX IF NOT EXISTS ix_claim_fingerprint ON claims(fingerprint);
                CREATE TABLE IF NOT EXISTS resolution_attempts (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_resolution_attempt_task
                    ON resolution_attempts(task_id);
                CREATE TABLE IF NOT EXISTS conflict_clusters (
                    id TEXT PRIMARY KEY, project_fingerprint TEXT NOT NULL,
                    assertion_key TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_cluster_project_assertion
                    ON conflict_clusters(project_fingerprint, assertion_key);
                CREATE TABLE IF NOT EXISTS conflict_verdicts (
                    id TEXT PRIMARY KEY, resolution_task_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ix_verdict_resolution_task
                    ON conflict_verdicts(resolution_task_id);
                CREATE TABLE IF NOT EXISTS reconstructions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_reconstruction_task
                    ON reconstructions(task_id);
                CREATE TABLE IF NOT EXISTS promotion_decisions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_promotion_task
                    ON promotion_decisions(task_id);
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_benchmark_task
                    ON benchmark_runs(task_id);
                CREATE TABLE IF NOT EXISTS virtual_pathways (
                    id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pathway_decisions (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pathway_benchmarks (
                    id TEXT PRIMARY KEY, pathway_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_decisions (
                    id TEXT PRIMARY KEY, root_task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_plan_decision_root ON plan_decisions(root_task_id);
                CREATE TABLE IF NOT EXISTS planning_runs (
                    id TEXT PRIMARY KEY, root_task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_planning_run_root ON planning_runs(root_task_id);
                CREATE TABLE IF NOT EXISTS execution_attempts (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, root_task_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_execution_task ON execution_attempts(task_id);
                CREATE INDEX IF NOT EXISTS ix_execution_root ON execution_attempts(root_task_id);
                CREATE TABLE IF NOT EXISTS route_predictions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_route_prediction_task ON route_predictions(task_id);
                CREATE TABLE IF NOT EXISTS routing_policy_updates (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS route_evaluations (
                    id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repair_proposals (
                    id TEXT PRIMARY KEY, repair_task_id TEXT NOT NULL,
                    signature TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_repair_proposal_task
                    ON repair_proposals(repair_task_id);
                CREATE INDEX IF NOT EXISTS ix_repair_proposal_signature
                    ON repair_proposals(signature);
                CREATE TABLE IF NOT EXISTS repair_validations (
                    id TEXT PRIMARY KEY, repair_task_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_repair_validation_task
                    ON repair_validations(repair_task_id);
                CREATE TABLE IF NOT EXISTS repair_approvals (
                    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_repair_approval_proposal
                    ON repair_approvals(proposal_id);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_repair_approval_proposal
                    ON repair_approvals(proposal_id);
                CREATE TABLE IF NOT EXISTS repair_promotions (
                    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_repair_promotion_proposal
                    ON repair_promotions(proposal_id);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_repair_promotion_proposal
                    ON repair_promotions(proposal_id);
                CREATE TABLE IF NOT EXISTS post_repair_reconciliations (
                    id TEXT PRIMARY KEY, promotion_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ix_reconciliation_promotion
                    ON post_repair_reconciliations(promotion_id);
                CREATE TABLE IF NOT EXISTS maintenance_workflows (
                    id TEXT PRIMARY KEY, signature TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_leases (
                    project_root TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id TEXT PRIMARY KEY, suite_version TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS codex_readonly_proofs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recursive_codex_proofs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generic_codex_evaluations (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS investigation_sessions (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resumable_session_evaluations (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS unreal_index_scans (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS unreal_artifacts (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS unreal_dependencies (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_workspace_records (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_tickets (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ticket_events (id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ticket_validation_results (id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS implementation_sandboxes (id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observer_activities (id TEXT PRIMARY KEY, activity_kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scheduled_work (id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, project_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_governance_policies (id TEXT PRIMARY KEY, project_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_turns (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    claim_id TEXT, payload TEXT NOT NULL, UNIQUE(session_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS ix_chat_turn_session ON chat_turns(session_id, ordinal);
                CREATE INDEX IF NOT EXISTS ix_chat_turn_claim ON chat_turns(claim_id);
                CREATE TABLE IF NOT EXISTS conversation_interpretations (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conversation_interpretation_session
                    ON conversation_interpretations(session_id, created_at);
                CREATE INDEX IF NOT EXISTS ix_conversation_interpretation_turn
                    ON conversation_interpretations(turn_id);
                CREATE TABLE IF NOT EXISTS conversation_facts (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conversation_fact_session
                    ON conversation_facts(session_id, created_at);
                CREATE TABLE IF NOT EXISTS memory_associations (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_memory_association_session
                    ON memory_associations(session_id, created_at);
                CREATE TABLE IF NOT EXISTS memory_relationship_interpretations (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    association_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_memory_relationship_session
                    ON memory_relationship_interpretations(session_id, created_at);
                CREATE TABLE IF NOT EXISTS memory_clusters (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, signature TEXT NOT NULL UNIQUE,
                    abstraction_level INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_memory_cluster_session
                    ON memory_clusters(session_id, abstraction_level, created_at);
                CREATE TABLE IF NOT EXISTS concept_branches (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, signature TEXT NOT NULL UNIQUE,
                    parent_branch_id TEXT, depth INTEGER NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_concept_branch_session
                    ON concept_branches(session_id, depth, created_at);
                CREATE TABLE IF NOT EXISTS autonomous_decisions (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_autonomous_decision_session
                    ON autonomous_decisions(session_id, updated_at);
                CREATE TABLE IF NOT EXISTS autonomous_inquiries (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_autonomous_inquiry_session
                    ON autonomous_inquiries(session_id, updated_at);
                CREATE TABLE IF NOT EXISTS concept_branch_outcomes (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_concept_branch_outcome_session
                    ON concept_branch_outcomes(session_id, created_at);
                CREATE TABLE IF NOT EXISTS autonomous_work_policies (
                    session_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS autonomous_tasks (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, outcome_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_autonomous_task_session
                    ON autonomous_tasks(session_id, updated_at);
                CREATE TABLE IF NOT EXISTS autonomous_task_plans (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, autonomous_task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_autonomous_task_plan_session
                    ON autonomous_task_plans(session_id, created_at);
                CREATE TABLE IF NOT EXISTS deductive_theories (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, subject TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_deductive_theory_session
                    ON deductive_theories(session_id, subject, created_at);
                CREATE TABLE IF NOT EXISTS self_assessment_reports (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, work_result_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_self_assessment_report_session
                    ON self_assessment_reports(session_id, created_at);
                CREATE TABLE IF NOT EXISTS conversation_work_requests (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conversation_work_request_session
                    ON conversation_work_requests(session_id, created_at);
                CREATE TABLE IF NOT EXISTS conversation_work_results (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conversation_work_result_session
                    ON conversation_work_results(session_id, created_at);
                CREATE INDEX IF NOT EXISTS ix_conversation_work_result_request
                    ON conversation_work_results(request_id);
                CREATE TABLE IF NOT EXISTS self_improvement_proposals (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_self_improvement_proposal_session
                    ON self_improvement_proposals(session_id, updated_at);
                INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '4')
                    ON CONFLICT(key) DO UPDATE SET value='4';
                CREATE INDEX IF NOT EXISTS ix_ticket_event_ticket ON ticket_events(ticket_id);
                CREATE INDEX IF NOT EXISTS ix_workspace_record_project ON project_workspace_records(project_id);
                CREATE INDEX IF NOT EXISTS ix_ticket_project ON project_tickets(project_id);
                CREATE INDEX IF NOT EXISTS ix_ticket_validation_ticket ON ticket_validation_results(ticket_id);
                CREATE INDEX IF NOT EXISTS ix_sandbox_ticket ON implementation_sandboxes(ticket_id);
                CREATE INDEX IF NOT EXISTS ix_scheduled_work_status ON scheduled_work(status);
                CREATE INDEX IF NOT EXISTS ix_scheduled_work_project ON scheduled_work(project_id);
                CREATE INDEX IF NOT EXISTS ix_scheduled_work_ticket ON scheduled_work(ticket_id);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_project_governance_project ON project_governance_policies(project_id);
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_scans (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_project_scan_project
                    ON project_scans(project_id);
                CREATE TABLE IF NOT EXISTS project_files (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, path TEXT NOT NULL,
                    lifecycle TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_project_file_project
                    ON project_files(project_id);
                CREATE TABLE IF NOT EXISTS project_symbols (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_tests (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_dependencies (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_file_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            schema = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='claims'"
            ).fetchone()["sql"]
            if "fingerprint TEXT NOT NULL UNIQUE" in schema:
                db.executescript(
                    """
                    ALTER TABLE claims RENAME TO claims_legacy;
                    CREATE TABLE claims (
                        id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL
                    );
                    INSERT INTO claims SELECT id, fingerprint, payload FROM claims_legacy;
                    DROP TABLE claims_legacy;
                    CREATE INDEX IF NOT EXISTS ix_claim_fingerprint ON claims(fingerprint);
                    """
                )

    def save_chat_session(self, session: ChatSession) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO chat_sessions VALUES (?, ?, ?)",
                (session.id, session.updated_at.isoformat(), session.model_dump_json()),
            )

    def chat_sessions(self) -> list[ChatSession]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM chat_sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [ChatSession.model_validate_json(row["payload"]) for row in rows]

    def save_chat_turn(self, turn: ChatTurn) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO chat_turns VALUES (?, ?, ?, ?, ?)",
                (turn.id, turn.session_id, turn.ordinal, turn.claim_id, turn.model_dump_json()),
            )

    def chat_turns(self, session_id: str) -> list[ChatTurn]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM chat_turns WHERE session_id = ? ORDER BY ordinal",
                (session_id,),
            ).fetchall()
        return [ChatTurn.model_validate_json(row["payload"]) for row in rows]

    def save_conversation_interpretation(
        self, interpretation: ConversationInterpretationRecord
    ) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO conversation_interpretations VALUES (?, ?, ?, ?, ?)",
                (
                    interpretation.id, interpretation.session_id, interpretation.turn_id,
                    interpretation.created_at.isoformat(), interpretation.model_dump_json(),
                ),
            )

    def conversation_interpretations(
        self, session_id: str
    ) -> list[ConversationInterpretationRecord]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM conversation_interpretations "
                "WHERE session_id = ? ORDER BY created_at, id",
                (session_id,),
            ).fetchall()
        return [ConversationInterpretationRecord.model_validate_json(row["payload"]) for row in rows]

    def save_conversation_fact(self, fact: ConversationFact) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO conversation_facts VALUES (?, ?, ?, ?)",
                (fact.id, fact.session_id, fact.created_at.isoformat(), fact.model_dump_json()),
            )

    def conversation_facts(self, session_id: str) -> list[ConversationFact]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM conversation_facts "
                "WHERE session_id = ? ORDER BY created_at, id",
                (session_id,),
            ).fetchall()
        return [ConversationFact.model_validate_json(row["payload"]) for row in rows]

    def save_memory_association(self, association: MemoryAssociation) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO memory_associations VALUES (?, ?, ?, ?)",
                (
                    association.id, association.session_id,
                    association.created_at.isoformat(), association.model_dump_json(),
                ),
            )

    def memory_associations(self, session_id: str) -> list[MemoryAssociation]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM memory_associations "
                "WHERE session_id = ? ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [MemoryAssociation.model_validate_json(row["payload"]) for row in rows]

    def save_memory_relationship_interpretation(
        self, interpretation: MemoryRelationshipInterpretation
    ) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO memory_relationship_interpretations VALUES (?, ?, ?, ?, ?)",
                (
                    interpretation.id, interpretation.session_id, interpretation.association_id,
                    interpretation.created_at.isoformat(), interpretation.model_dump_json(),
                ),
            )

    def memory_relationship_interpretations(
        self, session_id: str
    ) -> list[MemoryRelationshipInterpretation]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM memory_relationship_interpretations "
                "WHERE session_id = ? ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [
            MemoryRelationshipInterpretation.model_validate_json(row["payload"])
            for row in rows
        ]

    def save_memory_cluster(self, cluster: MemoryCluster) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO memory_clusters VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cluster.id, cluster.session_id, cluster.signature, cluster.abstraction_level,
                    cluster.created_at.isoformat(), cluster.model_dump_json(),
                ),
            )

    def memory_clusters(self, session_id: str) -> list[MemoryCluster]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM memory_clusters WHERE session_id = ? "
                "ORDER BY abstraction_level, created_at, id", (session_id,),
            ).fetchall()
        return [MemoryCluster.model_validate_json(row["payload"]) for row in rows]

    def save_concept_branch(self, branch: ConceptBranch) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO concept_branches VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    branch.id, branch.session_id, branch.signature, branch.parent_branch_id,
                    branch.depth, branch.created_at.isoformat(), branch.model_dump_json(),
                ),
            )

    def concept_branches(self, session_id: str) -> list[ConceptBranch]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM concept_branches WHERE session_id = ? "
                "ORDER BY depth, created_at, id", (session_id,),
            ).fetchall()
        return [ConceptBranch.model_validate_json(row["payload"]) for row in rows]

    def save_autonomous_decision(self, decision: AutonomousDecision) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO autonomous_decisions VALUES (?, ?, ?, ?)",
                (decision.id, decision.session_id, decision.updated_at.isoformat(), decision.model_dump_json()),
            )

    def autonomous_decisions(self, session_id: str) -> list[AutonomousDecision]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM autonomous_decisions WHERE session_id = ? "
                "ORDER BY updated_at, id", (session_id,),
            ).fetchall()
        return [AutonomousDecision.model_validate_json(row["payload"]) for row in rows]

    def save_autonomous_inquiry(self, inquiry: AutonomousInquiry) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO autonomous_inquiries VALUES (?, ?, ?, ?, ?)",
                (
                    inquiry.id, inquiry.session_id, inquiry.branch_id,
                    inquiry.updated_at.isoformat(), inquiry.model_dump_json(),
                ),
            )

    def autonomous_inquiries(self, session_id: str) -> list[AutonomousInquiry]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM autonomous_inquiries WHERE session_id = ? "
                "ORDER BY updated_at, id", (session_id,),
            ).fetchall()
        return [AutonomousInquiry.model_validate_json(row["payload"]) for row in rows]

    def save_concept_branch_outcome(self, outcome: ConceptBranchOutcome) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO concept_branch_outcomes VALUES (?, ?, ?, ?, ?)",
                (
                    outcome.id, outcome.session_id, outcome.branch_id,
                    outcome.created_at.isoformat(), outcome.model_dump_json(),
                ),
            )

    def concept_branch_outcomes(self, session_id: str) -> list[ConceptBranchOutcome]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM concept_branch_outcomes WHERE session_id = ? "
                "ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [ConceptBranchOutcome.model_validate_json(row["payload"]) for row in rows]

    def save_autonomous_work_policy(self, policy: AutonomousWorkPolicy) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO autonomous_work_policies VALUES (?, ?, ?)",
                (policy.session_id, policy.updated_at.isoformat(), policy.model_dump_json()),
            )

    def autonomous_work_policies(self) -> list[AutonomousWorkPolicy]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM autonomous_work_policies ORDER BY updated_at, session_id"
            ).fetchall()
        return [AutonomousWorkPolicy.model_validate_json(row["payload"]) for row in rows]

    def save_autonomous_task(self, task: AutonomousTask) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO autonomous_tasks VALUES (?, ?, ?, ?, ?)",
                (task.id, task.session_id, task.outcome_id, task.updated_at.isoformat(), task.model_dump_json()),
            )

    def autonomous_tasks(self, session_id: str) -> list[AutonomousTask]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM autonomous_tasks WHERE session_id = ? "
                "ORDER BY updated_at, id", (session_id,),
            ).fetchall()
        return [AutonomousTask.model_validate_json(row["payload"]) for row in rows]

    def save_autonomous_task_plan(self, plan: AutonomousTaskPlan) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO autonomous_task_plans VALUES (?, ?, ?, ?, ?)",
                (plan.id, plan.session_id, plan.autonomous_task_id,
                 plan.created_at.isoformat(), plan.model_dump_json()),
            )

    def autonomous_task_plans(self, session_id: str) -> list[AutonomousTaskPlan]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM autonomous_task_plans WHERE session_id = ? "
                "ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [AutonomousTaskPlan.model_validate_json(row["payload"]) for row in rows]

    def save_deductive_theory(self, theory: DeductiveTheory) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO deductive_theories VALUES (?, ?, ?, ?, ?)",
                (theory.id, theory.session_id, theory.subject,
                 theory.created_at.isoformat(), theory.model_dump_json()),
            )

    def deductive_theories(self, session_id: str) -> list[DeductiveTheory]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM deductive_theories WHERE session_id = ? "
                "ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [DeductiveTheory.model_validate_json(row["payload"]) for row in rows]

    def save_self_assessment_report(self, report: SelfAssessmentReport) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO self_assessment_reports VALUES (?, ?, ?, ?, ?)",
                (report.id, report.session_id, report.work_result_id,
                 report.created_at.isoformat(), report.model_dump_json()),
            )

    def self_assessment_reports(self, session_id: str) -> list[SelfAssessmentReport]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM self_assessment_reports WHERE session_id = ? "
                "ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [SelfAssessmentReport.model_validate_json(row["payload"]) for row in rows]

    def save_conversation_work_request(self, request: ConversationWorkRequest) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO conversation_work_requests VALUES (?, ?, ?, ?)",
                (request.id, request.session_id, request.created_at.isoformat(), request.model_dump_json()),
            )

    def conversation_work_requests(self, session_id: str) -> list[ConversationWorkRequest]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM conversation_work_requests "
                "WHERE session_id = ? ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [ConversationWorkRequest.model_validate_json(row["payload"]) for row in rows]

    def save_conversation_work_result(self, result: ConversationWorkResult) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO conversation_work_results VALUES (?, ?, ?, ?, ?)",
                (
                    result.id, result.session_id, result.request_id,
                    result.created_at.isoformat(), result.model_dump_json(),
                ),
            )

    def conversation_work_results(self, session_id: str) -> list[ConversationWorkResult]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM conversation_work_results "
                "WHERE session_id = ? ORDER BY created_at, id", (session_id,),
            ).fetchall()
        return [ConversationWorkResult.model_validate_json(row["payload"]) for row in rows]

    def save_self_improvement_proposal(self, proposal: SelfImprovementProposal) -> None:
        self.initialize()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO self_improvement_proposals VALUES (?, ?, ?, ?)",
                (proposal.id, proposal.session_id, proposal.updated_at.isoformat(), proposal.model_dump_json()),
            )

    def self_improvement_proposals(self) -> list[SelfImprovementProposal]:
        self.initialize()
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM self_improvement_proposals ORDER BY updated_at, id"
            ).fetchall()
        return [SelfImprovementProposal.model_validate_json(row["payload"]) for row in rows]

    def save_task(self, task: Task) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)",
                (task.id, task.fingerprint, task.model_dump_json()),
            )

    def save_claim(self, task: Task, claim: Claim) -> None:
        initialize_provenance(task, claim)
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO claims (id, fingerprint, payload) VALUES (?, ?, ?)",
                (claim.id, claim.fingerprint, claim.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (task.id, GraphRelation.DISCOVERED, claim.id),
            )
            for source_claim_id in claim.source_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (claim.id, GraphRelation.DERIVED_FROM, source_claim_id),
                )

    def update_claim(self, claim: Claim) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE claims SET fingerprint = ?, payload = ? WHERE id = ?",
                (claim.fingerprint, claim.model_dump_json(), claim.id),
            )

    def save_edge(self, edge: GraphEdge) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (edge.source, edge.relation, edge.target),
            )

    def edges(self) -> list[GraphEdge]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT source, relation, target FROM edges ORDER BY rowid"
            ).fetchall()
        return [GraphEdge.model_validate(dict(row)) for row in rows]

    def find_claim(self, fingerprint: str) -> Claim | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM claims WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return Claim.model_validate_json(row["payload"]) if row else None

    def find_claims(self, project_fingerprint: str) -> list[Claim]:
        return [
            claim for claim in self.claims() if claim.project_fingerprint == project_fingerprint
        ]

    def get_task(self, task_id: str) -> Task | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return Task.model_validate_json(row["payload"]) if row else None

    def get_claim(self, claim_id: str) -> Claim | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return Claim.model_validate_json(row["payload"]) if row else None

    def tasks(self) -> list[Task]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM tasks ORDER BY rowid").fetchall()
        return [Task.model_validate_json(row["payload"]) for row in rows]

    def claims(self) -> list[Claim]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM claims ORDER BY rowid").fetchall()
        return [Claim.model_validate_json(row["payload"]) for row in rows]

    def save_resolution_attempt(self, attempt: ResolutionAttempt) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO resolution_attempts VALUES (?, ?, ?)",
                (attempt.id, attempt.task_id, attempt.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (attempt.task_id, GraphRelation.ATTEMPTED, attempt.id),
            )

    def resolution_attempts(self, task_id: str) -> list[ResolutionAttempt]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM resolution_attempts WHERE task_id = ? ORDER BY rowid",
                (task_id,),
            ).fetchall()
        return [ResolutionAttempt.model_validate_json(row["payload"]) for row in rows]

    def save_conflict_cluster(self, cluster: ConflictCluster) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO conflict_clusters VALUES (?, ?, ?, ?)",
                (
                    cluster.id,
                    cluster.project_fingerprint,
                    cluster.assertion_key,
                    cluster.model_dump_json(),
                ),
            )

    def get_conflict_cluster(self, cluster_id: str) -> ConflictCluster | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM conflict_clusters WHERE id = ?", (cluster_id,)
            ).fetchone()
        return ConflictCluster.model_validate_json(row["payload"]) if row else None

    def conflict_clusters(self) -> list[ConflictCluster]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM conflict_clusters ORDER BY rowid").fetchall()
        return [ConflictCluster.model_validate_json(row["payload"]) for row in rows]

    def save_conflict_verdict(self, verdict: ConflictVerdict) -> None:
        with self.connect() as db:
            db.execute(
                "DELETE FROM edges WHERE target = ? AND relation IN (?, ?, ?, ?)",
                (
                    verdict.id,
                    GraphRelation.HAS_VERDICT,
                    GraphRelation.SUPPORTS_VERDICT,
                    GraphRelation.CONTRADICTS_VERDICT,
                    GraphRelation.EVIDENCE_FOR_VERDICT,
                ),
            )
            db.execute(
                "INSERT OR REPLACE INTO conflict_verdicts VALUES (?, ?, ?)",
                (verdict.id, verdict.resolution_task_id, verdict.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (verdict.resolution_task_id, GraphRelation.HAS_VERDICT, verdict.id),
            )
            for claim_id in verdict.supporting_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (claim_id, GraphRelation.SUPPORTS_VERDICT, verdict.id),
                )
            for claim_id in verdict.contradicting_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (claim_id, GraphRelation.CONTRADICTS_VERDICT, verdict.id),
                )
            for claim_id in verdict.evidence_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (claim_id, GraphRelation.EVIDENCE_FOR_VERDICT, verdict.id),
                )

    def conflict_verdicts(self, task_id: str | None = None) -> list[ConflictVerdict]:
        query = "SELECT payload FROM conflict_verdicts"
        params: tuple[str, ...] = ()
        if task_id is not None:
            query += " WHERE resolution_task_id = ?"
            params = (task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [ConflictVerdict.model_validate_json(row["payload"]) for row in rows]

    def save_reconstruction(self, session: ReconstructionSession) -> None:
        relation_by_action = {
            ReconstructionAction.SEED: GraphRelation.SEEDED,
            ReconstructionAction.EXPAND: GraphRelation.EXPANDED_TO,
            ReconstructionAction.PRUNE: GraphRelation.PRUNED_FROM,
        }
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO reconstructions VALUES (?, ?, ?)",
                (session.id, session.task_id, session.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (session.task_id, GraphRelation.HAS_RECONSTRUCTION, session.id),
            )
            for step in session.steps:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (session.id, GraphRelation.HAS_STEP, step.id),
                )
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (step.id, relation_by_action[step.action], step.node_id),
                )

    def get_reconstruction(self, session_id: str) -> ReconstructionSession | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM reconstructions WHERE id = ?", (session_id,)
            ).fetchone()
        return ReconstructionSession.model_validate_json(row["payload"]) if row else None

    def reconstructions(self) -> list[ReconstructionSession]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM reconstructions ORDER BY rowid").fetchall()
        return [ReconstructionSession.model_validate_json(row["payload"]) for row in rows]

    def save_promotion_decision(self, decision: PromotionDecision) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO promotion_decisions VALUES (?, ?, ?)",
                (decision.id, decision.task_id, decision.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (decision.task_id, GraphRelation.HAS_PROMOTION, decision.id),
            )
            for claim_id in decision.candidate_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (decision.id, GraphRelation.EVALUATED, claim_id),
                )
                if decision.outcome == PromotionOutcome.REJECTED:
                    db.execute(
                        "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                        (decision.id, GraphRelation.REJECTED_CANDIDATE, claim_id),
                    )
            if decision.promoted_claim_id:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (decision.id, GraphRelation.PROMOTED_TO, decision.promoted_claim_id),
                )

    def promotion_decisions(self) -> list[PromotionDecision]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM promotion_decisions ORDER BY rowid").fetchall()
        return [PromotionDecision.model_validate_json(row["payload"]) for row in rows]

    def save_benchmark_run(self, run: BenchmarkRun) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO benchmark_runs VALUES (?, ?, ?)",
                (run.id, run.task_id, run.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (run.task_id, GraphRelation.HAS_BENCHMARK, run.id),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (run.id, GraphRelation.MEASURED_RECONSTRUCTION, run.reconstruction_id),
            )

    def benchmark_runs(self) -> list[BenchmarkRun]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM benchmark_runs ORDER BY rowid").fetchall()
        return [BenchmarkRun.model_validate_json(row["payload"]) for row in rows]

    def save_pathway(self, pathway: VirtualMemoryPathway) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO virtual_pathways VALUES (?, ?, ?)",
                (pathway.id, pathway.token, pathway.model_dump_json()),
            )
            for claim_id in pathway.source_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (pathway.id, GraphRelation.PATHWAY_INCLUDES, claim_id),
                )
            for reconstruction_id in pathway.supporting_reconstruction_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (reconstruction_id, GraphRelation.SUPPORTS_PATHWAY, pathway.id),
                )

    def pathways(self) -> list[VirtualMemoryPathway]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM virtual_pathways ORDER BY rowid").fetchall()
        return [VirtualMemoryPathway.model_validate_json(row["payload"]) for row in rows]

    def save_pathway_decision(self, decision: PathwayPromotionDecision) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO pathway_decisions VALUES (?, ?)",
                (decision.id, decision.model_dump_json()),
            )
            for task_id in decision.candidate_task_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (task_id, GraphRelation.HAS_PATHWAY_DECISION, decision.id),
                )
            if decision.pathway_id:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (decision.id, GraphRelation.PROMOTED_PATHWAY, decision.pathway_id),
                )

    def pathway_decisions(self) -> list[PathwayPromotionDecision]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM pathway_decisions ORDER BY rowid").fetchall()
        return [PathwayPromotionDecision.model_validate_json(row["payload"]) for row in rows]

    def save_pathway_benchmark(self, result: PathwayBenchmarkResult) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO pathway_benchmarks VALUES (?, ?, ?)",
                (result.id, result.pathway_id, result.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (result.pathway_id, GraphRelation.HAS_BENCHMARK, result.id),
            )

    def pathway_benchmarks(self) -> list[PathwayBenchmarkResult]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM pathway_benchmarks ORDER BY rowid").fetchall()
        return [PathwayBenchmarkResult.model_validate_json(row["payload"]) for row in rows]

    def save_plan_decision(self, decision: PlanDecision) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO plan_decisions VALUES (?, ?, ?)",
                (decision.id, decision.root_task_id, decision.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (decision.root_task_id, GraphRelation.HAS_PLAN_DECISION, decision.id),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (decision.id, GraphRelation.PLANNED_TASK, decision.task_id),
            )

    def plan_decisions(self, root_task_id: str | None = None) -> list[PlanDecision]:
        query = "SELECT payload FROM plan_decisions"
        params: tuple[str, ...] = ()
        if root_task_id is not None:
            query += " WHERE root_task_id = ?"
            params = (root_task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [PlanDecision.model_validate_json(row["payload"]) for row in rows]

    def save_planning_run(self, run: PlanningRun) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO planning_runs VALUES (?, ?, ?)",
                (run.id, run.root_task_id, run.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (run.root_task_id, GraphRelation.HAS_PLANNING_RUN, run.id),
            )

    def planning_runs(self, root_task_id: str | None = None) -> list[PlanningRun]:
        query = "SELECT payload FROM planning_runs"
        params: tuple[str, ...] = ()
        if root_task_id is not None:
            query += " WHERE root_task_id = ?"
            params = (root_task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [PlanningRun.model_validate_json(row["payload"]) for row in rows]

    def save_execution_attempt(self, attempt: ExecutionAttempt) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO execution_attempts VALUES (?, ?, ?, ?)",
                (
                    attempt.id,
                    attempt.task_id,
                    attempt.root_task_id,
                    attempt.model_dump_json(),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (attempt.task_id, GraphRelation.HAS_EXECUTION, attempt.id),
            )
            if attempt.fallback_from_attempt_id:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (
                        attempt.fallback_from_attempt_id,
                        GraphRelation.FALLBACK_TO,
                        attempt.id,
                    ),
                )
            if attempt.route_prediction_id:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (
                        attempt.route_prediction_id,
                        GraphRelation.PREDICTED_EXECUTION,
                        attempt.id,
                    ),
                )

    def execution_attempts(self, task_id: str | None = None) -> list[ExecutionAttempt]:
        query = "SELECT payload FROM execution_attempts"
        params: tuple[str, ...] = ()
        if task_id is not None:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [ExecutionAttempt.model_validate_json(row["payload"]) for row in rows]

    def save_route_prediction(self, prediction: RoutePrediction) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO route_predictions VALUES (?, ?, ?)",
                (prediction.id, prediction.task_id, prediction.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (prediction.task_id, GraphRelation.HAS_ROUTE_PREDICTION, prediction.id),
            )

    def route_predictions(self, task_id: str | None = None) -> list[RoutePrediction]:
        query = "SELECT payload FROM route_predictions"
        params: tuple[str, ...] = ()
        if task_id is not None:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [RoutePrediction.model_validate_json(row["payload"]) for row in rows]

    def save_routing_policy_update(self, update: RoutingPolicyUpdate) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO routing_policy_updates VALUES (?, ?, ?)",
                (update.id, update.version, update.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (update.root_task_id, GraphRelation.HAS_POLICY_UPDATE, update.id),
            )
            for execution_id in update.evidence_execution_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (update.id, GraphRelation.BASED_ON_EXECUTION, execution_id),
                )

    def routing_policy_updates(self) -> list[RoutingPolicyUpdate]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM routing_policy_updates ORDER BY version, rowid"
            ).fetchall()
        return [RoutingPolicyUpdate.model_validate_json(row["payload"]) for row in rows]

    def save_route_evaluation(self, evaluation: RouteEvaluation) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO route_evaluations VALUES (?, ?, ?)",
                (evaluation.id, evaluation.prediction_id, evaluation.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (
                    evaluation.prediction_id,
                    GraphRelation.EVALUATES_PREDICTION,
                    evaluation.id,
                ),
            )

    def route_evaluations(self) -> list[RouteEvaluation]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM route_evaluations ORDER BY rowid").fetchall()
        return [RouteEvaluation.model_validate_json(row["payload"]) for row in rows]

    def save_repair_proposal(self, proposal: RepairProposal) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO repair_proposals VALUES (?, ?, ?, ?)",
                (
                    proposal.id,
                    proposal.repair_task_id,
                    proposal.signature,
                    proposal.model_dump_json(),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (proposal.repair_task_id, GraphRelation.PROPOSED_PATCH, proposal.id),
            )

    def repair_proposals(self, task_id: str | None = None) -> list[RepairProposal]:
        query = "SELECT payload FROM repair_proposals"
        params: tuple[str, ...] = ()
        if task_id is not None:
            query += " WHERE repair_task_id = ?"
            params = (task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [RepairProposal.model_validate_json(row["payload"]) for row in rows]

    def save_repair_validation(self, validation: RepairValidation) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO repair_validations VALUES (?, ?, ?, ?)",
                (
                    validation.id,
                    validation.repair_task_id,
                    validation.proposal_id,
                    validation.model_dump_json(),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (validation.proposal_id, GraphRelation.VALIDATED_BY, validation.id),
            )
            if validation.status.value == "VERIFIED":
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (
                        validation.repair_task_id,
                        GraphRelation.VERIFIED_REPAIR,
                        validation.id,
                    ),
                )

    def repair_validations(self, task_id: str | None = None) -> list[RepairValidation]:
        query = "SELECT payload FROM repair_validations"
        params: tuple[str, ...] = ()
        if task_id is not None:
            query += " WHERE repair_task_id = ?"
            params = (task_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [RepairValidation.model_validate_json(row["payload"]) for row in rows]

    def save_repair_approval(self, approval: RepairApproval) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO repair_approvals VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET proposal_id=excluded.proposal_id, "
                "payload=excluded.payload",
                (approval.id, approval.proposal_id, approval.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (approval.proposal_id, GraphRelation.HAS_APPROVAL, approval.id),
            )
            if approval.decision.value == "APPROVED":
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (approval.id, GraphRelation.APPROVES_REPAIR, approval.proposal_id),
                )

    def repair_approvals(self, proposal_id: str | None = None) -> list[RepairApproval]:
        query = "SELECT payload FROM repair_approvals"
        params: tuple[str, ...] = ()
        if proposal_id is not None:
            query += " WHERE proposal_id = ?"
            params = (proposal_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [RepairApproval.model_validate_json(row["payload"]) for row in rows]

    def save_repair_promotion(self, promotion: RepairPromotion) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO repair_promotions VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET proposal_id=excluded.proposal_id, "
                "payload=excluded.payload",
                (promotion.id, promotion.proposal_id, promotion.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (
                    promotion.proposal_id,
                    GraphRelation.HAS_PROMOTION_RUN,
                    promotion.id,
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (promotion.approval_id, GraphRelation.APPLIED_REPAIR, promotion.id),
            )
            if promotion.status.value == "VERIFIED":
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (
                        promotion.id,
                        GraphRelation.FINAL_VALIDATED_BY,
                        promotion.validation_id,
                    ),
                )
            if promotion.status.value == "ROLLED_BACK":
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (
                        promotion.id,
                        GraphRelation.ROLLED_BACK_REPAIR,
                        promotion.proposal_id,
                    ),
                )

    def repair_promotions(self, proposal_id: str | None = None) -> list[RepairPromotion]:
        query = "SELECT payload FROM repair_promotions"
        params: tuple[str, ...] = ()
        if proposal_id is not None:
            query += " WHERE proposal_id = ?"
            params = (proposal_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [RepairPromotion.model_validate_json(row["payload"]) for row in rows]

    def save_post_repair_reconciliation(self, reconciliation: PostRepairReconciliation) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO post_repair_reconciliations VALUES (?, ?, ?)",
                (
                    reconciliation.id,
                    reconciliation.promotion_id,
                    reconciliation.model_dump_json(),
                ),
            )
            for source, relation, target in (
                (
                    reconciliation.promotion_id,
                    GraphRelation.RECONCILED_BY,
                    reconciliation.id,
                ),
                (
                    reconciliation.id,
                    GraphRelation.RECONCILIATION_SCAN,
                    reconciliation.scan_id,
                ),
                (
                    reconciliation.id,
                    GraphRelation.RECORDED_REPAIRED_STATE,
                    reconciliation.replacement_claim_id,
                ),
                (
                    reconciliation.id,
                    GraphRelation.PROVED_FOLLOWUP_REUSE,
                    reconciliation.follow_up_task_id,
                ),
            ):
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (source, relation, target),
                )

    def post_repair_reconciliations(
        self, promotion_id: str | None = None
    ) -> list[PostRepairReconciliation]:
        query = "SELECT payload FROM post_repair_reconciliations"
        params: tuple[str, ...] = ()
        if promotion_id is not None:
            query += " WHERE promotion_id = ?"
            params = (promotion_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [PostRepairReconciliation.model_validate_json(row["payload"]) for row in rows]

    def save_maintenance_workflow(self, workflow: MaintenanceWorkflow) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO maintenance_workflows VALUES (?, ?, ?)",
                (workflow.id, workflow.signature, workflow.model_dump_json()),
            )
            links = (
                (GraphRelation.WORKFLOW_DIAGNOSIS, workflow.diagnosis_task_id),
                (GraphRelation.WORKFLOW_REPAIR, workflow.repair_task_id),
                (GraphRelation.WORKFLOW_APPROVAL, workflow.approval_id),
                (GraphRelation.WORKFLOW_PROMOTION, workflow.promotion_id),
                (GraphRelation.WORKFLOW_RECONCILIATION, workflow.reconciliation_id),
                (GraphRelation.WORKFLOW_FOLLOWUP, workflow.follow_up_task_id),
            )
            for relation, target in links:
                if target:
                    db.execute(
                        "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                        (workflow.id, relation, target),
                    )

    def maintenance_workflows(self) -> list[MaintenanceWorkflow]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM maintenance_workflows ORDER BY rowid").fetchall()
        return [MaintenanceWorkflow.model_validate_json(row["payload"]) for row in rows]

    @staticmethod
    def _lease_root(project_root: str) -> str:
        return str(Path(project_root).resolve()).casefold()

    def acquire_project_lease(
        self,
        project_root: str,
        holder_id: str,
        workflow_id: str | None,
        *,
        ttl_seconds: float = 120,
        now: datetime | None = None,
        recovery_journal_id: str | None = None,
    ) -> ProjectLeaseAcquisition:
        moment = now or datetime.now(UTC)
        root = self._lease_root(project_root)
        project_id = next(
            (item.id for item in self.projects() if self._lease_root(item.root) == root), None
        )
        unfinished = [
            attempt.promotion.mutation_journal
            for attempt in self.implementation_sandboxes()
            if attempt.promotion
            and attempt.promotion.mutation_journal
            and not attempt.promotion.mutation_journal.terminal
            and self._lease_root(attempt.project_root) == root
        ]
        if unfinished and recovery_journal_id not in {item.id for item in unfinished}:
            raise RuntimeError(
                "Project has an incomplete sandbox promotion; recover it before acquiring another mutation lease."
            )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM project_leases WHERE project_root = ?", (root,)
            ).fetchone()
            current = ProjectLease.model_validate_json(row["payload"]) if row else None
            if (
                current
                and current.status == ProjectLeaseStatus.ACTIVE
                and current.expires_at > moment
                and current.holder_id != holder_id
            ):
                current.events.append(
                    ProjectLeaseEvent(
                        kind=ProjectLeaseEventKind.CONTENDED,
                        holder_id=holder_id,
                        workflow_id=workflow_id,
                        detail=f"Lease held by {current.holder_id} until {current.expires_at.isoformat()}.",
                        occurred_at=moment,
                    )
                )
                db.execute(
                    "UPDATE project_leases SET payload=? WHERE project_root=?",
                    (current.model_dump_json(), root),
                )
                return ProjectLeaseAcquisition(acquired=False, lease=current)
            reclaimed = bool(
                current
                and current.status == ProjectLeaseStatus.ACTIVE
                and current.expires_at <= moment
            )
            if (
                current
                and current.holder_id == holder_id
                and current.status == ProjectLeaseStatus.ACTIVE
                and current.expires_at > moment
            ):
                current.renewed_at = moment
                current.expires_at = moment + timedelta(seconds=ttl_seconds)
                current.workflow_id = workflow_id or current.workflow_id
                current.events.append(
                    ProjectLeaseEvent(
                        kind=ProjectLeaseEventKind.RENEWED,
                        holder_id=holder_id,
                        workflow_id=workflow_id,
                        detail="Lease renewed by its current holder.",
                        occurred_at=moment,
                    )
                )
                lease = current
            else:
                fence = (current.fencing_token + 1) if current else 1
                kind = (
                    ProjectLeaseEventKind.RECLAIMED if reclaimed else ProjectLeaseEventKind.ACQUIRED
                )
                lease = ProjectLease(
                    project_root=str(Path(project_root).resolve()),
                    project_id=project_id,
                    holder_id=holder_id,
                    workflow_id=workflow_id,
                    fencing_token=fence,
                    acquired_at=moment,
                    renewed_at=moment,
                    expires_at=moment + timedelta(seconds=ttl_seconds),
                    events=(current.events if current else [])
                    + [
                        ProjectLeaseEvent(
                            kind=kind,
                            holder_id=holder_id,
                            workflow_id=workflow_id,
                            detail="Expired lease reclaimed by a new holder."
                            if reclaimed
                            else "Exclusive project mutation lease acquired.",
                            occurred_at=moment,
                        )
                    ],
                )
            db.execute(
                "INSERT OR REPLACE INTO project_leases VALUES (?, ?)",
                (root, lease.model_dump_json()),
            )
            return ProjectLeaseAcquisition(acquired=True, reclaimed=reclaimed, lease=lease)

    def renew_project_lease(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        *,
        ttl_seconds: float = 120,
        now: datetime | None = None,
    ) -> ProjectLease:
        moment = now or datetime.now(UTC)
        root = self._lease_root(project_root)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM project_leases WHERE project_root=?", (root,)
            ).fetchone()
            if not row:
                raise RuntimeError("Project lease no longer exists.")
            lease = ProjectLease.model_validate_json(row["payload"])
            if (
                lease.status != ProjectLeaseStatus.ACTIVE
                or lease.holder_id != holder_id
                or lease.fencing_token != fencing_token
                or lease.expires_at <= moment
            ):
                raise RuntimeError("Project lease is stale or owned by another process.")
            lease.renewed_at, lease.expires_at = moment, moment + timedelta(seconds=ttl_seconds)
            lease.events.append(
                ProjectLeaseEvent(
                    kind=ProjectLeaseEventKind.RENEWED,
                    holder_id=holder_id,
                    workflow_id=lease.workflow_id,
                    detail="Exclusive mutation lease renewed.",
                    occurred_at=moment,
                )
            )
            db.execute(
                "UPDATE project_leases SET payload=? WHERE project_root=?",
                (lease.model_dump_json(), root),
            )
            return lease

    def release_project_lease(
        self, project_root: str, holder_id: str, fencing_token: int, *, now: datetime | None = None
    ) -> ProjectLease:
        return self.record_project_lease_event(
            project_root,
            holder_id,
            fencing_token,
            ProjectLeaseEventKind.RELEASED,
            "Exclusive project mutation lease released.",
            now=now,
        )

    def record_project_lease_event(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        kind: ProjectLeaseEventKind,
        detail: str,
        *,
        workflow_id: str | None = None,
        now: datetime | None = None,
    ) -> ProjectLease:
        moment = now or datetime.now(UTC)
        root = self._lease_root(project_root)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM project_leases WHERE project_root=?", (root,)
            ).fetchone()
            if not row:
                raise RuntimeError("Project lease no longer exists.")
            lease = ProjectLease.model_validate_json(row["payload"])
            if (
                lease.holder_id != holder_id
                or lease.fencing_token != fencing_token
                or lease.status != ProjectLeaseStatus.ACTIVE
            ):
                raise RuntimeError("Project lease is stale or owned by another process.")
            lease.events.append(
                ProjectLeaseEvent(
                    kind=kind,
                    holder_id=holder_id,
                    workflow_id=workflow_id or lease.workflow_id,
                    detail=detail,
                    occurred_at=moment,
                )
            )
            if kind == ProjectLeaseEventKind.RELEASED:
                lease.status, lease.released_at = ProjectLeaseStatus.RELEASED, moment
            db.execute(
                "UPDATE project_leases SET payload=? WHERE project_root=?",
                (lease.model_dump_json(), root),
            )
            return lease

    def project_leases(self) -> list[ProjectLease]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM project_leases ORDER BY project_root").fetchall()
        return [ProjectLease.model_validate_json(row["payload"]) for row in rows]

    def save_evaluation_run(self, run: EvaluationRun) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO evaluation_runs VALUES (?, ?, ?)",
                (run.id, run.suite_version, run.model_dump_json()),
            )

    def evaluation_runs(self) -> list[EvaluationRun]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM evaluation_runs ORDER BY rowid").fetchall()
        return [EvaluationRun.model_validate_json(row["payload"]) for row in rows]

    def save_codex_readonly_proof(self, proof: CodexReadOnlyProof) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO codex_readonly_proofs VALUES (?, ?)",
                (proof.id, proof.model_dump_json()),
            )

    def codex_readonly_proofs(self) -> list[CodexReadOnlyProof]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM codex_readonly_proofs ORDER BY rowid").fetchall()
        return [CodexReadOnlyProof.model_validate_json(row["payload"]) for row in rows]

    def save_recursive_codex_proof(self, proof: RecursiveCodexDelegationProof) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO recursive_codex_proofs VALUES (?, ?)",
                (proof.id, proof.model_dump_json()),
            )

    def recursive_codex_proofs(self) -> list[RecursiveCodexDelegationProof]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM recursive_codex_proofs ORDER BY rowid"
            ).fetchall()
        return [
            RecursiveCodexDelegationProof.model_validate_json(row["payload"])
            for row in rows
        ]

    def save_generic_codex_evaluation(self, evaluation: GenericCodexEvaluation) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO generic_codex_evaluations VALUES (?, ?)",
                (evaluation.id, evaluation.model_dump_json()),
            )

    def generic_codex_evaluations(self) -> list[GenericCodexEvaluation]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM generic_codex_evaluations ORDER BY rowid"
            ).fetchall()
        return [GenericCodexEvaluation.model_validate_json(row["payload"]) for row in rows]

    def save_investigation_session(self, session: InvestigationSession) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO investigation_sessions VALUES (?, ?)",
                (session.id, session.model_dump_json()),
            )

    def investigation_sessions(self) -> list[InvestigationSession]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM investigation_sessions ORDER BY rowid"
            ).fetchall()
        return [InvestigationSession.model_validate_json(row["payload"]) for row in rows]

    def save_resumable_session_evaluation(
        self, evaluation: ResumableSessionEvaluation
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO resumable_session_evaluations VALUES (?, ?)",
                (evaluation.id, evaluation.model_dump_json()),
            )

    def resumable_session_evaluations(self) -> list[ResumableSessionEvaluation]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM resumable_session_evaluations ORDER BY rowid"
            ).fetchall()
        return [ResumableSessionEvaluation.model_validate_json(row["payload"]) for row in rows]

    def save_unreal_index(self, scan, artifacts, dependencies) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO unreal_index_scans VALUES (?, ?)", (scan.id, scan.model_dump_json()))
            db.execute("DELETE FROM unreal_artifacts WHERE project_id = ?", (scan.project_id,))
            db.execute("DELETE FROM unreal_dependencies WHERE project_id = ?", (scan.project_id,))
            db.executemany("INSERT INTO unreal_artifacts VALUES (?, ?, ?)", [(item.id, item.project_id, item.model_dump_json()) for item in artifacts])
            db.executemany("INSERT INTO unreal_dependencies VALUES (?, ?, ?)", [(item.id, item.project_id, item.model_dump_json()) for item in dependencies])

    def unreal_index_scans(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM unreal_index_scans ORDER BY rowid").fetchall()
        return [UnrealIndexScan.model_validate_json(row["payload"]) for row in rows]

    def unreal_artifacts(self, project_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM unreal_artifacts" + (" WHERE project_id = ?" if project_id else "") + " ORDER BY rowid", (project_id,) if project_id else ()).fetchall()
        return [UnrealArtifact.model_validate_json(row["payload"]) for row in rows]

    def unreal_dependencies(self, project_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM unreal_dependencies" + (" WHERE project_id = ?" if project_id else "") + " ORDER BY rowid", (project_id,) if project_id else ()).fetchall()
        return [UnrealDependency.model_validate_json(row["payload"]) for row in rows]













    def save_project_workspace_record(self, record):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO project_workspace_records VALUES (?, ?, ?)",
                (record.id, record.project_id, record.model_dump_json()),
            )

    def project_workspace_records(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM project_workspace_records ORDER BY rowid"
            ).fetchall()
        return [ProjectWorkspaceRecord.model_validate_json(row["payload"]) for row in rows]

    def save_project_ticket(self, ticket):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO project_tickets VALUES (?, ?, ?)",
                (ticket.id, ticket.project_id, ticket.model_dump_json()),
            )

    def project_tickets(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM project_tickets ORDER BY rowid").fetchall()
        return [ProjectTicket.model_validate_json(row["payload"]) for row in rows]

    def save_ticket_event(self, event):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO ticket_events VALUES (?, ?, ?)",
                (event.id, event.ticket_id, event.model_dump_json()),
            )

    def ticket_events(self, ticket_id=None):
        query = "SELECT payload FROM ticket_events"
        parameters = ()
        if ticket_id:
            query += " WHERE ticket_id = ?"
            parameters = (ticket_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [TicketEvent.model_validate_json(row["payload"]) for row in rows]

    def save_ticket_validation_result(self, result):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO ticket_validation_results VALUES (?, ?, ?)",
                (result.id, result.ticket_id, result.model_dump_json()),
            )

    def ticket_validation_results(self, ticket_id=None):
        query = "SELECT payload FROM ticket_validation_results"
        parameters = ()
        if ticket_id:
            query += " WHERE ticket_id = ?"
            parameters = (ticket_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [TicketValidationResult.model_validate_json(row["payload"]) for row in rows]

    def save_implementation_sandbox(self, attempt):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO implementation_sandboxes VALUES (?, ?, ?)",
                (attempt.id, attempt.ticket_id, attempt.model_dump_json()),
            )
            if attempt.promotion and attempt.promotion.reconciliation:
                reconciliation = attempt.promotion.reconciliation
                for source, relation, target in [
                    (attempt.promotion.id, GraphRelation.RECONCILED_BY, reconciliation.id),
                    (reconciliation.id, GraphRelation.RECONCILIATION_SCAN, reconciliation.scan_id),
                    *[
                        (reconciliation.id, GraphRelation.RECORDED_REPAIRED_STATE, claim_id)
                        for claim_id in reconciliation.replacement_claim_ids
                    ],
                ]:
                    db.execute(
                        "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                        (source, relation, target),
                    )

    def implementation_sandboxes(self, ticket_id=None):
        query = "SELECT payload FROM implementation_sandboxes"
        parameters = ()
        if ticket_id:
            query += " WHERE ticket_id = ?"
            parameters = (ticket_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [ImplementationSandboxAttempt.model_validate_json(row["payload"]) for row in rows]

    def save_observer_activity(self, state):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO observer_activities VALUES (?, ?, ?)",
                (state.id, state.activity_kind, state.model_dump_json()),
            )

    def observer_activities(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM observer_activities ORDER BY rowid"
            ).fetchall()
        return [ObserverActivityState.model_validate_json(row["payload"]) for row in rows]

    def save_scheduled_work(self, item):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO scheduled_work VALUES (?, ?, ?, ?, ?)",
                (item.id, item.ticket_id, item.project_id, item.status, item.model_dump_json()),
            )

    def scheduled_work(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM scheduled_work ORDER BY rowid"
            ).fetchall()
        return [ScheduledWorkItem.model_validate_json(row["payload"]) for row in rows]

    def save_project_governance_policy(self, policy):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO project_governance_policies VALUES (?, ?, ?)",
                (policy.id, policy.project_id, policy.model_dump_json()),
            )

    def project_governance_policies(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM project_governance_policies ORDER BY project_id"
            ).fetchall()
        return [ProjectGovernancePolicy.model_validate_json(row["payload"]) for row in rows]

    def save_project_record(self, project: ProjectRecord) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO projects VALUES (?, ?, ?)",
                (project.id, project.root, project.model_dump_json()),
            )

    def save_project_snapshot(
        self,
        project: ProjectRecord,
        scan: ProjectScan,
        files: list[ProjectFile],
        symbols: list[ProjectSymbol],
        tests: list[ProjectTest],
        dependencies: list[ProjectDependency],
    ) -> None:
        with self.connect() as db:
            old_ids = {
                row["id"]
                for table in (
                    "project_files",
                    "project_symbols",
                    "project_tests",
                    "project_dependencies",
                )
                for row in db.execute(
                    f"SELECT id FROM {table} WHERE project_id = ?",
                    (project.id,),
                ).fetchall()
            }
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                parameters = tuple(old_ids)
                db.execute(
                    f"DELETE FROM edges WHERE source IN ({placeholders}) "
                    f"OR target IN ({placeholders})",
                    (*parameters, *parameters),
                )
            for table in (
                "project_files",
                "project_symbols",
                "project_tests",
                "project_dependencies",
            ):
                db.execute(f"DELETE FROM {table} WHERE project_id = ?", (project.id,))
            db.execute(
                "INSERT OR REPLACE INTO projects VALUES (?, ?, ?)",
                (project.id, project.root, project.model_dump_json()),
            )
            db.execute(
                "INSERT OR REPLACE INTO project_scans VALUES (?, ?, ?)",
                (scan.id, project.id, scan.model_dump_json()),
            )
            db.execute(
                "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                (project.id, GraphRelation.HAS_PROJECT_SCAN, scan.id),
            )
            if scan.previous_scan_id:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (scan.id, GraphRelation.PREVIOUS_PROJECT_SCAN, scan.previous_scan_id),
                )
            for item in files:
                db.execute(
                    "INSERT INTO project_files VALUES (?, ?, ?, ?, ?)",
                    (item.id, project.id, item.path, item.lifecycle, item.model_dump_json()),
                )
                relation = (
                    GraphRelation.CONTAINS_PROJECT_FILE
                    if item.lifecycle.value == "ACTIVE"
                    else GraphRelation.OBSERVED_PROJECT_FILE
                )
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (project.id, relation, item.id),
                )
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (scan.id, GraphRelation.OBSERVED_PROJECT_FILE, item.id),
                )
            for item in symbols:
                db.execute(
                    "INSERT INTO project_symbols VALUES (?, ?, ?, ?)",
                    (item.id, project.id, item.file_id, item.model_dump_json()),
                )
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (item.file_id, GraphRelation.DECLARES_SYMBOL, item.id),
                )
            for item in tests:
                db.execute(
                    "INSERT INTO project_tests VALUES (?, ?, ?, ?)",
                    (item.id, project.id, item.file_id, item.model_dump_json()),
                )
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (item.file_id, GraphRelation.DECLARES_TEST, item.id),
                )
            for item in dependencies:
                db.execute(
                    "INSERT INTO project_dependencies VALUES (?, ?, ?, ?)",
                    (item.id, project.id, item.source_file_id, item.model_dump_json()),
                )
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (item.source_file_id, GraphRelation.IMPORTS_DEPENDENCY, item.id),
                )
                if item.target_file_id:
                    db.execute(
                        "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                        (item.id, GraphRelation.DEPENDS_ON_FILE, item.target_file_id),
                    )
            for claim_id in scan.invalidated_claim_ids:
                db.execute(
                    "INSERT OR IGNORE INTO edges VALUES (?, ?, ?)",
                    (claim_id, GraphRelation.INVALIDATED_BY_SCAN, scan.id),
                )

    def projects(self) -> list[ProjectRecord]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM projects ORDER BY rowid").fetchall()
        return [ProjectRecord.model_validate_json(row["payload"]) for row in rows]

    def project_scans(self, project_id: str | None = None) -> list[ProjectScan]:
        query = "SELECT payload FROM project_scans"
        parameters: tuple[str, ...] = ()
        if project_id:
            query += " WHERE project_id = ?"
            parameters = (project_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [ProjectScan.model_validate_json(row["payload"]) for row in rows]

    def project_files(
        self, project_id: str | None = None, *, include_deleted: bool = False
    ) -> list[ProjectFile]:
        clauses: list[str] = []
        parameters: list[str] = []
        if project_id:
            clauses.append("project_id = ?")
            parameters.append(project_id)
        if not include_deleted:
            clauses.append("lifecycle = 'ACTIVE'")
        query = "SELECT payload FROM project_files"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY path"
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [ProjectFile.model_validate_json(row["payload"]) for row in rows]

    def _project_artifacts(self, table: str, model, project_id: str | None):
        query = f"SELECT payload FROM {table}"
        parameters: tuple[str, ...] = ()
        if project_id:
            query += " WHERE project_id = ?"
            parameters = (project_id,)
        query += " ORDER BY rowid"
        with self.connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [model.model_validate_json(row["payload"]) for row in rows]

    def project_symbols(self, project_id: str | None = None) -> list[ProjectSymbol]:
        return self._project_artifacts("project_symbols", ProjectSymbol, project_id)

    def project_tests(self, project_id: str | None = None) -> list[ProjectTest]:
        return self._project_artifacts("project_tests", ProjectTest, project_id)

    def project_dependencies(self, project_id: str | None = None) -> list[ProjectDependency]:
        return self._project_artifacts("project_dependencies", ProjectDependency, project_id)


class Neo4jGraphStore:
    """Neo4j implementation with the same persistence contract."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def initialize(self) -> None:
        self.driver.verify_connectivity()
        self.driver.execute_query(
            "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (n:Task) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT project_governance_id IF NOT EXISTS "
            "FOR (n:ProjectGovernancePolicy) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT project_governance_project IF NOT EXISTS "
            "FOR (n:ProjectGovernancePolicy) REQUIRE n.project_id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT chat_session_id IF NOT EXISTS "
            "FOR (n:ChatSession) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT chat_turn_id IF NOT EXISTS "
            "FOR (n:ChatTurn) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT conversation_interpretation_id IF NOT EXISTS "
            "FOR (n:ConversationInterpretation) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query("DROP CONSTRAINT claim_fingerprint IF EXISTS")
        self.driver.execute_query(
            "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (n:Claim) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT resolution_attempt_id IF NOT EXISTS "
            "FOR (n:ResolutionAttempt) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT conflict_cluster_id IF NOT EXISTS "
            "FOR (n:ConflictCluster) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT conflict_verdict_id IF NOT EXISTS "
            "FOR (n:ConflictVerdict) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT reconstruction_id IF NOT EXISTS "
            "FOR (n:Reconstruction) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT reconstruction_step_id IF NOT EXISTS "
            "FOR (n:ReconstructionStep) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT promotion_decision_id IF NOT EXISTS "
            "FOR (n:PromotionDecision) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT benchmark_run_id IF NOT EXISTS "
            "FOR (n:BenchmarkRun) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT pathway_id IF NOT EXISTS "
            "FOR (n:VirtualMemoryPathway) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT pathway_token IF NOT EXISTS "
            "FOR (n:VirtualMemoryPathway) REQUIRE n.token IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT pathway_decision_id IF NOT EXISTS "
            "FOR (n:PathwayPromotionDecision) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT pathway_benchmark_id IF NOT EXISTS "
            "FOR (n:PathwayBenchmark) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT execution_attempt_id IF NOT EXISTS "
            "FOR (n:ExecutionAttempt) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT route_prediction_id IF NOT EXISTS "
            "FOR (n:RoutePrediction) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT routing_policy_update_id IF NOT EXISTS "
            "FOR (n:RoutingPolicyUpdate) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT route_evaluation_id IF NOT EXISTS "
            "FOR (n:RouteEvaluation) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT repair_proposal_id IF NOT EXISTS "
            "FOR (n:RepairProposal) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT repair_validation_id IF NOT EXISTS "
            "FOR (n:RepairValidation) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT repair_approval_id IF NOT EXISTS "
            "FOR (n:RepairApproval) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT repair_promotion_id IF NOT EXISTS "
            "FOR (n:RepairPromotion) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT post_repair_reconciliation_id IF NOT EXISTS "
            "FOR (n:PostRepairReconciliation) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT sandbox_promotion_id IF NOT EXISTS "
            "FOR (n:SandboxPromotion) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT sandbox_promotion_reconciliation_id IF NOT EXISTS "
            "FOR (n:SandboxPromotionReconciliation) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT maintenance_workflow_id IF NOT EXISTS "
            "FOR (n:MaintenanceWorkflow) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT maintenance_workflow_signature IF NOT EXISTS "
            "FOR (n:MaintenanceWorkflow) REQUIRE n.signature IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT repair_approval_proposal IF NOT EXISTS "
            "FOR (n:RepairApproval) REQUIRE n.proposal_id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT repair_promotion_proposal IF NOT EXISTS "
            "FOR (n:RepairPromotion) REQUIRE n.proposal_id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT project_lease_root IF NOT EXISTS "
            "FOR (n:ProjectLease) REQUIRE n.project_root IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT evaluation_run_id IF NOT EXISTS "
            "FOR (n:EvaluationRun) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT codex_readonly_proof_id IF NOT EXISTS "
            "FOR (n:CodexReadOnlyProof) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT recursive_codex_proof_id IF NOT EXISTS "
            "FOR (n:RecursiveCodexDelegationProof) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT generic_codex_evaluation_id IF NOT EXISTS "
            "FOR (n:GenericCodexEvaluation) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT investigation_session_id IF NOT EXISTS "
            "FOR (n:InvestigationSession) REQUIRE n.id IS UNIQUE"
        )
        self.driver.execute_query(
            "CREATE CONSTRAINT resumable_session_evaluation_id IF NOT EXISTS "
            "FOR (n:ResumableSessionEvaluation) REQUIRE n.id IS UNIQUE"
        )
        for label, constraint in (
            ("UnrealIndexScan", "unreal_index_scan_id"),
            ("UnrealArtifact", "unreal_artifact_id"),
            ("UnrealDependency", "unreal_dependency_id"),
            ("ProjectWorkspaceRecord", "project_workspace_record_id"),
            ("ProjectTicket", "project_ticket_id"),
            ("TicketEvent", "ticket_event_id"),
            ("TicketValidationResult", "ticket_validation_result_id"),
            ("ImplementationSandboxAttempt", "implementation_sandbox_attempt_id"),
        ):
            self.driver.execute_query(
                f"CREATE CONSTRAINT {constraint} IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )
        for label, name in (
            ("Project", "project_id"),
            ("ProjectScan", "project_scan_id"),
            ("ProjectFile", "project_file_id"),
            ("ProjectSymbol", "project_symbol_id"),
            ("ProjectTest", "project_test_id"),
            ("ProjectDependency", "project_dependency_id"),
        ):
            self.driver.execute_query(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )

    def save_task(self, task: Task) -> None:
        self.driver.execute_query(
            "MERGE (t:Task {id: $id}) SET t.fingerprint=$fingerprint, t.payload=$payload",
            id=task.id,
            fingerprint=task.fingerprint,
            payload=task.model_dump_json(),
        )

    def save_claim(self, task: Task, claim: Claim) -> None:
        initialize_provenance(task, claim)
        self.driver.execute_query(
            "MATCH (t:Task {id: $task_id}) "
            "MERGE (c:Claim {id: $claim_id}) "
            "SET c.fingerprint=$fingerprint, "
            "c.project_fingerprint=$project_fingerprint, c.project_root=$project_root, "
            "c.validity_status=$validity_status, c.memory_tier=$memory_tier, "
            "c.memory_lifecycle=$memory_lifecycle, c.source_task_id=$source_task_id, "
            "c.source_commit=$source_commit, c.learned_at=$learned_at, "
            "c.valid_from=$valid_from, c.payload=$payload "
            "MERGE (t)-[:DISCOVERED]->(c)",
            task_id=task.id,
            fingerprint=claim.fingerprint,
            claim_id=claim.id,
            project_fingerprint=claim.project_fingerprint,
            project_root=claim.project_root,
            validity_status=claim.validity_status.value,
            memory_tier=claim.memory_tier.value,
            memory_lifecycle=claim.memory_lifecycle.value,
            source_task_id=claim.source_task_id,
            source_commit=claim.source_commit,
            learned_at=claim.learned_at.isoformat(),
            valid_from=claim.valid_from,
            payload=claim.model_dump_json(),
        )
        for source_claim_id in claim.source_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=claim.id,
                    relation=GraphRelation.DERIVED_FROM,
                    target=source_claim_id,
                )
            )

    def update_claim(self, claim: Claim) -> None:
        self.driver.execute_query(
            "MATCH (c:Claim {id: $id}) "
            "SET c.fingerprint=$fingerprint, c.project_fingerprint=$project_fingerprint, "
            "c.project_root=$project_root, c.memory_tier=$memory_tier, "
            "c.memory_lifecycle=$memory_lifecycle, c.successful_reuse_count=$reuse_count, "
            "c.validity_status=$validity_status, c.valid_until=$valid_until, "
            "c.superseded_by_claim_id=$superseded_by_claim_id, c.payload=$payload",
            id=claim.id,
            fingerprint=claim.fingerprint,
            project_fingerprint=claim.project_fingerprint,
            project_root=claim.project_root,
            memory_tier=claim.memory_tier.value,
            memory_lifecycle=claim.memory_lifecycle.value,
            reuse_count=claim.successful_reuse_count,
            validity_status=claim.validity_status.value,
            valid_until=claim.valid_until,
            superseded_by_claim_id=claim.superseded_by_claim_id,
            payload=claim.model_dump_json(),
        )

    def find_claim(self, fingerprint: str) -> Claim | None:
        records, _, _ = self.driver.execute_query(
            "MATCH (c:Claim {fingerprint: $fingerprint}) RETURN c.payload AS payload",
            fingerprint=fingerprint,
        )
        return Claim.model_validate_json(records[0]["payload"]) if records else None

    def find_claims(self, project_fingerprint: str) -> list[Claim]:
        records, _, _ = self.driver.execute_query(
            "MATCH (c:Claim {project_fingerprint: $project_fingerprint}) "
            "RETURN c.payload AS payload",
            project_fingerprint=project_fingerprint,
        )
        return [Claim.model_validate_json(record["payload"]) for record in records]

    def get_task(self, task_id: str) -> Task | None:
        records, _, _ = self.driver.execute_query(
            "MATCH (t:Task {id: $id}) RETURN t.payload AS payload", id=task_id
        )
        return Task.model_validate_json(records[0]["payload"]) if records else None

    def get_claim(self, claim_id: str) -> Claim | None:
        records, _, _ = self.driver.execute_query(
            "MATCH (c:Claim {id: $id}) RETURN c.payload AS payload", id=claim_id
        )
        return Claim.model_validate_json(records[0]["payload"]) if records else None

    def save_edge(self, edge: GraphEdge) -> None:
        relation = GraphRelation(edge.relation).value
        self.driver.execute_query(
            f"MATCH (source {{id: $source}}), (target {{id: $target}}) "
            f"MERGE (source)-[:{relation}]->(target)",
            source=edge.source,
            target=edge.target,
        )

    def edges(self) -> list[GraphEdge]:
        records, _, _ = self.driver.execute_query(
            "MATCH (source)-[edge]->(target) "
            "WHERE type(edge) IN $relations "
            "RETURN source.id AS source, type(edge) AS relation, target.id AS target",
            relations=[relation.value for relation in GraphRelation],
        )
        return [GraphEdge.model_validate(dict(record)) for record in records]

    def tasks(self) -> list[Task]:
        records, _, _ = self.driver.execute_query("MATCH (t:Task) RETURN t.payload AS payload")
        return [Task.model_validate_json(record["payload"]) for record in records]

    def claims(self) -> list[Claim]:
        records, _, _ = self.driver.execute_query("MATCH (c:Claim) RETURN c.payload AS payload")
        return [Claim.model_validate_json(record["payload"]) for record in records]

    def save_resolution_attempt(self, attempt: ResolutionAttempt) -> None:
        self.driver.execute_query(
            "MATCH (t:Task {id: $task_id}) "
            "MERGE (a:ResolutionAttempt {id: $id}) "
            "SET a.task_id=$task_id, a.created_at=$created_at, a.payload=$payload "
            "MERGE (t)-[:ATTEMPTED]->(a)",
            task_id=attempt.task_id,
            id=attempt.id,
            created_at=attempt.created_at.isoformat(),
            payload=attempt.model_dump_json(),
        )

    def resolution_attempts(self, task_id: str) -> list[ResolutionAttempt]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:Task {id: $task_id})-[:ATTEMPTED]->(a:ResolutionAttempt) "
            "RETURN a.payload AS payload ORDER BY a.created_at, a.id",
            task_id=task_id,
        )
        return [ResolutionAttempt.model_validate_json(record["payload"]) for record in records]

    def save_conflict_cluster(self, cluster: ConflictCluster) -> None:
        self.driver.execute_query(
            "MERGE (c:ConflictCluster {id: $id}) "
            "SET c.project_fingerprint=$project_fingerprint, "
            "c.assertion_key=$assertion_key, c.status=$status, c.payload=$payload",
            id=cluster.id,
            project_fingerprint=cluster.project_fingerprint,
            assertion_key=cluster.assertion_key,
            status=cluster.status.value,
            payload=cluster.model_dump_json(),
        )

    def get_conflict_cluster(self, cluster_id: str) -> ConflictCluster | None:
        records, _, _ = self.driver.execute_query(
            "MATCH (c:ConflictCluster {id: $id}) RETURN c.payload AS payload", id=cluster_id
        )
        return ConflictCluster.model_validate_json(records[0]["payload"]) if records else None

    def conflict_clusters(self) -> list[ConflictCluster]:
        records, _, _ = self.driver.execute_query(
            "MATCH (c:ConflictCluster) RETURN c.payload AS payload"
        )
        return [ConflictCluster.model_validate_json(record["payload"]) for record in records]

    def save_conflict_verdict(self, verdict: ConflictVerdict) -> None:
        self.driver.execute_query(
            "MATCH ()-[r]->(v:ConflictVerdict {id: $id}) WHERE type(r) IN $relations DELETE r",
            id=verdict.id,
            relations=[
                GraphRelation.HAS_VERDICT.value,
                GraphRelation.SUPPORTS_VERDICT.value,
                GraphRelation.CONTRADICTS_VERDICT.value,
                GraphRelation.EVIDENCE_FOR_VERDICT.value,
            ],
        )
        self.driver.execute_query(
            "MATCH (t:Task {id: $task_id}) "
            "MERGE (v:ConflictVerdict {id: $id}) "
            "SET v.resolution_task_id=$task_id, v.assertion_key=$assertion_key, "
            "v.status=$status, v.selected_value=$selected_value, "
            "v.confidence=$confidence, v.payload=$payload "
            "MERGE (t)-[:HAS_VERDICT]->(v)",
            task_id=verdict.resolution_task_id,
            id=verdict.id,
            assertion_key=verdict.assertion_key,
            status=verdict.status.value,
            selected_value=verdict.selected_value,
            confidence=verdict.confidence,
            payload=verdict.model_dump_json(),
        )
        for claim_id in verdict.supporting_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=claim_id,
                    relation=GraphRelation.SUPPORTS_VERDICT,
                    target=verdict.id,
                )
            )
        for claim_id in verdict.contradicting_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=claim_id,
                    relation=GraphRelation.CONTRADICTS_VERDICT,
                    target=verdict.id,
                )
            )
        for claim_id in verdict.evidence_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=claim_id,
                    relation=GraphRelation.EVIDENCE_FOR_VERDICT,
                    target=verdict.id,
                )
            )

    def conflict_verdicts(self, task_id: str | None = None) -> list[ConflictVerdict]:
        parameters = {}
        if task_id is None:
            query = "MATCH (v:ConflictVerdict) "
        else:
            query = "MATCH (:Task {id: $task_id})-[:HAS_VERDICT]->(v:ConflictVerdict) "
            parameters["task_id"] = task_id
        query += "RETURN v.payload AS payload ORDER BY v.id"
        records, _, _ = self.driver.execute_query(query, parameters_=parameters)
        return [ConflictVerdict.model_validate_json(record["payload"]) for record in records]

    def save_reconstruction(self, session: ReconstructionSession) -> None:
        self.driver.execute_query(
            "MATCH (t:Task {id: $task_id}) "
            "MERGE (r:Reconstruction {id: $id}) "
            "SET r.status=$status, r.reconstructed_tokens=$reconstructed_tokens, "
            "r.baseline_tokens=$baseline_tokens, r.payload=$payload "
            "MERGE (t)-[:HAS_RECONSTRUCTION]->(r)",
            task_id=session.task_id,
            id=session.id,
            status=session.status.value,
            reconstructed_tokens=session.reconstructed_token_estimate,
            baseline_tokens=session.baseline_token_estimate,
            payload=session.model_dump_json(),
        )
        relation_by_action = {
            ReconstructionAction.SEED: GraphRelation.SEEDED,
            ReconstructionAction.EXPAND: GraphRelation.EXPANDED_TO,
            ReconstructionAction.PRUNE: GraphRelation.PRUNED_FROM,
        }
        for step in session.steps:
            relation = relation_by_action[step.action].value
            self.driver.execute_query(
                "MATCH (r:Reconstruction {id: $session_id}), (claim:Claim {id: $node_id}) "
                "MERGE (s:ReconstructionStep {id: $id}) "
                "SET s.sequence=$sequence, s.action=$action, s.reason=$reason, "
                "s.score=$score, s.payload=$payload "
                "MERGE (r)-[:HAS_STEP]->(s) "
                f"MERGE (s)-[:{relation}]->(claim)",
                session_id=session.id,
                node_id=step.node_id,
                id=step.id,
                sequence=step.sequence,
                action=step.action.value,
                reason=step.reason,
                score=step.score,
                payload=step.model_dump_json(),
            )

    def get_reconstruction(self, session_id: str) -> ReconstructionSession | None:
        records, _, _ = self.driver.execute_query(
            "MATCH (r:Reconstruction {id: $id}) RETURN r.payload AS payload", id=session_id
        )
        return ReconstructionSession.model_validate_json(records[0]["payload"]) if records else None

    def reconstructions(self) -> list[ReconstructionSession]:
        records, _, _ = self.driver.execute_query(
            "MATCH (r:Reconstruction) RETURN r.payload AS payload"
        )
        return [ReconstructionSession.model_validate_json(record["payload"]) for record in records]

    def save_promotion_decision(self, decision: PromotionDecision) -> None:
        self.driver.execute_query(
            "MATCH (t:Task {id: $task_id}) "
            "MERGE (d:PromotionDecision {id: $id}) "
            "SET d.outcome=$outcome, d.from_tier=$from_tier, d.to_tier=$to_tier, "
            "d.reason=$reason, d.created_at=$created_at, d.payload=$payload "
            "MERGE (t)-[:HAS_PROMOTION]->(d)",
            task_id=decision.task_id,
            id=decision.id,
            outcome=decision.outcome.value,
            from_tier=decision.from_tier.value,
            to_tier=decision.to_tier.value,
            reason=decision.reason,
            created_at=decision.created_at.isoformat(),
            payload=decision.model_dump_json(),
        )
        for claim_id in decision.candidate_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=decision.id,
                    relation=GraphRelation.EVALUATED,
                    target=claim_id,
                )
            )
            if decision.outcome == PromotionOutcome.REJECTED:
                self.save_edge(
                    GraphEdge(
                        source=decision.id,
                        relation=GraphRelation.REJECTED_CANDIDATE,
                        target=claim_id,
                    )
                )
        if decision.promoted_claim_id:
            self.save_edge(
                GraphEdge(
                    source=decision.id,
                    relation=GraphRelation.PROMOTED_TO,
                    target=decision.promoted_claim_id,
                )
            )

    def promotion_decisions(self) -> list[PromotionDecision]:
        records, _, _ = self.driver.execute_query(
            "MATCH (d:PromotionDecision) RETURN d.payload AS payload"
        )
        return [PromotionDecision.model_validate_json(record["payload"]) for record in records]

    def save_benchmark_run(self, run: BenchmarkRun) -> None:
        self.driver.execute_query(
            "MATCH (t:Task {id: $task_id}), (r:Reconstruction {id: $reconstruction_id}) "
            "MERGE (b:BenchmarkRun {id: $id}) "
            "SET b.case_id=$case_id, b.passed=$passed, b.token_reduction=$token_reduction, "
            "b.created_at=$created_at, b.payload=$payload "
            "MERGE (t)-[:HAS_BENCHMARK]->(b) "
            "MERGE (b)-[:MEASURED_RECONSTRUCTION]->(r)",
            task_id=run.task_id,
            reconstruction_id=run.reconstruction_id,
            id=run.id,
            case_id=run.case_id,
            passed=run.passed,
            token_reduction=run.token_reduction,
            created_at=run.created_at.isoformat(),
            payload=run.model_dump_json(),
        )

    def benchmark_runs(self) -> list[BenchmarkRun]:
        records, _, _ = self.driver.execute_query(
            "MATCH (b:BenchmarkRun) RETURN b.payload AS payload"
        )
        return [BenchmarkRun.model_validate_json(record["payload"]) for record in records]

    def save_pathway(self, pathway: VirtualMemoryPathway) -> None:
        self.driver.execute_query(
            "MERGE (p:VirtualMemoryPathway {id: $id}) "
            "SET p.token=$token, p.version=$version, p.signature=$signature, "
            "p.project_root=$project_root, "
            "p.lifecycle=$lifecycle, p.access_frequency=$access_frequency, "
            "p.average_tokens_saved=$average_tokens_saved, p.payload=$payload",
            id=pathway.id,
            token=pathway.token,
            version=pathway.version,
            signature=pathway.signature,
            project_root=pathway.project_root,
            lifecycle=pathway.lifecycle.value,
            access_frequency=pathway.access_frequency,
            average_tokens_saved=pathway.average_tokens_saved,
            payload=pathway.model_dump_json(),
        )
        for claim_id in pathway.source_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=pathway.id,
                    relation=GraphRelation.PATHWAY_INCLUDES,
                    target=claim_id,
                )
            )
        for reconstruction_id in pathway.supporting_reconstruction_ids:
            self.save_edge(
                GraphEdge(
                    source=reconstruction_id,
                    relation=GraphRelation.SUPPORTS_PATHWAY,
                    target=pathway.id,
                )
            )

    def pathways(self) -> list[VirtualMemoryPathway]:
        records, _, _ = self.driver.execute_query(
            "MATCH (p:VirtualMemoryPathway) RETURN p.payload AS payload"
        )
        return [VirtualMemoryPathway.model_validate_json(record["payload"]) for record in records]

    def save_pathway_decision(self, decision: PathwayPromotionDecision) -> None:
        self.driver.execute_query(
            "MERGE (d:PathwayPromotionDecision {id: $id}) "
            "SET d.outcome=$outcome, d.reason=$reason, d.payload=$payload",
            id=decision.id,
            outcome=decision.outcome.value,
            reason=decision.reason,
            payload=decision.model_dump_json(),
        )
        for task_id in decision.candidate_task_ids:
            self.save_edge(
                GraphEdge(
                    source=task_id,
                    relation=GraphRelation.HAS_PATHWAY_DECISION,
                    target=decision.id,
                )
            )
        if decision.pathway_id:
            self.save_edge(
                GraphEdge(
                    source=decision.id,
                    relation=GraphRelation.PROMOTED_PATHWAY,
                    target=decision.pathway_id,
                )
            )

    def pathway_decisions(self) -> list[PathwayPromotionDecision]:
        records, _, _ = self.driver.execute_query(
            "MATCH (d:PathwayPromotionDecision) RETURN d.payload AS payload"
        )
        return [
            PathwayPromotionDecision.model_validate_json(record["payload"]) for record in records
        ]

    def save_pathway_benchmark(self, result: PathwayBenchmarkResult) -> None:
        self.driver.execute_query(
            "MATCH (p:VirtualMemoryPathway {id: $pathway_id}) "
            "MERGE (b:PathwayBenchmark {id: $id}) "
            "SET b.additional_reduction=$additional_reduction, b.correct=$correct, "
            "b.evidence_preserved=$evidence_preserved, b.payload=$payload "
            "MERGE (p)-[:HAS_BENCHMARK]->(b)",
            pathway_id=result.pathway_id,
            id=result.id,
            additional_reduction=result.additional_reduction,
            correct=result.correct,
            evidence_preserved=result.evidence_preserved,
            payload=result.model_dump_json(),
        )

    def pathway_benchmarks(self) -> list[PathwayBenchmarkResult]:
        records, _, _ = self.driver.execute_query(
            "MATCH (b:PathwayBenchmark) RETURN b.payload AS payload"
        )
        return [PathwayBenchmarkResult.model_validate_json(record["payload"]) for record in records]

    def save_plan_decision(self, decision: PlanDecision) -> None:
        self.driver.execute_query(
            "MATCH (root:Task {id: $root_task_id}), (task:Task {id: $task_id}) "
            "MERGE (d:PlanDecision {id: $id}) "
            "SET d.root_task_id=$root_task_id, d.task_id=$task_id, "
            "d.action=$action, d.reason=$reason, d.priority=$priority, "
            "d.route=$route, d.created_at=$created_at, d.payload=$payload "
            "MERGE (root)-[:HAS_PLAN_DECISION]->(d) "
            "MERGE (d)-[:PLANNED_TASK]->(task)",
            root_task_id=decision.root_task_id,
            task_id=decision.task_id,
            id=decision.id,
            action=decision.action.value,
            reason=decision.reason,
            priority=decision.priority,
            route=decision.route.value if decision.route else None,
            created_at=decision.created_at.isoformat(),
            payload=decision.model_dump_json(),
        )

    def plan_decisions(self, root_task_id: str | None = None) -> list[PlanDecision]:
        where = " WHERE d.root_task_id = $root_task_id" if root_task_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (d:PlanDecision)" + where + " RETURN d.payload AS payload ORDER BY d.created_at",
            root_task_id=root_task_id,
        )
        return [PlanDecision.model_validate_json(record["payload"]) for record in records]

    def save_planning_run(self, run: PlanningRun) -> None:
        self.driver.execute_query(
            "MATCH (root:Task {id: $root_task_id}) "
            "MERGE (r:PlanningRun {id: $id}) "
            "SET r.root_task_id=$root_task_id, r.status=$status, "
            "r.stopping_reason=$stopping_reason, r.model_calls_used=$model_calls_used, "
            "r.retrieval_tokens_used=$retrieval_tokens_used, "
            "r.elapsed_seconds=$elapsed_seconds, r.started_at=$started_at, r.payload=$payload "
            "MERGE (root)-[:HAS_PLANNING_RUN]->(r)",
            id=run.id,
            root_task_id=run.root_task_id,
            status=run.status.value,
            stopping_reason=run.stopping_reason.value if run.stopping_reason else None,
            model_calls_used=run.model_calls_used,
            retrieval_tokens_used=run.retrieval_tokens_used,
            elapsed_seconds=run.elapsed_seconds,
            started_at=run.started_at.isoformat(),
            payload=run.model_dump_json(),
        )

    def planning_runs(self, root_task_id: str | None = None) -> list[PlanningRun]:
        where = " WHERE r.root_task_id = $root_task_id" if root_task_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (r:PlanningRun)" + where + " RETURN r.payload AS payload",
            root_task_id=root_task_id,
        )
        runs = [PlanningRun.model_validate_json(record["payload"]) for record in records]
        return sorted(runs, key=lambda run: (run.started_at, run.id))

    def save_execution_attempt(self, attempt: ExecutionAttempt) -> None:
        self.driver.execute_query(
            "MATCH (task:Task {id: $task_id}) "
            "MERGE (attempt:ExecutionAttempt {id: $id}) "
            "SET attempt.root_task_id=$root_task_id, attempt.task_id=$task_id, "
            "attempt.sequence=$sequence, attempt.planned_route=$planned_route, "
            "attempt.actual_route=$actual_route, attempt.worker=$worker, "
            "attempt.outcome=$outcome, attempt.total_tokens=$total_tokens, "
            "attempt.estimated_cost_usd=$estimated_cost_usd, "
            "attempt.latency_ms=$latency_ms, attempt.created_at=$created_at, "
            "attempt.payload=$payload "
            "MERGE (task)-[:HAS_EXECUTION]->(attempt)",
            id=attempt.id,
            root_task_id=attempt.root_task_id,
            task_id=attempt.task_id,
            sequence=attempt.sequence,
            planned_route=attempt.planned_route.value,
            actual_route=attempt.actual_route.value,
            worker=attempt.worker,
            outcome=attempt.outcome.value,
            total_tokens=attempt.total_tokens,
            estimated_cost_usd=attempt.estimated_cost_usd,
            latency_ms=attempt.latency_ms,
            created_at=attempt.created_at.isoformat(),
            payload=attempt.model_dump_json(),
        )
        if attempt.fallback_from_attempt_id:
            self.driver.execute_query(
                "MATCH (first:ExecutionAttempt {id: $first_id}), "
                "(second:ExecutionAttempt {id: $second_id}) "
                "MERGE (first)-[:FALLBACK_TO]->(second)",
                first_id=attempt.fallback_from_attempt_id,
                second_id=attempt.id,
            )
        if attempt.route_prediction_id:
            self.save_edge(
                GraphEdge(
                    source=attempt.route_prediction_id,
                    relation=GraphRelation.PREDICTED_EXECUTION,
                    target=attempt.id,
                )
            )

    def execution_attempts(self, task_id: str | None = None) -> list[ExecutionAttempt]:
        where = " WHERE attempt.task_id = $task_id" if task_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (attempt:ExecutionAttempt)"
            + where
            + " RETURN attempt.payload AS payload ORDER BY attempt.created_at",
            task_id=task_id,
        )
        return [ExecutionAttempt.model_validate_json(record["payload"]) for record in records]

    def save_route_prediction(self, prediction: RoutePrediction) -> None:
        self.driver.execute_query(
            "MATCH (task:Task {id: $task_id}) "
            "MERGE (prediction:RoutePrediction {id: $id}) "
            "SET prediction.root_task_id=$root_task_id, prediction.task_id=$task_id, "
            "prediction.policy_version=$policy_version, "
            "prediction.static_route=$static_route, prediction.chosen_route=$chosen_route, "
            "prediction.chosen_worker=$chosen_worker, "
            "prediction.changed_static_route=$changed_static_route, "
            "prediction.created_at=$created_at, prediction.payload=$payload "
            "MERGE (task)-[:HAS_ROUTE_PREDICTION]->(prediction)",
            id=prediction.id,
            root_task_id=prediction.root_task_id,
            task_id=prediction.task_id,
            policy_version=prediction.policy_version,
            static_route=prediction.static_route.value,
            chosen_route=prediction.chosen_route.value,
            chosen_worker=prediction.chosen_worker,
            changed_static_route=prediction.changed_static_route,
            created_at=prediction.created_at.isoformat(),
            payload=prediction.model_dump_json(),
        )

    def route_predictions(self, task_id: str | None = None) -> list[RoutePrediction]:
        where = " WHERE prediction.task_id = $task_id" if task_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (prediction:RoutePrediction)"
            + where
            + " RETURN prediction.payload AS payload ORDER BY prediction.created_at",
            task_id=task_id,
        )
        return [RoutePrediction.model_validate_json(record["payload"]) for record in records]

    def save_routing_policy_update(self, update: RoutingPolicyUpdate) -> None:
        self.driver.execute_query(
            "MERGE (update:RoutingPolicyUpdate {id: $id}) "
            "SET update.root_task_id=$root_task_id, "
            "update.triggering_task_id=$triggering_task_id, "
            "update.version=$version, update.previous_version=$previous_version, "
            "update.task_category=$task_category, update.from_route=$from_route, "
            "update.to_route=$to_route, update.accepted=$accepted, "
            "update.created_at=$created_at, update.payload=$payload",
            id=update.id,
            root_task_id=update.root_task_id,
            triggering_task_id=update.triggering_task_id,
            version=update.version,
            previous_version=update.previous_version,
            task_category=update.task_category,
            from_route=update.from_route.value,
            to_route=update.to_route.value,
            accepted=update.accepted,
            created_at=update.created_at.isoformat(),
            payload=update.model_dump_json(),
        )
        self.save_edge(
            GraphEdge(
                source=update.root_task_id,
                relation=GraphRelation.HAS_POLICY_UPDATE,
                target=update.id,
            )
        )
        for execution_id in update.evidence_execution_ids:
            self.save_edge(
                GraphEdge(
                    source=update.id,
                    relation=GraphRelation.BASED_ON_EXECUTION,
                    target=execution_id,
                )
            )

    def routing_policy_updates(self) -> list[RoutingPolicyUpdate]:
        records, _, _ = self.driver.execute_query(
            "MATCH (update:RoutingPolicyUpdate) "
            "RETURN update.payload AS payload ORDER BY update.version, update.created_at"
        )
        return [RoutingPolicyUpdate.model_validate_json(record["payload"]) for record in records]

    def save_route_evaluation(self, evaluation: RouteEvaluation) -> None:
        self.driver.execute_query(
            "MATCH (prediction:RoutePrediction {id: $prediction_id}) "
            "MERGE (evaluation:RouteEvaluation {id: $id}) "
            "SET evaluation.task_id=$task_id, evaluation.policy_version=$policy_version, "
            "evaluation.predicted_route=$predicted_route, "
            "evaluation.actual_final_route=$actual_final_route, "
            "evaluation.actual_success=$actual_success, "
            "evaluation.actual_cost_usd=$actual_cost_usd, "
            "evaluation.actual_latency_ms=$actual_latency_ms, "
            "evaluation.created_at=$created_at, evaluation.payload=$payload "
            "MERGE (prediction)-[:EVALUATES_PREDICTION]->(evaluation)",
            id=evaluation.id,
            prediction_id=evaluation.prediction_id,
            task_id=evaluation.task_id,
            policy_version=evaluation.policy_version,
            predicted_route=evaluation.predicted_route.value,
            actual_final_route=evaluation.actual_final_route.value,
            actual_success=evaluation.actual_success,
            actual_cost_usd=evaluation.actual_cost_usd,
            actual_latency_ms=evaluation.actual_latency_ms,
            created_at=evaluation.created_at.isoformat(),
            payload=evaluation.model_dump_json(),
        )

    def route_evaluations(self) -> list[RouteEvaluation]:
        records, _, _ = self.driver.execute_query(
            "MATCH (evaluation:RouteEvaluation) "
            "RETURN evaluation.payload AS payload ORDER BY evaluation.created_at"
        )
        return [RouteEvaluation.model_validate_json(record["payload"]) for record in records]

    def save_repair_proposal(self, proposal: RepairProposal) -> None:
        self.driver.execute_query(
            "MATCH (task:Task {id: $task_id}) "
            "MERGE (proposal:RepairProposal {id: $id}) "
            "SET proposal.repair_task_id=$task_id, proposal.signature=$signature, "
            "proposal.status=$status, proposal.created_at=$created_at, "
            "proposal.payload=$payload "
            "MERGE (task)-[:PROPOSED_PATCH]->(proposal)",
            task_id=proposal.repair_task_id,
            id=proposal.id,
            signature=proposal.signature,
            status=proposal.status.value,
            created_at=proposal.created_at.isoformat(),
            payload=proposal.model_dump_json(),
        )

    def repair_proposals(self, task_id: str | None = None) -> list[RepairProposal]:
        where = " WHERE proposal.repair_task_id = $task_id" if task_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (proposal:RepairProposal)"
            + where
            + " RETURN proposal.payload AS payload ORDER BY proposal.created_at",
            task_id=task_id,
        )
        return [RepairProposal.model_validate_json(record["payload"]) for record in records]

    def save_repair_validation(self, validation: RepairValidation) -> None:
        self.driver.execute_query(
            "MATCH (proposal:RepairProposal {id: $proposal_id}) "
            "MERGE (validation:RepairValidation {id: $id}) "
            "SET validation.repair_task_id=$task_id, validation.proposal_id=$proposal_id, "
            "validation.status=$status, validation.attempt=$attempt, "
            "validation.created_at=$created_at, validation.payload=$payload "
            "MERGE (proposal)-[:VALIDATED_BY]->(validation)",
            id=validation.id,
            task_id=validation.repair_task_id,
            proposal_id=validation.proposal_id,
            status=validation.status.value,
            attempt=validation.attempt,
            created_at=validation.created_at.isoformat(),
            payload=validation.model_dump_json(),
        )
        if validation.status.value == "VERIFIED":
            self.driver.execute_query(
                "MATCH (task:Task {id: $task_id}), "
                "(validation:RepairValidation {id: $validation_id}) "
                "MERGE (task)-[:VERIFIED_REPAIR]->(validation)",
                task_id=validation.repair_task_id,
                validation_id=validation.id,
            )

    def repair_validations(self, task_id: str | None = None) -> list[RepairValidation]:
        where = " WHERE validation.repair_task_id = $task_id" if task_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (validation:RepairValidation)"
            + where
            + " RETURN validation.payload AS payload ORDER BY validation.created_at",
            task_id=task_id,
        )
        return [RepairValidation.model_validate_json(record["payload"]) for record in records]

    def save_repair_approval(self, approval: RepairApproval) -> None:
        self.driver.execute_query(
            "MATCH (proposal:RepairProposal {id: $proposal_id}) "
            "MERGE (approval:RepairApproval {id: $id}) "
            "SET approval.proposal_id=$proposal_id, approval.validation_id=$validation_id, "
            "approval.decision=$decision, approval.approved_by=$approved_by, "
            "approval.created_at=$created_at, approval.payload=$payload "
            "MERGE (proposal)-[:HAS_APPROVAL]->(approval)",
            id=approval.id,
            proposal_id=approval.proposal_id,
            validation_id=approval.validation_id,
            decision=approval.decision.value,
            approved_by=approval.approved_by,
            created_at=approval.created_at.isoformat(),
            payload=approval.model_dump_json(),
        )
        if approval.decision.value == "APPROVED":
            self.driver.execute_query(
                "MATCH (approval:RepairApproval {id: $approval_id}), "
                "(proposal:RepairProposal {id: $proposal_id}) "
                "MERGE (approval)-[:APPROVES_REPAIR]->(proposal)",
                approval_id=approval.id,
                proposal_id=approval.proposal_id,
            )

    def repair_approvals(self, proposal_id: str | None = None) -> list[RepairApproval]:
        where = " WHERE approval.proposal_id = $proposal_id" if proposal_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (approval:RepairApproval)"
            + where
            + " RETURN approval.payload AS payload ORDER BY approval.created_at",
            proposal_id=proposal_id,
        )
        return [RepairApproval.model_validate_json(record["payload"]) for record in records]

    def save_repair_promotion(self, promotion: RepairPromotion) -> None:
        self.driver.execute_query(
            "MATCH (proposal:RepairProposal {id: $proposal_id}), "
            "(approval:RepairApproval {id: $approval_id}) "
            "MERGE (promotion:RepairPromotion {id: $id}) "
            "SET promotion.proposal_id=$proposal_id, promotion.validation_id=$validation_id, "
            "promotion.approval_id=$approval_id, promotion.status=$status, "
            "promotion.created_at=$created_at, promotion.payload=$payload "
            "MERGE (proposal)-[:HAS_PROMOTION_RUN]->(promotion) "
            "MERGE (approval)-[:APPLIED_REPAIR]->(promotion)",
            id=promotion.id,
            proposal_id=promotion.proposal_id,
            validation_id=promotion.validation_id,
            approval_id=promotion.approval_id,
            status=promotion.status.value,
            created_at=promotion.created_at.isoformat(),
            payload=promotion.model_dump_json(),
        )
        if promotion.status.value == "VERIFIED":
            self.driver.execute_query(
                "MATCH (promotion:RepairPromotion {id: $promotion_id}), "
                "(validation:RepairValidation {id: $validation_id}) "
                "MERGE (promotion)-[:FINAL_VALIDATED_BY]->(validation)",
                promotion_id=promotion.id,
                validation_id=promotion.validation_id,
            )
        if promotion.status.value == "ROLLED_BACK":
            self.driver.execute_query(
                "MATCH (promotion:RepairPromotion {id: $promotion_id}), "
                "(proposal:RepairProposal {id: $proposal_id}) "
                "MERGE (promotion)-[:ROLLED_BACK_REPAIR]->(proposal)",
                promotion_id=promotion.id,
                proposal_id=promotion.proposal_id,
            )

    def repair_promotions(self, proposal_id: str | None = None) -> list[RepairPromotion]:
        where = " WHERE promotion.proposal_id = $proposal_id" if proposal_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (promotion:RepairPromotion)"
            + where
            + " RETURN promotion.payload AS payload ORDER BY promotion.created_at",
            proposal_id=proposal_id,
        )
        return [RepairPromotion.model_validate_json(record["payload"]) for record in records]

    def save_post_repair_reconciliation(self, reconciliation: PostRepairReconciliation) -> None:
        self.driver.execute_query(
            "MATCH (promotion:RepairPromotion {id: $promotion_id}), "
            "(scan:ProjectScan {id: $scan_id}), "
            "(claim:Claim {id: $claim_id}), (task:Task {id: $task_id}) "
            "MERGE (reconciliation:PostRepairReconciliation {id: $id}) "
            "SET reconciliation.promotion_id=$promotion_id, "
            "reconciliation.status=$status, reconciliation.created_at=$created_at, "
            "reconciliation.payload=$payload "
            "MERGE (promotion)-[:RECONCILED_BY]->(reconciliation) "
            "MERGE (reconciliation)-[:RECONCILIATION_SCAN]->(scan) "
            "MERGE (reconciliation)-[:RECORDED_REPAIRED_STATE]->(claim) "
            "MERGE (reconciliation)-[:PROVED_FOLLOWUP_REUSE]->(task)",
            id=reconciliation.id,
            promotion_id=reconciliation.promotion_id,
            scan_id=reconciliation.scan_id,
            claim_id=reconciliation.replacement_claim_id,
            task_id=reconciliation.follow_up_task_id,
            status=reconciliation.status.value,
            created_at=reconciliation.created_at.isoformat(),
            payload=reconciliation.model_dump_json(),
        )

    def post_repair_reconciliations(
        self, promotion_id: str | None = None
    ) -> list[PostRepairReconciliation]:
        where = " WHERE reconciliation.promotion_id = $promotion_id" if promotion_id else ""
        records, _, _ = self.driver.execute_query(
            "MATCH (reconciliation:PostRepairReconciliation)"
            + where
            + " RETURN reconciliation.payload AS payload "
            "ORDER BY reconciliation.created_at",
            promotion_id=promotion_id,
        )
        return [
            PostRepairReconciliation.model_validate_json(record["payload"]) for record in records
        ]

    def save_maintenance_workflow(self, workflow: MaintenanceWorkflow) -> None:
        self.driver.execute_query(
            "MERGE (workflow:MaintenanceWorkflow {id: $id}) "
            "SET workflow.signature=$signature, workflow.status=$status, "
            "workflow.project_root=$project_root, workflow.test_path=$test_path, "
            "workflow.updated_at=$updated_at, workflow.payload=$payload",
            id=workflow.id,
            signature=workflow.signature,
            status=workflow.status.value,
            project_root=workflow.project_root,
            test_path=workflow.test_path,
            updated_at=workflow.updated_at.isoformat(),
            payload=workflow.model_dump_json(),
        )
        links = (
            (GraphRelation.WORKFLOW_DIAGNOSIS, workflow.diagnosis_task_id, "Task"),
            (GraphRelation.WORKFLOW_REPAIR, workflow.repair_task_id, "Task"),
            (GraphRelation.WORKFLOW_APPROVAL, workflow.approval_id, "RepairApproval"),
            (GraphRelation.WORKFLOW_PROMOTION, workflow.promotion_id, "RepairPromotion"),
            (
                GraphRelation.WORKFLOW_RECONCILIATION,
                workflow.reconciliation_id,
                "PostRepairReconciliation",
            ),
            (GraphRelation.WORKFLOW_FOLLOWUP, workflow.follow_up_task_id, "Task"),
        )
        for relation, target, label in links:
            if target:
                self.driver.execute_query(
                    f"MATCH (workflow:MaintenanceWorkflow {{id: $workflow_id}}), "
                    f"(artifact:{label} {{id: $target_id}}) "
                    f"MERGE (workflow)-[:{relation.value}]->(artifact)",
                    workflow_id=workflow.id,
                    target_id=target,
                )

    def maintenance_workflows(self) -> list[MaintenanceWorkflow]:
        records, _, _ = self.driver.execute_query(
            "MATCH (workflow:MaintenanceWorkflow) "
            "RETURN workflow.payload AS payload ORDER BY workflow.id"
        )
        return [MaintenanceWorkflow.model_validate_json(record["payload"]) for record in records]

    @staticmethod
    def _lease_root(project_root: str) -> str:
        return str(Path(project_root).resolve()).casefold()

    def acquire_project_lease(
        self,
        project_root: str,
        holder_id: str,
        workflow_id: str | None,
        *,
        ttl_seconds: float = 120,
        now: datetime | None = None,
        recovery_journal_id: str | None = None,
    ) -> ProjectLeaseAcquisition:
        moment = now or datetime.now(UTC)
        root = self._lease_root(project_root)
        project_id = next(
            (item.id for item in self.projects() if self._lease_root(item.root) == root), None
        )
        unfinished = [
            attempt.promotion.mutation_journal
            for attempt in self.implementation_sandboxes()
            if attempt.promotion
            and attempt.promotion.mutation_journal
            and not attempt.promotion.mutation_journal.terminal
            and self._lease_root(attempt.project_root) == root
        ]
        if unfinished and recovery_journal_id not in {item.id for item in unfinished}:
            raise RuntimeError(
                "Project has an incomplete sandbox promotion; recover it before acquiring another mutation lease."
            )

        def operation(tx):
            record = tx.run(
                "MERGE (lease:ProjectLease {project_root:$root}) "
                "ON CREATE SET lease.payload=$empty "
                "SET lease.write_lock=coalesce(lease.write_lock,0)+1 "
                "RETURN lease.payload AS payload",
                root=root,
                empty="",
            ).single()
            current = (
                ProjectLease.model_validate_json(record["payload"])
                if record and record["payload"]
                else None
            )
            if (
                current
                and current.status == ProjectLeaseStatus.ACTIVE
                and current.expires_at > moment
                and current.holder_id != holder_id
            ):
                current.events.append(
                    ProjectLeaseEvent(
                        kind=ProjectLeaseEventKind.CONTENDED,
                        holder_id=holder_id,
                        workflow_id=workflow_id,
                        detail=f"Lease held by {current.holder_id} until {current.expires_at.isoformat()}.",
                        occurred_at=moment,
                    )
                )
                tx.run(
                    "MATCH (lease:ProjectLease {project_root:$root}) SET lease.payload=$payload",
                    root=root,
                    payload=current.model_dump_json(),
                )
                return ProjectLeaseAcquisition(acquired=False, lease=current)
            reclaimed = bool(
                current
                and current.status == ProjectLeaseStatus.ACTIVE
                and current.expires_at <= moment
            )
            if (
                current
                and current.holder_id == holder_id
                and current.status == ProjectLeaseStatus.ACTIVE
                and current.expires_at > moment
            ):
                current.renewed_at, current.expires_at = (
                    moment,
                    moment + timedelta(seconds=ttl_seconds),
                )
                current.workflow_id = workflow_id or current.workflow_id
                current.events.append(
                    ProjectLeaseEvent(
                        kind=ProjectLeaseEventKind.RENEWED,
                        holder_id=holder_id,
                        workflow_id=workflow_id,
                        detail="Lease renewed by its current holder.",
                        occurred_at=moment,
                    )
                )
                lease = current
            else:
                kind = (
                    ProjectLeaseEventKind.RECLAIMED if reclaimed else ProjectLeaseEventKind.ACQUIRED
                )
                lease = ProjectLease(
                    project_root=str(Path(project_root).resolve()),
                    project_id=project_id,
                    holder_id=holder_id,
                    workflow_id=workflow_id,
                    fencing_token=(current.fencing_token + 1 if current else 1),
                    acquired_at=moment,
                    renewed_at=moment,
                    expires_at=moment + timedelta(seconds=ttl_seconds),
                    events=(current.events if current else [])
                    + [
                        ProjectLeaseEvent(
                            kind=kind,
                            holder_id=holder_id,
                            workflow_id=workflow_id,
                            detail="Expired lease reclaimed by a new holder."
                            if reclaimed
                            else "Exclusive project mutation lease acquired.",
                            occurred_at=moment,
                        )
                    ],
                )
            tx.run(
                "MATCH (lease:ProjectLease {project_root:$root}) SET lease.holder_id=$holder, lease.workflow_id=$workflow, lease.fencing_token=$fence, lease.status=$status, lease.expires_at=$expires, lease.payload=$payload",
                root=root,
                holder=lease.holder_id,
                workflow=lease.workflow_id,
                fence=lease.fencing_token,
                status=lease.status.value,
                expires=lease.expires_at.isoformat(),
                payload=lease.model_dump_json(),
            )
            return ProjectLeaseAcquisition(acquired=True, reclaimed=reclaimed, lease=lease)

        with self.driver.session() as session:
            return session.execute_write(operation)

    def renew_project_lease(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        *,
        ttl_seconds: float = 120,
        now: datetime | None = None,
    ) -> ProjectLease:
        moment = now or datetime.now(UTC)
        return self._mutate_lease(
            project_root,
            holder_id,
            fencing_token,
            ProjectLeaseEventKind.RENEWED,
            "Exclusive mutation lease renewed.",
            moment,
            ttl_seconds=ttl_seconds,
        )

    def release_project_lease(
        self, project_root: str, holder_id: str, fencing_token: int, *, now: datetime | None = None
    ) -> ProjectLease:
        return self.record_project_lease_event(
            project_root,
            holder_id,
            fencing_token,
            ProjectLeaseEventKind.RELEASED,
            "Exclusive project mutation lease released.",
            now=now,
        )

    def record_project_lease_event(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        kind: ProjectLeaseEventKind,
        detail: str,
        *,
        workflow_id: str | None = None,
        now: datetime | None = None,
    ) -> ProjectLease:
        return self._mutate_lease(
            project_root,
            holder_id,
            fencing_token,
            kind,
            detail,
            now or datetime.now(UTC),
            workflow_id=workflow_id,
        )

    def _mutate_lease(
        self,
        project_root: str,
        holder_id: str,
        fencing_token: int,
        kind: ProjectLeaseEventKind,
        detail: str,
        moment: datetime,
        *,
        workflow_id: str | None = None,
        ttl_seconds: float | None = None,
    ) -> ProjectLease:
        root = self._lease_root(project_root)

        def operation(tx):
            record = tx.run(
                "MATCH (lease:ProjectLease {project_root:$root}) SET lease.write_lock=coalesce(lease.write_lock,0)+1 RETURN lease.payload AS payload",
                root=root,
            ).single()
            if not record:
                raise RuntimeError("Project lease no longer exists.")
            lease = ProjectLease.model_validate_json(record["payload"])
            if (
                lease.status != ProjectLeaseStatus.ACTIVE
                or lease.holder_id != holder_id
                or lease.fencing_token != fencing_token
                or (kind == ProjectLeaseEventKind.RENEWED and lease.expires_at <= moment)
            ):
                raise RuntimeError("Project lease is stale or owned by another process.")
            lease.events.append(
                ProjectLeaseEvent(
                    kind=kind,
                    holder_id=holder_id,
                    workflow_id=workflow_id or lease.workflow_id,
                    detail=detail,
                    occurred_at=moment,
                )
            )
            if kind == ProjectLeaseEventKind.RENEWED:
                lease.renewed_at, lease.expires_at = (
                    moment,
                    moment + timedelta(seconds=ttl_seconds or 120),
                )
            elif kind == ProjectLeaseEventKind.RELEASED:
                lease.status, lease.released_at = ProjectLeaseStatus.RELEASED, moment
            tx.run(
                "MATCH (lease:ProjectLease {project_root:$root}) SET lease.status=$status, lease.expires_at=$expires, lease.payload=$payload",
                root=root,
                status=lease.status.value,
                expires=lease.expires_at.isoformat(),
                payload=lease.model_dump_json(),
            )
            return lease

        with self.driver.session() as session:
            return session.execute_write(operation)

    def project_leases(self) -> list[ProjectLease]:
        records, _, _ = self.driver.execute_query(
            "MATCH (lease:ProjectLease) RETURN lease.payload AS payload ORDER BY lease.project_root"
        )
        return [
            ProjectLease.model_validate_json(record["payload"])
            for record in records
            if record["payload"]
        ]

    def save_evaluation_run(self, run: EvaluationRun) -> None:
        self.driver.execute_query(
            "MERGE (evaluation:EvaluationRun {id:$id}) "
            "SET evaluation.suite_version=$suite_version, evaluation.passed=$passed, "
            "evaluation.created_at=$created_at, evaluation.payload=$payload",
            id=run.id,
            suite_version=run.suite_version,
            passed=run.passed,
            created_at=run.created_at.isoformat(),
            payload=run.model_dump_json(),
        )
        for result in run.results:
            self.driver.execute_query(
                "MATCH (evaluation:EvaluationRun {id:$run_id}) "
                "MERGE (result:EvaluationCaseResult {id:$id}) "
                "SET result.case_id=$case_id, result.strategy=$strategy, "
                "result.scenario=$scenario, result.repetition=$repetition, "
                "result.correct=$correct, result.payload=$payload "
                "MERGE (evaluation)-[:HAS_EVALUATION_RESULT]->(result)",
                run_id=run.id,
                id=result.id,
                case_id=result.case_id,
                strategy=result.strategy.value,
                scenario=result.scenario.value,
                repetition=result.repetition,
                correct=result.correct,
                payload=result.model_dump_json(),
            )

    def evaluation_runs(self) -> list[EvaluationRun]:
        records, _, _ = self.driver.execute_query(
            "MATCH (evaluation:EvaluationRun) RETURN evaluation.payload AS payload "
            "ORDER BY evaluation.created_at"
        )
        return [EvaluationRun.model_validate_json(record["payload"]) for record in records]

    def save_codex_readonly_proof(self, proof: CodexReadOnlyProof) -> None:
        self.driver.execute_query(
            "MERGE (proof:CodexReadOnlyProof {id:$id}) "
            "SET proof.project_root=$project_root, proof.test_path=$test_path, "
            "proof.passed=$passed, proof.created_at=$created_at, proof.payload=$payload",
            id=proof.id,
            project_root=proof.project_root,
            test_path=proof.test_path,
            passed=proof.passed,
            created_at=proof.created_at.isoformat(),
            payload=proof.model_dump_json(),
        )
        for relation, target in (
            ("INITIAL_EXECUTION", proof.initial_execution_id),
            ("REPLAY_EXECUTION", proof.replay_execution_id),
            ("ANSWERED_BY", proof.initial_claim_id),
        ):
            self.driver.execute_query(
                "MATCH (proof:CodexReadOnlyProof {id:$id}), (target {id:$target}) "
                f"MERGE (proof)-[:{relation}]->(target)",
                id=proof.id,
                target=target,
            )

    def codex_readonly_proofs(self) -> list[CodexReadOnlyProof]:
        records, _, _ = self.driver.execute_query(
            "MATCH (proof:CodexReadOnlyProof) RETURN proof.payload AS payload "
            "ORDER BY proof.created_at"
        )
        return [CodexReadOnlyProof.model_validate_json(record["payload"]) for record in records]

    def save_recursive_codex_proof(self, proof: RecursiveCodexDelegationProof) -> None:
        self.driver.execute_query(
            "MERGE (proof:RecursiveCodexDelegationProof {id:$id}) "
            "SET proof.project_root=$project_root, proof.test_path=$test_path, "
            "proof.passed=$passed, proof.created_at=$created_at, proof.payload=$payload",
            id=proof.id,
            project_root=proof.project_root,
            test_path=proof.test_path,
            passed=proof.passed,
            created_at=proof.created_at.isoformat(),
            payload=proof.model_dump_json(),
        )
        links = [
            ("HAS_ROOT", proof.root_task_id),
            ("HAS_SYNTHESIS", proof.synthesis_task_id),
            ("HAS_FINAL_CLAIM", proof.final_claim_id),
            ("HAS_REPLAY_ROOT", proof.replay_root_task_id),
        ]
        links.extend(("HAS_BRANCH", item.task_id) for item in proof.branch_results)
        links.extend(("HAS_REPLAY_BRANCH", item) for item in proof.replay_branch_task_ids)
        if proof.follow_up_task_id:
            links.append(("HAS_FOLLOW_UP", proof.follow_up_task_id))
        for relation, target in links:
            self.driver.execute_query(
                "MATCH (proof:RecursiveCodexDelegationProof {id:$id}), "
                "(target {id:$target}) "
                f"MERGE (proof)-[:{relation}]->(target)",
                id=proof.id,
                target=target,
            )

    def recursive_codex_proofs(self) -> list[RecursiveCodexDelegationProof]:
        records, _, _ = self.driver.execute_query(
            "MATCH (proof:RecursiveCodexDelegationProof) "
            "RETURN proof.payload AS payload ORDER BY proof.created_at"
        )
        return [
            RecursiveCodexDelegationProof.model_validate_json(record["payload"])
            for record in records
        ]

    def save_generic_codex_evaluation(self, evaluation: GenericCodexEvaluation) -> None:
        self.driver.execute_query(
            "MERGE (evaluation:GenericCodexEvaluation {id:$id}) "
            "SET evaluation.suite_version=$suite_version, evaluation.passed=$passed, "
            "evaluation.created_at=$created_at, evaluation.payload=$payload",
            id=evaluation.id,
            suite_version=evaluation.suite_version,
            passed=evaluation.passed,
            created_at=evaluation.created_at.isoformat(),
            payload=evaluation.model_dump_json(),
        )
        for case in evaluation.cases:
            self.driver.execute_query(
                "MATCH (evaluation:GenericCodexEvaluation {id:$id}), "
                "(proof:RecursiveCodexDelegationProof {id:$proof_id}) "
                "MERGE (evaluation)-[:HAS_GENERIC_CASE]->(proof)",
                id=evaluation.id,
                proof_id=case.proof_id,
            )

    def generic_codex_evaluations(self) -> list[GenericCodexEvaluation]:
        records, _, _ = self.driver.execute_query(
            "MATCH (evaluation:GenericCodexEvaluation) "
            "RETURN evaluation.payload AS payload ORDER BY evaluation.created_at"
        )
        return [
            GenericCodexEvaluation.model_validate_json(record["payload"])
            for record in records
        ]

    def save_investigation_session(self, session: InvestigationSession) -> None:
        self.driver.execute_query(
            "MERGE (session:InvestigationSession {id:$id}) "
            "SET session.status=$status, session.active_stage=$stage, "
            "session.updated_at=$updated_at, session.payload=$payload",
            id=session.id,
            status=session.status,
            stage=session.active_stage,
            updated_at=session.updated_at.isoformat(),
            payload=session.model_dump_json(),
        )

    def investigation_sessions(self) -> list[InvestigationSession]:
        records, _, _ = self.driver.execute_query(
            "MATCH (session:InvestigationSession) "
            "RETURN session.payload AS payload ORDER BY session.updated_at"
        )
        return [InvestigationSession.model_validate_json(record["payload"]) for record in records]

    def save_resumable_session_evaluation(
        self, evaluation: ResumableSessionEvaluation
    ) -> None:
        self.driver.execute_query(
            "MERGE (evaluation:ResumableSessionEvaluation {id:$id}) "
            "SET evaluation.passed=$passed, evaluation.created_at=$created_at, "
            "evaluation.payload=$payload",
            id=evaluation.id,
            passed=evaluation.passed,
            created_at=evaluation.created_at.isoformat(),
            payload=evaluation.model_dump_json(),
        )

    def resumable_session_evaluations(self) -> list[ResumableSessionEvaluation]:
        records, _, _ = self.driver.execute_query(
            "MATCH (evaluation:ResumableSessionEvaluation) "
            "RETURN evaluation.payload AS payload ORDER BY evaluation.created_at"
        )
        return [
            ResumableSessionEvaluation.model_validate_json(record["payload"])
            for record in records
        ]

    def save_unreal_index(self, scan, artifacts, dependencies) -> None:
        self.driver.execute_query(
            "MERGE (scan:UnrealIndexScan {id:$id}) SET scan.project_id=$project_id, scan.created_at=$created_at, scan.payload=$payload",
            id=scan.id, project_id=scan.project_id, created_at=scan.created_at.isoformat(), payload=scan.model_dump_json(),
        )
        self.driver.execute_query("MATCH (n) WHERE (n:UnrealArtifact OR n:UnrealDependency) AND n.project_id=$project_id DETACH DELETE n", project_id=scan.project_id)
        for item in artifacts:
            self.driver.execute_query(
                "CREATE (n:UnrealArtifact {id:$id, project_id:$project_id, kind:$kind, path:$path, payload:$payload})",
                id=item.id, project_id=item.project_id, kind=item.kind, path=item.path, payload=item.model_dump_json(),
            )
        for item in dependencies:
            self.driver.execute_query(
                "CREATE (n:UnrealDependency {id:$id, project_id:$project_id, relation:$relation, payload:$payload})",
                id=item.id, project_id=item.project_id, relation=item.relation, payload=item.model_dump_json(),
            )
            self.driver.execute_query(
                "MATCH (a:UnrealArtifact {id:$source}), (d:UnrealDependency {id:$id}) MERGE (a)-[:HAS_UNREAL_DEPENDENCY]->(d)",
                source=item.source_artifact_id, id=item.id,
            )
            if item.target_artifact_id:
                self.driver.execute_query(
                    "MATCH (d:UnrealDependency {id:$id}), (a:UnrealArtifact {id:$target}) MERGE (d)-[:DEPENDS_ON_UNREAL_ARTIFACT]->(a)",
                    id=item.id, target=item.target_artifact_id,
                )

    def _unreal_payloads(self, label, model, project_id=None):
        records, _, _ = self.driver.execute_query(
            f"MATCH (n:{label}) WHERE $project_id IS NULL OR n.project_id=$project_id RETURN n.payload AS payload ORDER BY n.path, n.id",
            project_id=project_id,
        )
        return [model.model_validate_json(record["payload"]) for record in records]

    def unreal_index_scans(self):
        return self._unreal_payloads("UnrealIndexScan", UnrealIndexScan)

    def unreal_artifacts(self, project_id=None):
        return self._unreal_payloads("UnrealArtifact", UnrealArtifact, project_id)

    def unreal_dependencies(self, project_id=None):
        return self._unreal_payloads("UnrealDependency", UnrealDependency, project_id)













    def save_project_workspace_record(self, record):
        self.driver.execute_query(
            "MATCH (project:Project {id:$project_id}) "
            "MERGE (result:ProjectWorkspaceRecord {id:$id}) "
            "SET result.project_id=$project_id, result.kind=$kind, result.status=$status, "
            "result.created_at=$created_at, result.payload=$payload "
            "MERGE (project)-[:HAS_WORKSPACE_RESULT]->(result)",
            project_id=record.project_id,
            id=record.id,
            kind=record.kind,
            status=record.status,
            created_at=record.created_at.isoformat(),
            payload=record.model_dump_json(),
        )
        if record.ticket_id:
            self.driver.execute_query(
                "MATCH (ticket:ProjectTicket {id:$ticket_id}), "
                "(result:ProjectWorkspaceRecord {id:$id}) "
                "MERGE (ticket)-[:HAS_WORKSPACE_RESULT]->(result)",
                ticket_id=record.ticket_id,
                id=record.id,
            )

    def project_workspace_records(self):
        return self._unreal_payloads("ProjectWorkspaceRecord", ProjectWorkspaceRecord)

    def save_project_ticket(self, ticket):
        self.driver.execute_query(
            "MATCH (project:Project {id:$project_id}) "
            "MERGE (ticket:ProjectTicket {id:$id}) "
            "SET ticket.project_id=$project_id, ticket.status=$status, "
            "ticket.priority=$priority, ticket.updated_at=$updated_at, ticket.payload=$payload "
            "MERGE (project)-[:HAS_TICKET]->(ticket)",
            project_id=ticket.project_id,
            id=ticket.id,
            status=ticket.status,
            priority=ticket.priority,
            updated_at=ticket.updated_at.isoformat(),
            payload=ticket.model_dump_json(),
        )
        self.driver.execute_query(
            "MATCH (ticket:ProjectTicket {id:$id})-[edge:DEPENDS_ON_TICKET]->() DELETE edge",
            id=ticket.id,
        )
        for dependency_id in ticket.dependency_ticket_ids:
            self.driver.execute_query(
                "MATCH (ticket:ProjectTicket {id:$id}), "
                "(dependency:ProjectTicket {id:$dependency_id}) "
                "MERGE (ticket)-[:DEPENDS_ON_TICKET]->(dependency)",
                id=ticket.id,
                dependency_id=dependency_id,
            )

    def project_tickets(self):
        return self._unreal_payloads("ProjectTicket", ProjectTicket)

    def save_ticket_event(self, event):
        self.driver.execute_query(
            "MATCH (ticket:ProjectTicket {id:$ticket_id}) "
            "MERGE (event:TicketEvent {id:$id}) "
            "SET event.project_id=ticket.project_id, event.ticket_id=$ticket_id, "
            "event.kind=$kind, event.created_at=$created_at, event.payload=$payload "
            "MERGE (ticket)-[:HAS_TICKET_EVENT]->(event)",
            ticket_id=event.ticket_id,
            id=event.id,
            kind=event.kind,
            created_at=event.created_at.isoformat(),
            payload=event.model_dump_json(),
        )

    def ticket_events(self, ticket_id=None):
        records, _, _ = self.driver.execute_query(
            "MATCH (event:TicketEvent) "
            "WHERE $ticket_id IS NULL OR event.ticket_id=$ticket_id "
            "RETURN event.payload AS payload ORDER BY event.created_at",
            ticket_id=ticket_id,
        )
        return [TicketEvent.model_validate_json(record["payload"]) for record in records]

    def save_ticket_validation_result(self, result):
        self.driver.execute_query(
            "MATCH (ticket:ProjectTicket {id:$ticket_id}) "
            "MERGE (result:TicketValidationResult {id:$id}) "
            "SET result.project_id=ticket.project_id, result.ticket_id=$ticket_id, "
            "result.status=$status, result.created_at=$created_at, result.payload=$payload "
            "MERGE (ticket)-[:HAS_VALIDATION_RESULT]->(result)",
            ticket_id=result.ticket_id,
            id=result.id,
            status=result.status,
            created_at=result.created_at.isoformat(),
            payload=result.model_dump_json(),
        )
        if result.workspace_record_id:
            self.driver.execute_query(
                "MATCH (result:TicketValidationResult {id:$id}), "
                "(workspace:ProjectWorkspaceRecord {id:$workspace_id}) "
                "MERGE (result)-[:VALIDATES_WORKSPACE_RESULT]->(workspace)",
                id=result.id,
                workspace_id=result.workspace_record_id,
            )

    def ticket_validation_results(self, ticket_id=None):
        records, _, _ = self.driver.execute_query(
            "MATCH (result:TicketValidationResult) "
            "WHERE $ticket_id IS NULL OR result.ticket_id=$ticket_id "
            "RETURN result.payload AS payload ORDER BY result.created_at",
            ticket_id=ticket_id,
        )
        return [
            TicketValidationResult.model_validate_json(record["payload"])
            for record in records
        ]

    def save_implementation_sandbox(self, attempt):
        self.driver.execute_query(
            "MATCH (ticket:ProjectTicket {id:$ticket_id}) "
            "MERGE (attempt:ImplementationSandboxAttempt {id:$id}) "
            "SET attempt.project_id=ticket.project_id, attempt.ticket_id=$ticket_id, "
            "attempt.status=$status, attempt.created_at=$created_at, attempt.payload=$payload "
            "MERGE (ticket)-[:HAS_IMPLEMENTATION_SANDBOX]->(attempt)",
            ticket_id=attempt.ticket_id,
            id=attempt.id,
            status=attempt.status,
            created_at=attempt.created_at.isoformat(),
            payload=attempt.model_dump_json(),
        )
        self.driver.execute_query(
            "MATCH (attempt:ImplementationSandboxAttempt {id:$id}), "
            "(plan:ProjectWorkspaceRecord {id:$plan_id}) "
            "MERGE (attempt)-[:IMPLEMENTS_APPROVED_PLAN]->(plan)",
            id=attempt.id,
            plan_id=attempt.plan_record_id,
        )
        if attempt.promotion:
            self.driver.execute_query(
                "MATCH (attempt:ImplementationSandboxAttempt {id:$attempt_id}) "
                "MERGE (promotion:SandboxPromotion {id:$id}) "
                "SET promotion.status=$status, promotion.payload=$payload "
                "MERGE (attempt)-[:HAS_SANDBOX_PROMOTION]->(promotion)",
                attempt_id=attempt.id,
                id=attempt.promotion.id,
                status=attempt.promotion.status,
                payload=attempt.promotion.model_dump_json(),
            )
            reconciliation = attempt.promotion.reconciliation
            if reconciliation:
                self.driver.execute_query(
                    "MATCH (promotion:SandboxPromotion {id:$promotion_id}), "
                    "(scan:ProjectScan {id:$scan_id}) "
                    "MERGE (reconciliation:SandboxPromotionReconciliation {id:$id}) "
                    "SET reconciliation.status=$status, reconciliation.payload=$payload "
                    "MERGE (promotion)-[:RECONCILED_BY]->(reconciliation) "
                    "MERGE (reconciliation)-[:RECONCILIATION_SCAN]->(scan)",
                    promotion_id=attempt.promotion.id,
                    scan_id=reconciliation.scan_id,
                    id=reconciliation.id,
                    status=reconciliation.status,
                    payload=reconciliation.model_dump_json(),
                )
                for claim_id in reconciliation.replacement_claim_ids:
                    self.driver.execute_query(
                        "MATCH (reconciliation:SandboxPromotionReconciliation {id:$id}), "
                        "(claim:Claim {id:$claim_id}) "
                        "MERGE (reconciliation)-[:RECORDED_REPAIRED_STATE]->(claim)",
                        id=reconciliation.id,
                        claim_id=claim_id,
                    )

    def implementation_sandboxes(self, ticket_id=None):
        records, _, _ = self.driver.execute_query(
            "MATCH (attempt:ImplementationSandboxAttempt) "
            "WHERE $ticket_id IS NULL OR attempt.ticket_id=$ticket_id "
            "RETURN attempt.payload AS payload ORDER BY attempt.created_at",
            ticket_id=ticket_id,
        )
        return [
            ImplementationSandboxAttempt.model_validate_json(record["payload"])
            for record in records
        ]

    def save_observer_activity(self, state):
        self.driver.execute_query(
            "MERGE (state:ObserverActivityState {id:$id}) "
            "SET state.activity_kind=$activity_kind, state.status=$status, "
            "state.ticket_id=$ticket_id, state.updated_at=$updated_at, state.payload=$payload",
            id=state.id,
            activity_kind=state.activity_kind,
            status=state.status,
            ticket_id=state.ticket_id,
            updated_at=state.updated_at.isoformat(),
            payload=state.model_dump_json(),
        )

    def observer_activities(self):
        return self._unreal_payloads("ObserverActivityState", ObserverActivityState)

    def save_scheduled_work(self, item):
        self.driver.execute_query(
            "MATCH (ticket:ProjectTicket {id:$ticket_id}) "
            "MERGE (item:ScheduledWorkItem {id:$id}) "
            "SET item.project_id=$project_id, item.ticket_id=$ticket_id, "
            "item.status=$status, item.updated_at=$updated_at, item.payload=$payload "
            "MERGE (ticket)-[:HAS_SCHEDULED_WORK]->(item)",
            id=item.id,
            ticket_id=item.ticket_id,
            project_id=item.project_id,
            status=item.status,
            updated_at=item.updated_at.isoformat(),
            payload=item.model_dump_json(),
        )

    def scheduled_work(self):
        return self._unreal_payloads("ScheduledWorkItem", ScheduledWorkItem)

    def save_project_governance_policy(self, policy):
        self.driver.execute_query(
            "MERGE (policy:ProjectGovernancePolicy {id:$id}) "
            "SET policy.project_id=$project_id, policy.project_root=$project_root, "
            "policy.version=$version, policy.payload=$payload",
            id=policy.id,
            project_id=policy.project_id,
            project_root=policy.project_root,
            version=policy.version,
            payload=policy.model_dump_json(),
        )

    def project_governance_policies(self):
        return self._unreal_payloads("ProjectGovernancePolicy", ProjectGovernancePolicy)

    def save_chat_session(self, session: ChatSession) -> None:
        self.driver.execute_query(
            "MERGE (session:ChatSession {id:$id}) "
            "SET session.updated_at=$updated_at, session.payload=$payload",
            id=session.id, updated_at=session.updated_at.isoformat(),
            payload=session.model_dump_json(),
        )

    def chat_sessions(self) -> list[ChatSession]:
        records, _, _ = self.driver.execute_query(
            "MATCH (session:ChatSession) RETURN session.payload AS payload "
            "ORDER BY session.updated_at DESC"
        )
        return [ChatSession.model_validate_json(record["payload"]) for record in records]

    def save_chat_turn(self, turn: ChatTurn) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (turn:ChatTurn {id:$id}) "
            "SET turn.session_id=$session_id, turn.ordinal=$ordinal, "
            "turn.claim_id=$claim_id, turn.payload=$payload "
            "MERGE (session)-[:HAS_CHAT_TURN]->(turn)",
            id=turn.id, session_id=turn.session_id, ordinal=turn.ordinal,
            claim_id=turn.claim_id, payload=turn.model_dump_json(),
        )

    def chat_turns(self, session_id: str) -> list[ChatTurn]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_CHAT_TURN]->(turn:ChatTurn) "
            "RETURN turn.payload AS payload ORDER BY turn.ordinal",
            session_id=session_id,
        )
        return [ChatTurn.model_validate_json(record["payload"]) for record in records]

    def save_conversation_interpretation(
        self, interpretation: ConversationInterpretationRecord
    ) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (item:ConversationInterpretation {id:$id}) "
            "SET item.session_id=$session_id, item.turn_id=$turn_id, "
            "item.created_at=$created_at, item.payload=$payload "
            "MERGE (session)-[:HAS_INTERPRETATION]->(item)",
            id=interpretation.id, session_id=interpretation.session_id,
            turn_id=interpretation.turn_id,
            created_at=interpretation.created_at.isoformat(),
            payload=interpretation.model_dump_json(),
        )
        if interpretation.turn_id:
            self.driver.execute_query(
                "MATCH (item:ConversationInterpretation {id:$id}), "
                "(turn:ChatTurn {id:$turn_id}) "
                "MERGE (turn)-[:INTERPRETED_AS]->(item)",
                id=interpretation.id, turn_id=interpretation.turn_id,
            )

    def conversation_interpretations(
        self, session_id: str
    ) -> list[ConversationInterpretationRecord]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_INTERPRETATION]->"
            "(item:ConversationInterpretation) RETURN item.payload AS payload "
            "ORDER BY item.created_at, item.id",
            session_id=session_id,
        )
        return [
            ConversationInterpretationRecord.model_validate_json(record["payload"])
            for record in records
        ]

    def save_conversation_fact(self, fact: ConversationFact) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (fact:ConversationFact {id:$id}) "
            "SET fact.session_id=$session_id, fact.created_at=$created_at, fact.payload=$payload "
            "MERGE (session)-[:HAS_CONVERSATION_FACT]->(fact)",
            id=fact.id, session_id=fact.session_id,
            created_at=fact.created_at.isoformat(), payload=fact.model_dump_json(),
        )
        self.driver.execute_query(
            "MATCH (fact:ConversationFact {id:$id}), (turn:ChatTurn {id:$turn_id}), "
            "(interpretation:ConversationInterpretation {id:$interpretation_id}) "
            "MERGE (fact)-[:SUPPORTED_BY_TURN]->(turn) "
            "MERGE (fact)-[:DERIVED_FROM_INTERPRETATION]->(interpretation)",
            id=fact.id, turn_id=fact.source_turn_id,
            interpretation_id=fact.source_interpretation_id,
        )

    def conversation_facts(self, session_id: str) -> list[ConversationFact]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_CONVERSATION_FACT]->"
            "(fact:ConversationFact) RETURN fact.payload AS payload "
            "ORDER BY fact.created_at, fact.id",
            session_id=session_id,
        )
        return [ConversationFact.model_validate_json(record["payload"]) for record in records]

    def save_memory_association(self, association: MemoryAssociation) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (association:MemoryAssociation {id:$id}) "
            "SET association.session_id=$session_id, association.created_at=$created_at, "
            "association.payload=$payload "
            "MERGE (session)-[:HAS_MEMORY_ASSOCIATION]->(association)",
            id=association.id, session_id=association.session_id,
            created_at=association.created_at.isoformat(),
            payload=association.model_dump_json(),
        )
        for memory_id in association.source_memory_ids:
            self.driver.execute_query(
                "MATCH (association:MemoryAssociation {id:$id}), "
                "(fact:ConversationFact {id:$memory_id}) "
                "MERGE (association)-[:CONNECTS_MEMORY]->(fact)",
                id=association.id, memory_id=memory_id,
            )

    def memory_associations(self, session_id: str) -> list[MemoryAssociation]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_MEMORY_ASSOCIATION]->"
            "(association:MemoryAssociation) RETURN association.payload AS payload "
            "ORDER BY association.created_at, association.id", session_id=session_id,
        )
        return [MemoryAssociation.model_validate_json(record["payload"]) for record in records]

    def save_memory_relationship_interpretation(
        self, interpretation: MemoryRelationshipInterpretation
    ) -> None:
        self.driver.execute_query(
            "MATCH (association:MemoryAssociation {id:$association_id}) "
            "MERGE (interpretation:MemoryRelationshipInterpretation {id:$id}) "
            "SET interpretation.session_id=$session_id, interpretation.created_at=$created_at, "
            "interpretation.payload=$payload "
            "MERGE (interpretation)-[:INTERPRETS_ASSOCIATION]->(association)",
            id=interpretation.id, association_id=interpretation.association_id,
            session_id=interpretation.session_id,
            created_at=interpretation.created_at.isoformat(),
            payload=interpretation.model_dump_json(),
        )

    def memory_relationship_interpretations(
        self, session_id: str
    ) -> list[MemoryRelationshipInterpretation]:
        records, _, _ = self.driver.execute_query(
            "MATCH (interpretation:MemoryRelationshipInterpretation {session_id:$session_id}) "
            "RETURN interpretation.payload AS payload "
            "ORDER BY interpretation.created_at, interpretation.id", session_id=session_id,
        )
        return [
            MemoryRelationshipInterpretation.model_validate_json(record["payload"])
            for record in records
        ]

    def save_memory_cluster(self, cluster: MemoryCluster) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (cluster:MemoryCluster {signature:$signature}) "
            "ON CREATE SET cluster.id=$id, cluster.session_id=$session_id, "
            "cluster.abstraction_level=$level, cluster.created_at=$created_at, "
            "cluster.payload=$payload "
            "MERGE (session)-[:HAS_MEMORY_CLUSTER]->(cluster)",
            id=cluster.id, session_id=cluster.session_id, signature=cluster.signature,
            level=cluster.abstraction_level, created_at=cluster.created_at.isoformat(),
            payload=cluster.model_dump_json(),
        )
        for member_id in cluster.member_memory_ids:
            self.driver.execute_query(
                "MATCH (cluster:MemoryCluster {signature:$signature}) "
                "OPTIONAL MATCH (fact:ConversationFact {id:$member_id}) "
                "OPTIONAL MATCH (child:MemoryCluster {id:$member_id}) "
                "FOREACH (_ IN CASE WHEN fact IS NULL THEN [] ELSE [1] END | "
                "MERGE (cluster)-[:HAS_CLUSTER_MEMBER]->(fact)) "
                "FOREACH (_ IN CASE WHEN child IS NULL THEN [] ELSE [1] END | "
                "MERGE (cluster)-[:HAS_CLUSTER_MEMBER]->(child))",
                signature=cluster.signature, member_id=member_id,
            )

    def memory_clusters(self, session_id: str) -> list[MemoryCluster]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_MEMORY_CLUSTER]->"
            "(cluster:MemoryCluster) RETURN cluster.payload AS payload "
            "ORDER BY cluster.abstraction_level, cluster.created_at, cluster.id",
            session_id=session_id,
        )
        return [MemoryCluster.model_validate_json(record["payload"]) for record in records]

    def save_concept_branch(self, branch: ConceptBranch) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (branch:ConceptBranch {signature:$signature}) "
            "ON CREATE SET branch.id=$id, branch.session_id=$session_id, branch.depth=$depth, "
            "branch.created_at=$created_at, branch.payload=$payload "
            "MERGE (session)-[:HAS_CONCEPT_BRANCH]->(branch)",
            id=branch.id, session_id=branch.session_id, signature=branch.signature,
            depth=branch.depth, created_at=branch.created_at.isoformat(),
            payload=branch.model_dump_json(),
        )
        if branch.parent_branch_id:
            self.driver.execute_query(
                "MATCH (parent:ConceptBranch {id:$parent_id}), "
                "(child:ConceptBranch {signature:$signature}) "
                "MERGE (parent)-[:BRANCHES_TO]->(child)",
                parent_id=branch.parent_branch_id, signature=branch.signature,
            )

    def concept_branches(self, session_id: str) -> list[ConceptBranch]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_CONCEPT_BRANCH]->"
            "(branch:ConceptBranch) RETURN branch.payload AS payload "
            "ORDER BY branch.depth, branch.created_at, branch.id", session_id=session_id,
        )
        return [ConceptBranch.model_validate_json(record["payload"]) for record in records]

    def save_autonomous_decision(self, decision: AutonomousDecision) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (decision:AutonomousDecision {id:$id}) "
            "SET decision.session_id=$session_id, decision.updated_at=$updated_at, "
            "decision.payload=$payload MERGE (session)-[:MADE_AUTONOMOUS_DECISION]->(decision)",
            id=decision.id, session_id=decision.session_id,
            updated_at=decision.updated_at.isoformat(), payload=decision.model_dump_json(),
        )

    def autonomous_decisions(self, session_id: str) -> list[AutonomousDecision]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:MADE_AUTONOMOUS_DECISION]->"
            "(decision:AutonomousDecision) RETURN decision.payload AS payload "
            "ORDER BY decision.updated_at, decision.id", session_id=session_id,
        )
        return [AutonomousDecision.model_validate_json(record["payload"]) for record in records]

    def save_autonomous_inquiry(self, inquiry: AutonomousInquiry) -> None:
        self.driver.execute_query(
            "MATCH (decision:AutonomousDecision {id:$decision_id}), "
            "(branch:ConceptBranch {id:$branch_id}) "
            "MERGE (inquiry:AutonomousInquiry {id:$id}) "
            "SET inquiry.session_id=$session_id, inquiry.updated_at=$updated_at, "
            "inquiry.payload=$payload "
            "MERGE (decision)-[:SELECTED_INQUIRY]->(inquiry) "
            "MERGE (inquiry)-[:INVESTIGATES_BRANCH]->(branch)",
            id=inquiry.id, decision_id=inquiry.decision_id, branch_id=inquiry.branch_id,
            session_id=inquiry.session_id, updated_at=inquiry.updated_at.isoformat(),
            payload=inquiry.model_dump_json(),
        )

    def autonomous_inquiries(self, session_id: str) -> list[AutonomousInquiry]:
        records, _, _ = self.driver.execute_query(
            "MATCH (inquiry:AutonomousInquiry {session_id:$session_id}) "
            "RETURN inquiry.payload AS payload ORDER BY inquiry.updated_at, inquiry.id",
            session_id=session_id,
        )
        return [AutonomousInquiry.model_validate_json(record["payload"]) for record in records]

    def save_concept_branch_outcome(self, outcome: ConceptBranchOutcome) -> None:
        self.driver.execute_query(
            "MATCH (branch:ConceptBranch {id:$branch_id}), "
            "(inquiry:AutonomousInquiry {id:$inquiry_id}) "
            "MERGE (outcome:ConceptBranchOutcome {id:$id}) "
            "SET outcome.session_id=$session_id, outcome.created_at=$created_at, "
            "outcome.payload=$payload "
            "MERGE (branch)-[:HAS_AUTONOMOUS_OUTCOME]->(outcome) "
            "MERGE (outcome)-[:RESULT_OF_INQUIRY]->(inquiry)",
            id=outcome.id, branch_id=outcome.branch_id, inquiry_id=outcome.inquiry_id,
            session_id=outcome.session_id, created_at=outcome.created_at.isoformat(),
            payload=outcome.model_dump_json(),
        )

    def concept_branch_outcomes(self, session_id: str) -> list[ConceptBranchOutcome]:
        records, _, _ = self.driver.execute_query(
            "MATCH (outcome:ConceptBranchOutcome {session_id:$session_id}) "
            "RETURN outcome.payload AS payload ORDER BY outcome.created_at, outcome.id",
            session_id=session_id,
        )
        return [ConceptBranchOutcome.model_validate_json(record["payload"]) for record in records]

    def save_autonomous_work_policy(self, policy: AutonomousWorkPolicy) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (policy:AutonomousWorkPolicy {session_id:$session_id}) "
            "SET policy.updated_at=$updated_at, policy.payload=$payload "
            "MERGE (session)-[:HAS_AUTONOMOUS_WORK_POLICY]->(policy)",
            session_id=policy.session_id, updated_at=policy.updated_at.isoformat(),
            payload=policy.model_dump_json(),
        )

    def autonomous_work_policies(self) -> list[AutonomousWorkPolicy]:
        records, _, _ = self.driver.execute_query(
            "MATCH (policy:AutonomousWorkPolicy) RETURN policy.payload AS payload "
            "ORDER BY policy.updated_at, policy.session_id"
        )
        return [AutonomousWorkPolicy.model_validate_json(record["payload"]) for record in records]

    def save_autonomous_task(self, task: AutonomousTask) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (task:AutonomousTask {id:$id}) "
            "SET task.session_id=$session_id, task.updated_at=$updated_at, task.payload=$payload "
            "MERGE (session)-[:HAS_AUTONOMOUS_TASK]->(task)",
            id=task.id, session_id=task.session_id, updated_at=task.updated_at.isoformat(),
            payload=task.model_dump_json(),
        )

    def autonomous_tasks(self, session_id: str) -> list[AutonomousTask]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_AUTONOMOUS_TASK]->"
            "(task:AutonomousTask) RETURN task.payload AS payload "
            "ORDER BY task.updated_at, task.id", session_id=session_id,
        )
        return [AutonomousTask.model_validate_json(record["payload"]) for record in records]

    def save_autonomous_task_plan(self, plan: AutonomousTaskPlan) -> None:
        self.driver.execute_query(
            "MATCH (task:AutonomousTask {id:$task_id}) "
            "MERGE (plan:AutonomousTaskPlan {id:$id}) "
            "SET plan.session_id=$session_id, plan.created_at=$created_at, plan.payload=$payload "
            "MERGE (task)-[:HAS_PROPOSED_PLAN]->(plan)",
            id=plan.id, task_id=plan.autonomous_task_id, session_id=plan.session_id,
            created_at=plan.created_at.isoformat(), payload=plan.model_dump_json(),
        )

    def autonomous_task_plans(self, session_id: str) -> list[AutonomousTaskPlan]:
        records, _, _ = self.driver.execute_query(
            "MATCH (task:AutonomousTask {session_id:$session_id})-[:HAS_PROPOSED_PLAN]->"
            "(plan:AutonomousTaskPlan) RETURN plan.payload AS payload "
            "ORDER BY plan.created_at, plan.id", session_id=session_id,
        )
        return [AutonomousTaskPlan.model_validate_json(record["payload"]) for record in records]

    def save_deductive_theory(self, theory: DeductiveTheory) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (theory:DeductiveTheory {id:$id}) "
            "SET theory.session_id=$session_id, theory.subject=$subject, "
            "theory.created_at=$created_at, theory.payload=$payload "
            "MERGE (session)-[:HAS_DEDUCTIVE_THEORY]->(theory)",
            id=theory.id, session_id=theory.session_id, subject=theory.subject,
            created_at=theory.created_at.isoformat(), payload=theory.model_dump_json(),
        )
        for claim_id in theory.source_claim_ids:
            self.driver.execute_query(
                "MATCH (theory:DeductiveTheory {id:$id}), (claim:Claim {id:$claim_id}) "
                "MERGE (theory)-[:DEDUCED_FROM_CLAIM]->(claim)",
                id=theory.id, claim_id=claim_id,
            )

    def deductive_theories(self, session_id: str) -> list[DeductiveTheory]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:HAS_DEDUCTIVE_THEORY]->"
            "(theory:DeductiveTheory) RETURN theory.payload AS payload "
            "ORDER BY theory.created_at, theory.id", session_id=session_id,
        )
        return [DeductiveTheory.model_validate_json(record["payload"]) for record in records]

    def save_self_assessment_report(self, report: SelfAssessmentReport) -> None:
        self.driver.execute_query(
            "MATCH (result:ConversationWorkResult {id:$result_id}) "
            "MERGE (report:SelfAssessmentReport {id:$id}) "
            "SET report.session_id=$session_id, report.created_at=$created_at, "
            "report.payload=$payload MERGE (report)-[:ASSESSMENT_OF_RESULT]->(result)",
            id=report.id, result_id=report.work_result_id, session_id=report.session_id,
            created_at=report.created_at.isoformat(), payload=report.model_dump_json(),
        )

    def self_assessment_reports(self, session_id: str) -> list[SelfAssessmentReport]:
        records, _, _ = self.driver.execute_query(
            "MATCH (report:SelfAssessmentReport {session_id:$session_id}) "
            "RETURN report.payload AS payload ORDER BY report.created_at, report.id",
            session_id=session_id,
        )
        return [SelfAssessmentReport.model_validate_json(record["payload"]) for record in records]

    def save_conversation_work_request(self, request: ConversationWorkRequest) -> None:
        self.driver.execute_query(
            "MATCH (session:ChatSession {id:$session_id}) "
            "MERGE (request:ConversationWorkRequest {id:$id}) "
            "SET request.session_id=$session_id, request.created_at=$created_at, "
            "request.payload=$payload MERGE (session)-[:SUBMITTED_WORK_REQUEST]->(request)",
            id=request.id, session_id=request.session_id,
            created_at=request.created_at.isoformat(), payload=request.model_dump_json(),
        )

    def conversation_work_requests(self, session_id: str) -> list[ConversationWorkRequest]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:SUBMITTED_WORK_REQUEST]->"
            "(request:ConversationWorkRequest) RETURN request.payload AS payload "
            "ORDER BY request.created_at, request.id", session_id=session_id,
        )
        return [ConversationWorkRequest.model_validate_json(record["payload"]) for record in records]

    def save_conversation_work_result(self, result: ConversationWorkResult) -> None:
        self.driver.execute_query(
            "MATCH (request:ConversationWorkRequest {id:$request_id}) "
            "MERGE (result:ConversationWorkResult {id:$id}) "
            "SET result.session_id=$session_id, result.created_at=$created_at, "
            "result.payload=$payload MERGE (request)-[:RETURNED_WORK_RESULT]->(result)",
            id=result.id, request_id=result.request_id, session_id=result.session_id,
            created_at=result.created_at.isoformat(), payload=result.model_dump_json(),
        )
        self.driver.execute_query(
            "MATCH (result:ConversationWorkResult {id:$id}), (task:Task {id:$task_id}) "
            "MERGE (result)-[:TRACED_TO_TASK]->(task)", id=result.id, task_id=result.task_id,
        )
        for claim_id in result.claim_ids:
            self.driver.execute_query(
                "MATCH (result:ConversationWorkResult {id:$id}), (claim:Claim {id:$claim_id}) "
                "MERGE (result)-[:RETURNED_CLAIM]->(claim)", id=result.id, claim_id=claim_id,
            )

    def conversation_work_results(self, session_id: str) -> list[ConversationWorkResult]:
        records, _, _ = self.driver.execute_query(
            "MATCH (:ChatSession {id:$session_id})-[:SUBMITTED_WORK_REQUEST]->"
            "(:ConversationWorkRequest)-[:RETURNED_WORK_RESULT]->"
            "(result:ConversationWorkResult) RETURN result.payload AS payload "
            "ORDER BY result.created_at, result.id", session_id=session_id,
        )
        return [ConversationWorkResult.model_validate_json(record["payload"]) for record in records]

    def save_self_improvement_proposal(self, proposal: SelfImprovementProposal) -> None:
        self.driver.execute_query(
            "MATCH (request:ConversationWorkRequest {id:$request_id}), "
            "(result:ConversationWorkResult {id:$result_id}) "
            "MERGE (proposal:SelfImprovementProposal {id:$id}) "
            "SET proposal.session_id=$session_id, proposal.updated_at=$updated_at, "
            "proposal.payload=$payload "
            "MERGE (proposal)-[:DERIVED_FROM_REQUEST]->(request) "
            "MERGE (proposal)-[:DERIVED_FROM_RESULT]->(result)",
            id=proposal.id, session_id=proposal.session_id,
            request_id=proposal.work_request_id, result_id=proposal.work_result_id,
            updated_at=proposal.updated_at.isoformat(), payload=proposal.model_dump_json(),
        )

    def self_improvement_proposals(self) -> list[SelfImprovementProposal]:
        records, _, _ = self.driver.execute_query(
            "MATCH (proposal:SelfImprovementProposal) RETURN proposal.payload AS payload "
            "ORDER BY proposal.updated_at, proposal.id"
        )
        return [SelfImprovementProposal.model_validate_json(record["payload"]) for record in records]

    def save_project_record(self, project: ProjectRecord) -> None:
        self.driver.execute_query(
            "MERGE (p:Project {id: $id}) "
            "SET p.root=$root, p.read_only=$read_only, "
            "p.explicitly_selected=$explicitly_selected, p.payload=$payload",
            id=project.id,
            root=project.root,
            read_only=project.read_only,
            explicitly_selected=project.explicitly_selected,
            payload=project.model_dump_json(),
        )

    def save_project_snapshot(
        self,
        project: ProjectRecord,
        scan: ProjectScan,
        files: list[ProjectFile],
        symbols: list[ProjectSymbol],
        tests: list[ProjectTest],
        dependencies: list[ProjectDependency],
    ) -> None:
        self.driver.execute_query(
            "MERGE (p:Project {id: $id}) "
            "SET p.root=$root, p.read_only=$read_only, "
            "p.explicitly_selected=$explicitly_selected, p.payload=$payload",
            id=project.id,
            root=project.root,
            read_only=project.read_only,
            explicitly_selected=project.explicitly_selected,
            payload=project.model_dump_json(),
        )
        self.driver.execute_query(
            "MATCH (p:Project {id: $project_id}) "
            "MERGE (s:ProjectScan {id: $id}) "
            "SET s.project_id=$project_id, s.status=$status, "
            "s.started_at=$started_at, s.payload=$payload "
            "MERGE (p)-[:HAS_PROJECT_SCAN]->(s)",
            project_id=project.id,
            id=scan.id,
            status=scan.status.value,
            started_at=scan.started_at.isoformat(),
            payload=scan.model_dump_json(),
        )
        if scan.previous_scan_id:
            self.driver.execute_query(
                "MATCH (current:ProjectScan {id: $current_id}), "
                "(previous:ProjectScan {id: $previous_id}) "
                "MERGE (current)-[:PREVIOUS_PROJECT_SCAN]->(previous)",
                current_id=scan.id,
                previous_id=scan.previous_scan_id,
            )
        keep_ids = [item.id for item in [*files, *symbols, *tests, *dependencies]]
        self.driver.execute_query(
            "MATCH (n) WHERE n.project_id = $project_id "
            "AND (n:ProjectFile OR n:ProjectSymbol OR n:ProjectTest OR n:ProjectDependency) "
            "AND NOT n.id IN $keep_ids DETACH DELETE n",
            project_id=project.id,
            keep_ids=keep_ids,
        )
        self.driver.execute_query(
            "MATCH (p:Project {id: $project_id})-[r:CONTAINS_PROJECT_FILE]->() DELETE r",
            project_id=project.id,
        )

        def batches(items, size: int = 500):
            for offset in range(0, len(items), size):
                yield items[offset : offset + size]

        file_rows = [
            {
                "id": item.id,
                "path": item.path,
                "content_hash": item.content_hash,
                "lifecycle": item.lifecycle.value,
                "active": item.lifecycle.value == "ACTIVE",
                "payload": item.model_dump_json(),
            }
            for item in files
        ]
        for rows in batches(file_rows):
            self.driver.execute_query(
                "MATCH (p:Project {id: $project_id}), (s:ProjectScan {id: $scan_id}) "
                "UNWIND $rows AS row "
                "MERGE (f:ProjectFile {id: row.id}) "
                "SET f.project_id=$project_id, f.path=row.path, "
                "f.content_hash=row.content_hash, f.lifecycle=row.lifecycle, "
                "f.payload=row.payload "
                "MERGE (s)-[:OBSERVED_PROJECT_FILE]->(f) "
                "FOREACH (_ IN CASE WHEN row.active THEN [1] ELSE [] END | "
                "MERGE (p)-[:CONTAINS_PROJECT_FILE]->(f))",
                project_id=project.id,
                scan_id=scan.id,
                rows=rows,
            )
        symbol_rows = [
            {
                "file_id": item.file_id,
                "id": item.id,
                "name": item.name,
                "kind": item.kind.value,
                "payload": item.model_dump_json(),
            }
            for item in symbols
        ]
        for rows in batches(symbol_rows):
            self.driver.execute_query(
                "UNWIND $rows AS row "
                "MATCH (f:ProjectFile {id: row.file_id}) "
                "MERGE (n:ProjectSymbol {id: row.id}) "
                "SET n.project_id=$project_id, n.name=row.name, "
                "n.kind=row.kind, n.payload=row.payload "
                "MERGE (f)-[:DECLARES_SYMBOL]->(n)",
                project_id=project.id,
                rows=rows,
            )
        test_rows = [
            {
                "file_id": item.file_id,
                "id": item.id,
                "name": item.name,
                "framework": item.framework,
                "payload": item.model_dump_json(),
            }
            for item in tests
        ]
        for rows in batches(test_rows):
            self.driver.execute_query(
                "UNWIND $rows AS row "
                "MATCH (f:ProjectFile {id: row.file_id}) "
                "MERGE (n:ProjectTest {id: row.id}) "
                "SET n.project_id=$project_id, n.name=row.name, "
                "n.framework=row.framework, n.payload=row.payload "
                "MERGE (f)-[:DECLARES_TEST]->(n)",
                project_id=project.id,
                rows=rows,
            )
        dependency_rows = [
            {
                "file_id": item.source_file_id,
                "id": item.id,
                "import_name": item.import_name,
                "target_file_id": item.target_file_id,
                "payload": item.model_dump_json(),
            }
            for item in dependencies
        ]
        for rows in batches(dependency_rows):
            self.driver.execute_query(
                "UNWIND $rows AS row "
                "MATCH (f:ProjectFile {id: row.file_id}) "
                "MERGE (n:ProjectDependency {id: row.id}) "
                "SET n.project_id=$project_id, n.import_name=row.import_name, "
                "n.payload=row.payload "
                "MERGE (f)-[:IMPORTS_DEPENDENCY]->(n) "
                "FOREACH (_ IN CASE WHEN row.target_file_id IS NOT NULL THEN [1] ELSE [] END | "
                "MERGE (target:ProjectFile {id: row.target_file_id}) "
                "MERGE (n)-[:DEPENDS_ON_FILE]->(target))",
                project_id=project.id,
                rows=rows,
            )
        for claim_id in scan.invalidated_claim_ids:
            self.save_edge(
                GraphEdge(
                    source=claim_id,
                    relation=GraphRelation.INVALIDATED_BY_SCAN,
                    target=scan.id,
                )
            )

    def projects(self) -> list[ProjectRecord]:
        records, _, _ = self.driver.execute_query(
            "MATCH (p:Project) RETURN p.payload AS payload ORDER BY p.id"
        )
        return [ProjectRecord.model_validate_json(record["payload"]) for record in records]

    def project_scans(self, project_id: str | None = None) -> list[ProjectScan]:
        records, _, _ = self.driver.execute_query(
            "MATCH (s:ProjectScan) RETURN s.payload AS payload ORDER BY s.id"
        )
        scans = [ProjectScan.model_validate_json(record["payload"]) for record in records]
        return [scan for scan in scans if project_id is None or scan.project_id == project_id]

    def project_files(
        self, project_id: str | None = None, *, include_deleted: bool = False
    ) -> list[ProjectFile]:
        records, _, _ = self.driver.execute_query(
            "MATCH (f:ProjectFile) RETURN f.payload AS payload ORDER BY f.id"
        )
        files = [ProjectFile.model_validate_json(record["payload"]) for record in records]
        return [
            item
            for item in files
            if (project_id is None or item.project_id == project_id)
            and (include_deleted or item.lifecycle.value == "ACTIVE")
        ]

    def _neo_project_artifacts(self, label: str, model, project_id: str | None):
        records, _, _ = self.driver.execute_query(
            f"MATCH (n:{label}) RETURN n.payload AS payload ORDER BY n.id"
        )
        items = [model.model_validate_json(record["payload"]) for record in records]
        return [item for item in items if project_id is None or item.project_id == project_id]

    def project_symbols(self, project_id: str | None = None) -> list[ProjectSymbol]:
        return self._neo_project_artifacts("ProjectSymbol", ProjectSymbol, project_id)

    def project_tests(self, project_id: str | None = None) -> list[ProjectTest]:
        return self._neo_project_artifacts("ProjectTest", ProjectTest, project_id)

    def project_dependencies(self, project_id: str | None = None) -> list[ProjectDependency]:
        return self._neo_project_artifacts("ProjectDependency", ProjectDependency, project_id)
