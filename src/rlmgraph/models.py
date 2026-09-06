from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"
    RECURSE = "RECURSE"
    STOPPED = "STOPPED"


class StoppingReason(StrEnum):
    COMPLETED = "COMPLETED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MAX_DEPTH = "MAX_DEPTH"
    CALL_BUDGET = "CALL_BUDGET"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    RETRIEVAL_TOKEN_BUDGET = "RETRIEVAL_TOKEN_BUDGET"
    WALL_TIME_BUDGET = "WALL_TIME_BUDGET"
    DUPLICATE_BUDGET = "DUPLICATE_BUDGET"


class TaskKind(StrEnum):
    INVESTIGATION = "INVESTIGATION"
    RESOLUTION = "RESOLUTION"
    FOLLOW_UP = "FOLLOW_UP"


class PlanningAction(StrEnum):
    CREATED = "CREATED"
    PRIORITIZED = "PRIORITIZED"
    ROUTED = "ROUTED"
    REUSED = "REUSED"
    REPLANNED = "REPLANNED"
    CONSUMED = "CONSUMED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


class TaskRoute(StrEnum):
    MEMORY = "MEMORY"
    LOCAL_INVESTIGATOR = "LOCAL_INVESTIGATOR"
    LOCAL_MODEL = "LOCAL_MODEL"
    CODEX = "CODEX"
    RESOLVER = "RESOLVER"


class ExecutionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    FAILED = "FAILED"
    REUSED = "REUSED"


class ClaimKind(StrEnum):
    DISCOVERY = "DISCOVERY"
    ADJUDICATED = "ADJUDICATED"


class ClaimValidity(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class MemoryTier(StrEnum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"


class MemoryLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class PromotionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PathwayLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"


class ResolutionChoice(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    VALUE = "value"
    NEITHER = "neither"


class ClusterStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class VerdictStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class ScanStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProjectIdeaStatus(StrEnum):
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"


class RepairStatus(StrEnum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PromotionStatus(StrEnum):
    APPROVED = "APPROVED"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    ROLLED_BACK = "ROLLED_BACK"
    APPLICATION_FAILED = "APPLICATION_FAILED"


class ReconciliationStatus(StrEnum):
    RECONCILED = "RECONCILED"


class MaintenanceWorkflowStatus(StrEnum):
    CREATED = "CREATED"
    DIAGNOSED = "DIAGNOSED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class ProjectLeaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ProjectLeaseEventKind(StrEnum):
    ACQUIRED = "ACQUIRED"
    RENEWED = "RENEWED"
    CONTENDED = "CONTENDED"
    RECLAIMED = "RECLAIMED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    RELEASED = "RELEASED"


class EvaluationStrategy(StrEnum):
    MEMORYLESS = "MEMORYLESS"
    STATIC_RETRIEVAL = "STATIC_RETRIEVAL"
    RLMGRAPH = "RLMGRAPH"


class EvaluationScenario(StrEnum):
    REPEATED_DEBUGGING = "REPEATED_DEBUGGING"
    CONFLICT = "CONFLICT"
    RECOVERY = "RECOVERY"


class FileLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class FileChangeKind(StrEnum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    RENAMED = "RENAMED"
    DELETED = "DELETED"
    UNCHANGED = "UNCHANGED"


class SymbolKind(StrEnum):
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"


class ReconstructionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ReconstructionAction(StrEnum):
    SEED = "SEED"
    EXPAND = "EXPAND"
    PRUNE = "PRUNE"


class GraphRelation(StrEnum):
    DISCOVERED = "DISCOVERED"
    CONTRADICTS = "CONTRADICTS"
    CONSIDERS = "CONSIDERS"
    PRODUCED = "PRODUCED"
    RESOLVES = "RESOLVES"
    SPAWNED = "SPAWNED"
    INFORMS = "INFORMS"
    ATTEMPTED = "ATTEMPTED"
    HAS_CLUSTER = "HAS_CLUSTER"
    SUPPORTS = "SUPPORTS"
    CORROBORATES = "CORROBORATES"
    OUTLIER = "OUTLIER"
    RESOLVES_CLUSTER = "RESOLVES_CLUSTER"
    DERIVED_FROM = "DERIVED_FROM"
    SUPERSEDES = "SUPERSEDES"
    REUSED = "REUSED"
    HAS_RECONSTRUCTION = "HAS_RECONSTRUCTION"
    HAS_STEP = "HAS_STEP"
    SEEDED = "SEEDED"
    EXPANDED_TO = "EXPANDED_TO"
    PRUNED_FROM = "PRUNED_FROM"
    HAS_PROMOTION = "HAS_PROMOTION"
    EVALUATED = "EVALUATED"
    CONSOLIDATED_FROM = "CONSOLIDATED_FROM"
    PROMOTED_TO = "PROMOTED_TO"
    REJECTED_CANDIDATE = "REJECTED_CANDIDATE"
    HAS_BENCHMARK = "HAS_BENCHMARK"
    MEASURED_RECONSTRUCTION = "MEASURED_RECONSTRUCTION"
    HAS_PATHWAY_DECISION = "HAS_PATHWAY_DECISION"
    PROMOTED_PATHWAY = "PROMOTED_PATHWAY"
    PATHWAY_INCLUDES = "PATHWAY_INCLUDES"
    SUPPORTS_PATHWAY = "SUPPORTS_PATHWAY"
    HAS_PLAN_DECISION = "HAS_PLAN_DECISION"
    PLANNED_TASK = "PLANNED_TASK"
    HAS_PLANNING_RUN = "HAS_PLANNING_RUN"
    HAS_EXECUTION = "HAS_EXECUTION"
    FALLBACK_TO = "FALLBACK_TO"
    HAS_ROUTE_PREDICTION = "HAS_ROUTE_PREDICTION"
    PREDICTED_EXECUTION = "PREDICTED_EXECUTION"
    HAS_POLICY_UPDATE = "HAS_POLICY_UPDATE"
    BASED_ON_EXECUTION = "BASED_ON_EXECUTION"
    EVALUATES_PREDICTION = "EVALUATES_PREDICTION"
    HAS_VERDICT = "HAS_VERDICT"
    SUPPORTS_VERDICT = "SUPPORTS_VERDICT"
    CONTRADICTS_VERDICT = "CONTRADICTS_VERDICT"
    EVIDENCE_FOR_VERDICT = "EVIDENCE_FOR_VERDICT"
    REUSED_VERDICT = "REUSED_VERDICT"
    HAS_PROJECT_SCAN = "HAS_PROJECT_SCAN"
    PREVIOUS_PROJECT_SCAN = "PREVIOUS_PROJECT_SCAN"
    CONTAINS_PROJECT_FILE = "CONTAINS_PROJECT_FILE"
    OBSERVED_PROJECT_FILE = "OBSERVED_PROJECT_FILE"
    DECLARES_SYMBOL = "DECLARES_SYMBOL"
    DECLARES_TEST = "DECLARES_TEST"
    IMPORTS_DEPENDENCY = "IMPORTS_DEPENDENCY"
    DEPENDS_ON_FILE = "DEPENDS_ON_FILE"
    DEPENDS_ON_TASK = "DEPENDS_ON_TASK"
    INVALIDATED_BY_SCAN = "INVALIDATED_BY_SCAN"
    AUTHORIZED_FILE = "AUTHORIZED_FILE"
    TRACED_DEPENDENCY = "TRACED_DEPENDENCY"
    SYNTHESIZED_FROM = "SYNTHESIZED_FROM"
    HAS_REPAIR = "HAS_REPAIR"
    PROPOSED_PATCH = "PROPOSED_PATCH"
    VALIDATED_BY = "VALIDATED_BY"
    VERIFIED_REPAIR = "VERIFIED_REPAIR"
    REUSED_REPAIR = "REUSED_REPAIR"
    HAS_APPROVAL = "HAS_APPROVAL"
    APPROVES_REPAIR = "APPROVES_REPAIR"
    HAS_PROMOTION_RUN = "HAS_PROMOTION_RUN"
    APPLIED_REPAIR = "APPLIED_REPAIR"
    FINAL_VALIDATED_BY = "FINAL_VALIDATED_BY"
    ROLLED_BACK_REPAIR = "ROLLED_BACK_REPAIR"
    RECONCILED_BY = "RECONCILED_BY"
    RECONCILIATION_SCAN = "RECONCILIATION_SCAN"
    RECORDED_REPAIRED_STATE = "RECORDED_REPAIRED_STATE"
    PROVED_FOLLOWUP_REUSE = "PROVED_FOLLOWUP_REUSE"
    WORKFLOW_DIAGNOSIS = "WORKFLOW_DIAGNOSIS"
    WORKFLOW_REPAIR = "WORKFLOW_REPAIR"
    WORKFLOW_APPROVAL = "WORKFLOW_APPROVAL"
    WORKFLOW_PROMOTION = "WORKFLOW_PROMOTION"
    WORKFLOW_RECONCILIATION = "WORKFLOW_RECONCILIATION"
    WORKFLOW_FOLLOWUP = "WORKFLOW_FOLLOWUP"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Annotated[str, Field(min_length=1)]
    detail: str
    line: int | None = None


class SourceFile(BaseModel):
    path: str
    content_hash: str
    evidence_lines: list[int] = Field(default_factory=list)


class FileChange(BaseModel):
    kind: FileChangeKind
    path: str
    previous_path: str | None = None
    content_hash: str | None = None
    previous_hash: str | None = None


class ProjectIdea(BaseModel):
    id: str = Field(default_factory=lambda: new_id("IDEA"))
    title: Annotated[str, Field(min_length=1, max_length=160)]
    detail: Annotated[str, Field(max_length=2000)] = ""
    status: ProjectIdeaStatus = ProjectIdeaStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectIdeaSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=160)]
    detail: Annotated[str, Field(min_length=1, max_length=800)]
    rationale: Annotated[str, Field(min_length=1, max_length=800)]
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=4)]


class ProjectIdeaSuggestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: Annotated[
        list[ProjectIdeaSuggestion], Field(min_length=1, max_length=3)
    ]
    files_examined: Annotated[list[str], Field(min_length=1, max_length=30)]
    confidence: Annotated[float, Field(ge=0, le=1)]


class ProjectExecutionMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    PROTECTED = "PROTECTED"
    AUTONOMOUS_SANDBOX = "AUTONOMOUS_SANDBOX"
    AUTONOMOUS_PROJECT = "AUTONOMOUS_PROJECT"


class ProjectRecord(BaseModel):
    id: str
    root: str
    explicitly_selected: bool
    read_only: bool = True
    execution_mode: ProjectExecutionMode = ProjectExecutionMode.PROTECTED
    latest_scan_id: str | None = None
    organization: Annotated[str, Field(min_length=1, max_length=120)] = "Personal"
    project_manifest: Annotated[str, Field(max_length=12000)] = ""
    project_goals: Annotated[str, Field(max_length=12000)] = ""
    ideas: list[ProjectIdea] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalPolicyRule(BaseModel):
    id: str
    action: str
    required_roles: list[str] = Field(default_factory=list)
    minimum_approvals: int = Field(default=1, ge=1)
    artifact_kinds: list[str] = Field(default_factory=list)
    required_validation_categories: list[str] = Field(default_factory=list)


class GovernanceDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("GOVERNANCE-DECISION"))
    project_id: str
    project_root: str
    action: str
    artifact_id: str
    decision: str
    actor: str
    actor_roles: list[str] = Field(default_factory=list)
    authenticated_subject: str | None = None
    authentication_method: str | None = None
    organization_id: str | None = None
    session_id: str | None = None
    reason: str
    policy_id: str
    policy_version: int
    rule_id: str
    binding_sha256: str
    source_manifest_sha256: str | None = None
    patch_sha256: str | None = None
    requirements_sha256: str | None = None
    evidence_sha256: str | None = None
    valid: bool = True
    expiration_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectPolicyRevision(BaseModel):
    version: int
    permitted_worker_ids: list[str]
    required_validation_categories: list[str]
    plan_approvers: list[str]
    promotion_approvers: list[str]
    actor_roles: dict[str, list[str]] = Field(default_factory=dict)
    authority_mode: str = "INDIVIDUAL_LOCAL"
    authority_organization_id: str | None = None
    authenticated_role_bindings: dict[str, list[str]] = Field(default_factory=dict)
    approval_rules: list[ApprovalPolicyRule] = Field(default_factory=list)
    artifact_validation_requirements: dict[str, list[str]] = Field(default_factory=dict)
    max_ticket_budget: dict[str, int | float]
    configured_by: str
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectGovernancePolicy(BaseModel):
    """Durable authorization limits for exactly one registered project."""

    id: str = Field(default_factory=lambda: new_id("PROJECT-POLICY"))
    project_id: str
    project_root: str
    permitted_worker_ids: list[str] = Field(default_factory=lambda: ["*"])
    required_validation_categories: list[str] = Field(default_factory=list)
    plan_approvers: list[str] = Field(default_factory=lambda: ["*"])
    promotion_approvers: list[str] = Field(default_factory=lambda: ["*"])
    actor_roles: dict[str, list[str]] = Field(default_factory=dict)
    authority_mode: str = "INDIVIDUAL_LOCAL"
    authority_organization_id: str | None = None
    authenticated_role_bindings: dict[str, list[str]] = Field(default_factory=dict)
    approval_rules: list[ApprovalPolicyRule] = Field(default_factory=lambda: [
        ApprovalPolicyRule(id="PLAN-APPROVAL", action="PLAN", minimum_approvals=1),
        ApprovalPolicyRule(id="PROMOTION-APPROVAL", action="PROMOTION", minimum_approvals=1),
        ApprovalPolicyRule(id="VALIDATION-ATTESTATION", action="ATTESTATION", minimum_approvals=1),
    ])
    artifact_validation_requirements: dict[str, list[str]] = Field(default_factory=dict)
    max_ticket_budget: TicketBudget = Field(default_factory=lambda: TicketBudget())
    configured_by: str = "RLMGraph default governance"
    reason: str = "Compatibility policy created for an explicitly registered project."
    version: int = Field(default=1, ge=1)
    revision_history: list[ProjectPolicyRevision] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectFile(BaseModel):
    id: str
    project_id: str
    path: str
    content_hash: str
    size_bytes: int
    modified_time_ns: int = 0
    language: str
    is_test: bool = False
    lifecycle: FileLifecycle = FileLifecycle.ACTIVE
    last_scan_id: str


