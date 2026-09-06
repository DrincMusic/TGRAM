import pytest
from test_learning import draft, fixture

from rlmgraph.conversation_memory import ConversationMemoryPipeline
from rlmgraph.learning import ApplicationReport
from rlmgraph.models import ChatSession, ChatTurn, ConversationFact
from rlmgraph.project_world_memory import ProjectWorldMemory
from rlmgraph.workflow_fact_search import WorkflowFactSearch
from rlmgraph.world_neural_memory import WorldMemoryRanker


def test_shared_fact_has_one_source_and_is_available_to_conversation_and_work(tmp_path):
    root, store, project, _ = fixture(tmp_path)
    session = ChatSession(profile_id="owner")
    store.save_chat_session(session)
    turn = ChatTurn(session_id=session.id, ordinal=1, user_message="Keep navigation compact",
                    answer="Recorded", scope="SYSTEM", route="RLM_CONVERSATION", routing_confidence=1)
    store.save_chat_turn(turn)
    fact = ConversationFact(session_id=session.id, kind="PREFERENCE", subject="navigation",
        predicate="layout", value="Keep navigation compact", source_turn_id=turn.id,
        source_interpretation_id="interpretation", confidence=.9, meaning="PREFERENCE")
    store.save_conversation_fact(fact)
    world = ProjectWorldMemory(store)
    assert world.search("compact navigation", project)["memories"] == []
    with pytest.raises(PermissionError):
        world.link(project, session.id, fact.id, "stranger")
    for _ in range(2):
        world.link(project, session.id, fact.id, "owner")
    assert len(store.conversation_facts(session.id)) == 1
    recalled = world.search("compact navigation", project)
    assert [item["id"] for item in recalled["memories"]] == [fact.id]
    assert recalled["neural_state"]["training_examples"] > 0
    assert any(hit.reference == fact.id for hit in WorkflowFactSearch(store).search(
        "compact navigation", root, project).hits)
    memory = ConversationMemoryPipeline(store).reconstruct(
        session.id, "compact navigation", [turn], [], project, profile_id="owner")
    assert memory.relevant_world_memories[0]["id"] == fact.id
    turn.superseded_by_turn_id = "replacement-turn"
    store.save_chat_turn(turn)
    assert world.search("compact navigation", project)["memories"] == []


def test_lesson_world_index_and_positive_negative_feedback(tmp_path):
    _, store, project, library = fixture(tmp_path)
    lesson = library.learn(project, draft(), "owner")
    assert "vector" in lesson["world_index"]
    world = ProjectWorldMemory(store)
    assert world.search("caching lookup", project)["memories"][0]["id"] == lesson["id"]
    for outcome in ("HELPED", "DID_NOT_HELP", "INCONCLUSIVE"):
        library.report(project, lesson["id"], ApplicationReport(outcome=outcome,
            context="database lookup", observation="measured response", evidence_ref="run:1"), "owner")
    ranker = WorldMemoryRanker(world.state_path)
    assert ranker.outcome_examples == 2
    assert ranker.ready() is False
