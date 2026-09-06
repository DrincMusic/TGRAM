from pathlib import Path

from rlmgraph.dashboard import DEMO_ROOT_ID, DemoController, build_dashboard_snapshot
from rlmgraph.models import (
    Claim,
    ClaimValidity,
    ConflictVerdict,
    Evidence,
    GraphEdge,
    GraphRelation,
    MemoryTier,
    PromotionDecision,
    PromotionOutcome,
    ReconstructionAction,
    ReconstructionSession,
    ReconstructionStep,
    ResolutionAttempt,
    ResolutionChoice,
    ResolutionResult,
    SourceFile,
    Task,
    TaskKind,
    TaskStatus,
    VerdictStatus,
)


class MemoryStore:
    def __init__(self) -> None:
        self.root = Task(
            id=DEMO_ROOT_ID,
            question="Root",
            fingerprint="root",
            project_root="demo",
            status=TaskStatus.DONE,
        )
        self.resolution = Task(
            id="LIVE-DEMO-RESOLUTION",
            question="Resolve",
            fingerprint="resolution",
            project_root="demo",
            kind=TaskKind.RESOLUTION,
            parent_task_id=self.root.id,
            status=TaskStatus.DONE,
            depth=1,
            attempt_count=2,
        )
        self.follow_up = Task(
            id="TASK-follow-up",
            question="Find evidence",
            fingerprint="follow-up",
            project_root="demo",
            kind=TaskKind.FOLLOW_UP,
            parent_task_id=self.resolution.id,
            status=TaskStatus.DONE,
            depth=2,
            attempt_count=1,
            output_claim_id="CLAIM-evidence",
        )
        self.unrelated = Task(
            id="TASK-unrelated",
            question="Unrelated",
            fingerprint="other",
            project_root="other",
        )
        self.claim = Claim(
            id="CLAIM-evidence",
            fingerprint="claim",
            subject="Evidence",
            producer="CodexCliInvestigator",
            conclusion="The contract says percentage.",
            confidence=0.9,
            evidence=[Evidence(path="CONTRACT.md", detail="Defines percentage", line=3)],
            files_examined=["CONTRACT.md"],
            source_files=[
                SourceFile(
                    path="CONTRACT.md", content_hash="a" * 64, evidence_lines=[3]
                )
            ],
            source_task_id=self.follow_up.id,
            valid_from="state-new",
            memory_tier=MemoryTier.EPISODIC,
        )
        self.old_claim = Claim(
            id="CLAIM-historical",
            fingerprint="old-claim",
            subject="Old evidence",
            producer="CodexCliInvestigator",
            conclusion="The old contract said fixed amount.",
            confidence=0.8,
            validity_status=ClaimValidity.SUPERSEDED,
            validity_reason="Superseded by CLAIM-evidence.",
            valid_from="state-old",
            valid_until="state-new",
            superseded_by_claim_id=self.claim.id,
            memory_tier=MemoryTier.EPISODIC,
        )
        self.attempts = [
            ResolutionAttempt(
                id="ATTEMPT-one",
                task_id=self.resolution.id,
                result=ResolutionResult(
                    selected_claim=ResolutionChoice.NEITHER,
                    resolved_assertion=None,
                    rationale="Evidence is missing.",
                    confidence=0.8,
                    unresolved_questions=["What does the contract say?"],
                ),
            )
        ]
        self.reconstruction = ReconstructionSession(
            id="RECON-one",
            task_id=self.root.id,
            query=self.root.question,
            seed_node_ids=[self.claim.id],
            selected_node_ids=[self.claim.id],
            pruned_node_ids=[self.old_claim.id],
            baseline_node_ids=[self.claim.id, self.old_claim.id],
            reconstructed_token_estimate=100,
            baseline_token_estimate=240,
            required_evidence_ids=[self.claim.id],
            evidence_preserved=True,
            steps=[
                ReconstructionStep(
                    id="STEP-one",
                    sequence=0,
                    action=ReconstructionAction.SEED,
                    node_id=self.claim.id,
                    score=1.0,
                    reason="Best evidence seed.",
                    token_estimate=100,
                )
            ],
        )
        self.promotion = PromotionDecision(
            id="PROMOTION-one",
            task_id=self.follow_up.id,
            project_root="demo",
            assertion_key="contract.payment",
            from_tier=MemoryTier.EPISODIC,
            to_tier=MemoryTier.SEMANTIC,
            outcome=PromotionOutcome.REJECTED,
            candidate_claim_ids=[self.claim.id],
            rejected_claim_ids=[self.claim.id],
            minimum_support=2,
            minimum_confidence=0.8,
            observed_support=1,
            observed_confidence=0.9,
            reason="Only one independent episode supports this assertion.",
        )

    def tasks(self):
        return [self.root, self.unrelated, self.follow_up, self.resolution]

    def claims(self):
        return [self.claim, self.old_claim]

    def edges(self):
        return [
            GraphEdge(source=self.root.id, relation=GraphRelation.SPAWNED, target=self.resolution.id),
            GraphEdge(
                source=self.resolution.id,
                relation=GraphRelation.SPAWNED,
                target=self.follow_up.id,
            ),
            GraphEdge(
                source=self.follow_up.id,
                relation=GraphRelation.DISCOVERED,
                target=self.claim.id,
            ),
            GraphEdge(
                source=self.resolution.id,
                relation=GraphRelation.ATTEMPTED,
                target=self.attempts[0].id,
            ),
            GraphEdge(
                source=self.claim.id,
                relation=GraphRelation.SUPERSEDES,
                target=self.old_claim.id,
            ),
            GraphEdge(
                source=self.root.id,
                relation=GraphRelation.HAS_RECONSTRUCTION,
                target=self.reconstruction.id,
            ),
            GraphEdge(
                source=self.reconstruction.id,
                relation=GraphRelation.HAS_STEP,
                target=self.reconstruction.steps[0].id,
            ),
            GraphEdge(
                source=self.reconstruction.steps[0].id,
                relation=GraphRelation.SEEDED,
                target=self.claim.id,
            ),
        ]

    def resolution_attempts(self, task_id):
        return self.attempts if task_id == self.resolution.id else []

    def conflict_clusters(self):
        return []

    def conflict_verdicts(self, task_id=None):
        return []

    def reconstructions(self):
        return [self.reconstruction]

    def promotion_decisions(self):
        return [self.promotion]

    def benchmark_runs(self):
        return []

    def pathways(self):
        return []

    def pathway_decisions(self):
        return []

    def pathway_benchmarks(self):
        return []

    def plan_decisions(self, root_task_id=None):
        return []

    def planning_runs(self, root_task_id=None):
        return []

    def execution_attempts(self, task_id=None):
        return []

    def route_predictions(self, task_id=None):
        return []

    def routing_policy_updates(self):
        return []

    def route_evaluations(self):
        return []

    def projects(self):
        return []

    def project_scans(self, project_id=None):
        return []

    def project_files(self, project_id=None, *, include_deleted=False):
        return []

    def project_symbols(self, project_id=None):
        return []

    def project_tests(self, project_id=None):
        return []

    def project_dependencies(self, project_id=None):
        return []