class ProjectSymbol(BaseModel):
    id: str
    project_id: str
    file_id: str
    source_path: str
    source_content_hash: str
    name: str
    qualified_name: str
    kind: SymbolKind
    line: int


class ProjectTest(BaseModel):
    id: str
    project_id: str
    file_id: str
    source_path: str
    source_content_hash: str
    name: str
    qualified_name: str
    line: int
    framework: str


class ProjectDependency(BaseModel):
    id: str
    project_id: str
    source_file_id: str
    source_path: str
    source_content_hash: str
    import_name: str
    target_file_id: str | None = None


class ProjectScan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SCAN"))
    project_id: str
    root: str
    previous_scan_id: str | None = None
    status: ScanStatus = ScanStatus.COMPLETED
    changes: list[FileChange] = Field(default_factory=list)
    file_count: int = 0
    symbol_count: int = 0
    test_count: int = 0
    dependency_count: int = 0
    parsed_file_count: int = 0
    content_read_file_count: int = 0
    reused_file_ids: list[str] = Field(default_factory=list)
    invalidated_claim_ids: list[str] = Field(default_factory=list)
    model_calls: int = 0
    read_only_verified: bool = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DependencySlice(BaseModel):
    test_path: str
    test_file_id: str
    file_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    dependency_ids: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)


