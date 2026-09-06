"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ConversationMemory, ResponseMemory, shareConversationFact, type SavedConversation, type MemoryReceipt } from "./conversation-memory";
import { LearningLibrary } from "./learning-library";

import { TicketNextStep } from "./ticket-next-step";
import { FileChangePreview } from "./file-change-preview";

type Evidence = { path: string; detail: string; line: number | null };
type ChatActivity = {
  label: string;
  detail: string;
  status: "ACTIVE" | "COMPLETE" | "FAILED";
};
type ModelRole = {
  role: string; label: string; description: string; providers: string[];
  provider: string; model: string; base_url: string; api_key_environment: string;
};
type ModelSettings = {
  available_models: string[];
  providers: Record<string, string>;
  roles: ModelRole[];
  storage_path: string;
  api_keys_are_persisted: boolean;
};
type MachineProfile = {
  id: string; name: string;
  response_style: "CONCISE" | "BALANCED" | "DETAILED";
  owns_legacy_memory: boolean; created_at: string;
};
type ProfileSession = { profile: MachineProfile; token: string };
type ChatMessage = {
  turnId?: string;
  userMessage?: string;
  ticketId?: string;
  projectId?: string;
  memoryReceipt?: MemoryReceipt | null;
  role: "user" | "assistant";
  content: string;
  route?: string;
  metrics?: Record<string, number | null>;
  confidence?: number;
  routingConfidence?: number;
  routingReason?: string;
  operationRoute?: string;
  scope?: string;
  taskId?: string;
  claimId?: string;
  evidence?: Array<Record<string, unknown>>;
  taskTree?: Array<{
    id: string;
    parent_task_id?: string | null;
    question: string;
    depth: number;
    status: string;
    route?: string | null;
    reused_claim_id?: string | null;
    stopping_reason?: string | null;
  }>;
  planningQuestions?: string[];
  contradictions?: Array<Record<string, unknown>>;
  investigationCalls?: number;
  budgetExhausted?: boolean;
  investigationMode?: string;
  contextClaimIds?: string[];
  contextTokenEstimate?: number;
  workProjectId?: string;
};
type SourceFile = {
  path: string;
  content_hash: string;
  evidence_lines: number[];
};
type ValidityEvent = {
  status: string;
  project_fingerprint: string;
  reason: string;
  observed_at: string;
};
type TierTransition = {
  from_tier: string | null;
  to_tier: string;
  reason: string;
  policy_decision_id: string | null;
  transitioned_at: string;
};
type BenchmarkOutcome = {
  answer: string;
  correct: boolean;
  evidence_complete: boolean;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  wall_time_ms: number;
  context_node_ids: string[];
  accessed_evidence_ids: string[];
  duplicate_retrievals: number;
};
type WorkerEstimate = {
  route: string;
  worker: string;
  sample_count: number;
  success_count: number;
  predicted_success_probability: number;
  mean_reported_confidence: number;
  calibration_error: number;
  predicted_cost_usd: number;
  predicted_latency_ms: number;
  predicted_tokens: number;
  eligible: boolean;
  evidence_execution_ids: string[];
};
type FileChange = {
  change_reason?: string | null;
  before_hash?: string;
  after_hash?: string;
  unified_diff?: string;
  kind: string;
  path: string;
  previous_path: string | null;
  content_hash: string | null;
  previous_hash: string | null;
};
type PatchChange = {
  change_reason?: string | null;
  path: string;
  before_hash: string;
  after_hash: string;
  unified_diff: string;
};
type TestExecution = {
  command: string[];
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
};
type GraphEvent = {
  status?: string;
  kind?: string;
  holder_id?: string;
  workflow_id?: string | null;
  detail: string;
  occurred_at: string;
  artifact_ids?: string[];
};
type EvaluationResult = {
  id: string;
  case_id: string;
  repetition: number;
  scenario: string;
  strategy: string;
  contract_type?: string | null;
  answer: string;
  expected_answer: string;
  correct: boolean;
  evidence_complete: boolean;
  worker_calls: number;
  resolution_calls?: number;
  model_calls: number;
  retrieved_tokens: number;
  retrieval_size?: number;
  latency_ms: number;
  observed_latency_ms: number;
  duplicate_investigations: number;
  memory_reuses: number;
  conflict_resolved?: boolean | null;
  recovery_succeeded?: boolean | null;
  source_integrity_verified?: boolean | null;
  abstained?: boolean;
  expected_abstention?: boolean;
  required_evidence_paths?: string[];
  required_evidence_terms?: string[];
  observed_evidence_paths?: string[];
  observed_evidence_terms?: string[];
  task_id?: string | null;
  verdict_id?: string | null;
  retrieved_claim_ids: string[];
  required_evidence_ids: string[];
  notes: string[];
};
type GraphNode = {
  path?: string;
  dependency_paths?: string[];
  exact_reuse_preserved?: boolean;
  resumable_recovery_verified?: boolean;
  id: string;
  node_type:
    | "task"
    | "claim"
    | "attempt"
    | "cluster"
    | "conflict_verdict"
    | "reconstruction"
    | "reconstruction_step"
    | "promotion"
    | "benchmark"
    | "pathway"
    | "pathway_decision"
    | "pathway_benchmark"
    | "plan_decision"
    | "planning_run"
    | "execution_attempt"
    | "route_prediction"
    | "routing_policy_update"
    | "route_evaluation"
    | "project"
    | "project_scan"
    | "project_file"
    | "project_symbol"
    | "project_test"
    | "project_dependency"
    | "repair_proposal"
    | "repair_validation"
    | "repair_approval"
    | "repair_promotion"
    | "post_repair_reconciliation"
    | "maintenance_workflow"
    | "project_lease"
    | "evaluation_run"
    | "evaluation_result"
    | "codex_readonly_proof"
    | "recursive_codex_proof"
    | "generic_codex_evaluation"
    | "investigation_session"
    | "resumable_session_evaluation"
    | "unreal_index_scan"
    | "unreal_artifact"
    | "unreal_dependency"
    | "project_workspace_result"
    | "ticket"
    | "ticket_event"
    | "ticket_validation"
    | "implementation_sandbox";
  kind: string;
  title: string;
  status: string;
  depth?: number;
  parent_id?: string | null;
  attempt_count?: number;
  reused_claim_id?: string | null;
  reuse_type?: string | null;
  relevance_score?: number | null;
  reuse_reason?: string | null;
  stopping_reason?: string | null;
  last_error?: string | null;
  confidence?: number;
  conclusion?: string;
  producer?: string;
  evidence?: Evidence[];
  files?: string[];
  project_root?: string;
  assertions?: { key: string; value: string }[];
  selected_claim?: string;
  rationale?: string;
  unresolved_questions?: string[];
  created_at?: string;
  interpretations?: {
    value: string;
    normalized_value: string;
    claim_ids: string[];
  }[];
  corroborated_claim_ids?: string[];
  outlier_claim_ids?: string[];
  selected_value?: string;
  claim_ids?: string[];
  supporting_claim_ids?: string[];
  contradicting_claim_ids?: string[];
  evidence_claim_ids?: string[];
  resolver_attempt_id?: string;
  confidence_threshold?: number;
  max_resolution_attempts?: number;
  conflict_verdict_id?: string | null;
  reused_verdict_id?: string | null;
  source_task_id?: string;
  source_claim_ids?: string[];
  source_files?: SourceFile[];
  source_commit?: string | null;
  learned_at?: string;
  valid_from?: string;
  valid_until?: string | null;
  validity_reason?: string;
  validity_history?: ValidityEvent[];
  superseded_by_claim_id?: string | null;
  seed_node_ids?: string[];
  selected_node_ids?: string[];
  pruned_node_ids?: string[];
  baseline_node_ids?: string[];
  reconstructed_tokens?: number;
  baseline_tokens?: number;
  required_evidence_ids?: string[];
  evidence_preserved?: boolean | null;
  sequence?: number;
  action?: string;
  claim_id?: string;
  frontier_node_id?: string | null;
  relation?: string | null;
  score?: number;
  reason?: string;
  token_estimate?: number;
  memory_tier?: string;
  memory_lifecycle?: string;
  tier_history?: TierTransition[];
  promoted_to_claim_id?: string | null;
  successful_reuse_count?: number;
  memory_policy_decision_id?: string | null;
  assertion_key?: string;
  from_tier?: string;
  to_tier?: string;
  candidate_claim_ids?: string[];
  accepted_claim_ids?: string[];
  rejected_claim_ids?: string[];
  contradictory_claim_ids?: string[];
  stale_claim_ids?: string[];
  promoted_claim_id?: string | null;
  policy_version?: string | number;
  minimum_support?: number;
  minimum_confidence?: number;
  observed_support?: number;
  observed_confidence?: number;
  case_id?: string;
  expected_answer?: string;
  fixed?: BenchmarkOutcome;
  active?: BenchmarkOutcome;
  traversal_node_ids?: string[];
  traversal_edges?: Edge[];
  token_reduction?: number;
  correctness_preserved?: boolean;
  benchmark_evidence_preserved?: boolean;
  token?: string;
  version?: number;
  signature?: string;
  node_ids?: string[];
  child_tokens?: string[];
  supporting_task_ids?: string[];
  supporting_reconstruction_ids?: string[];
  access_frequency?: number;
  average_tokens_saved?: number;
  stability?: number;
  lifecycle?: string;
  policy_decision_id?: string;
  candidate_reconstruction_ids?: string[];
  candidate_task_ids?: string[];
  candidate_node_ids?: string[];
  minimum_frequency?: number;
  minimum_tokens_saved?: number;
  minimum_stability?: number;
  observed_frequency?: number;
  observed_average_tokens_saved?: number;
  observed_stability?: number;
  pathway_id?: string;
  active_input_tokens?: number;
  token_input_tokens?: number;
  additional_reduction?: number;
  correct?: boolean;
  expansion_complete?: boolean;
  priority?: string | number;
  uncertainty?: number;
  difficulty?: number;
  route?: string;
  dependency_task_ids?: string[];
  task_id?: string | null;
  model_calls_used?: number;
  retrieval_tokens_used?: number;
  duplicate_investigations?: number;
  elapsed_seconds?: number;
  max_model_calls?: number;
  max_retrieval_tokens?: number;
  max_depth?: number;
  max_duplicate_investigations?: number;
  max_wall_time_seconds?: number;
  planned_route?: string;
  actual_route?: string;
  worker?: string;
  outcome?: string;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  estimated_cost_usd?: number;
  latency_ms?: number;
  fallback_from_attempt_id?: string | null;
  fallback_reason?: string | null;
  error?: string | null;
  static_route?: string;
  chosen_route?: string;
  chosen_worker?: string;
  required_success_probability?: number;
  minimum_evidence?: number;
  changed_static_route?: boolean;
  candidates?: WorkerEstimate[];
  fixed_safety_limits?: Record<string, number>;
  previous_version?: number;
  from_route?: string;
  to_route?: string;
  accepted?: boolean;
  evidence_execution_ids?: string[];
  prediction_id?: string;
  predicted_route?: string;
  actual_final_route?: string;
  predicted_success_probability?: number;
  actual_success?: boolean;
  predicted_cost_usd?: number;
  actual_cost_usd?: number;
  cost_error_usd?: number;
  predicted_latency_ms?: number;
  actual_latency_ms?: number;
  latency_error_ms?: number;
  predicted_tokens?: number;
  actual_tokens?: number;
  worker_calls?: number;
  fallback_count?: number;
  root?: string;
  explicitly_selected?: boolean;
  read_only?: boolean;
  latest_scan_id?: string;
  previous_scan_id?: string | null;
  changes?: (FileChange | PatchChange)[];
  file_count?: number;
  symbol_count?: number;
  test_count?: number;
  dependency_count?: number;
  parsed_file_count?: number;
  content_read_file_count?: number;
  reused_file_ids?: string[];
  invalidated_claim_ids?: string[];
  model_calls?: number;
  read_only_verified?: boolean;
  size_bytes?: number;
  language?: string;
  is_test?: boolean;
  content_hash?: string;
  last_scan_id?: string;
  file_id?: string;
  source_path?: string;
  source_content_hash?: string;
  name?: string;
  qualified_name?: string;
  line?: number;
  framework?: string;
  import_name?: string;
  target_file_id?: string | null;
  repair_task_id?: string;
  diagnosis_task_id?: string;
  diagnosis_claim_id?: string;
  test_path?: string;
  authorized_paths?: string[];
  proposal_id?: string;
  validation_id?: string;
  sandbox_validation_id?: string;
  approval_id?: string;
  promotion_id?: string;
  reconciliation_id?: string;
  attempt?: number;
  before?: TestExecution;
  after?: TestExecution;
  original_unchanged?: boolean;
  failure_reason?: string | null;
  decision?: string;
  approved_by?: string;
  source_tree_fingerprint?: string;
  original_tree_fingerprint?: string;
  initial_project_fingerprint?: string;
  applied_tree_fingerprint?: string | null;
  final_validation?: TestExecution | null;
  rollback_tree_fingerprint?: string | null;
  rollback_validation?: TestExecution | null;
  rollback_verified?: boolean | null;
  events?: GraphEvent[];
  completed_at?: string | null;
  previous_project_fingerprint?: string;
  new_project_fingerprint?: string;
  scan_id?: string;
  affected_paths?: string[];
  parsed_paths?: string[];
  superseded_claim_ids?: string[];
  replacement_claim_id?: string;
  follow_up_task_id?: string;
  follow_up_claim_id?: string;
  follow_up_reuse_type?: string;
  follow_up_worker_calls?: number;
  diagnosis_worker_calls?: number;
  repair_worker_calls?: number;
  repair_model_calls?: number;
  promotion_attempts?: number;
  holder_id?: string;
  workflow_id?: string | null;
  fencing_token?: number;
  acquired_at?: string;
  renewed_at?: string;
  expires_at?: string;
  released_at?: string | null;
  suite_version?: string;
  repetitions?: number;
  results?: EvaluationResult[];
  fewer_repeat_worker_calls?: boolean;
  fewer_tokens_than_static?: boolean;
  stale_or_conflicting_memory_blocked?: boolean;
  recovery_verified?: boolean;
  reproducible?: boolean;
  passed?: boolean;
  exact_replays_zero_calls?: boolean;
  abstention_verified?: boolean;
  source_integrity_verified?: boolean;
  no_project_write_capability?: boolean;
  case_contract_count?: number;
  subsystem_count?: number;
  initial_manifest_sha256?: string | null;
  final_manifest_sha256?: string | null;
  repetition?: number;
  scenario?: string;
  strategy?: string;
  contract_type?: string | null;
  answer?: string;
  evidence_complete?: boolean;
  resolution_calls?: number;
  retrieved_tokens?: number;
  retrieval_size?: number;
  observed_latency_ms?: number;
  memory_reuses?: number;
  conflict_resolved?: boolean | null;
  recovery_succeeded?: boolean | null;
  abstained?: boolean;
  expected_abstention?: boolean;
  required_evidence_paths?: string[];
  required_evidence_terms?: string[];
  observed_evidence_paths?: string[];
  observed_evidence_terms?: string[];
  verdict_id?: string | null;
  retrieved_claim_ids?: string[];
  notes?: string[];
  max_codex_calls?: number;
  max_context_tokens?: number;
  max_result_tokens?: number;
  sandbox?: string;
  initial_task_id?: string;
  initial_claim_id?: string;
  initial_execution_id?: string;
  replay_task_id?: string;
  replay_execution_id?: string;
  initial_codex_calls?: number;
  replay_codex_calls?: number;
  cost_basis?: string;
  files_examined?: string[];
  structured_result_validated?: boolean;
  evidence_contract_met?: boolean;
  access_scope_verified?: boolean;
  no_project_write_attempt?: boolean;
  no_repair_capability?: boolean;
  exact_replay_zero_calls?: boolean;
  root_question?: string;
  root_task_id?: string;
  branch_results?: {
    branch_id: string;
    name: string;
    task_id: string;
    authorized_paths: string[];
    max_codex_calls: number;
    max_wall_time_seconds: number;
    max_context_tokens: number;
    max_result_tokens: number;
    codex_calls: number;
    input_tokens: number;
    output_tokens: number;
    latency_ms: number;
    conclusion: string;
    confidence: number;
    evidence: Evidence[];
    unresolved_questions: string[];
    branch_contract_met: boolean;
    safety_decision: string;
    selection_reason: string;
    dependency_distance: number;
  }[];
  synthesis_task_id?: string;
  final_claim_id?: string;
  final_answer?: string;
  final_confidence?: number;
  final_evidence?: Evidence[];
  agreements?: { assertion_key: string; value: string; claim_ids: string[] }[];
  contradictions?: {
    assertion_key: string;
    values: Record<string, string[]>;
  }[];
  follow_up_created?: boolean;
  follow_up_reason?: string | null;
  follow_up_codex_calls?: number;
  replay_root_task_id?: string;
  replay_branch_task_ids?: string[];
  replay_resolution_calls?: number;
  hierarchy_persisted?: boolean;
  dependencies_persisted?: boolean;
  provenance_persisted?: boolean;
  safety_decisions_persisted?: boolean;
  mutation_rejection_verified?: boolean;
  plan_generated?: boolean;
  planning_algorithm?: string;
  candidate_paths?: string[];
  selected_paths?: string[];
  excluded_paths?: string[];
  abstention_reason?: string | null;
  cases?: {
    case_id: string;
    subsystem: string;
    question: string;
    test_path: string;
    proof_id: string;
    selected_paths: string[];
    initial_codex_calls: number;
    initial_input_tokens: number;
    initial_output_tokens: number;
    initial_latency_ms: number;
    replay_codex_calls: number;
    replay_resolution_calls: number;
    evidence_contract_met: boolean;
    abstained: boolean;
    source_integrity_verified: boolean;
    passed: boolean;
  }[];
  initial_input_tokens?: number;
  initial_output_tokens?: number;
  initial_latency_ms?: number;
  semantic_reuse_enabled?: boolean;
  semantic_match_question?: string | null;
  semantic_match_score?: number;
  reused_claim_ids?: string[];
  rejected_reuse_claims?: { claim_id: string; path: string; reason: string }[];
  uncovered_paths?: string[];
  remaining_worker_calls?: number;
  fresh_baseline_codex_calls?: number;
  fresh_baseline_input_tokens?: number;
  fresh_baseline_latency_ms?: number;
  semantic_reuse_verified?: boolean;
  fresh_codex_calls?: number;
  reuse_codex_calls?: number;
  fresh_input_tokens?: number;
  reuse_input_tokens?: number;
  fresh_latency_ms?: number;
  reuse_latency_ms?: number;
  stale_reuse_blocked?: boolean;
  contradiction_reuse_blocked?: boolean;
  weak_relevance_blocked?: boolean;
  active_stage?: string;
  remaining_tasks?: string[];
  checkpoints?: {
    detail?: string;
    occurred_at?: string;
    id: string;
    sequence: number;
    stage: string;
    completed_paths: string[];
    codex_calls_spent: number;
    input_tokens_spent: number;
    latency_ms_spent: number;
    safety_decisions: string[];
    created_at: string;
  }[];
  recovered?: boolean;
  recovery_count?: number;
  recovered_checkpoint_ids?: string[];
  invalidation_reasons?: string[];
  avoided_codex_calls?: number;
  avoided_input_tokens?: number;
  avoided_latency_ms?: number;
  final_proof_id?: string | null;
  lease_expires_at?: string;
  budgets_preserved?: boolean;
  semantic_reuse_preserved?: boolean;
  planning_recovery_verified?: boolean;
  delegation_recovery_verified?: boolean;
  conflict_recovery_verified?: boolean;
  synthesis_recovery_verified?: boolean;
  stale_provenance_rejected?: boolean;
  stale_lease_rejected?: boolean;
  artifact_count?: number;
  kind_counts?: Record<string, number>;
  parsed_artifact_count?: number;
  reused_artifact_count?: number;
  scope_name?: string;
  project_launched?: boolean;
  project_compiled?: boolean;
  generated_files?: number;
  package_path?: string | null;
  module_name?: string | null;
  plugin_name?: string | null;
  class_names?: string[];
  asset_class?: string | null;
  blueprint_generated_class?: string | null;
  metadata_terms?: string[];
  binary_metadata_only?: boolean;
  source_artifact_id?: string;
  target_reference?: string;
  target_artifact_id?: string | null;
  question?: string;
  subsystem?: string;
  seed_artifact_ids?: string[];
  retrieval_artifact_ids?: string[];
  retrieval_paths?: string[];
  traversed_dependency_ids?: string[];
  exact_reused_proof_id?: string | null;
  semantic_reused_proof_id?: string | null;
  reused_artifact_ids?: string[];
  rejected_reuse_reasons?: string[];
  investigation_calls?: number;
  resumed_session_id?: string | null;
  artifact_kind_counts?: Record<string, number>;
  exact_reuse_verified?: boolean;
  stale_index_rejection_verified?: boolean;
  project_not_launched?: boolean;
  project_not_compiled?: boolean;
  no_generated_files?: boolean;
  evidence_contracts_preserved?: boolean;
  proof_ids?: string[];
  request_id?: string;
  request?: string;
  requested_by?: string;
  acceptance_criteria?: string[];
  manifest_sha256?: string;
  index_scan_id?: string;
  affected_artifact_ids?: string[];
  impact_by_kind?: Record<string, string[]>;
  dependent_systems?: string[];
  steps?: {
    order: number;
    title: string;
    description: string;
    affected_artifact_ids: string[];
    validation_requirement_ids: string[];
  }[];
  risks?: {
    id: string;
    severity: string;
    summary: string;
    mitigation: string;
    artifact_ids: string[];
  }[];
  validation_requirements?: {
    id: string;
    category: string;
    description: string;
    required: boolean;
    command?: string | null;
    requires_unreal_editor: boolean;
  }[];
  approval_required?: boolean;
  approval_status?: string;
  execution_authorized?: boolean;
  stale_evidence_rejected?: boolean;
  stale_evidence_rejection_verified?: boolean;
  plan_id?: string;
  decided_by?: string;
  evidence_current?: boolean;
  representative_request_count?: number;
  evidence_backed_impacts_verified?: boolean;
  dependency_traversal_verified?: boolean;
  risks_verified?: boolean;
  validation_requirements_verified?: boolean;
  approval_gates_verified?: boolean;
  project_id?: string;
  project_name?: string;
  prompt?: string;
  affected_file_ids?: string[];
  impact_groups?: Record<string, string[]>;
  indexed_manifest_sha256?: string;
  source_result_id?: string | null;
  workspace_steps?: string[];
  workspace_risks?: string[];
  workspace_validations?: string[];
  ticket_id?: string | null;
  description?: string;
  dependency_ticket_ids?: string[];
  approval_history?: GovernanceDecision[];
  approval_missing?: string[];
  approval_expiration_reasons?: string[];
  promotion_approval_history?: GovernanceDecision[];
  promotion_approval_missing?: string[];
  promotion_approval_expiration_reasons?: string[];
  ticket_criteria?: {
    id: string;
    description: string;
    status: string;
    evidence_ids: string[];
    waiver_reason?: string | null;
    blocker_reason?: string | null;
    resolved_by?: string | null;
  }[];
  closure_ready?: boolean;
  closure_failures?: string[];
  closure_gates?: {
    criterion_id: string;
    description: string;
    status: string;
    resolved: boolean;
    explanation: string;
    resolved_by?: string | null;
    evidence_assessments: {
      evidence_id: string;
      artifact_type: string;
      eligible: boolean;
      reason: string;
      status?: string | null;
    }[];
  }[];
  eligible_ticket_evidence?: {
    evidence_id: string;
    artifact_type: string;
    eligible: boolean;
    reason: string;
    status?: string | null;
  }[];
  ineligible_ticket_evidence?: {
    evidence_id: string;
    artifact_type: string;
    eligible: boolean;
    reason: string;
    status?: string | null;
  }[];
  ticket_constraints?: { id: string; description: string }[];
  ticket_budget?: {
    max_tokens: number;
    max_model_calls: number;
    max_worker_calls: number;
    max_wall_time_seconds: number;
    max_branch_depth: number;
  };
  ticket_usage?: {
    tokens: number;
    model_calls: number;
    worker_calls: number;
    wall_time_seconds: number;
    deepest_branch: number;
  };
  plan_record_id?: string;
  patch_sha256?: string | null;
  filesystem_disposed?: boolean;
  validations?: {
    command: string[];
    exit_code: number;
    stdout: string;
    stderr: string;
    duration_ms: number;
  }[];
  validation_decisions?: {
    id: string;
    path: string;
    artifact_kind: string;
    category: string;
    requirement: string;
    status: string;
    requires_unreal_editor: boolean;
    execution_index: number | null;
    evidence: Evidence[];
    satisfied_by?: string | null;
    satisfied_at?: string | null;
    attestation_history?: GovernanceDecision[];
    attestation_missing?: string[];
  }[];
  validation_evidence?: Evidence[];
  validation_worker_executions?: {
    id: string;
    worker_name: string;
    category: string;
    artifact_kind: string;
    path: string;
    authorization_status: string;
    command: string[];
    status: string;
    exit_code?: number | null;
    duration_ms: number;
    observed_processes: number;
    peak_memory_bytes: number;
    output_bytes: number;
    cost_usd: number;
    failure_reason?: string | null;
    limits: {
      max_wall_time_seconds: number;
      max_processes: number;
      max_memory_bytes: number;
      max_output_bytes: number;
      allowed_paths: string[];
      allowed_artifact_kinds: string[];
      allowed_executables: string[];
      allowed_argument_templates: string[][];
    };
    evidence: Evidence[];
  }[];
  external_validation_reports?: {
    id: string;
    report_kind: string;
    artifact_path: string;
    report_sha256: string;
    status: string;
    detail: string;
    recorded_by: string;
    evidence: Evidence[];
  }[];
  promotion_approval?: {
    id: string;
    decision: string;
    approved_by: string;
    reason: string;
    source_manifest_sha256: string;
    created_at: string;
  } | null;
  promotion?: {
    id: string;
    approval_id: string;
    status: string;
    initial_manifest_sha256: string;
    applied_manifest_sha256?: string | null;
    final_manifest_sha256?: string | null;
    validations: TestExecution[];
    rollback_validations: TestExecution[];
    rollback_verified?: boolean | null;
    failure_reason?: string | null;
    lease_id?: string | null;
    fencing_token?: number | null;
    evidence: Evidence[];
    checkpoints: {
      sequence: number;
      stage: string;
      detail: string;
      occurred_at: string;
    }[];
    mutation_journal?: {
      id: string;
      stage: string;
      fencing_token: number;
      validation_state: string;
      rollback_state: string;
      recovery_count: number;
      recovery_required: boolean;
      terminal: boolean;
      failure_reason?: string | null;
      entries: {
        path: string;
        before_sha256: string;
        after_sha256: string;
        staged: boolean;
        replacement_started: boolean;
        replacement_completed: boolean;
        rollback_completed: boolean;
      }[];
      checkpoints: {
        sequence: number;
        stage: string;
        detail: string;
        occurred_at: string;
      }[];
    } | null;
    reconciliation?: {
      id: string;
      status: string;
      previous_manifest_sha256: string;
      new_manifest_sha256: string;
      scan_id: string;
      changed_paths: string[];
      dependent_paths: string[];
      parsed_paths: string[];
      reused_file_ids: string[];
      invalidated_claim_ids: string[];
      superseded_claim_ids: string[];
      invalidated_workspace_record_ids: string[];
      superseded_validation_decision_ids: string[];
      replacement_claim_ids: string[];
      evidence: Evidence[];
      checkpoints: {
        sequence: number;
        stage: string;
        detail: string;
        occurred_at: string;
      }[];
      source_unchanged_during_reconciliation: boolean;
    } | null;
    completed_at?: string | null;
  } | null;
};
type Edge = { source: string; relation: string; target: string };
type DiagnosticState = {
  run_id: string | null;
  status: string;
  stage: string;
  question: string;
  test_path: string;
  started_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number;
  task_id: string | null;
  claim_id: string | null;
  worker_calls: number;
  reused_subtasks: number;
  dependency_paths: string[];
  conclusion: string;
  source_integrity_verified: boolean | null;
  error: string | null;
};
type ConflictState = {
  run_id: string | null;
  status: string;
  stage: string;
  question: string;
  test_path: string;
  started_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number;
  task_id: string | null;
  finding_claim_ids: string[];
  cluster_id: string | null;
  resolution_task_id: string | null;
  verdict_id: string | null;
  verdict_status: string | null;
  selected_value: string | null;
  rationale: string;
  investigation_calls: number;
  resolution_calls: number;
  reused_verdict: boolean;
  evidence_claim_ids: string[];
  dependency_paths: string[];
  source_integrity_verified: boolean | null;
  error: string | null;
};
type DiagnosticOptions = {
  project_root: string;
  read_only: boolean;
  tests: string[];
  limits: {
    question_characters: number;
    dependency_files: number;
    concurrent_runs: number;
    wall_time_seconds: number;
    model_calls: number;
    project_writes: number;
  };
};
type WorkspaceProject = {
  id: string;
  name: string;
  root: string;
  organization: string;
  execution_mode: "READ_ONLY" | "PROTECTED" | "AUTONOMOUS_SANDBOX" | "AUTONOMOUS_PROJECT";
  project_manifest: string;
  project_goals: { title: string; goal: string }[];
  ideas: {
    id: string;
    title: string;
    detail: string;
    status: "DRAFT" | "ARCHIVED";
    created_at: string;
  }[];
  read_only: boolean;
  write_capability: boolean;
  index_current: boolean;
  index_scan_id: string | null;
  artifact_count: number;
  dependency_count: number;
  adapter: string;
};
type IdeaSuggestionResponse = {
  project_id: string;
  project_name: string;
  index_scan_id: string | null;
  indexed_manifest_sha256: string;
  source_integrity_verified: boolean;
  read_only_verified: boolean;
  suggestions: {
    title: string;
    detail: string;
    rationale: string;
    evidence: Evidence[];
  }[];
  confidence: number;
  files_examined: string[];
  worker: {
    name: string;
    model: string;
    sandbox: string;
    calls: number;
    indexed_files: number;
    authorized_files: number;
    source_bytes: number;
    monetary_cost: number | null;
    cost_basis: string;
  };
  persistence: "NOT_SAVED";
  authority: "NO_TICKET_RUN_OR_PROJECT_WRITE";
};
type WorkspaceOptions = {
  projects: WorkspaceProject[];
  limits: {
    request_characters: number;
    acceptance_criteria: number;
    criterion_characters: number;
    concurrent_jobs: number;
    project_writes: number;
    unreal_launches: number;
    compilations: number;
  };
};
type WorkspaceState = {
  ticket_id?: string | null;
  job_id: string | null;
  kind: string | null;
  project_id: string | null;
  project_name: string | null;
  status: string;
  stage: string;
  prompt: string;
  started_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number;
  result_id: string | null;
  answer: string;
  evidence_count: number;
  dependency_count: number;
  source_integrity_verified: boolean | null;
  read_only_verified: boolean | null;
  approval_status: string | null;
  execution_authorized: boolean;
  error: string | null;
};
type ValidationWorker = {
  id: string;
  name: string;
  categories: string[];
  artifact_kinds: string[];
  executable: string;
  arguments: string[];
  enabled: boolean;
  authorized_by: string;
  authorization_reason: string;
  limits: {
    max_wall_time_seconds: number;
    max_processes: number;
    max_memory_bytes: number;
    max_output_bytes: number;
    allowed_paths: string[];
    allowed_artifact_kinds: string[];
    allowed_executables: string[];
    allowed_argument_templates: string[][];
  };
};
type SandboxState = {
  attempt_id: string | null;
  ticket_id: string | null;
  plan_record_id: string | null;
  status: string;
  stage: string;
  error: string | null;
  validation_workers?: ValidationWorker[];
};
type ApprovalRule = {
  id: string;
  action: string;
  required_roles: string[];
  minimum_approvals: number;
  artifact_kinds: string[];
  required_validation_categories: string[];
};
type GovernanceDecision = {
  id: string;
  action: string;
  artifact_id: string;
  decision: string;
  actor: string;
  actor_roles: string[];
  authenticated_subject?: string | null;
  authentication_method?: string | null;
  organization_id?: string | null;
  session_id?: string | null;
  reason: string;
  policy_id: string;
  policy_version: number;
  rule_id: string;
  binding_sha256: string;
  valid: boolean;
  expiration_reason?: string | null;
  created_at: string;
};
type GovernancePolicy = {
  id: string;
  project_id: string;
  project_root: string;
  permitted_worker_ids: string[];
  required_validation_categories: string[];
  plan_approvers: string[];
  promotion_approvers: string[];
  actor_roles: Record<string, string[]>;
  authority_mode: "INDIVIDUAL_LOCAL" | "AUTHENTICATED_TEAM";
  authority_organization_id?: string | null;
  authenticated_role_bindings: Record<string, string[]>;
  approval_rules: ApprovalRule[];
  artifact_validation_requirements: Record<string, string[]>;
  revision_history: {
    version: number;
    configured_by: string;
    reason: string;
    created_at: string;
  }[];
  max_ticket_budget: {
    max_tokens: number;
    max_model_calls: number;
    max_worker_calls: number;
    max_wall_time_seconds: number;
    max_branch_depth: number;
  };
  configured_by: string;
  reason: string;
  version: number;
  updated_at: string;
};
type ScheduledWork = {
  id: string;
  ticket_id: string;
  project_id: string;
  work_kind: string;
  status: string;
  priority: string;
  predicted_cost_usd: number;
  predicted_latency_seconds: number;
  predicted_worker_calls: number;
  capacity_units: number;
  required_validation_categories: string[];
  scheduling_score: number;
  scheduling_reasons: string[];
  blocked_reason?: string | null;
  resumable: boolean;
  cancellation_requested: boolean;
  cancelled_by?: string | null;
  cancellation_reason?: string | null;
  resources_disposed: boolean;
  evidence_ids: string[];
  checkpoints: {
    sequence: number;
    stage: string;
    detail: string;
    created_at: string;
  }[];
  updated_at: string;
};
type Snapshot = {
  generated_at: string;
  connected: boolean;
  running: boolean;
  root_status: string;
  nodes: GraphNode[];
  edges: Edge[];
  workspace?: {
    focus_ticket_id?: string | null;
    needs_attention: number;
    in_progress: number;
    completed: number;
    work_items: {
      ticket_id: string;
      project_id: string;
      title: string;
      priority: string;
      status: string;
      action: string;
      action_label: string;
      detail: string;
      urgency: string;
      closure_ready: boolean;
      resolved_criteria: number;
      total_criteria: number;
      exhausted_budgets: string[];
      updated_at: string;
    }[];
    durable_activities: {
      id: string;
      activity_kind: string;
      status: string;
      ticket_id?: string | null;
      artifact_id?: string | null;
      stage: string;
      resumable: boolean;
      error?: string | null;
      updated_at: string;
    }[];
    scheduled_work: ScheduledWork[];
    scheduler_limits?: {
      global_concurrency: number;
      per_project_concurrency: number;
      per_ticket_concurrency: number;
      capacity_units: number;
      active_jobs: number;
      used_capacity_units: number;
    };
    governance_policies: GovernancePolicy[];
    leases: {
      id: string;
      project_id?: string | null;
      project_root: string;
      status: string;
      holder_id: string;
      fencing_token: number;
      expires_at: string;
      events: number;
    }[];
  };
  metrics: {
    tasks: number;
    codex_calls: number;
    resolution_attempts: number;
    evidence_claims: number;
    average_evidence_confidence: number | null;
    active_tasks: number;
    stopped_tasks: number;
    conflict_clusters?: number;
    conflict_verdicts?: number;
    resolved_verdicts?: number;
    unresolved_verdicts?: number;
    verdict_reuses?: number;
    onboarded_projects?: number;
    project_scans?: number;
    project_files?: number;
    project_symbols?: number;
    project_tests?: number;
    project_dependencies?: number;
    scan_parsed_files?: number;
    scan_reused_files?: number;
    scan_model_calls?: number;
    scan_invalidated_claims?: number;
    read_only_projects?: number;
    repair_proposals?: number;
    repair_validations?: number;
    verified_repairs?: number;
    rejected_repairs?: number;
    repair_model_calls?: number;
    repair_approvals?: number;
    approved_repairs?: number;
    repair_promotions?: number;
    promoted_repairs?: number;
    rolled_back_repairs?: number;
    project_leases?: number;
    active_project_leases?: number;
    lease_contentions?: number;
    lease_reclaims?: number;
    lease_recoveries?: number;
    evaluation_runs?: number;
    passed_evaluation_runs?: number;
    evaluation_results?: number;
    evaluation_worker_calls?: number;
    evaluation_model_calls?: number;
    evaluation_retrieved_tokens?: number;
    evaluation_latency_ms?: number;
    evaluation_observed_latency_ms?: number;
    evaluation_duplicate_investigations?: number;
    evaluation_memory_reuses?: number;
    outlier_claims?: number;
    current_claims?: number;
    invalidated_claims?: number;
    superseded_claims?: number;
    reconstructions?: number;
    reconstructed_nodes?: number;
    baseline_nodes?: number;
    reconstructed_tokens?: number;
    baseline_tokens?: number;
    pruned_nodes?: number;
    evidence_preserved?: boolean;
    working_memories?: number;
    episodic_memories?: number;
    semantic_memories?: number;
    procedural_memories?: number;
    promotion_decisions?: number;
    accepted_promotions?: number;
    rejected_promotions?: number;
    benchmark_runs?: number;
    benchmark_passes?: number;
    fixed_benchmark_tokens?: number;
    active_benchmark_tokens?: number;
    benchmark_token_reduction?: number | null;
    benchmark_correctness_preserved?: boolean;
    benchmark_evidence_preserved?: boolean;
    benchmark_duplicate_retrievals?: number;
    virtual_pathways?: number;
    active_virtual_pathways?: number;
    invalidated_virtual_pathways?: number;
    pathway_decisions?: number;
    accepted_pathway_promotions?: number;
    pathway_benchmarks?: number;
    average_pathway_token_reduction?: number | null;
    plan_decisions?: number;
    replanning_decisions?: number;
    planning_model_calls?: number;
    planning_retrieval_tokens?: number;
    duplicate_investigations?: number;
    execution_attempts?: number;
    execution_fallbacks?: number;
    execution_tokens?: number;
    execution_cost_usd?: number;
    execution_latency_ms?: number;
    route_predictions?: number;
    learned_route_changes?: number;
    routing_policy_version?: number;
    route_evaluations?: number;
    route_prediction_success_rate?: number | null;
    mean_route_cost_error_usd?: number | null;
    mean_route_latency_error_ms?: number | null;
    total_token_usage?: number;
    potential_total_token_usage?: number;
    measured_avoided_tokens?: number;
    token_comparison_count?: number;
    unmetered_model_calls?: number;
    legacy_unmetered_model_calls?: number;
    model_call_count?: number;
    metered_total_tokens?: number;
    provider_measured_tokens?: number;
    estimated_tokens?: number;
    provider_measured_calls?: number;
    estimated_call_count?: number;
    failed_model_calls?: number;
    local_observed_input_tokens?: number;
    provider_unexplained_input_tokens?: number;
    provider_cached_input_tokens?: number;
    provider_uncached_input_tokens?: number;
    provider_unexplained_uncached_input_tokens?: number;
    provider_measurement_coverage_percent?: number;
    measurement_started_at?: string;
    excluded_historical_calls?: number;
    excluded_historical_tokens?: number;
    token_diagnostics?: Array<{
      occurred_at: string;
      role: string;
      operation: string;
      provider: string;
      model: string;
      status: string;
      provider_input_tokens: number;
      provider_output_tokens: number;
      local_prompt_tokens?: number;
      local_output_schema_tokens?: number;
      local_observed_input_tokens?: number;
      provider_unexplained_input_tokens?: number;
      local_result_tokens?: number;
      component_tokens?: Record<string, number>;
      codex_event_count?: number;
      codex_command_count?: number;
      codex_commands?: string[];
      codex_exposed_tool_activity?: boolean;
      codex_event_types?: Record<string, number>;
      codex_item_types?: Record<string, number>;
      codex_reported_usage_breakdown?: Record<string, number>;
    }>;
  };
  control?: { last_output: string; last_error: string };
  diagnostic?: DiagnosticState;
  conflict?: ConflictState;
  project_workspace?: WorkspaceState;
  implementation_sandbox?: SandboxState;
  conversation_benchmark?: {
    status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
    error: string;
    result?: {
      id: string;
      created_at: string;
      model: string;
      baseline_tokens: number;
      rlmgraph_tokens: number;
      tokens_saved: number;
      savings_percent: number;
      quality_preserved: boolean;
      criteria_total: number;
      baseline: { quality: number; model_call_count: number };
      rlmgraph: { quality: number; model_call_count: number };
    } | null;
  };
  project_goal_benchmark?: {
    status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
    error: string;
    result?: {
      id: string;
      created_at: string;
      goal: string;
      baseline_tokens: number;
      rlmgraph_tokens: number;
      tokens_saved: number;
      savings_percent: number;
      quality_preserved: boolean;
      criteria_total?: number;
      baseline: { criteria_passed: number; tokens_per_criterion: number | null };
      rlmgraph: { criteria_passed: number; tokens_per_criterion: number | null };
    } | null;
  };
  unreal_benchmark?: {
    status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
    error?: string | null;
    result?: {
      id: string;
      status: string;
      run_root: string;
      report_path: string;
      arms: Record<string, {
        project_root: string;
        changed_files: string[];
        namespace_violations: string[];
        policy_passed: boolean;
        token_usage?: {
          model_call_count: number;
          metered_total_tokens: number;
          provider_measured_tokens: number;
          provider_cached_input_tokens: number;
          provider_uncached_input_tokens: number;
          provider_measurement_coverage_percent: number;
          tokens_per_task: number;
          tokens_per_acceptance_criterion: number | null;
        };
      }>;
    } | null;
  };
};

