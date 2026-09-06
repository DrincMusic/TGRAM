from datetime import timedelta
from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.models import (
    Evidence,
    ImplementationSandboxAttempt,
    PatchChange,
    ProjectWorkspaceRecord,
    TicketBudget,
)
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


def setup_manager(tmp_path: Path):
    root = tmp_path / "Project"
    root.mkdir()
    (root / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "tickets.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    return root, store, TicketManager(store), store.projects()[0]


def create_ticket(manager, project, *, dependencies=None, budget=None):
    return manager.create(
        project_id=project.id,
        title="Explain the service",
        description="Collect graph-grounded evidence without changing source.",
        acceptance_criteria=["The answer cites current project evidence."],
        constraints=["Project source remains unchanged."],
        priority="HIGH",
        dependency_ticket_ids=dependencies or [],
        budget=budget or TicketBudget(),
        created_by="test",
    )


def test_ticket_requires_attached_evidence_before_satisfied(tmp_path: Path) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    ticket = create_ticket(manager, project)
    criterion = ticket.acceptance_criteria[0]

    with pytest.raises(ValueError, match="remains pending"):
        manager.transition(ticket.id, "SATISFIED", actor="test", reason="premature")
    with pytest.raises(ValueError, match="belong to this ticket"):
        manager.resolve_criterion(
            ticket.id, criterion.id, status="EVIDENCED", evidence_ids=["foreign"],
            reason="", actor="test",
        )

    record = ProjectWorkspaceRecord(
        project_id=project.id, project_root=project.root, project_name="Project",
        kind="DIAGNOSTIC", prompt="What is VALUE?", answer="VALUE is 1.",
        status="COMPLETED", index_scan_id="SCAN-test",
        indexed_manifest_sha256="same", final_manifest_sha256="same",
        evidence=[Evidence(path="service.py", detail="VALUE = 1")],
        source_integrity_verified=True, read_only_verified=True,
        tokens_used=30, worker_calls_used=1, elapsed_seconds=0.25,
    )
    manager.attach_workspace_record(ticket.id, record)
    ticket = manager.resolve_criterion(
        ticket.id, criterion.id, status="EVIDENCED", evidence_ids=[record.id],
        reason="", actor="test",
    )
    ticket = manager.transition(ticket.id, "SATISFIED", actor="test", reason="all proven")

    assert ticket.status == "SATISFIED"
    assert ticket.execution_authorized is False
    assert ticket.usage.tokens == 30 and ticket.usage.worker_calls == 1
    assert store.project_workspace_records()[0].ticket_id == ticket.id
    assert all(not item.execution_authorized for item in store.project_tickets())


def test_waiver_blocker_dependencies_and_budget_are_enforced(tmp_path: Path) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    dependency = create_ticket(manager, project)
    dependent = create_ticket(
        manager, project, dependencies=[dependency.id],
        budget=TicketBudget(max_worker_calls=1),
    )
    criterion = dependent.acceptance_criteria[0]
    with pytest.raises(ValueError, match="explicit reason"):
        manager.resolve_criterion(
            dependent.id, criterion.id, status="WAIVED", evidence_ids=[], reason="", actor="test"
        )
    manager.resolve_criterion(
        dependent.id, criterion.id, status="BLOCKED", evidence_ids=[],
        reason="External service unavailable.", actor="test",
    )
    with pytest.raises(ValueError, match="dependency is not satisfied"):
        manager.transition(dependent.id, "SATISFIED", actor="test", reason="blocked documented")

    dep_criterion = dependency.acceptance_criteria[0]
    manager.resolve_criterion(
        dependency.id, dep_criterion.id, status="WAIVED", evidence_ids=[],
        reason="Explicitly out of scope.", actor="test",
    )
    manager.transition(dependency.id, "SATISFIED", actor="test", reason="waived")
    assert manager.transition(
        dependent.id, "SATISFIED", actor="test", reason="blocker documented"
    ).status == "SATISFIED"

    record = ProjectWorkspaceRecord(
        project_id=project.id, project_root=project.root, project_name="Project",
        kind="DIAGNOSTIC", prompt="q", answer="a", worker_calls_used=1,
        status="COMPLETED", index_scan_id="SCAN-test",
        indexed_manifest_sha256="same", final_manifest_sha256="same",
        source_integrity_verified=True, read_only_verified=True,
    )
    manager.attach_workspace_record(dependent.id, record)
    with pytest.raises(RuntimeError, match="worker-call"):
        manager.check_budget(dependent.id)
    assert store.ticket_events(dependent.id)


def test_validation_is_ticket_scoped_and_never_authorizes_execution(tmp_path: Path) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    ticket = create_ticket(manager, project)
    validation = manager.record_validation(
        ticket.id, name="Read-only check", status="PASSED", detail="Manifest unchanged.",
        evidence=[Evidence(path="service.py", detail="Hash matched")],
        workspace_record_id=None, recorded_by="test",
    )
    assert validation.execution_authorized is False
    criterion = ticket.acceptance_criteria[0]
    manager.resolve_criterion(
        ticket.id, criterion.id, status="EVIDENCED", evidence_ids=[validation.id],
        reason="", actor="test",
    )
    assert store.ticket_validation_results(ticket.id)[0].id == validation.id


def test_failed_stale_and_superseded_evidence_cannot_resolve_or_close(tmp_path: Path) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    ticket = create_ticket(manager, project)
    criterion = ticket.acceptance_criteria[0]
    failed = manager.record_validation(
        ticket.id, name="Tests", status="FAILED", detail="A regression failed.",
        evidence=[], workspace_record_id=None, recorded_by="validator",
    )
    with pytest.raises(ValueError, match="status is FAILED"):
        manager.resolve_criterion(
            ticket.id, criterion.id, status="EVIDENCED", evidence_ids=[failed.id],
            reason="", actor="reviewer",
        )

    current = ProjectWorkspaceRecord(
        project_id=project.id, project_root=project.root, project_name="Project",
        kind="DIAGNOSTIC", prompt="q", answer="a", status="COMPLETED",
        index_scan_id="SCAN-test", indexed_manifest_sha256="current",
        final_manifest_sha256="current", source_integrity_verified=True,
        read_only_verified=True,
    )
    manager.attach_workspace_record(ticket.id, current)
    manager.resolve_criterion(
        ticket.id, criterion.id, status="EVIDENCED", evidence_ids=[current.id],
        reason="", actor="reviewer",
    )
    current.status = "SUPERSEDED"
    store.save_project_workspace_record(current)
    with pytest.raises(ValueError, match="current eligible evidence"):
        manager.transition(ticket.id, "SATISFIED", actor="reviewer", reason="close")

    persisted = manager.get(ticket.id)
    assert persisted.status == "DRAFT"
    assert persisted.closure_decisions[-1].allowed is False
    assert persisted.acceptance_criteria[0].evidence_assessments[-1].eligible is False
    current.status = "COMPLETED"
    current.final_manifest_sha256 = "stale"
    store.save_project_workspace_record(current)
    assert "stale" in manager.assess_evidence(persisted, current.id).reason


def test_cross_ticket_cross_project_and_direct_close_are_rejected(tmp_path: Path) -> None:
    root, store, manager, project = setup_manager(tmp_path)
    other_root = tmp_path / "Other"
    other_root.mkdir()
    (other_root / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(other_root))
    other_project = next(item for item in store.projects() if item.id != project.id)
    ticket = create_ticket(manager, project)
    other_ticket = create_ticket(manager, project)
    criterion = ticket.acceptance_criteria[0]
    foreign = ProjectWorkspaceRecord(
        project_id=project.id, project_root=str(root), project_name="Project",
        kind="DIAGNOSTIC", prompt="q", answer="a", status="COMPLETED",
        index_scan_id="SCAN-test", indexed_manifest_sha256="same",
        final_manifest_sha256="same", source_integrity_verified=True,
        read_only_verified=True, ticket_id=other_ticket.id,
    )
    store.save_project_workspace_record(foreign)
    with pytest.raises(ValueError, match="belongs to ticket"):
        manager.resolve_criterion(
            ticket.id, criterion.id, status="EVIDENCED", evidence_ids=[foreign.id],
            reason="", actor="reviewer",
        )
    wrong_project = foreign.model_copy(update={
        "id": "WORKSPACE-RESULT-wrong-project", "ticket_id": ticket.id,
        "project_id": other_project.id, "project_root": other_project.root,
    })
    store.save_project_workspace_record(wrong_project)
    with pytest.raises(ValueError, match="belongs to project"):
        manager.resolve_criterion(
            ticket.id, criterion.id, status="EVIDENCED",
            evidence_ids=[wrong_project.id], reason="", actor="reviewer",
        )
    with pytest.raises(ValueError, match="cannot be CLOSED"):
        manager.transition(ticket.id, "CLOSED", actor="reviewer", reason="bypass")


def test_closure_decisions_are_attributed_idempotent_and_serialize_for_both_stores(
    tmp_path: Path,
) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    ticket = create_ticket(manager, project)
    for _ in range(2):
        with pytest.raises(ValueError, match="remains pending"):
            manager.transition(ticket.id, "SATISFIED", actor="reviewer", reason="same request")
    ticket = manager.get(ticket.id)
    assert len(ticket.closure_decisions) == 1
    assert ticket.closure_decisions[0].actor == "reviewer"
    assert sum(event.kind == "CLOSURE_DECIDED" for event in store.ticket_events(ticket.id)) == 1

    criterion = ticket.acceptance_criteria[0]
    manager.resolve_criterion(
        ticket.id, criterion.id, status="WAIVED", evidence_ids=[],
        reason="Requirement was explicitly removed from scope.", actor="owner",
    )
    satisfied = manager.transition(
        ticket.id, "SATISFIED", actor="reviewer", reason="reviewed gates",
    )
    sqlite_round_trip = manager.get(ticket.id)
    assert sqlite_round_trip.closure_decisions[-1].allowed is True
    assert sqlite_round_trip.closure_decisions[-1].criterion_gates[0].resolved_by == "owner"

    class RecordingDriver:
        def __init__(self):
            self.calls = []

        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_project_ticket(satisfied)
    payload = next(
        parameters["payload"] for query, parameters in neo.driver.calls
        if "ticket.payload" in query
    )
    assert '"closure_decisions"' in payload
    assert '"criterion_gates"' in payload


def test_observer_snapshot_explains_gates_and_only_offers_eligible_evidence(
    tmp_path: Path,
) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    ticket = create_ticket(manager, project)
    passed = manager.record_validation(
        ticket.id, name="Current check", status="PASSED", detail="Passed.",
        evidence=[], workspace_record_id=None, recorded_by="validator",
    )
    failed = manager.record_validation(
        ticket.id, name="Failed check", status="FAILED", detail="Failed.",
        evidence=[], workspace_record_id=None, recorded_by="validator",
    )
    manager.resolve_criterion(
        ticket.id, ticket.acceptance_criteria[0].id, status="EVIDENCED",
        evidence_ids=[passed.id], reason="", actor="reviewer",
    )
    snapshot = build_dashboard_snapshot(store)
    node = next(item for item in snapshot["nodes"] if item["id"] == ticket.id)
    assert node["closure_ready"] is True
    assert node["closure_failures"] == []
    assert node["closure_gates"][0]["resolved"] is True
    assert "Current implementation evidence accepted" in node["closure_gates"][0]["explanation"]
    assert [item["evidence_id"] for item in node["eligible_ticket_evidence"]] == [passed.id]
    assert [item["evidence_id"] for item in node["ineligible_ticket_evidence"]] == [failed.id]
    assert "not PASSED" in node["ineligible_ticket_evidence"][0]["reason"]


def test_reviewable_sandbox_evidence_cannot_count_before_promotion_and_reconciliation(
    tmp_path: Path,
) -> None:
    _, store, manager, project = setup_manager(tmp_path)
    ticket = create_ticket(manager, project)
    manifest = manager._current_project_manifest(ticket)
    change = PatchChange(
        path="service.py", before_hash="before", after_hash="after",
        unified_diff="--- a/service.py\n+++ b/service.py\n",
    )
    first = ImplementationSandboxAttempt(
        ticket_id=ticket.id, plan_record_id="PLAN-one", project_id=project.id,
        project_root=project.root, status="READY_FOR_REVIEW",
        authorized_paths=["service.py"], changes=[change], patch_sha256="patch-one",
        worker="fixture", initial_manifest_sha256=manifest,
        final_manifest_sha256=manifest, original_unchanged=True,
        filesystem_disposed=True,
    )
    store.save_implementation_sandbox(first)
    assessment = manager.assess_evidence(ticket, first.id)
    assert assessment.eligible is False
    assert "not been promoted and reconciled" in assessment.reason
    second = first.model_copy(update={"id": "SANDBOX-newer", "patch_sha256": "patch-two"})
    second.created_at = first.created_at + timedelta(microseconds=1)
    store.save_implementation_sandbox(second)
    assert "not been promoted and reconciled" in manager.assess_evidence(ticket, first.id).reason
    second.status = "PROMOTION_REJECTED"
    store.save_implementation_sandbox(second)
    assert "promotion_rejected" in manager.assess_evidence(ticket, second.id).reason