def test_snapshot_queries_only_demo_lineage_and_related_graph_records() -> None:
    snapshot = build_dashboard_snapshot(MemoryStore())

    node_ids = {node["id"] for node in snapshot["nodes"]}
    assert "TASK-unrelated" not in node_ids
    assert node_ids == {
        DEMO_ROOT_ID,
        "LIVE-DEMO-RESOLUTION",
        "TASK-follow-up",
        "CLAIM-evidence",
        "CLAIM-historical",
        "ATTEMPT-one",
        "RECON-one",
        "STEP-one",
        "PROMOTION-one",
    }
    assert len(snapshot["edges"]) == 8


def test_snapshot_exposes_conflict_verdict_provenance_and_reuse() -> None:
    store = MemoryStore()
    verdict = ConflictVerdict(
        id="VERDICT-one",
        resolution_task_id=store.resolution.id,
        assertion_key="contract.payment",
        status=VerdictStatus.RESOLVED,
        selected_value="percentage",
        confidence=0.95,
        rationale="The contract supports percentage semantics.",
        claim_ids=[store.claim.id, store.old_claim.id],
        supporting_claim_ids=[store.claim.id],
        contradicting_claim_ids=[store.old_claim.id],
        evidence_claim_ids=[store.claim.id, store.old_claim.id],
        resolver_attempt_id=store.attempts[0].id,
        confidence_threshold=0.75,
        max_resolution_attempts=2,
    )
    store.resolution.conflict_verdict_id = verdict.id
    store.follow_up.reused_verdict_id = verdict.id
    store.conflict_verdicts = lambda task_id=None: [verdict]  # type: ignore[method-assign]
    original_edges = store.edges
    store.edges = lambda: [  # type: ignore[method-assign]
        *original_edges(),
        GraphEdge(
            source=store.resolution.id,
            relation=GraphRelation.HAS_VERDICT,
            target=verdict.id,
        ),
        GraphEdge(
            source=store.claim.id,
            relation=GraphRelation.SUPPORTS_VERDICT,
            target=verdict.id,
        ),
        GraphEdge(
            source=store.old_claim.id,
            relation=GraphRelation.CONTRADICTS_VERDICT,
            target=verdict.id,
        ),
        GraphEdge(
            source=store.follow_up.id,
            relation=GraphRelation.REUSED_VERDICT,
            target=verdict.id,
        ),
    ]

    snapshot = build_dashboard_snapshot(store)

    node = next(item for item in snapshot["nodes"] if item["id"] == verdict.id)
    assert node["node_type"] == "conflict_verdict"
    assert node["status"] == "RESOLVED"
    assert node["supporting_claim_ids"] == [store.claim.id]
    assert node["contradicting_claim_ids"] == [store.old_claim.id]
    assert node["max_resolution_attempts"] == 2
    assert snapshot["metrics"]["conflict_verdicts"] == 1
    assert snapshot["metrics"]["resolved_verdicts"] == 1
    assert snapshot["metrics"]["verdict_reuses"] == 1


