import json
from pathlib import Path
from types import SimpleNamespace

from rlmgraph.adapters import CodexCliInvestigator
from rlmgraph.conversation_interpreter import MemoryInterpreter
from rlmgraph.models import (
    ChatScope,
    ChatTurn,
    ConversationConcept,
    ConversationInterpretation,
    ConversationInterpretationRecord,
    ConversationMemoryProjection,
    ConversationReference,
    ConversationRepairPatch,
    ConversationResponse,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


class SemanticInterpreter:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def interpret_conversation(self, message, memory):
        self.calls.append((message, memory))
        return next(self.results)


class ReflectiveInterpreter(SemanticInterpreter):
    def __init__(self, results, repairs):
        super().__init__(results)
        self.repairs = iter(repairs)
        self.repair_calls = []

    def repair_conversation(self, message, memory, interpretation, confusion):
        self.repair_calls.append((message, memory, interpretation, confusion))
        return next(self.repairs)


class ConversationalInterpreter(SemanticInterpreter):
    def __init__(self, results, responses):
        super().__init__(results)
        self.responses = iter(responses)
        self.response_calls = []

    def respond_conversation(self, message, memory, interpretation):
        self.response_calls.append((message, memory, interpretation))
        return next(self.responses)


def _chat(monkeypatch, store, interpreter):
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    return ObserverChat(store, interpreter=interpreter)


def test_ephemeral_meaning_controls_route_and_is_persisted_before_workflow(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="PROJECTS",
        user_meaning="The user wants the connected project registry.",
        confidence=.96,
    )])
    chat = _chat(monkeypatch, store, interpreter)

    result = chat.reply("What have I connected here?", [], None, None)

    assert result["route"] == "RLM_PROJECT_REGISTRY"
    assert result["intent"] == "PROJECTS"
    assert result["interpretation_fallback"] is False
    assert len(interpreter.calls) == 1
    records = store.conversation_interpretations(result["session_id"])
    turns = store.chat_turns(result["session_id"])
    assert records[0].turn_id == turns[0].id
    assert turns[0].interpretation_id == records[0].id
    assert records[0].interpretation.user_meaning.startswith("The user wants")
    system_architecture = interpreter.calls[0][1].architecture_contexts[0]
    assert system_architecture.scope == "SYSTEM"
    assert any(item.name == "ConversationInterpreter" for item in system_architecture.components)
    assert len(system_architecture.components) == 5
    assert "reverse memory interpreter" in system_architecture.concepts


