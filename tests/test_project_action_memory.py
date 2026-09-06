from rlmgraph.project_action_memory import ProjectActionMemory


def test_parses_persists_and_retrieves_only_relevant_bounded_actions(tmp_path) -> None:
    memory = ProjectActionMemory(tmp_path / "actions.jsonl", max_records=2, char_budget=900)
    memory.remember(
        milestone_index=1, milestone="Normalize task priority values", phase="IMPLEMENT",
        rationale="Implemented `ProjectBoard.update_priority` in taskboard.py. Extra detail ignored.",
        files_changed=["taskboard.py"], confidence=0.9,
    )
    memory.remember(
        milestone_index=2, milestone="Add dependency cycle rejection", phase="REVIEW_AND_REPAIR",
        rationale="Verified dependency traversal and repaired `ProjectBoard.add_dependency`.",
        files_changed=["taskboard.py"], confidence=0.95,
    )

    recalled = memory.retrieve("dependency blockers and cycle handling", current_milestone=3)

    assert recalled
    assert recalled[0]["milestone"] == 2
    assert "dependency" in recalled[0]["concepts"]
    assert len(recalled) <= 2
    assert len(str(recalled)) < 900
    assert len(ProjectActionMemory(tmp_path / "actions.jsonl").records()) == 2


def test_irrelevant_memory_is_not_injected(tmp_path) -> None:
    memory = ProjectActionMemory(tmp_path / "actions.jsonl")
    memory.remember(
        milestone_index=1, milestone="Document serialization", phase="IMPLEMENT",
        rationale="Updated README documentation.", files_changed=["README.md"], confidence=1,
    )

    assert memory.retrieve("dependency cycle algorithm", current_milestone=20) == []


def test_duplicate_memories_are_coalesced_and_superseded_records_are_hidden(tmp_path) -> None:
    memory = ProjectActionMemory(tmp_path / "actions.jsonl")
    first = memory.remember(
        milestone_index=1, milestone="Normalize priority", phase="IMPLEMENT",
        rationale="Implemented priority normalization.", files_changed=["taskboard.py"],
        confidence=0.8, archive_ref="archive-1",
    )
    duplicate = memory.remember(
        milestone_index=1, milestone="Normalize priority", phase="IMPLEMENT",
        rationale="Implemented priority normalization.", files_changed=["taskboard.py"],
        confidence=0.8, archive_ref="archive-duplicate",
    )
    replacement = memory.remember(
        milestone_index=2, milestone="Normalize priority safely", phase="REVIEW_AND_REPAIR",
        rationale="Repaired priority normalization validation.", files_changed=["taskboard.py"],
        confidence=1, archive_ref="archive-2", supersedes=[first.id],
    )

    recalled = memory.retrieve("priority normalization", current_milestone=3)
    assert duplicate.id == first.id
    assert len(memory.records()) == 2
    assert first.id not in {item.get("memory_id") for item in recalled}
    assert recalled[0]["archive_ref"] == "archive-2"
    assert replacement.id != first.id