def test_snapshot_exposes_readable_properties_and_derived_metrics() -> None:
    snapshot = build_dashboard_snapshot(MemoryStore(), running=True)

    evidence = next(node for node in snapshot["nodes"] if node["id"] == "CLAIM-evidence")
    attempt = next(node for node in snapshot["nodes"] if node["id"] == "ATTEMPT-one")
    assert snapshot["running"] is True
    assert snapshot["root_status"] == "DONE"
    assert snapshot["metrics"] == {
        "tasks": 3,
        "codex_calls": 2,
        "resolution_attempts": 1,
        "evidence_claims": 1,
        "average_evidence_confidence": 0.9,
        "active_tasks": 0,
        "stopped_tasks": 0,
        "conflict_clusters": 0,
        "conflict_verdicts": 0,
        "resolved_verdicts": 0,
        "unresolved_verdicts": 0,
        "verdict_reuses": 0,
        "onboarded_projects": 0,
        "project_scans": 0,
        "project_files": 0,
        "project_symbols": 0,
        "project_tests": 0,
        "project_dependencies": 0,
        "scan_parsed_files": 0,
        "scan_reused_files": 0,
        "scan_model_calls": 0,
        "scan_invalidated_claims": 0,
        "read_only_projects": 0,
        "repair_proposals": 0,
        "repair_validations": 0,
        "verified_repairs": 0,
        "rejected_repairs": 0,
        "repair_model_calls": 0,
        "repair_approvals": 0,
        "approved_repairs": 0,
        "repair_promotions": 0,
        "promoted_repairs": 0,
        "rolled_back_repairs": 0,
        "post_repair_reconciliations": 0,
        "reconciled_affected_files": 0,
        "reconciled_invalidated_claims": 0,
        "reconciled_follow_up_worker_calls": 0,
        "maintenance_workflows": 0,
        "waiting_maintenance_workflows": 0,
        "completed_maintenance_workflows": 0,
        "rolled_back_maintenance_workflows": 0,
        "project_leases": 0,
        "active_project_leases": 0,
        "lease_contentions": 0,
        "lease_reclaims": 0,
        "lease_recoveries": 0,
        "scheduled_work": 0,
        "queued_scheduled_work": 0,
        "active_scheduled_work": 0,
        "cancelled_scheduled_work": 0,
        "evaluation_runs": 0,
        "passed_evaluation_runs": 0,
        "evaluation_results": 0,
        "evaluation_worker_calls": 0,
        "evaluation_model_calls": 0,
        "evaluation_retrieved_tokens": 0,
        "evaluation_latency_ms": 0,
        "evaluation_observed_latency_ms": 0,
        "evaluation_duplicate_investigations": 0,
        "evaluation_memory_reuses": 0,
        "codex_readonly_proofs": 0,
        "passed_codex_readonly_proofs": 0,
        "bounded_codex_calls": 0,
        "recursive_codex_proofs": 0,
        "passed_recursive_codex_proofs": 0,
        "delegated_codex_branches": 0,
        "delegation_initial_calls": 0,
        "delegation_replay_calls": 0,
        "generic_codex_evaluations": 0,
        "passed_generic_codex_evaluations": 0,
        "generic_codex_subsystems": 0,
        "generic_codex_abstentions": 0,
        "investigation_sessions": 0,
        "recovered_investigation_sessions": 0,
        "session_checkpoints": 0,
        "session_avoided_codex_calls": 0,
        "resumable_session_evaluations": 0,
        "passed_resumable_session_evaluations": 0,
        "unreal_index_scans": 0,
        "unreal_artifacts": 0,
        "unreal_dependencies": 0,
            "project_workspace_results": 0,
            "project_tickets": 0,
            "active_project_tickets": 0,
            "satisfied_project_tickets": 0,
            "blocked_project_tickets": 0,
            "pending_ticket_criteria": 0,
                "ticket_validations": 0,
                "implementation_sandboxes": 0,
                    "reviewable_sandbox_patches": 0,
                    "discarded_sandboxes": 0,
                    "sandbox_mutation_journals": 0,
                    "sandbox_promotions_requiring_recovery": 0,
                    "sandbox_promotion_recoveries": 0,
                    "sandbox_validation_worker_executions": 0,
                    "passed_sandbox_validation_workers": 0,
                    "external_sandbox_validation_reports": 0,
        "outlier_claims": 0,
        "current_claims": 1,
        "invalidated_claims": 0,
        "superseded_claims": 1,
        "reconstructions": 1,
        "reconstructed_nodes": 1,
        "baseline_nodes": 2,
        "reconstructed_tokens": 100,
        "baseline_tokens": 240,
        "pruned_nodes": 1,
        "evidence_preserved": True,
        "working_memories": 0,
        "episodic_memories": 2,
        "semantic_memories": 0,
        "procedural_memories": 0,
        "promotion_decisions": 1,
        "accepted_promotions": 0,
        "rejected_promotions": 1,
        "benchmark_runs": 0,
        "benchmark_passes": 0,
        "fixed_benchmark_tokens": 0,
        "active_benchmark_tokens": 0,
        "benchmark_token_reduction": None,
        "benchmark_correctness_preserved": True,
        "benchmark_evidence_preserved": True,
        "benchmark_duplicate_retrievals": 0,
        "virtual_pathways": 0,
        "active_virtual_pathways": 0,
        "invalidated_virtual_pathways": 0,
        "pathway_decisions": 0,
        "accepted_pathway_promotions": 0,
        "pathway_benchmarks": 0,
            "average_pathway_token_reduction": None,
            "plan_decisions": 0,
            "replanning_decisions": 0,
            "planning_model_calls": 0,
            "planning_retrieval_tokens": 0,
            "duplicate_investigations": 0,
            "execution_attempts": 0,
            "execution_fallbacks": 0,
            "execution_tokens": 0,
            "execution_cost_usd": 0,
            "execution_latency_ms": 0,
            "route_predictions": 0,
            "learned_route_changes": 0,
            "routing_policy_version": 0,
            "route_evaluations": 0,
            "route_prediction_success_rate": None,
                "mean_route_cost_error_usd": None,
                "mean_route_latency_error_ms": None,
                "total_token_usage": 0,
                "potential_total_token_usage": 0,
                "measured_avoided_tokens": 0,
                "token_comparison_count": 0,
                "unmetered_model_calls": 0,
                "legacy_unmetered_model_calls": 0,
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
                "token_diagnostics": [],
            }
    assert evidence["evidence"][0] == {
        "path": "CONTRACT.md",
        "detail": "Defines percentage",
        "line": 3,
    }
    assert evidence["producer"] == "CodexCliInvestigator"
    assert evidence["status"] == "CURRENT"
    assert "validity_reason" in evidence
    assert "validity_history" in evidence
    assert evidence["source_files"][0]["evidence_lines"] == [3]
    assert evidence["memory_tier"] == "EPISODIC"
    promotion = next(node for node in snapshot["nodes"] if node["id"] == "PROMOTION-one")
    assert promotion["status"] == "REJECTED"
    assert promotion["policy_version"] == "governed-memory-v1"
    assert promotion["rejected_claim_ids"] == ["CLAIM-evidence"]
    historical = next(
        node for node in snapshot["nodes"] if node["id"] == "CLAIM-historical"
    )
    assert historical["status"] == "SUPERSEDED"
    assert historical["superseded_by_claim_id"] == "CLAIM-evidence"
    reconstruction = next(
        node for node in snapshot["nodes"] if node["id"] == "RECON-one"
    )
    step = next(node for node in snapshot["nodes"] if node["id"] == "STEP-one")
    assert reconstruction["evidence_preserved"] is True
    assert reconstruction["reconstructed_tokens"] == 100
    assert reconstruction["baseline_tokens"] == 240
    assert step["action"] == "SEED"
    assert step["reason"] == "Best evidence seed."
    assert attempt["selected_claim"] == "neither"
    assert attempt["unresolved_questions"] == ["What does the contract say?"]


def test_demo_controller_uses_only_the_isolated_demo_script(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class Completed:
        returncode = 0
        stdout = "reset"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr("rlmgraph.dashboard.subprocess.run", fake_run)
    controller = DemoController(tmp_path)

    controller.reset()

    command, kwargs = calls[0]
    assert command[-1] == "--reset-only"
    assert command[-2] == str(tmp_path / "examples" / "live_neo4j_demo.py")
    assert kwargs["cwd"] == tmp_path
    assert controller.last_output == "reset"
