from pathlib import Path

import pytest

from rlmgraph.object_memory import ObjectMemory


def test_object_memory_knows_rock_is_not_a_path(tmp_path: Path):
    memory = ObjectMemory(tmp_path / "objects.jsonl")
    path = "/Game/Forest/Rocks/SM_Rock_01.SM_Rock_01"

    ids = memory.remember_inventory([path], source_fingerprint="SOURCE")
    projection = memory.retrieve("Create a path using SM_Rock_01")

    assert projection["memory_ids"] == ["OBJECT-CONCEPT-SHELTER", *ids]
    record = memory.records()[0]
    assert record.object_type == "rock"
    assert "natural dressing" in record.intended_uses
    assert "path surface" in record.prohibited_uses
    assert "walkable corridor section" in record.prohibited_uses


def test_object_memory_distinguishes_surface_and_structural_roles(tmp_path: Path):
    memory = ObjectMemory(tmp_path / "objects.jsonl")
    memory.remember_inventory([
        "/Engine/BasicShapes/Plane.Plane",
        "/Game/Forest/Cabin/Walls/SM_Wall.SM_Wall",
        "/Game/Forest/Cabin/Roofs/SM_Roof.SM_Roof",
    ], source_fingerprint="SOURCE")

    records = {item.object_type: item for item in memory.records()}
    assert "path surface" in records["surface_plane"].intended_uses
    assert "enclosure" in records["wall_module"].intended_uses
    assert "never invert" in records["roof_module"].grounding_rule


def test_object_memory_rejects_submission_objects(tmp_path: Path):
    memory = ObjectMemory(tmp_path / "objects.jsonl")

    with pytest.raises(ValueError, match="cannot ingest benchmark submission"):
        memory.remember_inventory(
            ["/TGRAMBiome/GeneratedRock.GeneratedRock"],
            source_fingerprint="SUBMISSION", submission_derived=True,
        )


def test_object_memory_defines_shelter_as_an_inside_outside_boundary(tmp_path: Path):
    memory = ObjectMemory(tmp_path / "objects.jsonl")
    memory.remember_inventory([
        "/Game/Forest/Cabin/Floors/SM_Floor.SM_Floor",
        "/Game/Forest/Cabin/Walls/SM_Wall.SM_Wall",
        "/Game/Forest/Cabin/Doors/SM_Door.SM_Door",
        "/Game/Forest/Cabin/Roofs/SM_Roof.SM_Roof",
    ], source_fingerprint="SOURCE")

    projection = memory.retrieve("Build a weather-resistant cabin shelter")

    assert projection["concept_count"] == 1
    assert projection["memory_ids"][0] == "OBJECT-CONCEPT-SHELTER"
    assert "insulation between an interior and the exterior" in projection["text"]
    assert "substantially continuous protective boundary" in projection["text"]
    assert "deliberate boundary interfaces with fitted closures" in projection["text"]

    records = {item.object_type: item for item in memory.records()}
    assert "separates interior from ground" in records["floor_module"].affordances
    assert "insulates interior from exterior" in records["wall_module"].affordances
    assert "closes a deliberate shelter opening" in records["door_module"].affordances
    assert "insulates interior from exterior above" in records["roof_module"].affordances