def test_hello_passes_through_interpreter_and_memory_without_starting_workflow(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([
        ConversationInterpretation(
            speech_act="GREETING", primary_intent="CONVERSE",
            user_meaning="The user is greeting RLMGraph and has not requested work.",
            confidence=.99,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="The user now wants to know which projects are connected.",
            confidence=.95,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)
    chat.supervisor.run = lambda *args: (_ for _ in ()).throw(
        AssertionError("a greeting must not start an investigation")
    )
    chat.recursive_supervisor.run = chat.supervisor.run

    hello = chat.reply("Hello", [], None, None)

    assert hello["answer"] == "Hello! What would you like to talk about?"
    assert hello["route"] == "RLM_CONVERSATION"
    assert hello["operation_route"] == "CONVERSATIONAL_RESPONSE"
    assert hello["intent"] == "CONVERSE"
    assert "claim_id" not in hello
    records = store.conversation_interpretations(hello["session_id"])
    assert records[0].turn_id == hello["turn_id"]
    assert records[0].interpretation.speech_act == "GREETING"

    follow_up = chat.reply(
        "What is connected?", [], None, None, hello["session_id"]
    )
    assert follow_up["route"] == "RLM_PROJECT_REGISTRY"
    assert "GREETING/CONVERSE" in interpreter.calls[1][1].semantic_summary
    assert records[0].id in interpreter.calls[1][1].relevant_interpretation_ids
    assert interpreter.calls[1][1].verbatim_turns[0].user_message == "Hello"
    assert interpreter.calls[1][1].verbatim_turns[0].assistant_answer == hello["answer"]


def test_hello_still_uses_memory_when_model_interpreter_is_offline(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()

    class Offline:
        def interpret_conversation(self, message, memory):
            raise TimeoutError("offline")

    chat = _chat(monkeypatch, store, Offline())
    result = chat.reply("hello", [], None, None)
    assert result["route"] == "RLM_CONVERSATION"
    assert result["interpretation_fallback"] is True
    record = store.conversation_interpretations(result["session_id"])[0]
    assert record.interpretation.speech_act == "GREETING"
    assert record.turn_id == result["turn_id"]


def test_interpreter_gratitude_vocabulary_maps_to_natural_conversation(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="gratitude", primary_intent="CONVERSE",
        user_meaning="The user is expressing thanks.", confidence=.99,
    )])
    result = _chat(monkeypatch, store, interpreter).reply("thank you", [], None, None)
    assert result["route"] == "RLM_CONVERSATION"
    assert result["answer"] == "You’re welcome."


def test_open_ended_conversation_uses_memory_responder_not_worker_or_canned_fallback(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ConversationalInterpreter(
        [ConversationInterpretation(
            speech_act="QUESTION", primary_intent="CONVERSE",
            user_meaning="The user wants a qualitative conversational response.",
            confidence=.94,
        )],
        [ConversationResponse(
            answer="I think the project has a promising memory architecture, with routing still immature.",
            confidence=.86,
        )],
    )
    chat = _chat(monkeypatch, store, interpreter)
    chat.recursive_supervisor.run = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("conversation must not enter the worker pipeline")
    )

    result = chat.reply("what are your thoughts on this project?", [], None, None)

    assert result["route"] == "RLM_CONVERSATION"
    assert result["answer"].startswith("I think the project")
    assert result["conversation_response_generated"] is True
    assert result["conversation_response_confidence"] == .86
    assert len(interpreter.response_calls) == 1
    assert interpreter.response_calls[0][0] == "what are your thoughts on this project?"
    assert interpreter.response_calls[0][1].relevant_claim_ids == []


def test_conversational_ambiguity_does_not_enter_reflection_loop(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()

    class AmbiguousConversation(ConversationalInterpreter):
        def repair_conversation(self, *args):
            raise AssertionError("CONVERSE must not enter interpretation repair")

    interpreter = AmbiguousConversation(
        [ConversationInterpretation(
            speech_act="QUESTION", primary_intent="CONVERSE",
            user_meaning="The user wants a conversational opinion.",
            ambiguities=["How broad the requested opinion should be."],
            confidence=.7, needs_clarification=True,
        )],
        [ConversationResponse(
            answer="My high-level view is that the project’s memory separation is promising.",
            confidence=.8,
        )],
    )

    result = _chat(monkeypatch, store, interpreter).reply(
        "what are your thoughts on this project?", [], None, None
    )

    assert result["route"] == "RLM_CONVERSATION"
    assert result["reflection_steps"] == []
    assert result["conversation_response_generated"] is True


def test_opinion_question_stays_conversational_when_meaning_interpreter_times_out(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()

    class MeaningOffline:
        def interpret_conversation(self, message, memory):
            raise TimeoutError("meaning interpreter unavailable")

        def respond_conversation(self, message, memory, interpretation):
            return ConversationResponse(
                answer="I can still discuss the project from our conversational context.",
                confidence=.7,
            )

    result = _chat(monkeypatch, store, MeaningOffline()).reply(
        "what are your thoughts on this project?", [], None, None
    )

    assert result["route"] == "RLM_CONVERSATION"
    assert result["intent"] == "CONVERSE"
    assert result["conversation_response_generated"] is True
    assert result["answer"].startswith("I can still discuss")


def test_identity_question_has_useful_fallback_when_conversation_responder_is_absent(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="CONVERSE",
        user_meaning="The user asks what RLMGraph is.", confidence=.95,
    )])

    result = _chat(monkeypatch, store, interpreter).reply("what are you?", [], None, None)

    assert result["route"] == "RLM_CONVERSATION"
    assert result["answer"].startswith("TGRAM is the durable tokenized graph")
    assert result["answer"] != "I’m listening."
    assert interpreter.calls == []
    record = store.conversation_interpretations(result["session_id"])[0]
    assert record.interpreter == "RLMGraphMemoryCore"


def test_self_memory_question_is_answered_from_typed_cognitive_state(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ConversationalInterpreter(
        [ConversationInterpretation(
            speech_act="QUESTION", primary_intent="CONVERSE",
            user_meaning="The user asks how RLMGraph memory works.", confidence=.97,
        )],
        [ConversationResponse(
            answer=(
                "My durable conversation and worker memories are separate; disposable LLM calls "
                "interpret or communicate from that state."
            ),
            confidence=.93,
        )],
    )

    result = _chat(monkeypatch, store, interpreter).reply(
        "how does your memory system work?", [], None, None
    )

    assert result["route"] == "RLM_CONVERSATION"
    assert result["conversation_response_generated"] is True
    assert interpreter.calls == []
    state = interpreter.response_calls[0][1].memory_system
    assert state.identity_id == "TGRAM-SYSTEM"
    assert state.language_models_are_disposable is True
    assert state.layers[0].name == "system_workspace"
    assert interpreter.response_calls[0][1].relevant_claim_ids == []


def test_project_identity_declaration_is_remembered_without_reflection_or_workflow(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="STATEMENT", primary_intent="INVESTIGATE",
        user_meaning="The user states that the current project is RLMGraph.",
        objective_update="Treat the current project as RLMGraph in this conversation.",
        ambiguities=["Whether project means the selected repository or product."],
        confidence=.72, needs_clarification=True,
    )])
    chat = _chat(monkeypatch, store, interpreter)
    chat.supervisor.run = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("a context declaration must not start a workflow")
    )

    result = chat.reply("this project is RLMGraph", [], None, None)

    assert result["route"] == "RLM_CONVERSATION"
    assert result["answer"] == "Got it."
    assert result["intent"] == "CONVERSE"
    assert result["interpretation"]["needs_clarification"] is False
    assert result["reflection_steps"] == []
    record = store.conversation_interpretations(result["session_id"])[0]
    assert record.interpretation.objective_update.startswith("Treat the current project")


