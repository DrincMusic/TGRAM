import sqlite3
from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.implementation_sandbox import (
    ImplementationSandboxManager,
    InteractiveSandboxController,
)
from rlmgraph.interactive_workspace import InteractiveProjectWorkspaceController
from rlmgraph.models import ObserverActivityState, ProjectWorkspaceRecord, TicketBudget
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.operations import SQLiteMaintenance, TicketAuditExporter
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


def setup_workspace(tmp_path: Path):
    root = tmp_path / "Project"
    root.mkdir()
    (root / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "observer.db")
    project = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    project_record = next(item for item in store.projects() if item.id == project.project_id)
    manager = TicketManager(store)
    ticket = manager.create(
        project_id=project_record.id,
        title="Make the service dependable",
        description="Investigate and complete a real project-scoped workflow.",
        acceptance_criteria=["Current evidence proves the outcome."],
        constraints=["Preserve the registered source boundary."],
        priority="HIGH",
        dependency_ticket_ids=[],
        budget=TicketBudget(),
        created_by="test",
    )
    return store, manager, ticket


def test_interrupted_workspace_activity_survives_backend_restart(tmp_path: Path) -> None:
    store, _, ticket = setup_workspace(tmp_path)
    store.save_observer_activity(ObserverActivityState(
        id="OBSERVER-WORKSPACE",
        activity_kind="PROJECT_WORKSPACE",
        status="RUNNING",
        ticket_id=ticket.id,
        project_id=ticket.project_id,
        stage="Collecting current evidence.",
        resume_payload={
            "job_id": "WORKSPACE-interrupted",
            "kind": "DIAGNOSTIC",
            "project_id": ticket.project_id,
            "project_name": "Project",
            "ticket_id": ticket.id,
            "criteria": [],
            "status": "RUNNING",
            "stage": "Collecting current evidence.",
            "prompt": "What does the service do?",
            "started_at": "2026-08-16T00:00:00+00:00",
        },
    ))

    restarted = InteractiveProjectWorkspaceController(store)
    snapshot = restarted.snapshot()
    assert snapshot["status"] == "INTERRUPTED"
    assert snapshot["ticket_id"] == ticket.id
    assert snapshot["prompt"] == "What does the service do?"
    persisted = next(
        item for item in store.observer_activities() if item.id == "OBSERVER-WORKSPACE"
    )
    assert persisted.resumable is True
    assert persisted.status == "INTERRUPTED"
    assert build_dashboard_snapshot(store)["workspace"]["focus_ticket_id"] == ticket.id


def test_interrupted_sandbox_activity_survives_backend_restart(tmp_path: Path) -> None:
    store, _, ticket = setup_workspace(tmp_path)
    store.save_observer_activity(ObserverActivityState(
        id="OBSERVER-SANDBOX",
        activity_kind="IMPLEMENTATION_SANDBOX",
        status="RUNNING",
        ticket_id=ticket.id,
        stage="Building an isolated implementation.",
        resume_payload={
            "attempt_id": None,
            "ticket_id": ticket.id,
            "plan_record_id": "WORKSPACE-RESULT-plan",
            "status": "RUNNING",
            "stage": "Building an isolated implementation.",
            "error": None,
        },
    ))

    controller = InteractiveSandboxController(ImplementationSandboxManager(store, object()))
    snapshot = controller.snapshot()
    assert snapshot["status"] == "INTERRUPTED"
    assert snapshot["ticket_id"] == ticket.id
    persisted = next(
        item for item in store.observer_activities() if item.id == "OBSERVER-SANDBOX"
    )
    assert persisted.resumable is True


def test_work_queue_opens_with_an_actionable_real_ticket(tmp_path: Path) -> None:
    store, manager, ticket = setup_workspace(tmp_path)
    manager.transition(ticket.id, "ACTIVE", actor="test", reason="Begin work.")
    snapshot = build_dashboard_snapshot(store)

    assert snapshot["workspace"]["focus_ticket_id"] == ticket.id
    item = snapshot["workspace"]["work_items"][0]
    assert item["ticket_id"] == ticket.id
    assert item["action"] == "INVESTIGATE"
    assert item["action_label"] == "Investigate or plan"
    assert item["detail"] == "Start with current project evidence."

    ticket = manager.get(ticket.id)
    ticket.usage.worker_calls = ticket.budget.max_worker_calls
    store.save_project_ticket(ticket)
    item = build_dashboard_snapshot(store)["workspace"]["work_items"][0]
    assert item["action"] == "BUDGET_BLOCKED"
    assert item["exhausted_budgets"] == ["worker-call"]


