from types import SimpleNamespace

import pytest

from rlmgraph.models import (
    ConversationInterpretation,
    DeductivePremise,
    DeductiveTheory,
    SelfAssessmentReport,
    WeaknessCandidate,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


class Interpreter:
    def __init__(self, results):
        self.results = iter(results)

    def interpret_conversation(self, message, memory):
        return next(self.results)


def _chat(monkeypatch, store, interpreter):
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    return ObserverChat(store, interpreter=interpreter)


def _worker_result():
    claim = SimpleNamespace(
        id="CLAIM-BRIDGE", conclusion="Evidence-backed worker output.", confidence=.91,
        evidence=[], unresolved_questions=[],
    )
    task = SimpleNamespace(id="TASK-BRIDGE", reuse_type=None)
    return SimpleNamespace(claim=claim, task=task, cache_hit=False, sub_tasks=[])


def test_read_only_bridge_persists_exact_request_selected_facts_and_result(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([
        ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE",
            user_meaning="The current project is RLMGraph.", confidence=.98,
        ),
        ConversationInterpretation(
            speech_act="QUESTION", primary_intent="INVESTIGATE",
            user_meaning="Investigate RLMGraph worker request routing.",
            proposed_scope="SYSTEM", confidence=.95,
        ),
    ])
    chat = _chat(monkeypatch, store, interpreter)
    first = chat.reply("this project is RLMGraph", [], None, None)
    theory = DeductiveTheory(
        session_id=first["session_id"], subject="memory.recall",
        premises=[DeductivePremise(
            source_id="CLAIM-OLD", source_kind="EVIDENCE_CLAIM",
            statement="Past evidence suggests theory recall is incomplete.", confidence=.8,
        )],
        inference_rule="INCOMPLETE_RECALL_LIMITS_REASONING",
        conclusion="The worker should test whether learned theories are recalled.",
        confidence=.8, falsifiers=["A traced worker request recalls this theory."],
        source_claim_ids=["CLAIM-OLD"],
    )
    store.save_deductive_theory(theory)
    candidate = WeaknessCandidate(
        category="MEMORY_RECALL", description=theory.conclusion, theory_id=theory.id,
        evidence_strength=.8, impact=.8, recurrence=.5, unresolvedness=.7, severity=.72,
    )
    report = SelfAssessmentReport(
        session_id=first["session_id"], work_result_id="WORK-OLD",
        source_claim_ids=["CLAIM-OLD"], candidates=[candidate],
        selected_candidate_id=candidate.id, conclusion=theory.conclusion, confidence=.8,
    )
    store.save_self_assessment_report(report)
    observed = []
    run = lambda question, root, **kwargs: observed.append(question) or _worker_result()
    chat.supervisor.run = run
    chat.recursive_supervisor.run = run
    prompt = "How does RLMGraph route worker requests?"

    result = chat.reply(prompt, [], None, None, first["session_id"])

    requests = store.conversation_work_requests(first["session_id"])
    results = store.conversation_work_results(first["session_id"])
    facts = store.conversation_facts(first["session_id"])
    assert len(requests) == len(results) == 1
    assert requests[0].exact_user_prompt == prompt
    assert requests[0].authorization == "READ_ONLY_INVESTIGATION"
    assert requests[0].status == "COMPLETED"
    assert requests[0].conversation_fact_ids == [fact.id for fact in facts]
    assert requests[0].deductive_theory_ids == [theory.id]
    assert requests[0].self_assessment_report_ids == [report.id]
    assert results[0].request_id == requests[0].id
    assert results[0].task_id == "TASK-BRIDGE"
    assert results[0].claim_ids == ["CLAIM-BRIDGE"]
    assert result["work_bridge_request_id"] == requests[0].id
    assert result["work_bridge_result_id"] == results[0].id
    assert '"current_user_prompt_verbatim": "How does RLMGraph route worker requests?"' in observed[0]
    assert '"selected_conversation_facts"' in observed[0]
    assert '"recalled_deductive_theories"' in observed[0]
    assert theory.id in observed[0]
    assert '"falsifiers"' in observed[0]
    assert '"recalled_self_assessments"' in observed[0]
    assert '"value": "RLMGraph"' in observed[0]
    assert '"conversation_memory"' not in observed[0]
    assert first["answer"] not in observed[0]


def test_conversation_turn_creates_no_work_bridge_records(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([ConversationInterpretation(
        speech_act="GREETING", primary_intent="CONVERSE",
        user_meaning="The user says hello.", confidence=.99,
    )])

    result = _chat(monkeypatch, store, interpreter).reply("hello", [], None, None)

    assert result["route"] == "RLM_CONVERSATION"
    assert store.conversation_work_requests(result["session_id"]) == []
    assert store.conversation_work_results(result["session_id"]) == []


def test_worker_failure_leaves_auditable_request_without_fabricated_result(
    tmp_path, monkeypatch
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    interpreter = Interpreter([ConversationInterpretation(
        speech_act="QUESTION", primary_intent="INVESTIGATE",
        user_meaning="Investigate a worker failure.", proposed_scope="SYSTEM", confidence=.9,
    )])
    chat = _chat(monkeypatch, store, interpreter)
    failure = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("worker offline"))
    chat.supervisor.run = failure
    chat.recursive_supervisor.run = failure

    with pytest.raises(RuntimeError, match="worker offline"):
        chat.reply("Why is the worker offline?", [], None, None)

    sessions = store.chat_sessions()
    assert len(sessions) == 1
    assert len(store.conversation_work_requests(sessions[0].id)) == 1
    assert store.conversation_work_results(sessions[0].id) == []
