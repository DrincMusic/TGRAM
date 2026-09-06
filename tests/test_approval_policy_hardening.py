from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.governance import ProjectGovernance
from rlmgraph.implementation_sandbox import ImplementationSandboxManager
from rlmgraph.models import (
    ApprovalPolicyRule,
    ImplementationSandboxAttempt,
    PatchChange,
    ProjectWorkspaceRecord,
    SandboxValidationDecision,
    TicketBudget,
)
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


class UnusedWorker:
    def implement(self, request, evidence, sandbox_root):  # pragma: no cover
        raise AssertionError("implementation must not run in governance tests")


def rules(*, plan=1, promotion=1, attestation=1, promotion_categories=None):
    return [
        ApprovalPolicyRule(
            id="PLAN-REVIEW", action="PLAN", required_roles=["PLAN_REVIEWER"],
            minimum_approvals=plan,
        ),
        ApprovalPolicyRule(
            id="PROMOTION-REVIEW", action="PROMOTION", required_roles=["PROMOTER"],
            minimum_approvals=promotion,
            required_validation_categories=promotion_categories or [],
        ),
        ApprovalPolicyRule(
            id="MANUAL-ATTESTATION", action="ATTESTATION", required_roles=["VALIDATOR"],
            minimum_approvals=attestation,
        ),
    ]


