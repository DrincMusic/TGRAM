from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .sqlite_utils import ClosingSQLiteConnection

CLAIM_SCHEMA = "rlmgraph-claim-statement-v1"
EVIDENCE_SCHEMA = "rlmgraph-claim-evidence-v1"
EVENT_SCHEMA = "rlmgraph-claim-state-event-v1"
AUTHENTICATION_SCHEMA = "rlmgraph-claim-authentication-v1"
AUTHENTICATION_PURPOSE = "RLMGRAPH_CLAIM_EVIDENCE_V1"


class ClaimEvidenceLedgerError(RuntimeError):
    """Base error for fail-closed claim-evidence operations."""


class DuplicatePayloadError(ClaimEvidenceLedgerError):
    """An existing immutable identifier was presented with different content."""


class EvidenceIntegrityError(ClaimEvidenceLedgerError):
    """An evidence artifact does not match its declared content hash."""


class ClaimTransitionError(ClaimEvidenceLedgerError):
    """A requested terminal or authentication transition is not eligible."""


class EvidenceLevel(StrEnum):
    PROPOSED = "PROPOSED"
    OBSERVED = "OBSERVED"
    TESTED = "TESTED"
    REPLICATED = "REPLICATED"


class ClaimDisposition(StrEnum):
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AuthenticationState(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    AUTHENTICATED = "AUTHENTICATED"
    INVALID = "INVALID"


class ClaimDisplayState(StrEnum):
    PROPOSED = "PROPOSED"
    OBSERVED = "OBSERVED"
    TESTED = "TESTED"
    REPLICATED = "REPLICATED"
    AUTHENTICATED = "AUTHENTICATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EvidenceKind(StrEnum):
    AGENT_REPORT = "AGENT_REPORT"
    SOURCE_OBSERVATION = "SOURCE_OBSERVATION"
    TEST_RUN = "TEST_RUN"
    REPLICATION_RUN = "REPLICATION_RUN"
    COUNTEREVIDENCE = "COUNTEREVIDENCE"


class EvidenceOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INAPPLICABLE = "INAPPLICABLE"


@dataclass(frozen=True, slots=True)
class ClaimStatement:
    claim_id: str
    subject: str
    assertion: str
    source_manifest_sha256: str
    policy_sha256: str
    required_test_spec_sha256: str
    schema_version: str = CLAIM_SCHEMA


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    evidence_id: str
    claim_id: str
    kind: EvidenceKind
    artifact_path: str
    artifact_sha256: str
    source_manifest_sha256: str
    policy_sha256: str
    producer_id: str
    outcome: EvidenceOutcome = EvidenceOutcome.INAPPLICABLE
    test_spec_sha256: str | None = None
    run_id: str | None = None
    independence_key: str | None = None
    detail: str = ""
    schema_version: str = EVIDENCE_SCHEMA


@dataclass(frozen=True, slots=True)
class ClaimAssessment:
    claim_id: str
    evidence_level: EvidenceLevel
    disposition: ClaimDisposition
    authentication: AuthenticationState
    display_state: ClaimDisplayState
    evidence_ids: tuple[str, ...]
    eligible_evidence_ids: tuple[str, ...]
    evidence_merkle_root: str
    superseded_by_claim_id: str | None = None


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    ok: bool
    claim_count: int
    evidence_count: int
    event_count: int
    authentication_count: int
    errors: tuple[str, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_sha256(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _claim_payload(claim: ClaimStatement) -> dict[str, object]:
    payload = asdict(claim)
    payload["schema_version"] = CLAIM_SCHEMA
    return payload


def _evidence_payload(evidence: ClaimEvidence) -> dict[str, object]:
    payload = asdict(evidence)
    payload["kind"] = evidence.kind.value
    payload["outcome"] = evidence.outcome.value
    payload["schema_version"] = EVIDENCE_SCHEMA
    return payload


def _merkle_root(records: list[tuple[str, str]]) -> str:
    leaves = [
        bytes.fromhex(_sha256_json({"id": record_id, "payload_sha256": payload_sha256}))
        for record_id, payload_sha256 in sorted(records)
    ]
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])
        leaves = [
            hashlib.sha256(leaves[index] + leaves[index + 1]).digest()
            for index in range(0, len(leaves), 2)
        ]
    return leaves[0].hex()


class ClaimEvidenceLedger:
    """Append-only, hash-bound evidence and state history for durable claims.

    Evidence maturity, claim disposition, and authentication are deliberately
    separate axes.  Callers append evidence; they cannot request a maturity
    promotion.  The current view is derived from the immutable claim binding and
    the evidence artifacts that still match their recorded SHA-256 digests.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        authentication_keys: Mapping[str, str | bytes] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._authentication_keys = {
            _require_text(key_id, "authentication key id"): (
                value.encode("utf-8") if isinstance(value, str) else bytes(value)
            )
            for key_id, value in (authentication_keys or {}).items()
        }
        if any(not secret for secret in self._authentication_keys.values()):
            raise ValueError("authentication keys must not be empty")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, timeout=10, factory=ClosingSQLiteConnection
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS claim_evidence_claims (
                    claim_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claim_evidence_records (
                    evidence_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (claim_id) REFERENCES claim_evidence_claims(claim_id)
                );
                CREATE INDEX IF NOT EXISTS ix_claim_evidence_record_claim
                    ON claim_evidence_records(claim_id);
                CREATE TABLE IF NOT EXISTS claim_evidence_supersessions (
                    claim_id TEXT PRIMARY KEY,
                    replacement_claim_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (claim_id) REFERENCES claim_evidence_claims(claim_id),
                    FOREIGN KEY (replacement_claim_id)
                        REFERENCES claim_evidence_claims(claim_id)
                );
                CREATE TABLE IF NOT EXISTS claim_evidence_authentications (
                    envelope_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (claim_id) REFERENCES claim_evidence_claims(claim_id)
                );
                CREATE INDEX IF NOT EXISTS ix_claim_evidence_auth_claim
                    ON claim_evidence_authentications(claim_id);
                CREATE TABLE IF NOT EXISTS claim_evidence_state_events (
                    event_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    previous_event_sha256 TEXT,
                    event_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE (claim_id, sequence),
                    FOREIGN KEY (claim_id) REFERENCES claim_evidence_claims(claim_id)
                );
                CREATE INDEX IF NOT EXISTS ix_claim_evidence_event_claim
                    ON claim_evidence_state_events(claim_id, sequence);
                CREATE TRIGGER IF NOT EXISTS claim_evidence_claims_no_update
                    BEFORE UPDATE ON claim_evidence_claims
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_claims_no_delete
                    BEFORE DELETE ON claim_evidence_claims
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_records_no_update
                    BEFORE UPDATE ON claim_evidence_records
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_records_no_delete
                    BEFORE DELETE ON claim_evidence_records
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_supersessions_no_update
                    BEFORE UPDATE ON claim_evidence_supersessions
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_supersessions_no_delete
                    BEFORE DELETE ON claim_evidence_supersessions
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_authentications_no_update
                    BEFORE UPDATE ON claim_evidence_authentications
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_authentications_no_delete
                    BEFORE DELETE ON claim_evidence_authentications
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_state_events_no_update
                    BEFORE UPDATE ON claim_evidence_state_events
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS claim_evidence_state_events_no_delete
                    BEFORE DELETE ON claim_evidence_state_events
                    BEGIN SELECT RAISE(ABORT, 'claim evidence ledger is append-only'); END;
                """
            )

    @staticmethod
    def _validate_claim(claim: ClaimStatement) -> ClaimStatement:
        if claim.schema_version != CLAIM_SCHEMA:
            raise ValueError(f"unsupported claim schema: {claim.schema_version}")
        _require_text(claim.claim_id, "claim id")
        _require_text(claim.subject, "claim subject")
        _require_text(claim.assertion, "claim assertion")
        _require_sha256(claim.source_manifest_sha256, "source manifest hash")
        _require_sha256(claim.policy_sha256, "policy hash")
        _require_sha256(claim.required_test_spec_sha256, "test specification hash")
        return claim

    @staticmethod
    def _validate_evidence(evidence: ClaimEvidence) -> ClaimEvidence:
        if evidence.schema_version != EVIDENCE_SCHEMA:
            raise ValueError(f"unsupported evidence schema: {evidence.schema_version}")
        _require_text(evidence.evidence_id, "evidence id")
        _require_text(evidence.claim_id, "claim id")
        _require_text(evidence.producer_id, "evidence producer")
        _require_sha256(evidence.artifact_sha256, "artifact hash")
        _require_sha256(evidence.source_manifest_sha256, "source manifest hash")
        _require_sha256(evidence.policy_sha256, "policy hash")
        if evidence.test_spec_sha256 is not None:
            _require_sha256(evidence.test_spec_sha256, "test specification hash")
        artifact = Path(evidence.artifact_path).resolve(strict=True)
        if not artifact.is_file():
            raise EvidenceIntegrityError(f"evidence artifact is not a file: {artifact}")
        actual = _sha256_file(artifact)
        if not hmac.compare_digest(actual, evidence.artifact_sha256):
            raise EvidenceIntegrityError(
                f"evidence artifact hash mismatch for {evidence.evidence_id}"
            )
        if evidence.kind in {
            EvidenceKind.TEST_RUN,
            EvidenceKind.REPLICATION_RUN,
        } and (evidence.test_spec_sha256 is None or not evidence.run_id):
            raise ValueError("test evidence requires a test specification and run id")
        if evidence.kind is EvidenceKind.REPLICATION_RUN and not evidence.independence_key:
            raise ValueError("replication evidence requires an independence key")
        if evidence.kind is EvidenceKind.COUNTEREVIDENCE:
            if evidence.outcome is not EvidenceOutcome.FAILED:
                raise ValueError("counterevidence must record a FAILED outcome")
            if evidence.test_spec_sha256 is None:
                raise ValueError("counterevidence requires a test specification")
        return ClaimEvidence(
            **{
                **asdict(evidence),
                "kind": evidence.kind,
                "outcome": evidence.outcome,
                "artifact_path": str(artifact),
            }
        )

    def propose(self, claim: ClaimStatement) -> ClaimAssessment:
        claim = self._validate_claim(claim)
        payload = _claim_payload(claim)
        serialized = _canonical_json(payload)
        payload_sha256 = _sha256_bytes(serialized.encode("utf-8"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload FROM claim_evidence_claims WHERE claim_id=?",
                (claim.claim_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload"] != serialized:
                    raise DuplicatePayloadError(
                        f"claim id {claim.claim_id} already has different immutable content"
                    )
                return self._assess(connection, claim.claim_id)
            connection.execute(
                "INSERT INTO claim_evidence_claims VALUES (?, ?, ?)",
                (claim.claim_id, payload_sha256, serialized),
            )
            assessment = self._assess(connection, claim.claim_id)
            self._append_event(
                connection,
                assessment,
                action_kind="CLAIM_PROPOSED",
                action_id=payload_sha256,
            )
            return assessment

    def append_evidence(self, evidence: ClaimEvidence) -> ClaimAssessment:
        evidence = self._validate_evidence(evidence)
        payload = _evidence_payload(evidence)
        serialized = _canonical_json(payload)
        payload_sha256 = _sha256_bytes(serialized.encode("utf-8"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._load_claim(connection, evidence.claim_id)
            existing = connection.execute(
                "SELECT payload FROM claim_evidence_records WHERE evidence_id=?",
                (evidence.evidence_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload"] != serialized:
                    raise DuplicatePayloadError(
                        f"evidence id {evidence.evidence_id} already has different immutable content"
                    )
                return self._assess(connection, evidence.claim_id)
            connection.execute(
                "INSERT INTO claim_evidence_records VALUES (?, ?, ?, ?)",
                (evidence.evidence_id, evidence.claim_id, payload_sha256, serialized),
            )
            assessment = self._assess(connection, evidence.claim_id)
            self._append_event(
                connection,
                assessment,
                action_kind="EVIDENCE_APPENDED",
                action_id=evidence.evidence_id,
            )
            return assessment

    def authenticate(self, claim_id: str, *, key_id: str) -> ClaimAssessment:
        _require_text(key_id, "authentication key id")
        secret = self._authentication_keys.get(key_id)
        if secret is None:
            raise ClaimTransitionError(f"authentication key is unavailable: {key_id}")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            claim, claim_sha256 = self._load_claim(connection, claim_id)
            assessment = self._assess(connection, claim_id)
            if assessment.disposition is not ClaimDisposition.ACTIVE:
                raise ClaimTransitionError("only active claims can be authenticated")
            if assessment.evidence_level is not EvidenceLevel.REPLICATED:
                raise ClaimTransitionError(
                    "authentication requires independently replicated evidence"
                )
            signed_body = {
                "schema_version": AUTHENTICATION_SCHEMA,
                "purpose": AUTHENTICATION_PURPOSE,
                "claim_id": claim_id,
                "claim_payload_sha256": claim_sha256,
                "source_manifest_sha256": claim.source_manifest_sha256,
                "policy_sha256": claim.policy_sha256,
                "test_spec_sha256": claim.required_test_spec_sha256,
                "evidence_level": assessment.evidence_level.value,
                "disposition": assessment.disposition.value,
                "evidence_ids": list(assessment.eligible_evidence_ids),
                "evidence_merkle_root": assessment.evidence_merkle_root,
                "key_id": key_id,
                "algorithm": "HMAC-SHA256",
            }
            signed = _canonical_json(signed_body).encode("utf-8")
            signature = hmac.new(secret, signed, hashlib.sha256).hexdigest()
            payload = {**signed_body, "signature": signature}
            serialized = _canonical_json(payload)
            payload_sha256 = _sha256_bytes(serialized.encode("utf-8"))
            envelope_id = "CLAIM-AUTH-" + payload_sha256[:32]
            existing = connection.execute(
                "SELECT payload FROM claim_evidence_authentications WHERE envelope_id=?",
                (envelope_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload"] != serialized:
                    raise DuplicatePayloadError(
                        f"authentication envelope {envelope_id} has conflicting content"
                    )
                return self._assess(connection, claim_id)
            connection.execute(
                "INSERT INTO claim_evidence_authentications VALUES (?, ?, ?, ?)",
                (envelope_id, claim_id, payload_sha256, serialized),
            )
            assessment = self._assess(connection, claim_id)
            self._append_event(
                connection,
                assessment,
                action_kind="CLAIM_AUTHENTICATED",
                action_id=envelope_id,
            )
            return assessment

    def supersede(
        self,
        claim_id: str,
        *,
        replacement_claim_id: str,
        reason: str,
    ) -> ClaimAssessment:
        _require_text(reason, "supersession reason")
        if claim_id == replacement_claim_id:
            raise ClaimTransitionError("a claim cannot supersede itself")
        payload = {
            "schema_version": "rlmgraph-claim-supersession-v1",
            "claim_id": claim_id,
            "replacement_claim_id": replacement_claim_id,
            "reason": reason,
        }
        serialized = _canonical_json(payload)
        payload_sha256 = _sha256_bytes(serialized.encode("utf-8"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._load_claim(connection, claim_id)
            self._load_claim(connection, replacement_claim_id)
            existing = connection.execute(
                "SELECT payload FROM claim_evidence_supersessions WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload"] != serialized:
                    raise DuplicatePayloadError(
                        f"claim {claim_id} already has a different supersession"
                    )
                return self._assess(connection, claim_id)
            connection.execute(
                "INSERT INTO claim_evidence_supersessions VALUES (?, ?, ?, ?)",
                (claim_id, replacement_claim_id, payload_sha256, serialized),
            )
            assessment = self._assess(connection, claim_id)
            self._append_event(
                connection,
                assessment,
                action_kind="CLAIM_SUPERSEDED",
                action_id=payload_sha256,
            )
            return assessment

    def assess(self, claim_id: str) -> ClaimAssessment:
        with self._connect() as connection:
            return self._assess(connection, claim_id)

    def history(self, claim_id: str) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            self._load_claim(connection, claim_id)
            rows = connection.execute(
                "SELECT payload FROM claim_evidence_state_events "
                "WHERE claim_id=? ORDER BY sequence",
                (claim_id,),
            ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def _load_claim(
        self, connection: sqlite3.Connection, claim_id: str
    ) -> tuple[ClaimStatement, str]:
        row = connection.execute(
            "SELECT payload, payload_sha256 FROM claim_evidence_claims WHERE claim_id=?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise KeyError(claim_id)
        raw = json.loads(row["payload"])
        return ClaimStatement(**raw), str(row["payload_sha256"])

    @staticmethod
    def _artifact_matches(raw: Mapping[str, object]) -> bool:
        try:
            path = Path(str(raw["artifact_path"]))
            return path.is_file() and hmac.compare_digest(
                _sha256_file(path), str(raw["artifact_sha256"])
            )
        except (OSError, KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _binding_matches(claim: ClaimStatement, raw: Mapping[str, object]) -> bool:
        if (
            raw.get("source_manifest_sha256") != claim.source_manifest_sha256
            or raw.get("policy_sha256") != claim.policy_sha256
        ):
            return False
        if raw.get("kind") in {
            EvidenceKind.TEST_RUN.value,
            EvidenceKind.REPLICATION_RUN.value,
            EvidenceKind.COUNTEREVIDENCE.value,
        }:
            return raw.get("test_spec_sha256") == claim.required_test_spec_sha256
        return True

    def _assess(self, connection: sqlite3.Connection, claim_id: str) -> ClaimAssessment:
        claim, claim_sha256 = self._load_claim(connection, claim_id)
        rows = connection.execute(
            "SELECT evidence_id, payload_sha256, payload FROM claim_evidence_records "
            "WHERE claim_id=? ORDER BY evidence_id",
            (claim_id,),
        ).fetchall()
        records = [(str(row["evidence_id"]), str(row["payload_sha256"])) for row in rows]
        raw_by_id = {str(row["evidence_id"]): json.loads(row["payload"]) for row in rows}
        eligible = {
            evidence_id: raw
            for evidence_id, raw in raw_by_id.items()
            if self._artifact_matches(raw) and self._binding_matches(claim, raw)
        }
        level = EvidenceLevel.PROPOSED
        if any(
            raw.get("kind") == EvidenceKind.SOURCE_OBSERVATION.value for raw in eligible.values()
        ):
            level = EvidenceLevel.OBSERVED
        passing_tests = [
            raw
            for raw in eligible.values()
            if raw.get("kind") in {EvidenceKind.TEST_RUN.value, EvidenceKind.REPLICATION_RUN.value}
            and raw.get("outcome") == EvidenceOutcome.PASSED.value
        ]
        if passing_tests:
            level = EvidenceLevel.TESTED
        independent = {
            str(raw["independence_key"]) for raw in passing_tests if raw.get("independence_key")
        }
        if len(independent) >= 2:
            level = EvidenceLevel.REPLICATED

        supersession = connection.execute(
            "SELECT replacement_claim_id FROM claim_evidence_supersessions WHERE claim_id=?",
            (claim_id,),
        ).fetchone()
        rejected = any(
            raw.get("kind") == EvidenceKind.COUNTEREVIDENCE.value
            and raw.get("outcome") == EvidenceOutcome.FAILED.value
            for raw in eligible.values()
        )
        if supersession is not None:
            disposition = ClaimDisposition.SUPERSEDED
            superseded_by = str(supersession["replacement_claim_id"])
        elif rejected:
            disposition = ClaimDisposition.REJECTED
            superseded_by = None
        else:
            disposition = ClaimDisposition.ACTIVE
            superseded_by = None

        eligible_records = [
            (evidence_id, payload_sha256)
            for evidence_id, payload_sha256 in records
            if evidence_id in eligible
        ]
        evidence_root = _merkle_root(eligible_records)
        authentication = self._authentication_state(
            connection,
            claim=claim,
            claim_sha256=claim_sha256,
            level=level,
            disposition=disposition,
            eligible_ids=tuple(sorted(eligible)),
            evidence_root=evidence_root,
        )
        display = self._display_state(level, disposition, authentication)
        return ClaimAssessment(
            claim_id=claim_id,
            evidence_level=level,
            disposition=disposition,
            authentication=authentication,
            display_state=display,
            evidence_ids=tuple(evidence_id for evidence_id, _ in records),
            eligible_evidence_ids=tuple(sorted(eligible)),
            evidence_merkle_root=evidence_root,
            superseded_by_claim_id=superseded_by,
        )

    def _authentication_state(
        self,
        connection: sqlite3.Connection,
        *,
        claim: ClaimStatement,
        claim_sha256: str,
        level: EvidenceLevel,
        disposition: ClaimDisposition,
        eligible_ids: tuple[str, ...],
        evidence_root: str,
    ) -> AuthenticationState:
        rows = connection.execute(
            "SELECT payload FROM claim_evidence_authentications "
            "WHERE claim_id=? ORDER BY envelope_id",
            (claim.claim_id,),
        ).fetchall()
        matching: list[dict[str, object]] = []
        for row in rows:
            raw = json.loads(row["payload"])
            if (
                raw.get("claim_payload_sha256") == claim_sha256
                and raw.get("source_manifest_sha256") == claim.source_manifest_sha256
                and raw.get("policy_sha256") == claim.policy_sha256
                and raw.get("test_spec_sha256") == claim.required_test_spec_sha256
                and raw.get("evidence_level") == level.value
                and raw.get("disposition") == disposition.value
                and tuple(raw.get("evidence_ids", ())) == eligible_ids
                and raw.get("evidence_merkle_root") == evidence_root
            ):
                matching.append(raw)
        if not matching:
            return AuthenticationState.UNAUTHENTICATED
        for raw in matching:
            key_id = str(raw.get("key_id", ""))
            secret = self._authentication_keys.get(key_id)
            if secret is None or raw.get("algorithm") != "HMAC-SHA256":
                continue
            signed_body = {key: value for key, value in raw.items() if key != "signature"}
            expected = hmac.new(
                secret,
                _canonical_json(signed_body).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(expected, str(raw.get("signature", ""))):
                return AuthenticationState.AUTHENTICATED
        return AuthenticationState.INVALID

    @staticmethod
    def _display_state(
        level: EvidenceLevel,
        disposition: ClaimDisposition,
        authentication: AuthenticationState,
    ) -> ClaimDisplayState:
        if disposition is ClaimDisposition.SUPERSEDED:
            return ClaimDisplayState.SUPERSEDED
        if disposition is ClaimDisposition.REJECTED:
            return ClaimDisplayState.REJECTED
        if authentication is AuthenticationState.AUTHENTICATED:
            return ClaimDisplayState.AUTHENTICATED
        return ClaimDisplayState(level.value)

    def _append_event(
        self,
        connection: sqlite3.Connection,
        assessment: ClaimAssessment,
        *,
        action_kind: str,
        action_id: str,
    ) -> None:
        _, claim_payload_sha256 = self._load_claim(connection, assessment.claim_id)
        previous = connection.execute(
            "SELECT sequence, event_sha256 FROM claim_evidence_state_events "
            "WHERE claim_id=? ORDER BY sequence DESC LIMIT 1",
            (assessment.claim_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_sha256 = str(previous["event_sha256"]) if previous is not None else None
        body = {
            "schema_version": EVENT_SCHEMA,
            "claim_id": assessment.claim_id,
            "claim_payload_sha256": claim_payload_sha256,
            "sequence": sequence,
            "previous_event_sha256": previous_sha256,
            "action_kind": action_kind,
            "action_id": action_id,
            "evidence_level": assessment.evidence_level.value,
            "disposition": assessment.disposition.value,
            "authentication": assessment.authentication.value,
            "display_state": assessment.display_state.value,
            "evidence_ids": list(assessment.evidence_ids),
            "eligible_evidence_ids": list(assessment.eligible_evidence_ids),
            "evidence_merkle_root": assessment.evidence_merkle_root,
            "superseded_by_claim_id": assessment.superseded_by_claim_id,
        }
        serialized = _canonical_json(body)
        event_sha256 = _sha256_bytes(serialized.encode("utf-8"))
        event_id = "CLAIM-EVENT-" + event_sha256[:32]
        connection.execute(
            "INSERT INTO claim_evidence_state_events VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_id,
                assessment.claim_id,
                sequence,
                previous_sha256,
                event_sha256,
                serialized,
            ),
        )

    def verify_integrity(self) -> IntegrityReport:
        errors: list[str] = []
        with self._connect() as connection:
            claim_rows = connection.execute(
                "SELECT claim_id, payload_sha256, payload FROM claim_evidence_claims "
                "ORDER BY claim_id"
            ).fetchall()
            evidence_rows = connection.execute(
                "SELECT evidence_id, claim_id, payload_sha256, payload "
                "FROM claim_evidence_records ORDER BY evidence_id"
            ).fetchall()
            supersession_rows = connection.execute(
                "SELECT claim_id, replacement_claim_id, payload_sha256, payload "
                "FROM claim_evidence_supersessions ORDER BY claim_id"
            ).fetchall()
            authentication_rows = connection.execute(
                "SELECT envelope_id, payload_sha256, payload "
                "FROM claim_evidence_authentications ORDER BY envelope_id"
            ).fetchall()
            event_rows = connection.execute(
                "SELECT event_id, claim_id, sequence, previous_event_sha256, "
                "event_sha256, payload FROM claim_evidence_state_events "
                "ORDER BY claim_id, sequence"
            ).fetchall()

        claim_hashes = {str(row["claim_id"]): str(row["payload_sha256"]) for row in claim_rows}
        for row in claim_rows:
            actual = _sha256_bytes(str(row["payload"]).encode("utf-8"))
            if not hmac.compare_digest(actual, str(row["payload_sha256"])):
                errors.append(f"claim payload hash mismatch: {row['claim_id']}")
        evidence_hashes: dict[str, tuple[str, str]] = {}
        for row in evidence_rows:
            evidence_hashes[str(row["evidence_id"])] = (
                str(row["claim_id"]),
                str(row["payload_sha256"]),
            )
            actual = _sha256_bytes(str(row["payload"]).encode("utf-8"))
            if not hmac.compare_digest(actual, str(row["payload_sha256"])):
                errors.append(f"evidence payload hash mismatch: {row['evidence_id']}")
                continue
            try:
                raw = json.loads(row["payload"])
            except json.JSONDecodeError:
                errors.append(f"evidence payload is not JSON: {row['evidence_id']}")
                continue
            if not self._artifact_matches(raw):
                errors.append(f"evidence artifact hash mismatch: {row['evidence_id']}")
        for row in supersession_rows:
            actual = _sha256_bytes(str(row["payload"]).encode("utf-8"))
            if not hmac.compare_digest(actual, str(row["payload_sha256"])):
                errors.append(f"supersession payload hash mismatch: {row['claim_id']}")
            try:
                raw = json.loads(row["payload"])
            except json.JSONDecodeError:
                errors.append(f"supersession payload is not JSON: {row['claim_id']}")
                continue
            if (
                raw.get("claim_id") != row["claim_id"]
                or raw.get("replacement_claim_id") != row["replacement_claim_id"]
            ):
                errors.append(f"supersession binding mismatch: {row['claim_id']}")
        for row in authentication_rows:
            actual = _sha256_bytes(str(row["payload"]).encode("utf-8"))
            if not hmac.compare_digest(actual, str(row["payload_sha256"])):
                errors.append(f"authentication payload hash mismatch: {row['envelope_id']}")
            expected_id = "CLAIM-AUTH-" + actual[:32]
            if row["envelope_id"] != expected_id:
                errors.append(f"authentication envelope id mismatch: {row['envelope_id']}")

        previous_by_claim: dict[str, tuple[int, str]] = {}
        for row in event_rows:
            event_id = str(row["event_id"])
            claim_id = str(row["claim_id"])
            sequence = int(row["sequence"])
            payload = str(row["payload"])
            actual = _sha256_bytes(payload.encode("utf-8"))
            if not hmac.compare_digest(actual, str(row["event_sha256"])):
                errors.append(f"event payload hash mismatch: {event_id}")
            if event_id != "CLAIM-EVENT-" + actual[:32]:
                errors.append(f"event id mismatch: {event_id}")
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError:
                errors.append(f"event payload is not JSON: {event_id}")
                continue
            previous = previous_by_claim.get(claim_id)
            expected_sequence = previous[0] + 1 if previous else 1
            expected_previous = previous[1] if previous else None
            if sequence != expected_sequence or raw.get("sequence") != sequence:
                errors.append(f"event sequence mismatch: {event_id}")
            if (
                row["previous_event_sha256"] != expected_previous
                or raw.get("previous_event_sha256") != expected_previous
            ):
                errors.append(f"event chain mismatch: {event_id}")
            if raw.get("claim_id") != claim_id:
                errors.append(f"event claim mismatch: {event_id}")
            if raw.get("claim_payload_sha256") != claim_hashes.get(claim_id):
                errors.append(f"event claim payload binding mismatch: {event_id}")
            event_evidence_ids = raw.get("evidence_ids", [])
            eligible_ids = raw.get("eligible_evidence_ids", [])
            if not isinstance(event_evidence_ids, list) or not isinstance(eligible_ids, list):
                errors.append(f"event evidence inventory is invalid: {event_id}")
            else:
                if not set(eligible_ids).issubset(event_evidence_ids):
                    errors.append(f"event eligible evidence is not a subset: {event_id}")
                event_records: list[tuple[str, str]] = []
                for evidence_id in eligible_ids:
                    bound = evidence_hashes.get(str(evidence_id))
                    if bound is None or bound[0] != claim_id:
                        errors.append(f"event evidence binding mismatch: {event_id}")
                        continue
                    event_records.append((str(evidence_id), bound[1]))
                if raw.get("evidence_merkle_root") != _merkle_root(event_records):
                    errors.append(f"event evidence root mismatch: {event_id}")
            previous_by_claim[claim_id] = (sequence, str(row["event_sha256"]))

        return IntegrityReport(
            ok=not errors,
            claim_count=len(claim_rows),
            evidence_count=len(evidence_rows),
            event_count=len(event_rows),
            authentication_count=len(authentication_rows),
            errors=tuple(errors),
        )


__all__ = [
    "AuthenticationState",
    "ClaimAssessment",
    "ClaimDisplayState",
    "ClaimDisposition",
    "ClaimEvidence",
    "ClaimEvidenceLedger",
    "ClaimEvidenceLedgerError",
    "ClaimStatement",
    "ClaimTransitionError",
    "DuplicatePayloadError",
    "EvidenceIntegrityError",
    "EvidenceKind",
    "EvidenceLevel",
    "EvidenceOutcome",
    "IntegrityReport",
]