class ValidityEvent(BaseModel):
    status: ClaimValidity
    project_fingerprint: str
    reason: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TierTransition(BaseModel):
    from_tier: MemoryTier | None = None
    to_tier: MemoryTier
    reason: str
    decision_id: str | None = None
    transitioned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Assertion(BaseModel):
    """One exclusive, machine-comparable statement about code behavior."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: str
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)]
    files_examined: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    files_changed: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)


class ResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_claim: ResolutionChoice
    resolved_assertion: Assertion | None
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)]
    unresolved_questions: list[str] = Field(default_factory=list)
    selected_value: str | None = None
    selected_claim_ids: list[str] = Field(default_factory=list)
    corroborated_claim_ids: list[str] = Field(default_factory=list)
    outlier_claim_ids: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CLAIM"))
    fingerprint: str
    project_fingerprint: str = ""
    project_root: str = ""
    subject: str
    producer: str
    kind: ClaimKind = ClaimKind.DISCOVERY
    resolution_task_id: str | None = None
    resolved_claim_ids: list[str] = Field(default_factory=list)
    conclusion: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    evidence: list[Evidence] = Field(default_factory=list)
    files_examined: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_task_id: str | None = None
    source_claim_ids: list[str] = Field(default_factory=list)
    source_files: list[SourceFile] = Field(default_factory=list)
    source_commit: str | None = None
    learned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_from: str | None = None
    valid_until: str | None = None
    validity_status: ClaimValidity = ClaimValidity.CURRENT
    validity_reason: str = "Claim has not yet been checked against repository evidence."
    validity_history: list[ValidityEvent] = Field(default_factory=list)
    superseded_by_claim_id: str | None = None
    memory_tier: MemoryTier = MemoryTier.WORKING
    memory_lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE
    tier_history: list[TierTransition] = Field(default_factory=list)
    promoted_to_claim_id: str | None = None
    successful_reuse_count: int = 0
    memory_policy_decision_id: str | None = None
    conflict_verdict_id: str | None = None


class Interpretation(BaseModel):
    value: str
    normalized_value: str
    claim_ids: list[str] = Field(default_factory=list)


class ConflictCluster(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CLUSTER"))
    project_fingerprint: str
    assertion_key: str
    claim_ids: list[str] = Field(default_factory=list)
    interpretations: list[Interpretation] = Field(default_factory=list)
    corroborated_claim_ids: list[str] = Field(default_factory=list)
    outlier_claim_ids: list[str] = Field(default_factory=list)
    resolution_task_id: str | None = None
    resolved_claim_id: str | None = None
    selected_value: str | None = None
    status: ClusterStatus = ClusterStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConflictVerdict(BaseModel):
    """Durable, provenance-complete adjudication of one assertion conflict."""

    id: str = Field(default_factory=lambda: new_id("VERDICT"))
    resolution_task_id: str
    conflict_cluster_id: str | None = None
    assertion_key: str
    status: VerdictStatus
    selected_value: str | None = None
    confidence: Annotated[float, Field(ge=0, le=1)]
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    contradicting_claim_ids: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    resolver_attempt_id: str
    unresolved_questions: list[str] = Field(default_factory=list)
    confidence_threshold: Annotated[float, Field(ge=0, le=1)]
    max_resolution_attempts: int = Field(ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("TASK"))
    question: str
    fingerprint: str
    project_fingerprint: str = ""
    project_root: str
    kind: TaskKind = TaskKind.INVESTIGATION
    parent_task_id: str | None = None
    conflicting_claim_ids: list[str] = Field(default_factory=list)
    disputed_assertion_key: str | None = None
    resolved_claim_id: str | None = None
    conflict_cluster_id: str | None = None
    conflict_verdict_id: str | None = None
    reused_verdict_id: str | None = None
    evidence_gap: str | None = None
    relevant_files: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    output_claim_id: str | None = None
    depth: int = 0
    attempt_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stopping_reason: StoppingReason | None = None
    last_error: str | None = None
    status: TaskStatus = TaskStatus.OPEN
    reused_claim_id: str | None = None
    reuse_type: str | None = None
    relevance_score: float | None = None
    reuse_reason: str | None = None
    reconstruction_id: str | None = None
    priority: float = 0.0
    uncertainty: float = 1.0
    difficulty: float = 0.5
    route: TaskRoute | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls, question: str, project_root: Path, fingerprint: str, project_state: str
    ) -> Task:
        return cls(
            question=question,
            project_root=str(project_root.resolve()),
            fingerprint=fingerprint,
            project_fingerprint=project_state,
        )


class ClaimConflict(BaseModel):
    left_claim_id: str
    right_claim_id: str
    assertion_key: str
    left_value: str
    right_value: str


class RunResult(BaseModel):
    task: Task
    claim: Claim
    cache_hit: bool
    reuse_type: str | None = None
    relevance_score: float | None = None
    reuse_reason: str | None = None
    conflicts: list[ClaimConflict] = Field(default_factory=list)
    resolution_tasks: list[Task] = Field(default_factory=list)
    conflict_clusters: list[ConflictCluster] = Field(default_factory=list)
    investigation_calls: int
    reconstruction: ReconstructionSession | None = None
    project_scan_id: str | None = None
    source_files_read: int = 0
    source_files_parsed: int = 0


class GraphDebugResult(BaseModel):
    root_task: Task
    sub_tasks: list[Task] = Field(default_factory=list)
    finding_claims: list[Claim] = Field(default_factory=list)
    diagnosis: Claim
    dependency_slice: DependencySlice
    project_scan: ProjectScan
    worker_calls: int = 0
    reused_subtasks: int = 0
    analyzed_files: list[str] = Field(default_factory=list)
    supplied_files: list[str] = Field(default_factory=list)


class RepairWorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    files_read: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    file_change_reasons: dict[str, str] = Field(default_factory=dict)
    model_calls: int = 1


class GeneratedTextArtifact(BaseModel):
    """A tool-free model result that RLMGraph may validate and write itself."""

    model_config = ConfigDict(extra="forbid")

    content: str
    rationale: str
    confidence: Annotated[float, Field(ge=0, le=1)]


class SingleCallFileReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    change_reason: str = Field(default="", max_length=2000, description="Explain why this file must change to satisfy the user's task; distinguish required work from optional cleanup.")


class SingleCallPatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    replacements: list[SingleCallFileReplacement] = Field(default_factory=list)


class SurgicalSymbolEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    target_symbol: str
    expected_hash: str
    operation: Literal["REPLACE_SYMBOL", "INSERT_AFTER"]
    content: str
    change_reason: str = Field(default="", max_length=2000, description="Explain why this edit is necessary for the requested outcome, rather than unrelated improvement.")


class SingleCallSurgicalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    edits: list[SurgicalSymbolEdit] = Field(default_factory=list)


class PatchChange(BaseModel):
    path: str
    before_hash: str
    after_hash: str
    unified_diff: str
    change_reason: str | None = None
    before_content: str | None = None
    after_content: str | None = None
    before_bytes_base64: str | None = None
    after_bytes_base64: str | None = None


class TestExecution(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0


class RepairProposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("REPAIR"))
    repair_task_id: str
    diagnosis_claim_id: str
    project_root: str
    project_fingerprint: str
    source_tree_fingerprint: str = ""
    test_path: str
    authorized_paths: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    changes: list[PatchChange] = Field(default_factory=list)
    rationale: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    worker: str
    model_calls: int = 0
    signature: str
    status: RepairStatus = RepairStatus.PROPOSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepairValidation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("VALIDATION"))
    repair_task_id: str
    proposal_id: str
    attempt: int
    status: RepairStatus
    before: TestExecution
    after: TestExecution
    original_unchanged: bool
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepairRunResult(BaseModel):
    repair_task: Task
    proposal: RepairProposal
    validation: RepairValidation
    attempts: list[RepairValidation] = Field(default_factory=list)
    retry_tasks: list[Task] = Field(default_factory=list)
    worker_calls: int = 0
    model_calls: int = 0
    reused: bool = False


class RepairApproval(BaseModel):
    id: str = Field(default_factory=lambda: new_id("APPROVAL"))
    proposal_id: str
    validation_id: str
    project_root: str
    proposal_signature: str
    source_tree_fingerprint: str
    decision: ApprovalDecision
    approved_by: str
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromotionEvent(BaseModel):
    status: PromotionStatus
    detail: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepairPromotion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PROMOTION-RUN"))
    proposal_id: str
    validation_id: str
    approval_id: str
    project_root: str
    status: PromotionStatus
    changes: list[PatchChange] = Field(default_factory=list)
    original_tree_fingerprint: str
    applied_tree_fingerprint: str | None = None
    final_validation: TestExecution | None = None
    rollback_tree_fingerprint: str | None = None
    rollback_validation: TestExecution | None = None
    rollback_verified: bool | None = None
    failure_reason: str | None = None
    events: list[PromotionEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class PromotionRunResult(BaseModel):
    approval: RepairApproval
    promotion: RepairPromotion | None = None


class PostRepairReconciliation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("RECONCILE"))
    promotion_id: str
    proposal_id: str
    project_root: str
    status: ReconciliationStatus = ReconciliationStatus.RECONCILED
    previous_project_fingerprint: str
    new_project_fingerprint: str
    scan_id: str
    affected_paths: list[str] = Field(default_factory=list)
    parsed_paths: list[str] = Field(default_factory=list)
    parsed_file_count: int = 0
    content_read_file_count: int = 0
    reused_file_ids: list[str] = Field(default_factory=list)
    invalidated_claim_ids: list[str] = Field(default_factory=list)
    superseded_claim_ids: list[str] = Field(default_factory=list)
    replacement_claim_id: str
    follow_up_task_id: str
    follow_up_claim_id: str
    follow_up_reuse_type: str
    follow_up_worker_calls: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MaintenanceWorkflowEvent(BaseModel):
    status: MaintenanceWorkflowStatus
    detail: str
    artifact_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MaintenanceWorkflow(BaseModel):
    id: str = Field(default_factory=lambda: new_id("WORKFLOW"))
    signature: str
    question: str
    project_root: str
    test_path: str
    initial_project_fingerprint: str
    status: MaintenanceWorkflowStatus = MaintenanceWorkflowStatus.CREATED
    diagnosis_task_id: str | None = None
    diagnosis_claim_id: str | None = None
    repair_task_id: str | None = None
    proposal_id: str | None = None
    sandbox_validation_id: str | None = None
    approval_id: str | None = None
    promotion_id: str | None = None
    reconciliation_id: str | None = None
    follow_up_task_id: str | None = None
    follow_up_claim_id: str | None = None
    diagnosis_worker_calls: int = 0
    repair_worker_calls: int = 0
    repair_model_calls: int = 0
    promotion_attempts: int = 0
    follow_up_worker_calls: int = 0
    events: list[MaintenanceWorkflowEvent] = Field(default_factory=list)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class ProjectLeaseEvent(BaseModel):
    kind: ProjectLeaseEventKind
    holder_id: str
    workflow_id: str | None = None
    detail: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectLease(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PROJECT-LEASE"))
    project_root: str
    project_id: str | None = None
    holder_id: str
    workflow_id: str | None = None
    fencing_token: int = 1
    status: ProjectLeaseStatus = ProjectLeaseStatus.ACTIVE
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    renewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    released_at: datetime | None = None
    events: list[ProjectLeaseEvent] = Field(default_factory=list)


class ProjectLeaseAcquisition(BaseModel):
    acquired: bool
    reclaimed: bool = False
    lease: ProjectLease


class EvaluationCaseResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("EVAL-CASE"))
    run_id: str
    case_id: str
    repetition: int
    scenario: EvaluationScenario
    strategy: EvaluationStrategy
    answer: str
    expected_answer: str
    correct: bool
    evidence_complete: bool
    worker_calls: int
    model_calls: int
    retrieved_tokens: int
    latency_ms: float
    observed_latency_ms: float = 0.0
    duplicate_investigations: int
    memory_reuses: int
    conflict_resolved: bool | None = None
    recovery_succeeded: bool | None = None
    resolution_calls: int = 0
    retrieval_size: int = 0
    source_integrity_verified: bool | None = None
    abstained: bool = False
    expected_abstention: bool = False
    required_evidence_paths: list[str] = Field(default_factory=list)
    required_evidence_terms: list[str] = Field(default_factory=list)
    observed_evidence_paths: list[str] = Field(default_factory=list)
    observed_evidence_terms: list[str] = Field(default_factory=list)
    task_id: str | None = None
    verdict_id: str | None = None
    contract_type: str | None = None
    retrieved_claim_ids: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))



class EvaluationRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("EVALUATION"))
    suite_version: str = "deterministic-evaluation-v1"
    project_root: str
    repetitions: int
    results: list[EvaluationCaseResult] = Field(default_factory=list)
    correctness_preserved: bool = False
    evidence_preserved: bool = False
    fewer_repeat_worker_calls: bool = False
    fewer_tokens_than_static: bool = False
    stale_or_conflicting_memory_blocked: bool = False
    recovery_verified: bool = False
    reproducible: bool = False
    exact_replays_zero_calls: bool = False
    abstention_verified: bool = False
    source_integrity_verified: bool = False
    no_project_write_capability: bool = False
    case_contract_count: int = 0
    subsystem_count: int = 0
    initial_manifest_sha256: str | None = None
    final_manifest_sha256: str | None = None
    passed: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphEdge(BaseModel):
    source: str
    relation: GraphRelation
    target: str


class PromotionDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PROMOTION"))
    task_id: str
    project_root: str
    assertion_key: str
    from_tier: MemoryTier
    to_tier: MemoryTier
    outcome: PromotionOutcome
    candidate_claim_ids: list[str] = Field(default_factory=list)
    accepted_claim_ids: list[str] = Field(default_factory=list)
    rejected_claim_ids: list[str] = Field(default_factory=list)
    contradictory_claim_ids: list[str] = Field(default_factory=list)
    stale_claim_ids: list[str] = Field(default_factory=list)
    promoted_claim_id: str | None = None
    policy_version: str = "governed-memory-v1"
    minimum_support: int
    minimum_confidence: float
    observed_support: int
    observed_confidence: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReconstructionStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("STEP"))
    sequence: int
    action: ReconstructionAction
    node_id: str
    frontier_node_id: str | None = None
    relation: GraphRelation | None = None
    score: float = 0.0
    reason: str
    token_estimate: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReconstructionSession(BaseModel):
    id: str = Field(default_factory=lambda: new_id("RECON"))
    task_id: str
    query: str
    seed_node_ids: list[str] = Field(default_factory=list)
    selected_node_ids: list[str] = Field(default_factory=list)
    pruned_node_ids: list[str] = Field(default_factory=list)
    context_edges: list[GraphEdge] = Field(default_factory=list)
    steps: list[ReconstructionStep] = Field(default_factory=list)
    baseline_node_ids: list[str] = Field(default_factory=list)
    reconstructed_token_estimate: int = 0
    baseline_token_estimate: int = 0
    required_evidence_ids: list[str] = Field(default_factory=list)
    evidence_preserved: bool | None = None
    status: ReconstructionStatus = ReconstructionStatus.COMPLETE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BenchmarkOutcome(BaseModel):
    answer: str
    correct: bool
    evidence_complete: bool
    input_tokens: int
    output_tokens: int
    total_tokens: int
    wall_time_ms: float
    context_node_ids: list[str] = Field(default_factory=list)
    accessed_evidence_ids: list[str] = Field(default_factory=list)
    duplicate_retrievals: int = 0


class BenchmarkRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("BENCH"))
    task_id: str
    reconstruction_id: str
    case_id: str
    project_root: str
    question: str
    expected_answer: str
    required_evidence_ids: list[str] = Field(default_factory=list)
    fixed: BenchmarkOutcome
    active: BenchmarkOutcome
    traversal_node_ids: list[str] = Field(default_factory=list)
    traversal_edges: list[GraphEdge] = Field(default_factory=list)
    token_reduction: float
    correctness_preserved: bool
    evidence_preserved: bool
    passed: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VirtualMemoryPathway(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PATHWAY"))
    token: str
    version: int
    signature: str
    project_root: str
    node_ids: list[str]
    edges: list[GraphEdge] = Field(default_factory=list)
    child_tokens: list[str] = Field(default_factory=list)
    supporting_task_ids: list[str] = Field(default_factory=list)
    supporting_reconstruction_ids: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    source_files: list[SourceFile] = Field(default_factory=list)
    access_frequency: int
    average_tokens_saved: float
    confidence: Annotated[float, Field(ge=0, le=1)]
    stability: Annotated[float, Field(ge=0, le=1)]
    lifecycle: PathwayLifecycle = PathwayLifecycle.ACTIVE
    validity_reason: str
    valid_from: str
    valid_until: str | None = None
    policy_decision_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PathwayPromotionDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PATHDECISION"))
    project_root: str
    signature: str
    outcome: PromotionOutcome
    candidate_reconstruction_ids: list[str] = Field(default_factory=list)
    candidate_task_ids: list[str] = Field(default_factory=list)
    candidate_node_ids: list[str] = Field(default_factory=list)
    pathway_id: str | None = None
    token: str | None = None
    policy_version: str = "virtual-pathway-v1"
    minimum_frequency: int
    minimum_tokens_saved: int
    minimum_confidence: float
    minimum_stability: float
    observed_frequency: int
    observed_average_tokens_saved: float
    observed_confidence: float
    observed_stability: float
    contradictory_claim_ids: list[str] = Field(default_factory=list)
    stale_claim_ids: list[str] = Field(default_factory=list)
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PathwayExpansion(BaseModel):
    token: str
    pathway_id: str | None = None
    requested_depth: int
    expanded_tokens: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    source_files: list[SourceFile] = Field(default_factory=list)
    expansion_trace: list[str] = Field(default_factory=list)
    token_cost: int = 0
    complete: bool = False
    reason: str


class PathwayBenchmarkResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PATHBENCH"))
    pathway_id: str
    token: str
    task_id: str
    question: str
    active_input_tokens: int
    token_input_tokens: int
    additional_reduction: float
    correct: bool
    evidence_preserved: bool
    expansion_complete: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResolutionRunResult(BaseModel):
    task: Task
    result: ResolutionResult
    adjudicated_claim: Claim | None = None
    verdict: ConflictVerdict
    resolution_calls: int


class ResolutionAttempt(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ATTEMPT"))
    task_id: str
    result: ResolutionResult
    evidence_claim_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResolutionContext(BaseModel):
    follow_up_claims: list[Claim] = Field(default_factory=list)
    previous_attempts: list[ResolutionAttempt] = Field(default_factory=list)
    conflict_cluster: ConflictCluster | None = None


class PursuitConfig(BaseModel):
    max_depth: Annotated[int, Field(ge=0)] = 4
    max_codex_calls: Annotated[int, Field(ge=0)] = 8
    max_retries_per_task: Annotated[int, Field(ge=1)] = 2
    minimum_confidence: Annotated[float, Field(ge=0, le=1)] = 0.75
    max_retrieval_tokens: Annotated[int, Field(ge=0)] = 8000
    max_duplicate_investigations: Annotated[int, Field(ge=0)] = 0
    max_wall_time_seconds: Annotated[float, Field(ge=0)] = 300.0


class PlanDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PLAN"))
    root_task_id: str
    task_id: str
    action: PlanningAction
    reason: str
    priority: float = 0.0
    uncertainty: float = 0.0
    difficulty: float = 0.0
    route: TaskRoute | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    model_calls_used: int = 0
    retrieval_tokens_used: int = 0
    duplicate_investigations: int = 0
    elapsed_seconds: float = 0.0
    stopping_reason: StoppingReason | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PlanningRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("PLANNING-RUN"))
    root_task_id: str
    status: TaskStatus = TaskStatus.OPEN
    stopping_reason: StoppingReason | None = None
    model_calls_used: int = 0
    retrieval_tokens_used: int = 0
    duplicate_investigations: int = 0
    elapsed_seconds: float = 0.0
    max_model_calls: int
    max_retrieval_tokens: int
    max_depth: int
    max_duplicate_investigations: int
    max_wall_time_seconds: float
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class ExecutionAttempt(BaseModel):
    id: str = Field(default_factory=lambda: new_id("EXECUTION"))
    root_task_id: str
    task_id: str
    sequence: int
    planned_route: TaskRoute
    actual_route: TaskRoute
    worker: str
    outcome: ExecutionOutcome
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    confidence: float | None = None
    fallback_from_attempt_id: str | None = None
    fallback_reason: str | None = None
    error: str | None = None
    task_category: str = "unknown"
    task_difficulty: float = 0.0
    route_prediction_id: str | None = None
    authorized_paths: list[str] = Field(default_factory=list)
    max_worker_calls: int | None = None
    max_wall_time_seconds: float | None = None
    max_context_tokens: int | None = None
    max_result_tokens: int | None = None
    sandbox: str | None = None
    structured_result_validated: bool | None = None
    access_scope_verified: bool | None = None
    source_integrity_verified: bool | None = None
    project_write_attempted: bool | None = None
    safety_decision: str | None = None
    replay: bool = False
    cost_basis: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CodexReadOnlyProof(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CODEX-PROOF"))
    project_id: str
    project_root: str
    test_path: str
    question: str
    expected_answer: str
    required_evidence_paths: list[str]
    required_evidence_terms: list[str]
    authorized_paths: list[str]
    max_codex_calls: int
    max_wall_time_seconds: float
    max_context_tokens: int
    max_result_tokens: int
    sandbox: str = "read-only"
    initial_task_id: str
    initial_claim_id: str
    initial_execution_id: str
    replay_task_id: str
    replay_execution_id: str
    initial_codex_calls: int
    replay_codex_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float = 0.0
    cost_basis: str
    latency_ms: float
    conclusion: str
    confidence: float
    evidence: list[Evidence]
    files_examined: list[str]
    unresolved_questions: list[str]
    structured_result_validated: bool
    evidence_contract_met: bool
    access_scope_verified: bool
    source_integrity_verified: bool
    no_project_write_attempt: bool
    no_repair_capability: bool
    exact_replay_zero_calls: bool
    initial_manifest_sha256: str
    final_manifest_sha256: str
    passed: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DelegatedCodexBranch(BaseModel):
    branch_id: str
    name: str
    question: str
    task_id: str
    claim_id: str
    execution_id: str
    authorized_paths: list[str]
    max_codex_calls: int
    max_wall_time_seconds: float
    max_context_tokens: int
    max_result_tokens: int
    codex_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float = 0.0
    cost_basis: str
    latency_ms: float
    conclusion: str
    confidence: float
    evidence: list[Evidence]
    files_examined: list[str]
    unresolved_questions: list[str]
    assertions: list[Assertion]
    structured_result_validated: bool
    branch_contract_met: bool
    safety_decision: str
    selection_reason: str = "Explicit milestone branch contract."
    dependency_distance: int = 0
    reused: bool = False
    semantic_relevance: float = 0.0
    reuse_reason: str | None = None
    source_proof_id: str | None = None


class DelegationAgreement(BaseModel):
    assertion_key: str
    value: str
    claim_ids: list[str]


class DelegationContradiction(BaseModel):
    assertion_key: str
    values: dict[str, list[str]]


class RecursiveCodexDelegationProof(BaseModel):
    id: str = Field(default_factory=lambda: new_id("RECURSIVE-CODEX"))
    project_id: str
    project_root: str
    test_path: str
    root_question: str
    expected_answer: str
    required_evidence_paths: list[str]
    required_evidence_terms: list[str]
    root_task_id: str
    branch_results: list[DelegatedCodexBranch]
    synthesis_task_id: str
    final_claim_id: str
    final_answer: str
    final_confidence: float
    final_evidence: list[Evidence]
    agreements: list[DelegationAgreement]
    contradictions: list[DelegationContradiction]
    follow_up_created: bool
    follow_up_reason: str | None = None
    follow_up_task_id: str | None = None
    follow_up_claim_id: str | None = None
    follow_up_execution_id: str | None = None
    follow_up_codex_calls: int = 0
    resolution_calls: int = 0
    initial_codex_calls: int
    initial_input_tokens: int
    initial_output_tokens: int
    initial_estimated_cost_usd: float = 0.0
    initial_latency_ms: float
    replay_root_task_id: str
    replay_branch_task_ids: list[str]
    replay_execution_ids: list[str]
    replay_codex_calls: int
    replay_resolution_calls: int
    exact_replay_zero_calls: bool
    evidence_contract_met: bool
    hierarchy_persisted: bool
    dependencies_persisted: bool
    provenance_persisted: bool
    safety_decisions_persisted: bool
    access_scope_verified: bool
    source_integrity_verified: bool
    no_project_write_attempt: bool
    no_repair_capability: bool
    mutation_rejection_verified: bool
    initial_manifest_sha256: str
    final_manifest_sha256: str
    passed: bool
    plan_generated: bool = False
    planning_algorithm: str = "explicit-branch-contract-v1"
    candidate_paths: list[str] = Field(default_factory=list)
    selected_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    abstained: bool = False
    abstention_reason: str | None = None
    semantic_reuse_enabled: bool = False
    semantic_match_question: str | None = None
    semantic_match_score: float = 0.0
    reused_claim_ids: list[str] = Field(default_factory=list)
    rejected_reuse_claims: list[dict[str, str]] = Field(default_factory=list)
    uncovered_paths: list[str] = Field(default_factory=list)
    remaining_worker_calls: int = 0
    fresh_baseline_codex_calls: int = 0
    fresh_baseline_input_tokens: int = 0
    fresh_baseline_output_tokens: int = 0
    fresh_baseline_latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GenericCodexEvaluationCase(BaseModel):
    case_id: str
    subsystem: str
    question: str
    test_path: str
    proof_id: str
    selected_paths: list[str]
    initial_codex_calls: int
    initial_input_tokens: int = 0
    initial_output_tokens: int = 0
    initial_latency_ms: float = 0.0
    replay_codex_calls: int
    replay_resolution_calls: int
    evidence_contract_met: bool
    abstained: bool
    source_integrity_verified: bool
    passed: bool
    reused_claim_count: int = 0
    rejected_claim_count: int = 0
    uncovered_paths: list[str] = Field(default_factory=list)
    fresh_codex_calls: int = 0
    reuse_codex_calls: int = 0
    fresh_input_tokens: int = 0
    reuse_input_tokens: int = 0
    fresh_latency_ms: float = 0.0
    reuse_latency_ms: float = 0.0


class GenericCodexEvaluation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("GENERIC-CODEX-EVAL"))
    suite_version: str
    project_id: str
    project_root: str
    cases: list[GenericCodexEvaluationCase]
    subsystem_count: int
    initial_codex_calls: int
    initial_input_tokens: int = 0
    initial_output_tokens: int = 0
    initial_latency_ms: float = 0.0
    replay_codex_calls: int
    replay_resolution_calls: int
    abstention_verified: bool
    exact_replays_zero_calls: bool
    source_integrity_verified: bool
    no_repair_capability: bool
    passed: bool
    initial_manifest_sha256: str
    final_manifest_sha256: str
    semantic_reuse_verified: bool = False
    fresh_codex_calls: int = 0
    reuse_codex_calls: int = 0
    fresh_input_tokens: int = 0
    reuse_input_tokens: int = 0
    fresh_latency_ms: float = 0.0
    reuse_latency_ms: float = 0.0
    stale_reuse_blocked: bool = False
    contradiction_reuse_blocked: bool = False
    weak_relevance_blocked: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InvestigationCheckpoint(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CHECKPOINT"))
    sequence: int
    stage: str
    project_fingerprint: str
    source_manifest_sha256: str
    fencing_token: int
    root_task_id: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    completed_paths: list[str] = Field(default_factory=list)
    branch_claim_ids: dict[str, str] = Field(default_factory=dict)
    branch_results: list[DelegatedCodexBranch] = Field(default_factory=list)
    follow_up_claim_id: str | None = None
    follow_up_execution_id: str | None = None
    synthesis_claim_id: str | None = None
    synthesis_task_id: str | None = None
    codex_calls_spent: int = 0
    input_tokens_spent: int = 0
    output_tokens_spent: int = 0
    latency_ms_spent: float = 0.0
    safety_decisions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InvestigationSession(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SESSION"))
    project_id: str
    project_root: str
    question: str
    test_path: str
    expected_answer: str = ""
    required_evidence_terms: list[str] = Field(default_factory=list)
    status: str = "CREATED"
    plan_algorithm: str = "indexed-dependency-distance-v1"
    candidate_paths: list[str] = Field(default_factory=list)
    selected_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    branch_specs: list[dict[str, object]] = Field(default_factory=list)
    root_task_id: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    checkpoints: list[InvestigationCheckpoint] = Field(default_factory=list)
    active_stage: str = "CREATED"
    remaining_tasks: list[str] = Field(default_factory=list)
    holder_id: str
    fencing_token: int = 1
    lease_expires_at: datetime
    recovered: bool = False
    recovery_count: int = 0
    invalidation_reasons: list[str] = Field(default_factory=list)
    recovered_checkpoint_ids: list[str] = Field(default_factory=list)
    avoided_codex_calls: int = 0
    avoided_input_tokens: int = 0
    avoided_output_tokens: int = 0
    avoided_latency_ms: float = 0.0
    final_proof_id: str | None = None
    source_integrity_verified: bool = False
    exact_reuse_preserved: bool = False
    semantic_reuse_preserved: bool = False
    budgets_preserved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResumableSessionEvaluationCase(BaseModel):
    case_id: str
    subsystem: str
    interrupted_stage: str
    session_id: str
    proof_id: str
    recovered_checkpoint_count: int
    avoided_codex_calls: int
    avoided_input_tokens: int
    avoided_latency_ms: float
    evidence_contract_met: bool
    source_integrity_verified: bool
    budgets_preserved: bool
    passed: bool


class ResumableSessionEvaluation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SESSION-EVAL"))
    suite_version: str = "resumable-project-sessions-v1"
    project_id: str
    project_root: str
    cases: list[ResumableSessionEvaluationCase]
    subsystem_count: int
    planning_recovery_verified: bool
    delegation_recovery_verified: bool
    conflict_recovery_verified: bool
    synthesis_recovery_verified: bool
    stale_provenance_rejected: bool
    stale_lease_rejected: bool
    exact_reuse_preserved: bool
    semantic_reuse_preserved: bool
    avoided_codex_calls: int
    avoided_input_tokens: int
    avoided_latency_ms: float
    source_integrity_verified: bool
    budgets_preserved: bool
    passed: bool
    initial_manifest_sha256: str
    final_manifest_sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UnrealArtifact(BaseModel):
    id: str
    project_id: str
    path: str
    content_hash: str
    size_bytes: int
    modified_time_ns: int
    kind: str
    name: str
    package_path: str | None = None
    module_name: str | None = None
    plugin_name: str | None = None
    class_names: list[str] = Field(default_factory=list)
    asset_class: str | None = None
    blueprint_generated_class: str | None = None
    metadata_terms: list[str] = Field(default_factory=list)
    is_test: bool = False
    binary_metadata_only: bool = False
    last_scan_id: str


class UnrealDependency(BaseModel):
    id: str
    project_id: str
    source_artifact_id: str
    source_path: str
    relation: str
    target_reference: str
    target_artifact_id: str | None = None
    evidence_line: int | None = None


class UnrealIndexScan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("UNREAL-SCAN"))
    project_id: str
    project_root: str
    artifact_count: int
    dependency_count: int
    kind_counts: dict[str, int]
    parsed_artifact_count: int
    reused_artifact_count: int
    invalidated_artifact_ids: list[str] = Field(default_factory=list)
    source_integrity_verified: bool
    project_launched: bool = False
    project_compiled: bool = False
    generated_files: int = 0
    initial_manifest_sha256: str
    final_manifest_sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))






















class ProjectWorkspaceRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("WORKSPACE-RESULT"))
    project_id: str
    project_root: str
    project_name: str
    kind: str
    prompt: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: str
    answer: str
    affected_file_ids: list[str] = Field(default_factory=list)
    affected_paths: list[str] = Field(default_factory=list)
    dependency_ids: list[str] = Field(default_factory=list)
    dependency_paths: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    impact_groups: dict[str, list[str]] = Field(default_factory=dict)
    steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)
    validation_commands: list[list[str]] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    source_result_id: str | None = None
    index_scan_id: str
    indexed_manifest_sha256: str
    final_manifest_sha256: str
    stale_evidence_rejected: bool = False
    source_integrity_verified: bool
    read_only_verified: bool
    approval_required: bool = False
    approval_status: str | None = None
    approval_history: list[GovernanceDecision] = Field(default_factory=list)
    approval_missing: list[str] = Field(default_factory=list)
    approval_expiration_reasons: list[str] = Field(default_factory=list)
    execution_authorized: bool = False
    ticket_id: str | None = None
    tokens_used: int = 0
    model_calls_used: int = 0
    worker_calls_used: int = 0
    branch_depth_used: int = 0
    elapsed_seconds: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TicketBudget(BaseModel):
    max_tokens: int = Field(default=50_000, ge=0)
    max_model_calls: int = Field(default=10, ge=0)
    max_worker_calls: int = Field(default=10, ge=0)
    max_wall_time_seconds: float = Field(default=900, ge=1)
    max_branch_depth: int = Field(default=4, ge=0)


ProjectGovernancePolicy.model_rebuild()


class TicketUsage(BaseModel):
    tokens: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    worker_calls: int = Field(default=0, ge=0)
    wall_time_seconds: float = Field(default=0, ge=0)
    deepest_branch: int = Field(default=0, ge=0)


class TicketEvidenceAssessment(BaseModel):
    evidence_id: str
    artifact_type: str
    eligible: bool
    reason: str
    ticket_id: str | None = None
    project_id: str | None = None
    status: str | None = None
    source_manifest_sha256: str | None = None
    patch_sha256: str | None = None
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TicketAcceptanceCriterion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CRITERION"))
    description: str
    status: str = "PENDING"
    evidence_ids: list[str] = Field(default_factory=list)
    waiver_reason: str | None = None
    blocker_reason: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    evidence_assessments: list[TicketEvidenceAssessment] = Field(default_factory=list)


class TicketCriterionClosureGate(BaseModel):
    criterion_id: str
    description: str
    status: str
    resolved: bool
    explanation: str
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    evidence_assessments: list[TicketEvidenceAssessment] = Field(default_factory=list)


class TicketClosureDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("TICKET-CLOSURE"))
    ticket_id: str
    project_id: str
    requested_status: str
    allowed: bool
    actor: str
    reason: str
    fingerprint: str
    failures: list[str] = Field(default_factory=list)
    criterion_gates: list[TicketCriterionClosureGate] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TicketConstraint(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CONSTRAINT"))
    description: str


class TicketDependencyScope(BaseModel):
    ticket_id: str
    project_id: str
    read_only: bool = True
    separately_authorized: bool = False


class ProjectTicket(BaseModel):
    id: str = Field(default_factory=lambda: new_id("TICKET"))
    project_id: str
    project_root: str
    title: str
    description: str
    priority: str = "MEDIUM"
    status: str = "DRAFT"
    acceptance_criteria: list[TicketAcceptanceCriterion]
    constraints: list[TicketConstraint] = Field(default_factory=list)
    dependency_ticket_ids: list[str] = Field(default_factory=list)
    dependency_scopes: list[TicketDependencyScope] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)
    governance_policy_id: str | None = None
    governance_policy_version: int | None = None
    budget_policy_rule_id: str = "BUDGET-CEILING"
    budget: TicketBudget = Field(default_factory=TicketBudget)
    usage: TicketUsage = Field(default_factory=TicketUsage)
    execution_authorized: bool = False
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    satisfied_at: datetime | None = None
    closure_decisions: list[TicketClosureDecision] = Field(default_factory=list)


class ObserverActivityState(BaseModel):
    id: str
    activity_kind: str
    status: str = "IDLE"
    ticket_id: str | None = None
    project_id: str | None = None
    artifact_id: str | None = None
    stage: str = "Ready."
    resumable: bool = False
    resume_payload: dict[str, object] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SchedulerLimits(BaseModel):
    global_concurrency: int = Field(default=2, ge=1)
    per_project_concurrency: int = Field(default=1, ge=1)
    per_ticket_concurrency: int = Field(default=1, ge=1)
    capacity_units: int = Field(default=2, ge=1)


class SchedulerCheckpoint(BaseModel):
    sequence: int = Field(ge=1)
    stage: str
    detail: str
    worker_calls_used: int = Field(default=0, ge=0)
    wall_time_seconds_used: float = Field(default=0, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScheduledWorkItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SCHEDULED-WORK"))
    ticket_id: str
    project_id: str
    project_root: str
    work_kind: str
    artifact_id: str | None = None
    status: str = "QUEUED"
    priority: str = "MEDIUM"
    required_validation_categories: list[str] = Field(default_factory=list)
    predicted_cost_usd: float = Field(default=0, ge=0)
    predicted_latency_seconds: float = Field(default=0, ge=0)
    predicted_worker_calls: int = Field(default=1, ge=0)
    capacity_units: int = Field(default=1, ge=1)
    requires_project_lease: bool = False
    scheduling_score: float = 0
    scheduling_reasons: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    resumable: bool = True
    cancellation_requested: bool = False
    cancelled_by: str | None = None
    cancellation_reason: str | None = None
    temporary_resources: list[str] = Field(default_factory=list)
    resources_disposed: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    checkpoints: list[SchedulerCheckpoint] = Field(default_factory=list)
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class TicketEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("TICKET-EVENT"))
    ticket_id: str
    project_id: str | None = None
    project_root: str | None = None
    kind: str
    detail: str
    actor: str
    artifact_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TicketValidationResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("TICKET-VALIDATION"))
    ticket_id: str
    project_id: str | None = None
    project_root: str | None = None
    name: str
    status: str
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)
    workspace_record_id: str | None = None
    recorded_by: str
    execution_authorized: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SandboxCheckpoint(BaseModel):
    sequence: int
    stage: str
    detail: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SandboxValidationDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-VALIDATION"))
    path: str
    artifact_kind: str
    category: str
    requirement: str
    status: str
    requires_unreal_editor: bool = False
    execution_index: int | None = None
    worker_execution_id: str | None = None
    external_report_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    satisfied_by: str | None = None
    satisfied_at: datetime | None = None
    attestation_history: list[GovernanceDecision] = Field(default_factory=list)
    attestation_missing: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ValidationWorkerLimits(BaseModel):
    max_wall_time_seconds: float = Field(default=30, gt=0)
    max_processes: int = Field(default=1, ge=1)
    max_memory_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    max_output_bytes: int = Field(default=20_000, ge=1)
    allowed_paths: list[str] = Field(default_factory=list)
    allowed_artifact_kinds: list[str] = Field(default_factory=list)
    allowed_executables: list[str] = Field(default_factory=list)
    allowed_argument_templates: list[list[str]] = Field(default_factory=list)


class ValidationWorkerSpec(BaseModel):
    id: str = Field(default_factory=lambda: new_id("VALIDATION-WORKER"))
    name: str
    categories: list[str]
    artifact_kinds: list[str]
    executable: str
    arguments: list[str]
    limits: ValidationWorkerLimits
    enabled: bool = True
    authorized_by: str
    authorization_reason: str
    estimated_cost_usd: float = Field(default=0, ge=0)


class SandboxValidationWorkerExecution(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-WORKER-EXECUTION"))
    ticket_id: str
    project_id: str | None = None
    project_root: str | None = None
    attempt_id: str
    decision_id: str
    worker_id: str
    worker_name: str
    category: str
    artifact_kind: str
    path: str
    source_manifest_sha256: str
    patch_sha256: str
    authorization_status: str
    policy_id: str | None = None
    policy_version: int | None = None
    policy_rule_id: str | None = None
    command: list[str] = Field(default_factory=list)
    limits: ValidationWorkerLimits
    status: str = "AUTHORIZED"
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0
    observed_processes: int = 0
    peak_memory_bytes: int = 0
    output_bytes: int = 0
    cost_usd: float = 0
    failure_reason: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    checkpoints: list[SandboxCheckpoint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SandboxExternalValidationReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-EXTERNAL-REPORT"))
    ticket_id: str
    project_id: str | None = None
    project_root: str | None = None
    attempt_id: str
    decision_id: str
    report_kind: str
    artifact_path: str
    source_manifest_sha256: str
    patch_sha256: str
    report_sha256: str
    report_bytes_base64: str
    status: str
    detail: str
    recorded_by: str
    policy_id: str | None = None
    policy_version: int | None = None
    rule_ids: list[str] = Field(default_factory=list)
    binding_sha256: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SandboxPromotionApproval(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-PROMOTION-APPROVAL"))
    project_id: str | None = None
    project_root: str | None = None
    decision: str
    approved_by: str
    reason: str
    source_manifest_sha256: str
    policy_id: str | None = None
    policy_version: int | None = None
    rule_ids: list[str] = Field(default_factory=list)
    binding_sha256: str | None = None
    requirements_sha256: str | None = None
    evidence_sha256: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SandboxPromotionReconciliation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-RECONCILIATION"))
    attempt_id: str
    promotion_id: str
    ticket_id: str
    project_id: str
    project_root: str
    status: str = "RECONCILED"
    previous_manifest_sha256: str
    new_manifest_sha256: str
    scan_id: str
    changed_paths: list[str] = Field(default_factory=list)
    dependent_paths: list[str] = Field(default_factory=list)
    parsed_paths: list[str] = Field(default_factory=list)
    reused_file_ids: list[str] = Field(default_factory=list)
    invalidated_claim_ids: list[str] = Field(default_factory=list)
    superseded_claim_ids: list[str] = Field(default_factory=list)
    invalidated_workspace_record_ids: list[str] = Field(default_factory=list)
    superseded_validation_decision_ids: list[str] = Field(default_factory=list)
    replacement_claim_ids: list[str] = Field(default_factory=list)
    replacement_task_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    checkpoints: list[SandboxCheckpoint] = Field(default_factory=list)
    source_unchanged_during_reconciliation: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SandboxMutationJournalEntry(BaseModel):
    path: str
    before_sha256: str
    after_sha256: str
    before_bytes_base64: str
    after_bytes_base64: str
    original_mode: int
    staged: bool = False
    replacement_started: bool = False
    replacement_completed: bool = False
    rollback_completed: bool = False


class SandboxMutationJournal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-MUTATION-JOURNAL"))
    ticket_id: str
    attempt_id: str
    promotion_id: str
    approval_id: str
    project_id: str
    project_root: str
    authorized_paths: list[str]
    initial_manifest_sha256: str
    approved_manifest_sha256: str
    proposed_manifest_sha256: str | None = None
    final_manifest_sha256: str | None = None
    lease_id: str
    lease_holder_id: str
    fencing_token: int
    stage: str = "PREPARED"
    entries: list[SandboxMutationJournalEntry] = Field(default_factory=list)
    validation_commands: list[list[str]] = Field(default_factory=list)
    validation_state: str = "PENDING"
    rollback_state: str = "NOT_REQUIRED"
    recovery_count: int = 0
    recovery_required: bool = True
    terminal: bool = False
    failure_reason: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    checkpoints: list[SandboxCheckpoint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SandboxPromotionRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX-PROMOTION"))
    project_id: str | None = None
    project_root: str | None = None
    approval_id: str
    status: str = "APPROVED"
    initial_manifest_sha256: str
    applied_manifest_sha256: str | None = None
    final_manifest_sha256: str | None = None
    validations: list[TestExecution] = Field(default_factory=list)
    rollback_validations: list[TestExecution] = Field(default_factory=list)
    rollback_verified: bool | None = None
    failure_reason: str | None = None
    lease_id: str | None = None
    fencing_token: int | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    checkpoints: list[SandboxCheckpoint] = Field(default_factory=list)
    mutation_journal: SandboxMutationJournal | None = None
    reconciliation: SandboxPromotionReconciliation | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class ImplementationSandboxAttempt(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SANDBOX"))
    ticket_id: str
    plan_record_id: str
    project_id: str
    project_root: str
    status: str = "CREATED"
    authorized_paths: list[str]
    changes: list[PatchChange] = Field(default_factory=list)
    patch_sha256: str | None = None
    validations: list[TestExecution] = Field(default_factory=list)
    validation_decisions: list[SandboxValidationDecision] = Field(default_factory=list)
    validation_evidence: list[Evidence] = Field(default_factory=list)
    validation_worker_executions: list[SandboxValidationWorkerExecution] = Field(
        default_factory=list
    )
    external_validation_reports: list[SandboxExternalValidationReport] = Field(
        default_factory=list
    )
    promotion_approval: SandboxPromotionApproval | None = None
    promotion_approval_history: list[GovernanceDecision] = Field(default_factory=list)
    promotion_approval_missing: list[str] = Field(default_factory=list)
    promotion_approval_expiration_reasons: list[str] = Field(default_factory=list)
    promotion: SandboxPromotionRecord | None = None
    checkpoints: list[SandboxCheckpoint] = Field(default_factory=list)
    worker: str
    worker_configuration: dict[str, object] = Field(default_factory=dict)
    files_read: list[str] = Field(default_factory=list)
    process_policy: dict[str, object] = Field(default_factory=dict)
    network_policy: dict[str, object] = Field(default_factory=dict)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    cost_basis: str = "Worker did not report monetary cost."
    worker_calls: int = 0
    model_calls: int = 0
    elapsed_seconds: float = 0
    initial_manifest_sha256: str
    final_manifest_sha256: str | None = None
    original_unchanged: bool = False
    filesystem_disposed: bool = False
    failure_reason: str | None = None
    execution_authorized: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    discarded_at: datetime | None = None


class WorkerRouteEstimate(BaseModel):
    route: TaskRoute
    worker: str
    sample_count: int
    success_count: int
    predicted_success_probability: float
    mean_reported_confidence: float
    calibration_error: float
    predicted_cost_usd: float
    predicted_latency_ms: float
    predicted_tokens: float
    eligible: bool
    evidence_execution_ids: list[str] = Field(default_factory=list)


class RoutePrediction(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ROUTE-PREDICTION"))
    root_task_id: str
    task_id: str
    task_category: str
    policy_version: int
    static_route: TaskRoute
    chosen_route: TaskRoute
    chosen_worker: str
    required_success_probability: float
    minimum_evidence: int
    changed_static_route: bool = False
    reason: str
    candidates: list[WorkerRouteEstimate] = Field(default_factory=list)
    fixed_safety_limits: dict[str, float | int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoutingPolicyUpdate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ROUTING-POLICY"))
    version: int
    previous_version: int
    root_task_id: str
    triggering_task_id: str
    task_category: str
    from_route: TaskRoute
    to_route: TaskRoute
    accepted: bool
    reason: str
    minimum_evidence: int
    required_success_probability: float
    evidence_execution_ids: list[str] = Field(default_factory=list)
    fixed_safety_limits: dict[str, float | int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RouteEvaluation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ROUTE-EVALUATION"))
    prediction_id: str
    task_id: str
    policy_version: int
    predicted_route: TaskRoute
    actual_final_route: TaskRoute
    predicted_success_probability: float
    actual_success: bool
    predicted_cost_usd: float
    actual_cost_usd: float
    cost_error_usd: float
    predicted_latency_ms: float
    actual_latency_ms: float
    latency_error_ms: float
    predicted_tokens: float
    actual_tokens: int
    worker_calls: int
    fallback_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PursuitResult(BaseModel):
    root_task_id: str
    tasks: list[Task]
    codex_calls: int
    status: TaskStatus
    stopping_reason: StoppingReason
    planning_run: PlanningRun | None = None


class ChatScope(StrEnum):
    SYSTEM = "SYSTEM"
    PROJECT = "PROJECT"


class ConversationReference(BaseModel):
    phrase: str
    target_id: str | None = None
    target_kind: str = "UNRESOLVED"
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.0


class ArchitectureComponent(BaseModel):
    name: str
    role: str
    paths: list[str] = Field(default_factory=list)


class ProjectArchitectureContext(BaseModel):
    project_id: str | None = None
    project_name: str
    scope: str
    components: list[ArchitectureComponent] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


class SystemSelfModel(BaseModel):
    identity_id: str = "TGRAM-SYSTEM"
    name: str = "TGRAM"
    legacy_identity_ids: list[str] = Field(default_factory=lambda: ["RLMGRAPH-SYSTEM"])
    aliases: list[str] = Field(default_factory=list)
    purpose: str
    capabilities: list[str] = Field(default_factory=list)
    authority_boundaries: list[str] = Field(default_factory=list)
    evidence_policy: str


class SystemWorkspace(BaseModel):
    """Reserved engine workspace; never an ordinary loaded project."""

    identity_id: str = "TGRAM-SYSTEM"
    name: str = "TGRAM"
    root: str
    scope: Literal["SYSTEM"] = "SYSTEM"
    purpose: str
    action_memory_path: str
    loaded_project_ids: list[str] = Field(default_factory=list)
    legacy_identity_ids: list[str] = Field(default_factory=lambda: ["RLMGRAPH-SYSTEM"])


class MemoryLayerModel(BaseModel):
    name: str
    role: str
    owns: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    persistence: str
    source_ids: list[str] = Field(default_factory=list)


class MemorySystemState(BaseModel):
    """Live, typed account of the durable system behind disposable language calls."""

    identity_id: str = "TGRAM-SYSTEM"
    identity_statement: str
    memory_is_core_state: bool = True
    language_models_are_disposable: bool = True
    interpreter_role: str
    responder_role: str
    worker_role: str
    layers: list[MemoryLayerModel] = Field(default_factory=list)
    background_flow: list[str] = Field(default_factory=list)
    live_record_counts: dict[str, int] = Field(default_factory=dict)
    current_fact_ids: list[str] = Field(default_factory=list)
    authority_boundary: str
    evidence_basis: list[str] = Field(default_factory=list)


class ConversationConcept(BaseModel):
    name: str
    meaning: str
    architecture_scope: str = "UNKNOWN"
    source_ids: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.0


class ConversationMemoryCandidate(BaseModel):
    """A user-authored memory proposed by interpretation, not inferred repository truth."""

    kind: Literal["IDENTITY", "PREFERENCE", "CONTEXT", "EPISODIC"]
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(default="is", min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=2_000)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    confidence: Annotated[float, Field(ge=0, le=1)]
    sensitivity: Literal["NORMAL", "SENSITIVE", "SECRET"] = "NORMAL"
    meaning: Literal["REPORTED", "REQUIREMENT", "PREFERENCE", "CONVENTION"] = "REPORTED"
    source_excerpt: str = Field(default="", max_length=500)
    useful_when: str = Field(default="", max_length=500)


class ConversationInterpretation(BaseModel):
    """Schema-constrained meaning extracted by a disposable language-model call."""

    speech_act: str
    primary_intent: str
    user_meaning: str
    workflow_request: str | None = None
    objective_update: str | None = None
    entities: list[str] = Field(default_factory=list)
    concept_bindings: list[ConversationConcept] = Field(default_factory=list)
    memory_candidates: list[ConversationMemoryCandidate] = Field(default_factory=list)
    references: list[ConversationReference] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    proposed_scope: str = "AUTO"
    authorization_signal: bool = False
    confidence: Annotated[float, Field(ge=0, le=1)]
    needs_clarification: bool = False
    memory_query: str | None = Field(default=None, max_length=500)


class ConversationRouteReview(BaseModel):
    """A bounded second look at meaning, using conversation evidence only."""

    intent: Literal["CONVERSE", "INVESTIGATE", "CHANGE", "CLARIFY", "VERIFY", "REPLAY"]
    user_meaning: str = Field(max_length=2000)
    requested_work_quote: str | None = Field(default=None, max_length=4000)
    source_turn_ids: list[str] = Field(default_factory=list, max_length=12)
    clarification: str | None = Field(default=None, max_length=500)


class ConversationResponse(BaseModel):
    """A conversation-only answer with no worker or repository authority."""

    answer: str = Field(min_length=1, max_length=4_000)
    used_fact_ids: list[str] = Field(default_factory=list)
    used_action_memory_ids: list[str] = Field(default_factory=list)
    used_evaluation_memory_ids: list[str] = Field(default_factory=list)
    used_operational_memory_ids: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)]


class ConversationConfusion(BaseModel):
    """A graph-generated account of why an interpretation cannot yet be used safely."""

    trigger: str
    ambiguities: list[str] = Field(default_factory=list)
    unresolved_references: list[ConversationReference] = Field(default_factory=list)
    attempted_intent: str
    attempted_scope: str
    confidence: Annotated[float, Field(ge=0, le=1)]


class ConversationRepairPatch(BaseModel):
    """A disposable interpreter's bounded correction to uncertain meaning."""

    resolved_references: list[ConversationReference] = Field(default_factory=list)
    revised_concepts: list[ConversationConcept] = Field(default_factory=list)
    revised_primary_intent: str | None = None
    revised_user_meaning: str | None = None
    revised_workflow_request: str | None = None
    revised_objective_update: str | None = None
    revised_scope: str | None = None
    remaining_ambiguities: list[str] = Field(default_factory=list)
    added_assumptions: list[str] = Field(default_factory=list)
    resolution_basis: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0, le=1)]
    needs_clarification: bool = False


