from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.governance import ProjectGovernance
from rlmgraph.implementation_sandbox import ImplementationSandboxManager
from rlmgraph.models import (
    ImplementationSandboxAttempt,
    ProjectWorkspaceRecord,
    SandboxValidationDecision,
    TicketBudget,
    ValidationWorkerLimits,
    ValidationWorkerSpec,
)
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder, ReadOnlyViolation
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


class UnusedWorker:
    def implement(self, request, evidence, sandbox_root):  # pragma: no cover
        raise AssertionError("worker must not run")


def setup_projects(tmp_path: Path):
    store = SQLiteGraphStore(tmp_path / "multi.db")
    onboarder = ReadOnlyProjectOnboarder(store)
    projects = []
    for name in ("Alpha", "Beta"):
        root = tmp_path / name
        root.mkdir()
        (root / "service.py").write_text(f"PROJECT = {name!r}\n", encoding="utf-8")
        onboarder.scan(ProjectSelection.explicit(root))
        projects.append(next(item for item in store.projects() if Path(item.root) == root.resolve()))
    return store, projects


def create_ticket(manager: TicketManager, project_id: str, dependencies=None, budget=None):
    return manager.create(
        project_id=project_id,
        title="Project-scoped work",
        description="Exercise one registered project boundary.",
        acceptance_criteria=["The project boundary is preserved."],
        constraints=[],
        priority="HIGH",
        dependency_ticket_ids=dependencies or [],
        budget=budget or TicketBudget(),
        created_by="owner",
    )


def test_cross_project_dependencies_are_explicitly_read_only(tmp_path: Path) -> None:
    store, (alpha, beta) = setup_projects(tmp_path)
    manager = TicketManager(store)
    dependency = create_ticket(manager, beta.id)
    ticket = create_ticket(manager, alpha.id, [dependency.id])

    assert ticket.dependency_scopes[0].project_id == beta.id
    assert ticket.dependency_scopes[0].read_only is True
    assert ticket.dependency_scopes[0].separately_authorized is False
    assert ticket.project_id == alpha.id
    assert Path(ticket.project_root) == Path(alpha.root)


def test_project_policy_enforces_budget_workers_and_approvers(tmp_path: Path) -> None:
    store, (alpha, beta) = setup_projects(tmp_path)
    governance = ProjectGovernance(store)
    alpha_policy = governance.configure(
        alpha.id,
        permitted_worker_ids=["ALPHA-WORKER"],
        required_validation_categories=["PYTHON_TEST"],
        plan_approvers=["alpha-planner"],
        promotion_approvers=["alpha-promoter"],
        max_ticket_budget=TicketBudget(max_tokens=100, max_model_calls=2, max_worker_calls=2),
        actor="alpha-owner",
        reason="Constrain Alpha independently.",
    )
    beta_policy = governance.configure(
        beta.id,
        permitted_worker_ids=["BETA-WORKER"],
        required_validation_categories=[],
        plan_approvers=["beta-planner"],
        promotion_approvers=["beta-promoter"],
        max_ticket_budget=TicketBudget(max_tokens=500),
        actor="beta-owner",
        reason="Keep Beta's authorization separate.",
    )
    manager = TicketManager(store)
    with pytest.raises(ValueError, match="exceeds project policy"):
        create_ticket(manager, alpha.id, budget=TicketBudget(max_tokens=101))
    ticket = create_ticket(manager, alpha.id, budget=TicketBudget(max_tokens=100, max_model_calls=2, max_worker_calls=2))
    plan = ProjectWorkspaceRecord(
        project_id=alpha.id, project_root=alpha.root, project_name="Alpha",
        kind="CHANGE_PLAN", prompt="change", answer="plan", affected_paths=["service.py"],
        status="COMPLETED", approval_required=True, source_integrity_verified=True,
        read_only_verified=True, index_scan_id=alpha.latest_scan_id or "",
        indexed_manifest_sha256="manifest", final_manifest_sha256="manifest",
    )
    manager.attach_workspace_record(ticket.id, plan)
    with pytest.raises(ValueError, match="not authorized"):
        manager.approve_plan(ticket.id, plan.id, actor="beta-planner", reason="wrong project")
    assert manager.approve_plan(
        ticket.id, plan.id, actor="alpha-planner", reason="approved for Alpha"
    ).approval_status == "APPROVED"
    assert alpha_policy.project_id != beta_policy.project_id
    assert {item.id for item in store.project_governance_policies()} == {
        alpha_policy.id, beta_policy.id,
    }


