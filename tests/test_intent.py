from types import SimpleNamespace

import pytest

from rlmgraph.intent import IntentRouter, MessageIntent
from rlmgraph.models import (
    ChatSession,
    ConversationInterpretation,
    DeductivePremise,
    DeductiveTheory,
    SelfAssessmentReport,
    WeaknessCandidate,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


class _Store:
    def projects(self): return []
    def chat_sessions(self): return []
    def chat_turns(self, session_id): return []
    def save_chat_session(self, session): pass
    def save_chat_turn(self, turn): pass


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    return ObserverChat(_Store())


def test_intent_router_separates_change_from_repository_scope() -> None:
    result = IntentRouter.classify("Fix the startup crash and run its tests")
    assert result.intent == MessageIntent.CHANGE
    assert result.confidence >= .8


def test_intent_router_recognizes_greeting_without_inventing_work() -> None:
    result = IntentRouter.classify("Hello!")
    assert result.intent == MessageIntent.CONVERSE
    assert "not a workflow" in result.rationale


def test_intent_router_treats_project_identity_as_context_not_work() -> None:
    result = IntentRouter.classify("this project is RLMGraph")
    assert result.intent == MessageIntent.CONVERSE
    assert "requests no action" in result.rationale


def test_intent_router_treats_project_context_recall_as_conversation() -> None:
    result = IntentRouter.classify("what project are we discussing?")
    assert result.intent == MessageIntent.CONVERSE
    assert "recall conversational context" in result.rationale


def test_intent_router_keeps_project_opinion_question_out_of_worker_pipeline() -> None:
    result = IntentRouter.classify("what are your thoughts on this project?")
    assert result.intent == MessageIntent.CONVERSE
    assert "conversational discussion" in result.rationale


def test_intent_router_treats_self_memory_question_as_conversation() -> None:
    result = IntentRouter.classify("how does your memory system work?")
    assert result.intent == MessageIntent.CONVERSE
    assert "typed memory state" in result.rationale


def test_intent_router_treats_self_identity_as_conversation() -> None:
    result = IntentRouter.classify("what are you?")
    assert result.intent == MessageIntent.CONVERSE
    assert "typed identity" in result.rationale


@pytest.mark.parametrize("message", [
    "what is your biggest weakness?",
    "what is your biggest weakness right now?",
    "what do you think your biggest weakness is?",
    "what do you see as your main limitation?",
    "what are your current limitations?",
    "where do you fail?",
    "how reliable are you?",
    "can you actually iterate on yourself?",
])
def test_intent_router_requires_evidence_for_current_self_assessment(message) -> None:
    result = IntentRouter.classify(message)
    assert result.intent == MessageIntent.INVESTIGATE
    assert result.confidence == .99
    assert "requires source, test, or runtime evidence" in result.rationale


def test_self_assessment_cannot_be_downgraded_to_conversation_or_dummy_project(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()

    class ConversationalInterpreter:
        def interpret_conversation(self, message, memory):
            return ConversationInterpretation(
                speech_act="OPINION", primary_intent="CONVERSE",
                user_meaning="Offer a conversational self-assessment.", confidence=.96,
            )

    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    chat = ObserverChat(store, interpreter=ConversationalInterpreter(), system_root=tmp_path)
    captured = {}
    claim = SimpleNamespace(
        id="CLAIM-SELF-ASSESSMENT", conclusion="Evidence-backed limitation.",
        confidence=.82, evidence=[], unresolved_questions=[],
    )
    task = SimpleNamespace(id="TASK-SELF-ASSESSMENT", reuse_type=None)

    def investigate(question, root, force_investigation=False):
        captured.update(question=question, root=root, forced=force_investigation)
        return SimpleNamespace(claim=claim, task=task, cache_hit=False, sub_tasks=[])

    chat.recursive_supervisor.run = investigate

    response = chat.reply(
        "what is your biggest weakness?", [], "PROJECT-DUMMY", None
    )

    assert response["route"] == "RLM_SYSTEM_INVESTIGATION"
    assert response["scope"] == "SYSTEM"
    assert response["project_id"] is None
    assert response["claim_id"] == claim.id
    assert response["work_bridge_request_id"]
    assert captured["forced"] is True
    assert store.conversation_work_requests(response["session_id"])[0].scope.value == "SYSTEM"


def test_self_assessment_answers_immediately_from_persisted_deductive_memory(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    store.save_chat_session(ChatSession(id="SESSION-OLD"))
    theory = DeductiveTheory(
        session_id="SESSION-OLD", subject="weakness.memory_recall",
        premises=[DeductivePremise(
            source_id="CLAIM-OLD", source_kind="EVIDENCE_CLAIM",
            statement="Cross-session recall previously failed.", confidence=.88,
        )],
        inference_rule="FAILED_RECALL_IMPLIES_MEMORY_WEAKNESS",
        conclusion="Memory recall is the strongest observed weakness.", confidence=.88,
        falsifiers=["Repeated cross-session recall succeeds."],
        source_claim_ids=["CLAIM-OLD"],
    )
    store.save_deductive_theory(theory)
    candidate = WeaknessCandidate(
        category="MEMORY_RECALL", description=theory.conclusion, theory_id=theory.id,
        evidence_strength=.88, impact=.9, recurrence=.8, unresolvedness=.7, severity=.84,
    )
    report = SelfAssessmentReport(
        session_id="SESSION-OLD", work_result_id="WORK-OLD",
        source_claim_ids=["CLAIM-OLD"], candidates=[candidate],
        selected_candidate_id=candidate.id, conclusion=theory.conclusion, confidence=.88,
    )
    store.save_self_assessment_report(report)

    class Interpreter:
        def interpret_conversation(self, message, memory):
            return ConversationInterpretation(
                speech_act="QUESTION", primary_intent="INVESTIGATE",
                user_meaning="Ask for the strongest current weakness.",
                proposed_scope="SYSTEM", confidence=.99,
            )

    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    chat = ObserverChat(store, interpreter=Interpreter(), system_root=tmp_path)
    chat.recursive_supervisor.run = lambda *args, **kwargs: pytest.fail(
        "persisted self-assessment should answer without synchronous investigation"
    )

    response = chat.reply("what is your biggest weakness?", [], None, None)

    assert response["route"] == "RLM_DEDUCTIVE_MEMORY_RECALL"
    assert "memory recall" in response["answer"].casefold()
    assert response["deductive_theory_ids"] == [theory.id]


def test_intent_router_normalizes_hostile_whitespace_and_nuls() -> None:
    result = IntentRouter.classify("  why\x00\n\n does\tstartup fail?  ")
    assert result.intent == MessageIntent.INVESTIGATE
    assert result.normalized_message == "why does startup fail?"


def test_intent_router_turns_non_text_and_oversized_input_into_clarification() -> None:
    assert IntentRouter.classify(None).intent == MessageIntent.CLARIFY
    result = IntentRouter.classify({"unexpected": "object"})
    assert result.intent == MessageIntent.CLARIFY
    assert "dict" in result.rationale
    assert IntentRouter.classify("x" * 4_001).intent == MessageIntent.CLARIFY


def test_safe_chat_returns_recoverable_envelope_instead_of_raising(chat) -> None:
    result = chat.safe_reply(" ", [], None, None)
    assert result["route"] == "RLM_RECOVERY"
    assert result["recoverable"] is True
    assert result["intent"] == "CLARIFY"
    assert "rephrase" in result["answer"]


def test_safe_chat_contains_worker_outage(chat) -> None:
    chat.recursive_supervisor.run = lambda *args, **kwargs: (_ for _ in ()).throw(
        TimeoutError("worker deadline exceeded")
    )
    result = chat.safe_reply("How does RLMGraph route requests?", [], None, None)
    assert result["route"] == "RLM_RECOVERY"
    assert result["intent"] == "INVESTIGATE"
    assert "worker deadline exceeded" in result["error"]


def test_unsupported_model_is_a_configuration_error(chat):
    detail = "The 'gpt-5.4' model is not supported when using Codex with a ChatGPT account."
    result = chat._recovery_response(detail, IntentRouter.classify("Investigate this project"))
    assert result["operation_route"] == "MODEL_CONFIGURATION_ERROR"
    assert "retry the same request" in result["answer"]
    assert "split it" not in result["answer"]
    assert result["error"] == detail