class ConversationReflectionStep(BaseModel):
    pass_index: int = Field(ge=1)
    confusion: ConversationConfusion
    repair: ConversationRepairPatch | None = None
    accepted: bool = False
    acceptance_reason: str
    resulting_interpretation: ConversationInterpretation


class ConversationInterpretationRecord(BaseModel):
    """Durable hypothesis about one message; never repository truth or action authority."""

    id: str = Field(default_factory=lambda: new_id("CHAT-INTERPRETATION"))
    session_id: str
    turn_id: str | None = None
    message: str
    interpretation: ConversationInterpretation
    interpreter: str
    contract_version: str = "conversation-meaning-v1"
    fallback_used: bool = False
    reflection_steps: list[ConversationReflectionStep] = Field(default_factory=list)
    supersedes_interpretation_id: str | None = None
    confirmed: bool = False
    routing_review: ConversationRouteReview | None = None
    memory_retry_query: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationExcerpt(BaseModel):
    turn_id: str
    user_message: str
    assistant_answer: str
    interpretation_id: str | None = None


class ConversationFactKind(StrEnum):
    IDENTITY = "IDENTITY"
    OBJECTIVE = "OBJECTIVE"
    PREFERENCE = "PREFERENCE"
    CONTEXT = "CONTEXT"
    EPISODIC = "EPISODIC"


