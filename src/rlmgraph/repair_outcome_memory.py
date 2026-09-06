from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


@dataclass(frozen=True)
class RepairOutcomeRecord:
    id: str
    task_id: int
    criterion: str
    observed_failure: str
    diagnosis: str
    attempted_change: str
    attempt: int
    target_passed: bool
    regressions: list[str]
    verified: bool
    action_memory_id: str
    evidence_refs: list[str]
    created_at: str


class RepairOutcomeMemoryStore(TokenizedMemoryStore):
    """Append-only causal repair history: failure, theory, action, and verification."""

    tokenization_mode = TokenizationMode.SIDECAR_INDEX

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self.token_index = TokenizedMemoryStore.token_index(self.path)

    def remember(
        self, *, task_id: int, criterion: str, diagnosis: str,
        attempted_change: str, attempt: int, target_passed: bool,
        regressions: list[str], action_memory_id: str,
        evidence_refs: list[str],
    ) -> RepairOutcomeRecord:
        key = f"{task_id}|{criterion}|{attempt}|{action_memory_id}"
        record_id = "REPAIR-OUTCOME-" + hashlib.sha256(key.encode()).hexdigest()[:12]
        for record in self.records():
            if record.id == record_id:
                return record
        verified = bool(target_passed and not regressions)
        record = RepairOutcomeRecord(
            id=record_id, task_id=task_id, criterion=criterion,
            observed_failure=f"Deterministic criterion {criterion} failed after implementation.",
            diagnosis=" ".join(diagnosis.split())[:500],
            attempted_change=" ".join(attempted_change.split())[:500],
            attempt=attempt, target_passed=target_passed,
            regressions=list(dict.fromkeys(regressions))[:12], verified=verified,
            action_memory_id=action_memory_id,
            evidence_refs=list(dict.fromkeys(evidence_refs))[:12],
            created_at=datetime.now(UTC).isoformat(),
        )
        self.token_index.remember(
            record.id, self._searchable(record),
            importance=.85 if record.verified else .3,
        )
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        return record

    def records(self) -> list[RepairOutcomeRecord]:
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(RepairOutcomeRecord(**json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return records

    def retrieve(self, query: str, *, limit: int = 6) -> list[RepairOutcomeRecord]:
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked = []
        for index, record in enumerate(self.records()):
            text = self._searchable(record)
            overlap = len(terms.intersection(self.token_index.terms(record.id, text)))
            hint = bool(re.search(
                r"\b(?:repair|fix|fail|wrong|diagnos|why)\w*\b", query, re.IGNORECASE
            ))
            if overlap or hint:
                ranked.append((overlap * 3 + (2 if hint else 0), index, record))
        ranked.sort(key=lambda item: (-item[0], -item[1]))
        return [item[2] for item in ranked[:limit]]

    @staticmethod
    def _searchable(record: RepairOutcomeRecord) -> str:
        return " ".join((record.criterion, record.observed_failure, record.diagnosis,
                         record.attempted_change, " ".join(record.regressions))).casefold()
