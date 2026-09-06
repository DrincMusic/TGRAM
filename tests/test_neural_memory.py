from rlmgraph.conversation_memory import ConversationMemoryPipeline
from rlmgraph.models import (
    ChatSession,
    ConversationFact,
    ConversationFactKind,
    NeuralMemoryScore,
)
from rlmgraph.neural_memory import NeuralMemoryRanker
from rlmgraph.store import SQLiteGraphStore


def _fact(session_id: str, subject: str, value: str) -> ConversationFact:
    return ConversationFact(
        session_id=session_id,
        kind=ConversationFactKind.CONTEXT,
        subject=subject,
        predicate="is",
        value=value,
        source_turn_id=f"TURN-{subject}",
        source_interpretation_id=f"INTERPRETATION-{subject}",
        confidence=.9,
    )


def test_neural_ranker_trains_persists_and_restores_weights(tmp_path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ranker = NeuralMemoryRanker(store)
    relevant = _fact("S1", "project architecture", "graph memory")
    unrelated = _fact("S2", "weather", "sunny")

    scores = ranker.rank(
        "explain the project architecture",
        [(relevant, 8.0), (unrelated, .2)],
        {relevant.id},
        "S1",
    )

    assert len(scores) == 2
    assert next(item for item in scores if item.memory_id == relevant.id).selected is True
    assert ranker.training_examples == 2
    assert ranker.state_path is not None and ranker.state_path.exists()
    restored = NeuralMemoryRanker(store)
    assert restored.training_examples == 2
    assert restored.w2 == ranker.w2
    assert restored.state().mode == "SHADOW"


def test_neural_ranker_is_shadow_only_and_does_not_change_selected_ids(tmp_path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ranker = NeuralMemoryRanker(store)
    first = _fact("S1", "first", "alpha")
    second = _fact("S1", "second", "beta")

    scores = ranker.rank("beta", [(first, 1.0), (second, 4.0)], {second.id}, "S1")

    assert {item.memory_id for item in scores if item.selected} == {second.id}
    assert all(0 <= item.neural_score <= 1 for item in scores)


def test_outcome_feedback_trains_only_when_memory_usage_is_observed(tmp_path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ranker = NeuralMemoryRanker(store)
    used = _fact("S1", "project", "RLMGraph")
    unused = _fact("S2", "weather", "sunny")

    ranker.reinforce("what project?", [used, unused], set(), "S1")
    assert ranker.outcome_examples == 0

    ranker.reinforce("what project?", [used, unused], {used.id}, "S1")

    assert ranker.outcome_examples == 2
    assert ranker.state().rolling_loss > 0
    restored = NeuralMemoryRanker(store)
    assert restored.outcome_examples == 2


def test_ready_network_can_rescue_but_never_remove_deterministic_memories(tmp_path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    store.save_chat_session(ChatSession(id="S1"))
    facts = [_fact("S1", f"memory-{index}", str(index)) for index in range(14)]
    for fact in facts:
        store.save_conversation_fact(fact)
    pipeline = ConversationMemoryPipeline(store)
    pipeline.neural_ranker.ready = lambda: False
    deterministic, _, _ = pipeline._retrieve_facts("S1", "unrelated query")
    deterministic_ids = {fact.id for fact in deterministic}
    missed = next(fact for fact in facts if fact.id not in deterministic_ids)
    pipeline.neural_ranker.ready = lambda: True
    pipeline.neural_ranker.rank = lambda *args, **kwargs: [
        NeuralMemoryScore(
            memory_id=fact.id,
            memory_kind=fact.kind.value,
            deterministic_score=1,
            neural_score=.95 if fact == missed else .2,
            selected=False,
        )
        for fact in facts
    ]

    selected, _, rescued = pipeline._retrieve_facts("S1", "unrelated query")

    assert {fact.id for fact in deterministic}.issubset({fact.id for fact in selected})
    assert rescued == [missed.id]
    assert len(selected) == 13