def test_worker_and_attempt_cannot_cross_project_policy(tmp_path: Path) -> None:
    store, (alpha, _) = setup_projects(tmp_path)
    governance = ProjectGovernance(store)
    governance.configure(
        alpha.id, permitted_worker_ids=["ALLOWED"], required_validation_categories=[],
        plan_approvers=["planner"], promotion_approvers=["promoter"],
        max_ticket_budget=TicketBudget(), actor="owner", reason="worker isolation",
    )
    ticket = create_ticket(TicketManager(store), alpha.id)
    decision = SandboxValidationDecision(
        path="service.py", artifact_kind="PYTHON", category="PYTHON_TEST",
        requirement="Run tests", status="REQUIRED",
    )
    attempt = ImplementationSandboxAttempt(
        ticket_id=ticket.id, plan_record_id="PLAN", project_id=alpha.id,
        project_root=alpha.root, status="READY_FOR_REVIEW", authorized_paths=["service.py"],
        validation_decisions=[decision], worker="fixture", initial_manifest_sha256="manifest",
    )
    store.save_implementation_sandbox(attempt)
    denied = ValidationWorkerSpec(
        id="DENIED", name="Wrong project worker", categories=["PYTHON_TEST"],
        artifact_kinds=["PYTHON"], executable="python", arguments=[],
        limits=ValidationWorkerLimits(), authorized_by="beta-owner", authorization_reason="Beta only",
    )
    sandbox = ImplementationSandboxManager(store, UnusedWorker(), validation_workers=[denied])
    with pytest.raises(ValueError, match="not permitted"):
        sandbox.run_validation_worker(ticket.id, attempt.id, decision.id, denied.id)

    attempt.project_id = "OTHER-PROJECT"
    store.save_implementation_sandbox(attempt)
    with pytest.raises(ReadOnlyViolation, match="does not match"):
        sandbox.run_validation_worker(ticket.id, attempt.id, decision.id, denied.id)


def test_promotion_requires_project_approver_and_project_validation_policy(tmp_path: Path) -> None:
    store, (alpha, _) = setup_projects(tmp_path)
    ProjectGovernance(store).configure(
        alpha.id, permitted_worker_ids=["*"], required_validation_categories=["COMPILE"],
        plan_approvers=["planner"], promotion_approvers=["alpha-promoter"],
        max_ticket_budget=TicketBudget(), actor="owner", reason="promotion governance",
    )
    ticket = create_ticket(TicketManager(store), alpha.id)
    decision = SandboxValidationDecision(
        path="service.py", artifact_kind="PYTHON", category="PYTHON_TEST",
        requirement="Run tests", status="PASSED",
    )
    attempt = ImplementationSandboxAttempt(
        ticket_id=ticket.id, plan_record_id="PLAN", project_id=alpha.id,
        project_root=alpha.root, status="READY_FOR_REVIEW", authorized_paths=["service.py"],
        validation_decisions=[decision], worker="fixture", initial_manifest_sha256="manifest",
    )
    store.save_implementation_sandbox(attempt)
    sandbox = ImplementationSandboxManager(store, UnusedWorker(), validation_workers=[])
    with pytest.raises(ValueError, match="not authorized"):
        sandbox.approve_promotion(
            ticket.id, attempt.id, actor="beta-promoter", reason="wrong project"
        )
    with pytest.raises(ValueError, match="requires validation categories: COMPILE"):
        sandbox.approve_promotion(
            ticket.id, attempt.id, actor="alpha-promoter", reason="missing compile"
        )

def test_policy_sqlite_neo4j_and_observer_parity(tmp_path: Path) -> None:
    store, (alpha, _) = setup_projects(tmp_path)
    policy = ProjectGovernance(store).configure(
        alpha.id, permitted_worker_ids=["WORKER"], required_validation_categories=["COMPILE"],
        plan_approvers=["planner"], promotion_approvers=["promoter"],
        max_ticket_budget=TicketBudget(max_tokens=321), actor="owner", reason="parity",
    )
    round_trip = next(item for item in store.project_governance_policies() if item.id == policy.id)
    assert round_trip == policy

    class RecordingDriver:
        def __init__(self): self.calls = []
        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_project_governance_policy(policy)
    payload = neo.driver.calls[0][1]["payload"]
    assert '"project_id"' in payload and '"permitted_worker_ids"' in payload

    snapshot = build_dashboard_snapshot(store)
    shown = next(item for item in snapshot["workspace"]["governance_policies"] if item["id"] == policy.id)
    assert shown["project_id"] == alpha.id
    assert shown["required_validation_categories"] == ["COMPILE"]


def test_registered_project_roots_cannot_overlap(tmp_path: Path) -> None:
    root = tmp_path / "Root"
    nested = root / "Nested"
    nested.mkdir(parents=True)
    (root / "root.py").write_text("ROOT = True\n", encoding="utf-8")
    (nested / "nested.py").write_text("NESTED = True\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "overlap.db")
    onboarder = ReadOnlyProjectOnboarder(store)
    onboarder.scan(ProjectSelection.explicit(root))
    with pytest.raises(ValueError, match="must not overlap"):
        onboarder.scan(ProjectSelection.explicit(nested))