class ConversationFact(BaseModel):
    """Conversation-scoped user context; never repository evidence or worker authority."""

    id: str = Field(default_factory=lambda: new_id("CONVERSATION-FACT"))
    session_id: str
    kind: ConversationFactKind
    subject: str
    predicate: str
    value: str
    source_turn_id: str
    source_interpretation_id: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    aliases: list[str] = Field(default_factory=list, max_length=12)
    profile_memory: bool = False
    meaning: Literal["REPORTED", "REQUIREMENT", "PREFERENCE", "CONVENTION"] = "REPORTED"
    source_excerpt: str = Field(default="", max_length=500)
    useful_when: str = Field(default="", max_length=500)
    supporting_turn_ids: list[str] = Field(default_factory=list, max_length=8)
    last_confirmed_at: datetime | None = None
    supersedes_fact_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryAssociationType(StrEnum):
    SIMILAR_TO = "SIMILAR_TO"
    CONTRASTS_WITH = "CONTRASTS_WITH"
    ANALOGOUS_TO = "ANALOGOUS_TO"
    SUPERSEDES = "SUPERSEDES"


class MemoryAssociationStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    ACCEPTED = "ACCEPTED"


class MemoryAssociation(BaseModel):
    """A fallible connection inferred between durable memories, never a fact itself."""

    id: str = Field(default_factory=lambda: new_id("MEMORY-ASSOCIATION"))
    session_id: str
    source_memory_ids: list[str] = Field(min_length=2)
    relation: MemoryAssociationType
    explanation: str
    shared_pattern: str
    semantic_score: Annotated[float, Field(ge=0, le=1)]
    structural_score: Annotated[float, Field(ge=0, le=1)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    supporting_memory_ids: list[str] = Field(default_factory=list)
    conflicting_memory_ids: list[str] = Field(default_factory=list)
    status: MemoryAssociationStatus = MemoryAssociationStatus.CANDIDATE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryRelationshipInterpretation(BaseModel):
    """Typed, disposable interpretation of an association between exact memories."""

    id: str = Field(default_factory=lambda: new_id("MEMORY-RELATIONSHIP-INTERPRETATION"))
    session_id: str
    association_id: str
    source_memory_ids: list[str] = Field(min_length=2)
    relationship: MemoryAssociationType
    shared_pattern: str
    differences: list[str] = Field(default_factory=list)
    possible_abstraction: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    interpreter: str = "TypedRelationshipInterpreter"
    status: MemoryAssociationStatus = MemoryAssociationStatus.CANDIDATE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryCluster(BaseModel):
    """Recursively nestable abstraction retaining descent to its exact fact support."""

    id: str = Field(default_factory=lambda: new_id("MEMORY-CLUSTER"))
    session_id: str
    signature: str
    label: str
    defining_pattern: str
    abstraction_level: int = Field(ge=1, le=4)
    member_memory_ids: list[str] = Field(min_length=2, max_length=8)
    supporting_fact_ids: list[str] = Field(min_length=2)
    relationship_interpretation_ids: list[str] = Field(default_factory=list)
    centroid_terms: list[str] = Field(default_factory=list, max_length=16)
    confidence: Annotated[float, Field(ge=0, le=1)]
    status: MemoryAssociationStatus = MemoryAssociationStatus.CANDIDATE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConceptBranch(BaseModel):
    """A novel, provenance-linked line of thought opened from memory relationships."""

    id: str = Field(default_factory=lambda: new_id("CONCEPT-BRANCH"))
    session_id: str
    signature: str
    concept: str
    insight: str
    origin_interpretation_id: str
    supporting_fact_ids: list[str] = Field(min_length=2)
    parent_branch_id: str | None = None
    depth: int = Field(ge=1, le=4)
    status: str = "EXPLORING"
    confidence: Annotated[float, Field(ge=0, le=1)]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutonomyBudget(BaseModel):
    max_decisions_per_session: int = Field(default=8, ge=1, le=64)
    max_candidates_per_cycle: int = Field(default=8, ge=1, le=8)
    max_inquiries_per_cycle: int = Field(default=1, ge=1, le=1)
    minimum_branch_confidence: Annotated[float, Field(ge=0, le=1)] = .35
    maximum_branch_depth: int = Field(default=4, ge=1, le=4)


class AutonomousCandidateScore(BaseModel):
    branch_id: str
    novelty: Annotated[float, Field(ge=0, le=1)]
    uncertainty: Annotated[float, Field(ge=0, le=1)]
    relevance: Annotated[float, Field(ge=0, le=1)]
    expected_information_gain: Annotated[float, Field(ge=0, le=1)]
    estimated_cost: Annotated[float, Field(ge=0, le=1)]
    total: Annotated[float, Field(ge=0, le=1)]


class AutonomousDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("AUTONOMOUS-DECISION"))
    session_id: str
    candidates: list[AutonomousCandidateScore] = Field(default_factory=list, max_length=8)
    selected_branch_id: str | None = None
    inquiry_id: str | None = None
    reason: str
    budget: AutonomyBudget
    status: str = "SELECTED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutonomousInquiry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("AUTONOMOUS-INQUIRY"))
    session_id: str
    decision_id: str
    branch_id: str
    question: str
    expected_information_gain: Annotated[float, Field(ge=0, le=1)]
    authorization: str = "READ_ONLY_INVESTIGATION"
    status: str = "PENDING"
    work_request_id: str | None = None
    work_result_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConceptBranchOutcome(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CONCEPT-BRANCH-OUTCOME"))
    session_id: str
    branch_id: str
    inquiry_id: str
    work_result_id: str
    claim_ids: list[str] = Field(default_factory=list)
    status: str
    summary: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutonomousWorkPolicy(BaseModel):
    session_id: str
    enabled: bool = False
    max_tasks_per_session: int = Field(default=3, ge=1, le=8)
    allow_draft_tickets: bool = True
    allow_read_only_diagnostics: bool = True
    allow_proposed_plans: bool = True
    allow_source_writes: bool = False
    allow_self_approval: bool = False
    enabled_by: str | None = None
    enabled_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutonomousTaskPlan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("AUTONOMOUS-TASK-PLAN"))
    session_id: str
    autonomous_task_id: str
    ticket_id: str
    objective: str
    steps: list[str] = Field(min_length=1, max_length=8)
    baseline_checks: list[str] = Field(default_factory=list, max_length=8)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    source_claim_ids: list[str] = Field(default_factory=list)
    status: str = "PROPOSED_REQUIRES_USER_APPROVAL"
    approval_granted: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutonomousTask(BaseModel):
    id: str = Field(default_factory=lambda: new_id("AUTONOMOUS-TASK"))
    session_id: str
    branch_id: str
    outcome_id: str
    title: str
    objective: str
    priority: str = "MEDIUM"
    status: str = "PREPARING"
    ticket_id: str | None = None
    plan_id: str | None = None
    blocker: str | None = None
    authority: str = "DRAFT_TICKET_AND_PROPOSED_PLAN_ONLY"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeductivePremise(BaseModel):
    source_id: str
    source_kind: str
    statement: str
    confidence: Annotated[float, Field(ge=0, le=1)]


