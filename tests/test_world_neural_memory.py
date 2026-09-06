from rlmgraph.world_neural_memory import WorldMemoryRanker


def _candidates():
    return [
        ("OBJECT-tree", "tree canopy forest vegetation", 8.0, "object", .98),
        ("PHYSICS-support", "wall floor support load path", 3.0, "physics", 1.0),
    ]


def test_world_ranker_trains_persists_and_reports_its_parameters(tmp_path) -> None:
    path = tmp_path / "world-ranker.json"
    ranker = WorldMemoryRanker(path)

    ordered, state = ranker.rank("place forest trees", _candidates())

    assert ordered == ["OBJECT-tree", "PHYSICS-support"]
    assert state["mode"] == "SHADOW"
    assert state["parameter_count"] == 1169
    assert state["training_examples"] == 2
    restored = WorldMemoryRanker(path)
    assert restored.training_examples == 2
    assert restored.w2 == ranker.w2


def test_world_ranker_learns_only_from_explicit_outcome_usage(tmp_path) -> None:
    ranker = WorldMemoryRanker(tmp_path / "world-ranker.json")
    ranker.reinforce("build supported cabin", _candidates(), set())
    assert ranker.outcome_examples == 0

    ranker.reinforce("build supported cabin", _candidates(), {"PHYSICS-support"})
    assert ranker.outcome_examples == 2
    assert ranker.rolling_loss > 0


def test_typed_memory_exposes_world_ranker_state_without_changing_safety(tmp_path) -> None:
    from rlmgraph.object_memory import ObjectMemory

    ranker = WorldMemoryRanker(tmp_path / "ranker.json")
    memory = ObjectMemory(tmp_path / "objects.jsonl", neural_ranker=ranker)
    memory.remember_inventory(
        ["/Game/Environment/Rocks/SM_Rock_01"], source_fingerprint="verified",
    )

    projection = memory.retrieve("use a rock as the path surface")

    assert projection["world_neural_memory"]["mode"] == "SHADOW"
    assert "path surface" in projection["text"]
    assert projection["submission_derived_records"] == 0
