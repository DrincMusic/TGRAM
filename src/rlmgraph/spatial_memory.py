from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .memory_tokenization import extract_memory_concepts, hashed_memory_vector, tokenize_memory
from .model_call_ledger import exact_tokens
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


@dataclass(frozen=True)
class SpatialMemoryRecord:
    memory_id: str
    relation: str
    subject_type: str
    object_type: str
    invariant: str
    verification_strategy: str
    concepts: tuple[str, ...]
    provenance: str = "TGRAM_VERIFIED_SPATIAL_ONTOLOGY"
    verified: bool = True
    submission_derived: bool = False
    search_terms: tuple[str, ...] = ()
    neural_vector: tuple[float, ...] = ()
    extracted_concepts: tuple[str, ...] = ()


class SpatialMemory(TokenizedMemoryStore):
    """Reusable scene relationships without retaining completed scene coordinates."""

    tokenization_mode = TokenizationMode.INLINE_RECORD

    DEFAULT_RELATIONS = (
        (
            "SUPPORTED_BY", "wall", "floor",
            "Each structural wall bottom contacts the floor or foundation footprint.",
            "Compare transformed wall bottom bounds with the supporting top plane.",
            ("building", "support", "wall", "floor", "contact"),
        ),
        (
            "COVERS", "roof", "wall_enclosure",
            "The roof remains world-up, above the walls, and covers their horizontal footprint.",
            "Check up vector, vertical ordering, and XY footprint overlap.",
            ("building", "roof", "cover", "upright", "footprint"),
        ),
        (
            "EDGE_CONNECTED", "wall_endpoint", "wall_endpoint",
            "Every perimeter wall endpoint meets another compatible endpoint within seam tolerance, except an intentional framed opening.",
            "Transform local connection ports to world space and build an endpoint adjacency graph.",
            ("building", "wall", "walls", "corner", "seam", "gap", "connection", "connected"),
        ),
        (
            "NON_OVERLAPPING", "collinear_wall", "collinear_wall",
            "Collinear wall intervals may meet at an edge but cannot occupy the same run.",
            "Project both wall bounds onto their shared structural axis and measure interval intersection.",
            ("building", "wall", "overlap", "interval", "collision"),
        ),
        (
            "ALIGNED_WITH", "door", "door_frame",
            "A door aligns with a framed wall opening in position, facing, and elevation.",
            "Compare entrance ports, horizontal facing axes, and bottom elevations.",
            ("building", "door", "frame", "entrance", "alignment"),
        ),
        (
            "ACCESSIBLE_FROM", "door", "stairs_or_path",
            "The entrance has a clear connected approach from the circulation network.",
            "Trace a continuous clearance corridor from path through stairs to the door.",
            ("access", "door", "stairs", "path", "clearance", "route"),
        ),
        (
            "CLEAR_OF", "circulation", "obstacle",
            "Paths, stairs, and door approaches remain clear of rocks, vegetation, walls, and props.",
            "Test obstacle bounds against the swept traversal corridor and entrance clearance volume.",
            ("access", "path", "stairs", "door", "rock", "vegetation", "collision"),
        ),
        (
            "GROUNDED_ON", "ordinary_actor", "ground_surface",
            "Ordinary actors rest on the ground and are not materially below it; only roots or explicitly embedded foundations receive a small exception.",
            "Compare transformed lower bounds with sampled ground height and the object's embedding policy.",
            ("ground", "placement", "bounds", "below", "embed", "tree"),
        ),
        (
            "CONTAINED_BY", "building_part", "assembly_envelope",
            "Every structural part belongs to the connected main assembly rather than floating as an orphan.",
            "Build a contact graph and require every structural node to reach the floor or foundation component.",
            ("building", "assembly", "orphan", "connected", "envelope"),
        ),
        (
            "SEPARATED_FROM", "vegetation", "structure",
            "Vegetation remains outside structural bounds and entrance clearance volumes.",
            "Use transformed world bounds or collision envelopes, not actor-origin distance alone.",
            ("vegetation", "building", "clearance", "bounds", "collision"),
        ),
        (
            "CONNECTED_TO", "path_section", "path_section",
            "Path sections form a continuous navigable corridor rather than isolated markers.",
            "Build a section adjacency graph and require a connected route between destination anchors.",
            ("path", "route", "connected", "navigation", "corridor"),
        ),
        (
            "OCCUPIES", "placed_actor", "spatial_ledger",
            "Before accepting a placement, register its transformed bounds, semantic role, grounding exception, and connection ports in a scene-local occupancy ledger.",
            "Reject placements whose ledger entry violates a required relation or prohibited overlap.",
            ("scene", "occupancy", "ledger", "bounds", "placement", "ports"),
        ),
    )

    def __init__(self, path: Path, *, char_budget: int = 6500, neural_ranker=None) -> None:
        self.path = path
        self.char_budget = char_budget
        self.neural_ranker = neural_ranker
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def seed_verified_ontology(self) -> list[str]:
        existing = {record.memory_id: record for record in self.records()}
        remembered = []
        for relation, subject, object_type, invariant, verification, concepts in self.DEFAULT_RELATIONS:
            memory_id = "SPATIAL-" + hashlib.sha256(
                json.dumps([relation, subject, object_type, invariant]).encode()
            ).hexdigest()[:20]
            record = SpatialMemoryRecord(
                memory_id=memory_id, relation=relation, subject_type=subject,
                object_type=object_type, invariant=invariant,
                verification_strategy=verification, concepts=concepts,
                search_terms=tokenize_memory(" ".join((relation, subject, object_type,
                                                     invariant, verification, *concepts))),
                neural_vector=hashed_memory_vector(tokenize_memory(" ".join((
                    relation, subject, object_type, invariant, verification, *concepts,
                )))),
                extracted_concepts=extract_memory_concepts(" ".join((
                    relation, subject, object_type, invariant, verification, *concepts,
                ))),
            )
            existing[memory_id] = record
            remembered.append(memory_id)
        self.path.write_text(
            "".join(json.dumps(asdict(item), sort_keys=True) + "\n" for item in existing.values()),
            encoding="utf-8",
        )
        return remembered

    def remember_relation(self, record: SpatialMemoryRecord) -> str:
        if record.submission_derived:
            raise ValueError("Spatial memory cannot ingest benchmark submission layouts.")
        if not record.verified:
            raise ValueError("Spatial memory accepts only verified reusable relations.")
        records = {item.memory_id: item for item in self.records()}
        records[record.memory_id] = record
        self.path.write_text(
            "".join(json.dumps(asdict(item), sort_keys=True) + "\n" for item in records.values()),
            encoding="utf-8",
        )
        return record.memory_id

    def records(self) -> list[SpatialMemoryRecord]:
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if value.get("verified") and not value.get("submission_derived"):
                    records.append(SpatialMemoryRecord(**value))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def retrieve(self, query: str) -> dict:
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked = []
        for record in self.records():
            record_terms = set(record.search_terms or tokenize_memory(" ".join((
                record.relation, record.subject_type, record.object_type, record.invariant,
                record.verification_strategy, *record.concepts,
            ))))
            overlap = terms.intersection(record_terms)
            if overlap:
                ranked.append((len(overlap), record))
        ranked.sort(key=lambda item: (-item[0], item[1].relation, item[1].memory_id))
        neural_state = None
        if self.neural_ranker is not None:
            candidates = [(record.memory_id, " ".join((record.relation, record.subject_type,
                           record.object_type, record.invariant, record.verification_strategy,
                           *record.concepts)), score, "spatial", 1.0,
                           record.neural_vector or hashed_memory_vector(record.search_terms),
                           record.search_terms)
                          for score, record in ranked]
            order, neural_state = self.neural_ranker.rank(query, candidates)
            positions = {memory_id: index for index, memory_id in enumerate(order)}
            ranked.sort(key=lambda item: (-item[0], positions[item[1].memory_id]))
        selected = []
        used = 2
        for score, record in ranked:
            payload = {**asdict(record), "relevance": score}
            payload.pop("search_terms", None)
            payload.pop("neural_vector", None)
            payload.pop("extracted_concepts", None)
            size = len(json.dumps(payload, separators=(",", ":")))
            if used + size > self.char_budget:
                continue
            selected.append(payload)
            used += size
        text = (
            "TGRAM SPATIAL MEMORY (reusable relation constraints; build a new scene-local "
            "occupancy graph, never copy a prior layout):\n"
            + json.dumps(selected, separators=(",", ":"))
        )
        return {
            "text": text,
            "memory_ids": [item["memory_id"] for item in selected],
            "record_count": len(selected),
            "characters": len(text),
            "tokens": exact_tokens(text),
            "submission_derived_records": 0,
            "world_neural_memory": neural_state,
        }