class DeductiveTheory(BaseModel):
    """A durable conclusion derived from explicit premises, never promoted directly to fact."""

    id: str = Field(default_factory=lambda: new_id("DEDUCTIVE-THEORY"))
    session_id: str
    subject: str
    premises: list[DeductivePremise] = Field(min_length=1, max_length=16)
    inference_rule: str
    conclusion: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    falsifiers: list[str] = Field(default_factory=list, max_length=8)
    source_claim_ids: list[str] = Field(default_factory=list)
    status: str = "ACTIVE_THEORY"
    supersedes_theory_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WeaknessCandidate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("WEAKNESS-CANDIDATE"))
    category: str
    description: str
    theory_id: str
    evidence_strength: Annotated[float, Field(ge=0, le=1)]
    impact: Annotated[float, Field(ge=0, le=1)]
    recurrence: Annotated[float, Field(ge=0, le=1)]
    unresolvedness: Annotated[float, Field(ge=0, le=1)]
    severity: Annotated[float, Field(ge=0, le=1)]


class SelfAssessmentReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("SELF-ASSESSMENT-REPORT"))
    session_id: str
    work_result_id: str
    source_claim_ids: list[str] = Field(default_factory=list)
    candidates: list[WeaknessCandidate] = Field(min_length=1, max_length=8)
    selected_candidate_id: str
    conclusion: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    reasoning_method: str = "EXPLICIT_DEDUCTIVE_RANKING_V1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NeuralMemoryScore(BaseModel):
    """Inspectable shadow score from the learned memory-routing network."""

    memory_id: str
    memory_kind: str
    deterministic_score: float
    neural_score: Annotated[float, Field(ge=0, le=1)]
    selected: bool = False
    model_version: str = "memory-ranker-mlp-v1"


