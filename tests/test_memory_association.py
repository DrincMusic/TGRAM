from rlmgraph.memory_association import MemoryAssociationEngine
from rlmgraph.models import (
    ChatSession,
    ConversationFact,
    ConversationFactKind,
    MemoryAssociationStatus,
    MemoryAssociationType,
)
from rlmgraph.store import SQLiteGraphStore


def _fact(session, subject, value, *, predicate="maps_to", supersedes=None):
    return ConversationFact(
        session_id=session,
        kind=ConversationFactKind.CONTEXT,
        subject=subject,
        predicate=predicate,
        value=value,
        source_turn_id=f"TURN-{subject}",
        source_interpretation_id=f"INTERPRETATION-{subject}",
        confidence=.95,
        supersedes_fact_id=supersedes,
    )


def test_engine_discovers_structural_analogy_and_persists_candidate(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    queen = _fact("SESSION-1", "queen", "woman")
    king = _fact("SESSION-1", "king", "man")
    store.save_conversation_fact(queen)
    store.save_conversation_fact(king)

    found = MemoryAssociationEngine(store).discover(king)

    assert len(found) == 1
    assert found[0].relation == MemoryAssociationType.ANALOGOUS_TO
    assert found[0].status == MemoryAssociationStatus.CANDIDATE
    assert found[0].source_memory_ids == [queen.id, king.id]
    assert found[0].structural_score == .5
    assert "both memories use relation 'maps_to'" in found[0].shared_pattern
    assert store.memory_associations("SESSION-1") == found


def test_revision_is_connected_without_becoming_an_accepted_fact(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    old = _fact("SESSION-1", "project", "Alpha", predicate="is")
    new = _fact("SESSION-1", "project", "RLMGraph", predicate="is", supersedes=old.id)
    store.save_conversation_fact(old)
    store.save_conversation_fact(new)

    found = MemoryAssociationEngine(store).discover(new)

    assert found[0].relation == MemoryAssociationType.SUPERSEDES
    assert found[0].status == MemoryAssociationStatus.CANDIDATE
    assert found[0].confidence >= .95


def test_unrelated_memories_do_not_receive_a_spurious_connection(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    first = _fact("SESSION-1", "queen", "woman", predicate="gender")
    second = _fact("SESSION-1", "database", "sqlite", predicate="persists_with")
    store.save_conversation_fact(first)
    store.save_conversation_fact(second)

    assert MemoryAssociationEngine(store).discover(second) == []
    assert store.memory_associations("SESSION-1") == []


def test_new_memory_connects_to_related_memory_in_an_older_session(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    store.save_chat_session(ChatSession(id="SESSION-OLD"))
    store.save_chat_session(ChatSession(id="SESSION-NEW"))
    old = _fact("SESSION-OLD", "queen", "woman")
    new = _fact("SESSION-NEW", "king", "man")
    store.save_conversation_fact(old)
    store.save_conversation_fact(new)

    found = MemoryAssociationEngine(store).discover(new)

    assert len(found) == 1
    assert found[0].source_memory_ids == [old.id, new.id]
    assert found[0].session_id == "SESSION-NEW"


def test_relationship_interpretations_form_cluster_with_exact_fact_descent(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    engine = MemoryAssociationEngine(store)
    facts = [
        _fact("SESSION-1", "queen", "woman"),
        _fact("SESSION-1", "king", "man"),
        _fact("SESSION-1", "princess", "girl"),
    ]
    for fact in facts:
        store.save_conversation_fact(fact)
        engine.discover(fact)

    interpretations = store.memory_relationship_interpretations("SESSION-1")
    clusters = store.memory_clusters("SESSION-1")
    assert len(interpretations) == 3
    assert all(item.possible_abstraction.startswith("reusable relation pattern") for item in interpretations)
    assert len(clusters) == 1
    assert clusters[0].abstraction_level == 1
    assert set(clusters[0].supporting_fact_ids) == {fact.id for fact in facts}
    assert set(clusters[0].member_memory_ids) == {fact.id for fact in facts}


def test_clusters_recursively_form_higher_order_cluster(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    engine = MemoryAssociationEngine(store)
    facts = [
        _fact("SESSION-1", "queen", "woman", predicate="maps_to"),
        _fact("SESSION-1", "king", "man", predicate="maps_to"),
        _fact("SESSION-1", "princess", "girl", predicate="maps_to"),
        _fact("SESSION-1", "chat", "conversation_memory", predicate="belongs_to"),
        _fact("SESSION-1", "claim", "worker_memory", predicate="belongs_to"),
        _fact("SESSION-1", "request", "work_bridge", predicate="belongs_to"),
    ]
    for fact in facts:
        store.save_conversation_fact(fact)
        engine.discover(fact)

    clusters = store.memory_clusters("SESSION-1")
    level_one = [item for item in clusters if item.abstraction_level == 1]
    level_two = [item for item in clusters if item.abstraction_level == 2]
    assert len(level_one) >= 2
    assert len(level_two) >= 1
    assert set(level_two[-1].member_memory_ids).issubset({item.id for item in level_one})
    assert set(level_two[-1].supporting_fact_ids).issubset({fact.id for fact in facts})
    branches = store.concept_branches("SESSION-1")
    assert len(branches) == 2
    assert branches[0].depth == 1
    assert branches[1].parent_branch_id == branches[0].id
    assert branches[1].depth == 2
    assert all(branch.status == "EXPLORING" for branch in branches)


def test_repeated_insight_does_not_duplicate_existing_branch(tmp_path):
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    engine = MemoryAssociationEngine(store)
    facts = [
        _fact("SESSION-1", "queen", "woman"),
        _fact("SESSION-1", "king", "man"),
        _fact("SESSION-1", "princess", "girl"),
    ]
    for fact in facts:
        store.save_conversation_fact(fact)
        engine.discover(fact)

    branches = store.concept_branches("SESSION-1")
    assert len(branches) == 1
    assert branches[0].origin_interpretation_id in {
        item.id for item in store.memory_relationship_interpretations("SESSION-1")
    }
    assert set(branches[0].supporting_fact_ids).issubset({fact.id for fact in facts})
