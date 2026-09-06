from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from test_approval_policy_hardening import setup_governed
from test_implementation_sandbox import promoted_source_only_attempt

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.models import (
    ImplementationSandboxAttempt,
    PatchChange,
    ScheduledWorkItem,
    SchedulerLimits,
    TicketBudget,
)
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder, ReadOnlyViolation
from rlmgraph.operations import TicketAuditExporter
from rlmgraph.reconciliation import SandboxPromotionReconciler
from rlmgraph.scheduler import ResourceAwareScheduler
from rlmgraph.store import GraphStore, Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


def test_complete_ticket_lifecycle_reaches_reconciled_auditable_closure(tmp_path: Path) -> None:
    root, store, ticket, plan, attempt, _ = promoted_source_only_attempt(tmp_path)
    persisted_plan = next(item for item in store.project_workspace_records() if item.id == plan.id)
    assert persisted_plan.approval_status == "APPROVED"
    assert attempt.status == "PROMOTED" and attempt.promotion
    assert all(
        decision.status in {"PASSED", "SATISFIED"}
        for decision in attempt.validation_decisions
    )

    reconciliation = SandboxPromotionReconciler(store).reconcile(ticket.id, attempt.id)
    tickets = TicketManager(store)
    criterion = tickets.get(ticket.id).acceptance_criteria[0]
    tickets.resolve_criterion(
        ticket.id, criterion.id, status="EVIDENCED",
        evidence_ids=[reconciliation.id], reason="", actor="release-reviewer",
    )
    satisfied = tickets.transition(
        ticket.id, "SATISFIED", actor="release-reviewer",
        reason="Promoted and reconciled evidence satisfies the requested outcome.",
    )
    closed = tickets.transition(
        ticket.id, "CLOSED", actor="release-reviewer",
        reason="Release lifecycle and audit package reviewed.",
    )
    package = TicketAuditExporter(store).build(ticket.id)

    assert satisfied.status == "SATISFIED" and closed.status == "CLOSED"
    assert closed.closure_decisions[-1].allowed is True
    assert reconciliation.status == "RECONCILED"
    assert TicketAuditExporter.verify(package)
    assert package["implementation_sandboxes"][0]["promotion"]["reconciliation"]["id"] == reconciliation.id
    assert Path(root, "src/service.py").read_text(encoding="utf-8").endswith("value + value\n")