def test_work_queue_advances_through_plan_implementation_and_completion(
    tmp_path: Path,
) -> None:
    store, manager, ticket = setup_workspace(tmp_path)
    manifest = manager._current_project_manifest(ticket)
    plan = ProjectWorkspaceRecord(
        project_id=ticket.project_id,
        project_root=ticket.project_root,
        project_name="Project",
        kind="CHANGE_PLAN",
        prompt="Plan the dependable service change.",
        answer="A bounded implementation plan.",
        status="COMPLETED",
        index_scan_id="SCAN-plan",
        indexed_manifest_sha256=manifest,
        final_manifest_sha256=manifest,
        source_integrity_verified=True,
        read_only_verified=True,
        approval_required=True,
        approval_status="PENDING",
    )
    manager.attach_workspace_record(ticket.id, plan)
    item = build_dashboard_snapshot(store)["workspace"]["work_items"][0]
    assert item["action"] == "APPROVE_PLAN"

    manager.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Scoped and current.")
    item = build_dashboard_snapshot(store)["workspace"]["work_items"][0]
    assert item["action"] == "IMPLEMENT"

    manager.resolve_criterion(
        ticket.id,
        ticket.acceptance_criteria[0].id,
        status="WAIVED",
        evidence_ids=[],
        reason="Explicitly removed from this ticket.",
        actor="owner",
    )
    item = build_dashboard_snapshot(store)["workspace"]["work_items"][0]
    assert item["action"] == "IMPLEMENT"
    manager.transition(ticket.id, "SATISFIED", actor="reviewer", reason="Reviewed gates.")
    item = build_dashboard_snapshot(store)["workspace"]["work_items"][0]
    assert item["action"] == "CLOSE"
    manager.transition(ticket.id, "CLOSED", actor="reviewer", reason="Archive completed work.")
    snapshot = build_dashboard_snapshot(store)
    assert snapshot["workspace"]["work_items"][0]["action"] == "DONE"
    assert snapshot["workspace"]["completed"] == 1


def test_ticket_audit_export_is_scoped_complete_and_self_verifying(tmp_path: Path) -> None:
    store, manager, ticket = setup_workspace(tmp_path)
    criterion = ticket.acceptance_criteria[0]
    manager.resolve_criterion(
        ticket.id,
        criterion.id,
        status="WAIVED",
        evidence_ids=[],
        reason="Explicitly removed from this ticket.",
        actor="owner",
    )
    manager.transition(ticket.id, "SATISFIED", actor="reviewer", reason="Reviewed gates.")

    package = TicketAuditExporter(store).build(ticket.id)
    assert package["format"] == "RLMGRAPH_TICKET_AUDIT"
    assert package["ticket"]["id"] == ticket.id
    assert package["project_governance_policy"]["project_id"] == ticket.project_id
    assert package["ticket"]["closure_decisions"]
    assert package["events"]
    assert TicketAuditExporter.verify(package) is True
    package["ticket"]["title"] = "tampered"
    assert TicketAuditExporter.verify(package) is False


def test_sqlite_backup_restore_migration_and_maintenance_are_verified(
    tmp_path: Path,
) -> None:
    store, manager, ticket = setup_workspace(tmp_path)
    operations = SQLiteMaintenance(store)
    migrated = operations.migrate()
    assert migrated["schema_version"] == migrated["expected_schema_version"]
    assert migrated["integrity"] == "ok"
    assert migrated["required_tables_present"] is True
    with store.connect() as db:
        indexes = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_schema WHERE type='index'"
            ).fetchall()
        }
        plan = " ".join(
            str(value) for row in db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM ticket_events "
                "INDEXED BY ix_ticket_event_ticket WHERE ticket_id=?",
                (ticket.id,),
            ).fetchall() for value in row
        )
    assert "ix_ticket_event_ticket" in indexes
    assert "USING INDEX ix_ticket_event_ticket" in plan

    registered_root = Path(store.projects()[0].root)
    with pytest.raises(ValueError, match="outside registered project root"):
        operations.backup(registered_root / "forbidden-backup.db")

    backup_path = tmp_path / "backups" / "observer-backup.db"
    backup = operations.backup(backup_path)
    assert backup["integrity"] == "ok" and backup_path.is_file()
    with pytest.raises(ValueError, match="confirmation must be exactly"):
        operations.restore(backup_path, confirmation="RESTORE wrong.db")
    manager.transition(ticket.id, "ACTIVE", actor="test", reason="Change after backup.")
    assert manager.get(ticket.id).status == "ACTIVE"

    restored = operations.restore(
        backup_path, confirmation=f"RESTORE {backup_path.name}"
    )
    assert restored["integrity"] == "ok"
    assert Path(restored["safety_backup"]).is_file()
    assert manager.get(ticket.id).status == "DRAFT"
    assert store.project_governance_policies()[0].project_id == ticket.project_id
    assert operations.optimize()["integrity"] == "ok"


def test_migration_upgrades_a_minimal_legacy_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE tasks (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)"
        )
    status = SQLiteMaintenance(SQLiteGraphStore(path)).migrate()
    assert status["schema_version"] == 4
    assert status["required_tables_present"] is True
    assert status["integrity"] == "ok"


def test_observer_activity_has_sqlite_and_neo4j_payload_parity(tmp_path: Path) -> None:
    store, _, ticket = setup_workspace(tmp_path)
    state = ObserverActivityState(
        id="OBSERVER-WORKSPACE",
        activity_kind="PROJECT_WORKSPACE",
        status="INTERRUPTED",
        ticket_id=ticket.id,
        project_id=ticket.project_id,
        stage="Resume from the work queue.",
        resumable=True,
        resume_payload={"prompt": "Resume me"},
    )
    store.save_observer_activity(state)
    assert store.observer_activities()[0] == state

    class RecordingDriver:
        def __init__(self):
            self.calls = []

        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_observer_activity(state)
    payload = neo.driver.calls[0][1]["payload"]
    assert '"resumable":true' in payload
    assert '"Resume me"' in payload
