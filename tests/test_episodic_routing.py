from types import SimpleNamespace

import pytest

from rlmgraph.episodic_recall import retrieve_episodes
from rlmgraph.models import (
    ChatScope,
    ChatSession,
    ChatTurn,
    ConversationInterpretation,
    ConversationResponse,
    ConversationRouteReview,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


def turn(session, ordinal, user, answer):
    return ChatTurn(
        session_id=session.id,
        ordinal=ordinal,
        user_message=user,
        answer=answer,
        scope=ChatScope.SYSTEM,
        route="RLM_CONVERSATION",
        routing_confidence=1,
    )


class Reviewer:
    def __init__(self, cue, reply, mode="CONVERSE", initial_intent="INVESTIGATE"):
        self.cue, self.reply, self.mode = cue, reply, mode
        self.initial_intent = initial_intent
        self.reviews = 0

    def interpret_conversation(self, message, memory):
        return ConversationInterpretation(
            speech_act="QUESTION",
            primary_intent=self.initial_intent,
            user_meaning="Investigate whether this exists in the repository.",
            confidence=0.6,
            needs_clarification=self.initial_intent == "INVESTIGATE",
            memory_query=self.cue,
        )

    def review_conversation_route(self, message, memory, interpretation):
        self.reviews += 1
        assert memory.architecture_contexts == []
        assert memory.active_objective is None
        matches = [item for item in memory.verbatim_turns if self.cue in item.user_message]
        assert matches
        assert all("foreign-secret" not in item.user_message for item in memory.verbatim_turns)
        return ConversationRouteReview(
            intent=self.mode,
            user_meaning="Respond using the convention established in dialogue.",
            source_turn_ids=[matches[0].turn_id],
            clarification="Could you remind me of the intended response?",
        )

    def respond_conversation(self, message, memory, interpretation):
        assert interpretation.workflow_request is None
        assert any(self.reply in item.assistant_answer for item in memory.verbatim_turns)
        return ConversationResponse(answer=self.reply, confidence=0.95)


@pytest.mark.parametrize(
    "cue,reply",
    [("copper lantern", "the harbor is open"), ("quiet comet", "bring the blue notebook")],
)
@pytest.mark.parametrize("initial_intent", ["INVESTIGATE", "VERIFY", "REPLAY"])
def test_shared_convention_recovered_from_original_dialogue_without_worker(
    tmp_path, monkeypatch, cue, reply, initial_intent
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    old = ChatSession(profile_id="LOCAL-LEGACY")
    foreign = ChatSession(profile_id="FOREIGN")
    store.save_chat_session(old)
    store.save_chat_session(foreign)
    store.save_chat_turn(
        turn(old, 1, f"Let's establish a shared phrase: {cue}.", "What response should I use?")
    )
    store.save_chat_turn(
        turn(old, 2, f"Respond with {reply} when I use that phrase.", f"Agreed: {reply}")
    )
    for index in range(3, 23):
        store.save_chat_turn(turn(old, index, f"Schedule note number {index}", "Recorded"))
    store.save_chat_turn(turn(foreign, 1, f"foreign-secret {cue}", "wrong response"))
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    current = ChatSession(profile_id="LOCAL-LEGACY")
    store.save_chat_session(current)
    mistaken = turn(
        current, 1, f"What if I said {cue}?",
        "No. There is no repository artifact or test establishing that convention.",
    )
    mistaken.route = "RLM_INVESTIGATION"
    mistaken.claim_id = "CLAIM-misleading-prior"
    store.save_chat_turn(mistaken)
    reviewer = Reviewer(cue, reply, initial_intent=initial_intent)
    chat = ObserverChat(store, interpreter=reviewer)
    chat._verify_follow_up = lambda *args, **kwargs: pytest.fail("Do not verify a mistaken answer")
    chat._exact_follow_up = lambda *args, **kwargs: pytest.fail("Do not replay a mistaken answer")
    chat.recursive_supervisor.run = lambda *args, **kwargs: pytest.fail(
        "No repository investigation"
    )
    result = chat.reply(f"What if I said {cue}?", [], None, None, current.id)
    assert result["answer"] == reply
    assert result["route"] == "RLM_CONVERSATION"
    assert reviewer.reviews == 1
    saved = store.conversation_interpretations(result["session_id"])[-1]
    assert saved.routing_review.intent == "CONVERSE"
    reviewer.mode = "CLARIFY"
    result = chat.reply("What does that imply?", [], None, None, result["session_id"])
    assert result["route"] == "RLM_CONVERSATION_CLARIFICATION"
    assert reviewer.reviews == 2  # At most one review per incoming message.
    reviewer.mode = "INVESTIGATE"
    result = chat.reply("And then?", [], None, None, result["session_id"])
    assert result["route"] == "RLM_CONVERSATION_CLARIFICATION"  # Missing current work quote.

    from rlmgraph.intent import IntentRouter, MessageIntent

    reviewer.review_conversation_route = lambda message, memory, interpretation: (
        ConversationRouteReview(
            intent="INVESTIGATE",
            user_meaning="Inspect the requested repository file.",
            requested_work_quote=message,
        )
    )
    message = "Inspect the repository parser and explain its failure handling."
    _, intent, _ = chat._interpret(
        result["session_id"],
        message,
        store.chat_turns(result["session_id"]),
        IntentRouter.classify(message),
    )
    assert intent.intent == MessageIntent.INVESTIGATE

    # Deliberate requests still reach their respective prior-turn handlers after review.
    for route, message, handler in [
        ("VERIFY", "Please verify your previous claim.", "_verify_follow_up"),
        ("REPLAY", "Repeat your last answer exactly.", "_exact_follow_up"),
    ]:
        reviewer.initial_intent = route
        reviewer.review_conversation_route = lambda message, memory, interpretation: (
            ConversationRouteReview(
                intent=interpretation.primary_intent,
                user_meaning="Explicit request concerning the prior answer.",
                requested_work_quote=message,
            )
        )
        calls = []

        def prior_handler(*args, recorded_calls=calls, reviewed_route=route, **kwargs):
            recorded_calls.append(args)
            return {"answer": "Requested prior answer operation", "route": reviewed_route,
                    "scope": "SYSTEM", "routing_confidence": 1.0}

        monkeypatch.setattr(chat, handler, prior_handler)
        latest = store.chat_turns(current.id)[-1]
        latest.claim_id = mistaken.claim_id
        store.save_chat_turn(latest)
        result = chat.reply(message, [], None, None, current.id)
        assert result["route"] == route
        assert len(calls) == 1

        reviewer.review_conversation_route = lambda message, memory, interpretation: (
            ConversationRouteReview(intent=interpretation.primary_intent, user_meaning="No quote")
        )
        result = chat.reply(message, [], None, None, current.id)
        assert result["route"] == "RLM_CONVERSATION_CLARIFICATION"
        assert len(calls) == 1


def test_retrieval_does_not_anchor_on_assistant_invention_and_stays_bounded():
    session = ChatSession()
    turns = [
        turn(session, 1, "Remember the glass mountain", "agreed"),
        turn(session, 2, "That should mean take a break", "take a break"),
        turn(session, 3, "Unrelated", "I invented a glass mountain claim"),
    ]
    result = retrieve_episodes(turns, "glass mountain", "other", max_characters=120)
    assert result[0].turn_id == turns[0].id
    assert sum(len(item.user_message) + len(item.assistant_answer) for item in result) <= 120


def test_repeated_cues_do_not_crowd_out_the_original_exchange():
    session = ChatSession()
    original = turn(
        session,
        1,
        "When I mention a velvet compass, remind me to consider alternatives.",
        "Consider alternatives.",
    )
    turns = [original] + [turn(session, i, "A velvet compass?", "Uncertain") for i in range(2, 20)]
    result = retrieve_episodes(turns, "A velvet compass?", session.id)
    assert original.id in {item.turn_id for item in result}


def test_retry_replaces_only_after_success_and_filters_memory(tmp_path, monkeypatch):
    from rlmgraph.models import ConversationFact

    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    session = ChatSession(profile_id="owner")
    store.save_chat_session(session)
    previous = turn(session, 1, "A velvet compass?", "Misleading repository answer")
    store.save_chat_turn(previous)
    fact = ConversationFact(session_id=session.id, kind="CONTEXT", subject="cue",
                            predicate="means", value="Misleading finding",
                            source_turn_id=previous.id, source_interpretation_id="old", confidence=1)
    store.save_conversation_fact(fact)
    chat = ObserverChat(store, interpreter=Reviewer("velvet compass", "Consider alternatives"))

    def replacement(*args, **kwargs):
        return chat._persist(session, previous.user_message,
                             {"answer": "Consider alternatives", "route": "RLM_CONVERSATION"})

    monkeypatch.setattr(chat, "safe_reply", replacement)
    with pytest.raises(ValueError):
        chat.retry_answer(session.id, previous.id, profile_id="foreign")
    result = chat.retry_answer(session.id, previous.id, profile_id="owner")
    assert result["replaces_turn_id"] == previous.id
    assert len(store.chat_turns(session.id)) == 2  # Compact audit history retained.
    assert [item.id for item in chat._turns(session.id)] == [result["turn_id"]]

    assert chat.conversation_memory._all_facts(session.id) == []
    excerpts = retrieve_episodes(store.chat_turns(session.id), "velvet compass", session.id)
    assert [item.turn_id for item in excerpts] == [result["turn_id"]]
    with pytest.raises(ValueError):
        chat.retry_answer(session.id, previous.id, profile_id="owner")

    monkeypatch.setattr(chat, "safe_reply", lambda *args, **kwargs: chat._persist(
        session, previous.user_message, {"answer": "Unavailable", "route": "RLM_RECOVERY"}
    ))
    failed = chat.retry_answer(session.id, result["turn_id"], profile_id="owner")
    assert "replaces_turn_id" not in failed
    assert [item.id for item in chat._turns(session.id)] == [result["turn_id"]]
    monkeypatch.setattr(chat, "safe_reply", replacement)
    recovered = chat.retry_answer(session.id, result["turn_id"], profile_id="owner")
    assert recovered["replaces_turn_id"] == result["turn_id"]
    assert len(store.chat_turns(session.id)) == 4
    assert [item.ordinal for item in store.chat_turns(session.id)] == [1, 2, 3, 4]


def test_draft_is_checked_before_response_or_memory_commit(tmp_path):
    from rlmgraph.models import ConversationMemoryProjection

    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SimpleNamespace(
        respond_conversation=lambda *args: ConversationResponse(answer="Wrong draft", confidence=1),
        review_conversation_answer=lambda *args: ConversationResponse(answer="Checked answer", confidence=1),
    )
    chat = ObserverChat(store, interpreter=interpreter)
    interpretation = ConversationInterpretation(speech_act="QUESTION", primary_intent="CONVERSE",
                                               user_meaning="Shared convention", confidence=1)
    memory = ConversationMemoryProjection(session_id="test")
    result = chat._conversation_reply(interpretation, None, None, "A velvet compass?", memory)
    assert result["answer"] == "Checked answer"
    assert result["conversation_answer_reviewed"] is True

    def unavailable(*args):
        raise RuntimeError("Review unavailable")

    interpreter.review_conversation_answer = unavailable
    result = chat._conversation_reply(interpretation, None, None, "A velvet compass?", memory)
    assert result["route"] == "RLM_RECOVERY"
    assert "Wrong draft" not in result["answer"]


pytestmark = pytest.mark.usefixtures("offline_chat_adapter")
