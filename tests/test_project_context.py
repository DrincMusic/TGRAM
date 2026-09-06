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
