from __future__ import annotations

import json
import math
import os
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
CONCEPT_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "was", "with",
})


def tokenize_memory(text: str) -> tuple[str, ...]:
    """Normalize and deduplicate retrieval terms once, at memory write time."""
    return tuple(sorted(set(TOKEN_PATTERN.findall(text.casefold()))))


def extract_memory_concepts(text: str, limit: int = 32) -> tuple[str, ...]:
    """Extract stable lexical concepts while discarding grammatical filler."""
    counts: dict[str, int] = {}
    first: dict[str, int] = {}
    for ordinal, token in enumerate(TOKEN_PATTERN.findall(text.casefold())):
        if token in CONCEPT_STOP_WORDS or len(token) < 3:
            continue
        counts[token] = counts.get(token, 0) + 1
        first.setdefault(token, ordinal)
    return tuple(token for token, _ in sorted(
        counts.items(), key=lambda item: (-item[1], first[item[0]], item[0]),
    )[:limit])


def hashed_memory_vector(tokens: tuple[str, ...], dimensions: int = 32) -> tuple[float, ...]:
    """Persist the vector consumed by the world ranker instead of rebuilding it per query."""
    vector = [0.0] * dimensions
    for term in tokens:
        digest = sha256(term.encode()).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        vector[index] += 1.0 if digest[2] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return tuple(value / norm for value in vector)


class PersistentMemoryTokenIndex:
    """Sidecar cache for stores whose public record schema must stay prompt-clean."""

    def __init__(self, memory_path: Path) -> None:
        self.path = Path(f"{memory_path}.tokens.json")
        self.entries: dict[str, dict] = {}
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if value.get("version") == 1:
                    self.entries = dict(value.get("entries", {}))
            except (OSError, ValueError, TypeError):
                pass

    def remember(self, memory_id: str, text: str, *, importance: float = .5,
                 protected: bool = False) -> dict:
        fingerprint = sha256(text.encode()).hexdigest()
        cached = self.entries.get(memory_id)
        if cached and cached.get("fingerprint") == fingerprint:
            cached["last_accessed"] = datetime.now(UTC).isoformat()
            cached["access_count"] = int(cached.get("access_count", 0)) + 1
            cached["importance"] = max(float(cached.get("importance", 0)), importance)
            cached["protected"] = bool(cached.get("protected", False) or protected)
            self._save()
            return cached
        terms = tokenize_memory(text)
        cached = {
            "fingerprint": fingerprint,
            "terms": list(terms),
            "concepts": list(extract_memory_concepts(text)),
            "vector": list(hashed_memory_vector(terms)),
            "importance": max(0.0, min(1.0, importance)),
            "protected": protected,
            "access_count": 1,
            "last_accessed": datetime.now(UTC).isoformat(),
        }
        self.entries[memory_id] = cached
        self._save()
        self.release_unimportant()
        return cached

    def terms(self, memory_id: str, text: str) -> set[str]:
        return set(self.remember(memory_id, text)["terms"])

    def vector(self, memory_id: str, text: str) -> tuple[float, ...]:
        return tuple(self.remember(memory_id, text)["vector"])

    def concepts(self, memory_id: str, text: str) -> set[str]:
        return set(self.remember(memory_id, text)["concepts"])

    def release_unimportant(self, *, max_entries: int = 5000) -> list[str]:
        """Evict the least useful unprotected tokenized memories when capacity is exceeded."""
        excess = len(self.entries) - max_entries
        if excess <= 0:
            return []
        candidates = [
            (float(value.get("importance", .5)), int(value.get("access_count", 0)),
             str(value.get("last_accessed", "")), memory_id)
            for memory_id, value in self.entries.items() if not value.get("protected")
        ]
        released = [item[3] for item in sorted(candidates)[:excess]]
        for memory_id in released:
            self.entries.pop(memory_id, None)
        if released:
            self._save()
        return released

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, "entries": self.entries}),
                                 encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