def setup_governed(tmp_path: Path, *, policy_rules=None, artifact_requirements=None):
    root = tmp_path / "Project"
    root.mkdir()
    (root / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "governance.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    project = store.projects()[0]
    policy = ProjectGovernance(store).configure(
        project.id,
        permitted_worker_ids=["*"],
        required_validation_categories=[],
        plan_approvers=["*"],
        promotion_approvers=["*"],
        max_ticket_budget=TicketBudget(),
        actor="owner",
        reason="Configure sensitive-change governance.",
        actor_roles={
            "planner-one": ["PLAN_REVIEWER"],
            "planner-two": ["PLAN_REVIEWER"],
            "promoter-one": ["PROMOTER"],
            "promoter-two": ["PROMOTER"],
            "validator-one": ["VALIDATOR"],
            "validator-two": ["VALIDATOR"],
            "outsider": ["OBSERVER"],
        },
        approval_rules=policy_rules or rules(),
        artifact_validation_requirements=artifact_requirements or {},
    )
    tickets = TicketManager(store)
    ticket = tickets.create(
        project_id=project.id, title="Governed change", description="Test approval policy.",
        acceptance_criteria=["Policy is enforced."], constraints=[], priority="HIGH",
        dependency_ticket_ids=[], budget=TicketBudget(), created_by="owner",
    )
    sandbox = ImplementationSandboxManager(store, UnusedWorker(), validation_workers=[])
    manifest = sandbox._current_manifest(project.id, root.resolve())
    plan = ProjectWorkspaceRecord(
        project_id=project.id, project_root=project.root, project_name="Project",
        kind="CHANGE_PLAN", prompt="Change VALUE", answer="Edit service.py",
        affected_paths=["service.py"], steps=["Edit VALUE"], risks=["Regression"],
        validation_requirements=["Review behavior"], status="COMPLETED",
        approval_required=True, approval_status="PENDING", index_scan_id=project.latest_scan_id or "",
        indexed_manifest_sha256=manifest, final_manifest_sha256=manifest,
        source_integrity_verified=True, read_only_verified=True,
    )
    tickets.attach_workspace_record(ticket.id, plan)
    return root, store, project, policy, tickets, ticket, plan, sandbox


def attempt_for(store, project, ticket, sandbox, *, artifact_kind="PYTHON", category="REVIEW"):
    manifest = sandbox._current_manifest(project.id, Path(project.root))
    validation = SandboxValidationDecision(
        path="service.py", artifact_kind=artifact_kind, category=category,
        requirement="Review the proposed behavior.", status="PASSED" if category != "REVIEW" else "REQUIRED",
    )
    attempt = ImplementationSandboxAttempt(
        ticket_id=ticket.id, plan_record_id="PLAN", project_id=project.id,
        project_root=project.root, status="READY_FOR_REVIEW", authorized_paths=["service.py"],
        changes=[PatchChange(
            path="service.py", before_hash="a" * 64, after_hash="b" * 64,
            unified_diff="-VALUE = 1\n+VALUE = 2",
        )],
        validation_decisions=[validation], worker="fixture",
        initial_manifest_sha256=manifest, final_manifest_sha256=manifest,
        filesystem_disposed=True, original_unchanged=True,
    )
    store.save_implementation_sandbox(attempt)
    return attempt, validation


def test_plan_requires_independent_role_bearing_reviewers_and_keeps_history(tmp_path: Path) -> None:
    _, store, _, policy, tickets, ticket, plan, _ = setup_governed(
        tmp_path, policy_rules=rules(plan=2)
    )
    first = tickets.approve_plan(
        ticket.id, plan.id, actor="planner-one", reason="First review."
    )
    assert first.approval_status == "PENDING"
    assert "1 additional independent" in first.approval_missing[0]
    duplicate = tickets.approve_plan(
        ticket.id, plan.id, actor="planner-one", reason="Repeat review."
    )
    assert duplicate.approval_status == "PENDING"
    approved = tickets.approve_plan(
        ticket.id, plan.id, actor="planner-two", reason="Independent review."
    )
    assert approved.approval_status == "APPROVED"
    assert len(approved.approval_history) == 3
    assert {item.actor for item in approved.approval_history} == {"planner-one", "planner-two"}
    assert all(item.policy_version == policy.version and item.rule_id == "PLAN-REVIEW" for item in approved.approval_history)
    assert store.project_workspace_records()[0].approval_history == approved.approval_history

    with pytest.raises(ValueError, match="lacks a role"):
        tickets.approve_plan(ticket.id, plan.id, actor="outsider", reason="Not my role.")
    denied = tickets.approve_plan(
        ticket.id, plan.id, actor="planner-one", reason="A later explicit denial.",
        decision="DENIED",
    )
    assert denied.approval_status == "DENIED"
    assert denied.approval_history[-1].decision == "DENIED"
    assert denied.approval_history[-1].rule_id == "PLAN-REVIEW"


def test_plan_approval_expires_on_artifact_or_policy_change(tmp_path: Path) -> None:
    _, store, project, _, tickets, ticket, plan, sandbox = setup_governed(tmp_path)
    approved = tickets.approve_plan(ticket.id, plan.id, actor="planner-one", reason="Reviewed.")
    approved.validation_requirements.append("A stronger new check")
    store.save_project_workspace_record(approved)
    with pytest.raises(ValueError, match="bound source, patch, requirements, or evidence changed"):
        sandbox.run(ticket.id, plan.id)
    expired = next(item for item in store.project_workspace_records() if item.id == plan.id)
    assert expired.approval_status == "EXPIRED"
    assert expired.approval_history[0].valid is True

    fresh = ProjectGovernance(store).configure(
        project.id, permitted_worker_ids=["*"], required_validation_categories=[],
        plan_approvers=["*"], promotion_approvers=["*"], max_ticket_budget=TicketBudget(),
        actor="owner", reason="Advance policy version without reusing approvals.",
    )
    assert fresh.version == 2 and len(fresh.revision_history) == 2
    assert fresh.revision_history[0].version == 1


def test_manual_attestation_requires_independent_validators_and_is_append_only(tmp_path: Path) -> None:
    _, store, project, policy, _, ticket, _, sandbox = setup_governed(
        tmp_path, policy_rules=rules(attestation=2)
    )
    attempt, validation = attempt_for(store, project, ticket, sandbox)
    first = sandbox.satisfy_validation(
        ticket.id, attempt.id, validation.id, actor="validator-one", detail="Reviewed once."
    )
    gate = first.validation_decisions[0]
    assert gate.status == "REQUIRED" and gate.attestation_missing
    second = sandbox.satisfy_validation(
        ticket.id, attempt.id, validation.id, actor="validator-two", detail="Independent review."
    )
    gate = second.validation_decisions[0]
    assert gate.status == "SATISFIED"
    assert len(gate.attestation_history) == 2
    assert all(item.policy_version == policy.version and item.rule_id == "MANUAL-ATTESTATION" for item in gate.attestation_history)


def test_promotion_threshold_and_binding_expiration_are_recomputed(tmp_path: Path) -> None:
    _, store, project, policy, _, ticket, _, sandbox = setup_governed(
        tmp_path, policy_rules=rules(promotion=2)
    )
    attempt, _ = attempt_for(store, project, ticket, sandbox, category="PYTHON_TEST")
    first = sandbox.approve_promotion(
        ticket.id, attempt.id, actor="promoter-one", reason="First promotion review."
    )
    assert first.promotion_approval is None and first.promotion_approval_missing
    second = sandbox.approve_promotion(
        ticket.id, attempt.id, actor="promoter-two", reason="Independent promotion review."
    )
    assert second.promotion_approval is not None
    assert len(second.promotion_approval_history) == 2
    assert second.promotion_approval.policy_version == policy.version
    assert second.promotion_approval.rule_ids == ["PROMOTION-REVIEW"]

    second.validation_decisions[0].requirement = "Changed validation requirement"
    store.save_implementation_sandbox(second)
    with pytest.raises(ValueError, match="expired or is incomplete"):
        sandbox.promote(ticket.id, attempt.id)
    expired = store.implementation_sandboxes(ticket.id)[0]
    assert expired.promotion_approval is None
    assert any("bound source, patch, requirements, or evidence changed" in item for item in expired.promotion_approval_expiration_reasons)


def test_artifact_specific_validation_and_policy_version_cannot_retroactively_authorize(tmp_path: Path) -> None:
    _, store, project, _, _, ticket, _, sandbox = setup_governed(
        tmp_path, artifact_requirements={"CPP": ["COMPILE"]}
    )
    attempt, _ = attempt_for(
        store, project, ticket, sandbox, artifact_kind="CPP", category="PYTHON_TEST"
    )
    with pytest.raises(ValueError, match="requires validation categories: COMPILE"):
        sandbox.approve_promotion(
            ticket.id, attempt.id, actor="promoter-one", reason="Missing compilation."
        )

    python_attempt, _ = attempt_for(store, project, ticket, sandbox, category="PYTHON_TEST")
    sandbox.approve_promotion(
        ticket.id, python_attempt.id, actor="promoter-one", reason="Approved under v1."
    )
    ProjectGovernance(store).configure(
        project.id, permitted_worker_ids=["*"], required_validation_categories=[],
        plan_approvers=["*"], promotion_approvers=["*"], max_ticket_budget=TicketBudget(),
        actor="owner", reason="New policy must require a fresh decision.",
    )
    with pytest.raises(ValueError, match="expired or is incomplete"):
        sandbox.promote(ticket.id, python_attempt.id)


def test_policy_and_decision_history_have_sqlite_neo4j_and_observer_parity(tmp_path: Path) -> None:
    _, store, project, policy, tickets, ticket, plan, sandbox = setup_governed(tmp_path)
    approved = tickets.approve_plan(
        ticket.id, plan.id, actor="planner-one", reason="Parity review."
    )
    snapshot = build_dashboard_snapshot(store)
    node = next(item for item in snapshot["nodes"] if item["id"] == approved.id)
    assert node["approval_history"][0]["rule_id"] == "PLAN-REVIEW"
    shown_policy = next(
        item for item in snapshot["workspace"]["governance_policies"]
        if item["project_id"] == project.id
    )
    assert shown_policy["revision_history"][0]["version"] == policy.version

    class RecordingDriver:
        def __init__(self): self.calls = []
        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_project_governance_policy(policy)
    neo.save_project_workspace_record(approved)
    attempt, validation = attempt_for(store, project, ticket, sandbox)
    attested = sandbox.satisfy_validation(
        ticket.id, attempt.id, validation.id,
        actor="validator-one", detail="Parity attestation.",
    )
    neo.save_implementation_sandbox(attested)
    payloads = [parameters.get("payload", "") for _, parameters in neo.driver.calls]
    assert any('"revision_history"' in payload for payload in payloads)
    assert any('"approval_history"' in payload and '"rule_id":"PLAN-REVIEW"' in payload for payload in payloads)
    assert any('"attestation_history"' in payload and '"rule_id":"MANUAL-ATTESTATION"' in payload for payload in payloads)
