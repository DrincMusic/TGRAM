from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.models import SchedulerLimits, TicketBudget
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.operations import TicketAuditExporter
from rlmgraph.scheduler import ResourceAwareScheduler, SchedulingCancelled
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


def setup_project(store, root: Path, name: str):
    root.mkdir()
    (root / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    project = next(item for item in store.projects() if Path(item.root) == root.resolve())
    ticket = TicketManager(store).create(
        project_id=project.id,
        title=name,
        description="Exercise resource scheduling.",
        acceptance_criteria=["Work is bounded."],
        constraints=[],
        priority="MEDIUM",
        dependency_ticket_ids=[],
        budget=TicketBudget(max_worker_calls=4, max_wall_time_seconds=100),
        created_by="tester",
    )
    return project, ticket


def test_queue_order_accounts_for_priority_cost_latency_and_validation(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    _, low = setup_project(store, tmp_path / "low", "Low")
    _, urgent = setup_project(store, tmp_path / "urgent", "Urgent")
    low.priority = "LOW"
    urgent.priority = "URGENT"
    store.save_project_ticket(low)
    store.save_project_ticket(urgent)
    scheduler = ResourceAwareScheduler(store, limits=SchedulerLimits(global_concurrency=2))
    scheduler.enqueue(
        ticket_id=low.id, work_kind="VALIDATION", predicted_cost_usd=0.01,
        predicted_latency_seconds=1,
    )
    expected = scheduler.enqueue(
        ticket_id=urgent.id, work_kind="VALIDATION", predicted_cost_usd=2,
        predicted_latency_seconds=30, required_validation_categories=["COMPILE"],
    )
    claimed = scheduler.claim_next()
    assert claimed and claimed.id == expected.id
    assert "priority=URGENT" in claimed.scheduling_reasons
    assert "validation_needs=COMPILE" in claimed.scheduling_reasons


def test_global_project_ticket_and_capacity_limits_are_durable(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    _, first_ticket = setup_project(store, tmp_path / "project", "First")
    second_ticket = TicketManager(store).create(
        project_id=first_ticket.project_id, title="Second", description="Second job.",
        acceptance_criteria=["Bounded."], constraints=[], priority="HIGH",
        dependency_ticket_ids=[], budget=TicketBudget(), created_by="tester",
    )
    limits = SchedulerLimits(
        global_concurrency=2, per_project_concurrency=1,
        per_ticket_concurrency=1, capacity_units=2,
    )
    scheduler = ResourceAwareScheduler(store, limits=limits)
    first = scheduler.enqueue(ticket_id=first_ticket.id, work_kind="IMPLEMENT", capacity_units=2)
    second = scheduler.enqueue(ticket_id=second_ticket.id, work_kind="VALIDATE")
    assert scheduler.claim_next().id == second.id  # higher ticket priority
    assert scheduler.claim_next() is None
    persisted = {item.id: item for item in store.scheduled_work()}
    assert persisted[first.id].status == "WAITING_FOR_CAPACITY"
    assert "Project concurrency" in persisted[first.id].blocked_reason


def test_global_ticket_and_capacity_admission_limits_each_block_excess_work(
    tmp_path: Path,
) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    _, ticket_one = setup_project(store, tmp_path / "one", "One")
    _, ticket_two = setup_project(store, tmp_path / "two", "Two")

    global_scheduler = ResourceAwareScheduler(
        store, limits=SchedulerLimits(
            global_concurrency=1, per_project_concurrency=2,
            per_ticket_concurrency=2, capacity_units=3,
        ),
    )
    first = global_scheduler.enqueue(ticket_id=ticket_one.id, work_kind="ONE")
    second = global_scheduler.enqueue(ticket_id=ticket_two.id, work_kind="TWO")
    assert global_scheduler.claim_next().id == first.id
    assert global_scheduler.claim_next() is None
    assert "Global concurrency" in global_scheduler.get(second.id).blocked_reason
    global_scheduler.complete(first.id)
    assert global_scheduler.claim_next().id == second.id
    global_scheduler.complete(second.id)

    ticket_scheduler = ResourceAwareScheduler(
        store, limits=SchedulerLimits(
            global_concurrency=2, per_project_concurrency=2,
            per_ticket_concurrency=1, capacity_units=2,
        ),
    )
    same_one = ticket_scheduler.enqueue(ticket_id=ticket_one.id, work_kind="SAME_ONE")
    same_two = ticket_scheduler.enqueue(ticket_id=ticket_one.id, work_kind="SAME_TWO")
    assert ticket_scheduler.claim_next().id == same_one.id
    assert ticket_scheduler.claim_next() is None
    assert "Ticket concurrency" in ticket_scheduler.get(same_two.id).blocked_reason
    ticket_scheduler.complete(same_one.id)
    ticket_scheduler.complete(ticket_scheduler.claim_next().id)

    capacity_scheduler = ResourceAwareScheduler(
        store, limits=SchedulerLimits(
            global_concurrency=2, per_project_concurrency=2,
            per_ticket_concurrency=2, capacity_units=2,
        ),
    )
    ticket_one.priority = "URGENT"
    store.save_project_ticket(ticket_one)
    heavy = capacity_scheduler.enqueue(
        ticket_id=ticket_one.id, work_kind="HEAVY", capacity_units=2,
    )
    light = capacity_scheduler.enqueue(ticket_id=ticket_two.id, work_kind="LIGHT")
    assert capacity_scheduler.claim_next().id == heavy.id
    assert capacity_scheduler.claim_next() is None
    assert "capacity units" in capacity_scheduler.get(light.id).blocked_reason


def test_budget_and_lease_contention_become_actionable_states(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    project, ticket = setup_project(store, tmp_path / "project", "Budget")
    blocked = ResourceAwareScheduler(store).enqueue(
        ticket_id=ticket.id, work_kind="VALIDATE", predicted_worker_calls=5,
    )
    assert blocked.status == "BLOCKED_BUDGET"
    assert "worker calls" in blocked.blocked_reason

    store.acquire_project_lease(project.root, "other-process", "other-work", ttl_seconds=300)
    scheduler = ResourceAwareScheduler(store)
    waiting = scheduler.enqueue(
        ticket_id=ticket.id, work_kind="PROMOTE", predicted_worker_calls=1,
        requires_project_lease=True,
    )
    assert scheduler.claim_next() is None
    waiting = scheduler.get(waiting.id)
    assert waiting.status == "WAITING_FOR_LEASE"
    assert "other-process" in waiting.blocked_reason


def test_restart_resume_and_cancellation_preserve_evidence_and_dispose_resources(
    tmp_path: Path,
) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    _, ticket = setup_project(store, tmp_path / "project", "Restart")
    resource_root = tmp_path / "scheduler-temp"
    resource = resource_root / "job-one"
    resource.mkdir(parents=True)
    (resource / "evidence.txt").write_text("temporary", encoding="utf-8")
    scheduler = ResourceAwareScheduler(store, temporary_root=resource_root)
    queued = scheduler.enqueue(ticket_id=ticket.id, work_kind="IMPLEMENT")
    running = scheduler.claim_next()
    assert running and running.id == queued.id
    scheduler.register_temporary_resource(running.id, resource)
    scheduler.checkpoint(running.id, "PATCH_CAPTURED", "Evidence persisted.", evidence_ids=["E-1"])

    restarted = ResourceAwareScheduler(store, temporary_root=resource_root)
    interrupted = restarted.get(running.id)
    assert interrupted.status == "INTERRUPTED" and interrupted.evidence_ids == ["E-1"]
    resumed = restarted.resume(interrupted.id)
    assert resumed.status == "QUEUED"
    cancelled = restarted.request_cancellation(
        resumed.id, actor="operator", reason="Capacity is needed elsewhere."
    )
    assert cancelled.status == "CANCELLED"
    assert cancelled.resources_disposed is True and not resource.exists()
    assert cancelled.evidence_ids == ["E-1"]
    assert cancelled.checkpoints[-1].stage == "CANCELLED"


def test_running_work_honors_cooperative_cancellation_at_checkpoint(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    _, ticket = setup_project(store, tmp_path / "project", "Cancel running")
    scheduler = ResourceAwareScheduler(store)
    item = scheduler.enqueue(ticket_id=ticket.id, work_kind="HEAVY")
    scheduler.claim_next()
    scheduler.checkpoint(item.id, "EVIDENCE", "Evidence retained.", evidence_ids=["E-1"])
    requested = scheduler.request_cancellation(
        item.id, actor="operator", reason="Stop after the current safe boundary."
    )
    assert requested.status == "CANCELLATION_REQUESTED"
    with pytest.raises(SchedulingCancelled):
        scheduler.checkpoint(item.id, "NEXT_STAGE", "Should not run.")
    cancelled = scheduler.get(item.id)
    assert cancelled.status == "CANCELLED" and cancelled.evidence_ids == ["E-1"]
    assert cancelled.resources_disposed is True


def test_sqlite_and_neo4j_serialize_the_same_scheduled_work_payload(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "scheduler.db")
    store.initialize()
    _, ticket = setup_project(store, tmp_path / "project", "Parity")
    item = ResourceAwareScheduler(store).enqueue(
        ticket_id=ticket.id, work_kind="VALIDATE",
        required_validation_categories=["PYTHON_TEST"],
    )
    sqlite_payload = store.scheduled_work()[0].model_dump_json()
    snapshot = build_dashboard_snapshot(store)
    assert snapshot["workspace"]["scheduled_work"][0]["id"] == item.id
    assert TicketAuditExporter(store).build(ticket.id)["scheduled_work"][0]["id"] == item.id

    class RecordingDriver:
        def __init__(self):
            self.calls = []

        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_scheduled_work(item)
    assert neo.driver.calls[0][1]["payload"] == sqlite_payload
    assert "HAS_SCHEDULED_WORK" in neo.driver.calls[0][0]
