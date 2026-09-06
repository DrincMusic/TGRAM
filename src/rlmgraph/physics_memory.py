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
class PhysicsMemoryRecord:
    memory_id: str
    principle: str
    invariant: str
    verification_strategy: str
    exceptions: tuple[str, ...]
    concepts: tuple[str, ...]
    provenance: str = "TGRAM_VERIFIED_PHYSICS_ONTOLOGY"
    verified: bool = True
    submission_derived: bool = False
    search_terms: tuple[str, ...] = ()
    neural_vector: tuple[float, ...] = ()
    extracted_concepts: tuple[str, ...] = ()


class PhysicsMemory(TokenizedMemoryStore):
    """Reusable physical plausibility constraints without retaining prior scenes."""

    tokenization_mode = TokenizationMode.INLINE_RECORD

    DEFAULT_PRINCIPLES = (
        (
            "GRAVITY_SUPPORT",
            "Every ordinary solid actor has either direct ground contact or an indirect, role-correct chain of supporting objects that eventually reaches ground. Elevated objects should not all be moved down to terrain.",
            "Build a directed support graph from transformed contact bounds and require every solid node to reach ground.",
            ("explicit suspension", "declared flying object", "physically simulated transient state"),
            ("gravity", "support", "ground", "floating", "solid", "contact"),
        ),
        (
            "DIRECTIONAL_SUPPORT_ROLES",
            "Support is directional and semantic: ground supports foundations and lower stairs; lower walls or columns support an upper floor; that floor supports upper walls; upper walls support the roof. A supported object does not automatically support its supporter.",
            "Label every contact edge supporter-to-supported, require an allowed role pairing, and require load direction to descend without cycles.",
            ("engineered role documented by the asset or design",),
            ("support", "direction", "wall", "floor", "roof", "stairs", "ground", "load"),
        ),
        (
            "INVALID_SUPPORT_ROLES",
            "Doors, vegetation, loose props, decorative ceilings, and roof coverings are not load-bearing supports for walls or floors. A ceiling may have walls above only when it is explicitly a structural floor slab with support below.",
            "Reject contact edges whose supporter role cannot carry the supported role, even when their bounds touch.",
            ("explicitly modeled structural slab, beam, or column",),
            ("invalid", "support", "door", "vegetation", "prop", "ceiling", "wall", "floor", "roof"),
        ),
        (
            "CONTACT_NOT_PROXIMITY",
            "Visual proximity is not support: supported and supporting surfaces must overlap horizontally and meet vertically within tolerance.",
            "Compare transformed support surfaces and contact patches rather than actor origins.",
            (), ("support", "contact", "bounds", "overlap", "proximity"),
        ),
        (
            "LOAD_PATH",
            "Upper floors and roofs transfer support through walls, beams, or columns to a grounded foundation.",
            "Trace each elevated structural component through lower supporting components to ground.",
            ("engineered cantilever with connected support",),
            ("building", "floor", "roof", "wall", "beam", "foundation", "support"),
        ),
        (
            "STABLE_ORIENTATION",
            "Structural pieces preserve a physically stable up direction and cannot be upside-down unless their designed role explicitly requires it.",
            "Check transformed up vectors, contact footprint, and center-of-mass projection.",
            ("purpose-built inverted fixture",),
            ("building", "upright", "orientation", "roof", "wall", "stability"),
        ),
        (
            "STAIR_ENDPOINT_CONTACT",
            "A stair flight connects two elevations: its lower endpoint contacts the lower walkable surface and its upper endpoint meets the destination threshold.",
            "Transform stair endpoint bounds and compare lower/top elevations plus horizontal contact with both surfaces.",
            (), ("stairs", "door", "floor", "entrance", "endpoint", "contact", "access"),
        ),
        (
            "GROUNDING",
            "Placed objects rest on the ground surface without unexplained burial or positive vertical gaps.",
            "Compare transformed lower bounds with sampled ground height using the object's embedding allowance.",
            ("tree roots", "buried foundation", "underground object", "declared suspension"),
            ("ground", "floating", "buried", "tree", "placement", "height"),
        ),
        (
            "COLLISION_EXCLUSION",
            "Independent solid objects cannot deeply occupy the same volume merely to appear connected.",
            "Measure transformed collision-volume intersection while permitting narrow designed seams.",
            ("designed socket", "small structural seam", "explicit boolean assembly"),
            ("collision", "overlap", "solid", "seam", "intersection"),
        ),
        (
            "PHYSICS_EXCEPTION_EXPLICITNESS",
            "If a placement appears to violate gravity, the construction must identify a real support, suspension, buoyancy, propulsion, or other explicit physical mechanism.",
            "Reject unexplained exceptions; Unreal's ability to freeze an actor in space is not physical justification.",
            ("supported", "suspended", "buoyant", "propelled"),
            ("physics", "exception", "floating", "magic", "mechanism", "unreal"),
        ),
    )

    def __init__(self, path: Path, *, char_budget: int = 5200, neural_ranker=None) -> None:
        self.path = path
        self.char_budget = char_budget
        self.neural_ranker = neural_ranker
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def seed_verified_ontology(self) -> list[str]:
        existing = {record.memory_id: record for record in self.records()}
        remembered = []
        for principle, invariant, verification, exceptions, concepts in self.DEFAULT_PRINCIPLES:
            memory_id = "PHYSICS-" + hashlib.sha256(
                json.dumps([principle, invariant, verification]).encode()
            ).hexdigest()[:20]
            existing[memory_id] = PhysicsMemoryRecord(
                memory_id=memory_id, principle=principle, invariant=invariant,
                verification_strategy=verification, exceptions=exceptions,
                concepts=concepts,
                search_terms=tokenize_memory(" ".join((principle, invariant, verification,
                                                     *exceptions, *concepts))),
                neural_vector=hashed_memory_vector(tokenize_memory(" ".join((
                    principle, invariant, verification, *exceptions, *concepts,
                )))),
                extracted_concepts=extract_memory_concepts(" ".join((
                    principle, invariant, verification, *exceptions, *concepts,
                ))),
            )
            remembered.append(memory_id)
        self.path.write_text(
            "".join(json.dumps(asdict(item), sort_keys=True) + "\n" for item in existing.values()),
            encoding="utf-8",
        )
        return remembered

    def records(self) -> list[PhysicsMemoryRecord]:
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if value.get("verified") and not value.get("submission_derived"):
                    records.append(PhysicsMemoryRecord(**value))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def retrieve(self, query: str) -> dict:
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked = []
        for record in self.records():
            searchable = " ".join((
                record.principle, record.invariant, record.verification_strategy,
                *record.exceptions, *record.concepts,
            )).casefold()
            overlap = terms.intersection(record.search_terms or tokenize_memory(searchable))
            if overlap:
                ranked.append((len(overlap), record))
        ranked.sort(key=lambda item: (-item[0], item[1].principle))
        neural_state = None
        if self.neural_ranker is not None:
            candidates = [(record.memory_id, " ".join((record.principle, record.invariant,
                           record.verification_strategy, *record.exceptions, *record.concepts)),
                           score, "physics", 1.0,
                           record.neural_vector or hashed_memory_vector(tokenize_memory(searchable)),
                           record.search_terms or tokenize_memory(searchable))
                          for score, record in ranked
                          for searchable in [" ".join((record.principle, record.invariant,
                           record.verification_strategy, *record.exceptions, *record.concepts))]]
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
            "TGRAM PHYSICS MEMORY (physical plausibility constraints; Unreal transform freedom "
            "does not justify unsupported floating objects):\n"
            + json.dumps(selected, separators=(",", ":"))
        )
        return {
            "text": text,
            "memory_ids": [item["memory_id"] for item in selected],
            "record_count": len(selected), "characters": len(text),
            "tokens": exact_tokens(text), "submission_derived_records": 0,
            "world_neural_memory": neural_state,
        }
