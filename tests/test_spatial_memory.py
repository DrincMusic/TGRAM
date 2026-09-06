from pathlib import Path

import pytest

from rlmgraph.spatial_memory import SpatialMemory, SpatialMemoryRecord


def test_spatial_memory_retrieves_scene_relationships_without_layout(tmp_path: Path):
    memory = SpatialMemory(tmp_path / "spatial.jsonl")
    ids = memory.seed_verified_ontology()

    projection = memory.retrieve(
        "Build connected cabin walls, roof, door, stairs, path, rocks, and vegetation",
    )

    assert len(ids) == len(memory.DEFAULT_RELATIONS)
    assert projection["record_count"] >= 8
    assert projection["tokens"] > 0
    assert projection["submission_derived_records"] == 0
    assert "EDGE_CONNECTED" in projection["text"]
    assert "ACCESSIBLE_FROM" in projection["text"]
    assert "CLEAR_OF" in projection["text"]
    assert "OCCUPIES" in projection["text"]
    assert "prior layout" in projection["text"]
    assert not any(
        hasattr(record, "world_location") or hasattr(record, "coordinates")
        for record in memory.records()
    )


def test_spatial_memory_rejects_submission_layouts(tmp_path: Path):
    memory = SpatialMemory(tmp_path / "spatial.jsonl")
    record = SpatialMemoryRecord(
        memory_id="BAD", relation="NEXT_TO", subject_type="saved_cabin",
        object_type="saved_tree", invariant="copy prior coordinates",
        verification_strategy="submission map", concepts=("layout",),
        submission_derived=True,
    )

    with pytest.raises(ValueError, match="cannot ingest benchmark submission layouts"):
        memory.remember_relation(record)


def test_spatial_memory_is_deterministic_and_deduplicated(tmp_path: Path):
    memory = SpatialMemory(tmp_path / "spatial.jsonl")

    first = memory.seed_verified_ontology()
    second = memory.seed_verified_ontology()

    assert first == second
    assert len(memory.records()) == len(first)