def test_unknown_model_speech_act_cannot_promote_context_declaration_to_investigation(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="PROJECT_IDENTITY_CONTEXT_SUPPLIED",
        primary_intent="INVESTIGATE",
        user_meaning="The current project is RLMGraph.",
        confidence=.8, needs_clarification=True,
        ambiguities=["The model invented an unnecessary project distinction."],
    )])
    chat = _chat(monkeypatch, store, interpreter)
    chat.recursive_supervisor.run = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("model vocabulary must not promote context into investigation")
    )

    result = chat.reply("this project is RLMGraph", [], None, None)

    assert result["route"] == "RLM_CONVERSATION"
    assert result["answer"] == "Got it."
    assert result["intent"] == "CONVERSE"
    assert result["interpretation"]["primary_intent"] == "CONVERSE"
    assert result["interpretation"]["needs_clarification"] is False
    assert result["reflection_steps"] == []


def test_interpreter_failure_falls_back_without_losing_semantic_memory(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()

    class Offline:
        def interpret_conversation(self, message, memory):
            raise TimeoutError("semantic model unavailable")

    result = _chat(monkeypatch, store, Offline()).reply(
        "List my connected projects", [], None, None
    )
    record = store.conversation_interpretations(result["session_id"])[0]
    assert result["route"] == "RLM_PROJECT_REGISTRY"
    assert result["interpretation_fallback"] is True
    assert record.fallback_used is True
    assert record.interpreter == "IntentRouterFallback"


def test_material_ambiguity_pauses_before_any_workflow(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="DIRECTIVE", primary_intent="CHANGE",
        user_meaning="Change an unresolved prior subject.",
        workflow_request="Fix it", confidence=.55, needs_clarification=True,
        ambiguities=["Does 'it' refer to the router or the selected project?"],
    )])
    chat = _chat(monkeypatch, store, interpreter)
    chat.supervisor.run = lambda *args: (_ for _ in ()).throw(
        AssertionError("workflow must not run")
    )
    result = chat.reply("Fix it", [], None, None)
    assert result["route"] == "RLM_CONVERSATION_CLARIFICATION"
    assert result["operation_route"] == "CLARIFICATION_REQUIRED"
    assert "router or the selected project" in result["answer"]
    assert result["authority"] == "READ_ONLY_CLARIFICATION_NO_WORKFLOW_AUTHORITY"


