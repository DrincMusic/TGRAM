from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .memory_tokenization import extract_memory_concepts, hashed_memory_vector, tokenize_memory
from .model_call_ledger import exact_tokens
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


@dataclass(frozen=True)
class GeometricMemoryRecord:
    memory_id: str
    asset_path: str
    semantic_kind: str
    dimensions: tuple[float, float, float]
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    pivot_offset_from_center: tuple[float, float, float]
    up_axis: str
    primary_axis: str
    thickness_axis: str
    connection_ports: tuple[dict, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    provenance: str = "UNREAL_SOURCE_ASSET_PROBE"
    source_fingerprint: str = ""
    verified: bool = True
    submission_derived: bool = False
    search_terms: tuple[str, ...] = field(default_factory=tuple)
    neural_vector: tuple[float, ...] = field(default_factory=tuple)
    concepts: tuple[str, ...] = field(default_factory=tuple)


class GeometricMemory(TokenizedMemoryStore):
    """Verified spatial facts and reusable constraints for bounded TGRAM workers."""

    tokenization_mode = TokenizationMode.INLINE_RECORD

    def __init__(self, path: Path, *, char_budget: int = 8000, neural_ranker=None) -> None:
        self.path = path
        self.char_budget = char_budget
        self.neural_ranker = neural_ranker
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    @staticmethod
    def _kind(path: str) -> str:
        lowered = path.casefold()
        for kind in ("wall", "floor", "roof", "door", "stairs", "support"):
            if f"/{kind}s/" in lowered or f"_{kind}_" in lowered:
                return kind
        return "generic_mesh"

    @staticmethod
    def _axes(dimensions: tuple[float, float, float]) -> tuple[str, str]:
        horizontal = (("X", dimensions[0]), ("Y", dimensions[1]))
        primary = max(horizontal, key=lambda item: item[1])[0]
        thickness = min(horizontal, key=lambda item: item[1])[0]
        return primary, thickness

    @staticmethod
    def _ports(
        kind: str, bounds_min: tuple[float, float, float],
        bounds_max: tuple[float, float, float], primary: str,
    ) -> tuple[dict, ...]:
        center = tuple((low + high) / 2 for low, high in zip(bounds_min, bounds_max))
        if kind in {"wall", "support"}:
            axis = 0 if primary == "X" else 1
            negative = list(center)
            positive = list(center)
            negative[axis] = bounds_min[axis]
            positive[axis] = bounds_max[axis]
            return (
                {"name": "edge_negative", "local_position": negative, "axis": primary},
                {"name": "edge_positive", "local_position": positive, "axis": primary},
            )
        if kind in {"door", "stairs"}:
            return ({"name": "entrance_interface", "local_position": list(center)},)
        if kind in {"floor", "roof"}:
            return tuple(
                {"name": f"edge_{axis}_{side}", "axis": axis, "coordinate": value}
                for axis, low, high in (
                    ("X", bounds_min[0], bounds_max[0]),
                    ("Y", bounds_min[1], bounds_max[1]),
                )
                for side, value in (("negative", low), ("positive", high))
            )
        return ()

    @staticmethod
    def _constraints(kind: str) -> tuple[str, ...]:
        common = (
            "derive world placement from transformed bounds and pivot, not actor origin alone",
            "use named pitch/yaw/roll arguments and preserve world Z as up",
            "reject deep volume intersection and unexplained below-ground bounds",
        )
        specialized = {
            "wall": (
                "connect transformed endpoint ports within seam tolerance",
                "collinear wall intervals may touch but must not overlap or leave gaps",
                "wall runs must cover at least two horizontal axes and form an enclosure",
            ),
            "floor": ("support the wall footprint and remain level",),
            "roof": (
                "remain non-inverted above walls and cover the structural footprint",
            ),
            "door": ("align with a wall opening and retain accessible clearance",),
            "stairs": (
                "connect ground access to a door and remain clear of rocks and structure",
            ),
            "support": ("connect to and support the main assembly",),
        }
        return common + specialized.get(kind, ())

    def remember_probe(self, values: list[dict], *, source_fingerprint: str) -> list[str]:
        existing = {record.memory_id: record for record in self.records()}
        remembered = []
        for value in values:
            if value.get("submission_derived"):
                raise ValueError("Geometric memory cannot ingest benchmark submission geometry.")
            path = str(value["path"])
            dimensions = tuple(float(item) for item in value["dimensions"])
            bounds_min = tuple(float(item) for item in value["bounds_min"])
            bounds_max = tuple(float(item) for item in value["bounds_max"])
            pivot = tuple(float(item) for item in value["pivot_offset_from_center"])
            if not all(len(item) == 3 for item in (dimensions, bounds_min, bounds_max, pivot)):
                raise ValueError("Geometric probe vectors must have exactly three components.")
            kind = self._kind(path)
            primary, thickness = self._axes(dimensions)
            memory_id = "GEOMETRY-" + hashlib.sha256(
                json.dumps([path, dimensions, bounds_min, bounds_max, pivot], sort_keys=True).encode()
            ).hexdigest()[:20]
            record = GeometricMemoryRecord(
                memory_id=memory_id,
                asset_path=path,
                semantic_kind=kind,
                dimensions=dimensions,
                bounds_min=bounds_min,
                bounds_max=bounds_max,
                pivot_offset_from_center=pivot,
                up_axis="Z",
                primary_axis=primary,
                thickness_axis=thickness,
                connection_ports=self._ports(kind, bounds_min, bounds_max, primary),
                constraints=self._constraints(kind),
                source_fingerprint=source_fingerprint,
                search_terms=tokenize_memory(" ".join((path, kind, *self._constraints(kind)))),
                neural_vector=hashed_memory_vector(
                    tokenize_memory(" ".join((path, kind, *self._constraints(kind)))),
                ),
                concepts=extract_memory_concepts(
                    " ".join((path, kind, *self._constraints(kind))),
                ),
            )
            existing[memory_id] = record
            remembered.append(memory_id)
        self.path.write_text(
            "".join(json.dumps(asdict(item), sort_keys=True) + "\n" for item in existing.values()),
            encoding="utf-8",
        )
        return remembered

    def records(self) -> list[GeometricMemoryRecord]:
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if value.get("verified") and not value.get("submission_derived"):
                    records.append(GeometricMemoryRecord(**value))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def retrieve(self, query: str) -> dict:
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked = []
        for record in self.records():
            searchable = " ".join((
                record.asset_path, record.semantic_kind, *record.constraints,
            )).casefold()
            cached_terms = record.search_terms or tokenize_memory(searchable)
            score = len(terms.intersection(cached_terms))
            if record.asset_path.casefold() in query.casefold():
                score += 100
            if score:
                ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], item[1].asset_path))
        neural_state = None
        if self.neural_ranker is not None:
            candidates = [(record.memory_id, searchable, score, "geometry", 1.0,
                           record.neural_vector or hashed_memory_vector(tokenize_memory(searchable)),
                           record.search_terms or tokenize_memory(searchable))
                          for score, record in ranked
                          for searchable in [" ".join((record.asset_path, record.semantic_kind, *record.constraints))]]
            order, neural_state = self.neural_ranker.rank(query, candidates)
            positions = {memory_id: index for index, memory_id in enumerate(order)}
            ranked.sort(key=lambda item: (-item[0], positions[item[1].memory_id]))
        selected = []
        used = 2
        for score, record in ranked:
            payload = {**asdict(record), "relevance": score}
            payload.pop("search_terms", None)
            payload.pop("neural_vector", None)
            payload.pop("concepts", None)
            size = len(json.dumps(payload, separators=(",", ":")))
            if used + size > self.char_budget:
                continue
            selected.append(payload)
            used += size
        text = (
            "TGRAM GEOMETRIC MEMORY (verified source facts; constraints, not a saved layout):\n"
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
