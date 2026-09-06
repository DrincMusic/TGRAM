from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .memory_tokenization import (
    extract_memory_concepts,
    hashed_memory_vector,
    tokenize_memory,
)
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore

_TOKEN = re.compile(r"[a-z][a-z0-9_]{2,}", re.IGNORECASE)
_CANARY = re.compile(r"[A-F0-9]{12}")
_SHA256 = re.compile(r"[a-f0-9]{64}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in _TOKEN.findall(value)}


@dataclass(frozen=True, slots=True)
class ContinuityMemoryRecord:
    memory_id: str
    project_scope: str
    origin_task_id: str
    claim_type: str
    semantic_rule: str
    field_order: tuple[str, ...]
    run_canary: str
    verification_status: str
    worker_model: str
    worker_output_digest: str
    semantic_validator_digest: str
    test_result_digest: str
    candidate_patch_digest: str
    candidate_promoted: bool
    created_after_validation: bool
    created_at: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ContinuityRetrieval:
    query: str
    project_scope: str
    candidate_memories: tuple[dict[str, object], ...]
    selected_memory: dict[str, object] | None
    selection_reason: str


class ProjectContinuityMemory(TokenizedMemoryStore):
    """Exact-scope, evidence-gated persistent memory for cross-task continuity."""

    tokenization_mode = TokenizationMode.SIDECAR_INDEX

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self.token_index = TokenizedMemoryStore.token_index(self.path)

    @staticmethod
    def _validate_digest(value: str, label: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        return value

    def remember(
        self,
        *,
        project_scope: str,
        origin_task_id: str,
        claim_type: str,
        semantic_rule: str,
        field_order: tuple[str, ...],
        run_canary: str,
        verification_status: str,
        worker_model: str,
        worker_output_digest: str,
        semantic_validator_digest: str,
        test_result_digest: str,
        candidate_patch_digest: str,
        candidate_promoted: bool,
        created_after_validation: bool,
        memory_id: str | None = None,
    ) -> ContinuityMemoryRecord:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                project_scope,
                origin_task_id,
                claim_type,
                semantic_rule,
                worker_model,
            )
        ):
            raise ValueError("Continuity memory text fields must not be empty.")
        if (
            not isinstance(field_order, tuple)
            or len(field_order) != 3
            or len(set(field_order)) != 3
            or not all(isinstance(value, str) and value.strip() for value in field_order)
        ):
            raise ValueError("Continuity field order must contain three distinct fields.")
        if not _CANARY.fullmatch(run_canary):
            raise ValueError("Continuity canary must be twelve uppercase hexadecimal characters.")
        for value, label in (
            (worker_output_digest, "worker output digest"),
            (semantic_validator_digest, "semantic validator digest"),
            (test_result_digest, "test result digest"),
            (candidate_patch_digest, "candidate patch digest"),
        ):
            self._validate_digest(value, label)
        if verification_status not in {"PROPOSED", "VERIFIED"}:
            raise ValueError("Continuity memory status must be PROPOSED or VERIFIED.")
        if type(candidate_promoted) is not bool or type(created_after_validation) is not bool:
            raise ValueError("Continuity provenance flags must be booleans.")
        if verification_status == "VERIFIED" and (
            candidate_promoted or not created_after_validation
        ):
            raise ValueError(
                "Verified continuity memory requires a discarded candidate and post-validation write."
            )
        body = {
            "memory_id": memory_id or f"CONTINUITY-{uuid.uuid4().hex}",
            "project_scope": project_scope,
            "origin_task_id": origin_task_id,
            "claim_type": claim_type,
            "semantic_rule": semantic_rule,
            "field_order": tuple(field_order),
            "run_canary": run_canary,
            "verification_status": verification_status,
            "worker_model": worker_model,
            "worker_output_digest": worker_output_digest,
            "semantic_validator_digest": semantic_validator_digest,
            "test_result_digest": test_result_digest,
            "candidate_patch_digest": candidate_patch_digest,
            "candidate_promoted": candidate_promoted,
            "created_after_validation": created_after_validation,
            "created_at": datetime.now(UTC).isoformat(),
        }
        record = ContinuityMemoryRecord(**body, content_sha256=_sha256_json(body))
        integrity_ok, integrity_errors = self.verify_integrity()
        if not integrity_ok:
            raise ValueError(
                "Existing continuity memory failed integrity: "
                + "; ".join(integrity_errors)
            )
        for existing in self.records():
            if existing.memory_id == record.memory_id:
                if existing != record:
                    raise ValueError("Continuity memory identifier has conflicting content.")
                return existing
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(_canonical_json(asdict(record)) + "\n")
        self.token_index.remember(
            record.memory_id,
            self._searchable(record),
            importance=1.0 if verification_status == "VERIFIED" else 0.1,
        )
        return record

    def records(self) -> list[ContinuityMemoryRecord]:
        records: list[ContinuityMemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            raw["field_order"] = tuple(raw["field_order"])
            records.append(ContinuityMemoryRecord(**raw))
        return records

    def retrieve(self, query: str, *, project_scope: str) -> ContinuityRetrieval:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Continuity retrieval query must not be empty.")
        if not isinstance(project_scope, str) or not project_scope.strip():
            raise ValueError("Continuity retrieval scope must not be empty.")
        integrity_ok, integrity_errors = self.verify_integrity()
        if not integrity_ok:
            raise ValueError(
                "Continuity memory integrity failed: " + "; ".join(integrity_errors)
            )
        query_tokens = _tokens(query)
        candidates: list[dict[str, object]] = []
        eligible: list[tuple[int, ContinuityMemoryRecord]] = []
        for record in self.records():
            cached = self.token_index.concepts(
                record.memory_id, self._searchable(record)
            )
            overlap = len(query_tokens.intersection(cached))
            scope_match = record.project_scope == project_scope
            verified = record.verification_status == "VERIFIED"
            safe = not record.candidate_promoted and record.created_after_validation
            selected_eligible = scope_match and verified and safe and overlap > 0
            rejection_reasons = []
            if not scope_match:
                rejection_reasons.append("WRONG_SCOPE")
            if not verified:
                rejection_reasons.append("NOT_VERIFIED")
            if not safe:
                rejection_reasons.append("INVALID_PROVENANCE")
            if overlap == 0:
                rejection_reasons.append("NO_SEMANTIC_OVERLAP")
            candidates.append(
                {
                    "memory_id": record.memory_id,
                    "verification_status": record.verification_status,
                    "project_scope": record.project_scope,
                    "content_sha256": record.content_sha256,
                    "semantic_overlap": overlap,
                    "eligible": selected_eligible,
                    "rejection_reasons": rejection_reasons,
                }
            )
            if selected_eligible:
                eligible.append((overlap, record))
        eligible.sort(key=lambda item: (-item[0], item[1].memory_id))
        selected = eligible[0][1] if eligible else None
        selected_payload = (
            {
                "memory_id": selected.memory_id,
                "project_scope": selected.project_scope,
                "origin_task_id": selected.origin_task_id,
                "claim_type": selected.claim_type,
                "semantic_rule": selected.semantic_rule,
                "field_order": list(selected.field_order),
                "run_canary": selected.run_canary,
                "verification_status": selected.verification_status,
                "content_sha256": selected.content_sha256,
            }
            if selected
            else None
        )
        return ContinuityRetrieval(
            query=query,
            project_scope=project_scope,
            candidate_memories=tuple(candidates),
            selected_memory=selected_payload,
            selection_reason=(
                "Highest semantic overlap among exact-scope VERIFIED memories."
                if selected
                else "No exact-scope VERIFIED memory had semantic overlap."
            ),
        )

    def verify_integrity(self) -> tuple[bool, tuple[str, ...]]:
        errors: list[str] = []
        seen: set[str] = set()
        try:
            records = self.records()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return False, (f"Unreadable continuity memory: {exc}",)
        for record in records:
            if record.memory_id in seen:
                errors.append(f"Duplicate memory id: {record.memory_id}")
            seen.add(record.memory_id)
            body = asdict(record)
            expected = body.pop("content_sha256")
            text_values = {
                "memory_id": record.memory_id,
                "project_scope": record.project_scope,
                "origin_task_id": record.origin_task_id,
                "claim_type": record.claim_type,
                "semantic_rule": record.semantic_rule,
                "worker_model": record.worker_model,
                "created_at": record.created_at,
            }
            if any(not isinstance(value, str) or not value.strip() for value in text_values.values()):
                errors.append(f"Invalid continuity text field: {record.memory_id!r}")
            if (
                not isinstance(record.field_order, tuple)
                or len(record.field_order) != 3
                or len(set(record.field_order)) != 3
                or not all(
                    isinstance(value, str) and value.strip()
                    for value in record.field_order
                )
            ):
                errors.append(f"Invalid continuity field order: {record.memory_id!r}")
            if not isinstance(record.run_canary, str) or not _CANARY.fullmatch(record.run_canary):
                errors.append(f"Invalid continuity canary: {record.memory_id!r}")
            if record.verification_status not in {"PROPOSED", "VERIFIED"}:
                errors.append(f"Invalid continuity status: {record.memory_id!r}")
            for label, value in (
                ("worker output", record.worker_output_digest),
                ("semantic validator", record.semantic_validator_digest),
                ("test result", record.test_result_digest),
                ("candidate patch", record.candidate_patch_digest),
                ("content", record.content_sha256),
            ):
                if not isinstance(value, str) or not _SHA256.fullmatch(value):
                    errors.append(
                        f"Invalid {label} digest: {record.memory_id!r}"
                    )
            if type(record.candidate_promoted) is not bool or type(record.created_after_validation) is not bool:
                errors.append(f"Invalid continuity provenance flags: {record.memory_id!r}")
            try:
                datetime.fromisoformat(record.created_at)
            except (TypeError, ValueError):
                errors.append(f"Invalid continuity timestamp: {record.memory_id!r}")
            if not isinstance(expected, str) or _sha256_json(body) != expected:
                errors.append(f"Continuity memory hash mismatch: {record.memory_id}")
            if record.verification_status == "VERIFIED" and (
                record.candidate_promoted or not record.created_after_validation
            ):
                errors.append(f"Invalid verified provenance: {record.memory_id}")
        token_path = self.token_index.path
        try:
            token_payload = json.loads(token_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            token_payload = {"version": 1, "entries": {}} if not records else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"Unreadable continuity token index: {exc}")
            token_payload = None
        entries: object = None
        if isinstance(token_payload, dict) and token_payload.get("version") == 1:
            entries = token_payload.get("entries")
        elif token_payload is not None:
            errors.append("Invalid continuity token index schema.")
        if not isinstance(entries, dict):
            if records:
                errors.append("Continuity token index entries are missing.")
        else:
            if set(entries) != {record.memory_id for record in records}:
                errors.append("Continuity token index inventory does not match records.")
            for record in records:
                entry = entries.get(record.memory_id)
                if not isinstance(entry, dict):
                    errors.append(f"Missing continuity token entry: {record.memory_id}")
                    continue
                searchable = self._searchable(record)
                terms = tokenize_memory(searchable)
                expected_entry = {
                    "fingerprint": hashlib.sha256(searchable.encode()).hexdigest(),
                    "terms": list(terms),
                    "concepts": list(extract_memory_concepts(searchable)),
                    "vector": list(hashed_memory_vector(terms)),
                }
                for key, value in expected_entry.items():
                    if entry.get(key) != value:
                        errors.append(
                            f"Continuity token entry mismatch ({key}): {record.memory_id}"
                        )
        return not errors, tuple(errors)

    @staticmethod
    def _searchable(record: ContinuityMemoryRecord) -> str:
        return " ".join(
            (
                record.claim_type,
                record.semantic_rule,
                " ".join(record.field_order),
            )
        )


__all__ = [
    "ContinuityMemoryRecord",
    "ContinuityRetrieval",
    "ProjectContinuityMemory",
]