def test_confusion_does_not_launch_a_repair_interpreter(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ReflectiveInterpreter(
        [ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="The referent is uncertain.",
            references=[ConversationReference(phrase="it")],
            ambiguities=["It may refer to the connected project registry."],
            confidence=.52, needs_clarification=True,
        )],
        [ConversationRepairPatch(
            resolved_references=[ConversationReference(
                phrase="it", target_id="PROJECT-REGISTRY", target_kind="SYSTEM_COMPONENT",
                confidence=.94,
            )],
            revised_user_meaning="The user is asking about the connected project registry.",
            revised_scope="SYSTEM", remaining_ambiguities=[],
            resolution_basis=["The prompt asks what is connected; architecture context identifies the registry."],
            confidence=.94, needs_clarification=False,
        )],
    )

    result = _chat(monkeypatch, store, interpreter).reply(
        "What is connected to it?", [], None, None
    )

    assert result["route"] == "RLM_CONVERSATION_CLARIFICATION"
    assert result["interpretation"]["needs_clarification"] is True
    assert result["interpretation"]["references"][0]["target_id"] is None
    assert interpreter.repair_calls == []
    assert result["reflection_steps"] == []
    stored = store.conversation_interpretations(result["session_id"])[0]
    assert stored.message == "What is connected to it?"
    assert stored.reflection_steps == []


