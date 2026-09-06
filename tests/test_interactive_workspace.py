from __future__ import annotations

import time
from pathlib import Path

from rlmgraph.interactive_workspace import InteractiveProjectWorkspaceController
from rlmgraph.models import TicketBudget
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.scheduler import ResourceAwareScheduler
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


def wait(controller: InteractiveProjectWorkspaceController) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = controller.snapshot()
        if state["status"] in {"COMPLETED", "FAILED"}:
            return state
        time.sleep(0.01)
    raise AssertionError("workspace job did not finish")


def generic_fixture(tmp_path: Path):
    root = tmp_path / "SampleProject"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src/service.py").write_text(
        "def calculate_total(value):\n    return value * 2\n", encoding="utf-8"
    )
    (root / "tests/test_service.py").write_text(
        "from src.service import calculate_total\n\ndef test_total():\n    assert calculate_total(2) == 4\n",
        encoding="utf-8",
    )
    store = SQLiteGraphStore(tmp_path / "generic.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    return root, store


def scheduled_ticket(store, project_id):
    return TicketManager(store).create(
        project_id=project_id, title="Scheduled workspace", description="Queue read-only work.",
        acceptance_criteria=["Evidence is current."], constraints=[], priority="HIGH",
        dependency_ticket_ids=[], budget=TicketBudget(), created_by="tester",
    )


def test_workspace_runs_through_durable_scheduler_and_can_cancel_while_waiting(
    tmp_path: Path,
) -> None:
    _, store = generic_fixture(tmp_path)
    project = store.projects()[0]
    ticket = scheduled_ticket(store, project.id)
    scheduler = ResourceAwareScheduler(store)
    controller = InteractiveProjectWorkspaceController(store, scheduler=scheduler)
    controller.start_diagnostic(project.id, "How is calculate_total tested?", ticket.id)
    completed = wait(controller)
    scheduled = store.scheduled_work()[0]
    assert completed["status"] == "COMPLETED"
    assert scheduled.status == "COMPLETED"
    assert scheduled.evidence_ids and scheduled.checkpoints[-1].stage == "COMPLETED"

    blocker = scheduler.enqueue(ticket_id=ticket.id, work_kind="BLOCKER")
    assert scheduler.try_claim(blocker.id)
    controller.start_diagnostic(project.id, "Where is calculate_total defined?", ticket.id)
    deadline = time.monotonic() + 2
    while controller.snapshot()["status"] != "QUEUED":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    cancelled = controller.cancel(actor="operator", reason="Release the queued request.")
    assert cancelled["status"] == "CANCELLED"
    assert store.scheduled_work()[-1].status == "CANCELLED"


def test_workspace_supports_any_registered_source_project_and_history(tmp_path: Path) -> None:
    root, store = generic_fixture(tmp_path)
    project = store.projects()[0]
    controller = InteractiveProjectWorkspaceController(store)
    options = controller.options()

    assert options["projects"][0]["name"] == "SampleProject"
    assert options["projects"][0]["adapter"] == "SOURCE_GRAPH"
    assert options["projects"][0]["index_current"]
    assert options["projects"][0]["write_capability"] is False
    assert options["limits"]["project_writes"] == 0

    controller.start_diagnostic(project.id, "How is calculate_total tested?")
    diagnostic = wait(controller)
    assert diagnostic["status"] == "COMPLETED"
    assert diagnostic["source_integrity_verified"]
    assert diagnostic["execution_authorized"] is False

    controller.start_change_plan(
        project.id,
        "Change calculate_total while preserving its tests",
        ["The existing test remains valid."],
    )
    planned = wait(controller)
    assert planned["status"] == "COMPLETED"
    assert planned["approval_status"] == "PENDING"
    assert planned["execution_authorized"] is False
    records = store.project_workspace_records()
    assert len(records) == 2
    assert records[0].kind == "DIAGNOSTIC"
    assert records[1].kind == "CHANGE_PLAN"
    assert records[1].steps and records[1].risks and records[1].validation_requirements
    assert records[1].affected_paths == ["src/service.py", "tests/test_service.py"]
    assert root.joinpath("src/service.py").read_text(encoding="utf-8").endswith("value * 2\n")


def test_workspace_project_documents_are_loaded_from_project_files(tmp_path: Path) -> None:
    root, store = generic_fixture(tmp_path)
    (root / "manifest.md").write_text("# File-backed manifest\n", encoding="utf-8")
    (root / "goals.json").write_text(
        '[{"title": "Ship", "goal": "Release the first version."}]\n',
        encoding="utf-8",
    )

    project = InteractiveProjectWorkspaceController(store).options()["projects"][0]

    assert project["project_manifest"] == "# File-backed manifest\n"
    assert project["project_goals"] == [
        {"title": "Ship", "goal": "Release the first version."}
    ]


def test_change_plan_does_not_authorize_files_for_generic_create_symbol(tmp_path: Path) -> None:
    root, store = generic_fixture(tmp_path)
    (root / "dashboard").mkdir()
    (root / "dashboard/page.tsx").write_text("export default function Page() {}\n", encoding="utf-8")
    (root / "src/create.py").write_text("def create():\n    pass\n", encoding="utf-8")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    project = store.projects()[0]
    controller = InteractiveProjectWorkspaceController(store)

    controller.start_change_plan(project.id, "Create a Savings page", ["Savings is visible."])
    assert wait(controller)["status"] == "COMPLETED"

    assert store.project_workspace_records()[-1].affected_paths == ["dashboard/page.tsx"]




def test_workspace_refreshes_stale_index_before_read_only_work(tmp_path: Path) -> None:
    root, store = generic_fixture(tmp_path)
    project = store.projects()[0]
    controller = InteractiveProjectWorkspaceController(store)
    source = root / "src/service.py"
    source.write_text(source.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    previous_scan = project.latest_scan_id
    controller.start_diagnostic(project.id, "How is calculate_total tested?")
    completed = wait(controller)

    assert completed["status"] == "COMPLETED"
    assert store.projects()[0].latest_scan_id != previous_scan
    assert store.project_workspace_records()[0].source_integrity_verified
