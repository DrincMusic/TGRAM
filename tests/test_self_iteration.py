from pathlib import Path
from types import SimpleNamespace

import pytest

from rlmgraph.models import (
    ChatScope,
    ChatSession,
    ConversationInterpretation,
    ConversationWorkRequest,
    ConversationWorkResult,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.self_iteration import SelfIterationManager
from rlmgraph.store import SQLiteGraphStore


def _completed_investigation(store, session_id="SESSION-SELF"):
    request = ConversationWorkRequest(
        session_id=session_id,
        source_interpretation_id="INTERPRETATION-1",
        exact_user_prompt="Why does RLMGraph lose conversational context?",
        objective="Prevent RLMGraph from losing conversational context.",
        scope=ChatScope.SYSTEM,
    )
    result = ConversationWorkResult(
        request_id=request.id, session_id=session_id, task_id="TASK-SELF",
        claim_ids=["CLAIM-SELF"], answer_summary="The context handoff drops facts.",
        confidence=.9, worker_trace_id="TASK-SELF",
    )
    request.status = "COMPLETED"
    store.save_conversation_work_request(request)
    store.save_conversation_work_result(result)
    return request, result


def test_self_improvement_proposal_is_claim_linked_durable_and_non_executing(tmp_path):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    request, result = _completed_investigation(store)

    proposal = SelfIterationManager(store, tmp_path).propose_latest(request.session_id)

    assert proposal.status == "DRAFT"
    assert proposal.work_request_id == request.id
    assert proposal.work_result_id == result.id
    assert proposal.source_claim_ids == ["CLAIM-SELF"]
    assert proposal.objective == request.objective
    assert proposal.ticket_id is None
    assert len(proposal.acceptance_criteria) == 2
    reopened = SQLiteGraphStore(tmp_path / "memory.db")
    assert reopened.self_improvement_proposals() == [proposal]
    assert reopened.project_tickets() == []


def test_explicit_acceptance_uses_ordinary_ticket_manager_without_authorizing_execution(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    request, _ = _completed_investigation(store)
    store.save_chat_session(ChatSession(id=request.session_id))
    project = SimpleNamespace(
        id="PROJECT-SELF", root=str(tmp_path), read_only=True, explicitly_selected=True,
    )
    store.projects = lambda: [project]
    proposal = SelfIterationManager(store, tmp_path).propose_latest(request.session_id)
    captured = {}
    ticket = SimpleNamespace(id="TICKET-SELF", project_id=project.id, status="DRAFT")

    class FakeTickets:
        def __init__(self, supplied_store):
            assert supplied_store is store

        def create(self, **kwargs):
            captured.update(kwargs)
            return ticket

    monkeypatch.setattr("rlmgraph.self_iteration.TicketManager", FakeTickets)
    manager = SelfIterationManager(store, Path(tmp_path))

    accepted, created = manager.accept(proposal.id, "human-user", "I approve these criteria.")

    assert created is ticket
    assert accepted.status == "ACCEPTED"
    assert accepted.ticket_id == ticket.id
    assert accepted.accepted_by == "human-user"
    assert captured["source_claim_ids"] == ["CLAIM-SELF"]
    assert captured["acceptance_criteria"] == proposal.acceptance_criteria
    assert captured["created_by"] == "human-user"
    assert ticket.status == "DRAFT"
    with pytest.raises(ValueError, match="Only a draft"):
        manager.accept(proposal.id, "human-user", "again")


def test_proposal_rejects_project_scope_or_missing_claim(tmp_path):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    request = ConversationWorkRequest(
        session_id="S", source_interpretation_id="I", exact_user_prompt="Inspect it",
        objective="Inspect it", scope=ChatScope.PROJECT, project_id="P",
    )
    result = ConversationWorkResult(
        request_id=request.id, session_id="S", task_id="T", claim_ids=[],
        answer_summary="No claim", confidence=0, worker_trace_id="T",
    )
    store.save_conversation_work_request(request)
    store.save_conversation_work_result(result)

    with pytest.raises(ValueError, match="system investigation"):
        SelfIterationManager(store, tmp_path).propose_latest("S")


def test_explicit_chat_command_drafts_proposal_without_starting_worker(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    request, _ = _completed_investigation(store)
    store.save_chat_session(ChatSession(id=request.session_id))

    class Interpreter:
        def interpret_conversation(self, message, memory):
            return ConversationInterpretation(
                speech_act="DIRECTIVE", primary_intent="CHANGE",
                user_meaning="Draft a proposal from the prior investigation.", confidence=.95,
            )

    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    chat = ObserverChat(store, interpreter=Interpreter(), system_root=tmp_path)
    failure = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("proposal drafting must not start a worker")
    )
    chat.supervisor.run = failure
    chat.recursive_supervisor.run = failure

    result = chat.reply(
        "propose an improvement based on the latest investigation",
        [], None, None, request.session_id,
    )

    assert result["route"] == "RLM_SELF_IMPROVEMENT_PROPOSAL"
    assert result["authority"] == "DRAFT_PROPOSAL_NO_EXECUTION_AUTHORITY"
    assert result["ticket_id"] is None
    assert result["self_improvement_proposal"]["status"] == "DRAFT"
    assert store.project_tickets() == []
