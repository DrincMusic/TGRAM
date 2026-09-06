from types import SimpleNamespace

from rlmgraph.models import (
    ChatScope,
    ChatTurn,
    ConversationFactKind,
    ConversationInterpretation,
    ConversationMemoryCandidate,
    ConversationResponse,
    ProjectRecord,
    ProjectScan,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.project_action_memory import ProjectActionMemory
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.system_evaluation_memory import SystemEvaluationMemoryStore


class Interpreter:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def interpret_conversation(self, message, memory):
        self.calls.append((message, memory))
        return next(self.results)


class ProfileInterpreter(Interpreter):
    def __init__(self, results):
        super().__init__(results)
        self.response_calls = []

    def respond_conversation(self, message, memory, interpretation):
        self.response_calls.append((message, memory, interpretation))
        recalled = memory.relevant_profile_memories
        if not recalled:
            return ConversationResponse(
                answer="I don't have a matching memory.", used_fact_ids=[], confidence=.9,
            )
        memory_item = recalled[0]
        return ConversationResponse(
            answer=f"I remember it as {memory_item.value}",
            used_fact_ids=[memory_item.id], confidence=.96,
        )


class ActionRecallInterpreter(Interpreter):
    def __init__(self, results):
        super().__init__(results)
        self.response_calls = []

    def respond_conversation(self, message, memory, interpretation):
        self.response_calls.append((message, memory, interpretation))
        actions = memory.relevant_action_memories
        if not actions:
            return ConversationResponse(
                answer="I couldn't find a matching completed change.", confidence=.88,
            )
        action = actions[0]
        return ConversationResponse(
            answer=(
                f"I remember changing {', '.join(action.files)} to {action.action} "
                f"for {action.invariant}"
            ),
            used_action_memory_ids=[action.memory_id], confidence=.96,
        )


class EvaluationRecallInterpreter(Interpreter):
    def __init__(self, results):
        super().__init__(results)
        self.response_calls = []

    def respond_conversation(self, message, memory, interpretation):
        self.response_calls.append((message, memory, interpretation))
        evaluation = memory.relevant_evaluation_memories[0]
        return ConversationResponse(
            answer=(
                f"Yes. In {evaluation.metrics['trial_count']} trials, TGRAM passed "
                f"{evaluation.metrics['tgram_pass_rate']:.2%} and the baseline passed "
                f"{evaluation.metrics['baseline_pass_rate']:.2%}. The quality-gated median "
                f"token savings were {evaluation.metrics['median_token_savings_percent']}%."
            ),
            used_evaluation_memory_ids=[evaluation.id], confidence=.97,
        )


def _evaluation_result():
    return {
        "id": "corrected-nine-trial-suite", "quality_threshold": .8,
        "project_count": 3, "repetitions": 3, "trial_count": 9,
        "summary": {
            "verdict": "VALID_SAVINGS_COMPARISON", "quality_gate_passed": True,
            "baseline_pass_rate": .8667, "rlmgraph_pass_rate": .9111,
            "baseline_median_tokens": 423220, "rlmgraph_median_tokens": 68353,
            "quality_gated_median_savings_percent": 83.8,
        },
    }


def test_system_evaluation_is_recalled_in_conversation(tmp_path, monkeypatch):
    system_root = tmp_path / "system"
    evaluation_store = SystemEvaluationMemoryStore(
        system_root / ".rlmgraph" / "system-evaluation-memory.jsonl"
    )
    report = tmp_path / "suite.json"
    report.write_text("{}", encoding="utf-8")
    evaluation = evaluation_store.remember_credible_suite(
        _evaluation_result(), report, models=["gpt-5.4"]
    )
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = EvaluationRecallInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="CONVERSE",
        user_meaning="The user asks TGRAM to recall its nine-trial evaluation.",
        confidence=.98,
    )])
    chat = _chat(monkeypatch, store, interpreter, system_root=system_root)

    response = chat.reply(
        "Do you remember the test you took in the 9 trials?", [], None, None
    )

    recalled = interpreter.response_calls[0][1].relevant_evaluation_memories
    assert recalled == [evaluation]
    assert response["route"] == "RLM_CONVERSATION"
    assert response["conversation_response_evaluation_memory_ids"] == [evaluation.id]
    assert "83.8%" in response["answer"]


