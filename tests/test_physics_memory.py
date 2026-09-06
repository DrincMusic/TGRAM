from pathlib import Path

from rlmgraph.physics_memory import PhysicsMemory


def test_physics_memory_retrieves_support_and_stair_principles(tmp_path: Path):
    memory = PhysicsMemory(tmp_path / "physics.jsonl")
    ids = memory.seed_verified_ontology()

    projection = memory.retrieve(
        "Build a two story cabin with supported roof floor walls and stairs to a door",
    )

    assert len(ids) == len(memory.DEFAULT_PRINCIPLES)
    assert projection["record_count"] >= 5
    assert "GRAVITY_SUPPORT" in projection["text"]
    assert "LOAD_PATH" in projection["text"]
    assert "STAIR_ENDPOINT_CONTACT" in projection["text"]
    assert "DIRECTIONAL_SUPPORT_ROLES" in projection["text"]
    assert "INVALID_SUPPORT_ROLES" in projection["text"]
    assert "Unreal transform freedom" in projection["text"]
    assert projection["submission_derived_records"] == 0


def test_physics_memory_is_deterministic_and_contains_explicit_exceptions(tmp_path: Path):
    memory = PhysicsMemory(tmp_path / "physics.jsonl")
    first = memory.seed_verified_ontology()
    second = memory.seed_verified_ontology()

    assert first == second
    assert len(memory.records()) == len(first)
    gravity = next(item for item in memory.records() if item.principle == "GRAVITY_SUPPORT")
    assert "explicit suspension" in gravity.exceptions
    assert "declared flying object" in gravity.exceptions