def test_confusion_does_not_create_reflection_history(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ReflectiveInterpreter(
        [
            ConversationInterpretation(
                speech_act="QUESTION", primary_intent="PROJECTS",
                user_meaning="The project subject is uncertain.",
                ambiguities=["Which registry is meant?"], confidence=.5,
                needs_clarification=True,
            ),
            ConversationInterpretation(
                speech_act="QUESTION", primary_intent="PROJECTS",
                user_meaning="Continue discussing connected projects.", confidence=.9,
            ),
        ],
        [ConversationRepairPatch(
            revised_user_meaning="The user means RLMGraph's connected project registry.",
            revised_scope="SYSTEM", remaining_ambiguities=[],
            resolution_basis=["Architecture context: project registry"],
            confidence=.91, needs_clarification=False,
        )],
    )
    chat = _chat(monkeypatch, store, interpreter)
    first = chat.reply("Which registry is connected?", [], None, None)
    chat.reply("What is in it?", [], None, None, first["session_id"])

    second_memory = interpreter.calls[1][1]
    assert second_memory.reflection_history == []
    assert interpreter.repair_calls == []


def test_confusion_never_uses_available_multi_pass_repairs(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    ambiguities = ["subject", "scope", "timeframe", "operation"]
    repairs = [
        ConversationRepairPatch(
            revised_user_meaning="The user means the connected project registry.",
            revised_scope="SYSTEM",
            remaining_ambiguities=ambiguities[index:],
            resolution_basis=[f"repair pass {index}"],
            confidence=.6 + index * .05,
            needs_clarification=index < 4,
        )
        for index in range(1, 5)
    ]
    interpreter = ReflectiveInterpreter(
        [ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="Several aspects remain uncertain.",
            ambiguities=ambiguities, confidence=.5, needs_clarification=True,
        )],
        repairs,
    )

    result = _chat(monkeypatch, store, interpreter).reply(
        "Which connected projects do you mean?", [], None, None
    )

    assert result["route"] == "RLM_CONVERSATION_CLARIFICATION"
    assert result["interpretation"]["needs_clarification"] is True
    assert result["reflection_steps"] == []
    assert interpreter.repair_calls == []


def test_correction_supersedes_prior_meaning_and_reverse_memory_uses_correction(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="PROJECTS",
            user_meaning="The user wants storage projects.", confidence=.9,
        ),
        ConversationInterpretation(
            speech_act="CORRECTION", primary_intent="PROJECTS",
            user_meaning="The user means connected source repositories, not storage.",
            objective_update="Discuss connected source repositories.", confidence=.95,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)
    first = chat.reply("Show those projects", [], None, None)
    second = chat.reply(
        "No, I meant source repositories", [], None, None, first["session_id"]
    )
    records = store.conversation_interpretations(first["session_id"])
    assert records[1].supersedes_interpretation_id == records[0].id
    assert "storage projects" in interpreter.calls[1][1].semantic_summary
    projection = MemoryInterpreter().reconstruct(
        first["session_id"], "What did I mean?",
        store.chat_turns(first["session_id"]), records,
    )
    assert "connected source repositories" in projection.semantic_summary
    assert "storage projects" not in projection.semantic_summary
    assert second["interpretation_id"] == records[1].id


def test_semantic_scope_routes_implicit_self_question_away_from_selected_project(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    project = SimpleNamespace(
        id="P1", root=str(tmp_path / "other"), read_only=True,
        explicitly_selected=True, latest_scan_id=None,
    )
    store.projects = lambda: [project]
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="INVESTIGATE",
        user_meaning="The user is asking about RLMGraph itself.",
        proposed_scope="SYSTEM", confidence=.93,
    )])
    chat = _chat(monkeypatch, store, interpreter)
    claim = SimpleNamespace(
        conclusion="System answer", id="C1", confidence=.9,
        evidence=[], unresolved_questions=[],
    )
    observed = []
    chat.recursive_supervisor.run = lambda question, root, **kwargs: (
        observed.append(root) or SimpleNamespace(
            claim=claim, task=SimpleNamespace(id="T1", reuse_type=None), cache_hit=False,
            sub_tasks=[],
        )
    )
    result = chat.reply("How did you decide that?", [], "P1", None)
    assert result["scope"] == "SYSTEM"
    assert result["routing_reason"] == "Scope was resolved by the ephemeral semantic interpreter."
    assert observed == [chat.system_root]


def test_self_reference_resolves_to_stable_identity_without_false_clarification(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="INVESTIGATE",
        user_meaning="The user is asking the system to reflect on itself.",
        references=[ConversationReference(
            phrase="yourself", target_id=None, target_kind="UNRESOLVED", confidence=.2,
        )],
        ambiguities=["It is unclear what 'yourself' refers to."],
        confidence=.84, needs_clarification=True,
    )])
    chat = _chat(monkeypatch, store, interpreter)
    claim = SimpleNamespace(
        conclusion="Self-reflection used current source evidence.", id="C-SELF",
        confidence=.88, evidence=[], unresolved_questions=[],
    )
    chat.recursive_supervisor.run = lambda *args, **kwargs: SimpleNamespace(
        claim=claim, task=SimpleNamespace(id="T-SELF", reuse_type=None),
        cache_hit=False, sub_tasks=[],
    )

    result = chat.reply("What do you understand about yourself?", [], None, None)

    assert result["route"] == "RLM_SYSTEM_INVESTIGATION"
    assert result["scope"] == "SYSTEM"
    assert result["interpretation"]["needs_clarification"] is False
    assert result["interpretation"]["ambiguities"] == []
    reference = result["interpretation"]["references"][0]
    assert reference["target_id"] == "TGRAM-SYSTEM"
    assert reference["target_kind"] == "SYSTEM_IDENTITY"
    assert result["memory_projection"]["system_self"]["identity_id"] == "TGRAM-SYSTEM"
    assert any(
        item["name"] == "TGRAM"
        for item in result["interpretation"]["concept_bindings"]
    )