def _chat(monkeypatch, store, interpreter, system_root=None):
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    return ObserverChat(store, interpreter=interpreter, system_root=system_root)


def test_identity_statement_becomes_a_durable_conversation_fact(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE",
            user_meaning="The current project is RLMGraph.", confidence=.97,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="The user asks about the current project.", confidence=.9,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)

    first = chat.reply("this project is RLMGraph", [], None, None)
    second = chat.reply(
        "what project are we discussing?", [], None, None, first["session_id"]
    )

    facts = store.conversation_facts(first["session_id"])
    assert len(facts) == 1
    assert facts[0].kind == ConversationFactKind.IDENTITY
    assert facts[0].subject == "conversation.current_project"
    assert facts[0].value == "RLMGraph"
    assert facts[0].source_turn_id == first["turn_id"]
    assert first["conversation_memory_updates"][0]["value"] == "RLMGraph"
    recalled = interpreter.calls[1][1].relevant_facts
    assert recalled == facts
    assert interpreter.calls[1][1].relevant_claim_ids == []
    cognitive_state = interpreter.calls[1][1].memory_system
    assert interpreter.calls[1][1].system_workspace.identity_id == "TGRAM-SYSTEM"
    assert interpreter.calls[1][1].system_workspace.loaded_project_ids == []
    assert cognitive_state.memory_is_core_state is True
    assert cognitive_state.language_models_are_disposable is True
    assert [layer.name for layer in cognitive_state.layers] == [
        "system_workspace", "conversation_memory", "worker_memory", "project_action_memory",
        "system_evaluation_memory", "federated_operational_memory",
        "conversation_work_bridge",
    ]
    assert cognitive_state.live_record_counts["turns"] == 1
    assert cognitive_state.current_fact_ids == [facts[0].id]
    assert "not the durable identity" in cognitive_state.identity_statement
    assert second["route"] == "RLM_CONVERSATION"
    assert second["answer"] == "We’re discussing RLMGraph."
    receipt = second["conversation_memory_receipt"]
    assert receipt["fact_ids"] == [facts[0].id]
    assert receipt["cited_fact_ids"] == [facts[0].id]
    # Reopening the database must preserve what was supplied at response time.
    reopened = SQLiteGraphStore(tmp_path / "memory.db")
    assert reopened.chat_turns(first["session_id"])[1].conversation_memory_receipt == receipt
    assert "RLMGraph" not in str(receipt)  # References, not duplicated fact bodies.


def test_new_identity_supersedes_old_identity_without_deleting_history(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE",
            user_meaning="The current project is Alpha.", confidence=.95,
        ),
        ConversationInterpretation(
            speech_act="CORRECTION", primary_intent="CONVERSE",
            user_meaning="The current project is RLMGraph, not Alpha.", confidence=.98,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="PROJECTS",
            user_meaning="Recall the current project.", confidence=.9,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)
    first = chat.reply("this project is Alpha", [], None, None)
    chat.reply("this project is RLMGraph", [], None, None, first["session_id"])
    chat.reply("what project?", [], None, None, first["session_id"])

    facts = store.conversation_facts(first["session_id"])
    assert [fact.value for fact in facts] == ["Alpha", "RLMGraph"]
    assert facts[1].supersedes_fact_id == facts[0].id
    assert [fact.value for fact in interpreter.calls[2][1].relevant_facts] == ["RLMGraph"]
    turns = SQLiteGraphStore(tmp_path / "memory.db").chat_turns(first["session_id"])
    assert turns[1].conversation_memory_receipt["fact_ids"] == [facts[0].id]
    assert turns[2].conversation_memory_receipt["fact_ids"] == [facts[1].id]


def test_new_session_can_recall_related_memory_from_prior_session(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE",
            user_meaning="The current project is RLMGraph.", confidence=.97,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="CONVERSE",
            user_meaning="Recall the project discussed in an earlier conversation.", confidence=.92,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)

    first = chat.reply("this project is RLMGraph", [], None, None)
    second = chat.reply("what project did we discuss before?", [], None, None)

    assert second["session_id"] != first["session_id"]
    recalled = interpreter.calls[1][1]
    assert any(fact.value == "RLMGraph" for fact in recalled.relevant_facts)
    assert any(
        excerpt.user_message == "this project is RLMGraph"
        for excerpt in recalled.verbatim_turns
    )
    assert len(recalled.verbatim_turns) <= 8
    assert len(recalled.relevant_facts) <= 12


