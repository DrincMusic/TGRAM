from types import SimpleNamespace

from rlmgraph.conversation_memory import ConversationMemoryPipeline
from rlmgraph.deductive_reasoning import DeductiveSelfAssessmentEngine
from rlmgraph.models import ConversationWorkResult
from rlmgraph.store import SQLiteGraphStore


def _result():
    return ConversationWorkResult(
        request_id="REQUEST-1", session_id="SESSION-1", task_id="TASK-1",
        claim_ids=["CLAIM-1"],
        answer_summary="The system lacks a mechanism to compare and rank weaknesses.",
        confidence=.9,
        unresolved_questions=["Which weakness dimension should dominate?"],
        worker_trace_id="TASK-1",
    )


def test_deductive_assessment_ranks_candidates_and_persists_theory_memory(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    claim = SimpleNamespace(
        id="CLAIM-1",
        conclusion="The system has no decision mechanism to compare, score, or rank weaknesses.",
        confidence=.93,
    )
    store.get_claim = lambda claim_id: claim if claim_id == claim.id else None

    report = DeductiveSelfAssessmentEngine(store).assess("SESSION-1", _result())

    assert report.reasoning_method == "EXPLICIT_DEDUCTIVE_RANKING_V1"
    assert report.candidates[0].category == "DECISION_QUALITY"
    assert report.selected_candidate_id == report.candidates[0].id
    assert "severity" in report.conclusion
    theories = store.deductive_theories("SESSION-1")
    assert len(theories) == 1
    assert theories[0].inference_rule == (
        "MISSING_COMPARATIVE_MECHANISM_IMPLIES_UNRELIABLE_SUPERLATIVE"
    )
    assert theories[0].premises[0].source_id == "CLAIM-1"
    assert theories[0].falsifiers
    assert store.self_assessment_reports("SESSION-1") == [report]


def test_new_assessment_supersedes_prior_theory_without_erasing_it(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    claim = SimpleNamespace(
        id="CLAIM-1", conclusion="No implemented mechanism ranks or scores weaknesses.",
        confidence=.9,
    )
    store.get_claim = lambda claim_id: claim
    engine = DeductiveSelfAssessmentEngine(store)

    first = engine.assess("SESSION-1", _result())
    second = engine.assess("SESSION-1", _result())

    theories = store.deductive_theories("SESSION-1")
    first_theory = next(item for item in theories if item.id == first.candidates[0].theory_id)
    second_theory = next(item for item in theories if item.id == second.candidates[0].theory_id)
    assert first_theory.status == "SUPERSEDED"
    assert second_theory.status == "ACTIVE_THEORY"
    assert second_theory.supersedes_theory_id == first_theory.id


def test_learned_theory_is_recalled_by_related_active_conversation(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    claim = SimpleNamespace(
        id="CLAIM-1", conclusion="Theory recall is incomplete in worker memory.", confidence=.9,
    )
    store.get_claim = lambda claim_id: claim
    report = DeductiveSelfAssessmentEngine(store).assess("SESSION-1", _result())

    memory = ConversationMemoryPipeline(store).reconstruct(
        "SESSION-1", "Can the worker recall its past weakness theories?", [], [],
    )

    recalled_ids = {theory.id for theory in memory.relevant_theories}
    assert report.candidates[0].theory_id in recalled_ids
    assert memory.recent_self_assessments == [report]
