from types import SimpleNamespace

from rlmgraph.autonomous_tasks import AutonomousTaskManager
from rlmgraph.models import ConceptBranch, ConceptBranchOutcome, ConversationInterpretation
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


def _outcome(store, session_id="SESSION-1"):
    branch = ConceptBranch(
        session_id=session_id, signature="branch:memory", concept="memory topology",
        insight="The topology may lose provenance.", origin_interpretation_id="I-1",
        supporting_fact_ids=["F-1", "F-2"], confidence=.7, depth=1,
    )
    outcome = ConceptBranchOutcome(
        session_id=session_id, branch_id=branch.id, inquiry_id="INQUIRY-1",
        work_result_id="RESULT-1", claim_ids=["CLAIM-1"], status="CHALLENGED",
        summary="One provenance edge is missing.", confidence=.8,
    )
    store.save_concept_branch(branch)
    store.save_concept_branch_outcome(outcome)
    return branch, outcome


def test_task_preparation_is_opt_in_and_blocks_without_registered_project(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    _outcome(store)
    manager = AutonomousTaskManager(store, tmp_path)

    try:
        manager.prepare_latest("SESSION-1")
        raise AssertionError("preparation should require explicit opt-in")
    except ValueError as exc:
        assert "not enabled" in str(exc)

    policy = manager.enable("SESSION-1", "human-user")
    task, plan = manager.prepare_latest("SESSION-1")

    assert policy.enabled is True
    assert policy.allow_source_writes is False
    assert policy.allow_self_approval is False
    assert task.status == "BLOCKED"
    assert "not explicitly registered" in task.blocker
    assert plan is None


def test_evidence_outcome_creates_ordinary_draft_ticket_and_unapproved_plan(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    branch, outcome = _outcome(store)
    project = SimpleNamespace(
        id="PROJECT-1", root=str(tmp_path), read_only=True, explicitly_selected=True,
    )
    store.projects = lambda: [project]
    captured = {}
    ticket = SimpleNamespace(
        id="TICKET-1", project_id=project.id, status="DRAFT",
        acceptance_criteria=[SimpleNamespace(description="criterion")],
        constraints=[SimpleNamespace(description="constraint")],
    )

    class FakeTickets:
        def __init__(self, supplied_store):
            assert supplied_store is store

        def create(self, **kwargs):
            captured.update(kwargs)
            return ticket

    monkeypatch.setattr("rlmgraph.autonomous_tasks.TicketManager", FakeTickets)
    manager = AutonomousTaskManager(store, tmp_path)
    manager.enable("SESSION-1", "human-user")

    task, plan = manager.prepare_latest("SESSION-1")

    assert task.branch_id == branch.id
    assert task.outcome_id == outcome.id
    assert task.status == "WAITING_FOR_USER_PLAN_APPROVAL"
    assert task.ticket_id == ticket.id
    assert plan is not None
    assert plan.status == "PROPOSED_REQUIRES_USER_APPROVAL"
    assert plan.approval_granted is False
    assert captured["created_by"] == "RLMGraph autonomous task preparation"
    assert captured["source_claim_ids"] == ["CLAIM-1"]
    assert store.autonomous_tasks("SESSION-1") == [task]
    assert store.autonomous_task_plans("SESSION-1") == [plan]


def test_chat_explicitly_enables_policy_but_does_not_invent_an_actionable_task(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()

    class Interpreter:
        def interpret_conversation(self, message, memory):
            return ConversationInterpretation(
                speech_act="COMMAND", primary_intent="CHANGE",
                user_meaning=message, confidence=.99,
            )

    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    chat = ObserverChat(store, interpreter=Interpreter(), system_root=tmp_path)

    enabled = chat.reply("enable autonomous task preparation", [], None, None)
    attempted = chat.reply(
        "start working on something useful", [], None, None, enabled["session_id"]
    )

    assert enabled["route"] == "RLM_AUTONOMOUS_TASK_POLICY"
    assert enabled["operation_route"] == "ENABLED"
    assert enabled["autonomous_work_policy"]["allow_source_writes"] is False
    assert attempted["operation_route"] == "NO_TASK_PREPARED"
    assert "No unused evidence-linked" in attempted["answer"]
    assert store.project_tickets() == []
