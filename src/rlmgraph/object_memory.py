from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar

from .memory_tokenization import extract_memory_concepts, hashed_memory_vector, tokenize_memory
from .model_call_ledger import exact_tokens
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


@dataclass(frozen=True)
class ObjectMemoryRecord:
    memory_id: str
    asset_path: str
    object_type: str
    intended_uses: tuple[str, ...]
    prohibited_uses: tuple[str, ...]
    affordances: tuple[str, ...]
    grounding_rule: str
    provenance: str
    source_fingerprint: str
    confidence: float
    verified: bool = True
    submission_derived: bool = False
    search_terms: tuple[str, ...] = ()
    intended_terms: tuple[str, ...] = ()
    prohibited_terms: tuple[str, ...] = ()
    affordance_terms: tuple[str, ...] = ()
    neural_vector: tuple[float, ...] = ()
    concepts: tuple[str, ...] = ()


class ObjectMemory(TokenizedMemoryStore):
    """Bounded semantic and affordance memory for verified source assets."""

    tokenization_mode = TokenizationMode.INLINE_RECORD
    SHELTER_CONCEPT: ClassVar[dict[str, object]] = {
        "memory_id": "OBJECT-CONCEPT-SHELTER",
        "concept": "shelter",
        "definition": (
            "A shelter is insulation between an interior and the exterior: its floor, walls, "
            "roof, and closures form a substantially continuous protective boundary that keeps "
            "outside conditions out and preserves a distinct inside space."
        ),
        "construction_invariants": (
            "close unintended gaps between floors, walls, wall corners, and roofs",
            "treat doors and windows as deliberate boundary interfaces with fitted closures, not holes",
            "align each closure to its aperture while preserving usable clearance and circulation",
            "avoid penetrations, severe overlaps, inverted pieces, and exposed interior seams",
            "verify the completed enclosure from both inside and outside",
        ),
    }

    def __init__(self, path: Path, *, char_budget: int = 6500, neural_ranker=None) -> None:
        self.path = path
        self.char_budget = char_budget
        self.neural_ranker = neural_ranker
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    @staticmethod
    def _semantics(path: str) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], str]:
        lowered = path.casefold()
        if "basicshapes/plane" in lowered:
            return (
                "surface_plane", ("ground surface", "path surface", "flat platform"),
                ("vegetation", "wall", "roof"),
                ("supports traversal when scaled and materially distinguished",),
                "place its surface at ground height; do not bury the traversable face",
            )
        categories = (
            ("/rocks/", "rock", ("natural dressing", "obstacle", "landmark"),
             ("path surface", "walkable corridor section", "wall", "door", "stairs"),
             ("blocks movement", "adds natural visual mass"),
             "may embed a small lower portion into ground, but must remain visibly rock-like"),
            ("/trees/", "tree", ("forest vegetation", "canopy", "natural obstacle"),
             ("path surface", "building structure", "roof", "wall"),
             ("creates canopy", "blocks traversal", "defines forest edge"),
             "root base may embed slightly; trunk remains world-Z-up"),
            ("grass", "grass", ("ground vegetation", "understory dressing", "edge dressing"),
             ("path surface", "building structure", "obstacle"),
             ("visually covers ground", "should not define collision or traversal"),
             "place at ground surface with only minor root embedding"),
            ("bush", "bush", ("understory vegetation", "forest-edge dressing", "soft obstacle"),
             ("path surface", "building structure", "door", "stairs"),
             ("fills understory", "requires clearance from entrances and structures"),
             "place at ground surface with minor root embedding"),
            ("fern", "fern", ("understory vegetation", "ground dressing"),
             ("path surface", "building structure"),
             ("fills shaded ground",), "place at ground surface"),
            ("flowers", "flowers", ("decorative ground vegetation", "path-border accent"),
             ("path surface", "building structure"),
             ("provides small visual accent",), "place at ground surface"),
            ("debris", "debris", ("environmental dressing", "small prop"),
             ("path surface", "building structure", "entrance connection"),
             ("adds local detail",), "rest on ground without unexplained burial"),
            ("/hut_misc/", "loose_log", ("forest prop", "dressing", "wood pile element"),
             ("path surface", "wall", "door", "stairs"),
             ("acts as a solid loose prop",), "rest on ground and avoid traversal routes"),
            ("/floors/", "floor_module", ("building floor", "platform"),
             ("vegetation", "roof", "path marker"),
             ("supports occupants", "defines building footprint", "separates interior from ground"),
             "top face remains above or level with ground"),
            ("/walls/", "wall_module", ("building wall", "enclosure", "door or window frame"),
             ("path surface", "vegetation", "floor", "roof"),
             ("connects edge-to-edge", "encloses space", "insulates interior from exterior"),
             "bottom edge meets floor or foundation"),
            ("/doors/", "door_module", ("building entrance", "wall opening closure"),
             ("path surface", "wall substitute without opening", "roof"),
             ("permits entrance", "must align to a door frame", "closes a deliberate shelter opening"),
             "bottom meets entrance floor elevation"),
            ("/roofs/", "roof_module", ("building roof", "weather cover"),
             ("path surface", "floor", "vegetation"),
             ("covers and caps a wall footprint", "insulates interior from exterior above"),
             "place above supported walls; never invert"),
            ("/stairs/", "stairs_module", ("entrance access", "elevation transition"),
             ("path surface by itself", "wall", "roof", "dressing"),
             ("connects two walkable elevations", "requires clear approach"),
             "lower end meets ground and upper end meets doorway or platform"),
            ("/supports/", "support_module", ("structural support", "beam", "foundation element"),
             ("path surface", "vegetation", "door"),
             ("supports or braces connected structure",), "must visibly connect supported geometry"),
        )
        for marker, kind, uses, prohibited, affordances, grounding in categories:
            if marker in lowered:
                return kind, uses, prohibited, affordances, grounding
        return (
            "unclassified_mesh", ("inspect before assigning a scene role",),
            ("critical traversal or structural role without semantic evidence",),
            ("unknown affordances",), "derive grounding from verified bounds and intended role",
        )

    def remember_inventory(
        self, asset_paths: list[str], *, source_fingerprint: str,
        submission_derived: bool = False,
    ) -> list[str]:
        if submission_derived:
            raise ValueError("Object memory cannot ingest benchmark submission objects.")
        existing = {record.memory_id: record for record in self.records()}
        remembered = []
        for path in sorted(set(asset_paths)):
            kind, uses, prohibited, affordances, grounding = self._semantics(path)
            memory_id = "OBJECT-" + hashlib.sha256(path.encode()).hexdigest()[:20]
            record = ObjectMemoryRecord(
                memory_id=memory_id, asset_path=path, object_type=kind,
                intended_uses=uses, prohibited_uses=prohibited,
                affordances=affordances, grounding_rule=grounding,
                provenance="VERIFIED_SOURCE_ASSET_PATH_SEMANTICS",
                source_fingerprint=source_fingerprint,
                confidence=.98 if kind != "unclassified_mesh" else .45,
                search_terms=tokenize_memory(" ".join((path, kind, *uses, *prohibited, *affordances))),
                intended_terms=tokenize_memory(" ".join(uses)),
                prohibited_terms=tokenize_memory(" ".join(prohibited)),
                affordance_terms=tokenize_memory(" ".join(affordances)),
                neural_vector=hashed_memory_vector(
                    tokenize_memory(" ".join((path, kind, *uses, *prohibited, *affordances))),
                ),
                concepts=extract_memory_concepts(
                    " ".join((path, kind, *uses, *prohibited, *affordances)),
                ),
            )
            existing[memory_id] = record
            remembered.append(memory_id)
        self.path.write_text(
            "".join(json.dumps(asdict(item), sort_keys=True) + "\n" for item in existing.values()),
            encoding="utf-8",
        )
        return remembered

    def records(self) -> list[ObjectMemoryRecord]:
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if value.get("verified") and not value.get("submission_derived"):
                    records.append(ObjectMemoryRecord(**value))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def retrieve(self, query: str) -> dict:
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked = []
        for record in self.records():
            searchable = " ".join((
                record.asset_path, record.object_type, *record.intended_uses,
                *record.prohibited_uses, *record.affordances,
            )).casefold()
            intended_terms = set(record.intended_terms or tokenize_memory(" ".join(record.intended_uses)))
            prohibited_terms = set(record.prohibited_terms or tokenize_memory(" ".join(record.prohibited_uses)))
            affordance_terms = set(record.affordance_terms or tokenize_memory(" ".join(record.affordances)))
            score = (
                len(terms.intersection(record.search_terms or tokenize_memory(searchable)))
                + 4 * len(terms.intersection(intended_terms))
                + 5 * len(terms.intersection(prohibited_terms))
                + 2 * len(terms.intersection(affordance_terms))
            )
            role_terms = {
                "path", "wall", "roof", "door", "stairs", "floor", "tree",
                "grass", "bush", "rock", "vegetation", "building", "ground",
            }
            score += 60 * len(terms.intersection(intended_terms).intersection(role_terms))
            score += 50 * len(terms.intersection(prohibited_terms).intersection(role_terms))
            if record.asset_path.casefold() in query.casefold():
                score += 20
            if score:
                ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], item[1].asset_path))
        neural_state = None
        if self.neural_ranker is not None:
            candidates = [(record.memory_id, " ".join((record.asset_path, record.object_type,
                           *record.intended_uses, *record.prohibited_uses, *record.affordances)),
                           score, "object", record.confidence,
                           record.neural_vector or hashed_memory_vector(tokenize_memory(searchable)),
                           record.search_terms or tokenize_memory(searchable))
                          for score, record in ranked
                          for searchable in [" ".join((record.asset_path, record.object_type,
                           *record.intended_uses, *record.prohibited_uses, *record.affordances))]]
            order, neural_state = self.neural_ranker.rank(query, candidates)
            positions = {memory_id: index for index, memory_id in enumerate(order)}
            ranked.sort(key=lambda item: (-item[0], positions[item[1].memory_id]))
        selected = []
        used = 2
        for score, record in ranked:
            payload = {**asdict(record), "relevance": score}
            for internal in ("search_terms", "intended_terms", "prohibited_terms",
                             "affordance_terms", "neural_vector"):
                payload.pop(internal, None)
            payload.pop("concepts", None)
            size = len(json.dumps(payload, separators=(",", ":")))
            if used + size > self.char_budget:
                continue
            selected.append(payload)
            used += size
        concepts = [self.SHELTER_CONCEPT]
        text = (
            "TGRAM OBJECT MEMORY (verified semantic roles, affordances, and object concepts; "
            "never substitute an object into a prohibited role):\n"
            + json.dumps({"concepts": concepts, "objects": selected}, separators=(",", ":"))
        )
        return {
            "text": text,
            "memory_ids": [self.SHELTER_CONCEPT["memory_id"], *[
                item["memory_id"] for item in selected
            ]],
            "record_count": len(selected),
            "concept_count": len(concepts),
            "characters": len(text),
            "tokens": exact_tokens(text),
            "submission_derived_records": 0,
            "world_neural_memory": neural_state,
        }