def test_legacy_rlmgraph_identity_reference_migrates_to_tgram(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="CONVERSE",
        user_meaning="The user refers to the engine using its former identity.",
        references=[ConversationReference(
            phrase="RLMGraph", target_id="RLMGRAPH-SYSTEM",
            target_kind="SYSTEM_IDENTITY", confidence=.9,
        )],
        confidence=.95,
    )])

    result = _chat(monkeypatch, store, interpreter).reply(
        "What are your thoughts about this project?", [], None, None
    )

    reference = result["interpretation"]["references"][0]
    assert reference["target_id"] == "TGRAM-SYSTEM"
    assert reference["confidence"] == .99


def test_reverse_memory_interpreter_selects_semantics_not_raw_transcript():
    session_id = "SESSION-1"
    turn = ChatTurn(
        id="TURN-1", session_id=session_id, ordinal=1, user_message="raw private prose",
        answer="answer", scope=ChatScope.SYSTEM, route="TEST", routing_confidence=1,
        claim_id="CLAIM-1",
    )
    record = ConversationInterpretationRecord(
        id="INTERPRETATION-1", session_id=session_id, turn_id=turn.id,
        message=turn.user_message, interpreter="test",
        interpretation=ConversationInterpretation(
            speech_act="CORRECTION", primary_intent="CHANGE",
            user_meaning="The parser objective now prioritizes conversational meaning.",
            objective_update="Preserve conversational meaning before workflow routing.",
            workflow_request="Update the parser conversation boundary.",
            ambiguities=["Whether historical turns require migration."], confidence=.9,
        ),
    )
    projection = MemoryInterpreter().reconstruct(
        session_id, "What about the parser objective?", [turn], [record]
    )
    assert projection.active_objective == record.interpretation.objective_update
    assert projection.pending_workflow_request == record.interpretation.workflow_request
    assert projection.relevant_claim_ids == ["CLAIM-1"]
    assert "raw private prose" not in projection.semantic_summary
    assert projection.verbatim_turns[0].user_message == "raw private prose"
    assert projection.verbatim_turns[0].assistant_answer == "answer"
    assert projection.token_estimate > 0


