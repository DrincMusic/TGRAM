from pathlib import Path

import pytest

from rlmgraph.geometric_memory import GeometricMemory


def wall_probe(**extra):
    return {
        "path": "/Game/Architecture/Walls/SM_Wall_Half.SM_Wall_Half",
        "bounds_min": [-400.0, -10.0, 0.0],
        "bounds_max": [400.0, 10.0, 300.0],
        "dimensions": [800.0, 20.0, 300.0],
        "pivot_offset_from_center": [0.0, 0.0, -150.0],
        **extra,
    }


def test_geometric_memory_derives_ports_axes_and_constraints(tmp_path: Path):
    memory = GeometricMemory(tmp_path / "geometry.jsonl")

    ids = memory.remember_probe([wall_probe()], source_fingerprint="SOURCE-HASH")
    projection = memory.retrieve("Build connected walls from SM_Wall_Half")

    assert ids == projection["memory_ids"]
    assert projection["record_count"] == 1
    assert projection["tokens"] > 0
    record = memory.records()[0]
    assert record.semantic_kind == "wall"
    assert record.primary_axis == "X"
    assert record.thickness_axis == "Y"
    assert {item["name"] for item in record.connection_ports} == {
        "edge_negative", "edge_positive",
    }
    assert any("must not overlap or leave gaps" in item for item in record.constraints)
    assert record.submission_derived is False


def test_geometric_memory_rejects_submission_derived_geometry(tmp_path: Path):
    memory = GeometricMemory(tmp_path / "geometry.jsonl")

    with pytest.raises(ValueError, match="cannot ingest benchmark submission"):
        memory.remember_probe(
            [wall_probe(submission_derived=True)], source_fingerprint="MAP-HASH",
        )


def test_geometric_memory_retrieval_is_bounded_and_relevant(tmp_path: Path):
    memory = GeometricMemory(tmp_path / "geometry.jsonl", char_budget=1800)
    probes = [
        wall_probe(path=f"/Game/Architecture/Walls/SM_Wall_{index}.SM_Wall_{index}")
        for index in range(20)
    ]
    memory.remember_probe(probes, source_fingerprint="SOURCE-HASH")

    projection = memory.retrieve("Use SM_Wall_7 to construct a wall")

    assert projection["characters"] <= 1900
    assert 0 < projection["record_count"] < 20
    assert "SM_Wall_7" in projection["text"]
    assert projection["submission_derived_records"] == 0
