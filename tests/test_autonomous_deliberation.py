import time
from types import SimpleNamespace

from rlmgraph.autonomous_deliberation import AutonomousDeliberationManager
from rlmgraph.models import (
    ConceptBranch,
    ConversationInterpretation,
    ConversationWorkResult,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


def _branch(session, concept, confidence, *, parent=None, depth=1):
    return ConceptBranch(
        session_id=session,
        signature=f"signature:{concept}",
        concept=concept,
        insight=f"Insight about {concept}",
        origin_interpretation_id=f"INTERPRETATION-{concept}",
        supporting_fact_ids=[f"FACT-{concept}-1", f"FACT-{concept}-2"],
        parent_branch_id=parent,
        depth=depth,
        confidence=confidence,
    )


def test_deliberation_selects_one_branch_and_persists_explainable_scores(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    certain = _branch("SESSION-1", "well understood", .95)
    uncertain = _branch("SESSION-1", "uncertain architecture", .45)
    store.save_concept_branch(certain)
    store.save_concept_branch(uncertain)

    decision, inquiry = AutonomousDeliberationManager(store).deliberate("SESSION-1")

    assert inquiry is not None
    assert decision.selected_branch_id == uncertain.id
    assert inquiry.branch_id == uncertain.id
    assert inquiry.authorization == "READ_ONLY_INVESTIGATION"
    assert len(decision.candidates) == 2
    assert decision.candidates[0].total >= decision.candidates[1].total
    assert store.autonomous_decisions("SESSION-1") == [decision]
    assert store.autonomous_inquiries("SESSION-1") == [inquiry]


def test_completed_inquiry_links_evidence_and_branch_outcome(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    branch = _branch("SESSION-1", "memory pattern", .5)
    store.save_concept_branch(branch)
    manager = AutonomousDeliberationManager(store)
    _, inquiry = manager.deliberate("SESSION-1")
    assert inquiry is not None
    result = ConversationWorkResult(
        request_id="REQUEST-1", session_id="SESSION-1", task_id="TASK-1",
        claim_ids=["CLAIM-1"], answer_summary="The pattern is implemented.",
        confidence=.9, worker_trace_id="TASK-1",
    )

    outcome = manager.complete(inquiry, result)

    assert outcome.status == "SUPPORTED"
    assert outcome.claim_ids == ["CLAIM-1"]
    assert store.autonomous_inquiries("SESSION-1")[0].status == "COMPLETED"
    assert store.autonomous_decisions("SESSION-1")[0].status == "COMPLETED"
    assert store.concept_branch_outcomes("SESSION-1") == [outcome]


def test_deliberation_does_not_overlap_an_active_inquiry(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    branch = _branch("SESSION-1", "one question", .5)
    store.save_concept_branch(branch)
    manager = AutonomousDeliberationManager(store)
    _, first = manager.deliberate("SESSION-1")
    second_decision, second = manager.deliberate("SESSION-1")

    assert first is not None
    assert second is None
    assert second_decision.status == "ACTIVE_INQUIRY_EXISTS"


def test_chat_autonomy_cycle_stops_cleanly_when_no_branch_is_eligible(tmp_path, monkeypatch):
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
    chat = ObserverChat(store, interpreter=Interpreter())

    response = chat.reply("run autonomous cycle", [], None, None)

    assert response["route"] == "RLM_AUTONOMOUS_DELIBERATION"
    assert response["operation_route"] == "NO_ELIGIBLE_BRANCH"
    assert response["authority"] == "READ_ONLY_AUTONOMY_NO_MUTATION_AUTHORITY"
    assert store.conversation_work_requests(response["session_id"]) == []


def test_natural_conversation_queues_cycle_and_reports_what_it_is_exploring(
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
    chat = ObserverChat(store, interpreter=Interpreter())
    session = chat._session(None, None, None, "autonomy")
    branch = _branch(session.id, "uncertainty handling", .5)
    store.save_concept_branch(branch)
    monkeypatch.setattr(chat, "_launch_autonomous_inquiry", lambda inquiry_id: None)

    started = chat.reply("explore one of your ideas", [], None, None, session.id)
    status = chat.reply("what are you thinking about?", [], None, None, session.id)

    assert started["operation_route"] == "READ_ONLY_INQUIRY_QUEUED"
    assert "I chose to explore" in started["answer"]
    assert status["route"] == "RLM_AUTONOMY_CONVERSATION"
    assert "uncertainty handling" in status["answer"]
    assert "Status: QUEUED" in status["answer"]


def test_background_cycle_completes_and_conversation_reports_durable_outcome(
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
    chat = ObserverChat(store, interpreter=Interpreter())
    session = chat._session(None, None, None, "autonomy")
    store.save_concept_branch(_branch(session.id, "memory topology", .5))
    monkeypatch.setattr(chat, "_investigate", lambda *args, **kwargs: {
        "answer": "Evidence challenges part of the topology hypothesis.",
        "task_id": "TASK-AUTO", "claim_id": "CLAIM-AUTO", "claim_confidence": .7,
        "unresolved_questions": [],
    })

    chat.reply("think about something", [], None, None, session.id)
    deadline = time.monotonic() + 3
    while store.autonomous_inquiries(session.id)[0].status != "COMPLETED":
        assert time.monotonic() < deadline
        time.sleep(.01)
    report = chat.reply("what did you learn?", [], None, None, session.id)

    inquiry = store.autonomous_inquiries(session.id)[0]
    assert inquiry.status == "COMPLETED"
    assert inquiry.work_request_id
    assert inquiry.work_result_id
    assert report["operation_route"] == "AUTONOMOUS_REPORT_COMPLETED"
    assert "CHALLENGED" in report["answer"]
    assert "Evidence challenges" in report["answer"]