class NeuralMemoryState(BaseModel):
    model_version: str = "memory-ranker-mlp-v1"
    mode: str = "SHADOW"
    training_examples: int = 0
    outcome_examples: int = 0
    rolling_loss: float = 0.0
    top_k_agreement: float = 0.0
    ready_for_evaluation: bool = False
    assisted_recall_enabled: bool = False
    rescued_memory_ids: list[str] = Field(default_factory=list, max_length=2)


class ConversationActionMemory(BaseModel):
    """A bounded, read-only project change memory exposed to conversation."""

    project_id: str
    project_name: str
    project_root: str
    memory_id: str
    milestone: int
    phase: str
    action: str
    invariant: str
    files: list[str] = Field(default_factory=list, max_length=12)
    symbols: list[str] = Field(default_factory=list, max_length=12)
    confidence: Annotated[float, Field(ge=0, le=1)]
    archive_ref: str = ""
    relevance: float = 0.0


class SystemEvaluationMemory(BaseModel):
    """Durable evidence about an evaluation TGRAM underwent."""

    id: str = Field(default_factory=lambda: new_id("SYSTEM-EVALUATION"))
    system_id: str = "TGRAM-SYSTEM"
    evaluation_type: str
    suite_id: str
    title: str
    summary: str
    verdict: str
    evidence_eligible: bool
    models: list[str] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | bool | str | None] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_report_path: str
    invalidates_evaluation_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationOperationalMemory(BaseModel):
    """A bounded typed reference to non-conversational memory."""

    memory_id: str
    memory_type: str
    scope: str
    project_id: str | None = None
    title: str
    summary: str
    status: str = "CURRENT"
    confidence: Annotated[float, Field(ge=0, le=1)] = 1.0
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    details: dict[str, object] = Field(default_factory=dict)
    relevance: float = 0.0