const API = "http://127.0.0.1:8787";
const empty: Snapshot = {
  generated_at: "",
  connected: false,
  running: false,
  root_status: "LOADING",
  nodes: [],
  edges: [],
  metrics: {
    tasks: 0,
    codex_calls: 0,
    resolution_attempts: 0,
    evidence_claims: 0,
    average_evidence_confidence: null,
    active_tasks: 0,
    stopped_tasks: 0,
  },
};

function shortId(id: string) {
  return id
    .replace("LIVE-DEMO-", "")
    .replace(/^TASK-/, "T-")
    .replace(/^CLAIM-/, "C-")
    .replace(/^ATTEMPT-/, "A-")
    .slice(0, 15);
}
function statusClass(status: string) {
  return status.toLowerCase().replaceAll("_", "-");
}
function completedAction(path: string) {
  const labels: Record<string, string> = {
    create: "Ticket created. No project files were changed.",
    "approve-plan": "Plan decision recorded against the current source state.",
    transition: "Ticket state updated and added to its history.",
    criterion: "Acceptance criterion decision recorded.",
    validation: "Validation result recorded on this ticket.",
    start: "Run queued in an isolated project copy.",
    discard: "Isolated proposal discarded; the project was not changed.",
    "satisfy-validation": "Validation decision recorded for this proposal.",
    "run-validation-worker": "Bounded validation completed and was recorded.",
    "import-validation-report":
      "External validation report recorded with its source and patch identity.",
    "approve-promotion":
      "Apply decision recorded for the exact reviewed proposal.",
    promote: "Approved files applied under the project write boundary.",
    recover: "Interrupted apply operation reached a safe recorded state.",
    reconcile: "Project index refreshed to the applied source state.",
  };
  return labels[path] || "Action completed and recorded.";
}
function plainAction(value: string) {
  return value
    .replace(/record promotion approval/i, "Approve change")
    .replace(/promote approved patch/i, "Apply approved change")
    .replace(/recover interrupted promotion/i, "Recover interrupted apply")
    .replace(/reconcile project knowledge/i, "Refresh project index")
    .replace(/create isolated implementation/i, "Start run")
    .replace(/run ticket investigation/i, "Answer ticket question")
    .replace(/generate ticket impact plan/i, "Create plan");
}
function plainStage(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/implementation sandbox/gi, "implementation run")
    .replace(/promotion/gi, "apply")
    .replace(/reconciliation/gi, "project refresh");
}