def test_complete_multiline_prompt_survives_interpretation_storage_and_workflow(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = SemanticInterpreter([ConversationInterpretation(
        speech_act="DIRECTIVE", primary_intent="INVESTIGATE",
        user_meaning="Investigate both exact requirements without dropping formatting.",
        proposed_scope="SYSTEM", confidence=.96,
    )])
    chat = _chat(monkeypatch, store, interpreter)
    prompt = "Investigate this exactly:\n\n1. Preserve `alpha = 1`.\n2. Do not omit the second line."
    claim = SimpleNamespace(
        conclusion="Both requirements were received.", id="C-MULTI", confidence=.9,
        evidence=[], unresolved_questions=[],
    )
    observed = []
    chat.recursive_supervisor.run = lambda question, root, **kwargs: (
        observed.append(question) or SimpleNamespace(
            claim=claim, task=SimpleNamespace(id="T-MULTI", reuse_type=None),
            cache_hit=False, sub_tasks=[],
        )
    )

    result = chat.reply(prompt, [], None, None)

    assert interpreter.calls[0][0] == prompt
    assert '"current_user_prompt_verbatim": "Investigate this exactly:\\n\\n1.' in observed[0]
    assert "`alpha = 1`" in observed[0]
    assert "Do not omit the second line." in observed[0]
    turn = store.chat_turns(result["session_id"])[0]
    record = store.conversation_interpretations(result["session_id"])[0]
    assert turn.user_message == prompt
    assert record.message == prompt


def test_interpreted_architecture_concept_moves_into_reverse_memory(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    concept = ConversationConcept(
        name="MemoryInterpreter",
        meaning="Retrieves relevant semantic and verbatim conversation for the next turn.",
        architecture_scope="SYSTEM",
        source_ids=["src/rlmgraph/conversation_interpreter.py"],
        confidence=.97,
    )
    interpreter = SemanticInterpreter([
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="The user is referring to the reverse memory interpreter.",
            concept_bindings=[concept], confidence=.96,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="The user is continuing that concept.", confidence=.9,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)
    first = chat.reply("Which projects can the memory interpreter see?", [], None, None)
    chat.reply("And what is connected?", [], None, None, first["session_id"])
    remembered = interpreter.calls[1][1].remembered_concepts
    assert remembered == [concept]
    assert interpreter.calls[1][1].verbatim_turns[0].user_message == (
        "Which projects can the memory interpreter see?"
    )


def test_codex_interpreter_is_ephemeral_schema_constrained_and_has_no_repository(
    monkeypatch, tmp_path: Path
):
    captured = {}
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({
            "speech_act": "CORRECTION", "primary_intent": "INVESTIGATE",
            "user_meaning": "The user corrected the prior subject.",
            "workflow_request": None, "objective_update": "Investigate the router, not storage.",
            "entities": ["router"], "concept_bindings": [],
            "references": [], "assumptions": [],
            "ambiguities": [], "proposed_scope": "SYSTEM",
            "authorization_signal": False, "confidence": .94,
            "needs_clarification": False,
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("rlmgraph.adapters.subprocess.run", fake_run)
    result = CodexCliInvestigator(sandbox="read-only").interpret_conversation(
        "No, I meant the router.", ConversationMemoryProjection(session_id="S1")
    )
    command = captured["command"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "Do not answer the user" in captured["prompt"]
    assert "grants no authority" in captured["prompt"]
    assert "primary_intent" in captured["schema"]["required"]
    assert "concept_bindings" in captured["schema"]["required"]
    assert captured["schema"]["additionalProperties"] is False
    assert result.speech_act == "CORRECTION"


def test_codex_repair_interpreter_receives_verbatim_prompt_and_confusion(
    monkeypatch, tmp_path: Path
):
    captured = {}
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    def fake_run(command, **kwargs):
        captured["prompt"] = kwargs["input"]
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({
            "resolved_references": [{
                "phrase": "it", "target_id": "TURN-1", "target_kind": "CHAT_TURN",
                "confidence": .92,
            }],
            "revised_concepts": [], "revised_primary_intent": None,
            "revised_user_meaning": "The user means the prior turn.",
            "revised_workflow_request": None, "revised_objective_update": None,
            "revised_scope": "SYSTEM", "remaining_ambiguities": [],
            "added_assumptions": [], "resolution_basis": ["memory turn TURN-1"],
            "confidence": .92, "needs_clarification": False,
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("rlmgraph.adapters.subprocess.run", fake_run)
    interpretation = ConversationInterpretation(
        speech_act="QUESTION", primary_intent="INVESTIGATE",
        user_meaning="Uncertain referent.", references=[ConversationReference(phrase="it")],
        ambiguities=["What does it mean?"], confidence=.4, needs_clarification=True,
    )
    from rlmgraph.conversation_interpreter import describe_confusion

    repair = CodexCliInvestigator(sandbox="read-only").repair_conversation(
        "Explain it.\nKeep this line.", ConversationMemoryProjection(session_id="S1"),
        interpretation, describe_confusion(interpretation),
    )
    assert "Explain it.\nKeep this line." in captured["prompt"]
    assert "What does it mean?" in captured["prompt"]
    assert "Return a patch" in captured["prompt"]
    assert "grants no workflow authority" in captured["prompt"]
    assert repair.resolved_references[0].target_id == "TURN-1"