def test_user_profile_memory_is_recalled_naturally_across_sessions(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ProfileInterpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE",
            user_meaning="The user defined a named shared conversational convention.",
            memory_candidates=[ConversationMemoryCandidate(
                kind="EPISODIC", subject="apple handshake", predicate="means",
                value="we each name a fruit and compare whether the earlier one was retained",
                aliases=["apple handshake", "fruit handshake"], confidence=.98,
            )],
            confidence=.98,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="CONVERSE",
            user_meaning="The user asks to recall their named conversational convention.",
            confidence=.96,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)

    first = chat.reply(
        "Let's call our fruit memory check the apple handshake.", [], None, None
    )
    second = chat.reply("Do you remember my apple handshake?", [], None, None)

    assert first["session_id"] != second["session_id"]
    memories = [
        fact for session in store.chat_sessions()
        for fact in store.conversation_facts(session.id) if fact.profile_memory
    ]
    assert len(memories) == 1
    assert memories[0].aliases == ["apple handshake", "fruit handshake"]
    recalled = interpreter.response_calls[0][1].relevant_profile_memories
    assert recalled == memories
    assert second["route"] == "RLM_CONVERSATION"
    assert second["operation_route"] == "CONVERSATIONAL_RESPONSE"
    assert second["conversation_response_generated"] is True
    assert second["conversation_response_fact_ids"] == [memories[0].id]
    assert second["answer"] == (
        "I remember it as we each name a fruit and compare whether the earlier one was retained"
    )


def test_profile_correction_supersedes_prior_session_memory(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ProfileInterpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE", user_meaning="Initial convention.",
            memory_candidates=[ConversationMemoryCandidate(
                kind="CONTEXT", subject="release handshake", predicate="means",
                value="say green before deployment", aliases=["release handshake"], confidence=.95,
            )], confidence=.95,
        ),
        ConversationInterpretation(
            speech_act="CORRECTION", primary_intent="CONVERSE", user_meaning="Corrected convention.",
            memory_candidates=[ConversationMemoryCandidate(
                kind="CONTEXT", subject="release handshake", predicate="means",
                value="say blue before deployment", aliases=["release handshake"], confidence=.98,
            )], confidence=.98,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="CONVERSE", user_meaning="Recall convention.",
            confidence=.96,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)

    chat.reply("The release handshake means say green before deployment.", [], None, None)
    chat.reply("Correction: the release handshake means say blue before deployment.", [], None, None)
    recalled = chat.reply("What was my release handshake?", [], None, None)

    profile = interpreter.response_calls[-1][1].relevant_profile_memories
    assert [fact.value for fact in profile] == ["say blue before deployment"]
    assert profile[0].supersedes_fact_id is not None
    assert recalled["conversation_response_fact_ids"] == [profile[0].id]


def test_conversation_recalls_bounded_action_memory_for_named_project(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    alpha = tmp_path / "project-alpha"
    beta = tmp_path / "project-beta"
    alpha.mkdir()
    beta.mkdir()
    for project_id, root in (("PROJECT-ALPHA", alpha), ("PROJECT-BETA", beta)):
        project = ProjectRecord(
            id=project_id, root=str(root), explicitly_selected=True, read_only=True,
        )
        scan = ProjectScan(project_id=project_id, root=str(root), read_only_verified=True)
        project.latest_scan_id = scan.id
        store.save_project_snapshot(project, scan, [], [], [], [])

    alpha_memory = ProjectActionMemory(alpha / ".rlmgraph" / "action-memory.jsonl")
    expected = alpha_memory.remember(
        milestone_index=3,
        milestone="Export invoices as CSV.",
        phase="IMPLEMENT",
        rationale="Changed `InvoiceExporter.to_csv` to stream normalized invoice rows.",
        files_changed=["src/invoice_exporter.py"],
        confidence=.97,
    )
    ProjectActionMemory(beta / ".rlmgraph" / "action-memory.jsonl").remember(
        milestone_index=1,
        milestone="Export unrelated audit logs.",
        phase="IMPLEMENT",
        rationale="Changed `AuditLog.dump` for an unrelated project.",
        files_changed=["src/audit_log.py"],
        confidence=.99,
    )
    interpreter = ActionRecallInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="CONVERSE",
        user_meaning="Recall the completed CSV export work in project alpha.", confidence=.97,
    )])
    chat = _chat(monkeypatch, store, interpreter)

    result = chat.reply(
        "Do you remember what we changed in project-alpha to get CSV exports?",
        [], None, None,
    )

    recalled = interpreter.response_calls[0][1].relevant_action_memories
    assert [item.memory_id for item in recalled] == [expected.id]
    assert recalled[0].project_id == "PROJECT-ALPHA"
    assert recalled[0].files == ["src/invoice_exporter.py"]
    assert recalled[0].symbols == ["InvoiceExporter.to_csv"]
    assert "audit_log.py" not in result["answer"]
    assert result["route"] == "RLM_CONVERSATION"
    assert result["conversation_response_action_memory_ids"] == [expected.id]


