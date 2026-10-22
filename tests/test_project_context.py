import json

from rlmgraph.project_context import ProjectContextCompiler
from rlmgraph.project_task_graph import TaskLease


def test_context_is_bounded_and_uses_only_selected_semantic_fields() -> None:
    lease = TaskLease(3, "add dependency checks", "cycles are rejected", [2], 1, "lease", "")
    memories = [{
        "action": "normalized dependency ids", "invariant": "ids are positive",
        "concepts": ["dependency"], "files": ["taskboard.py"],
        "archive_ref": "archive-1", "raw_payload": "x" * 20_000,
    }]
    result = ProjectContextCompiler(char_budget=1200, memory_char_budget=500).compile(
        lease=lease, project_intent="Build a board", phase="IMPLEMENT",
        memories=memories, pass_index=1, pass_count=2,
    )

    assert result.characters <= 1200
    assert "raw_payload" not in result.prompt
    assert "archive-1" in result.prompt
    assert "normalized dependency ids" in result.prompt


def test_context_budget_prioritizes_explicit_relevance_stably() -> None:
    lease = TaskLease(4, "repair serializer", "round trip passes", [], 1, "lease", "")
    memories = [
        {
            "memory_id": "LOW",
            "action": "inspect unrelated formatting behavior",
            "relevance": 0.1,
        },
        {
            "memory_id": "HIGH-FIRST",
            "action": "preserve the serialization contract",
            "relevance": 0.9,
        },
        {
            "memory_id": "HIGH-SECOND",
            "action": "retain stable ordering for equal relevance",
            "relevance": 0.9,
        },
    ]
    compiler = ProjectContextCompiler(char_budget=1200, memory_char_budget=210)

    result = compiler.compile(
        lease=lease,
        project_intent="Repair serialization",
        phase="IMPLEMENT",
        memories=memories,
        pass_index=1,
        pass_count=1,
    )
    packet = json.loads(result.prompt.split("TASK_PACKET=", 1)[1])
    selected = [memory["memory_id"] for memory in packet["relevant_memory"]]

    assert selected == ["HIGH-FIRST", "HIGH-SECOND"]
    assert "LOW" not in result.prompt


def test_context_preserves_input_order_when_relevance_is_missing_or_invalid() -> None:
    lease = TaskLease(5, "inspect state", "state is explained", [], 1, "lease", "")
    memories = [
        {"memory_id": "FIRST", "action": "first memory"},
        {"memory_id": "SECOND", "action": "second memory", "relevance": "unknown"},
    ]

    result = ProjectContextCompiler(char_budget=1200, memory_char_budget=500).compile(
        lease=lease,
        project_intent="Inspect state",
        phase="IMPLEMENT",
        memories=memories,
        pass_index=1,
        pass_count=1,
    )
    packet = json.loads(result.prompt.split("TASK_PACKET=", 1)[1])

    assert [memory["memory_id"] for memory in packet["relevant_memory"]] == [
        "FIRST",
        "SECOND",
    ]
