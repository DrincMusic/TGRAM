from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore

_WORD = re.compile(r"[a-z][a-z0-9_]{2,}", re.IGNORECASE)
_SYMBOL = re.compile(r"`([^`]+)`")
_STOP = {
    "add", "allow", "and", "are", "current", "every", "for", "from", "into",
    "only", "preserve", "project", "return", "support", "task", "that", "the",
    "this", "through", "using", "with", "worker",
}


def _concepts(*values: str) -> list[str]:
    found: list[str] = []
    for value in values:
        for token in _WORD.findall(value.casefold()):
            if token not in _STOP and token not in found:
                found.append(token)
    return found[:24]


def _bounded_sentence(value: str, limit: int = 280) -> str:
    normalized = " ".join(value.split())
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    return sentence[:limit].rstrip()


@dataclass(frozen=True)
class ParsedActionMemory:
    id: str
    milestone_index: int
    phase: str
    action: str
    invariant: str
    concepts: list[str]
    files: list[str]
    symbols: list[str]
    evidence: str
    confidence: float
    archive_ref: str = ""
    fingerprint: str = ""
    supersedes: list[str] = field(default_factory=list)


class ProjectActionMemory(TokenizedMemoryStore):
    """Durable parsed actions with bounded relevance retrieval for fresh workers."""

    tokenization_mode = TokenizationMode.SIDECAR_INDEX

    def __init__(self, path: Path, *, max_records: int = 6, char_budget: int = 1800) -> None:
        self.path = path
        self.max_records = max_records
        self.char_budget = char_budget
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self.token_index = TokenizedMemoryStore.token_index(self.path)

    def remember(
        self, *, milestone_index: int, milestone: str, phase: str,
        rationale: str, files_changed: list[str], confidence: float,
        archive_ref: str = "", supersedes: list[str] | None = None,
    ) -> ParsedActionMemory:
        action = _bounded_sentence(rationale)
        symbols = list(dict.fromkeys(_SYMBOL.findall(rationale)))[:12]
        fingerprint_source = json.dumps({
            "milestone": milestone_index, "phase": phase, "action": action.casefold(),
            "invariant": _bounded_sentence(milestone, 220).casefold(),
            "files": sorted(set(files_changed)), "symbols": sorted(symbols),
        }, sort_keys=True)
        fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
        for existing in self.records():
            if existing.fingerprint == fingerprint:
                return existing
        record = ParsedActionMemory(
            id=str(uuid.uuid4()),
            milestone_index=milestone_index,
            phase=phase,
            action=action,
            invariant=_bounded_sentence(milestone, 220),
            concepts=_concepts(milestone, action, " ".join(files_changed), " ".join(symbols)),
            files=list(dict.fromkeys(files_changed))[:12],
            symbols=symbols,
            evidence=action,
            confidence=max(0.0, min(1.0, float(confidence))),
            archive_ref=archive_ref,
            fingerprint=fingerprint,
            supersedes=list(dict.fromkeys(supersedes or [])),
        )
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        self.token_index.remember(
            record.id, self._searchable(record), importance=record.confidence,
        )
        return record

    def records(self) -> list[ParsedActionMemory]:
        records: list[ParsedActionMemory] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(ParsedActionMemory(**json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def retrieve(self, query: str, *, current_milestone: int) -> list[dict]:
        query_concepts = set(_concepts(query))
        records = self.records()
        superseded = {memory_id for record in records for memory_id in record.supersedes}
        ranked: list[tuple[float, int, ParsedActionMemory]] = []
        for record in records:
            if record.id in superseded:
                continue
            cached_concepts = self.token_index.concepts(
                record.id, self._searchable(record),
            )
            overlap = len(query_concepts.intersection(cached_concepts))
            shared_file = sum(name.casefold() in query.casefold() for name in record.files)
            recency = 1 / (1 + max(0, current_milestone - record.milestone_index))
            review_bonus = 0.25 if record.phase == "REVIEW_AND_REPAIR" else 0.0
            score = (overlap * 3 + shared_file * 2 + recency + review_bonus) * (
                0.5 + record.confidence / 2
            )
            if overlap or shared_file or record.milestone_index == current_milestone:
                estimated_size = max(1, len(json.dumps(asdict(record), separators=(",", ":"))))
                ranked.append((score / estimated_size, estimated_size, record))
        ranked.sort(key=lambda item: (-item[0], -item[2].milestone_index, item[2].id))

        selected: list[dict] = []
        used = 2
        selected_concepts: set[str] = set()
        for utility, _, record in ranked[: self.max_records * 4]:
            redundancy = len(selected_concepts.intersection(record.concepts))
            adjusted_utility = utility / (1 + redundancy * 0.35)
            payload = {
                "memory_id": record.id,
                "milestone": record.milestone_index,
                "phase": record.phase,
                "action": record.action,
                "invariant": record.invariant,
                "concepts": record.concepts,
                "files": record.files,
                "symbols": record.symbols,
                "confidence": record.confidence,
                "archive_ref": record.archive_ref,
                "relevance": round(adjusted_utility, 6),
            }
            size = len(json.dumps(payload, separators=(",", ":")))
            if used + size > self.char_budget:
                continue
            selected.append(payload)
            selected_concepts.update(record.concepts)
            used += size
            if len(selected) >= self.max_records:
                break
        return selected

    @staticmethod
    def _searchable(record: ParsedActionMemory) -> str:
        return " ".join((record.phase, record.action, record.invariant,
                         " ".join(record.concepts), " ".join(record.files),
                         " ".join(record.symbols)))