export default function Home() {
  const [snapshot, setSnapshot] = useState<Snapshot>(empty);
  const [initialLoading, setInitialLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string>("");
  const [activeTab, setActiveTab] = useState<
    "work" | "tickets" | "projects" | "activity" | "models" | "lab" | "savings"
  >("work");
  const [error, setError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [profiles, setProfiles] = useState<MachineProfile[]>([]);
  const [profileSession, setProfileSession] = useState<ProfileSession | null>(null);
  const [profileName, setProfileName] = useState("");
  const [profilePassword, setProfilePassword] = useState("");
  const [profilePasswordConfirmation, setProfilePasswordConfirmation] = useState("");
  const [showProfilePassword, setShowProfilePassword] = useState(false);
  const [profileId, setProfileId] = useState("");
  const [profileStyle, setProfileStyle] = useState<MachineProfile["response_style"]>("BALANCED");
  const [profileError, setProfileError] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileMode, setProfileMode] = useState<"LOGIN" | "CREATE">("LOGIN");
  const [profileChecking, setProfileChecking] = useState(true);
  const [theme, setTheme] = useState<"LIGHT" | "DARK">("LIGHT");
  const [chatTextSize, setChatTextSize] = useState<"SMALL" | "MEDIUM" | "LARGE">("MEDIUM");
  const [busy, setBusy] = useState(false);
  const [modelSettings, setModelSettings] = useState<ModelSettings | null>(null);
  const [modelBusyRole, setModelBusyRole] = useState<string | null>(null);
  const [conversationBenchmarkBusy, setConversationBenchmarkBusy] = useState(false);


  const [diagnosticOptions] =
    useState<DiagnosticOptions | null>(null);




  const [workspaceOptions, setWorkspaceOptions] =
    useState<WorkspaceOptions | null>(null);
  const [projectRoot, setProjectRoot] = useState("");
  const [projectBrowsing, setProjectBrowsing] = useState(false);
  const [projectSelectionNotice, setProjectSelectionNotice] = useState("");
  const [projectConnecting, setProjectConnecting] = useState(false);
  const [projectSection, setProjectSection] = useState<
    "manifests" | "organizations"
  >("manifests");
  const [projectIntentSection, setProjectIntentSection] = useState<
    "manifest" | "goals" | "ideas"
  >("manifest");
  const [projectMetadataBusy, setProjectMetadataBusy] = useState(false);
  const [ideaSuggestionBusy, setIdeaSuggestionBusy] = useState(false);
  const [ideaSuggestions, setIdeaSuggestions] =
    useState<IdeaSuggestionResponse | null>(null);
  const [workspaceProject, setWorkspaceProject] = useState("");
  const projectSelectionExplicit = useRef(false);
  const chatTranscriptRef = useRef<HTMLDivElement | null>(null);
  const [activeTicketId, setActiveTicketId] = useState("");
  const [ticketTitle, setTicketTitle] = useState("");
  const [ticketDescription, setTicketDescription] = useState("");
  const [ticketCriteria, setTicketCriteria] = useState("");
  const [ticketConstraints, setTicketConstraints] = useState("");
  const [ticketPriority, setTicketPriority] = useState("MEDIUM");
  const [ticketDependencies, setTicketDependencies] = useState<string[]>([]);
  const [ticketBudget, setTicketBudget] = useState({
    max_tokens: 50000,
    max_model_calls: 10,
    max_worker_calls: 10,
    max_wall_time_seconds: 900,
    max_branch_depth: 4,
  });
  const [ticketBusy, setTicketBusy] = useState(false);
  const [criterionEvidence, setCriterionEvidence] = useState<
    Record<string, string>
  >({});
  const [ticketInfo, setTicketInfo] = useState<{ ticketId: string; section: string } | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [savedConversations, setSavedConversations] = useState<SavedConversation[]>([]);
  const [memoryError, setMemoryError] = useState("");
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatScope, setChatScope] = useState<"AUTO" | "SYSTEM" | "PROJECT">("AUTO");
  const [chatInvestigationMode, setChatInvestigationMode] = useState<
    "AUTO" | "DIRECT" | "RECURSIVE"
  >("AUTO");
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatActivity, setChatActivity] = useState<ChatActivity[]>([]);
  const [claimTicketBusy, setClaimTicketBusy] = useState(false);
  const [claimTicketClaimId, setClaimTicketClaimId] = useState<string | null>(null);
  const [claimTicketObjective, setClaimTicketObjective] = useState("");
  const [claimTicketCriterion, setClaimTicketCriterion] = useState("");

  const loadProfiles = useCallback(async () => {
    const response = await fetch(`${API}/api/profiles`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Profiles unavailable");
    setProfiles(payload.profiles || []);
    setProfileId((current) => current || payload.profiles?.[0]?.id || "");
  }, []);

  useEffect(() => { void loadProfiles().catch(() => undefined); }, [loadProfiles]);
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem("tgram-profile-session");
      if (!saved) { setProfileChecking(false); return; }
      const candidate = JSON.parse(saved) as ProfileSession;
      void fetch(`${API}/api/profiles/me`, {
        headers: { Authorization: `Bearer ${candidate.token}` }, cache: "no-store",
      }).then(async (response) => {
        if (!response.ok) throw new Error("expired");
        const payload = await response.json();
        setProfileSession({ token: candidate.token, profile: payload.profile });
      }).catch(() => sessionStorage.removeItem("tgram-profile-session"))
        .finally(() => setProfileChecking(false));
    } catch { sessionStorage.removeItem("tgram-profile-session"); setProfileChecking(false); }
  }, []);

  useEffect(() => {
    if (!profileSession) return;
    const saved = localStorage.getItem(`tgram-theme-${profileSession.profile.id}`);
    setTheme(saved === "DARK" ? "DARK" : "LIGHT");
    const savedTextSize = localStorage.getItem(`tgram-chat-text-${profileSession.profile.id}`);
    setChatTextSize(
      savedTextSize === "SMALL" || savedTextSize === "LARGE" ? savedTextSize : "MEDIUM",
    );
  }, [profileSession]);

  function chooseTheme(nextTheme: "LIGHT" | "DARK") {
    setTheme(nextTheme);
    if (profileSession) {
      localStorage.setItem(`tgram-theme-${profileSession.profile.id}`, nextTheme);
    }
  }

  function chooseChatTextSize(nextSize: "SMALL" | "MEDIUM" | "LARGE") {
    setChatTextSize(nextSize);
    if (profileSession) {
      localStorage.setItem(`tgram-chat-text-${profileSession.profile.id}`, nextSize);
    }
  }

  async function submitProfile(event: FormEvent) {
    event.preventDefault();
    if (profileMode === "CREATE" && profilePassword !== profilePasswordConfirmation) {
      setProfileError("The passwords do not match.");
      return;
    }
    setProfileBusy(true); setProfileError("");
    try {
      const creating = profileMode === "CREATE";
      const response = await fetch(`${API}/api/profiles/${creating ? "create" : "login"}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON["stringify"](creating
          ? { name: profileName.trim(), password: profilePassword, response_style: profileStyle }
          : { profile_id: profileId, password: profilePassword }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Profile login failed");
      setProfileSession(payload); setProfilePassword("");
      setProfilePasswordConfirmation(""); setProfileName("");
      sessionStorage.setItem("tgram-profile-session", JSON["stringify"](payload));
      await loadProfiles(); setAccountOpen(false);
      setActionNotice(`Logged in to ${payload.profile.name}.`);
    } catch (reason) { setProfileError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setProfileBusy(false); }
  }

  async function logoutProfile() {
    if (profileSession) await fetch(`${API}/api/profiles/logout`, {
      method: "POST", headers: { Authorization: `Bearer ${profileSession.token}` },
    }).catch(() => undefined);
    sessionStorage.removeItem("tgram-profile-session");
    setProfileSession(null); setProfileMode("LOGIN"); setProfilePassword("");
    setProfilePasswordConfirmation(""); setShowProfilePassword(false);
    setChatMessages([]); setChatSessionId(null); setAccountOpen(false);
  }

  async function sendChat(event: { preventDefault(): void }, retry?: ChatMessage) {
    event.preventDefault();
    const message = (retry?.userMessage || chatInput).trim();
    if (!message || chatBusy || !profileSession) return;
    const activityId = crypto.randomUUID();
    let progressTimer: number | undefined;
    if (!retry) setChatMessages((current) => [...current, { role: "user", content: message }]);
    if (!retry) setChatInput("");
    setChatBusy(true);
    setChatActivity([
      { label: "Queued", detail: "Waiting for backend acknowledgement.", status: "ACTIVE" },
    ]);
    try {
      progressTimer = window.setInterval(() => {
        void fetch(`${API}/api/chat/progress/${activityId}`, { cache: "no-store" })
          .then((progressResponse) => progressResponse.json())
          .then((progress) => {
            const label = String(progress.stage || "QUEUED").replaceAll("_", " ");
            const next: ChatActivity = {
              label,
              detail: String(progress.detail || "Backend activity updated."),
              status: progress.status === "FAILED" ? "FAILED" : progress.status === "COMPLETE" ? "COMPLETE" : "ACTIVE",
            };
            setChatActivity((current) => {
              const completed = current.map((item) =>
                item.status === "ACTIVE" ? { ...item, status: "COMPLETE" as const } : item
              );
              if (completed.at(-1)?.label === next.label) {
                return [...completed.slice(0, -1), next];
              }
              return [...completed, next].slice(-6);
            });
          })
          .catch(() => undefined);
      }, 350);
      const response = await fetch(`${API}/api/chat${retry ? "/retry" : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${profileSession.token}` },
        body: JSON["stringify"]({
          message,
          turn_id: retry?.turnId,
          project_id: workspaceProject || null,
          ticket_id: activeTicketId || null,
          session_id: chatSessionId,
          scope: chatScope,
          investigation_mode: chatInvestigationMode,
          activity_id: activityId,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Chat response failed");
      if (retry && !payload.replaces_turn_id) throw new Error(payload.answer || "Retry did not produce a replacement. Your previous answer is retained.");
      setChatActivity((current) => [
        ...current.map((item) => ({ ...item, status: "COMPLETE" as const })),
        {
          label: String(payload.operation_route || payload.route || "Complete").replaceAll("_", " "),
          detail: String(payload.routing_reason || "The response was returned and persisted."),
          status: payload.route === "RLM_RECOVERY" ? "FAILED" as const : "COMPLETE" as const,
        },
      ].slice(-6));
      setChatMessages((current) => [
        ...current.filter((item) => !payload.replaces_turn_id || item.turnId !== payload.replaces_turn_id),
        {
          role: "assistant",
          turnId: payload.turn_id,
          userMessage: message,
          content: String(payload.answer),
          ticketId: payload.ticket_id,
          projectId: payload.project_id,
          memoryReceipt: payload.conversation_memory_receipt,
          route: payload.route,
          metrics: payload.metrics,
          confidence: payload.confidence,
          routingConfidence: payload.routing_confidence,
          routingReason: payload.routing_reason,
          operationRoute: payload.operation_route,
          scope: payload.scope,
          taskId: payload.task_id,
          claimId: payload.claim_id,
          evidence: payload.evidence,
          taskTree: payload.task_tree,
          planningQuestions: payload.planning_questions,
          contradictions: payload.contradictions,
          investigationCalls: payload.investigation_calls,
          budgetExhausted: payload.budget_exhausted,
          investigationMode: payload.investigation_mode,
          contextClaimIds: payload.context_claim_ids,
          contextTokenEstimate: payload.context_token_estimate,
          workProjectId: payload.work_project_id,
        },
      ]);
      if (payload.session_id) setChatSessionId(String(payload.session_id));
      void refreshConversationMemory();
    } catch (reason) {
      setChatActivity((current) => [
        ...current.filter((item) => item.status === "COMPLETE"),
        {
          label: "Response interrupted",
          detail: reason instanceof Error ? reason.message : "The chat request did not complete.",
          status: "FAILED",
        },
      ]);
      if (!retry) setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: reason instanceof Error ? reason.message : "Chat response failed.",
        },
      ]);
    } finally {
      if (progressTimer !== undefined) window.clearInterval(progressTimer);
      setChatBusy(false);
    }
  }

  async function createTicketFromClaim(event: FormEvent, message: ChatMessage) {
    event.preventDefault();
    if (!message.claimId || !message.workProjectId || claimTicketBusy) return;
    const objective = claimTicketObjective.trim();
    if (!objective) return;
    const criterion = claimTicketCriterion.trim();
    if (!criterion) return;
    setClaimTicketBusy(true);
    try {
      const response = await fetch(`${API}/api/tickets/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({
          project_id: message.workProjectId,
          title: objective.slice(0, 160),
          description: objective,
          acceptance_criteria: [criterion],
          constraints: [
            "Preserve read-only chat authority and existing governance boundaries.",
          ],
          priority: "MEDIUM",
          dependency_ticket_ids: [],
          budget: ticketBudget,
          source_claim_ids: [message.claimId],
        }),
      });
      const ticket = await response.json();
      if (!response.ok) throw new Error(ticket.error || "Unable to create ticket");
      setWorkspaceProject(message.workProjectId);
      setActiveTicketId(ticket.id);
      setClaimTicketClaimId(null);
      setClaimTicketObjective("");
      setClaimTicketCriterion("");
      setActiveTab("tickets");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to create ticket");
    } finally {
      setClaimTicketBusy(false);
    }
  }

  function editModelRole(role: string, patch: Partial<ModelRole>) {
    setModelSettings((current) => current ? {
      ...current,
      roles: current.roles.map((item) => item.role === role ? { ...item, ...patch } : item),
    } : current);
  }

  async function saveModelRole(role: ModelRole) {
    setModelBusyRole(role.role);
    try {
      const response = await fetch(`${API}/api/models`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON["stringify"](role),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Model selection failed");
      setModelSettings(payload);
      setActionNotice(`${role.label} now uses ${role.model}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Model selection failed.");
    } finally {
      setModelBusyRole(null);
    }
  }

  async function startProjectGoalBenchmark() {
    setConversationBenchmarkBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/benchmarks/project-goal/start`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Comparison could not start");
      setSnapshot((current) => ({ ...current, project_goal_benchmark: payload }));
    } catch (benchmarkError) {
      setError(benchmarkError instanceof Error ? benchmarkError.message : String(benchmarkError));
    } finally {
      setConversationBenchmarkBusy(false);
    }
  }



  useEffect(() => {
    void fetch(`${API}/api/models`, { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("models unavailable")))
      .then((payload) => setModelSettings(payload))
      .catch(() => undefined);
  }, []);

  const restoreConversation = useCallback((session?: SavedConversation) => {
        setChatSessionId(session?.id || null);
        setChatActivity([]);
        setChatInput("");
        setClaimTicketClaimId(null);
        setChatMessages((session?.turns || []).filter((turn) => !turn.superseded_by_turn_id).flatMap((turn) => [
          { role: "user", content: turn.user_message },
          {
            role: "assistant", content: turn.answer, route: turn.route,
            turnId: turn.id, userMessage: turn.user_message,
            ticketId: turn.ticket_id,
            projectId: turn.project_id,
            memoryReceipt: turn.conversation_memory_receipt,
            confidence: turn.claim_confidence, routingConfidence: turn.routing_confidence,
            routingReason: turn.routing_reason, operationRoute: turn.reuse_kind,
            scope: turn.scope,
            taskId: turn.task_id, claimId: turn.claim_id, evidence: turn.evidence,
            taskTree: turn.task_tree,
          investigationMode: turn.investigation_mode,
            contextClaimIds: turn.context_claim_ids,
            contextTokenEstimate: turn.context_token_estimate,
            workProjectId: turn.work_project_id,
          },
        ]));
  }, []);

  const memoryRequest = useRef<AbortController | null>(null);
  const refreshConversationMemory = useCallback(async (restore = false) => {
    memoryRequest.current?.abort();
    if (!profileSession) return;
    const controller = new AbortController();
    memoryRequest.current = controller;
    try {
      const response = await fetch(`${API}/api/chat/sessions`, {
        cache: "no-store", signal: controller.signal,
        headers: { Authorization: `Bearer ${profileSession.token}` },
      });
      if (!response.ok) throw new Error("Conversation memory could not be loaded. Try Refresh memory.");
      const payload = await response.json();
      if (controller.signal.aborted) return;
      setSavedConversations(payload.sessions || []);
      setMemoryError("");
      if (restore) restoreConversation(payload.sessions?.[0]);
    } catch (error) {
      if (!controller.signal.aborted) setMemoryError(error instanceof Error ? error.message : "Memory unavailable.");
    }
  }, [profileSession, restoreConversation]);

  useEffect(() => {
    setSavedConversations([]);
    setMemoryError("");
    restoreConversation();
    void refreshConversationMemory(true);
    return () => memoryRequest.current?.abort();
  }, [refreshConversationMemory, restoreConversation]);

  useEffect(() => {
    const transcript = chatTranscriptRef.current;
    if (!transcript) return;
    window.requestAnimationFrame(() => {
      transcript.scrollTop = transcript.scrollHeight;
    });
  }, [chatMessages, chatActivity, chatBusy]);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/snapshot`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Observer service is unavailable");
      const next = (await response.json()) as Snapshot;
      setSnapshot(next);
      setError("");
      setInitialLoading(false);
      setActiveTicketId((current) => {
        const currentTicketIsAvailable = Boolean(
          current &&
          next.nodes.some(
            (node) =>
              node.node_type === "ticket" &&
              node.id === current &&
              node.status !== "CLOSED",
          ),
        );
        if (currentTicketIsAvailable) return current;
        if (projectSelectionExplicit.current) return "";
        const ticketId =
          next.nodes.find(
                  (node) =>
                    node.node_type === "ticket" &&
                    node.id === next.workspace?.focus_ticket_id &&
                    node.status !== "CLOSED",
                )?.id ||
              next.nodes.find(
                (node) => node.node_type === "ticket" && node.status !== "CLOSED",
              )?.id ||
              "";
        const projectId = next.nodes.find(
          (node) => node.node_type === "ticket" && node.id === ticketId,
        )?.project_id;
        if (projectId && !projectSelectionExplicit.current) {
          setWorkspaceProject(projectId);
        }
        return ticketId;
      });
      setSelectedId(
        (current) =>
          current ||
          next.nodes.find((node) => node.node_type === "ticket")?.id ||
          next.nodes[0]?.id ||
          "",
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to load graph",
      );
      setInitialLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(refresh, 0);
    const timer = window.setInterval(refresh, 2000);
    const loadWorkspaceOptions = () => {
      void fetch(`${API}/api/workspace/options`, { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok)
            throw new Error("Workspace options are unavailable");
          const options = (await response.json()) as WorkspaceOptions;
          setWorkspaceOptions(options);
          setWorkspaceProject(
            (current) => current || options.projects[0]?.id || "",
          );
        })
        .catch((reason) =>
          setError(
            reason instanceof Error
              ? reason.message
              : "Unable to load workspace options",
          ),
        );
    };
    loadWorkspaceOptions();
    const workspaceOptionsTimer = window.setInterval(
      loadWorkspaceOptions,
      10000,
    );
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
      window.clearInterval(workspaceOptionsTimer);
    };
  }, [refresh]);

  async function control(action: "start" | "reset") {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/demo/${action}`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `${action} failed`);
      setSnapshot(payload as Snapshot);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Control failed");
    } finally {
      setBusy(false);
    }
  }





  async function createNextTicketPlan() {
    if (!activeTicket || ticketBusy || workspaceRunning) return;
    setTicketBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/workspace/plan`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({ project_id: activeTicket.project_id, ticket_id: activeTicket.id,
          request: activeTicket.description || activeTicket.title,
          acceptance_criteria: (activeTicket.ticket_criteria || []).map((item) => item.description) }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Planning could not start.");
      setActionNotice("Planning requested. Wait for the proposed plan; implementation has not started.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Planning could not start.");
    } finally { setTicketBusy(false); }
  }

  async function ticketAction(path: string, body: Record<string, unknown>) {
    setTicketBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/tickets/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"](body),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Ticket action failed");
      if (path === "create") {
        setActiveTicketId(payload.id);
        setTicketTitle("");
        setTicketDescription("");
        setTicketCriteria("");
        setTicketConstraints("");
        setTicketDependencies([]);
      }
      setActionNotice(completedAction(path));
      await refresh();
      return true;
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Ticket action failed",
      );
      return false;
    } finally {
      setTicketBusy(false);
    }
  }

  async function approvePromotionAndApply(
    ticketId: string,
    attemptId: string,
    reviewDecisionIds: string[],
  ) {
    if (ticketBusy) return;
    for (const decisionId of reviewDecisionIds) {
      const reviewed = await sandboxAction("satisfy-validation", {
        ticket_id: ticketId,
        attempt_id: attemptId,
        decision_id: decisionId,
        actor: "Local user",
        decision: "APPROVED",
        detail: "User reviewed and approved the exact displayed patch for application.",
      });
      if (!reviewed) return;
    }
    const approved = await sandboxAction("approve-promotion", {
      ticket_id: ticketId,
      attempt_id: attemptId,
      actor: "Local user",
      decision: "APPROVED",
      reason: "User approved this exact validated proposal and requested application.",
    });
    if (approved === false) return;
    await sandboxAction("promote", {
      ticket_id: ticketId,
      attempt_id: attemptId,
    });
  }

  async function connectProject(event: FormEvent) {
    event.preventDefault();
    setProjectConnecting(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/projects/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({ root: projectRoot.trim() }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Project could not be connected");
      const optionsResponse = await fetch(`${API}/api/workspace/options`, {
        cache: "no-store",
      });
      if (!optionsResponse.ok)
        throw new Error(
          "Project connected, but the project list could not refresh",
        );
      const options = (await optionsResponse.json()) as WorkspaceOptions;
      setWorkspaceOptions(options);
      setWorkspaceProject(payload.project.id);
      setProjectRoot("");
      setProjectSelectionNotice("");
      setActionNotice(
        "Project connected and indexed read-only. No project files were changed.",
      );
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Project could not be connected",
      );
    } finally {
      setProjectConnecting(false);
    }
  }

  async function createProject() {
    if (!projectRoot.trim()) return;
    setProjectConnecting(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/projects/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({ root: projectRoot.trim() }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Project could not be created");
      const optionsResponse = await fetch(`${API}/api/workspace/options`, { cache: "no-store" });
      if (!optionsResponse.ok)
        throw new Error("Project created, but the project list could not refresh");
      setWorkspaceOptions((await optionsResponse.json()) as WorkspaceOptions);
      setWorkspaceProject(payload.project.id);
      setProjectRoot("");
      setProjectSelectionNotice("");
      setActionNotice("New project created with manifest.md and goals.json, then selected in TGRAM.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project could not be created");
    } finally {
      setProjectConnecting(false);
    }
  }

  async function browseProject() {
    setProjectBrowsing(true);
    setError("");
    setProjectSelectionNotice("");
    try {
      const response = await fetch(`${API}/api/projects/browse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Folder browser could not open");
      if (payload.cancelled || !payload.root) {
        setProjectSelectionNotice(
          "Folder selection cancelled. No project was connected.",
        );
        return;
      }
      setProjectRoot(String(payload.root));
      setProjectSelectionNotice(
        "Folder selected. Nothing has been read or connected yet.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Folder browser could not open",
      );
    } finally {
      setProjectBrowsing(false);
    }
  }

  async function projectRecordAction(
    path: "organization" | "access" | "intent" | "goals" | "ideas" | "ideas/status",
    body: Record<string, unknown>,
    notice: string,
  ) {
    setProjectMetadataBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/projects/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"](body),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Project record could not be updated");
      const optionsResponse = await fetch(`${API}/api/workspace/options`, {
        cache: "no-store",
      });
      if (!optionsResponse.ok)
        throw new Error("Project updated, but its records could not refresh");
      setWorkspaceOptions((await optionsResponse.json()) as WorkspaceOptions);
      setActionNotice(notice);
      return true;
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Project record could not be updated",
      );
      return false;
    } finally {
      setProjectMetadataBusy(false);
    }
  }

  async function addProjectIdea(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspaceProject) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const saved = await projectRecordAction(
      "ideas",
      {
        project_id: selectedWorkspaceProject.id,
        title: String(fields.get("title") || ""),
        detail: String(fields.get("detail") || ""),
      },
      "Idea saved to the selected project. No ticket or run was created.",
    );
    if (saved) form.reset();
  }

  async function changeProjectAccess(executionMode: WorkspaceProject["execution_mode"]) {
    if (!selectedWorkspaceProject) return;
    await projectRecordAction("access", {
      project_id: selectedWorkspaceProject.id,
      execution_mode: executionMode,
    }, `Project execution mode changed to ${plainAction(executionMode)}.`);
  }

  async function saveProjectIntent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspaceProject) return;
    const fields = new FormData(event.currentTarget);
    await projectRecordAction(
      "intent",
      { project_id: selectedWorkspaceProject.id, project_manifest: String(fields.get("project_manifest") || "") },
      "manifest.md updated.",
    );
  }

  async function addProjectGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspaceProject) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const saved = await projectRecordAction("goals", {
      project_id: selectedWorkspaceProject.id,
      action: "add",
      title: String(fields.get("title") || ""),
      goal: String(fields.get("goal") || ""),
    }, "Goal appended to goals.json.");
    if (saved) form.reset();
  }

  async function deleteProjectGoal(index: number) {
    if (!selectedWorkspaceProject) return;
    await projectRecordAction("goals", {
      project_id: selectedWorkspaceProject.id,
      action: "delete",
      index,
    }, "Goal removed from goals.json.");
  }

  async function suggestProjectIdeas() {
    if (!selectedWorkspaceProject) return;
    setIdeaSuggestionBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/projects/ideas/suggest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({ project_id: selectedWorkspaceProject.id }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(
          payload.error || "AI suggestions could not be generated",
        );
      const result = payload as IdeaSuggestionResponse;
      setIdeaSuggestions(result);
      setActionNotice(
        `${result.suggestions.length} AI suggestion(s) returned from a read-only source mirror. Nothing was saved or authorized.`,
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "AI suggestions could not be generated",
      );
    } finally {
      setIdeaSuggestionBusy(false);
    }
  }

  async function organizeProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspaceProject) return;
    const fields = new FormData(event.currentTarget);
    await projectRecordAction(
      "organization",
      {
        project_id: selectedWorkspaceProject.id,
        organization: String(fields.get("organization") || ""),
      },
      "Organization label saved. It groups projects but grants no authority.",
    );
  }

  async function sandboxAction(
    path:
      | "start"
      | "discard"
      | "satisfy-validation"
      | "run-validation-worker"
      | "import-validation-report"
      | "approve-promotion"
      | "promote"
      | "recover"
      | "reconcile",
    body: Record<string, unknown>,
  ): Promise<boolean> {
    setTicketBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/sandboxes/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"](body),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Sandbox action failed");
      setActionNotice(completedAction(path));
      await refresh();
      return true;
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Sandbox action failed",
      );
      return false;
    } finally {
      setTicketBusy(false);
    }
  }

  async function resumeActivity(kind: string) {
    setTicketBusy(true);
    setError("");
    try {
      const path = kind === "PROJECT_WORKSPACE" ? "workspace" : "sandboxes";
      const response = await fetch(`${API}/api/${path}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Activity could not resume");
      setActionNotice(
        "Run resumed from its last durable checkpoint with the same limits and authority.",
      );
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Activity could not resume",
      );
    } finally {
      setTicketBusy(false);
    }
  }

  async function cancelActivity(kind: string) {
    const reason =
      window.prompt("Why should this scheduled work be cancelled?") || "";
    if (!reason.trim()) return;
    setTicketBusy(true);
    setError("");
    try {
      const path = kind === "PROJECT_WORKSPACE" ? "workspace" : "sandboxes";
      const response = await fetch(`${API}/api/${path}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({ actor: "Observer user", reason }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Activity could not be cancelled");
      setActionNotice(
        "Cancellation recorded. Temporary resources will be disposed without applying unapproved files.",
      );
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Activity could not be cancelled",
      );
    } finally {
      setTicketBusy(false);
    }
  }

  async function configureProjectPolicy(policy: GovernancePolicy) {
    const workers = window.prompt(
      "Permitted worker IDs, comma separated (* allows configured workers):",
      policy.permitted_worker_ids.join(", "),
    );
    const validations = window.prompt(
      "Required validation categories, comma separated:",
      policy.required_validation_categories.join(", "),
    );
    const planApprovers = window.prompt(
      "Plan approver identities, comma separated:",
      policy.plan_approvers.join(", "),
    );
    const promotionApprovers = window.prompt(
      "Promotion approver identities, comma separated:",
      policy.promotion_approvers.join(", "),
    );
    const actorRoles = window.prompt(
      "Actor roles as JSON (identity to role list):",
      JSON["stringify"](policy.actor_roles),
    );
    const approvalRules = window.prompt(
      "Approval rules as JSON:",
      JSON["stringify"](policy.approval_rules),
    );
    const artifactRequirements = window.prompt(
      "Artifact validation requirements as JSON:",
      JSON["stringify"](policy.artifact_validation_requirements),
    );
    const reason = window.prompt("Why is this project policy changing?");
    if (
      [
        workers,
        validations,
        planApprovers,
        promotionApprovers,
        actorRoles,
        approvalRules,
        artifactRequirements,
        reason,
      ].some((value) => value === null) ||
      !reason?.trim()
    )
      return;
    setTicketBusy(true);
    setError("");
    try {
      const values = (value: string | null) =>
        (value || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
      const response = await fetch(`${API}/api/projects/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON["stringify"]({
          project_id: policy.project_id,
          permitted_worker_ids: values(workers),
          required_validation_categories: values(validations),
          plan_approvers: values(planApprovers),
          promotion_approvers: values(promotionApprovers),
          actor_roles: JSON.parse(actorRoles || "{}"),
          approval_rules: JSON.parse(approvalRules || "[]"),
          artifact_validation_requirements: JSON.parse(
            artifactRequirements || "{}",
          ),
          max_ticket_budget: policy.max_ticket_budget,
          actor: "Observer user",
          reason,
        }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "Project policy update failed");
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Project policy update failed",
      );
    } finally {
      setTicketBusy(false);
    }
  }

  if (initialLoading)
    return (
      <main className="service-state" aria-live="polite">
        <i />
        <h1>Opening Observer</h1>
        <p>Loading projects, tickets, and saved runs.</p>
      </main>
    );
  if (error && !snapshot.generated_at && !snapshot.connected)
    return (
      <main className="service-state">
        <h1>Observer unavailable</h1>
        <p role="alert">{error}</p>
        <button className="primary" onClick={refresh}>
          Retry
        </button>
        <small>No project action was taken.</small>
      </main>
    );

  const selected =
    snapshot.nodes.find((node) => node.id === selectedId) || snapshot.nodes[0];
  const tasks = snapshot.nodes
    .filter((node) => node.node_type === "task")
    .sort((a, b) => (a.depth || 0) - (b.depth || 0));
  const attempts = snapshot.nodes
    .filter((node) => node.node_type === "attempt")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const evidenceClaims = snapshot.nodes.filter(
    (node) => node.node_type === "claim" && (node.evidence?.length || 0) > 0,
  );
  const clusters = snapshot.nodes.filter(
    (node) => node.node_type === "cluster",
  );
  const verdicts = snapshot.nodes.filter(
    (node) => node.node_type === "conflict_verdict",
  );
  const reconstructions = snapshot.nodes.filter(
    (node) => node.node_type === "reconstruction",
  );
  const reconstructionSteps = snapshot.nodes
    .filter((node) => node.node_type === "reconstruction_step")
    .sort((a, b) => (a.sequence || 0) - (b.sequence || 0));
  const promotions = snapshot.nodes
    .filter((node) => node.node_type === "promotion")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const benchmarks = snapshot.nodes
    .filter((node) => node.node_type === "benchmark")
    .sort((a, b) => (a.case_id || "").localeCompare(b.case_id || ""));
  const pathways = snapshot.nodes
    .filter((node) => node.node_type === "pathway")
    .sort((a, b) => (a.version || 0) - (b.version || 0));
  const pathwayDecisions = snapshot.nodes
    .filter((node) => node.node_type === "pathway_decision")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const pathwayBenchmarks = snapshot.nodes.filter(
    (node) => node.node_type === "pathway_benchmark",
  );
  const planDecisions = snapshot.nodes
    .filter((node) => node.node_type === "plan_decision")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const planningRuns = snapshot.nodes.filter(
    (node) => node.node_type === "planning_run",
  );
  const executions = snapshot.nodes
    .filter((node) => node.node_type === "execution_attempt")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const routePredictions = snapshot.nodes
    .filter((node) => node.node_type === "route_prediction")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const policyUpdates = snapshot.nodes
    .filter((node) => node.node_type === "routing_policy_update")
    .sort((a, b) => (a.version || 0) - (b.version || 0));
  const routeEvaluations = snapshot.nodes
    .filter((node) => node.node_type === "route_evaluation")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const projects = snapshot.nodes.filter(
    (node) => node.node_type === "project",
  );
  const projectScans = snapshot.nodes
    .filter((node) => node.node_type === "project_scan")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));

  const projectFiles = snapshot.nodes.filter(
    (node) => node.node_type === "project_file",
  );
  const repairProposals = snapshot.nodes.filter(
    (node) => node.node_type === "repair_proposal",
  );
  const repairValidations = snapshot.nodes.filter(
    (node) => node.node_type === "repair_validation",
  );
  const repairApprovals = snapshot.nodes.filter(
    (node) => node.node_type === "repair_approval",
  );
  const repairPromotions = snapshot.nodes.filter(
    (node) => node.node_type === "repair_promotion",
  );
  const postRepairReconciliations = snapshot.nodes.filter(
    (node) => node.node_type === "post_repair_reconciliation",
  );
  const maintenanceWorkflows = snapshot.nodes.filter(
    (node) => node.node_type === "maintenance_workflow",
  );
  const projectLeases = snapshot.nodes.filter(
    (node) => node.node_type === "project_lease",
  );
  const evaluationRuns = snapshot.nodes.filter(
    (node) => node.node_type === "evaluation_run",
  );
  const evaluationResults = snapshot.nodes.filter(
    (node) => node.node_type === "evaluation_result",
  );
  const codexReadOnlyProofs = snapshot.nodes.filter(
    (node) => node.node_type === "codex_readonly_proof",
  );
  const recursiveCodexProofs = snapshot.nodes.filter(
    (node) => node.node_type === "recursive_codex_proof",
  );
  const genericCodexEvaluations = snapshot.nodes.filter(
    (node) => node.node_type === "generic_codex_evaluation",
  );
  const investigationSessions = snapshot.nodes.filter(
    (node) => node.node_type === "investigation_session",
  );
  const resumableSessionEvaluations = snapshot.nodes.filter(
    (node) => node.node_type === "resumable_session_evaluation",
  );
  const unrealIndexScans = snapshot.nodes.filter(
    (node) => node.node_type === "unreal_index_scan",
  );
  const unrealArtifacts = snapshot.nodes.filter(
    (node) => node.node_type === "unreal_artifact",
  );
  const unrealDependencies = snapshot.nodes.filter(
    (node) => node.node_type === "unreal_dependency",
  );






  const workspaceHistory = snapshot.nodes
    .filter((node) => node.node_type === "project_workspace_result")
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  const tickets = snapshot.nodes
    .filter((node) => node.node_type === "ticket")
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  const activeTicket = tickets.find((ticket) => ticket.id === activeTicketId);
  const ticketArtifacts = activeTicket?.eligible_ticket_evidence || [];
  const ticketEvents = snapshot.nodes
    .filter(
      (node) =>
        node.node_type === "ticket_event" && node.ticket_id === activeTicketId,
    )
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  const ticketPlans = workspaceHistory.filter(
    (node) => node.ticket_id === activeTicketId && node.kind === "CHANGE_PLAN",
  );
  const currentTicketPlans = ticketPlans.slice(0, 1);
  const ticketSandboxes = snapshot.nodes
    .filter(
      (node) =>
        node.node_type === "implementation_sandbox" &&
        node.ticket_id === activeTicketId &&
        node.plan_record_id === currentTicketPlans[0]?.id,
    )
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  const governanceDecisions = [
    ...ticketPlans.flatMap((plan) => plan.approval_history || []),
    ...ticketSandboxes.flatMap((attempt) => [
      ...(attempt.promotion_approval_history || []),
      ...(attempt.validation_decisions?.flatMap(
        (decision) => decision.attestation_history || [],
      ) || []),
    ]),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const selectedWorkspaceProject = workspaceOptions?.projects.find(
    (project) => project.id === workspaceProject,
  );
  const chooseWorkspaceProject = (projectId: string) => {
    projectSelectionExplicit.current = true;
    setWorkspaceProject(projectId);
    setActiveTicketId((currentTicketId) => {
      const currentTicket = tickets.find((ticket) => ticket.id === currentTicketId);
      return currentTicket?.project_id === projectId ? currentTicketId : "";
    });
    setIdeaSuggestions(null);
  };
  const selectedProjectIdeas = selectedWorkspaceProject?.ideas || [];
  const currentIdeaSuggestions =
    ideaSuggestions?.project_id === workspaceProject &&
    ideaSuggestions.index_scan_id === selectedWorkspaceProject?.index_scan_id
      ? ideaSuggestions
      : null;
  const organizationGroups = Object.entries(
    (workspaceOptions?.projects || []).reduce<
      Record<string, WorkspaceProject[]>
    >((groups, project) => {
      const organization = project.organization || "Personal";
      (groups[organization] ||= []).push(project);
      return groups;
    }, {}),
  ).sort(([left], [right]) => left.localeCompare(right));
  const selectedGovernancePolicy =
    snapshot.workspace?.governance_policies?.find(
      (policy) => policy.project_id === workspaceProject,
    );
  const workspaceRunning =
    snapshot.project_workspace?.status === "QUEUED" ||
    snapshot.project_workspace?.status === "RUNNING";
  const activeWorkItem = snapshot.workspace?.work_items.find(
    (item) => item.ticket_id === activeTicketId,
  );
  const overviewWorkItems = snapshot.workspace?.work_items || [];
  const selectedOverviewIndex = overviewWorkItems.findIndex(
    (item) => item.ticket_id === activeTicketId,
  );
  const overviewTicketIndex = selectedOverviewIndex >= 0 ? selectedOverviewIndex : 0;
  const overviewTicket = overviewWorkItems[overviewTicketIndex];
  const selectOverviewTicket = (index: number) => {
    const item = overviewWorkItems[index];
    if (!item) return;
    setActiveTicketId(item.ticket_id);
    setWorkspaceProject(item.project_id);
  };
  const activeDurableActivity = snapshot.workspace?.durable_activities.find(
    (item) =>
      item.ticket_id === activeTicketId &&
      !["COMPLETED", "CANCELLED"].includes(item.status),
  );
  const anyDurableActivity = snapshot.workspace?.durable_activities.find(
    (item) => ["RUNNING", "QUEUED", "INTERRUPTED"].includes(item.status),
  );
  const currentStage = activeDurableActivity
    ? activeDurableActivity.status === "INTERRUPTED"
      ? "Recovery needed"
      : plainStage(activeDurableActivity.stage)
    : activeWorkItem?.status.replaceAll("_", " ") ||
      (activeTicket
        ? activeTicket.status.replaceAll("_", " ")
        : selectedWorkspaceProject
          ? "Project ready"
          : "No project selected");
  const nextAction =
    activeDurableActivity?.status === "INTERRUPTED"
      ? "Resume saved work"
      : (activeWorkItem ? plainAction(activeWorkItem.action_label) : "") ||
        (activeTicket
          ? "Review ticket"
          : selectedWorkspaceProject
            ? "Create a ticket"
            : "Connect a project");
  const currentBlocker =
    activeDurableActivity?.error ||
    activeWorkItem?.exhausted_budgets.join(", ") ||
    (activeTicket?.status === "BLOCKED" ? activeWorkItem?.detail : "");
  const totalTokenUsage = snapshot.metrics.total_token_usage || 0;
  const potentialTotalTokenUsage =
    snapshot.metrics.potential_total_token_usage || totalTokenUsage;
  const measuredTokensAvoided = snapshot.metrics.measured_avoided_tokens || 0;
  const tokenSavingsPercent = potentialTotalTokenUsage
    ? (measuredTokensAvoided / potentialTotalTokenUsage) * 100
    : 0;
  const inspectNode = (id: string) => {
    setSelectedId(id);
    setActiveTab("lab");
  };
  const tabs = [
    {
      id: "work",
      label: "Overview",
      count: snapshot.workspace?.needs_attention || 0,
    },
    { id: "tickets", label: "Tickets", count: tickets.length },
    {
      id: "projects",
      label: "Projects",
      count:
        workspaceOptions?.projects.length ||
        snapshot.metrics.onboarded_projects ||
        0,
    },
    {
      id: "activity",
      label: "Runs",
      count:
        snapshot.workspace?.durable_activities.filter((item) =>
          ["RUNNING", "QUEUED", "INTERRUPTED"].includes(item.status),
        ).length || 0,
    },
    { id: "models", label: "Models", count: modelSettings?.roles.length || 0 },
    { id: "lab", label: "Inspect", count: tasks.length },
    { id: "savings", label: "Savings", count: 0 },
  ] as const;

  if (profileChecking) {
    return <main className="auth-landing"><div className="auth-loading" aria-live="polite">Opening TGRAM…</div></main>;
  }

  if (!profileSession) {
    return (
      <main className="auth-landing">
        <section className="auth-intro">
          <div className="brandmark" aria-hidden="true">TG</div>
          <p className="eyebrow">TOKENIZED-GRAPH RECURSIVE AGENT MEMORY</p>
          <h1>Your work remembers where it was going.</h1>
          <p>
            TGRAM keeps each person&apos;s conversations and memory separate on this machine.
            Log in to continue, or create a local profile to begin.
          </p>
          <ul>
            <li>Machine-local profiles</li>
            <li>Separated conversational memory</li>
            <li>No cloud account required</li>
          </ul>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <div className="auth-mode" role="tablist" aria-label="Profile access">
            <button type="button" role="tab" aria-selected={profileMode === "LOGIN"}
              className={profileMode === "LOGIN" ? "active" : ""}
              onClick={() => { setProfileMode("LOGIN"); setProfileError(""); setProfilePasswordConfirmation(""); }}>Log in</button>
            <button type="button" role="tab" aria-selected={profileMode === "CREATE"}
              className={profileMode === "CREATE" ? "active" : ""}
              onClick={() => { setProfileMode("CREATE"); setProfileError(""); }}>Create profile</button>
          </div>
          <form onSubmit={submitProfile}>
            <div>
              <p className="eyebrow">{profileMode === "LOGIN" ? "WELCOME BACK" : "NEW LOCAL PROFILE"}</p>
              <h2 id="auth-title">{profileMode === "LOGIN" ? "Log in to TGRAM" : "Create your profile"}</h2>
              <small>Names are only stored when you enter them yourself.</small>
            </div>
            {profileMode === "LOGIN" ? (
              profiles.length ? <>
                <label htmlFor="landing-profile-id">Profile</label>
                <select id="landing-profile-id" value={profileId} onChange={(event) => setProfileId(event.target.value)} required>
                  <option value="" disabled>Select a profile</option>
                  {profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}
                </select>
              </> : <p className="auth-empty">No local profiles exist yet. Create the first profile to continue.</p>
            ) : <>
              <label htmlFor="landing-profile-name">Profile name</label>
              <input id="landing-profile-name" value={profileName} maxLength={80} required
                onChange={(event) => setProfileName(event.target.value)} autoComplete="username" />
              <label htmlFor="landing-profile-style">Preferred response style</label>
              <select id="landing-profile-style" value={profileStyle}
                onChange={(event) => setProfileStyle(event.target.value as MachineProfile["response_style"])}>
                <option value="CONCISE">Concise</option><option value="BALANCED">Balanced</option><option value="DETAILED">Detailed</option>
              </select>
            </>}
            {(profileMode === "CREATE" || profiles.length > 0) && <>
              <label htmlFor="landing-profile-password">Password</label>
              <div className="password-control">
                <input id="landing-profile-password" type={showProfilePassword ? "text" : "password"}
                  value={profilePassword} minLength={8} required
                  onChange={(event) => setProfilePassword(event.target.value)}
                  autoComplete={profileMode === "CREATE" ? "new-password" : "current-password"} />
                <button type="button" aria-label={showProfilePassword ? "Hide password" : "Show password"}
                  aria-pressed={showProfilePassword} onClick={() => setShowProfilePassword((visible) => !visible)}>
                  <span aria-hidden="true">👁</span>
                </button>
              </div>
              {profileMode === "CREATE" && <>
                <label htmlFor="landing-profile-password-confirmation">Enter password again</label>
                <div className="password-control">
                  <input id="landing-profile-password-confirmation" type={showProfilePassword ? "text" : "password"}
                    value={profilePasswordConfirmation} minLength={8} required
                    onChange={(event) => setProfilePasswordConfirmation(event.target.value)}
                    autoComplete="new-password" />
                  <button type="button" aria-label={showProfilePassword ? "Hide passwords" : "Show passwords"}
                    aria-pressed={showProfilePassword} onClick={() => setShowProfilePassword((visible) => !visible)}>
                    <span aria-hidden="true">👁</span>
                  </button>
                </div>
              </>}
              <small>Use at least 8 characters. The password itself is never stored.</small>
            </>}
            {profileError && <p className="auth-error" role="alert">{profileError}</p>}
            <button className="primary auth-submit" type="submit"
              disabled={profileBusy || !profilePassword || (profileMode === "CREATE"
                ? !profileName.trim() || !profilePasswordConfirmation || profilePassword !== profilePasswordConfirmation
                : !profileId)}>
              {profileBusy ? "Please wait…" : profileMode === "CREATE" ? "Create and continue" : "Log in"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className={`shell ${theme === "DARK" ? "dark-theme" : "light-theme"}`}>
      <header className="topbar">
        <div className="brand">
          <span className="brandmark">TG</span>
          <span>TGRAM</span>
          <small>Observer</small>
        </div>
        <div className="view-tabs" role="tablist" aria-label="Observer views">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              id={`tab-${tab.id}`}
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`view-${tab.id}`}
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}
            >
              <span>{tab.label}</span>
              <b>{tab.count}</b>
            </button>
          ))}
        </div>
        <div
          className={`connection ${snapshot.connected ? "online" : "offline"}`}
        >
          <i /> {snapshot.connected ? "Workspace connected" : "Connecting"}
          <span>
            {snapshot.running
              ? "Background work running"
              : snapshot.generated_at
                ? `Updated ${new Date(snapshot.generated_at).toLocaleTimeString()}`
                : "Waiting"}
          </span>
        </div>
        <div className="account-control">
          <button
            type="button"
            className="account-trigger"
            aria-label="Account and personalization"
            aria-expanded={accountOpen}
            onClick={() => setAccountOpen((open) => !open)}
          >
            <span aria-hidden="true">
              {(profileSession?.profile.name.trim()[0] || "P").toUpperCase()}
            </span>
            <b>{profileSession?.profile.name || "Profiles"}</b>
          </button>
          {accountOpen && (
            <form className="account-menu" onSubmit={submitProfile}>
              <div>
                <p className="eyebrow">LOCAL ACCOUNT</p>
                <h2>{profileSession ? profileSession.profile.name : "Profile login"}</h2>
                <small>Profiles and password hashes stay on this machine.</small>
              </div>
              {profileSession ? (
                <>
                  <fieldset className="theme-picker">
                    <legend>Appearance</legend>
                    <button type="button" className={theme === "LIGHT" ? "active" : ""}
                      aria-pressed={theme === "LIGHT"} onClick={() => chooseTheme("LIGHT")}>
                      Light
                    </button>
                    <button type="button" className={theme === "DARK" ? "active" : ""}
                      aria-pressed={theme === "DARK"} onClick={() => chooseTheme("DARK")}>
                      Dark
                    </button>
                  </fieldset>
                  <button type="button" onClick={() => void logoutProfile()}>Log out</button>
                </>
              ) : <>
                {profiles.length > 0 && <>
                  <label htmlFor="profile-id">Existing profile</label>
                  <select id="profile-id" value={profileId} onChange={(event) => setProfileId(event.target.value)}>
                    {profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}
                  </select>
                  <small>Or enter a new profile name below to create another profile.</small>
                </>}
                <label htmlFor="profile-name">{profiles.length ? "New profile name (optional)" : "Profile name"}</label>
                <input id="profile-name" value={profileName} maxLength={80}
                  onChange={(event) => setProfileName(event.target.value)} autoComplete="username" />
                <label htmlFor="profile-password">Password</label>
                <input id="profile-password" type="password" value={profilePassword} minLength={8}
                  onChange={(event) => setProfilePassword(event.target.value)} autoComplete="current-password" />
                {profileName.trim() && <>
                  <label htmlFor="profile-style">Preferred response style</label>
                  <select id="profile-style" value={profileStyle} onChange={(event) => setProfileStyle(event.target.value as MachineProfile["response_style"])}>
                    <option value="CONCISE">Concise</option><option value="BALANCED">Balanced</option><option value="DETAILED">Detailed</option>
                  </select>
                </>}
                {profileError && <small role="alert">{profileError}</small>}
                <button className="primary" type="submit" disabled={profileBusy || !profilePassword || (!profileName.trim() && !profileId)}>
                  {profileBusy ? "Please wait…" : profileName.trim() ? "Create profile" : "Log in"}
                </button>
              </>}
            </form>
          )}
        </div>
      </header>

      {activeTab !== "work" && <>
      <section
        className="work-context"
        aria-label="Active work context"
        aria-live="polite"
      >
        <div
          className="context-identity"
          role="group"
          aria-label="Selected project"
        >
          <small>SELECTED PROJECT</small>
          <b>{selectedWorkspaceProject?.name || "None selected"}</b>
          <span>
            {selectedWorkspaceProject?.root ||
              "Connect or select a local folder"}
          </span>
        </div>
        <div
          className="context-identity"
          role="group"
          aria-label="Selected ticket"
        >
          <small>SELECTED TICKET</small>
          <b>{activeTicket?.title || "None selected"}</b>
          <span>
            {activeTicket
              ? `${activeTicket.priority} · ${activeTicket.status.replaceAll("_", " ")}`
              : "Create or select a ticket"}
          </span>
        </div>
        <div>
          <small>CURRENT STATE</small>
          <b>{currentStage}</b>
          <span>
            {currentBlocker
              ? `Blocked: ${currentBlocker}`
              : "No recorded blocker"}
          </span>
        </div>
        <div>
          <small>NEXT AVAILABLE ACTION</small>
          <b>{nextAction}</b>
          <span>
            {activeDurableActivity?.status === "INTERRUPTED"
              ? "Continues from the last saved checkpoint without changing authority."
              : activeWorkItem?.detail || "Open the relevant view to continue."}
          </span>
        </div>
      </section>

      <section className="active-task" aria-label="Active run" aria-live="polite">
        <div>
          <p className="eyebrow">ACTIVE RUN</p>
          <b>
            {anyDurableActivity
              ? plainStage(anyDurableActivity.stage)
              : "No run is active."}
          </b>
          <span>
            Progress is saved. Interrupted work can be resumed from Runs.
          </span>
        </div>
        <i className={anyDurableActivity ? "working" : "idle"}>
          {anyDurableActivity ? anyDurableActivity.status : "IDLE"}
        </i>
      </section>
      </>}

      {actionNotice && (
        <div className="action-notice" role="status">
          <b>RECORDED</b>
          <span>{actionNotice}</span>
          <button
            onClick={() => setActionNotice("")}
            aria-label="Dismiss recorded action"
          >
            ×
          </button>
        </div>
      )}
      {error && (
        <div className="action-error" role="alert">
          <b>ACTION NOT COMPLETED</b>
          <span>{error}</span>
          <button
            onClick={() => {
              setError("");
              void refresh();
            }}
          >
            Retry refresh
          </button>
        </div>
      )}

      <section
        id="view-work"
        role="tabpanel"
        aria-labelledby="tab-work"
        hidden={activeTab !== "work"}
        className="daily-workspace"
      >
        <div className="daily-heading">
          <div>
            <p className="eyebrow">OVERVIEW</p>
            <h1>Work requiring a decision.</h1>
            <p className="lede">
              Tickets are ordered by current state and next available action.
            </p>
          </div>
          <div className="metrics">
            <article>
              <span>{snapshot.workspace?.needs_attention || 0}</span>
              <p>Needs attention</p>
              <small>Approval, recovery, validation, or completion</small>
            </article>
            <article>
              <span>{snapshot.workspace?.in_progress || 0}</span>
              <p>Running</p>
              <small>Saved work in progress</small>
            </article>
            <article>
              <span>{snapshot.workspace?.completed || 0}</span>
              <p>Complete</p>
              <small>Closed or rejected tickets</small>
            </article>
          </div>
          <section className="overview-context" aria-label="Overview work context">
            <div>
              <small>SELECTED PROJECT</small>
              <b>{selectedWorkspaceProject?.name || "None selected"}</b>
              <span>{selectedWorkspaceProject?.root || "Connect or select a local folder"}</span>
            </div>
            <div>
              <small>SELECTED TICKET</small>
              <b>{activeTicket?.title || "None selected"}</b>
              <span>{activeTicket ? `${activeTicket.priority} · ${activeTicket.status.replaceAll("_", " ")}` : "Create or select a ticket"}</span>
            </div>
            <div>
              <small>CURRENT STATE</small>
              <b>{currentStage}</b>
              <span>{currentBlocker ? `Blocked: ${currentBlocker}` : "No recorded blocker"}</span>
            </div>
            <div>
              <small>NEXT AVAILABLE ACTION</small>
              <b>{nextAction}</b>
              <span>{activeWorkItem?.detail || "Open the relevant view to continue."}</span>
            </div>
          </section>
          <section className="overview-run" aria-label="Active run" aria-live="polite">
            <div>
              <small>ACTIVE RUN</small>
              <b>{anyDurableActivity ? plainStage(anyDurableActivity.stage) : "No run is active."}</b>
            </div>
            <i className={anyDurableActivity ? "working" : "idle"}>
              {anyDurableActivity ? anyDurableActivity.status : "IDLE"}
            </i>
          </section>
        </div>
        <div className="work-queue">
          {overviewTicket ? (
            <>
              <button
                key={overviewTicket.ticket_id}
                className={`work-item urgency-${overviewTicket.urgency.toLowerCase()}`}
                onClick={() => {
                  setActiveTicketId(overviewTicket.ticket_id);
                  setWorkspaceProject(overviewTicket.project_id);
                  setActiveTab(
                    overviewTicket.action === "INVESTIGATE" ? "projects" : "tickets",
                  );
                }}
              >
                <span className="work-priority">
                  {overviewTicket.priority} · {overviewTicket.status.replaceAll("_", " ")}
                </span>
                <b>{overviewTicket.title}</b>
                <strong>{plainAction(overviewTicket.action_label)}</strong>
                <small>
                  {overviewTicket.detail} · {overviewTicket.resolved_criteria}/
                  {overviewTicket.total_criteria}{" "}
                  acceptance criteria resolved
                </small>
              </button>
              {overviewWorkItems.length > 1 && (
                <nav className="overview-ticket-navigation" aria-label="Overview tickets">
                  <button
                    type="button"
                    disabled={overviewTicketIndex === 0}
                    onClick={() => selectOverviewTicket(overviewTicketIndex - 1)}
                  >
                    Previous ticket
                  </button>
                  <span aria-live="polite">
                    Ticket {overviewTicketIndex + 1} of {overviewWorkItems.length}
                  </span>
                  <button
                    type="button"
                    disabled={overviewTicketIndex === overviewWorkItems.length - 1}
                    onClick={() => selectOverviewTicket(overviewTicketIndex + 1)}
                  >
                    Next ticket
                  </button>
                </nav>
              )}
            </>
          ) : (
            <div className="empty-state">
              <b>No tickets</b>
              <span>
                {workspaceOptions?.projects.length
                  ? "There is no recorded work for the selected projects."
                  : "No local project is connected."}
              </span>
              {!workspaceOptions?.projects.length && (
                <button
                  className="primary"
                  onClick={() => setActiveTab("projects")}
                >
                  Connect project
                </button>
              )}
            </div>
          )}
        </div>
        <section className={`overview-chat chat-text-${chatTextSize.toLowerCase()}`} aria-label="TGRAM conversation">
          <div className="chat-library-tools" aria-label="Conversation and learning tools">
          <LearningLibrary key={workspaceProject} api={API} token={profileSession.token} projectId={workspaceProject} />
          <ConversationMemory sessions={savedConversations} sessionId={chatSessionId} busy={chatBusy}
            onShare={workspaceProject ? (fact) => shareConversationFact(API, profileSession.token, workspaceProject, fact) : undefined}
            error={memoryError} onRefresh={() => void refreshConversationMemory()}
            onSelect={(id) => restoreConversation(savedConversations.find((session) => session.id === id))}
            onCorrect={(fact) => {
              const source = savedConversations.find((session) => session.id === fact.session_id);
              if (source) restoreConversation(source);
              setChatInput(`I want to correct my remembered ${fact.subject.replaceAll("conversation.", "").replaceAll("user.", "")}: “${fact.value}”. The correct value is: `);
              document.getElementById("overview-chat-input")?.focus();
            }} />
          </div>
          <div className="chat-transcript" ref={chatTranscriptRef} role="log" aria-live="polite">
            {chatMessages.length ? (
              chatMessages.map((message, index) => (
                <article className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
                  <b>{message.role === "user" ? "You" : "TGRAM"}</b>
                  <p>{message.content}</p>
                  {message.role === "assistant" && message.turnId && index === chatMessages.length - 1 && message.route !== "RLM_CONVERSATION_TASK" && (
                    <button type="button" disabled={chatBusy} onClick={(event) => void sendChat(event, message)}>
                      {chatBusy ? "Checking answer…" : "Retry answer"}
                    </button>
                  )}
                  {message.ticketId && message.route === "RLM_CONVERSATION_TASK" && (
                    <button type="button" onClick={() => {
                      if (message.projectId) setWorkspaceProject(message.projectId);
                      setActiveTicketId(message.ticketId!);
                      setActiveTab("tickets");
                    }}>Open task and progress</button>
                  )}
                  {message.role === "assistant" && <ResponseMemory receipt={message.memoryReceipt} sessions={savedConversations} />}
                  <details className="response-details"><summary>Response details and evidence</summary>
                  {message.route && <small>Route: {message.route.replaceAll("_", " ")}</small>}
                  {message.operationRoute && <small>Memory operation: {message.operationRoute.replaceAll("_", " ")}</small>}
                  {message.scope && <small>Evidence scope: {message.scope.replaceAll("_", " ")}</small>}
                  {message.investigationMode && <small>Investigation mode: {message.investigationMode.toLowerCase()}</small>}
                  {message.contextClaimIds && message.contextClaimIds.length > 0 && (
                    <small>
                      Reconstructed context: {message.contextClaimIds.length} current claim(s)
                      {message.contextTokenEstimate
                        ? ` · ~${message.contextTokenEstimate} tokens` : ""}
                    </small>
                  )}
                  {message.metrics && (
                    <dl className="chat-metrics">
                      {Object.entries(message.metrics).map(([label, value]) => (
                        <div key={label}>
                          <dt>{label.replaceAll("_", " ")}</dt>
                          <dd>{value === null ? "not measured" : value.toLocaleString()}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {message.routingConfidence !== undefined && <small>Routing confidence: {(message.routingConfidence * 100).toFixed(0)}%</small>}
                  {message.routingReason && <small>{message.routingReason}</small>}
                  {message.confidence !== undefined && message.confidence !== null && <small>Claim confidence: {(message.confidence * 100).toFixed(0)}%</small>}
                  {(message.taskId || message.claimId) && (
                    <small>
                      Investigation: {message.taskId ? shortId(message.taskId) : "—"}
                      {" · claim: "}{message.claimId ? shortId(message.claimId) : "—"}
                    </small>
                  )}
                  {message.evidence && message.evidence.length > 0 && (
                    <details>
                      <summary>{message.evidence.length} grounded evidence item(s)</summary>
                      <ul>
                        {message.evidence.map((item, evidenceIndex) => (
                          <li key={evidenceIndex}>
                            {String(item.path || item.source || "graph evidence")}
                            {item.line ? `:${String(item.line)}` : ""}
                            {item.detail ? ` — ${String(item.detail)}` : ""}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {message.taskTree && message.taskTree.length > 1 && (
                    <details open>
                      <summary>
                        Recursive investigation · {message.taskTree.length - 1} subtask(s)
                        {message.investigationCalls !== undefined
                          ? ` · ${message.investigationCalls} model call(s)` : ""}
                      </summary>
                      {message.planningQuestions && message.planningQuestions.length > 0 && (
                        <p>Planned branches: {message.planningQuestions.join(" · ")}</p>
                      )}
                      <ol>
                        {message.taskTree.map((task) => (
                          <li key={task.id} style={{ marginLeft: `${task.depth * 1.25}rem` }}>
                            <b>{task.depth === 0 ? "Synthesis" : `Depth ${task.depth}`}</b>
                            {" — "}{task.question}
                            <small>
                              {task.status.replaceAll("_", " ")}
                              {task.reused_claim_id ? " · graph memory reused" : " · fresh evidence"}
                              {task.stopping_reason
                                ? ` · ${task.stopping_reason.replaceAll("_", " ")}` : ""}
                            </small>
                          </li>
                        ))}
                      </ol>
                      {message.contradictions && message.contradictions.length > 0 && (
                        <p>{message.contradictions.length} explicit contradiction(s) detected.</p>
                      )}
                      {message.budgetExhausted && (
                        <p>Investigation stopped at its configured model-call or wall-time budget.</p>
                      )}
                    </details>
                  )}
                  </details>
                  {message.claimId && message.workProjectId && (
                    claimTicketClaimId === message.claimId ? (
                      <form
                        className="claim-ticket-form"
                        aria-label="Create user-directed ticket"
                        onSubmit={(event) => void createTicketFromClaim(event, message)}
                      >
                        <label htmlFor={`claim-objective-${message.claimId}`}>
                          Outcome for the person using RLMGraph
                        </label>
                        <textarea
                          id={`claim-objective-${message.claimId}`}
                          value={claimTicketObjective}
                          onChange={(event) => setClaimTicketObjective(event.target.value)}
                          maxLength={2000}
                          required
                          disabled={claimTicketBusy}
                        />
                        <label htmlFor={`claim-criterion-${message.claimId}`}>
                          Observable acceptance criterion
                        </label>
                        <textarea
                          id={`claim-criterion-${message.claimId}`}
                          value={claimTicketCriterion}
                          onChange={(event) => setClaimTicketCriterion(event.target.value)}
                          maxLength={500}
                          required
                          disabled={claimTicketBusy}
                        />
                        <div className="button-row">
                          <button
                            className="primary"
                            type="submit"
                            disabled={
                              claimTicketBusy
                              || !claimTicketObjective.trim()
                              || !claimTicketCriterion.trim()
                            }
                          >
                            {claimTicketBusy ? "Creating ticket…" : "Create governed draft ticket"}
                          </button>
                          <button
                            type="button"
                            disabled={claimTicketBusy}
                            onClick={() => setClaimTicketClaimId(null)}
                          >
                            Cancel
                          </button>
                        </div>
                        <small>
                          This creates a draft linked to claim {shortId(message.claimId)}. It does
                          not authorize planning, implementation, or promotion.
                        </small>
                      </form>
                    ) : (
                      <button
                        type="button"
                        disabled={claimTicketBusy}
                        onClick={() => {
                          setClaimTicketClaimId(message.claimId || null);
                          setClaimTicketObjective("");
                          setClaimTicketCriterion("");
                        }}
                      >
                        Create user-directed ticket from claim
                      </button>
                    )
                  )}
                </article>
              ))
            ) : (
              <div className="empty-state">
                <b>Start a conversation</b>
                <span>Tell TGRAM what you’re working toward, ask a question, or share something you want remembered.</span>
                <span>Explore conversation memory above to see what was recorded and where it came from.</span>
              </div>
            )}
            {chatActivity.length > 0 && (
              <section className="chat-activity" aria-label="RLMGraph activity" aria-live="polite">
                {chatActivity.map((activity, index) => (
                  <article className={`chat-activity-card ${activity.status.toLowerCase()}`} key={`${activity.label}-${index}`}>
                    <span>{activity.status === "ACTIVE" ? "IN PROGRESS" : activity.status}</span>
                    <b>{activity.label}</b>
                    <small>{activity.detail}</small>
                  </article>
                ))}
              </section>
            )}
          </div>
          <form className="chat-compose" onSubmit={sendChat}>
            <div className="chat-options" aria-label="Chat investigation settings">
              <label htmlFor="overview-chat-scope">
                <span>Scope</span>
                <select
                  id="overview-chat-scope"
                  value={chatScope}
                  onChange={(event) => setChatScope(event.target.value as "AUTO" | "SYSTEM" | "PROJECT")}
                  disabled={chatBusy}
                >
                  <option value="AUTO">Automatic</option>
                  <option value="SYSTEM">System</option>
                  <option value="PROJECT">Project</option>
                </select>
              </label>
              <label htmlFor="overview-chat-mode">
                <span>Depth</span>
                <select
                  id="overview-chat-mode"
                  value={chatInvestigationMode}
                  onChange={(event) => setChatInvestigationMode(
                    event.target.value as "AUTO" | "DIRECT" | "RECURSIVE",
                  )}
                  disabled={chatBusy}
                >
                  <option value="AUTO">Automatic</option>
                  <option value="RECURSIVE">Recursive</option>
                  <option value="DIRECT">Direct</option>
                </select>
              </label>
              <label htmlFor="overview-chat-text-size">
                <span>Text</span>
                <select
                  id="overview-chat-text-size"
                  value={chatTextSize}
                  onChange={(event) => chooseChatTextSize(
                    event.target.value as "SMALL" | "MEDIUM" | "LARGE",
                  )}
                >
                  <option value="SMALL">Small</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="LARGE">Large</option>
                </select>
              </label>
            </div>
            <label className="visually-hidden" htmlFor="overview-chat-input">Message</label>
            <textarea
              id="overview-chat-input"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter"
                  && !event.shiftKey
                  && !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Ask TGRAM a question… Enter to send · Shift+Enter for a new line"
              maxLength={4000}
              disabled={chatBusy || !profileSession}
            />
            <button
              className="new-chat-button"
              type="button"
              aria-label="Start a new conversation"
              title="New conversation"
              disabled={chatBusy || chatMessages.length === 0}
              onClick={() => restoreConversation()}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20">
                <path d="M5 5.75h14v10.5H9l-4 3v-13.5Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
                <path d="M12 8.5v5M9.5 11h5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </button>
            <button className="primary" type="submit" disabled={chatBusy || !chatInput.trim() || !profileSession}>
              {!profileSession ? "Log in to chat" : chatBusy ? "Thinking…" : "Send"}
            </button>
          </form>
        </section>
      </section>

      <section
        id="view-tickets"
        role="tabpanel"
        aria-labelledby="tab-tickets"
        hidden={activeTab !== "tickets"}
        className="ticket-workbench"
      >
        <aside className="ticket-board">
          <label>
            <span>Active ticket</span>
            <select
              value={activeTicketId}
              onChange={(event) => {
                const id = event.target.value;
                setActiveTicketId(id);
                const ticket = tickets.find((item) => item.id === id);
                if (ticket?.project_id) setWorkspaceProject(ticket.project_id);
              }}
            >
              <option value="">Choose a ticket</option>
              {tickets.map((ticket) => (
                <option key={ticket.id} value={ticket.id}>
                  {ticket.priority} · {ticket.title}
                </option>
              ))}
            </select>
          </label>
          {activeTicket ? (
            <div className="ticket-detail">
              <div className="activity-head">
                <div>
                  <p className="eyebrow">{activeTicket.priority} PRIORITY</p>
                  <h3>{activeTicket?.title}</h3>
                </div>
                <span
                  className={`diagnostic-status ${statusClass(activeTicket.status)}`}
                >
                  {activeTicket.status === "ACTIVE" ? "Task open" : activeTicket.status}
                </span>
              </div>
              {activeTicket.description !== activeTicket.title && <p>{activeTicket.description}</p>}
              <div className="ticket-workspace-layout">
              <div className="ticket-work-area" aria-label="Ticket work and next step">
              <TicketNextStep key={activeTicket.id}
                status={activeTicket.status} plan={currentTicketPlans[0]} attempt={ticketSandboxes[0]}
                closureReady={activeTicket.closure_ready} busy={ticketBusy || workspaceRunning}
                running={(snapshot.project_workspace?.ticket_id === activeTicket.id && ["QUEUED", "RUNNING"].includes(snapshot.project_workspace.status)) || (snapshot.implementation_sandbox?.ticket_id === activeTicket.id && ["QUEUED", "RUNNING"].includes(snapshot.implementation_sandbox.status))}
                onPlan={() => void createNextTicketPlan()}
                onDecision={(decision, reason) => ticketAction("approve-plan", { ticket_id: activeTicket.id, plan_record_id: currentTicketPlans[0].id, actor: "Local user", decision, reason })}
                onImplement={() => void sandboxAction("start", { ticket_id: activeTicket.id, plan_record_id: currentTicketPlans[0].id })}
                onResult={() => {
                  setTicketInfo({ ticketId: activeTicket.id, section: "plan" });
                }}
                onFinish={() => void ticketAction("transition", { ticket_id: activeTicket.id, status: "SATISFIED", reason: "User reviewed completion evidence." })}
                onClose={() => void ticketAction("transition", { ticket_id: activeTicket.id, status: "CLOSED", reason: "User closed the satisfied ticket." })}
              />
              <div className="ticket-sections">
              <section id="ticket-plan-results" className="ticket-information-panel" hidden={ticketInfo?.ticketId !== activeTicket.id || ticketInfo.section !== "plan"} aria-label="plan">
                <h4 className="ticket-information-heading"><b>Plan and implementation</b><span>{currentTicketPlans[0]?.approval_status || "No plan yet"} · {ticketSandboxes.length} run(s)</span></h4>
                <p className="ticket-section-help">The plan describes the proposed changes. An implementation run attempts those changes in an isolated copy. Approving a plan does not mean the changes have been made or applied to your project.</p>
                {!currentTicketPlans.length && <p className="ticket-section-feedback">No plan has been recorded yet. Use Create plan in the next-step panel to begin.</p>}
                {currentTicketPlans[0]?.approval_status === "DENIED" && <p className="ticket-section-feedback">The current plan was rejected. The task remains open, but this plan cannot start implementation. Request a replacement from the next-step panel when you are ready.</p>}
                {!!currentTicketPlans.length && !ticketSandboxes.length && <p className="ticket-section-feedback">There are no implementation results for this plan yet. Review its proposal and file list before proceeding through the next step.</p>}
              <div className="sandbox-panel">
                <div>
                  <b id="ticket-implementation-results">Implementation runs</b>
                  <span>
                    {snapshot.implementation_sandbox?.ticket_id ===
                    activeTicket.id
                      ? `${snapshot.implementation_sandbox.status.replaceAll("_", " ")} · ${snapshot.implementation_sandbox.stage.replaceAll("_", " ")}`
                      : "An approved plan can start a run in an isolated project copy."}
                  </span>
                </div>
                {currentTicketPlans.map((plan) => (
                  <article key={plan.id}>
                    <div>
                      <b>{plan.prompt}</b>
                      <span>
                        {plan.affected_paths?.length || 0} authorized files ·
                        plan {plan.approval_status} ·{" "}
                        {plan.approval_history?.length || 0} decisions
                      </span>
                      {plan.approval_missing?.map((item) => (
                        <small key={item}>Missing: {item}</small>
                      ))}
                      {plan.approval_expiration_reasons?.map((item) => (
                        <small key={item}>Expired: {item}</small>
                      ))}
                    </div>
                    <div>
                      <p className="ticket-plan-text">{plan.answer || "No readable plan summary was supplied."}</p>
                      <details><summary>Authorized files ({plan.affected_paths?.length || 0})</summary>
                        <div>{plan.affected_paths?.map((path) => <FileChangePreview key={path} path={path} context={plan.answer}
                          change={ticketSandboxes.find((attempt) => attempt.plan_record_id === plan.id)?.changes?.find((change) => change.path === path)} />)}</div>
                      </details>
                      <small>Use the next-step panel above to approve or replace this plan.</small>
                    </div>
                  </article>
                ))}
                {ticketSandboxes.map((attempt) => (
                  <article key={attempt.id}>
                    <button
                      className="sandbox-result"
                      onClick={() => inspectNode(attempt.id)}
                    >
                      <b>
                        {attempt.status} · {attempt.changes?.length || 0}{" "}
                        changed files
                      </b>
                      <span>
                        {attempt.validations?.length || 0} validation checks ·{" "}
                        {attempt.validation_decisions?.filter((item) =>
                          ["PASSED", "SATISFIED"].includes(item.status),
                        ).length || 0}
                        /{attempt.validation_decisions?.length || 0} gates
                        satisfied ·{" "}
                        {attempt.promotion_approval_history?.length || 0} apply
                        decisions · isolated copy removed{" "}
                        {attempt.filesystem_disposed ? "✓" : "✗"}
                      </span>
                      {attempt.promotion_approval_missing?.map((item) => (
                        <small key={item}>Missing: {item}</small>
                      ))}
                      {attempt.promotion_approval_expiration_reasons?.map(
                        (item) => (
                          <small key={item}>Expired: {item}</small>
                        ),
                      )}
                      {attempt.failure_reason && (
                        <small className="run-failure" role="alert">
                          Run failed: {attempt.failure_reason}. No files were
                          applied; open this result for details or discard it.
                        </small>
                      )}
                      <small className="inspect-link">
                        Review files, validation, and recorded authority →
                      </small>
                    </button>
                    {!!attempt.changes?.length && <div className="changed-file-list">
                      <b>Changed files — hover or click to inspect</b>
                      {attempt.changes.map((change) => <FileChangePreview key={change.path} path={change.path} change={change} />)}
                    </div>}
                    {attempt.status === "READY_FOR_REVIEW" &&
                      attempt.validation_decisions
                        ?.filter(
                          (item) =>
                            item.status === "REQUIRED" && item.category !== "REVIEW",
                        )
                        .map((decision) => (
                          <button
                            disabled={ticketBusy}
                            key={decision.id}
                            onClick={() =>
                              sandboxAction("satisfy-validation", {
                                ticket_id: activeTicket.id,
                                attempt_id: attempt.id,
                                decision_id: decision.id,
                                actor:
                                  window.prompt("Validator identity:") || "",
                                decision: "APPROVED",
                                detail:
                                  window.prompt(
                                    `Record evidence for ${decision.path}:`,
                                  ) || "",
                              })
                            }
                          >
                            Record {decision.category} attestation
                          </button>
                        ))}
                    {attempt.status === "READY_FOR_REVIEW" &&
                      !attempt.promotion_approval && (
                        <>
                          <button
                            className="primary"
                            disabled={
                              ticketBusy ||
                              attempt.validation_decisions?.some(
                                (decision) =>
                                  decision.status === "REQUIRED" &&
                                  decision.category !== "REVIEW",
                              )
                            }
                            onClick={() =>
                              void approvePromotionAndApply(
                                activeTicket.id,
                                attempt.id,
                                attempt.validation_decisions
                                  ?.filter(
                                    (decision) =>
                                      decision.status === "REQUIRED" &&
                                      decision.category === "REVIEW",
                                  )
                                  .map((decision) => decision.id) || [],
                              )
                            }
                          >
                            Approve and apply change
                          </button>
                          <button
                            disabled={ticketBusy}
                            onClick={() =>
                              sandboxAction("approve-promotion", {
                                ticket_id: activeTicket.id,
                                attempt_id: attempt.id,
                                actor: "Local user",
                                decision: "DENIED",
                                reason: "User rejected this proposal.",
                              })
                            }
                          >
                            Reject change
                          </button>
                        </>
                      )}
                    {attempt.status === "READY_FOR_REVIEW" &&
                      attempt.promotion_approval?.decision === "APPROVED" &&
                      !attempt.promotion && (
                        <button
                          className="primary"
                          disabled={ticketBusy}
                          onClick={() =>
                            sandboxAction("promote", {
                              ticket_id: activeTicket.id,
                              attempt_id: attempt.id,
                            })
                          }
                        >
                          Apply approved change
                        </button>
                      )}
                    {attempt.promotion?.mutation_journal &&
                      !attempt.promotion.mutation_journal.terminal && (
                        <button
                          className="primary"
                          disabled={ticketBusy}
                          onClick={() =>
                            sandboxAction("recover", {
                              ticket_id: activeTicket.id,
                              attempt_id: attempt.id,
                            })
                          }
                        >
                          Recover interrupted apply
                        </button>
                      )}
                    {!attempt.promotion &&
                      attempt.status !== "DISCARDED" &&
                      attempt.status !== "PROMOTED" && (
                        <button
                          disabled={ticketBusy}
                          onClick={() =>
                            sandboxAction("discard", {
                              ticket_id: activeTicket.id,
                              attempt_id: attempt.id,
                            })
                          }
                        >
                          Discard
                        </button>
                      )}
                  </article>
                ))}
              </div>
              <div className="sandbox-panel">
                {ticketSandboxes.flatMap(
                  (attempt) =>
                    attempt.validation_decisions
                      ?.filter((decision) => decision.status === "REQUIRED")
                      .flatMap((decision) =>
                        snapshot.implementation_sandbox?.validation_workers
                          ?.filter(
                            (worker) =>
                              worker.enabled &&
                              worker.categories.includes(decision.category) &&
                              worker.artifact_kinds.includes(
                                decision.artifact_kind,
                              ),
                          )
                          .map((worker) => (
                            <button
                              key={`${attempt.id}-${decision.id}-${worker.id}`}
                              disabled={ticketBusy}
                              onClick={() =>
                                sandboxAction("run-validation-worker", {
                                  ticket_id: activeTicket.id,
                                  attempt_id: attempt.id,
                                  decision_id: decision.id,
                                  worker_id: worker.id,
                                })
                              }
                            >
                              Run {worker.name} for {decision.path}
                            </button>
                          )),
                      ) || [],
                )}
                {ticketSandboxes.flatMap(
                  (attempt) =>
                    attempt.validation_decisions
                      ?.filter(
                        (decision) =>
                          decision.status === "REQUIRED" &&
                          decision.requires_unreal_editor,
                      )
                      .map((decision) => (
                        <button
                          key={`report-${attempt.id}-${decision.id}`}
                          disabled={ticketBusy}
                          onClick={() =>
                            sandboxAction("import-validation-report", {
                              ticket_id: activeTicket.id,
                              attempt_id: attempt.id,
                              decision_id: decision.id,
                              report_kind: "UNREAL_EDITOR",
                              artifact_path: decision.path,
                              source_manifest_sha256:
                                attempt.initial_manifest_sha256,
                              patch_sha256: attempt.patch_sha256,
                              report_bytes_base64:
                                window.prompt(
                                  "Paste the base64-encoded external Editor report:",
                                ) || "",
                              report_sha256:
                                window.prompt("Paste its SHA-256 digest:") ||
                                "",
                              status: "PASSED",
                              detail:
                                window.prompt(
                                  "Describe the external Editor validation:",
                                ) || "",
                            })
                          }
                        >
                          Import external Editor report for {decision.path}
                        </button>
                      )) || [],
                )}
              </div>
              {ticketSandboxes
                .filter((attempt) => attempt.promotion?.mutation_journal)
                .map((attempt) => (
                  <article
                    className="sandbox-panel"
                    key={`journal-${attempt.id}`}
                  >
                    <div>
                      <b>
                        Crash-safe mutation journal ·{" "}
                        {attempt.promotion?.mutation_journal?.stage}
                      </b>
                      <span>
                        fence{" "}
                        {attempt.promotion?.mutation_journal?.fencing_token} ·{" "}
                        {
                          attempt.promotion?.mutation_journal?.entries.filter(
                            (entry) => entry.replacement_completed,
                          ).length
                        }
                        /{attempt.promotion?.mutation_journal?.entries.length}{" "}
                        replacements completed · validation{" "}
                        {attempt.promotion?.mutation_journal?.validation_state}{" "}
                        · rollback{" "}
                        {attempt.promotion?.mutation_journal?.rollback_state} ·{" "}
                        {attempt.promotion?.mutation_journal?.terminal
                          ? "terminal ✓"
                          : "recovery required"}
                      </span>
                    </div>
                  </article>
                ))}
              {ticketSandboxes
                .filter(
                  (attempt) =>
                    attempt.status === "PROMOTED" &&
                    attempt.promotion &&
                    !attempt.promotion.reconciliation,
                )
                .map((attempt) => (
                  <button
                    className="primary reconciliation-action"
                    key={`reconcile-${attempt.id}`}
                    disabled={ticketBusy}
                    onClick={() =>
                      sandboxAction("reconcile", {
                        ticket_id: activeTicket.id,
                        attempt_id: attempt.id,
                      })
                    }
                  >
                    Refresh project index
                  </button>
                ))}
              </section>
              <section id="ticket-evidence-info" className="ticket-information-panel" hidden={ticketInfo?.ticketId !== activeTicket.id || ticketInfo.section !== "evidence"} aria-label="evidence">
                <h4 className="ticket-information-heading"><b>Evidence and acceptance</b><span>{ticketArtifacts.length} evidence item(s) · {activeTicket.closure_ready ? "Checks resolved" : "Checks pending"}</span></h4>
                <p className="ticket-section-help">Acceptance criteria are the outcomes this task must meet. Evidence is a recorded result, such as a test or reviewed change, that supports an outcome. A plan or an approval alone does not prove the work succeeded.</p>
<section className="ticket-evidence-card" aria-label="Evidence and completion">
              <div
                className={`closure-summary ${activeTicket.closure_ready ? "ready" : "blocked"}`}
              >
                <b>
                  {activeTicket.closure_ready
                    ? "Completion gates resolved"
                    : "Completion blocked"}
                </b>
                <span>
                  {activeTicket.closure_ready
                    ? "Every acceptance criterion has current evidence, an attributed waiver, or an attributed blocker."
                    : `${activeTicket.closure_failures?.length || 0} completion check(s) still need attention. This does not necessarily mean a run failed; it means the ticket cannot be marked finished yet.`}
                </span>
                {activeTicket.closure_failures?.map((failure) => (
                  <small key={failure}>{failure}</small>
                ))}
              </div>
              <section className="ticket-evidence" aria-label="Ticket evidence">
                <h3>Evidence and acceptance</h3>
                <p>{ticketArtifacts.length ? "Open an evidence item to inspect what supports this ticket." : "No eligible evidence has been collected yet."}</p>
                <div className="button-row">{ticketArtifacts.map((item) => (
                  <button key={item.evidence_id} type="button" onClick={() => inspectNode(item.evidence_id)}>
                    {item.artifact_type.replaceAll("_", " ")} · {item.status || "ELIGIBLE"}
                  </button>
                ))}</div>
              </section>
              <div className="criterion-list">
                <p className="ticket-section-help">For each outcome, inspect the evidence before choosing Use evidence. Waive records an intentional exception with your reason. Block records what prevents progress; it does not fix the problem or prove the outcome was met.</p>
                {activeTicket.ticket_criteria?.map((criterion) => {
                  const gate = activeTicket.closure_gates?.find(
                    (item) => item.criterion_id === criterion.id,
                  );
                  const selectedEvidence =
                    criterionEvidence[criterion.id] || "";
                  return (
                    <article key={criterion.id}>
                      <div>
                        <b>{criterion.description}</b>
                        <span>
                          {gate?.resolved ? "RESOLVED" : "UNRESOLVED"} ·{" "}
                          {gate?.explanation || criterion.status}
                        </span>
                        {gate?.evidence_assessments.map((item) => (
                          <small key={item.evidence_id}>
                            {item.artifact_type.replaceAll("_", " ")} ·{" "}
                            {item.status || "RECORDED"} · {item.reason}
                          </small>
                        ))}
                      </div>
                      <div>
                        <select
                          aria-label={`Evidence for ${criterion.description}`}
                          value={selectedEvidence}
                          onChange={(event) =>
                            setCriterionEvidence((current) => ({
                              ...current,
                              [criterion.id]: event.target.value,
                            }))
                          }
                        >
                          <option value="">Choose current evidence</option>
                          {ticketArtifacts.map((item) => (
                            <option
                              key={item.evidence_id}
                              value={item.evidence_id}
                            >
                              {item.artifact_type.replaceAll("_", " ")} ·{" "}
                              {item.status || "ELIGIBLE"}
                            </option>
                          ))}
                        </select>
                        <button
                          disabled={ticketBusy || !selectedEvidence}
                          onClick={() =>
                            ticketAction("criterion", {
                              ticket_id: activeTicket.id,
                              criterion_id: criterion.id,
                              status: "EVIDENCED",
                              evidence_ids: [selectedEvidence],
                              reason: "",
                            })
                          }
                        >
                          Use evidence
                        </button>
                        <button
                          disabled={ticketBusy}
                          onClick={() =>
                            ticketAction("criterion", {
                              ticket_id: activeTicket.id,
                              criterion_id: criterion.id,
                              status: "WAIVED",
                              evidence_ids: [],
                              reason:
                                window.prompt(
                                  "Why is this criterion waived?",
                                ) || "",
                            })
                          }
                        >
                          Waive
                        </button>
                        <button
                          disabled={ticketBusy}
                          onClick={() =>
                            ticketAction("criterion", {
                              ticket_id: activeTicket.id,
                              criterion_id: criterion.id,
                              status: "BLOCKED",
                              evidence_ids: [],
                              reason:
                                window.prompt("What blocks this criterion?") ||
                                "",
                            })
                          }
                        >
                          Block
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
              {!!activeTicket.ineligible_ticket_evidence?.length && (
                <details className="ineligible-evidence">
                  <summary>
                    Ineligible evidence (
                    {activeTicket.ineligible_ticket_evidence.length})
                  </summary>
                  {activeTicket.ineligible_ticket_evidence.map((item) => (
                    <p key={item.evidence_id}>
                      <b>{item.artifact_type.replaceAll("_", " ")}</b>
                      <span>{item.reason}</span>
                    </p>
                  ))}
                </details>
              )}
</section>
              </section>
              <section id="ticket-decision-info" className="ticket-information-panel" hidden={ticketInfo?.ticketId !== activeTicket.id || ticketInfo.section !== "decisions"} aria-label="decisions">
                  <h4 className="ticket-information-heading"><b>Approval decisions</b><span>{governanceDecisions.length} recorded decision(s)</span></h4>
                <div className="sandbox-panel governance-decisions">
                  <div>
                    <b>Who approved or rejected what</b>
                    <span>
                      These are saved permission and review decisions for this ticket. They explain who allowed or rejected a particular step and why. Older decisions remain here even after a replacement plan or later rejection.
                    </span>
                  </div>
                  <p className="ticket-section-feedback">{governanceDecisions.length
                    ? "This is decision history, not a list of actions waiting for you. An earlier approval does not override the current plan status shown in the next-step panel."
                    : "No approval or rejection has been recorded yet. You do not need to fill anything in here; decisions appear when you review a plan or implementation result."}</p>
                  {governanceDecisions.map((item) => (
                    <article key={item.id}>
                      <div>
                        <b>
                          {item.decision} · {item.actor}
                        </b>
                        <span>
                          {item.action === "PLAN"
                            ? "Plan decision: permission to implement the specified proposal. It does not apply changes to your project."
                            : item.action.includes("PROMOT") || item.action.includes("APPLY")
                              ? "Apply decision: permission concerning the specified changes to the real project. Check the implementation result to see whether application succeeded."
                              : "Review decision: a recorded assessment for the named step or required check. It does not, by itself, complete the ticket."}
                        </span>
                        <p>Reason: {item.reason || "No reason was recorded."}</p>
                        <small>{item.decision === "DENIED" ? "This decision withheld permission for that step. It did not close the task." : "This records a decision, not proof that implementation or testing succeeded."}</small>
                        {!item.valid && <small className="run-failure">This decision cannot currently be relied on: {item.expiration_reason || "its approval conditions are no longer valid"}.</small>}
                        <details><summary>Decision record details</summary>
                          <p>{item.action.replaceAll("_", " ")} · roles {item.actor_roles.join("/") || "none"} · policy v{item.policy_version} · rule {item.rule_id}</p>
                          <small>Record binding: {item.binding_sha256.slice(0, 12)}… · {item.valid ? "valid when recorded" : "invalid"}. The binding ties the decision to the specific files and state it reviewed.</small>
                        </details>
                      </div>
                    </article>
                  ))}
                </div>
                </section>
              <section id="ticket-workflow-details" className="ticket-information-panel" hidden={ticketInfo?.ticketId !== activeTicket.id || ticketInfo.section !== "history"} aria-label="history">
                <h4 className="ticket-information-heading">Technical details and audit history</h4>
                <p className="ticket-section-help">This is the task’s resource usage and activity record. It helps explain what ran and diagnose failures. Opening a record or exporting the history does not start work or grant approval.</p>
              <div className="ticket-budget">
                <span>
                  tokens {activeTicket.ticket_usage?.tokens || 0}/
                  {activeTicket.ticket_budget?.max_tokens}
                </span>
                <span>
                  workers {activeTicket.ticket_usage?.worker_calls || 0}/
                  {activeTicket.ticket_budget?.max_worker_calls}
                </span>
                <span>
                  time{" "}
                  {Math.round(
                    activeTicket.ticket_usage?.wall_time_seconds || 0,
                  )}
                  s/{activeTicket.ticket_budget?.max_wall_time_seconds}s
                </span>
              </div>
              <div className="sandbox-panel">
                <div>
                  <b>Configured bounded validation workers</b>
                  <p className="ticket-section-help">These are available automated checking tools. Enabled means a tool can be used, not that it has run or passed. Each has limits on time and resources. Missing checks remain unresolved until suitable evidence is recorded.</p>
                  <span>
                    {snapshot.implementation_sandbox?.validation_workers
                      ?.length || 0}{" "}
                    integrations · unavailable categories remain unmet
                  </span>
                </div>
                {snapshot.implementation_sandbox?.validation_workers?.map(
                  (worker) => (
                    <article key={worker.id}>
                      <div>
                        <b>
                          {worker.name} ·{" "}
                          {worker.enabled ? "ENABLED" : "DISABLED"}
                        </b>
                        <span>
                          {worker.categories.join(" · ")} ·{" "}
                          {worker.artifact_kinds.join(" · ")} ·{" "}
                          {worker.limits.max_wall_time_seconds}s ·{" "}
                          {worker.limits.max_processes} processes ·{" "}
                          {Math.round(worker.limits.max_memory_bytes / 1048576)}
                          MB · {worker.limits.max_output_bytes} output bytes
                          <br />
                          allowlisted command: {worker.executable}{" "}
                          {worker.arguments.join(" ")}
                        </span>
                      </div>
                    </article>
                  ),
                )}
              </div>
              <div className="ticket-actions">
                <button
                  onClick={() => {
                    window.location.href = `${API}/api/tickets/export?ticket_id=${encodeURIComponent(activeTicket.id)}`;
                  }}
                >
                  Export audit
                </button>
              </div>
              <div className="ticket-events">
                <b>Ticket history</b>
                {ticketEvents.map((event) => (
                  <button key={event.id} onClick={() => inspectNode(event.id)}>
                    <span>{event.kind.replaceAll("_", " ")}</span>
                    <small>{event.title}</small>
                  </button>
                ))}
              </div>
              </section>
              </div>
              </div>
              <nav className="ticket-information-nav" aria-label="Active ticket information">
                <h4>Ticket information</h4>
                <p>Choose what you need to see alongside your current step.</p>
                {[
                  ["plan", "Plan and implementation", currentTicketPlans[0]?.approval_status || "No plan yet"],
                  ["evidence", "Evidence and acceptance", `${ticketArtifacts.length} evidence item(s)`],
                  ["decisions", "Approval decisions", `${governanceDecisions.length} recorded`],
                  ["history", "Technical details and history", "Usage and audit records"],
                ].map(([section, label, detail]) => (
                  <button key={section} type="button"
                    aria-pressed={ticketInfo?.ticketId === activeTicket.id && ticketInfo.section === section}
                    onClick={() => setTicketInfo({ ticketId: activeTicket.id, section })}>
                    <b>{label}</b><span>{detail}</span>
                  </button>
                ))}
                {ticketInfo?.ticketId === activeTicket.id && <button type="button" onClick={() => setTicketInfo(null)}>Back to current step only</button>}
              </nav>
              </div>
            </div>
          ) : (
            <p>Choose or create a ticket to begin ticket-scoped work.</p>
          )}
        </aside>
        <details className="ticket-create ticket-new-task">
          <summary>New ticket <span>Create another task</span></summary>
          <div className="workspace-heading">
            <div>
              <p className="eyebrow">NEW TICKET</p>
              <h2>Requested outcome</h2>
              <p>
                A ticket keeps the request, acceptance criteria, decisions,
                results, and audit record together.
              </p>
            </div>
            <div className="safety-badges">
              <span>planning is read-only</span>
              <span>limits enforced</span>
              <span>applying is separate</span>
            </div>
          </div>
          <div className="ticket-form-grid">
            <label>
              <span>Project</span>
              <select
                value={workspaceProject}
                onChange={(event) => setWorkspaceProject(event.target.value)}
              >
                {workspaceOptions?.projects.map((project) => (
                  <option value={project.id} key={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Priority</span>
              <select
                value={ticketPriority}
                onChange={(event) => setTicketPriority(event.target.value)}
              >
                <option>LOW</option>
                <option>MEDIUM</option>
                <option>HIGH</option>
                <option>URGENT</option>
              </select>
            </label>
            <label className="wide">
              <span>Dependencies · optional</span>
              <select
                multiple
                value={ticketDependencies}
                onChange={(event) =>
                  setTicketDependencies(
                    Array.from(
                      event.target.selectedOptions,
                      (option) => option.value,
                    ),
                  )
                }
              >
                {tickets
                  .filter(
                    (ticket) =>
                      ticket.project_id === workspaceProject &&
                      !["CLOSED", "REJECTED"].includes(ticket.status),
                  )
                  .map((ticket) => (
                    <option key={ticket.id} value={ticket.id}>
                      {ticket.title} · {ticket.status}
                    </option>
                  ))}
              </select>
            </label>
            <label className="wide">
              <span>Title</span>
              <input
                value={ticketTitle}
                onChange={(event) => setTicketTitle(event.target.value)}
                placeholder="Describe the desired outcome"
              />
            </label>
            <label className="wide">
              <span>Requested outcome</span>
              <textarea
                value={ticketDescription}
                onChange={(event) => setTicketDescription(event.target.value)}
                placeholder="Describe the behavior or result you want in ordinary language."
              />
            </label>
            <label>
              <span>Acceptance criteria · one per line</span>
              <textarea
                value={ticketCriteria}
                onChange={(event) => setTicketCriteria(event.target.value)}
                placeholder="Answer cites current evidence."
              />
            </label>
            <label>
              <span>Constraints · one per line</span>
              <textarea
                value={ticketConstraints}
                onChange={(event) => setTicketConstraints(event.target.value)}
                placeholder="Project source remains unchanged."
              />
            </label>
            <details className="ticket-defaults wide">
              <summary>Limits and defaults</summary>
              <p>
                These caps bound time and compute. Planning remains read-only;
                implementation runs in an isolated copy; applying reviewed files
                requires a separate approval.
              </p>
              <div className="budget-fields">
                <span>Execution limits</span>
                {(
                  [
                    ["max_tokens", "Tokens"],
                    ["max_model_calls", "Model calls"],
                    ["max_worker_calls", "Worker calls"],
                    ["max_wall_time_seconds", "Seconds"],
                    ["max_branch_depth", "Branch depth"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    <span>{label}</span>
                    <input
                      type="number"
                      min="0"
                      value={ticketBudget[key]}
                      onChange={(event) =>
                        setTicketBudget((current) => ({
                          ...current,
                          [key]: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                ))}
              </div>
            </details>
          </div>
          <button
            className="primary"
            disabled={
              ticketBusy ||
              !ticketTitle.trim() ||
              !ticketDescription.trim() ||
              !ticketCriteria.trim() ||
              !workspaceProject
            }
            onClick={() =>
              ticketAction("create", {
                project_id: workspaceProject,
                title: ticketTitle,
                description: ticketDescription,
                acceptance_criteria: ticketCriteria.split("\n").filter(Boolean),
                constraints: ticketConstraints.split("\n").filter(Boolean),
                priority: ticketPriority,
                dependency_ticket_ids: ticketDependencies,
                budget: ticketBudget,
              })
            }
          >
            Create ticket
          </button>
        </details>
      </section>

      <section
        id="view-projects"
        role="tabpanel"
        aria-labelledby="tab-projects"
        hidden={activeTab !== "projects"}
        className="project-workspace"
      >
        <form className="project-connect" onSubmit={connectProject}>
          <div>
            <p className="eyebrow">PROJECTS</p>
            <h2>Local project folders</h2>
            <p>
              Connect an existing folder or create a new project. The selected
              folder becomes the boundary for its tickets, plans, runs, and
              audit records.
            </p>
            <small className="claim-boundary">
              Live proof is limited to an individual Python developer using a
              disposable project on Windows 11/WSL2 with Codex CLI 0.147.0,
              gpt-5.4, and SQLite.
            </small>
          </div>
          <div className="project-root-field">
            <label htmlFor="project-root">Folder path</label>
            <div className="folder-path-control">
              <input
                id="project-root"
                value={projectRoot}
                onChange={(event) => {
                  setProjectRoot(event.target.value);
                  setProjectSelectionNotice("");
                }}
                placeholder="C:\Projects\checkout-service"
                required
              />
              <button
                type="button"
                onClick={browseProject}
                disabled={projectBrowsing || projectConnecting}
                aria-label="Browse for project folder"
              >
                {projectBrowsing ? "Waiting for folder…" : "Browse…"}
              </button>
            </div>
            {projectSelectionNotice && (
              <small className="project-selection-state" role="status">
                {projectSelectionNotice}
              </small>
            )}
          </div>
          <div className="project-connect-actions">
            <button type="button" onClick={createProject}
              disabled={projectBrowsing || projectConnecting || !projectRoot.trim()}>
              {projectConnecting ? "Working…" : "Create new project"}
            </button>
            <button className="primary" disabled={projectBrowsing || projectConnecting || !projectRoot.trim()}>
              {projectConnecting ? "Working…" : "Connect existing project"}
            </button>
          </div>
        </form>
        <section className="project-records" aria-label="Project records">
          <div className="project-record-heading">
            <div>
              <p className="eyebrow">PROJECT RECORDS</p>
              <h2>Project manifest, goals, ideas, and organizations</h2>
              <p>
                One selected project drives these records and the Questions and
                plans workspace below.
              </p>
            </div>
            <label>
              <span>Managed project</span>
              <select
                value={workspaceProject}
                onChange={(event) => chooseWorkspaceProject(event.target.value)}
                disabled={projectMetadataBusy}
              >
                {!workspaceOptions?.projects.length && (
                  <option value="">Connect a project above</option>
                )}
                {workspaceOptions?.projects.map((project) => (
                  <option value={project.id} key={project.id}>
                    {project.name} · {project.organization || "Personal"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div
            className="project-record-tabs"
            role="tablist"
            aria-label="Project record types"
          >
            {(
              [
                ["manifests", "Project workspace", selectedWorkspaceProject ? 1 : 0],
                ["organizations", "Organizations", organizationGroups.length],
              ] as const
            ).map(([id, label, count]) => (
              <button
                type="button"
                role="tab"
                id={`project-record-tab-${id}`}
                aria-controls={`project-record-${id}`}
                aria-selected={projectSection === id}
                className={projectSection === id ? "active" : ""}
                onClick={() => setProjectSection(id)}
                key={id}
              >
                <span>{label}</span>
                <b>{count}</b>
              </button>
            ))}
          </div>

          {projectSection === "manifests" && (
            <label className="project-intent-switcher">
              <span>Project document</span>
              <select
                value={projectIntentSection}
                onChange={(event) => setProjectIntentSection(
                  event.target.value as "manifest" | "goals" | "ideas",
                )}
              >
                <option value="manifest">Project Manifest</option>
                <option value="goals">Project Goals</option>
                <option value="ideas">Ideas</option>
              </select>
            </label>
          )}

          <div
            id="project-record-manifests"
            role="tabpanel"
            aria-labelledby="project-record-tab-manifests"
            className="project-record-panel"
            hidden={projectSection !== "manifests"}
          >
            {selectedWorkspaceProject ? (
              <div className="project-metadata-rail">
                <h3>{selectedWorkspaceProject.name}</h3>
                <code className="manifest-location">{selectedWorkspaceProject.root}</code>
                <div className="manifest-index-state">
                  <small>SCAN {shortId(selectedWorkspaceProject.index_scan_id || "none")}</small>
                  <span className={selectedWorkspaceProject.index_current ? "manifest-current" : "manifest-stale"}>
                    {selectedWorkspaceProject.index_current ? "Current" : "Unavailable"}
                  </span>
                </div>
                <div className="manifest-grid" aria-label="Project index metadata">
                  <span>
                    <small>BOUNDARY</small>
                    <b>
                      {selectedWorkspaceProject.read_only
                        ? "Read-only index"
                        : "Write capable"}
                    </b>
                  </span>
                  <span>
                    <small>ARTIFACTS</small>
                    <b>{selectedWorkspaceProject?.artifact_count}</b>
                  </span>
                  <span>
                    <small>RELATIONSHIPS</small>
                    <b>{selectedWorkspaceProject?.dependency_count}</b>
                  </span>
                  <span>
                    <small>ADAPTER</small>
                    <b>{plainAction(selectedWorkspaceProject.adapter)}</b>
                  </span>
                  <span>
                    <small>ORGANIZATION</small>
                    <b>{selectedWorkspaceProject.organization || "Personal"}</b>
                  </span>
                </div>
                <div className="project-access-control">
                  <div>
                    <small>EXECUTION MODE</small>
                    <b>{plainAction(selectedWorkspaceProject.execution_mode)}</b>
                  </div>
                  <select value={selectedWorkspaceProject.execution_mode}
                    onChange={(event) => changeProjectAccess(event.target.value as WorkspaceProject["execution_mode"])}
                    disabled={projectMetadataBusy}>
                    <option value="PROTECTED">Protected</option>
                    <option value="AUTONOMOUS_SANDBOX">Autonomous Sandbox</option>
                    <option value="AUTONOMOUS_PROJECT">Autonomous Project</option>
                    <option value="READ_ONLY">Read-only</option>
                  </select>
                  <p>{selectedWorkspaceProject.execution_mode === "READ_ONLY"
                    ? "Investigation only. Implementation tickets and project writes are blocked."
                    : selectedWorkspaceProject.execution_mode === "PROTECTED"
                      ? "Changes run in a sandbox and require plan and promotion approval."
                      : selectedWorkspaceProject.execution_mode === "AUTONOMOUS_SANDBOX"
                        ? "TGRAM may plan, edit, and validate without interruption; changes remain in the disposable sandbox."
                        : "TGRAM may plan, validate, and promote bounded changes into this project without per-change approval."}</p>
                </div>

              </div>
            ) : (
              <p className="project-record-empty">
                Connect a project to create its first read-only manifest.
              </p>
            )}
          </div>

          <div className="project-intent-panel" hidden={
            projectSection !== "manifests" || projectIntentSection === "ideas"
          }>
            {selectedWorkspaceProject ? (
              projectIntentSection === "manifest" ? (
                <form onSubmit={saveProjectIntent} key={`${selectedWorkspaceProject.id}-manifest`}>
                  <div><small>PROJECT MANIFEST</small><h3>manifest.md</h3></div>
                  <textarea name="project_manifest" defaultValue={selectedWorkspaceProject.project_manifest}
                    maxLength={12000} placeholder="Describe what this project is, who it serves, and the scope it should preserve."
                    disabled={projectMetadataBusy} />
                  <button className="primary" disabled={projectMetadataBusy}>
                    {projectMetadataBusy ? "Saving…" : "Update manifest.md"}
                  </button>
                </form>
              ) : (
                <section className="project-goals-editor">
                  <div><small>PROJECT GOALS</small><h3>goals.json</h3></div>
                  <form className="goal-compose" onSubmit={addProjectGoal}>
                    <input name="title" maxLength={160} placeholder="Goal title" required disabled={projectMetadataBusy} />
                    <textarea name="goal" maxLength={2000} placeholder="Describe the goal and its intended outcome." required disabled={projectMetadataBusy} />
                    <button className="primary" disabled={projectMetadataBusy}>{projectMetadataBusy ? "Saving…" : "Add goal"}</button>
                  </form>
                  <div className="project-goal-list">
                    {selectedWorkspaceProject.project_goals.map((item, index) => (
                      <article key={`${item.title}-${index}`}>
                        <div><h4>{item.title}</h4><p>{item.goal}</p></div>
                        <button type="button" onClick={() => deleteProjectGoal(index)} disabled={projectMetadataBusy} aria-label={`Delete ${item.title}`}>Delete</button>
                      </article>
                    ))}
                    {!selectedWorkspaceProject.project_goals.length && <p className="project-record-empty">No goals yet. Add the first goal above.</p>}
                  </div>
                </section>
              )
            ) : <p className="project-record-empty">Select a managed project first.</p>}
          </div>

          <div
            id="project-record-ideas"
            role="tabpanel"
            aria-label="Project ideas"
            className="project-record-panel"
            hidden={projectSection !== "manifests" || projectIntentSection !== "ideas"}
          >
            <section className="idea-suggestions" aria-label="AI suggestions">
              <div className="idea-suggestion-heading">
                <div>
                  <small>AI SUGGESTIONS</small>
                  <h3>Source-grounded candidates</h3>
                  <p>
                    One bounded Codex call reads a disposable copy of the
                    current index. Results stay unsaved until you choose one.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={suggestProjectIdeas}
                  disabled={
                    !selectedWorkspaceProject?.index_current ||
                    projectMetadataBusy ||
                    ideaSuggestionBusy
                  }
                >
                  {ideaSuggestionBusy ? "Analyzing…" : "Suggest ideas"}
                </button>
              </div>
              {ideaSuggestionBusy && (
                <p className="idea-suggestion-progress" role="status">
                  Codex is analyzing a bounded read-only source mirror. No
                  project files, ideas, tickets, or runs are being changed.
                </p>
              )}
              {currentIdeaSuggestions && !ideaSuggestionBusy && (
                <div className="idea-suggestion-results">
                  <div className="idea-suggestion-provenance">
                    <span>
                      <b>Source</b> scan{" "}
                      {shortId(currentIdeaSuggestions.index_scan_id || "none")}{" "}
                      · integrity verified
                    </span>
                    <span>
                      <b>Worker</b> {currentIdeaSuggestions.worker.name} ·{" "}
                      {currentIdeaSuggestions.worker.model} ·{" "}
                      {currentIdeaSuggestions.worker.sandbox}
                    </span>
                    <span>
                      <b>Scope</b>{" "}
                      {currentIdeaSuggestions.worker.authorized_files}/
                      {currentIdeaSuggestions.worker.indexed_files} indexed
                      files ·{" "}
                      {(
                        currentIdeaSuggestions.worker.source_bytes / 1024
                      ).toFixed(1)}{" "}
                      KB
                    </span>
                    <span>
                      <b>Effect</b> 1 AI call · not saved · no ticket, run, or
                      write authority
                    </span>
                    <span title={currentIdeaSuggestions.worker.cost_basis}>
                      <b>Cost</b> not reported by Codex CLI
                    </span>
                  </div>
                  <div className="idea-suggestion-list">
                    {currentIdeaSuggestions.suggestions.map((suggestion) => {
                      const alreadySaved = selectedProjectIdeas.some(
                        (idea) =>
                          idea.title === suggestion.title &&
                          idea.detail === suggestion.detail,
                      );
                      return (
                        <article key={suggestion.title}>
                          <div>
                            <small>AI CANDIDATE</small>
                            <h3>{suggestion.title}</h3>
                            <p>{suggestion.detail}</p>
                            <p className="idea-suggestion-rationale">
                              <b>Why</b> {suggestion.rationale}
                            </p>
                            <ul aria-label={`Evidence for ${suggestion.title}`}>
                              {suggestion.evidence.map((evidence) => (
                                <li
                                  key={`${suggestion.title}-${evidence.path}-${evidence.line}`}
                                >
                                  <code>
                                    {evidence.path}
                                    {evidence.line ? `:${evidence.line}` : ""}
                                  </code>{" "}
                                  {evidence.detail}
                                </li>
                              ))}
                            </ul>
                          </div>
                          <button
                            type="button"
                            disabled={projectMetadataBusy || alreadySaved}
                            onClick={() =>
                              projectRecordAction(
                                "ideas",
                                {
                                  project_id: selectedWorkspaceProject?.id,
                                  title: suggestion.title,
                                  detail: suggestion.detail,
                                },
                                "AI suggestion saved as a project idea. No ticket or run was created.",
                              )
                            }
                          >
                            {alreadySaved ? "Saved" : "Save suggestion"}
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}
            </section>
            <form className="idea-compose" onSubmit={addProjectIdea}>
              <label>
                <span>Idea</span>
                <input
                  name="title"
                  maxLength={160}
                  placeholder="A possible outcome or improvement"
                  disabled={!selectedWorkspaceProject || projectMetadataBusy}
                  required
                />
              </label>
              <label>
                <span>Notes</span>
                <textarea
                  name="detail"
                  maxLength={2000}
                  placeholder="Why it may matter; no ticket or work is created yet."
                  disabled={!selectedWorkspaceProject || projectMetadataBusy}
                />
              </label>
              <button
                className="primary"
                disabled={!selectedWorkspaceProject || projectMetadataBusy}
              >
                Save idea
              </button>
            </form>
            <div className="idea-list">
              {selectedProjectIdeas.length ? (
                selectedProjectIdeas.map((idea) => (
                  <article
                    className={idea.status === "ARCHIVED" ? "archived" : ""}
                    key={idea.id}
                  >
                    <div>
                      <small>{idea.status}</small>
                      <h3>{idea.title}</h3>
                      <p>{idea.detail || "No notes recorded."}</p>
                    </div>
                    <div className="idea-actions">
                      {idea.status === "DRAFT" && (
                        <button
                          type="button"
                          onClick={() => {
                            setTicketTitle(idea.title);
                            setTicketDescription(idea.detail);
                            setTicketCriteria("");
                            setActiveTab("tickets");
                            setActionNotice(
                              "Idea copied into a ticket draft. No ticket was created.",
                            );
                          }}
                        >
                          Draft ticket
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={projectMetadataBusy}
                        onClick={() =>
                          projectRecordAction(
                            "ideas/status",
                            {
                              project_id: selectedWorkspaceProject?.id,
                              idea_id: idea.id,
                              status:
                                idea.status === "DRAFT" ? "ARCHIVED" : "DRAFT",
                            },
                            idea.status === "DRAFT"
                              ? "Idea archived. No ticket or work was changed."
                              : "Idea restored to the selected project.",
                          )
                        }
                      >
                        {idea.status === "DRAFT" ? "Archive" : "Restore"}
                      </button>
                    </div>
                  </article>
                ))
              ) : (
                <p className="project-record-empty">
                  No ideas are recorded for the selected project.
                </p>
              )}
            </div>
          </div>

          <div
            id="project-record-organizations"
            role="tabpanel"
            aria-labelledby="project-record-tab-organizations"
            className="project-record-panel"
            hidden={projectSection !== "organizations"}
          >
            <form
              className="organization-compose"
              onSubmit={organizeProject}
              key={selectedWorkspaceProject?.id || "no-project"}
            >
              <label>
                <span>Selected project organization</span>
                <input
                  name="organization"
                  maxLength={120}
                  defaultValue={
                    selectedWorkspaceProject?.organization || "Personal"
                  }
                  disabled={!selectedWorkspaceProject || projectMetadataBusy}
                  required
                />
              </label>
              <button
                className="primary"
                disabled={!selectedWorkspaceProject || projectMetadataBusy}
              >
                Save organization
              </button>
              <small>
                Local grouping only. Organization labels grant no identity,
                approval, or project authority.
              </small>
            </form>
            <div className="organization-list">
              {organizationGroups.length ? (
                organizationGroups.map(([organization, projects]) => (
                  <article key={organization}>
                    <div>
                      <small>ORGANIZATION</small>
                      <h3>{organization}</h3>
                    </div>
                    <span>{projects.length} project(s)</span>
                    <p>{projects.map((project) => project.name).join(" · ")}</p>
                  </article>
                ))
              ) : (
                <p className="project-record-empty">
                  Connected projects will appear here by organization.
                </p>
              )}
            </div>
          </div>
        </section>
        {selectedGovernancePolicy && (
          <div className="governance-panel">
            <div className="workspace-heading">
              <div>
                <p className="eyebrow">
                  PROJECT GOVERNANCE · VERSION{" "}
                  {selectedGovernancePolicy.version}
                </p>
                <h2>Authorization stays inside this project</h2>
                <p>
                  Cross-project dependencies are read-only. Decisions are
                  append-only, rule-cited, and rebound to current source, patch,
                  requirements, evidence, and policy before use.
                </p>
                <p>
                  Current authority: <b>{selectedGovernancePolicy.authority_mode === "AUTHENTICATED_TEAM" ? "Authenticated team" : "Individual / local"}</b>
                  {selectedGovernancePolicy.authority_mode === "AUTHENTICATED_TEAM"
                    ? ` · organization identity ${selectedGovernancePolicy.authority_organization_id || "unavailable"}`
                    : " · local names and organization labels are attribution only"}.
                </p>
              </div>
              <button
                disabled={ticketBusy}
                onClick={() => configureProjectPolicy(selectedGovernancePolicy)}
              >
                Configure policy
              </button>
            </div>
            <div className="governance-grid">
              <span>
                <b>Risk and required decision</b>
                Read-only viewing: no mutation approval · confined execution:
                bounded worker policy · project changes: separate bound approval ·
                recovery/policy: administrator authority
              </span>
              <span>
                <b>Workers</b>
                {selectedGovernancePolicy.permitted_worker_ids.join(" · ")}
              </span>
              <span>
                <b>Required validation</b>
                {selectedGovernancePolicy.required_validation_categories.join(
                  " · ",
                ) || "Artifact-routed defaults"}
              </span>
              <span>
                <b>Reviewer roles</b>
                {Object.entries(selectedGovernancePolicy.actor_roles)
                  .map(([actor, roles]) => `${actor}: ${roles.join("/")}`)
                  .join(" · ") || "No role assignments"}
              </span>
              <span>
                <b>Approval rules</b>
                {selectedGovernancePolicy.approval_rules
                  .map(
                    (rule) =>
                      `${rule.id}: ${rule.minimum_approvals} ${rule.required_roles.join("/") || "named"} reviewer(s)`,
                  )
                  .join(" · ")}
              </span>
              <span>
                <b>Artifact validation</b>
                {Object.entries(
                  selectedGovernancePolicy.artifact_validation_requirements,
                )
                  .map(
                    ([kind, categories]) => `${kind}: ${categories.join("/")}`,
                  )
                  .join(" · ") || "No stronger artifact rules"}
              </span>
              <span>
                <b>Maximum budget</b>
                {selectedGovernancePolicy.max_ticket_budget.max_tokens} tokens ·{" "}
                {selectedGovernancePolicy.max_ticket_budget.max_worker_calls}{" "}
                workers ·{" "}
                {
                  selectedGovernancePolicy.max_ticket_budget
                    .max_wall_time_seconds
                }
                s
              </span>
              <span>
                <b>Registered root</b>
                {selectedGovernancePolicy.project_root}
              </span>
              <span>
                <b>Append-only policy history</b>
                {selectedGovernancePolicy.revision_history
                  .map(
                    (item) =>
                      `v${item.version} · ${item.configured_by} · ${item.reason}`,
                  )
                  .join(" | ")}
              </span>
            </div>
          </div>
        )}

      </section>

      <section
        id="view-activity"
        role="tabpanel"
        aria-labelledby="tab-activity"
        hidden={activeTab !== "activity"}
        className="activity-workspace"
      >
        <div className="workspace-heading">
          <div>
            <p className="eyebrow">RUNS</p>
            <h2>Running and interrupted work</h2>
            <p>
              See interrupted and running work, reopen its ticket, or export the
              complete audit and evidence package.
            </p>
          </div>
        </div>
        <div className="activity-list">
          {snapshot.workspace?.durable_activities.length ? (
            snapshot.workspace.durable_activities.map((item) => (
              <article key={item.id}>
                <div>
                  <b>{plainStage(item.activity_kind)}</b>
                  <span>
                    {plainStage(item.status)} · {plainStage(item.stage)}
                  </span>
                  {item.error && <small>{item.error}</small>}
                </div>
                <div>
                  {item.ticket_id && (
                    <button
                      onClick={() => {
                        setActiveTicketId(item.ticket_id || "");
                        setActiveTab("tickets");
                      }}
                    >
                      Open ticket
                    </button>
                  )}
                  {item.resumable && (
                    <button
                      className="primary"
                      disabled={ticketBusy}
                      onClick={() => resumeActivity(item.activity_kind)}
                    >
                      Resume run
                    </button>
                  )}
                  {[
                    "QUEUED",
                    "RUNNING",
                    "INTERRUPTED",
                    "WAITING_FOR_CAPACITY",
                    "WAITING_FOR_LEASE",
                    "CANCELLATION_REQUESTED",
                  ].includes(item.status) &&
                    ["PROJECT_WORKSPACE", "IMPLEMENTATION_SANDBOX"].includes(
                      item.activity_kind,
                    ) && (
                      <button
                        disabled={ticketBusy}
                        onClick={() => cancelActivity(item.activity_kind)}
                      >
                        Cancel run
                      </button>
                    )}
                </div>
              </article>
            ))
          ) : (
            <p>No persisted background activity yet.</p>
          )}
        </div>
        <details className="run-internals">
          <summary>Scheduling and write-lock details</summary>
          <div className="activity-list scheduler-list">
            <div className="workspace-heading">
              <div>
                <p className="eyebrow">RESOURCE-AWARE SCHEDULER</p>
                <h2>Capacity, budgets, and durable queue decisions</h2>
                <p>
                  Priority is balanced with predicted cost, latency, capacity,
                  and validation needs. WAITING_FOR_CAPACITY, WAITING_FOR_LEASE,
                  budget, interruption, and cancellation states survive restart.
                </p>
                {snapshot.workspace?.scheduler_limits && (
                  <small>
                    {snapshot.workspace.scheduler_limits.active_jobs}/
                    {snapshot.workspace.scheduler_limits.global_concurrency}{" "}
                    global jobs · project limit{" "}
                    {
                      snapshot.workspace.scheduler_limits
                        .per_project_concurrency
                    }{" "}
                    · ticket limit{" "}
                    {snapshot.workspace.scheduler_limits.per_ticket_concurrency}{" "}
                    · {snapshot.workspace.scheduler_limits.used_capacity_units}/
                    {snapshot.workspace.scheduler_limits.capacity_units}{" "}
                    capacity in use
                  </small>
                )}
              </div>
            </div>
            {snapshot.workspace?.scheduled_work.length ? (
              snapshot.workspace.scheduled_work.map((item) => (
                <article key={item.id}>
                  <div>
                    <b>
                      {item.work_kind.replaceAll("_", " ")} ·{" "}
                      {item.status.replaceAll("_", " ")}
                    </b>
                    <span>
                      {item.priority} priority · score{" "}
                      {item.scheduling_score.toFixed(1)} · {item.capacity_units}{" "}
                      capacity · {item.predicted_worker_calls} predicted worker
                      call(s) · {item.predicted_latency_seconds}s predicted
                    </span>
                    <small>
                      {item.blocked_reason ||
                        item.scheduling_reasons.join(" · ")}
                    </small>
                    <small>
                      {item.required_validation_categories.join(" · ") ||
                        "No special validation route"}{" "}
                      · {item.checkpoints.length} durable checkpoints ·{" "}
                      {item.evidence_ids.length} evidence · resources disposed{" "}
                      {item.resources_disposed ? "✓" : "pending"}
                    </small>
                    {item.cancellation_reason && (
                      <small>
                        Cancelled by {item.cancelled_by}:{" "}
                        {item.cancellation_reason}
                      </small>
                    )}
                  </div>
                  <div>
                    <button
                      onClick={() => {
                        setActiveTicketId(item.ticket_id);
                        setActiveTab("tickets");
                      }}
                    >
                      Open ticket
                    </button>
                  </div>
                </article>
              ))
            ) : (
              <p>No scheduled work has been recorded.</p>
            )}
          </div>
          {!!snapshot.workspace?.leases.length && (
            <div className="lease-summary">
              <b>Project mutation leases</b>
              {snapshot.workspace.leases.map((lease) => (
                <article key={lease.id}>
                  <span>
                    {lease.status} · fence {lease.fencing_token}
                  </span>
                  <strong>{lease.holder_id}</strong>
                  <small>
                    expires {new Date(lease.expires_at).toLocaleString()} ·{" "}
                    {lease.events} durable events
                  </small>
                </article>
              ))}
            </div>
          )}
        </details>
        {activeTicket && (
          <div className="export-panel">
            <div>
              <b>Audit and evidence package</b>
              <span>
                Export the request, decisions, proposed and applied changes,
                validation results, recovery history, and project refresh in one
                integrity-hashed JSON record.
              </span>
            </div>
            <button
              onClick={() => {
                window.location.href = `${API}/api/tickets/export?ticket_id=${encodeURIComponent(activeTicket.id)}`;
              }}
            >
              Export audit record
            </button>
          </div>
        )}
      </section>

      <section
        id="view-lab"
        role="tabpanel"
        aria-labelledby="tab-lab"
        hidden={activeTab !== "lab"}
        className="diagnostic-console"
      >
        <div className="lab-controls">
          <div>
            <p className="eyebrow">OPTIONAL TECHNICAL LAB</p>
            <h2>Diagnostics, benchmarks, and graph internals</h2>
            <p>
              These proof surfaces are kept outside the daily ticket workflow.
            </p>
          </div>
          <div className="actions">
            <button
              className="secondary"
              disabled={busy || snapshot.running}
              onClick={() => control("reset")}
            >
              Reset demo data
            </button>
            <button
              className="primary"
              disabled={busy || snapshot.running}
              onClick={() => control("start")}
            >
              {snapshot.running ? "Running…" : "Run demonstration"}
            </button>
          </div>
        </div>
        <div className="workspace-history inspect-history">
          <div className="history-title">
            <div>
              <p className="eyebrow">SAVED PROJECT RESULTS</p>
              <h3>Inspect previous project work</h3>
            </div>
            <span>{workspaceHistory.length} saved results</span>
          </div>
          <div className="history-list">
            {workspaceHistory.length ? (
              workspaceHistory.map((item) => (
                <button
                  key={item.id}
                  onClick={() => inspectNode(item.id)}
                  className={selected?.id === item.id ? "selected" : ""}
                >
                  <small>
                    {item.project_name} ·{" "}
                    {item.kind === "CHANGE_PLAN" ? "CHANGE PLAN" : "DIAGNOSTIC"}
                  </small>
                  <b>{item.prompt}</b>
                  <span>
                    {item.affected_paths?.length || 0} files ·{" "}
                    {item.evidence?.length || 0} evidence ·{" "}
                    {item.approval_status || "completed"}
                  </span>
                </button>
              ))
            ) : (
              <p>No saved project results yet.</p>
            )}
          </div>
        </div>


        <div className="diagnostic-progress" aria-live="polite">
          <b>
            {snapshot.diagnostic?.stage || "Waiting for a diagnostic question."}
          </b>
          <span>
            {diagnosticOptions
              ? `${diagnosticOptions.limits.dependency_files}-file limit · ${diagnosticOptions.limits.wall_time_seconds}s limit · ${diagnosticOptions.limits.model_calls} model calls · ${diagnosticOptions.limits.project_writes} project writes`
              : "Loading safety limits…"}
          </span>
        </div>
        {snapshot.diagnostic?.status === "COMPLETED" && (
          <div className="diagnostic-result">
            <div>
              <b>
                {snapshot.diagnostic.worker_calls === 0
                  ? "GRAPH MEMORY REUSED"
                  : `${snapshot.diagnostic.worker_calls} bounded investigation calls`}
              </b>
              <span>
                {snapshot.diagnostic.reused_subtasks} reused subtasks ·{" "}
                {snapshot.diagnostic.dependency_paths.length} dependency files ·{" "}
                {snapshot.diagnostic.elapsed_seconds.toFixed(2)}s ·{" "}
                {snapshot.diagnostic.source_integrity_verified
                  ? "source unchanged"
                  : "integrity unverified"}
              </span>
              <p>{snapshot.diagnostic.conclusion}</p>
            </div>
            {snapshot.diagnostic.task_id && (
              <button
                className="secondary"
                onClick={() => inspectNode(snapshot.diagnostic?.task_id || "")}
              >
                Inspect task graph
              </button>
            )}
          </div>
        )}
        {snapshot.diagnostic?.status === "FAILED" && (
          <p className="diagnostic-error">{snapshot.diagnostic.error}</p>
        )}
        <div className="conflict-proof">

          <div className="diagnostic-progress">
            <b>
              {snapshot.conflict?.stage ||
                "Waiting for a conflict-resolution proof."}
            </b>
            <span>
              2 contradictory findings · targeted evidence · 1 resolution
              attempt · read only
            </span>
          </div>
          {snapshot.conflict?.status === "COMPLETED" && (
            <div className="diagnostic-result conflict-result">
              <div>
                <b>
                  {snapshot.conflict.reused_verdict
                    ? "RESOLVED VERDICT REUSED"
                    : snapshot.conflict.verdict_status === "RESOLVED"
                      ? "JUSTIFIED VERDICT"
                      : "ABSTAINED"}
                </b>
                <span>
                  {snapshot.conflict.investigation_calls} investigation calls ·{" "}
                  {snapshot.conflict.resolution_calls} resolution calls ·{" "}
                  {snapshot.conflict.evidence_claim_ids.length} provenance
                  claims · {snapshot.conflict.elapsed_seconds.toFixed(2)}s ·{" "}
                  {snapshot.conflict.source_integrity_verified
                    ? "source unchanged"
                    : "integrity unverified"}
                </span>
                <p>
                  <strong>
                    {snapshot.conflict.selected_value ||
                      "No defensible selection"}
                  </strong>{" "}
                  — {snapshot.conflict.rationale}
                </p>
              </div>
              {snapshot.conflict.task_id && (
                <button
                  className="secondary"
                  onClick={() => inspectNode(snapshot.conflict?.task_id || "")}
                >
                  Inspect conflict graph
                </button>
              )}
            </div>
          )}
          {snapshot.conflict?.status === "FAILED" && (
            <p className="diagnostic-error">{snapshot.conflict.error}</p>
          )}
        </div>
      </section>

      <section
        id="view-models"
        role="tabpanel"
        aria-labelledby="tab-models"
        hidden={activeTab !== "models"}
        className="diagnostic-console models-page"
      >
        <div className="lab-controls">
          <div>
            <p className="eyebrow">MODEL ROUTING</p>
            <h2>Models</h2>
            <p>
              Choose a provider and model for each role. API keys are read from environment
              variables and are never persisted by RLMGraph.
            </p>
          </div>
        </div>
        <div className="model-role-grid">
          {modelSettings?.roles.map((role) => (
            <article className="model-role-card" key={role.role}>
              <div>
                <span>{role.role.replaceAll("_", " ")}</span>
                <h3>{role.label}</h3>
                <p>{role.description}</p>
              </div>
              <label>
                Provider
                <select value={role.provider} onChange={(event) => editModelRole(role.role, {
                  provider: event.target.value,
                  base_url: event.target.value === "openai_api"
                    ? "https://api.openai.com/v1" : role.base_url,
                })}>
                  {role.providers.map((provider) => (
                    <option value={provider} key={provider}>
                      {modelSettings.providers[provider]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Model
                {role.provider === "local_openai" ? (
                  <input value={role.model} onChange={(event) => editModelRole(
                    role.role, { model: event.target.value }
                  )} placeholder="local model ID" />
                ) : (
                  <select value={role.model} onChange={(event) => editModelRole(
                    role.role, { model: event.target.value }
                  )}>
                    {modelSettings.available_models.map((model) => (
                      <option value={model} key={model}>{model}</option>
                    ))}
                  </select>
                )}
              </label>
              {role.provider !== "codex_cli" && (
                <>
                  <label>
                    API base URL
                    <input value={role.base_url} onChange={(event) => editModelRole(
                      role.role, { base_url: event.target.value }
                    )} placeholder="http://127.0.0.1:11434/v1" />
                  </label>
                  <label>
                    API key environment variable
                    <input value={role.api_key_environment} onChange={(event) => editModelRole(
                      role.role, { api_key_environment: event.target.value }
                    )} placeholder="OPENAI_API_KEY" />
                  </label>
                </>
              )}
              <button className="primary" disabled={modelBusyRole === role.role}
                onClick={() => void saveModelRole(role)}>
                {modelBusyRole === role.role ? "Applying…" : "Apply model"}
              </button>
            </article>
          )) || <p>Loading model configuration…</p>}
        </div>
      </section>

      <section
        id="view-savings"
        role="tabpanel"
        aria-labelledby="tab-savings"
        hidden={activeTab !== "savings"}
        className="diagnostic-console"
      >
        <div className="lab-controls savings-controls">
          <div className="savings-introduction">
            <p className="eyebrow">SAVINGS</p>
            <h2>Token usage and savings</h2>
            <p>
              See what TGRAM actually used, what controlled comparisons indicate
              it avoided, and how much of the measurement came directly from providers.
            </p>
          </div>
          <section className="savings-section" aria-labelledby="savings-summary-title">
            <div className="savings-section-heading">
              <div><small>AT A GLANCE</small><h3 id="savings-summary-title">What the totals mean</h3></div>
              <span>{tokenSavingsPercent.toFixed(1)}% measured reduction</span>
            </div>
            <div className="metrics savings-metrics savings-primary" aria-label="Token usage summary">
              <article>
                <span>{Math.round(totalTokenUsage).toLocaleString()}</span>
                <p>Tokens TGRAM used</p>
                <small>All recorded execution, retrieval, and project-workspace tokens.</small>
              </article>
              <article>
                <span>{Math.round(measuredTokensAvoided).toLocaleString()}</span>
                <p>Tokens avoided</p>
                <small>Savings demonstrated by {snapshot.metrics.token_comparison_count || 0} controlled comparison records.</small>
              </article>
              <article>
                <span>{Math.round(potentialTotalTokenUsage).toLocaleString()}</span>
                <p>Estimated use without savings</p>
                <small>Tokens TGRAM used plus the tokens measured as avoided.</small>
              </article>
            </div>
            <p className="savings-formula">
              <b>{Math.round(totalTokenUsage).toLocaleString()} used</b>
              <span>+</span><b>{Math.round(measuredTokensAvoided).toLocaleString()} avoided</b>
              <span>=</span><b>{Math.round(potentialTotalTokenUsage).toLocaleString()} estimated without savings</b>
            </p>
            <p className="savings-accounting-boundary">
              Current accounting began {snapshot.metrics.measurement_started_at
                ? new Date(snapshot.metrics.measurement_started_at).toLocaleString()
                : "when corrected metering was enabled"}. Earlier miscounted records remain in the audit ledger but are excluded from every total above.
            </p>
          </section>
          <section className="savings-section" aria-labelledby="comparison-title">
            <div className="savings-section-heading">
              <div><small>CONTROLLED TEST</small><h3 id="comparison-title">TGRAM compared with a growing chat</h3></div>
            </div>
          <div className="savings-benchmark-control">
            <div>
              <b>Run the same long-running project goal both ways</b>
              <span>
                Each agent receives a fresh copy, the same goal, and the same twenty hidden
                acceptance checks. Lower usage only counts as a win when quality is preserved.
              </span>
            </div>
            <button
              className="primary"
              disabled={
                conversationBenchmarkBusy ||
                snapshot.project_goal_benchmark?.status === "RUNNING"
              }
              onClick={() => void startProjectGoalBenchmark()}
            >
              {snapshot.project_goal_benchmark?.status === "RUNNING"
                ? "Comparison running…"
                : "Run controlled comparison"}
            </button>
          </div>
          {snapshot.project_goal_benchmark?.error && (
            <p className="savings-notice">{snapshot.project_goal_benchmark.error}</p>
          )}
          {snapshot.project_goal_benchmark?.result && (
            <div className="metrics savings-metrics" aria-label="Latest controlled comparison">
              <article>
                <span>{snapshot.project_goal_benchmark.result.baseline_tokens.toLocaleString()}</span>
                <p>Growing-chat tokens</p>
                <small>Passed {snapshot.project_goal_benchmark.result.baseline.criteria_passed} of {snapshot.project_goal_benchmark.result.criteria_total || 20} checks.</small>
              </article>
              <article>
                <span>{snapshot.project_goal_benchmark.result.rlmgraph_tokens.toLocaleString()}</span>
                <p>TGRAM tokens</p>
                <small>Passed {snapshot.project_goal_benchmark.result.rlmgraph.criteria_passed} of {snapshot.project_goal_benchmark.result.criteria_total || 20} checks.</small>
              </article>
              <article>
                <span>{snapshot.project_goal_benchmark.result.savings_percent.toFixed(1)}%</span>
                <p>Tokens reduced</p>
                <small>
                  {snapshot.project_goal_benchmark.result.tokens_saved.toLocaleString()} fewer tokens · quality
                  {snapshot.project_goal_benchmark.result.quality_preserved
                    ? " passed the required threshold" : " did not pass the required threshold"}
                </small>
              </article>
            </div>
          )}
          </section>
          <section className="savings-section" aria-labelledby="metering-title">
            <div className="savings-section-heading">
              <div><small>MEASUREMENT QUALITY</small><h3 id="metering-title">How much of this is directly measured?</h3></div>
            </div>
          <div className="metrics savings-metrics" aria-label="Model-call metering coverage">
            <article>
              <span>{snapshot.metrics.model_call_count || 0}</span>
              <p>Model calls recorded</p>
              <small>Includes {snapshot.metrics.failed_model_calls || 0} failed calls.</small>
            </article>
            <article>
              <span>{Math.round(snapshot.metrics.provider_measured_tokens || 0).toLocaleString()}</span>
              <p>Tokens reported by providers</p>
              <small>Direct usage data was available for {snapshot.metrics.provider_measurement_coverage_percent || 0}% of calls.</small>
            </article>
            <article>
              <span>{Math.round(snapshot.metrics.estimated_tokens || 0).toLocaleString()}</span>
              <p>Tokens TGRAM had to estimate</p>
              <small>Used only when a provider did not return token usage.</small>
            </article>
          </div>
          </section>
          <details className="savings-details">
            <summary>Show technical token and cache diagnostics</summary>
            <p>These numbers help explain differences between the prompt TGRAM assembled and the input a provider billed or reported.</p>
            <p><b>{snapshot.metrics.excluded_historical_calls || 0} historical calls</b> ({Math.round(snapshot.metrics.excluded_historical_tokens || 0).toLocaleString()} tokens) are retained for audit and excluded from current accounting.</p>
          <div className="metrics savings-metrics" aria-label="Token boundary reconciliation">
            <article>
              <span>{Math.round(snapshot.metrics.local_observed_input_tokens || 0).toLocaleString()}</span>
              <p>Prompt assembled by TGRAM</p>
              <small>Local token count of the prompt and output schema before launch.</small>
            </article>
            <article>
              <span>{Math.round(snapshot.metrics.provider_cached_input_tokens || 0).toLocaleString()}</span>
              <p>Cached provider input</p>
              <small>Previously processed input the provider marked as cache-reused.</small>
            </article>
            <article>
              <span>{Math.round(snapshot.metrics.provider_uncached_input_tokens || 0).toLocaleString()}</span>
              <p>New provider input</p>
              <small>Provider-reported input after its cached portion is removed.</small>
            </article>
            <article>
              <span>{Math.round(snapshot.metrics.provider_unexplained_uncached_input_tokens || 0).toLocaleString()}</span>
              <p>Input not explained locally</p>
              <small>New provider input minus TGRAM&apos;s locally counted prompt and schema.</small>
            </article>
          </div>
          {(snapshot.metrics.token_diagnostics || []).length > 0 && (
            <><h4>Recent calls</h4><div className="metrics savings-metrics savings-call-list" aria-label="Recent token diagnostics">
              {(snapshot.metrics.token_diagnostics || []).slice(0, 6).map((call, index) => (
                <article key={`${call.occurred_at}-${index}`}>
                  <span>{Math.round(call.provider_input_tokens || 0).toLocaleString()}</span>
                  <p>{call.operation}</p>
                  <small>
                    Local prompt {call.local_prompt_tokens || 0} · output schema {call.local_output_schema_tokens || 0}
                    {" · "}not explained locally {call.provider_unexplained_input_tokens || 0}
                    {call.component_tokens
                      ? ` · ${Object.entries(call.component_tokens).map(([name, tokens]) => `${name} ${tokens}`).join(" · ")}`
                      : ""}
                    {` · events ${call.codex_event_count || 0} · commands ${call.codex_command_count || 0}`}
                    {` · tools ${call.codex_exposed_tool_activity ? "yes" : "none"}`}
                    {call.codex_reported_usage_breakdown
                      ? ` · usage ${Object.entries(call.codex_reported_usage_breakdown).map(([name, tokens]) => `${name} ${tokens}`).join(" · ")}`
                      : ""}
                  </small>
                </article>
              ))}
            </div></>
          )}
          </details>
          {(snapshot.metrics.unmetered_model_calls || 0) > 0 && (
            <p className="notice savings-notice">
              {snapshot.metrics.unmetered_model_calls} call(s) use token estimates because
              their provider did not report usage.
            </p>
          )}
          {(snapshot.metrics.legacy_unmetered_model_calls || 0) > 0 && (
            <p className="notice savings-notice">
              {snapshot.metrics.legacy_unmetered_model_calls} historical implementation
              call(s) occurred before the unified ledger and remain unmetered.
            </p>
          )}
        </div>
      </section>

      <section hidden={activeTab !== "lab"} className="workspace">
        <aside className="rail">
          <p>RUN LINEAGE</p>
          {tasks.map((task) => (
            <button
              key={task.id}
              className={selected?.id === task.id ? "active" : ""}
              onClick={() => setSelectedId(task.id)}
              style={{ marginLeft: `${Math.min(task.depth || 0, 3) * 8}px` }}
            >
              <b>
                <i className={`task-state ${statusClass(task.status)}`} />
                {task.kind.replace("_", " ")}
              </b>
              <span>
                {shortId(task.id)} · {task.status.toLowerCase()}
              </span>
            </button>
          ))}
          <footer>
            Auto-refresh <strong>2s</strong>
          </footer>
        </aside>

        <div className="canvas">
          <div className="canvas-head">
            <div>
              <p className="eyebrow">TASK GRAPH</p>
              <h2>Recursive evidence path</h2>
            </div>
            <div className="legend">
              <span>
                <i className="dot task" />
                Task
              </span>
              <span>
                <i className="dot attempt-dot" />
                Attempt
              </span>
              <span>
                <i className="dot claim" />
                Evidence
              </span>
            </div>
          </div>
          {snapshot.nodes.length === 0 ? (
            <div className="empty-state">
              <b>No demonstration graph yet</b>
              <span>Reset the demo to seed the isolated task lineage.</span>
            </div>
          ) : (
            <>
              <div className="flow dynamic-flow">
                {tasks.map((task, index) => (
                  <div className="flow-item" key={task.id}>
                    <button
                      className={`node task-node ${statusClass(task.status)} ${selected?.id === task.id ? "selected" : ""}`}
                      onClick={() => setSelectedId(task.id)}
                    >
                      <small>{task.kind}</small>
                      <h3>{task.title}</h3>
                      <p>
                        {task.attempt_count || 0} supervisor{" "}
                        {task.attempt_count === 1 ? "attempt" : "attempts"}
                      </p>
                      <span className="status">{task.status}</span>
                    </button>
                    {index < tasks.length - 1 && (
                      <div className="connector">
                        <span>SPAWNED</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="evidence-strip">
                <div className="strip-title">
                  <p className="eyebrow">DECISION TRAIL</p>
                  <span>
                    {planDecisions.length} planner decisions ·{" "}
                    {snapshot.metrics.replanning_decisions || 0} replans ·{" "}
                    {pathways.length} virtual pathways
                  </span>
                </div>
                <div className="trail">
                  {planningRuns.map((run) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(run.status)} ${selected?.id === run.id ? "selected" : ""}`}
                      key={run.id}
                      onClick={() => setSelectedId(run.id)}
                    >
                      <small>LIVE PLAN BUDGET</small>
                      <b>
                        {run.model_calls_used}/{run.max_model_calls} calls
                      </b>
                      <span>
                        {run.retrieval_tokens_used}/{run.max_retrieval_tokens}{" "}
                        tokens · {(run.elapsed_seconds || 0).toFixed(2)}/
                        {run.max_wall_time_seconds}s
                      </span>
                    </button>
                  ))}
                  {planDecisions.map((decision) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(decision.status)} ${selected?.id === decision.id ? "selected" : ""}`}
                      key={decision.id}
                      onClick={() => setSelectedId(decision.id)}
                    >
                      <small>PLANNER · {decision.kind}</small>
                      <b>
                        {decision.route || "policy"} · priority{" "}
                        {(typeof decision.priority === "number" ? decision.priority.toFixed(1) : decision.priority || "0")}
                      </b>
                      <span>
                        {Math.round((decision.uncertainty || 0) * 100)}%
                        uncertainty · {decision.reason}
                      </span>
                    </button>
                  ))}
                  {executions.map((execution) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(execution.status)} ${selected?.id === execution.id ? "selected" : ""}`}
                      key={execution.id}
                      onClick={() => setSelectedId(execution.id)}
                    >
                      <small>EXECUTION · {execution.actual_route}</small>
                      <b>
                        {execution.worker} · {execution.status.toLowerCase()}
                      </b>
                      <span>
                        {execution.total_tokens} tokens · $
                        {(execution.estimated_cost_usd || 0).toFixed(6)} ·{" "}
                        {(execution.latency_ms || 0).toFixed(1)}ms
                        {execution.fallback_from_attempt_id
                          ? " · fallback"
                          : ""}
                      </span>
                    </button>
                  ))}
                  {policyUpdates.map((update) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(update.status)} ${selected?.id === update.id ? "selected" : ""}`}
                      key={update.id}
                      onClick={() => setSelectedId(update.id)}
                    >
                      <small>ROUTING POLICY · v{update.version}</small>
                      <b>
                        {update.from_route} → {update.to_route}
                      </b>
                      <span>
                        {update.evidence_execution_ids?.length || 0} evidence
                        attempts · fixed safety retained
                      </span>
                    </button>
                  ))}
                  {routePredictions.map((prediction) => (
                    <button
                      className={`trail-card pathway-decision-card ${statusClass(prediction.status)} ${selected?.id === prediction.id ? "selected" : ""}`}
                      key={prediction.id}
                      onClick={() => setSelectedId(prediction.id)}
                    >
                      <small>
                        ROUTE PREDICTION · v{prediction.policy_version}
                      </small>
                      <b>
                        {prediction.static_route} → {prediction.chosen_route}
                      </b>
                      <span>
                        {prediction.chosen_worker} ·{" "}
                        {prediction.changed_static_route
                          ? "learned override"
                          : "static retained"}
                      </span>
                    </button>
                  ))}
                  {routeEvaluations.map((evaluation) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(evaluation.status)} ${selected?.id === evaluation.id ? "selected" : ""}`}
                      key={evaluation.id}
                      onClick={() => setSelectedId(evaluation.id)}
                    >
                      <small>PREDICTED VS ACTUAL</small>
                      <b>
                        {evaluation.predicted_route} →{" "}
                        {evaluation.actual_final_route}
                      </b>
                      <span>
                        {evaluation.worker_calls} calls ·{" "}
                        {evaluation.fallback_count} fallbacks · $
                        {(evaluation.cost_error_usd || 0).toFixed(6)} cost error
                      </span>
                    </button>
                  ))}
                  {projects.map((project) => (
                    <button
                      className={`trail-card pathway-card ${statusClass(project.status)} ${selected?.id === project.id ? "selected" : ""}`}
                      key={project.id}
                      onClick={() => setSelectedId(project.id)}
                    >
                      <small>EXPLICIT PROJECT ROOT</small>
                      <b>{project.read_only ? "READ ONLY" : "UNSAFE"}</b>
                      <span>{project.root}</span>
                    </button>
                  ))}
                  {projectScans.map((scan) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(scan.status)} ${selected?.id === scan.id ? "selected" : ""}`}
                      key={scan.id}
                      onClick={() => setSelectedId(scan.id)}
                    >
                      <small>INCREMENTAL PROJECT SCAN</small>
                      <b>
                        {scan.parsed_file_count} parsed ·{" "}
                        {scan.reused_file_ids?.length || 0} reused
                      </b>
                      <span>
                        {scan.content_read_file_count || 0} source reads ·{" "}
                        {scan.model_calls} model calls ·{" "}
                        {scan.read_only_verified
                          ? "read-only verified"
                          : "unverified"}
                      </span>
                    </button>
                  ))}
                  {repairProposals.map((proposal) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(proposal.status)} ${selected?.id === proposal.id ? "selected" : ""}`}
                      key={proposal.id}
                      onClick={() => setSelectedId(proposal.id)}
                    >
                      <small>SANDBOXED PATCH</small>
                      <b>
                        {proposal.changes?.length || 0} changed file
                        {proposal.changes?.length === 1 ? "" : "s"}
                      </b>
                      <span>
                        {proposal.worker} · {proposal.model_calls} model call
                        {proposal.model_calls === 1 ? "" : "s"} ·{" "}
                        {proposal.status.toLowerCase()}
                      </span>
                    </button>
                  ))}
                  {repairValidations.map((validation) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(validation.status)} ${selected?.id === validation.id ? "selected" : ""}`}
                      key={validation.id}
                      onClick={() => setSelectedId(validation.id)}
                    >
                      <small>BEFORE / AFTER VALIDATION</small>
                      <b>
                        exit {validation.before?.exit_code} →{" "}
                        {validation.after?.exit_code}
                      </b>
                      <span>
                        attempt {validation.attempt} ·{" "}
                        {validation.original_unchanged
                          ? "original unchanged"
                          : "ORIGINAL CHANGED"}
                      </span>
                    </button>
                  ))}
                  {repairApprovals.map((approval) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(approval.status)} ${selected?.id === approval.id ? "selected" : ""}`}
                      key={approval.id}
                      onClick={() => setSelectedId(approval.id)}
                    >
                      <small>HUMAN REPAIR DECISION</small>
                      <b>
                        {approval.decision} · {approval.approved_by}
                      </b>
                      <span>{approval.reason}</span>
                    </button>
                  ))}
                  {repairPromotions.map((promotion) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(promotion.status)} ${selected?.id === promotion.id ? "selected" : ""}`}
                      key={promotion.id}
                      onClick={() => setSelectedId(promotion.id)}
                    >
                      <small>REAL PROJECT PROMOTION</small>
                      <b>{promotion.status.replaceAll("_", " ")}</b>
                      <span>
                        {promotion.final_validation
                          ? `final exit ${promotion.final_validation.exit_code}`
                          : "awaiting validation"}{" "}
                        ·{" "}
                        {promotion.rollback_verified
                          ? "rollback verified"
                          : "transaction recorded"}
                      </span>
                    </button>
                  ))}
                  {postRepairReconciliations.map((reconciliation) => (
                    <button
                      className={`trail-card pathway-decision-card ${statusClass(reconciliation.status)} ${selected?.id === reconciliation.id ? "selected" : ""}`}
                      key={reconciliation.id}
                      onClick={() => setSelectedId(reconciliation.id)}
                    >
                      <small>POST-REPAIR RECONCILIATION</small>
                      <b>
                        {reconciliation.affected_paths?.length || 0} affected
                        file reparsed
                      </b>
                      <span>
                        {reconciliation.invalidated_claim_ids?.length || 0}{" "}
                        stale claims invalidated ·{" "}
                        {reconciliation.follow_up_worker_calls || 0} follow-up
                        worker calls
                      </span>
                    </button>
                  ))}
                  {maintenanceWorkflows.map((workflow) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(workflow.status)} ${selected?.id === workflow.id ? "selected" : ""}`}
                      key={workflow.id}
                      onClick={() => setSelectedId(workflow.id)}
                    >
                      <small>DURABLE MAINTENANCE WORKFLOW</small>
                      <b>{workflow.status.replaceAll("_", " ")}</b>
                      <span>
                        {workflow.diagnosis_worker_calls || 0} diagnosis ·{" "}
                        {workflow.repair_worker_calls || 0} repair ·{" "}
                        {workflow.follow_up_worker_calls || 0} follow-up calls
                      </span>
                    </button>
                  ))}
                  {projectLeases.map((lease) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(lease.status)} ${selected?.id === lease.id ? "selected" : ""}`}
                      key={lease.id}
                      onClick={() => setSelectedId(lease.id)}
                    >
                      <small>PROJECT MUTATION LEASE</small>
                      <b>
                        {lease.status} · fence {lease.fencing_token}
                      </b>
                      <span>
                        {lease.holder_id} · {lease.events?.length || 0} durable
                        events
                      </span>
                    </button>
                  ))}
                  {evaluationRuns.map((run) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(run.status)} ${selected?.id === run.id ? "selected" : ""}`}
                      key={run.id}
                      onClick={() => setSelectedId(run.id)}
                    >
                      <small>
                        {run.suite_version?.startsWith("project-")
                          ? "PROJECT READ-ONLY EVALUATION"
                          : "DETERMINISTIC EVALUATION"}
                      </small>
                      <b>
                        {run.status} · {run.repetitions} repetitions
                      </b>
                      <span>
                        {run.case_contract_count || run.results?.length || 0}{" "}
                        contracts ·{" "}
                        {run.exact_replays_zero_calls
                          ? "zero-call replay"
                          : run.reproducible
                            ? "reproducible"
                            : "not reproducible"}
                      </span>
                    </button>
                  ))}
                  {evaluationResults.map((result) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(result.status)} ${selected?.id === result.id ? "selected" : ""}`}
                      key={result.id}
                      onClick={() => setSelectedId(result.id)}
                    >
                      <small>
                        {result.strategy} · {result.scenario}
                      </small>
                      <b>
                        {result.case_id} · repeat {result.repetition}
                      </b>
                      <span>
                        {result.worker_calls} worker ·{" "}
                        {result.resolution_calls || 0} resolution ·{" "}
                        {result.retrieval_size || 0} evidence lines ·{" "}
                        {result.memory_reuses} reuses
                      </span>
                    </button>
                  ))}
                  {codexReadOnlyProofs.map((proof) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(proof.status)} ${selected?.id === proof.id ? "selected" : ""}`}
                      key={proof.id}
                      onClick={() => setSelectedId(proof.id)}
                    >
                      <small>BOUNDED CODEX · READ ONLY</small>
                      <b>
                        {proof.status} · {proof.initial_codex_calls} →{" "}
                        {proof.replay_codex_calls} calls
                      </b>
                      <span>
                        {proof.authorized_paths?.length || 0} allowed files ·{" "}
                        {proof.input_tokens} input tokens ·{" "}
                        {(proof.latency_ms || 0).toFixed(0)}ms
                      </span>
                    </button>
                  ))}
                  {recursiveCodexProofs.map((proof) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(proof.status)} ${selected?.id === proof.id ? "selected" : ""}`}
                      key={proof.id}
                      onClick={() => setSelectedId(proof.id)}
                    >
                      <small>RECURSIVE CODEX DELEGATION</small>
                      <b>
                        {proof.status} · {proof.branch_results?.length || 0}{" "}
                        branches · {proof.initial_codex_calls} →{" "}
                        {proof.replay_codex_calls} calls
                      </b>
                      <span>
                        {proof.agreements?.length || 0} agreements ·{" "}
                        {proof.contradictions?.length || 0} contradictions ·{" "}
                        {proof.follow_up_created
                          ? `${proof.follow_up_codex_calls} follow-up call`
                          : "no follow-up needed"}
                      </span>
                    </button>
                  ))}
                  {genericCodexEvaluations.map((evaluation) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(evaluation.status)} ${selected?.id === evaluation.id ? "selected" : ""}`}
                      key={evaluation.id}
                      onClick={() => setSelectedId(evaluation.id)}
                    >
                      <small>GENERIC PROJECT DELEGATION</small>
                      <b>
                        {evaluation.status} · {evaluation.subsystem_count}{" "}
                        subsystems
                      </b>
                      <span>
                        {evaluation.initial_codex_calls} →{" "}
                        {evaluation.replay_codex_calls} calls ·{" "}
                        {evaluation.abstention_verified
                          ? "safe abstention verified"
                          : "no abstention proof"}
                      </span>
                    </button>
                  ))}
                  {investigationSessions.map((session) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(session.status)} ${selected?.id === session.id ? "selected" : ""}`}
                      key={session.id}
                      onClick={() => setSelectedId(session.id)}
                    >
                      <small>DURABLE INVESTIGATION SESSION</small>
                      <b>
                        {session.status} · {session.active_stage}
                      </b>
                      <span>
                        {session.checkpoints?.length || 0} checkpoints ·{" "}
                        {session.remaining_tasks?.length || 0} remaining ·{" "}
                        {session.avoided_codex_calls || 0} calls avoided
                      </span>
                    </button>
                  ))}
                  {resumableSessionEvaluations.map((evaluation) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(evaluation.status)} ${selected?.id === evaluation.id ? "selected" : ""}`}
                      key={evaluation.id}
                      onClick={() => setSelectedId(evaluation.id)}
                    >
                      <small>RECOVERY EVALUATION</small>
                      <b>
                        {evaluation.status} · {evaluation.subsystem_count}{" "}
                        subsystems
                      </b>
                      <span>
                        {evaluation.avoided_codex_calls || 0} calls avoided ·
                        planning through synthesis
                      </span>
                    </button>
                  ))}
                  {unrealIndexScans.map((scan) => (
                    <button
                      className={`trail-card pathway-card ${statusClass(scan.status)} ${selected?.id === scan.id ? "selected" : ""}`}
                      key={scan.id}
                      onClick={() => setSelectedId(scan.id)}
                    >
                      <small>UNREAL PROJECT INDEX</small>
                      <b>
                        {scan.status} · {scan.artifact_count} artifacts
                      </b>
                      <span>
                        {scan.dependency_count} relationships ·{" "}
                        {scan.parsed_artifact_count} parsed ·{" "}
                        {scan.reused_artifact_count} reused
                      </span>
                    </button>
                  ))}






                  {workspaceHistory.map((result) => (
                    <button
                      className={`trail-card evidence-card ${statusClass(result.status)} ${selected?.id === result.id ? "selected" : ""}`}
                      key={result.id}
                      onClick={() => setSelectedId(result.id)}
                    >
                      <small>PROJECT WORKSPACE · {result.kind}</small>
                      <b>{result.project_name}</b>
                      <span>
                        {result.affected_paths?.length || 0} files ·{" "}
                        {result.evidence?.length || 0} evidence
                      </span>
                    </button>
                  ))}
                  {unrealArtifacts
                    .filter(
                      (item) =>
                        item.kind === "MAP" ||
                        item.kind === "BLUEPRINT" ||
                        item.kind === "MODULE_RULES" ||
                        item.kind === "PLUGIN_DESCRIPTOR",
                    )
                    .map((item) => (
                      <button
                        className={`trail-card evidence-card ${statusClass(item.status)} ${selected?.id === item.id ? "selected" : ""}`}
                        key={item.id}
                        onClick={() => setSelectedId(item.id)}
                      >
                        <small>UNREAL {item.kind}</small>
                        <b>{item.name}</b>
                        <span>{item.path}</span>
                      </button>
                    ))}
                  {unrealDependencies
                    .filter((item) => item.target_artifact_id)
                    .slice(0, 100)
                    .map((item) => (
                      <button
                        className={`trail-card reconstruction-step ${statusClass(item.status)} ${selected?.id === item.id ? "selected" : ""}`}
                        key={item.id}
                        onClick={() => setSelectedId(item.id)}
                      >
                        <small>UNREAL RELATIONSHIP</small>
                        <b>{item.kind}</b>
                        <span>
                          {item.source_path} → {item.target_reference}
                        </span>
                      </button>
                    ))}
                  {projectFiles
                    .filter((file) => file.status !== "ACTIVE")
                    .map((file) => (
                      <button
                        className={`trail-card evidence-card ${statusClass(file.status)} ${selected?.id === file.id ? "selected" : ""}`}
                        key={file.id}
                        onClick={() => setSelectedId(file.id)}
                      >
                        <small>PROJECT FILE CHANGE</small>
                        <b>{file.status}</b>
                        <span>{file.title}</span>
                      </button>
                    ))}
                  {pathways.map((pathway) => (
                    <button
                      className={`trail-card pathway-card ${statusClass(pathway.status)} ${selected?.id === pathway.id ? "selected" : ""}`}
                      key={pathway.id}
                      onClick={() => setSelectedId(pathway.id)}
                    >
                      <small>VIRTUAL MEMORY TOKEN</small>
                      <b>{pathway.token}</b>
                      <span>
                        v{pathway.version} · {pathway.access_frequency}{" "}
                        traversals · {pathway.status.toLowerCase()}
                      </span>
                    </button>
                  ))}
                  {pathwayBenchmarks.map((result) => (
                    <button
                      className={`trail-card pathway-benchmark-card ${selected?.id === result.id ? "selected" : ""}`}
                      key={result.id}
                      onClick={() => setSelectedId(result.id)}
                    >
                      <small>TOKENIZED PATHWAY</small>
                      <b>
                        {Math.round((result.additional_reduction || 0) * 100)}%
                        extra reduction
                      </b>
                      <span>
                        {result.token_input_tokens}/{result.active_input_tokens}{" "}
                        tokens · {result.status.toLowerCase()}
                      </span>
                    </button>
                  ))}
                  {pathwayDecisions.map((decision) => (
                    <button
                      className={`trail-card pathway-decision-card ${statusClass(decision.status)} ${selected?.id === decision.id ? "selected" : ""}`}
                      key={decision.id}
                      onClick={() => setSelectedId(decision.id)}
                    >
                      <small>PATHWAY POLICY</small>
                      <b>{decision.status.toLowerCase()}</b>
                      <span>
                        {decision.observed_frequency}/
                        {decision.minimum_frequency} uses ·{" "}
                        {Math.round(
                          decision.observed_average_tokens_saved || 0,
                        )}{" "}
                        tokens saved
                      </span>
                    </button>
                  ))}
                  {benchmarks.map((run) => (
                    <button
                      className={`trail-card benchmark-card ${statusClass(run.status)} ${selected?.id === run.id ? "selected" : ""}`}
                      key={run.id}
                      onClick={() => setSelectedId(run.id)}
                    >
                      <small>TOKEN BENCHMARK</small>
                      <b>
                        {Math.round((run.token_reduction || 0) * 100)}%
                        reduction
                      </b>
                      <span>
                        {run.active?.input_tokens}/{run.fixed?.input_tokens}{" "}
                        tokens · {run.status.toLowerCase()}
                      </span>
                    </button>
                  ))}
                  {promotions.map((decision) => (
                    <button
                      className={`trail-card promotion-card ${statusClass(decision.status)} ${selected?.id === decision.id ? "selected" : ""}`}
                      key={decision.id}
                      onClick={() => setSelectedId(decision.id)}
                    >
                      <small>PROMOTION POLICY</small>
                      <b>
                        {decision.from_tier?.toLowerCase()} →{" "}
                        {decision.to_tier?.toLowerCase()}
                      </b>
                      <span>
                        {decision.status.toLowerCase()} ·{" "}
                        {decision.observed_support}/{decision.minimum_support}{" "}
                        independent support
                      </span>
                    </button>
                  ))}
                  {reconstructions.map((session) => (
                    <button
                      className={`trail-card reconstruction-card ${selected?.id === session.id ? "selected" : ""}`}
                      key={session.id}
                      onClick={() => setSelectedId(session.id)}
                    >
                      <small>ACTIVE CONTEXT</small>
                      <b>
                        {session.selected_node_ids?.length || 0} of{" "}
                        {session.baseline_node_ids?.length || 0} nodes
                      </b>
                      <span>
                        {session.reconstructed_tokens || 0} vs{" "}
                        {session.baseline_tokens || 0} tokens ·{" "}
                        {session.evidence_preserved === false
                          ? "evidence missing"
                          : "evidence preserved"}
                      </span>
                    </button>
                  ))}
                  {reconstructionSteps.map((step) => (
                    <button
                      className={`trail-card reconstruction-step ${statusClass(step.status)} ${selected?.id === step.id ? "selected" : ""}`}
                      key={step.id}
                      onClick={() => setSelectedId(step.id)}
                    >
                      <small>STEP {(step.sequence || 0) + 1}</small>
                      <b>{step.action?.toLowerCase()}</b>
                      <span>
                        {step.claim_id ? shortId(step.claim_id) : ""} ·{" "}
                        {Math.round((step.score || 0) * 100)}%
                      </span>
                    </button>
                  ))}
                  {clusters.map((cluster) => (
                    <button
                      className={`trail-card cluster-card ${selected?.id === cluster.id ? "selected" : ""}`}
                      key={cluster.id}
                      onClick={() => setSelectedId(cluster.id)}
                    >
                      <small>CONFLICT CLUSTER</small>
                      <b>
                        {cluster.interpretations?.length || 0} interpretations
                      </b>
                      <span>
                        {cluster.corroborated_claim_ids?.length || 0}{" "}
                        corroborating · {cluster.outlier_claim_ids?.length || 0}{" "}
                        outlier
                      </span>
                    </button>
                  ))}
                  {verdicts.map((verdict) => (
                    <button
                      className={`trail-card cluster-card ${statusClass(verdict.status)} ${selected?.id === verdict.id ? "selected" : ""}`}
                      key={verdict.id}
                      onClick={() => setSelectedId(verdict.id)}
                    >
                      <small>EVIDENCE-BASED VERDICT</small>
                      <b>{verdict.selected_value || "UNRESOLVED"}</b>
                      <span>
                        {Math.round((verdict.confidence || 0) * 100)}%
                        confidence · {verdict.supporting_claim_ids?.length || 0}{" "}
                        support · {verdict.contradicting_claim_ids?.length || 0}{" "}
                        contradict
                      </span>
                    </button>
                  ))}
                  {attempts.map((attempt, index) => (
                    <div className="trail-group" key={attempt.id}>
                      <button
                        className={`trail-card attempt-card ${statusClass(attempt.status)} ${selected?.id === attempt.id ? "selected" : ""}`}
                        onClick={() => setSelectedId(attempt.id)}
                      >
                        <small>ATTEMPT {index + 1}</small>
                        <b>{attempt.selected_claim || "pending"}</b>
                        <span>
                          {Math.round((attempt.confidence || 0) * 100)}%
                          confidence
                        </span>
                      </button>
                      {index === 0 &&
                        evidenceClaims.map((claim) => (
                          <button
                            className={`trail-card evidence-card ${selected?.id === claim.id ? "selected" : ""}`}
                            key={claim.id}
                            onClick={() => setSelectedId(claim.id)}
                          >
                            <small>EVIDENCE</small>
                            <b>{claim.conclusion}</b>
                            <span>
                              {claim.evidence?.length || 0} citations ·{" "}
                              {claim.producer}
                            </span>
                          </button>
                        ))}
                    </div>
                  ))}
                </div>
              </div>
              <div className="relationships">
                <p className="eyebrow">RELATIONSHIPS</p>
                <div>
                  {snapshot.edges.map((edge, index) => (
                    <button
                      key={`${edge.source}-${edge.relation}-${edge.target}-${index}`}
                      onClick={() => setSelectedId(edge.target)}
                    >
                      <span>{shortId(edge.source)}</span>
                      <b>{edge.relation}</b>
                      <span>{shortId(edge.target)}</span>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <aside className="inspector">
          {selected ? (
            <>
              <p className="eyebrow">SELECTED {selected.node_type}</p>
              <h2>{selected.title}</h2>
              <span className={`pill ${statusClass(selected.status)}`}>
                {selected.kind} · {selected.status}
              </span>
              <dl>
                {selected.confidence != null && (
                  <>
                    <dt>Confidence</dt>
                    <dd>
                      <b className="bar">
                        <i style={{ width: `${selected.confidence * 100}%` }} />
                      </b>{" "}
                      {Math.round(selected.confidence * 100)}%
                    </dd>
                  </>
                )}
                {selected.route && (
                  <>
                    <dt>Planner route</dt>
                    <dd>
                      <b>{selected.route}</b> · priority{" "}
                      {(typeof selected.priority === "number" ? selected.priority.toFixed(1) : selected.priority || "0")} ·{" "}
                      {Math.round((selected.uncertainty || 0) * 100)}%
                      uncertainty ·{" "}
                      {Math.round((selected.difficulty || 0) * 100)}% difficulty
                    </dd>
                  </>
                )}
                {selected.actual_route && (
                  <>
                    <dt>Execution route</dt>
                    <dd>
                      <b>
                        {selected.planned_route} → {selected.actual_route}
                      </b>{" "}
                      · {selected.worker} · {selected.outcome?.toLowerCase()}
                    </dd>
                    <dt>Measured execution</dt>
                    <dd>
                      {selected.input_tokens} input + {selected.output_tokens}{" "}
                      output = {selected.total_tokens} tokens · $
                      {(selected.estimated_cost_usd || 0).toFixed(6)} ·{" "}
                      {(selected.latency_ms || 0).toFixed(2)}ms
                    </dd>
                  </>
                )}
                {selected.fallback_from_attempt_id && (
                  <>
                    <dt>Fallback from</dt>
                    <dd>
                      {shortId(selected.fallback_from_attempt_id)} ·{" "}
                      {selected.fallback_reason}
                    </dd>
                  </>
                )}
                {selected.chosen_route && (
                  <>
                    <dt>Learned route prediction</dt>
                    <dd>
                      <b>
                        {selected.static_route} → {selected.chosen_route}
                      </b>{" "}
                      · {selected.chosen_worker} · policy v
                      {selected.policy_version}
                    </dd>
                    <dt>Evidence gate</dt>
                    <dd>
                      {selected.minimum_evidence} samples ·{" "}
                      {Math.round(
                        (selected.required_success_probability || 0) * 100,
                      )}
                      % required success ·{" "}
                      {selected.changed_static_route
                        ? "route changed"
                        : "static route retained"}
                    </dd>
                  </>
                )}
                {(selected.candidates?.length || 0) > 0 && (
                  <>
                    <dt>Calibrated candidates</dt>
                    {selected.candidates?.map((candidate) => (
                      <dd
                        className="interpretation"
                        key={`${candidate.route}-${candidate.worker}`}
                      >
                        <b>
                          {candidate.worker} · {candidate.route}
                        </b>
                        {candidate.sample_count} samples ·{" "}
                        {Math.round(
                          candidate.predicted_success_probability * 100,
                        )}
                        % predicted success ·{" "}
                        {Math.round(candidate.calibration_error * 100)}%
                        calibration error · $
                        {candidate.predicted_cost_usd.toFixed(6)}
                        <small>
                          {candidate.eligible
                            ? "eligible"
                            : "insufficient evidence"}
                        </small>
                      </dd>
                    ))}
                  </>
                )}
                {selected.previous_version != null && (
                  <>
                    <dt>Policy update</dt>
                    <dd>
                      <b>
                        v{selected.previous_version} → v{selected.version}
                      </b>{" "}
                      · {selected.from_route} → {selected.to_route} ·{" "}
                      {selected.accepted ? "accepted" : "rejected"}
                    </dd>
                  </>
                )}
                {(selected.evidence_execution_ids?.length || 0) > 0 && (
                  <>
                    <dt>Policy evidence</dt>
                    <dd>
                      {selected.evidence_execution_ids
                        ?.map(shortId)
                        .join(" · ")}
                    </dd>
                  </>
                )}
                {selected.fixed_safety_limits && (
                  <>
                    <dt>Fixed safety limits</dt>
                    <dd>
                      {Object.entries(selected.fixed_safety_limits)
                        .map(([key, value]) => `${key}: ${value}`)
                        .join(" · ")}
                    </dd>
                  </>
                )}
                {selected.from_route && selected.reason && (
                  <>
                    <dt>Why policy changed</dt>
                    <dd>{selected.reason}</dd>
                  </>
                )}
                {selected.actual_success != null && (
                  <>
                    <dt>Prediction outcome</dt>
                    <dd>
                      <b>{selected.actual_success ? "Successful" : "Failed"}</b>{" "}
                      · {selected.predicted_route} predicted,{" "}
                      {selected.actual_final_route} final ·{" "}
                      {selected.worker_calls} calls · {selected.fallback_count}{" "}
                      fallbacks
                    </dd>
                    <dt>Predicted versus actual</dt>
                    <dd>
                      ${(selected.predicted_cost_usd || 0).toFixed(6)} → $
                      {(selected.actual_cost_usd || 0).toFixed(6)} cost ·{" "}
                      {(selected.predicted_latency_ms || 0).toFixed(2)} →{" "}
                      {(selected.actual_latency_ms || 0).toFixed(2)}ms ·{" "}
                      {Math.round(selected.predicted_tokens || 0)} →{" "}
                      {selected.actual_tokens} tokens
                    </dd>
                  </>
                )}
                {selected.node_type === "project" && (
                  <>
                    <dt>Explicitly selected root</dt>
                    <dd>{selected.root}</dd>
                    <dt>Project safety policy</dt>
                    <dd>
                      <b>{selected.read_only ? "READ ONLY" : "UNSAFE"}</b> ·{" "}
                      {selected.explicitly_selected
                        ? "explicit user selection recorded"
                        : "selection missing"}{" "}
                      · graph storage kept outside project
                    </dd>
                  </>
                )}
                {selected.node_type === "project_scan" && (
                  <>
                    <dt>Incremental scan result</dt>
                    <dd>
                      <b>{selected.parsed_file_count} parsed</b> ·{" "}
                      {selected.content_read_file_count || 0} source files read
                      · {selected.reused_file_ids?.length || 0} unchanged files
                      reused · {selected.model_calls} model calls
                    </dd>
                    <dt>Indexed project graph</dt>
                    <dd>
                      {selected.file_count} files · {selected.symbol_count}{" "}
                      symbols · {selected.test_count} tests ·{" "}
                      {selected.dependency_count} dependencies
                    </dd>
                    <dt>Read-only verification</dt>
                    <dd>
                      {selected.read_only_verified
                        ? "Passed — source manifest unchanged"
                        : "FAILED"}
                    </dd>
                  </>
                )}
                {selected.reused_claim_id && (
                  <>
                    <dt>Graph memory reuse</dt>
                    <dd>
                      <b>REUSED {shortId(selected.reused_claim_id)}</b> ·{" "}
                      {selected.reuse_type} · zero investigation calls
                    </dd>
                    <dt>Why it was reused</dt>
                    <dd>{selected.reuse_reason}</dd>
                  </>
                )}
                {selected.node_type === "task" &&
                  (selected.files?.length || 0) > 0 && (
                    <>
                      <dt>Authorized dependency slice</dt>
                      <dd>
                        <b>
                          {selected.files?.length} file
                          {selected.files?.length === 1 ? "" : "s"}
                        </b>{" "}
                        · {selected.files?.join(" · ")}
                      </dd>
                    </>
                  )}
                {selected.node_type === "task" &&
                  (selected.source_claim_ids?.length || 0) > 0 && (
                    <>
                      <dt>Final synthesis inputs</dt>
                      <dd>
                        {selected.source_claim_ids?.map(shortId).join(" · ")}
                      </dd>
                    </>
                  )}
                {selected.node_type === "repair_proposal" && (
                  <>
                    <dt>Diagnosis provenance</dt>
                    <dd>
                      {shortId(selected.diagnosis_claim_id || "")} ·{" "}
                      {selected.supporting_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                    <dt>Authorized repair slice</dt>
                    <dd>{selected.authorized_paths?.join(" · ")}</dd>
                    <dt>Repair worker</dt>
                    <dd>
                      <b>{selected.worker}</b> · {selected.model_calls} model
                      call{selected.model_calls === 1 ? "" : "s"} ·{" "}
                      {Math.round((selected.confidence || 0) * 100)}% confidence
                    </dd>
                    <dt>Rationale</dt>
                    <dd>{selected.rationale}</dd>
                  </>
                )}
                {selected.node_type === "repair_proposal" &&
                  (selected.changes?.length || 0) > 0 && (
                    <>
                      <dt>Proposed diff</dt>
                      {selected.changes?.map((change, index) =>
                        "unified_diff" in change ? (
                          <dd
                            className="interpretation"
                            key={`${change.path}-${index}`}
                          >
                            <b>{change.path}</b>
                            <pre>{change.unified_diff}</pre>
                            <small>
                              {change.before_hash?.slice(0, 12) || "unavailable"} →{" "}
                              {change.after_hash?.slice(0, 12) || "unavailable"}
                            </small>
                          </dd>
                        ) : null,
                      )}
                    </>
                  )}
                {selected.node_type === "repair_validation" &&
                  selected.before &&
                  selected.after && (
                    <>
                      <dt>Affected test command</dt>
                      <dd>{selected.before.command.join(" ")}</dd>
                      <dt>Before repair</dt>
                      <dd>
                        <b>exit {selected.before.exit_code}</b> ·{" "}
                        {selected.before.duration_ms.toFixed(1)}ms
                        <pre>
                          {selected.before.stdout || selected.before.stderr}
                        </pre>
                      </dd>
                      <dt>After repair</dt>
                      <dd>
                        <b>exit {selected.after.exit_code}</b> ·{" "}
                        {selected.after.duration_ms.toFixed(1)}ms
                        <pre>
                          {selected.after.stdout || selected.after.stderr}
                        </pre>
                      </dd>
                      <dt>Original project integrity</dt>
                      <dd>
                        {selected.original_unchanged
                          ? "Verified byte-for-byte unchanged"
                          : "FAILED — original changed"}
                      </dd>
                      {selected.failure_reason && (
                        <>
                          <dt>Rejection reason</dt>
                          <dd>{selected.failure_reason}</dd>
                        </>
                      )}
                    </>
                  )}
                {selected.node_type === "repair_approval" && (
                  <>
                    <dt>Human approval gate</dt>
                    <dd>
                      <b>{selected.decision}</b> by {selected.approved_by}
                    </dd>
                    <dt>Review rationale</dt>
                    <dd>{selected.reason}</dd>
                    <dt>Approved artifact</dt>
                    <dd>
                      {shortId(selected.proposal_id || "")} · validation{" "}
                      {shortId(selected.validation_id || "")}
                    </dd>
                    <dt>Bound source state</dt>
                    <dd>{selected.source_tree_fingerprint?.slice(0, 16)}</dd>
                  </>
                )}
                {selected.node_type === "repair_promotion" && (
                  <>
                    <dt>Explicit project target</dt>
                    <dd>{selected.project_root}</dd>
                    <dt>Atomic application</dt>
                    <dd>
                      {selected.original_tree_fingerprint?.slice(0, 12)} →{" "}
                      {selected.applied_tree_fingerprint?.slice(0, 12) ||
                        "not completed"}
                    </dd>
                    {selected.final_validation && (
                      <>
                        <dt>Real-project final validation</dt>
                        <dd>
                          <b>exit {selected.final_validation.exit_code}</b> ·{" "}
                          {selected.final_validation.command.join(" ")}
                          <pre>
                            {selected.final_validation.stdout ||
                              selected.final_validation.stderr}
                          </pre>
                        </dd>
                      </>
                    )}
                    {selected.rollback_validation && (
                      <>
                        <dt>Automatic rollback proof</dt>
                        <dd>
                          <b>
                            {selected.rollback_verified
                              ? "ORIGINAL BYTES RESTORED"
                              : "ROLLBACK FAILED"}
                          </b>{" "}
                          · post-rollback exit{" "}
                          {selected.rollback_validation.exit_code}
                          <pre>
                            {selected.rollback_validation.stdout ||
                              selected.rollback_validation.stderr}
                          </pre>
                        </dd>
                      </>
                    )}
                    {selected.failure_reason && (
                      <>
                        <dt>Promotion failure</dt>
                        <dd>{selected.failure_reason}</dd>
                      </>
                    )}
                    {(selected.events?.length || 0) > 0 && (
                      <>
                        <dt>Complete promotion history</dt>
                        {selected.events?.map((event, index) => (
                          <dd
                            className="interpretation"
                            key={`${event.occurred_at}-${index}`}
                          >
                            <b>{event.status}</b>
                            {event.detail}
                            <small>
                              {new Date(event.occurred_at).toLocaleString()}
                            </small>
                          </dd>
                        ))}
                      </>
                    )}
                  </>
                )}
                {selected.node_type === "post_repair_reconciliation" && (
                  <>
                    <dt>Reconciled project state</dt>
                    <dd>
                      {selected.previous_project_fingerprint?.slice(0, 12)} →{" "}
                      {selected.new_project_fingerprint?.slice(0, 12)}
                    </dd>
                    <dt>Affected-file incremental scan</dt>
                    <dd>
                      <b>{selected.parsed_paths?.join(" · ")}</b> reparsed ·{" "}
                      {selected.reused_file_ids?.length || 0} unchanged files
                      reused
                    </dd>
                    <dt>Obsolete diagnosis memory</dt>
                    <dd>
                      {selected.invalidated_claim_ids?.length || 0} invalidated
                      · {selected.superseded_claim_ids?.length || 0} superseded
                      by {shortId(selected.replacement_claim_id || "")}
                    </dd>
                    <dt>Repaired-state provenance</dt>
                    <dd>
                      scan {shortId(selected.scan_id || "")} · claim{" "}
                      {shortId(selected.replacement_claim_id || "")}
                    </dd>
                    <dt>Follow-up debugging proof</dt>
                    <dd>
                      <b>{selected.follow_up_reuse_type}</b> · task{" "}
                      {shortId(selected.follow_up_task_id || "")} reused{" "}
                      {shortId(selected.follow_up_claim_id || "")} ·{" "}
                      {selected.follow_up_worker_calls} worker calls
                    </dd>
                  </>
                )}
                {selected.node_type === "maintenance_workflow" && (
                  <>
                    <dt>Durable workflow state</dt>
                    <dd>
                      <b>{selected.status.replaceAll("_", " ")}</b> ·{" "}
                      {selected.test_path}
                    </dd>
                    <dt>Initial indexed state</dt>
                    <dd>
                      {selected.initial_project_fingerprint?.slice(0, 16)}
                    </dd>
                    <dt>Persisted stage artifacts</dt>
                    <dd>
                      diagnosis{" "}
                      {shortId(selected.diagnosis_claim_id || "pending")} ·
                      patch {shortId(selected.proposal_id || "pending")} ·
                      approval {shortId(selected.approval_id || "pending")} ·
                      promotion {shortId(selected.promotion_id || "pending")} ·
                      reconciliation{" "}
                      {shortId(selected.reconciliation_id || "pending")}
                    </dd>
                    <dt>No-repeat counters</dt>
                    <dd>
                      {selected.diagnosis_worker_calls || 0} diagnosis ·{" "}
                      {selected.repair_worker_calls || 0} repair ·{" "}
                      {selected.repair_model_calls || 0} repair model ·{" "}
                      {selected.promotion_attempts || 0} promotion ·{" "}
                      {selected.follow_up_worker_calls || 0} follow-up calls
                    </dd>
                    {selected.status === "WAITING_FOR_APPROVAL" && (
                      <>
                        <dt>Human action required</dt>
                        <dd>
                          Review the verified sandbox patch, then explicitly
                          approve or reject this workflow.
                        </dd>
                      </>
                    )}
                    {(selected.events?.length || 0) > 0 && (
                      <>
                        <dt>Resumable transition history</dt>
                        {selected.events?.map((event, index) => (
                          <dd
                            className="interpretation"
                            key={`${event.occurred_at}-${index}`}
                          >
                            <b>{event.status}</b>
                            {event.detail}
                            <small>
                              {event.artifact_ids?.map(shortId).join(" · ") ||
                                "no artifact yet"}{" "}
                              · {new Date(event.occurred_at).toLocaleString()}
                            </small>
                          </dd>
                        ))}
                      </>
                    )}
                  </>
                )}
                {selected.node_type === "project_lease" && (
                  <>
                    <dt>Exclusive mutation owner</dt>
                    <dd>
                      <b>{selected.holder_id}</b> · workflow{" "}
                      {shortId(selected.workflow_id || "none")}
                    </dd>
                    <dt>Fencing and expiry</dt>
                    <dd>
                      token <b>{selected.fencing_token}</b> · expires{" "}
                      {selected.expires_at
                        ? new Date(selected.expires_at).toLocaleString()
                        : "unknown"}
                    </dd>
                    <dt>Lease event history</dt>
                    {selected.events?.map((event, index) => (
                      <dd
                        className="interpretation"
                        key={`${event.occurred_at}-${index}`}
                      >
                        <b>{event.kind}</b>
                        {event.detail}
                        <small>
                          {event.holder_id} ·{" "}
                          {new Date(event.occurred_at).toLocaleString()}
                        </small>
                      </dd>
                    ))}
                  </>
                )}
                {selected.node_type === "evaluation_run" &&
                  selected.suite_version?.startsWith("project-") && (
                    <>
                      <dt>Project evaluation verdict</dt>
                      <dd>
                        <b>
                          {selected.passed
                            ? "ALL READ-ONLY GATES PASSED"
                            : "GATE FAILURE"}
                        </b>{" "}
                        · {selected.case_contract_count} contracts across{" "}
                        {selected.subsystem_count} subsystems
                      </dd>
                      <dt>Answer and reuse gates</dt>
                      <dd>
                        correctness {selected.correctness_preserved ? "✓" : "✗"}{" "}
                        · required evidence{" "}
                        {selected.evidence_preserved ? "✓" : "✗"} · exact replay
                        zero calls{" "}
                        {selected.exact_replays_zero_calls ? "✓" : "✗"} ·
                        abstention {selected.abstention_verified ? "✓" : "✗"}
                      </dd>
                      <dt>Source safety gates</dt>
                      <dd>
                        byte integrity{" "}
                        {selected.source_integrity_verified ? "✓" : "✗"} · no
                        Project write artifacts{" "}
                        {selected.no_project_write_capability ? "✓" : "✗"}
                      </dd>
                      <dt>Manifest comparison</dt>
                      <dd>
                        {selected.initial_manifest_sha256?.slice(0, 16)} →{" "}
                        {selected.final_manifest_sha256?.slice(0, 16)}
                      </dd>
                    </>
                  )}
                {selected.node_type === "evaluation_run" &&
                  !selected.suite_version?.startsWith("project-") && (
                    <>
                      <dt>Evaluation verdict</dt>
                      <dd>
                        <b>
                          {selected.passed
                            ? "ALL GATES PASSED"
                            : "GATE FAILURE"}
                        </b>{" "}
                        · {selected.suite_version}
                      </dd>
                      <dt>Quality gates</dt>
                      <dd>
                        correctness {selected.correctness_preserved ? "✓" : "✗"}{" "}
                        · evidence {selected.evidence_preserved ? "✓" : "✗"} ·
                        repeat calls{" "}
                        {selected.fewer_repeat_worker_calls ? "✓" : "✗"} ·
                        tokens {selected.fewer_tokens_than_static ? "✓" : "✗"}
                      </dd>
                      <dt>Safety gates</dt>
                      <dd>
                        conflicts/stale memory{" "}
                        {selected.stale_or_conflicting_memory_blocked
                          ? "✓"
                          : "✗"}{" "}
                        · recovery {selected.recovery_verified ? "✓" : "✗"} ·
                        reproducible {selected.reproducible ? "✓" : "✗"}
                      </dd>
                      <dt>Compared strategies</dt>
                      <dd>
                        Memoryless · Static retrieval · RLMGraph across{" "}
                        {selected.repetitions} repetitions
                      </dd>
                    </>
                  )}
                {selected.node_type === "evaluation_result" &&
                  selected.contract_type?.startsWith("PROJECT_") && (
                    <>
                      <dt>Project evidence contract</dt>
                      <dd>
                        <b>{selected.case_id}</b> · {selected.contract_type} ·
                        repeat {selected.repetition}
                      </dd>
                      <dt>Answer</dt>
                      <dd>
                        {selected.answer} ·{" "}
                        {selected.correct
                          ? "expected"
                          : `expected ${selected.expected_answer}`}
                      </dd>
                      <dt>Required evidence</dt>
                      <dd>
                        {selected.required_evidence_paths?.join(" · ")} · terms{" "}
                        {selected.required_evidence_terms?.join(" + ") ||
                          "verdict provenance"}
                      </dd>
                      <dt>Observed retrieval</dt>
                      <dd>
                        {selected.retrieval_size || 0} evidence lines ·{" "}
                        {selected.observed_evidence_paths?.length || 0} files ·
                        terms{" "}
                        {selected.observed_evidence_terms?.join(" + ") ||
                          "verdict evidence"}
                      </dd>
                      <dt>Measured execution</dt>
                      <dd>
                        {selected.worker_calls} investigation calls ·{" "}
                        {selected.resolution_calls || 0} resolution calls ·{" "}
                        {selected.observed_latency_ms?.toFixed(3)}ms ·{" "}
                        {selected.memory_reuses} reuses
                      </dd>
                      <dt>Safety decision</dt>
                      <dd>
                        {selected.source_integrity_verified
                          ? "Project unchanged"
                          : "INTEGRITY FAILURE"}{" "}
                        ·{" "}
                        {selected.expected_abstention
                          ? selected.abstained
                            ? "required abstention occurred"
                            : "FAILED TO ABSTAIN"
                          : "answer required"}
                      </dd>
                    </>
                  )}
                {selected.node_type === "evaluation_result" &&
                  !selected.contract_type?.startsWith("PROJECT_") && (
                    <>
                      <dt>Strategy result</dt>
                      <dd>
                        <b>{selected.strategy}</b> · {selected.scenario} ·
                        repeat {selected.repetition}
                      </dd>
                      <dt>Answer quality</dt>
                      <dd>
                        {selected.correct ? "Correct" : "Incorrect"} · evidence{" "}
                        {selected.evidence_complete ? "complete" : "incomplete"}
                      </dd>
                      <dt>Measured cost</dt>
                      <dd>
                        {selected.worker_calls} worker calls ·{" "}
                        {selected.model_calls} model calls ·{" "}
                        {selected.retrieved_tokens} exact tokens ·{" "}
                        {selected.latency_ms}ms deterministic latency ·{" "}
                        {selected.observed_latency_ms?.toFixed(3)}ms observed
                        harness time
                      </dd>
                      <dt>Memory behavior</dt>
                      <dd>
                        {selected.memory_reuses} reuses ·{" "}
                        {selected.duplicate_investigations} duplicate
                        investigations
                      </dd>
                      {selected.conflict_resolved != null && (
                        <>
                          <dt>Conflict handling</dt>
                          <dd>
                            {selected.conflict_resolved
                              ? "Resolved without stale memory"
                              : "Conflicting/stale memory remained"}
                          </dd>
                        </>
                      )}
                      {selected.recovery_succeeded != null && (
                        <>
                          <dt>Recovery behavior</dt>
                          <dd>
                            {selected.recovery_succeeded
                              ? "Expired ownership safely reclaimed"
                              : "No durable recovery capability"}
                          </dd>
                        </>
                      )}
                    </>
                  )}
                {selected.node_type === "codex_readonly_proof" && (
                  <>
                    <dt>Bounded Codex verdict</dt>
                    <dd>
                      <b>
                        {selected.passed
                          ? "ALL READ-ONLY GATES PASSED"
                          : "SAFETY OR EVIDENCE FAILURE"}
                      </b>{" "}
                      · {selected.test_path}
                    </dd>
                    <dt>Initial → exact replay</dt>
                    <dd>
                      <b>
                        {selected.initial_codex_calls} →{" "}
                        {selected.replay_codex_calls} Codex calls
                      </b>{" "}
                      ·{" "}
                      {selected.exact_replay_zero_calls
                        ? "zero-call graph reuse verified"
                        : "replay called worker"}
                    </dd>
                    <dt>Explicit source allowlist</dt>
                    <dd>{selected.authorized_paths?.join(" · ")}</dd>
                    <dt>Fixed budgets</dt>
                    <dd>
                      {selected.max_codex_calls} call ·{" "}
                      {selected.max_wall_time_seconds}s ·{" "}
                      {selected.max_context_tokens} context tokens ·{" "}
                      {selected.max_result_tokens} result tokens · sandbox{" "}
                      {selected.sandbox}
                    </dd>
                    <dt>Validated structured answer</dt>
                    <dd>
                      {selected.conclusion} ·{" "}
                      {Math.round((selected.confidence || 0) * 100)}% confidence
                    </dd>
                    <dt>Evidence contract</dt>
                    <dd>
                      {selected.evidence_contract_met ? "Passed" : "FAILED"} ·
                      required {selected.required_evidence_terms?.join(" + ")} ·{" "}
                      {selected.evidence?.length || 0} file-line citations
                    </dd>
                    <dt>Measured execution</dt>
                    <dd>
                      {selected.input_tokens} input · {selected.output_tokens}{" "}
                      output tokens · {(selected.latency_ms || 0).toFixed(1)}ms
                      · ${(selected.estimated_cost_usd || 0).toFixed(6)}
                    </dd>
                    <dt>Cost basis</dt>
                    <dd>{selected.cost_basis}</dd>
                    <dt>Safety decision</dt>
                    <dd>
                      structured result{" "}
                      {selected.structured_result_validated ? "✓" : "✗"} · scope{" "}
                      {selected.access_scope_verified ? "✓" : "✗"} · Project bytes{" "}
                      {selected.source_integrity_verified ? "✓" : "✗"} · no
                      write attempt{" "}
                      {selected.no_project_write_attempt ? "✓" : "✗"} · no
                      repair capability{" "}
                      {selected.no_repair_capability ? "✓" : "✗"}
                    </dd>
                    <dt>Manifest comparison</dt>
                    <dd>
                      {selected.initial_manifest_sha256?.slice(0, 16)} →{" "}
                      {selected.final_manifest_sha256?.slice(0, 16)}
                    </dd>
                  </>
                )}
                {selected.node_type === "recursive_codex_proof" && (
                  <>
                    <dt>Recursive delegation verdict</dt>
                    <dd>
                      <b>
                        {selected.passed
                          ? selected.abstained
                            ? "SAFE ABSTENTION PASSED"
                            : "ALL DELEGATION GATES PASSED"
                          : "DELEGATION GATE FAILURE"}
                      </b>{" "}
                      · {selected.test_path}
                    </dd>
                    {selected.plan_generated && (
                      <>
                        <dt>Generated investigation plan</dt>
                        <dd>
                          <b>{selected.planning_algorithm}</b> ·{" "}
                          {selected.candidate_paths?.length || 0} candidates →{" "}
                          {selected.selected_paths?.length || 0} selected ·{" "}
                          {selected.excluded_paths?.length || 0} excluded
                        </dd>
                      </>
                    )}
                    <dt>Root task and final synthesis</dt>
                    <dd>
                      root {shortId(selected.root_task_id || "")} → synthesis{" "}
                      {shortId(selected.synthesis_task_id || "")} → claim{" "}
                      {shortId(selected.final_claim_id || "")}
                    </dd>
                    {selected.abstained && (
                      <>
                        <dt>Safe abstention</dt>
                        <dd>
                          <b>ZERO WORKERS CREATED</b> ·{" "}
                          {selected.abstention_reason}
                        </dd>
                      </>
                    )}
                    <dt>Delegated branches and budgets</dt>
                    {selected.branch_results?.map((branch) => (
                      <dd className="interpretation" key={branch.branch_id}>
                        <b>
                          {branch.name} · {branch.safety_decision}
                        </b>
                        {branch.authorized_paths.join(" · ")}
                        <small>
                          {branch.selection_reason} · graph distance{" "}
                          {branch.dependency_distance} · {branch.codex_calls}/
                          {branch.max_codex_calls} call ·{" "}
                          {(branch.latency_ms || 0).toFixed(1)}/
                          {branch.max_wall_time_seconds}s ·{" "}
                          {branch.input_tokens}/{branch.max_context_tokens}{" "}
                          context tokens · {branch.output_tokens}/
                          {branch.max_result_tokens} result tokens
                        </small>
                      </dd>
                    ))}
                    <dt>Evidence paths</dt>
                    {selected.branch_results?.map((branch) => (
                      <dd
                        className="interpretation"
                        key={`${branch.branch_id}-evidence`}
                      >
                        <b>
                          {branch.branch_contract_met
                            ? "CONTRACT PASSED"
                            : "CONTRACT FAILED"}{" "}
                          · {Math.round(branch.confidence * 100)}%
                        </b>
                        {branch.conclusion}
                        <small>
                          {branch.evidence
                            .map((item) => `${item.path}:${item.line}`)
                            .join(" · ")}
                        </small>
                      </dd>
                    ))}
                    <dt>Agreement and contradiction handling</dt>
                    <dd>
                      {selected.agreements?.length || 0} agreements ·{" "}
                      {selected.contradictions?.length || 0} contradictions ·{" "}
                      {selected.follow_up_created
                        ? `bounded follow-up: ${selected.follow_up_reason}`
                        : "no conflict or evidence gap; follow-up skipped"}
                    </dd>
                    {selected.agreements?.map((item) => (
                      <dd
                        className="interpretation"
                        key={`${item.assertion_key}-${item.value}`}
                      >
                        <b>AGREEMENT · {item.assertion_key}</b>
                        {item.value}
                        <small>{item.claim_ids.map(shortId).join(" · ")}</small>
                      </dd>
                    ))}
                    {selected.contradictions?.map((item) => (
                      <dd className="interpretation" key={item.assertion_key}>
                        <b>CONTRADICTION · {item.assertion_key}</b>
                        {Object.keys(item.values).join(" ↔ ")}
                        <small>
                          {selected.follow_up_reason || "unresolved"}
                        </small>
                      </dd>
                    ))}
                    <dt>Final evidence-backed answer</dt>
                    <dd>
                      <b>
                        {Math.round((selected.final_confidence || 0) * 100)}%
                        confidence
                      </b>{" "}
                      · {selected.final_answer}
                      <small>
                        {selected.final_evidence
                          ?.map((item) => `${item.path}:${item.line}`)
                          .join(" · ")}
                      </small>
                    </dd>
                    <dt>Initial versus exact replay</dt>
                    <dd>
                      <b>
                        {selected.initial_codex_calls} →{" "}
                        {selected.replay_codex_calls} Codex calls
                      </b>{" "}
                      · resolution {selected.follow_up_codex_calls || 0} →{" "}
                      {selected.replay_resolution_calls || 0} ·{" "}
                      {selected.exact_replay_zero_calls
                        ? "all current branch findings reused"
                        : "unexpected replay work"}
                    </dd>
                    <dt>Persisted graph contract</dt>
                    <dd>
                      hierarchy {selected.hierarchy_persisted ? "✓" : "✗"} ·
                      dependencies {selected.dependencies_persisted ? "✓" : "✗"}{" "}
                      · provenance {selected.provenance_persisted ? "✓" : "✗"} ·
                      safety decisions{" "}
                      {selected.safety_decisions_persisted ? "✓" : "✗"}
                    </dd>
                    <dt>Read-only safety decision</dt>
                    <dd>
                      scope {selected.access_scope_verified ? "✓" : "✗"} · Project
                      bytes {selected.source_integrity_verified ? "✓" : "✗"} ·
                      no writes {selected.no_project_write_attempt ? "✓" : "✗"}{" "}
                      · no repair capability{" "}
                      {selected.no_repair_capability ? "✓" : "✗"} · mutation
                      rejection{" "}
                      {selected.mutation_rejection_verified ? "✓" : "✗"}
                    </dd>
                    <dt>Manifest comparison</dt>
                    <dd>
                      {selected.initial_manifest_sha256?.slice(0, 16)} →{" "}
                      {selected.final_manifest_sha256?.slice(0, 16)}
                    </dd>
                  </>
                )}
                {selected.node_type === "generic_codex_evaluation" && (
                  <>
                    <dt>Generic delegation evaluation</dt>
                    <dd>
                      <b>
                        {selected.passed
                          ? "MULTI-SUBSYSTEM GATES PASSED"
                          : "EVALUATION FAILURE"}
                      </b>{" "}
                      · {selected.subsystem_count} distinct Project subsystems
                    </dd>
                    <dt>Generated-plan cases</dt>
                    {selected.cases?.map((item) => (
                      <dd className="interpretation" key={item.case_id}>
                        <b>
                          {item.subsystem} · {item.passed ? "PASSED" : "FAILED"}
                        </b>
                        {item.test_path}
                        <small>
                          {item.selected_paths.length} selected files ·{" "}
                          {item.initial_codex_calls} → {item.replay_codex_calls}{" "}
                          calls ·{" "}
                          {item.initial_input_tokens +
                            item.initial_output_tokens}{" "}
                          tokens · {(item.initial_latency_ms || 0).toFixed(1)}ms
                          ·{" "}
                          {item.evidence_contract_met
                            ? "evidence contract passed"
                            : item.abstained
                              ? "safe abstention"
                              : "contract failed"}
                        </small>
                      </dd>
                    ))}
                    <dt>Initial-versus-replay costs</dt>
                    <dd>
                      <b>
                        {selected.initial_codex_calls} →{" "}
                        {selected.replay_codex_calls} Codex calls
                      </b>{" "}
                      ·{" "}
                      {(selected.initial_input_tokens || 0) +
                        (selected.initial_output_tokens || 0)}{" "}
                      → 0 tokens ·{" "}
                      {(selected.initial_latency_ms || 0).toFixed(1)} → 0ms
                      worker latency · replay resolution{" "}
                      {selected.replay_resolution_calls} ·{" "}
                      {selected.exact_replays_zero_calls
                        ? "all exact replays used graph memory"
                        : "unexpected replay execution"}
                    </dd>
                    <dt>Abstention and safety</dt>
                    <dd>
                      safe abstention {selected.abstention_verified ? "✓" : "✗"}{" "}
                      · Project byte integrity{" "}
                      {selected.source_integrity_verified ? "✓" : "✗"} · no
                      repair capability{" "}
                      {selected.no_repair_capability ? "✓" : "✗"}
                    </dd>
                    <dt>Manifest comparison</dt>
                    <dd>
                      {selected.initial_manifest_sha256?.slice(0, 16)} →{" "}
                      {selected.final_manifest_sha256?.slice(0, 16)}
                    </dd>
                  </>
                )}
                {selected.node_type === "project_scan" &&
                  (selected.changes?.length || 0) > 0 && (
                    <>
                      <dt>File changes</dt>
                      {selected.changes?.map((change, index) =>
                        "kind" in change ? (
                          <dd
                            className="interpretation"
                            key={`${change.path}-${index}`}
                          >
                            <b>
                              {change.kind} · {change.path}
                            </b>
                            {change.previous_path
                              ? `renamed from ${change.previous_path}`
                              : ""}
                            <small>
                              {change.content_hash?.slice(0, 12) || "deleted"}
                            </small>
                          </dd>
                        ) : null,
                      )}
                    </>
                  )}
                {(selected.invalidated_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Claims invalidated by scan</dt>
                    <dd>
                      {selected.invalidated_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {selected.node_type === "project_file" && (
                  <>
                    <dt>Source file</dt>
                    <dd>
                      <b>{selected.title}</b> · {selected.language} ·{" "}
                      {selected.size_bytes} bytes ·{" "}
                      {selected.is_test
                        ? "test source"
                        : "implementation source"}
                    </dd>
                    <dt>Content hash</dt>
                    <dd>{selected.content_hash}</dd>
                  </>
                )}
                {selected.node_type === "project_symbol" && (
                  <>
                    <dt>Declared symbol</dt>
                    <dd>
                      <b>{selected.qualified_name}</b> ·{" "}
                      {selected.kind.toLowerCase()} · line {selected.line}
                    </dd>
                  </>
                )}
                {selected.node_type === "project_test" && (
                  <>
                    <dt>Indexed test</dt>
                    <dd>
                      <b>{selected.qualified_name}</b> · {selected.framework} ·
                      line {selected.line}
                    </dd>
                  </>
                )}
                {selected.node_type === "project_dependency" && (
                  <>
                    <dt>Imported dependency</dt>
                    <dd>
                      <b>{selected.import_name}</b> ·{" "}
                      {selected.target_file_id
                        ? `resolved to ${shortId(selected.target_file_id)}`
                        : "external dependency"}
                    </dd>
                  </>
                )}
                {selected.source_path && (
                  <>
                    <dt>Indexed artifact source</dt>
                    <dd>
                      <b>{selected.source_path}</b> · sha256{" "}
                      {selected.source_content_hash}
                    </dd>
                  </>
                )}
                {selected.max_model_calls != null && (
                  <>
                    <dt>Hard budgets</dt>
                    <dd>
                      <b>
                        {selected.model_calls_used}/{selected.max_model_calls}{" "}
                        calls
                      </b>{" "}
                      · {selected.retrieval_tokens_used}/
                      {selected.max_retrieval_tokens} retrieval tokens ·{" "}
                      {(selected.elapsed_seconds || 0).toFixed(2)}/
                      {selected.max_wall_time_seconds}s ·{" "}
                      {selected.duplicate_investigations}/
                      {selected.max_duplicate_investigations} duplicates
                    </dd>
                  </>
                )}
                {(selected.dependency_task_ids?.length || 0) > 0 && (
                  <>
                    <dt>Dependencies</dt>
                    <dd>
                      {selected.dependency_task_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {selected.memory_tier && (
                  <>
                    <dt>Memory tier</dt>
                    <dd>
                      {selected.memory_tier} ·{" "}
                      {selected.memory_lifecycle?.toLowerCase()}
                    </dd>
                  </>
                )}
                {selected.fixed && selected.active && (
                  <>
                    <dt>Exact token comparison</dt>
                    <dd>
                      <b>
                        {selected.fixed.input_tokens} →{" "}
                        {selected.active.input_tokens}
                      </b>{" "}
                      · {Math.round((selected.token_reduction || 0) * 100)}%
                      context reduction · o200k_base
                    </dd>
                    <dt>Output tokens</dt>
                    <dd>
                      {selected.fixed.output_tokens} fixed ·{" "}
                      {selected.active.output_tokens} active
                    </dd>
                    <dt>Quality gates</dt>
                    <dd>
                      {selected.correctness_preserved
                        ? "Correctness preserved"
                        : "Correctness degraded"}{" "}
                      ·{" "}
                      {selected.benchmark_evidence_preserved
                        ? "evidence preserved"
                        : "evidence missing"}
                    </dd>
                    <dt>Wall time</dt>
                    <dd>
                      {selected.fixed.wall_time_ms.toFixed(2)}ms fixed ·{" "}
                      {selected.active.wall_time_ms.toFixed(2)}ms active
                    </dd>
                    <dt>Duplicate retrieval</dt>
                    <dd>
                      {selected.fixed.duplicate_retrievals} fixed ·{" "}
                      {selected.active.duplicate_retrievals} active
                    </dd>
                  </>
                )}
                {selected.token && (
                  <>
                    <dt>Virtual memory token</dt>
                    <dd>
                      <b>{selected.token}</b>
                      {selected.version
                        ? `immutable version ${selected.version}`
                        : ""}
                    </dd>
                  </>
                )}
                {selected.access_frequency != null && (
                  <>
                    <dt>Pathway utility</dt>
                    <dd>
                      {selected.access_frequency} traversals ·{" "}
                      {Math.round(selected.average_tokens_saved || 0)} average
                      tokens saved
                    </dd>
                  </>
                )}
                {selected.stability != null && (
                  <>
                    <dt>Pathway trust</dt>
                    <dd>
                      {Math.round((selected.confidence || 0) * 100)}% confidence
                      · {Math.round(selected.stability * 100)}% stability
                    </dd>
                  </>
                )}
                {(selected.node_ids?.length || 0) > 0 && (
                  <>
                    <dt>Expandable pathway</dt>
                    <dd>{selected.node_ids?.map(shortId).join(" → ")}</dd>
                  </>
                )}
                {(selected.supporting_reconstruction_ids?.length || 0) > 0 && (
                  <>
                    <dt>Supporting traversals</dt>
                    <dd>
                      {selected.supporting_reconstruction_ids
                        ?.map(shortId)
                        .join(" · ")}
                    </dd>
                  </>
                )}
                {selected.observed_frequency != null && (
                  <>
                    <dt>Pathway promotion policy</dt>
                    <dd>
                      {selected.observed_frequency}/{selected.minimum_frequency}{" "}
                      uses ·{" "}
                      {Math.round(selected.observed_average_tokens_saved || 0)}/
                      {selected.minimum_tokens_saved} tokens ·{" "}
                      {Math.round((selected.observed_stability || 0) * 100)}%/
                      {Math.round((selected.minimum_stability || 0) * 100)}%
                      stability
                    </dd>
                  </>
                )}
                {selected.active_input_tokens != null && (
                  <>
                    <dt>Tokenized comparison</dt>
                    <dd>
                      <b>
                        {selected.active_input_tokens} →{" "}
                        {selected.token_input_tokens}
                      </b>{" "}
                      · {Math.round((selected.additional_reduction || 0) * 100)}
                      % additional reduction ·{" "}
                      {selected.correct ? "correct" : "incorrect"} ·{" "}
                      {selected.expansion_complete
                        ? "fully expandable"
                        : "expansion failed"}
                    </dd>
                  </>
                )}
                {(selected.traversal_node_ids?.length || 0) > 0 && (
                  <>
                    <dt>Traversal path</dt>
                    <dd>
                      {selected.traversal_node_ids?.map(shortId).join(" → ")}
                    </dd>
                  </>
                )}
                {selected.expected_answer && (
                  <>
                    <dt>Expected answer</dt>
                    <dd>{selected.expected_answer}</dd>
                  </>
                )}
                {selected.successful_reuse_count != null && (
                  <>
                    <dt>Successful reuse</dt>
                    <dd>
                      {selected.successful_reuse_count} task
                      {selected.successful_reuse_count === 1 ? "" : "s"}
                    </dd>
                  </>
                )}
                {selected.policy_version && selected.from_tier && (
                  <>
                    <dt>Promotion policy</dt>
                    <dd>
                      <b>{selected.policy_version}</b>
                      {selected.from_tier} → {selected.to_tier}
                    </dd>
                  </>
                )}
                {selected.observed_support != null && (
                  <>
                    <dt>Promotion threshold</dt>
                    <dd>
                      {selected.observed_support}/{selected.minimum_support}{" "}
                      independent episodes ·{" "}
                      {Math.round((selected.observed_confidence || 0) * 100)}%/
                      {Math.round((selected.minimum_confidence || 0) * 100)}%
                      confidence
                    </dd>
                  </>
                )}
                {(selected.candidate_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Evaluated candidates</dt>
                    <dd>
                      {selected.candidate_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.accepted_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Accepted evidence</dt>
                    <dd>
                      {selected.accepted_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.rejected_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Rejected candidates</dt>
                    <dd>
                      {selected.rejected_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.contradictory_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Contradictions</dt>
                    <dd>
                      {selected.contradictory_claim_ids
                        ?.map(shortId)
                        .join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.stale_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Stale candidates</dt>
                    <dd>
                      {selected.stale_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {selected.promoted_claim_id && (
                  <>
                    <dt>Promoted memory</dt>
                    <dd>{shortId(selected.promoted_claim_id)}</dd>
                  </>
                )}
                {selected.selected_claim && (
                  <>
                    <dt>Decision</dt>
                    <dd>{selected.selected_claim}</dd>
                  </>
                )}
                {selected.selected_value && (
                  <>
                    <dt>Selected interpretation</dt>
                    <dd>{selected.selected_value}</dd>
                  </>
                )}
                {selected.node_type === "conflict_verdict" && (
                  <>
                    <dt>Verdict outcome</dt>
                    <dd>
                      <b>{selected.status}</b> ·{" "}
                      {selected.selected_value || "No defensible selection"}
                    </dd>
                    <dt>Resolver safety bound</dt>
                    <dd>
                      {selected.max_resolution_attempts} maximum attempt
                      {selected.max_resolution_attempts === 1 ? "" : "s"} ·{" "}
                      {Math.round((selected.confidence_threshold || 0) * 100)}%
                      confidence required
                    </dd>
                  </>
                )}
                {(selected.supporting_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Supporting findings</dt>
                    <dd>
                      {selected.supporting_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.contradicting_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Contradicting findings</dt>
                    <dd>
                      {selected.contradicting_claim_ids
                        ?.map(shortId)
                        .join(" · ")}
                    </dd>
                  </>
                )}
                {selected.node_type === "conflict_verdict" &&
                selected.evidence_claim_ids?.length ? (
                  <>
                    <dt>Complete verdict provenance</dt>
                    <dd>
                      {selected.evidence_claim_ids.map(shortId).join(" · ")}
                    </dd>
                  </>
                ) : null}
                {selected.reused_verdict_id && (
                  <>
                    <dt>Reused conflict verdict</dt>
                    <dd>
                      {shortId(selected.reused_verdict_id)} · original workers
                      were not called again
                    </dd>
                  </>
                )}
                {(selected.interpretations?.length || 0) > 0 && (
                  <>
                    <dt>Competing interpretations</dt>
                    {selected.interpretations?.map((item) => (
                      <dd
                        className="interpretation"
                        key={item.normalized_value}
                      >
                        <b>{item.value}</b>
                        {item.claim_ids.length} supporting claim
                        {item.claim_ids.length === 1 ? "" : "s"}
                      </dd>
                    ))}
                  </>
                )}
                {(selected.corroborated_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Corroborated claims</dt>
                    <dd>
                      {selected.corroborated_claim_ids
                        ?.map(shortId)
                        .join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.outlier_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Outliers</dt>
                    <dd>
                      {selected.outlier_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {selected.producer && (
                  <>
                    <dt>Producer</dt>
                    <dd>{selected.producer}</dd>
                  </>
                )}
                {(selected.selected_node_ids?.length || 0) > 0 && (
                  <>
                    <dt>Reconstructed context</dt>
                    <dd>
                      {selected.selected_node_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.baseline_node_ids?.length || 0) > 0 && (
                  <>
                    <dt>Fixed-neighborhood baseline</dt>
                    <dd>
                      {selected.baseline_node_ids?.length} nodes ·{" "}
                      {selected.baseline_tokens} o200k tokens
                    </dd>
                  </>
                )}
                {selected.reconstructed_tokens != null && (
                  <>
                    <dt>Active context cost</dt>
                    <dd>
                      {selected.selected_node_ids?.length || 0} nodes ·{" "}
                      {selected.reconstructed_tokens} o200k tokens
                    </dd>
                  </>
                )}
                {(selected.pruned_node_ids?.length || 0) > 0 && (
                  <>
                    <dt>Pruned branches</dt>
                    <dd>
                      {selected.pruned_node_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {selected.evidence_preserved != null && (
                  <>
                    <dt>Required evidence</dt>
                    <dd>
                      {selected.evidence_preserved ? "Preserved" : "Missing"}
                    </dd>
                  </>
                )}
                {selected.action && (
                  <>
                    <dt>Reconstruction decision</dt>
                    <dd>
                      <b>{selected.action}</b>
                      {selected.reason}
                    </dd>
                  </>
                )}
                {selected.frontier_node_id && (
                  <>
                    <dt>Expanded from</dt>
                    <dd>
                      {shortId(selected.frontier_node_id)} via{" "}
                      {selected.relation}
                    </dd>
                  </>
                )}
                {selected.token_estimate != null && (
                  <>
                    <dt>Node cost</dt>
                    <dd>{selected.token_estimate} o200k tokens</dd>
                  </>
                )}
                {selected.validity_reason && (
                  <>
                    <dt>Why we believe this</dt>
                    <dd>{selected.validity_reason}</dd>
                  </>
                )}
                {selected.learned_at && (
                  <>
                    <dt>Learned</dt>
                    <dd>{new Date(selected.learned_at).toLocaleString()}</dd>
                  </>
                )}
                {selected.source_task_id && (
                  <>
                    <dt>Producing task</dt>
                    <dd>{shortId(selected.source_task_id)}</dd>
                  </>
                )}
                {selected.source_commit && (
                  <>
                    <dt>Source commit</dt>
                    <dd>{selected.source_commit.slice(0, 12)}</dd>
                  </>
                )}
                {selected.valid_from && (
                  <>
                    <dt>Valid from state</dt>
                    <dd>{selected.valid_from.slice(0, 12)}</dd>
                  </>
                )}
                {selected.valid_until && (
                  <>
                    <dt>Valid until state</dt>
                    <dd>{selected.valid_until.slice(0, 12)}</dd>
                  </>
                )}
                {selected.superseded_by_claim_id && (
                  <>
                    <dt>Superseded by</dt>
                    <dd>{shortId(selected.superseded_by_claim_id)}</dd>
                  </>
                )}
                {(selected.source_files?.length || 0) > 0 && (
                  <>
                    <dt>Grounding sources</dt>
                    {selected.source_files?.map((source) => (
                      <dd className="evidence-line" key={source.path}>
                        <b>
                          {source.path}
                          {source.evidence_lines.length
                            ? `:${source.evidence_lines.join(",")}`
                            : ""}
                        </b>
                        sha256 {source.content_hash.slice(0, 12)}…
                      </dd>
                    ))}
                  </>
                )}
                {(selected.source_claim_ids?.length || 0) > 0 && (
                  <>
                    <dt>Derived from</dt>
                    <dd>
                      {selected.source_claim_ids?.map(shortId).join(" · ")}
                    </dd>
                  </>
                )}
                {(selected.validity_history?.length || 0) > 0 && (
                  <>
                    <dt>Claim history</dt>
                    {selected.validity_history?.map((event, index) => (
                      <dd
                        className="interpretation"
                        key={`${event.observed_at}-${index}`}
                      >
                        <b>{event.status}</b>
                        {event.reason}
                        <small>
                          {new Date(event.observed_at).toLocaleString()} ·{" "}
                          {event.project_fingerprint.slice(0, 12)}
                        </small>
                      </dd>
                    ))}
                  </>
                )}
                {(selected.tier_history?.length || 0) > 0 && (
                  <>
                    <dt>Memory lifecycle</dt>
                    {selected.tier_history?.map((event, index) => (
                      <dd
                        className="interpretation"
                        key={`${event.transitioned_at}-${index}`}
                      >
                        <b>
                          {event.from_tier || "CAPTURED"} → {event.to_tier}
                        </b>
                        {event.reason}
                        <small>
                          {new Date(event.transitioned_at).toLocaleString()}
                        </small>
                      </dd>
                    ))}
                  </>
                )}
                {selected.attempt_count != null && (
                  <>
                    <dt>Task attempts</dt>
                    <dd>{selected.attempt_count}</dd>
                  </>
                )}
                {selected.stopping_reason && (
                  <>
                    <dt>Stopping reason</dt>
                    <dd>{selected.stopping_reason}</dd>
                  </>
                )}
                {(selected.files?.length || 0) > 0 && (
                  <>
                    <dt>Files examined</dt>
                    <dd>{selected.files?.join(" · ")}</dd>
                  </>
                )}
                {(selected.unresolved_questions?.length || 0) > 0 && (
                  <>
                    <dt>Unresolved</dt>
                    <dd>{selected.unresolved_questions?.join(" ")}</dd>
                  </>
                )}
                {(selected.evidence?.length || 0) > 0 && (
                  <>
                    <dt>Evidence</dt>
                    {selected.evidence?.map((item, index) => (
                      <dd
                        className="evidence-line"
                        key={`${item.path}-${index}`}
                      >
                        <b>
                          {item.path}
                          {item.line ? `:${item.line}` : ""}
                        </b>
                        {item.detail}
                      </dd>
                    ))}
                  </>
                )}
                {selected.last_error && (
                  <>
                    <dt>Last error</dt>
                    <dd className="error-text">{selected.last_error}</dd>
                  </>
                )}
                {selected.node_type === "recursive_codex_proof" &&
                  selected.semantic_reuse_enabled && (
                    <>
                      <dt>Semantic evidence match</dt>
                      <dd>
                        <b>
                          {Math.round(
                            (selected.semantic_match_score || 0) * 100,
                          )}
                          % match
                        </b>{" "}
                        · {selected.semantic_match_question}
                      </dd>
                      <dt>Reused current claims</dt>
                      <dd>
                        {selected.reused_claim_ids?.length || 0} accepted ·{" "}
                        {selected.reused_claim_ids?.map(shortId).join(" · ") ||
                          "none"}
                      </dd>
                      <dt>Rejected reuse and invalidation reasons</dt>
                      {selected.rejected_reuse_claims?.map((item) => (
                        <dd className="interpretation" key={item.claim_id}>
                          <b>REJECTED · {item.path}</b>
                          {item.reason}
                          <small>{shortId(item.claim_id)}</small>
                        </dd>
                      ))}
                      <dt>Uncovered evidence gaps</dt>
                      <dd>
                        {selected.uncovered_paths?.join(" · ") || "none"} ·{" "}
                        <b>
                          {selected.remaining_worker_calls || 0} remaining
                          worker calls
                        </b>
                      </dd>
                      <dt>Fresh versus semantic reuse cost</dt>
                      <dd>
                        <b>
                          {selected.fresh_baseline_codex_calls || 0} →{" "}
                          {selected.initial_codex_calls || 0} calls
                        </b>{" "}
                        · {selected.fresh_baseline_input_tokens || 0} →{" "}
                        {selected.initial_input_tokens || 0} input tokens ·{" "}
                        {(selected.fresh_baseline_latency_ms || 0).toFixed(1)} →{" "}
                        {(selected.initial_latency_ms || 0).toFixed(1)}ms
                      </dd>
                    </>
                  )}
                {selected.node_type === "generic_codex_evaluation" &&
                  selected.semantic_reuse_verified && (
                    <>
                      <dt>Semantic reuse evaluation</dt>
                      <dd>
                        <b>THREE-SUBSYSTEM REUSE GATES PASSED</b>
                      </dd>
                      <dt>Fresh versus reuse cost comparison</dt>
                      <dd>
                        <b>
                          {selected.fresh_codex_calls} →{" "}
                          {selected.reuse_codex_calls} calls
                        </b>{" "}
                        · {selected.fresh_input_tokens} →{" "}
                        {selected.reuse_input_tokens} input tokens ·{" "}
                        {(selected.fresh_latency_ms || 0).toFixed(1)} →{" "}
                        {(selected.reuse_latency_ms || 0).toFixed(1)}ms
                      </dd>
                      <dt>Unsafe reuse rejection gates</dt>
                      <dd>
                        changed/stale provenance{" "}
                        {selected.stale_reuse_blocked ? "✓" : "✗"} ·
                        contradiction{" "}
                        {selected.contradiction_reuse_blocked ? "✓" : "✗"} ·
                        weak relevance{" "}
                        {selected.weak_relevance_blocked ? "✓" : "✗"}
                      </dd>
                    </>
                  )}
                {selected.node_type === "investigation_session" && (
                  <>
                    <dt>Durable session state</dt>
                    <dd>
                      <b>
                        {selected.status} · {selected.active_stage}
                      </b>{" "}
                      · recovery count {selected.recovery_count || 0}
                    </dd>
                    <dt>Persisted plan and remaining tasks</dt>
                    <dd>
                      {selected.selected_paths?.length || 0} selected paths ·{" "}
                      {selected.remaining_tasks?.join(" · ") ||
                        "none remaining"}
                    </dd>
                    <dt>Checkpoint history</dt>
                    {selected.checkpoints?.map((item) => (
                      <dd className="interpretation" key={item.id}>
                        <b>
                          #{item.sequence} · {item.stage}
                        </b>
                        {item.completed_paths.length} completed branches ·{" "}
                        {item.codex_calls_spent} calls ·{" "}
                        {item.input_tokens_spent} input tokens
                        <small>
                          {item.safety_decisions.join(" · ") ||
                            "plan/synthesis checkpoint"}{" "}
                          · {(item.latency_ms_spent || 0).toFixed(1)}ms
                        </small>
                      </dd>
                    ))}
                    <dt>Recovered work and avoided cost</dt>
                    <dd>
                      <b>
                        {selected.avoided_codex_calls || 0} Codex calls avoided
                      </b>{" "}
                      · {selected.avoided_input_tokens || 0} input tokens ·{" "}
                      {(selected.avoided_latency_ms || 0).toFixed(1)}ms
                    </dd>
                    <dt>Invalidations and execution lease</dt>
                    <dd>
                      {selected.invalidation_reasons?.join(" · ") ||
                        "checkpoint provenance and fence current"}{" "}
                      · fence {selected.fencing_token} · expires{" "}
                      {selected.lease_expires_at
                        ? new Date(selected.lease_expires_at).toLocaleString()
                        : "unknown"}
                    </dd>
                    <dt>Recovery safety gates</dt>
                    <dd>
                      source integrity{" "}
                      {selected.source_integrity_verified ? "✓" : "✗"} · fixed
                      budgets {selected.budgets_preserved ? "✓" : "✗"} · exact
                      reuse {selected.exact_reuse_preserved ? "✓" : "✗"} ·
                      semantic reuse{" "}
                      {selected.semantic_reuse_preserved ? "✓" : "✗"}
                    </dd>
                  </>
                )}
                {selected.node_type === "resumable_session_evaluation" && (
                  <>
                    <dt>Resumable session evaluation</dt>
                    <dd>
                      <b>
                        {selected.passed
                          ? "ALL RECOVERY GATES PASSED"
                          : "RECOVERY FAILURE"}
                      </b>{" "}
                      · {selected.subsystem_count} Project subsystems
                    </dd>
                    <dt>Interrupted-stage coverage</dt>
                    <dd>
                      planning {selected.planning_recovery_verified ? "✓" : "✗"}{" "}
                      · delegation{" "}
                      {selected.delegation_recovery_verified ? "✓" : "✗"} ·
                      conflict resolution{" "}
                      {selected.conflict_recovery_verified ? "✓" : "✗"} ·
                      synthesis{" "}
                      {selected.synthesis_recovery_verified ? "✓" : "✗"}
                    </dd>
                    <dt>Rejected checkpoints</dt>
                    <dd>
                      stale provenance{" "}
                      {selected.stale_provenance_rejected ? "✓" : "✗"} · stale
                      execution lease{" "}
                      {selected.stale_lease_rejected ? "✓" : "✗"}
                    </dd>
                    <dt>Total recovered savings</dt>
                    <dd>
                      <b>{selected.avoided_codex_calls || 0} calls</b> ·{" "}
                      {selected.avoided_input_tokens || 0} input tokens ·{" "}
                      {(selected.avoided_latency_ms || 0).toFixed(1)}ms avoided
                    </dd>
                    <dt>Preserved contracts</dt>
                    <dd>
                      source integrity{" "}
                      {selected.source_integrity_verified ? "✓" : "✗"} · fixed
                      budgets {selected.budgets_preserved ? "✓" : "✗"} · exact
                      reuse {selected.exact_reuse_preserved ? "✓" : "✗"} ·
                      semantic reuse{" "}
                      {selected.semantic_reuse_preserved ? "✓" : "✗"}
                    </dd>
                  </>
                )}
                {selected.node_type === "unreal_index_scan" && (
                  <>
                    <dt>Unreal-aware project index</dt>
                    <dd>
                      <b>{selected.scope_name}</b> · {selected.artifact_count}{" "}
                      artifacts · {selected.dependency_count} relationships
                    </dd>
                    <dt>Incremental scan decision</dt>
                    <dd>
                      {selected.parsed_artifact_count} parsed ·{" "}
                      {selected.reused_artifact_count} unchanged artifacts
                      reused
                    </dd>
                    <dt>Artifact coverage</dt>
                    {Object.entries(selected.kind_counts || {}).map(
                      ([kind, count]) => (
                        <dd className="interpretation" key={kind}>
                          <b>{kind}</b>
                          {count} artifacts
                        </dd>
                      ),
                    )}
                    <dt>Strict read-only gates</dt>
                    <dd>
                      source integrity{" "}
                      {selected.source_integrity_verified ? "✓" : "✗"} · Unreal
                      not launched {selected.project_launched ? "✗" : "✓"} · not
                      compiled {selected.project_compiled ? "✗" : "✓"} ·
                      generated files {selected.generated_files || 0}
                    </dd>
                    <dt>Manifest comparison</dt>
                    <dd>
                      {selected.initial_manifest_sha256?.slice(0, 16)} →{" "}
                      {selected.final_manifest_sha256?.slice(0, 16)}
                    </dd>
                  </>
                )}
                {selected.node_type === "unreal_artifact" && (
                  <>
                    <dt>Unreal artifact</dt>
                    <dd>
                      <b>{selected.kind}</b> · {selected.title}
                    </dd>
                    <dt>Module, plugin, and package metadata</dt>
                    <dd>
                      module {selected.module_name || "—"} · plugin{" "}
                      {selected.plugin_name || "—"} · package{" "}
                      {selected.package_path || "—"}
                    </dd>
                    <dt>Class and Blueprint metadata</dt>
                    <dd>
                      {selected.class_names?.join(" · ") ||
                        selected.blueprint_generated_class ||
                        selected.asset_class ||
                        "no declared class metadata"}
                    </dd>
                    <dt>Binary safety</dt>
                    <dd>
                      {selected.binary_metadata_only
                        ? "metadata strings only; asset was not loaded or edited"
                        : "read-only text parse"}
                    </dd>
                    <dt>Content hash</dt>
                    <dd>{selected.content_hash}</dd>
                  </>
                )}
                {selected.node_type === "unreal_dependency" && (
                  <>
                    <dt>Unreal graph relationship</dt>
                    <dd>
                      <b>{selected.kind}</b> · {selected.source_path}
                    </dd>
                    <dt>Target reference</dt>
                    <dd>{selected.target_reference}</dd>
                    <dt>Resolution decision</dt>
                    <dd>
                      {selected.target_artifact_id
                        ? `resolved to ${shortId(selected.target_artifact_id)}`
                        : "external engine/plugin reference retained"}
                    </dd>
                  </>
                )}






                {selected.node_type === "project_workspace_result" && (
                  <>
                    <dt>Workspace request</dt>
                    <dd>
                      <b>{selected.project_name}</b> ·{" "}
                      {selected.kind === "CHANGE_PLAN"
                        ? "change plan"
                        : "diagnostic"}
                      <br />
                      {selected.prompt}
                    </dd>
                    <dt>Answer or impact summary</dt>
                    <dd>{selected.answer}</dd>
                    <dt>Affected project graph</dt>
                    {Object.entries(selected.impact_groups || {}).map(
                      ([group, paths]) => (
                        <dd className="interpretation" key={group}>
                          <b>
                            {group} · {paths.length}
                          </b>
                          {paths.join(" · ")}
                        </dd>
                      ),
                    )}
                    <dt>Evidence</dt>
                    {selected.evidence?.map((item, index) => (
                      <dd
                        className="interpretation"
                        key={`${item.path}-${index}`}
                      >
                        <b>
                          {item.path}
                          {item.line ? `:${item.line}` : ""}
                        </b>
                        {item.detail}
                      </dd>
                    ))}
                    <dt>Dependency paths</dt>
                    <dd>
                      {selected.dependency_paths?.join(" → ") ||
                        "No resolved graph path"}
                    </dd>
                    {(selected.workspace_steps?.length || 0) > 0 && (
                      <>
                        <dt>Proposed plan</dt>
                        {selected.workspace_steps?.map((step, index) => (
                          <dd className="interpretation" key={index}>
                            {step}
                          </dd>
                        ))}
                      </>
                    )}
                    {(selected.workspace_risks?.length || 0) > 0 && (
                      <>
                        <dt>Risks</dt>
                        {selected.workspace_risks?.map((risk, index) => (
                          <dd className="interpretation" key={index}>
                            {risk}
                          </dd>
                        ))}
                      </>
                    )}
                    {(selected.workspace_validations?.length || 0) > 0 && (
                      <>
                        <dt>Validation requirements</dt>
                        {selected.workspace_validations?.map(
                          (requirement, index) => (
                            <dd className="interpretation" key={index}>
                              {requirement}
                            </dd>
                          ),
                        )}
                      </>
                    )}
                    <dt>Human and execution boundary</dt>
                    <dd>
                      approval {selected.approval_status || "not required"} ·
                      execution{" "}
                      {selected.execution_authorized ? "ENABLED" : "BLOCKED"}
                    </dd>
                    <dt>Source safety</dt>
                    <dd>
                      read only {selected.read_only_verified ? "✓" : "✗"} ·
                      integrity {selected.source_integrity_verified ? "✓" : "✗"}{" "}
                      · manifest{" "}
                      {selected.indexed_manifest_sha256?.slice(0, 16)} →{" "}
                      {selected.final_manifest_sha256?.slice(0, 16)}
                    </dd>
                  </>
                )}
                {selected.node_type === "implementation_sandbox" && (
                  <>
                    <dt>Disposable implementation sandbox</dt>
                    <dd>
                      <b>{selected.status}</b> ·{" "}
                      {selected.authorized_paths?.length || 0} authorized files
                      · filesystem disposed{" "}
                      {selected.filesystem_disposed ? "✓" : "✗"}
                    </dd>
                    <dt>Registered source boundary</dt>
                    <dd>
                      source unchanged during sandbox{" "}
                      {selected.original_unchanged ? "✓" : "✗"} · planning
                      execution authorization{" "}
                      {selected.execution_authorized ? "DANGER" : "NONE"}
                      <br />
                      {selected.initial_manifest_sha256?.slice(0, 16)} →{" "}
                      {selected.final_manifest_sha256?.slice(0, 16)}
                    </dd>
                    <dt>Reviewable diffs</dt>
                    {selected.changes?.map((change) => (
                      <dd className="diff-review" key={change.path}>
                        <b>{change.path}</b>
                        <pre>{change.unified_diff}</pre>
                      </dd>
                    ))}
                    <dt>Artifact-aware validation routes</dt>
                    {selected.validation_decisions?.map((decision) => (
                      <dd className="interpretation" key={decision.id}>
                        <b>
                          {decision.status} · {decision.category} ·{" "}
                          {decision.path}
                        </b>
                        {decision.artifact_kind} · {decision.requirement}
                        <small>
                          {decision.satisfied_by
                            ? `Attested by ${decision.satisfied_by}`
                            : `Unreal Editor ${decision.requires_unreal_editor ? "required" : "not required"}`}
                        </small>
                      </dd>
                    ))}
                    <dt>Bounded sandbox validations</dt>
                    {selected.validations?.length ? (
                      selected.validations.map((validation, index) => (
                        <dd className="interpretation" key={index}>
                          <b>
                            {validation.exit_code === 0 ? "PASSED" : "FAILED"} ·{" "}
                            {validation.command.join(" ")}
                          </b>
                          {validation.duration_ms.toFixed(0)}ms
                          <pre>{validation.stdout || validation.stderr}</pre>
                        </dd>
                      ))
                    ) : (
                      <dd>
                        No bounded automated validation was routed; explicit
                        manual requirements are shown above.
                      </dd>
                    )}
                    <dt>Validation evidence</dt>
                    {selected.validation_evidence?.map((item, index) => (
                      <dd
                        className="interpretation"
                        key={`${item.path}-${index}`}
                      >
                        <b>{item.path}</b>
                        {item.detail}
                      </dd>
                    ))}
                    <dt>Separate promotion approval</dt>
                    <dd>
                      {selected.promotion_approval ? (
                        <>
                          <b>
                            {selected.promotion_approval.decision} ·{" "}
                            {selected.promotion_approval.approved_by}
                          </b>
                          <br />
                          {selected.promotion_approval.reason}
                        </>
                      ) : (
                        "Not approved; project writes remain unavailable."
                      )}
                    </dd>
                    {selected.promotion && (
                      <>
                        <dt>Promotion transaction</dt>
                        <dd>
                          <b>{selected.promotion.status}</b> · lease{" "}
                          {selected.promotion.lease_id} · fence{" "}
                          {selected.promotion.fencing_token}
                          <br />
                          manifest{" "}
                          {selected.promotion.initial_manifest_sha256.slice(
                            0,
                            16,
                          )}{" "}
                          →{" "}
                          {selected.promotion.final_manifest_sha256?.slice(
                            0,
                            16,
                          ) || "pending"}
                        </dd>
                        <dt>Post-application validation</dt>
                        {selected.promotion.validations.map((item, index) => (
                          <dd className="interpretation" key={index}>
                            <b>
                              {item.exit_code === 0 ? "PASSED" : "FAILED"} ·{" "}
                              {item.command.join(" ")}
                            </b>
                            {item.duration_ms.toFixed(0)}ms
                          </dd>
                        ))}
                        <dt>Rollback proof</dt>
                        <dd>
                          {selected.promotion.rollback_verified == null
                            ? "Not required."
                            : selected.promotion.rollback_verified
                              ? "Exact original bytes restored ✓"
                              : "ROLLBACK NOT VERIFIED"}
                        </dd>
                        <dt>Promotion checkpoints</dt>
                        {selected.promotion.checkpoints.map((item) => (
                          <dd className="interpretation" key={item.sequence}>
                            <b>
                              {item.sequence}. {item.stage}
                            </b>
                            {item.detail}
                          </dd>
                        ))}
                      </>
                    )}
                    <dt>Lifecycle checkpoints</dt>
                    {selected.checkpoints?.map((checkpoint) => (
                      <dd className="interpretation" key={checkpoint.sequence}>
                        <b>
                          {checkpoint.sequence}. {checkpoint.stage}
                        </b>
                        {checkpoint.detail}
                      </dd>
                    ))}
                    {(selected.failure_reason ||
                      selected.promotion?.failure_reason) && (
                      <>
                        <dt>Failure</dt>
                        <dd>
                          {selected.failure_reason ||
                            selected.promotion?.failure_reason}
                        </dd>
                      </>
                    )}
                  </>
                )}
                {selected.node_type === "implementation_sandbox" && (
                  <>
                    <dt>Pluggable bounded worker executions</dt>
                    {selected.validation_worker_executions?.length ? (
                      selected.validation_worker_executions.map((item) => (
                        <dd className="interpretation" key={item.id}>
                          <b>
                            {item.status} · {item.worker_name} · {item.path}
                          </b>
                          exit {item.exit_code ?? "none"} ·{" "}
                          {item.duration_ms.toFixed(1)}ms ·{" "}
                          {item.observed_processes}/{item.limits.max_processes}{" "}
                          processes · {item.peak_memory_bytes}/
                          {item.limits.max_memory_bytes} bytes memory ·{" "}
                          {item.output_bytes}/{item.limits.max_output_bytes}{" "}
                          output bytes · ${item.cost_usd.toFixed(4)}
                          <small>
                            {item.authorization_status} ·{" "}
                            {item.failure_reason || item.command.join(" ")}
                          </small>
                        </dd>
                      ))
                    ) : (
                      <dd>
                        No separately invoked validation workers recorded.
                      </dd>
                    )}
                    <dt>Imported external validation reports</dt>
                    {selected.external_validation_reports?.length ? (
                      selected.external_validation_reports.map((item) => (
                        <dd className="interpretation" key={item.id}>
                          <b>
                            {item.status} · {item.report_kind} ·{" "}
                            {item.artifact_path}
                          </b>
                          {item.detail}
                          <small>
                            {item.recorded_by} · SHA-256{" "}
                            {item.report_sha256.slice(0, 16)}
                          </small>
                        </dd>
                      ))
                    ) : (
                      <dd>
                        No external reports imported; RLMGraph has no implicit
                        Editor-launch authority.
                      </dd>
                    )}
                  </>
                )}
                {selected.node_type === "implementation_sandbox" &&
                  selected.promotion?.reconciliation && (
                    <>
                      <dt>Post-change graph reconciliation</dt>
                      <dd>
                        <b>{selected.promotion.reconciliation.status}</b> ·{" "}
                        {selected.promotion.reconciliation.parsed_paths.length}{" "}
                        incrementally parsed ·{" "}
                        {
                          selected.promotion.reconciliation.reused_file_ids
                            .length
                        }{" "}
                        files reused
                      </dd>
                      <dt>Changed and affected dependency paths</dt>
                      <dd>
                        {selected.promotion.reconciliation.changed_paths.join(
                          " · ",
                        )}
                        <br />
                        dependents:{" "}
                        {selected.promotion.reconciliation.dependent_paths.join(
                          " · ",
                        ) || "none"}
                      </dd>
                      <dt>Invalidated graph knowledge</dt>
                      <dd>
                        {
                          selected.promotion.reconciliation
                            .invalidated_claim_ids.length
                        }{" "}
                        claims ·{" "}
                        {
                          selected.promotion.reconciliation
                            .invalidated_workspace_record_ids.length
                        }{" "}
                        plans/diagnostics ·{" "}
                        {
                          selected.promotion.reconciliation
                            .superseded_validation_decision_ids.length
                        }{" "}
                        validation decisions
                      </dd>
                      <dt>Replacement provenance</dt>
                      <dd>
                        {selected.promotion.reconciliation.replacement_claim_ids.join(
                          " · ",
                        )}
                      </dd>
                      <dt>Reconciliation manifest</dt>
                      <dd>
                        {selected.promotion.reconciliation.previous_manifest_sha256.slice(
                          0,
                          16,
                        )}{" "}
                        →{" "}
                        {selected.promotion.reconciliation.new_manifest_sha256.slice(
                          0,
                          16,
                        )}{" "}
                        · source unchanged{" "}
                        {selected.promotion.reconciliation
                          .source_unchanged_during_reconciliation
                          ? "✓"
                          : "✗"}
                      </dd>
                      <dt>Reconciliation checkpoints</dt>
                      {selected.promotion.reconciliation.checkpoints.map(
                        (item) => (
                          <dd className="interpretation" key={item.sequence}>
                            <b>
                              {item.sequence}. {item.stage}
                            </b>
                            {item.detail}
                          </dd>
                        ),
                      )}
                    </>
                  )}
              </dl>
              <div className="node-id">{selected.id}</div>
            </>
          ) : (
            <div className="empty-state">
              <b>Select a node</b>
              <span>Readable details appear here.</span>
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}
