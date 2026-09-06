from types import SimpleNamespace

import pytest

from rlmgraph.automatic_tickets import AutomaticTicketRunner
from rlmgraph.conversation_tasks import ConversationTaskController
from rlmgraph.models import ProjectExecutionMode, ProjectRecord, ProjectScan
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


class Workspace:
    def __init__(self):
        self.calls = []
        self.state = {"status": "IDLE"}

    def snapshot(self):
        return self.state

    def start_change_plan(self, *args):
        self.calls.append(args)
        self.state = {"status": "RUNNING", "ticket_id": args[3], "stage": "Reading project files"}


class Automatic:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"status": "IDLE"}

    def start(self, project_id, ticket_id=None):
        self.calls.append((project_id, ticket_id))


@pytest.fixture
def setup(tmp_path):
    store = SQLiteGraphStore(tmp_path / "tasks.db")
    store.initialize()
    project = ProjectRecord(id="P1", root=str(tmp_path), explicitly_selected=True)
    store.save_project_snapshot(
        project,
        ProjectScan(project_id="P1", root=str(tmp_path), read_only_verified=True),
        [],
        [],
        [],
        [],
    )
    tickets, workspace, automatic = TicketManager(store), Workspace(), Automatic()
    return store, project, ConversationTaskController(store, tickets, workspace, automatic)


def test_protected_request_starts_real_ticket_planning_and_status(setup):
    store, _, controller = setup
    result = controller.handle("start working on Fix the export button", "P1", None, "USER")
    assert result["ticket_id"]
    assert "plan approval" in result["answer"]
    assert len(controller.workspace.calls) == 1
    assert controller.tickets.get(result["ticket_id"]).status == "ACTIVE"
    again = controller.handle("start working on Fix the export button", "P1", None, "USER")
    assert "duplicate" in again["answer"]
    assert len(store.project_tickets()) == 1
    assert len(controller.workspace.calls) == 1
    status = controller.handle("task status", "P1", result["ticket_id"], "USER")
    assert "Reading project files" in status["answer"]


@pytest.mark.parametrize("message", [
    "can you update the front end of TGRAM to where the chat is better than what it is right now?",
    "Please redesign TGRAM's chat composer to make it easier to use.",
    "Fix TGRAM's chat layout.",
])
def test_semantic_change_enters_task_workflow_for_tgram_source(setup, message):
    from rlmgraph.models import ConversationInterpretation, ConversationRouteReview
    from rlmgraph.observer_chat import ObserverChat

    store, project, controller = setup
    interpreter = SimpleNamespace(
        interpret_conversation=lambda *args: ConversationInterpretation(
            speech_act="DIRECTIVE", primary_intent="CHANGE", user_meaning=message,
            workflow_request=message, confidence=1,
        ),
        review_conversation_route=lambda *args: ConversationRouteReview(
            intent="CHANGE", user_meaning=message, requested_work_quote=message,
        ),
    )
    chat = ObserverChat(store, system_root=project.root, interpreter=interpreter,
                        task_controller=controller)
    chat.recursive_supervisor.run = lambda *args, **kwargs: pytest.fail("Change must not become read-only findings")
    result = chat.reply(message, [], "unrelated-selected-project", None)
    assert result["route"] == "RLM_CONVERSATION_TASK"
    assert result["project_id"] == project.id
    assert controller.tickets.get(result["ticket_id"]).description == message
    assert len(controller.workspace.calls) == 1
    assert "plan approval" in result["answer"]
    repeated = chat.reply(message, [], None, None, result["session_id"])
    assert repeated["ticket_id"] == result["ticket_id"]
    assert len(controller.workspace.calls) == 1

    chat.system_root = chat.system_root / "unconnected-source"
    unavailable = chat.reply(message, [], project.id, None)
    assert "connect its source folder" in unavailable["answer"]
    assert len(controller.workspace.calls) == 1


def test_autonomous_request_only_dispatches_the_named_ticket(setup):
    store, project, controller = setup
    project.execution_mode = ProjectExecutionMode.AUTONOMOUS_SANDBOX
    store.save_project_snapshot(
        project,
        ProjectScan(project_id="P1", root=project.root, read_only_verified=True),
        [],
        [],
        [],
        [],
    )
    result = controller.handle("start working on Fix export", "P1", None, "USER")
    assert controller.automatic.calls == [("P1", result["ticket_id"])]
    assert controller.tickets.get(result["ticket_id"]).status == "READY"
    runner = AutomaticTicketRunner(store, controller.workspace, None, controller.tickets)
    runner._target_ticket_id = "another-ticket"
    assert runner._ready("P1") == []
    runner._target_ticket_id = result["ticket_id"]
    assert [ticket.id for ticket in runner._ready("P1")] == [result["ticket_id"]]


def test_missing_project_and_questions_do_not_create_tasks(setup):
    store, _, controller = setup
    assert controller.handle("Can you work inside Atlas project?", "P1", None, "USER") is None
    assert controller.handle("How would you fix export?", "P1", None, "USER") is None
    result = controller.handle("start working on Fix export in project Missing", "P1", None, "USER")
    assert "matching Missing" in result["answer"]
    assert not store.project_tickets()


def test_start_failure_preserves_ticket_without_claiming_started(setup, monkeypatch):
    store, _, controller = setup

    def fail(*args):
        raise RuntimeError("Index needs refreshing")

    monkeypatch.setattr(controller.workspace, "start_change_plan", fail)
    result = controller.handle("start working on Fix export", "P1", None, "USER")
    assert "could not start" in result["answer"]
    assert len(store.project_tickets()) == 1


def test_observer_dispatches_and_recalls_task_without_interpreter(setup, monkeypatch):
    from rlmgraph.observer_chat import ObserverChat

    store, _, controller = setup
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    chat = ObserverChat(store, task_controller=controller)
    monkeypatch.setattr(chat, "_interpret", lambda *args: pytest.fail("No model routing needed"))
    result = chat.reply("start working on Fix export", [], "P1", None)
    status = chat.reply(
        "task status", [], "different-selected-project", "different-ticket", result["session_id"]
    )
    assert status["ticket_id"] == result["ticket_id"]
    assert store.chat_turns(result["session_id"])[0].ticket_id == result["ticket_id"]


def test_direct_fix_request_preserves_action_and_selected_task_reuses_ticket(setup):
    store, _, controller = setup
    result = controller.handle("Can you fix the export button?", "P1", None, "USER")
    ticket = controller.tickets.get(result["ticket_id"])
    assert ticket.description == "fix the export button"
    repeated = controller.handle("start this task", "P1", ticket.id, "USER")
    assert repeated["ticket_id"] == ticket.id
    assert len(store.project_tickets()) == 1


pytestmark = pytest.mark.usefixtures("offline_chat_adapter")