def test_release_security_contract_rejects_escape_cross_project_and_stale_approval(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Project"
    root.mkdir()
    (root / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    other = tmp_path / "Other"
    other.mkdir()
    (other / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "security.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(other))
    projects = store.projects()
    project = next(item for item in projects if Path(item.root) == root.resolve())
    foreign = next(item for item in projects if item.id != project.id)
    tickets = TicketManager(store)
    ticket = tickets.create(
        project_id=project.id, title="Security", description="Verify release boundaries.",
        acceptance_criteria=["Boundaries hold."], constraints=[], priority="HIGH",
        dependency_ticket_ids=[], budget=TicketBudget(), created_by="release-test",
    )

    attempt = ImplementationSandboxAttempt(
        ticket_id=ticket.id, plan_record_id="PLAN", project_id=project.id,
        project_root=project.root, status="READY_FOR_REVIEW",
        authorized_paths=["service.py"],
        changes=[PatchChange(
            path="../Other/other.py", before_hash="a" * 64, after_hash="b" * 64,
            unified_diff="-OTHER = 1\n+OTHER = 2",
        )],
        initial_manifest_sha256="a" * 64, final_manifest_sha256="a" * 64,
        filesystem_disposed=True, original_unchanged=True, worker="fixture",
    )
    with pytest.raises((ValueError, ReadOnlyViolation), match="authorized|path|boundary|outside"):
        tickets.attach_sandbox_attempt(ticket.id, attempt)

    foreign_attempt = attempt.model_copy(update={
        "id": "SANDBOX-FOREIGN", "project_id": foreign.id, "project_root": foreign.root,
        "changes": [], "authorized_paths": ["other.py"],
    })
    with pytest.raises(ValueError, match="originating ticket|project|root"):
        tickets.attach_sandbox_attempt(ticket.id, foreign_attempt)

    scheduler = ResourceAwareScheduler(
        store, limits=SchedulerLimits(
            global_concurrency=1, per_project_concurrency=1,
            per_ticket_concurrency=1, capacity_units=1,
        ),
    )
    first = scheduler.enqueue(ticket_id=ticket.id, work_kind="SECURITY_ONE")
    second = scheduler.enqueue(ticket_id=ticket.id, work_kind="SECURITY_TWO")
    assert scheduler.claim_next().id == first.id
    assert scheduler.claim_next() is None
    assert scheduler.get(second.id).status == "WAITING_FOR_CAPACITY"

    approval_root = tmp_path / "approval"
    approval_root.mkdir()
    _, approval_store, _, _, approval_tickets, approval_ticket, plan, sandbox = setup_governed(
        approval_root
    )
    with pytest.raises(ValueError, match="plan approval"):
        sandbox.run(approval_ticket.id, plan.id)
    approved = approval_tickets.approve_plan(
        approval_ticket.id, plan.id, actor="planner-one", reason="Release security review."
    )
    approved.validation_requirements.append("New requirement invalidates the binding")
    approval_store.save_project_workspace_record(approved)
    with pytest.raises(ValueError, match="bound source, patch, requirements, or evidence changed"):
        sandbox.run(approval_ticket.id, plan.id)


def test_sqlite_and_neo4j_expose_release_critical_store_contract() -> None:
    required = {
        "initialize", "projects", "project_scans", "project_files",
        "save_project_record",
        "save_project_ticket", "project_tickets", "save_project_workspace_record",
        "project_workspace_records", "save_implementation_sandbox",
        "implementation_sandboxes", "save_scheduled_work", "scheduled_work",
        "acquire_project_lease", "release_project_lease", "project_leases",
        "save_project_governance_policy", "project_governance_policies",
    }
    protocol = {name for name in required if callable(getattr(GraphStore, name, None))}
    assert protocol == required
    for backend in (SQLiteGraphStore, Neo4jGraphStore):
        assert all(callable(getattr(backend, name, None)) for name in required)

    item = ScheduledWorkItem(
        ticket_id="TICKET-contract", project_id="PROJECT-contract",
        project_root="C:/contract", work_kind="VALIDATION", status="QUEUED",
    )

    class RecordingDriver:
        def __init__(self):
            self.calls = []

        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_scheduled_work(item)
    payload = neo.driver.calls[0][1]["payload"]
    assert json.loads(payload) == item.model_dump(mode="json")
    assert "HAS_SCHEDULED_WORK" in neo.driver.calls[0][0]


def test_reproducible_scale_baselines_cover_index_history_queue_persistence_and_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "LargeProject"
    root.mkdir()
    for index in range(300):
        (root / f"module_{index:04d}.py").write_text(
            f"VALUE_{index} = {index}\n", encoding="utf-8"
        )
    store = SQLiteGraphStore(tmp_path / "performance.db")

    started = time.perf_counter()
    scan = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    index_seconds = time.perf_counter() - started
    project = store.projects()[0]
    tickets = TicketManager(store)
    ticket = tickets.create(
        project_id=project.id, title="Scale", description="Release baseline.",
        acceptance_criteria=["Baseline recorded."], constraints=[], priority="MEDIUM",
        dependency_ticket_ids=[], budget=TicketBudget(),
        created_by="benchmark",
    )
    scheduler = ResourceAwareScheduler(
        store, limits=SchedulerLimits(
            global_concurrency=4, per_project_concurrency=4,
            per_ticket_concurrency=4, capacity_units=4,
        ),
    )
    started = time.perf_counter()
    for index in range(250):
        scheduler.enqueue(
            ticket_id=ticket.id, work_kind=f"LOAD_{index:04d}",
            predicted_cost_usd=index / 100_000,
            predicted_latency_seconds=index % 30,
            predicted_worker_calls=0,
        )
    queue_seconds = time.perf_counter() - started
    started = time.perf_counter()
    persisted = SQLiteGraphStore(store.path).scheduled_work()
    persistence_seconds = time.perf_counter() - started
    started = time.perf_counter()
    snapshot = build_dashboard_snapshot(store)
    snapshot_seconds = time.perf_counter() - started

    assert scan.file_count == 300 and len(store.project_files(project.id)) == 300
    assert len(persisted) == 250
    assert len(snapshot["workspace"]["scheduled_work"]) == 250
    assert snapshot["metrics"]["scheduled_work"] == 250
    # Generous release ceilings catch algorithmic regressions without depending on fast hardware.
    assert index_seconds < 15
    assert queue_seconds < 15
    assert persistence_seconds < 5
    assert snapshot_seconds < 10