def test_action_recall_does_not_cross_an_unresolved_project_boundary(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = ActionRecallInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="CONVERSE",
        user_meaning="Recall changes for an unknown project.", confidence=.94,
    )])
    chat = _chat(monkeypatch, store, interpreter)

    result = chat.reply(
        "Do you remember what we changed in project-that-does-not-exist?",
        [], None, None,
    )

    assert interpreter.response_calls[0][1].relevant_action_memories == []
    assert result["answer"] == "I couldn't find a matching completed change."
    assert result["conversation_response_action_memory_ids"] == []


def test_tgram_system_workspace_and_actions_remain_outside_selected_project(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    system_root = tmp_path / "tgram-engine"
    project_root = tmp_path / "loaded-project"
    system_root.mkdir()
    project_root.mkdir()
    project = ProjectRecord(
        id="PROJECT-LOADED", root=str(project_root), explicitly_selected=True, read_only=True,
    )
    scan = ProjectScan(
        project_id=project.id, root=str(project_root), read_only_verified=True,
    )
    project.latest_scan_id = scan.id
    store.save_project_snapshot(project, scan, [], [], [], [])
    system_action = ProjectActionMemory(
        system_root / ".rlmgraph" / "system-action-memory.jsonl"
    ).remember(
        milestone_index=1,
        milestone="Add durable user-profile memory.",
        phase="IMPLEMENT",
        rationale="Changed `ConversationMemoryPipeline` to retrieve user profile facts.",
        files_changed=["src/rlmgraph/conversation_memory.py"],
        confidence=.98,
    )
    ProjectActionMemory(project_root / ".rlmgraph" / "action-memory.jsonl").remember(
        milestone_index=1,
        milestone="Add project-local memory.",
        phase="IMPLEMENT",
        rationale="Changed `LoadedProject.cache` in the external project.",
        files_changed=["src/cache.py"],
        confidence=.99,
    )
    interpreter = ActionRecallInterpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="CONVERSE",
        user_meaning="Recall the engine's own memory change.", proposed_scope="SYSTEM",
        confidence=.98,
    )])
    chat = _chat(monkeypatch, store, interpreter, system_root)

    result = chat.reply(
        "Do you remember what we changed in your memory system?",
        [], project.id, None,
    )

    projection = interpreter.response_calls[0][1]
    assert projection.system_self.identity_id == "TGRAM-SYSTEM"
    assert projection.system_workspace.identity_id == "TGRAM-SYSTEM"
    assert projection.system_workspace.loaded_project_ids == [project.id]
    assert projection.architecture_contexts[0].project_id == "TGRAM-SYSTEM"
    assert projection.architecture_contexts[0].project_name == "TGRAM"
    assert [item.memory_id for item in projection.relevant_action_memories] == [
        system_action.id
    ]
    assert result["conversation_response_action_memory_ids"] == [system_action.id]
    assert "src/cache.py" not in result["answer"]


def test_conversation_projection_does_not_import_worker_claim_ids(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="PROJECTS",
        user_meaning="Inspect conversation memory only.", confidence=.9,
    )])
    chat = _chat(monkeypatch, store, interpreter)
    session = chat._session(None, None, None, "memory")
    turn = ChatTurn(
        session_id=session.id, ordinal=1, user_message="prior worker question",
        answer="worker result", scope=ChatScope.SYSTEM, route="WORKER",
        routing_confidence=1, claim_id="CLAIM-WORKER",
    )
    store.save_chat_turn(turn)

    chat.reply("show connected projects", [], None, None, session.id)

    assert interpreter.calls[0][1].relevant_claim_ids == []
