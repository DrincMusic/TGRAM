from types import SimpleNamespace

from rlmgraph.conversation_memory import ConversationMemoryPipeline
from rlmgraph.models import ConversationInterpretation, ConversationInterpretationRecord
from rlmgraph.store import SQLiteGraphStore


def commit(pipeline, number, value="Keep chat compact", meaning="REQUIREMENT", excerpt="Keep chat compact"):
    turn = SimpleNamespace(id=f"turn-{number}", session_id="session", user_message=value)
    record = ConversationInterpretationRecord(
        session_id="session", message=value, interpreter="test",
        interpretation=ConversationInterpretation(
            speech_act="STATEMENT", primary_intent="CONVERSE", user_meaning=value,
            confidence=.9, memory_candidates=[{
                "kind": "CONTEXT", "subject": "chat", "predicate": "layout", "value": value,
                "confidence": .9, "meaning": meaning, "source_excerpt": excerpt,
                "useful_when": "designing dashboard navigation",
            }],
        ),
    )
    return pipeline.commit(turn, record)


def test_fact_provenance_deduplicates_and_preserves_corrections(tmp_path):
    store = SQLiteGraphStore(tmp_path / "facts.db")
    store.initialize()
    pipeline = ConversationMemoryPipeline(store)
    original = commit(pipeline, 0)[0]
    for number in range(1, 12):
        assert commit(pipeline, number) == []
    facts = store.conversation_facts("session")
    assert len(facts) == 1
    assert facts[0].supporting_turn_ids == [f"turn-{n}" for n in range(4, 12)]
    assert facts[0].confidence == .9
    assert facts[0].last_confirmed_at is not None
    assert facts[0].source_excerpt == "Keep chat compact"
    corrected = commit(pipeline, 12, "Use more detail", excerpt="invented quote")[0]
    assert corrected.supersedes_fact_id == original.id
    assert corrected.source_excerpt == ""
    observed = commit(pipeline, 13, "Chat is compact", meaning="REPORTED")[0]
    assert observed.supersedes_fact_id is None
    assert len(pipeline._active_facts("session")) == 2
    recalled = pipeline._retrieve_profile_memories("session", "dashboard navigation")
    assert corrected.id in {fact.id for fact in recalled}
    assert original.id not in {fact.id for fact in recalled}