class ConversationMemoryProjection(BaseModel):
    latency_observations: dict[str, object] = Field(default_factory=dict)
    relevant_lessons: list[dict[str, object]] = Field(default_factory=list)
    relevant_world_memories: list[dict[str, object]] = Field(default_factory=list)
    world_neural_state: dict[str, object] = Field(default_factory=dict)
    """Retrieved semantic and verbatim conversation state for the next turn."""

    session_id: str
    semantic_summary: str = "No prior semantic conversation state."
    active_objective: str | None = None
    pending_workflow_request: str | None = None
    relevant_turn_ids: list[str] = Field(default_factory=list)
    relevant_interpretation_ids: list[str] = Field(default_factory=list)
    relevant_claim_ids: list[str] = Field(default_factory=list)
    relevant_facts: list[ConversationFact] = Field(default_factory=list)
    relevant_profile_memories: list[ConversationFact] = Field(default_factory=list)
    relevant_action_memories: list[ConversationActionMemory] = Field(default_factory=list)
    relevant_evaluation_memories: list[SystemEvaluationMemory] = Field(default_factory=list)
    relevant_operational_memories: list[ConversationOperationalMemory] = Field(
        default_factory=list
    )
    relevant_associations: list[MemoryAssociation] = Field(default_factory=list)
    relevant_relationship_interpretations: list[MemoryRelationshipInterpretation] = Field(
        default_factory=list
    )
    relevant_memory_clusters: list[MemoryCluster] = Field(default_factory=list)
    relevant_concept_branches: list[ConceptBranch] = Field(default_factory=list)
    relevant_theories: list[DeductiveTheory] = Field(default_factory=list)
    recent_self_assessments: list[SelfAssessmentReport] = Field(default_factory=list)
    neural_memory_scores: list[NeuralMemoryScore] = Field(default_factory=list)
    neural_memory_state: NeuralMemoryState | None = None
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    verbatim_turns: list[ConversationExcerpt] = Field(default_factory=list)
    architecture_contexts: list[ProjectArchitectureContext] = Field(default_factory=list)
    system_self: SystemSelfModel | None = None
    system_workspace: SystemWorkspace | None = None
    memory_system: MemorySystemState | None = None
    remembered_concepts: list[ConversationConcept] = Field(default_factory=list)
    reflection_history: list[ConversationReflectionStep] = Field(default_factory=list)
    token_estimate: int = 0


class ConversationWorkRequest(BaseModel):
    """Auditable, read-only handoff from conversation into worker investigation."""

    id: str = Field(default_factory=lambda: new_id("CONVERSATION-WORK-REQUEST"))
    session_id: str
    source_interpretation_id: str
    exact_user_prompt: str
    objective: str
    scope: ChatScope
    project_id: str | None = None
    authorization: str = "READ_ONLY_INVESTIGATION"
    conversation_fact_ids: list[str] = Field(default_factory=list)
    deductive_theory_ids: list[str] = Field(default_factory=list)
    self_assessment_report_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    status: str = "SUBMITTED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationWorkResult(BaseModel):
    """Evidence-linked worker output returned through the conversation bridge."""

    id: str = Field(default_factory=lambda: new_id("CONVERSATION-WORK-RESULT"))
    request_id: str
    session_id: str
    task_id: str
    claim_ids: list[str] = Field(default_factory=list)
    answer_summary: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    unresolved_questions: list[str] = Field(default_factory=list)
    worker_trace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SelfImprovementProposal(BaseModel):
    """User-reviewable proposal derived from a self-investigation, with no execution authority."""

    id: str = Field(default_factory=lambda: new_id("SELF-IMPROVEMENT-PROPOSAL"))
    session_id: str
    work_request_id: str
    work_result_id: str
    source_claim_ids: list[str]
    originating_prompt: str
    title: str
    objective: str
    acceptance_criteria: list[str]
    constraints: list[str] = Field(default_factory=list)
    status: str = "DRAFT"
    accepted_by: str | None = None
    acceptance_reason: str | None = None
    ticket_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatTurn(BaseModel):
    """One immutable, typed exchange anchored to its exact graph claim when applicable."""

    id: str = Field(default_factory=lambda: new_id("CHAT-TURN"))
    session_id: str
    ordinal: int = Field(ge=1)
    user_message: str
    answer: str
    scope: ChatScope
    route: str
    intent: str = "INVESTIGATE"
    intent_confidence: Annotated[float, Field(ge=0, le=1)] = 1.0
    intent_rationale: str = ""
    interpretation_id: str | None = None
    interpretation_fallback: bool = False
    routing_confidence: Annotated[float, Field(ge=0, le=1)]
    routing_reason: str = ""
    investigation_mode: str = "DIRECT"
    claim_confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    project_id: str | None = None
    ticket_id: str | None = None
    task_id: str | None = None
    claim_id: str | None = None
    project_fingerprint: str | None = None
    parent_turn_id: str | None = None
    context_turn_ids: list[str] = Field(default_factory=list)
    context_claim_ids: list[str] = Field(default_factory=list)
    context_token_estimate: int = 0
    conversation_memory_receipt: dict[str, object] | None = None
    superseded_by_turn_id: str | None = None
    reuse_kind: str | None = None
    authority: str = "READ_ONLY_CHAT_NO_WRITE_AUTHORITY"
    evidence: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatSession(BaseModel):
    id: str = Field(default_factory=lambda: new_id("CHAT-SESSION"))
    title: str = "New investigation"
    project_id: str | None = None
    ticket_id: str | None = None
    profile_id: str = "LOCAL-LEGACY"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
