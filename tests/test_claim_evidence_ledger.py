from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from rlmgraph.claim_evidence_ledger import (
    AuthenticationState,
    ClaimDisplayState,
    ClaimDisposition,
    ClaimEvidence,
    ClaimEvidenceLedger,
    ClaimStatement,
    ClaimTransitionError,
    DuplicatePayloadError,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
)


def _digest(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _artifact(tmp_path: Path, name: str, content: str) -> tuple[Path, str]:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path, _digest(content)


def _claim(claim_id: str = "CLAIM-1") -> ClaimStatement:
    return ClaimStatement(
        claim_id=claim_id,
        subject="scheduled sampling",
        assertion="Predicted roll-ins are consumed during training.",
        source_manifest_sha256=_digest("source-manifest"),
        policy_sha256=_digest("claim-policy"),
        required_test_spec_sha256=_digest("locked-test-spec"),
    )


def _evidence(
    tmp_path: Path,
    claim: ClaimStatement,
    *,
    evidence_id: str,
    kind: EvidenceKind,
    content: str | None = None,
    outcome: EvidenceOutcome = EvidenceOutcome.INAPPLICABLE,
    source_manifest_sha256: str | None = None,
    policy_sha256: str | None = None,
    test_spec_sha256: str | None = None,
    run_id: str | None = None,
    independence_key: str | None = None,
    detail: str = "",
) -> ClaimEvidence:
    text = content or f"artifact for {evidence_id}"
    path, artifact_sha256 = _artifact(tmp_path, f"{evidence_id}.txt", text)
    return ClaimEvidence(
        evidence_id=evidence_id,
        claim_id=claim.claim_id,
        kind=kind,
        artifact_path=str(path),
        artifact_sha256=artifact_sha256,
        source_manifest_sha256=(source_manifest_sha256 or claim.source_manifest_sha256),
        policy_sha256=policy_sha256 or claim.policy_sha256,
        producer_id="worker",
        outcome=outcome,
        test_spec_sha256=test_spec_sha256,
        run_id=run_id,
        independence_key=independence_key,
        detail=detail,
    )


def _passing_test(
    tmp_path: Path,
    claim: ClaimStatement,
    evidence_id: str,
    independence_key: str,
) -> ClaimEvidence:
    return _evidence(
        tmp_path,
        claim,
        evidence_id=evidence_id,
        kind=EvidenceKind.TEST_RUN,
        outcome=EvidenceOutcome.PASSED,
        test_spec_sha256=claim.required_test_spec_sha256,
        run_id=f"run-{evidence_id}",
        independence_key=independence_key,
    )


def test_agent_report_cannot_promote_beyond_proposed(tmp_path: Path) -> None:
    ledger = ClaimEvidenceLedger(tmp_path / "claims.db")
    claim = _claim()
    initial = ledger.propose(claim)
    assert initial.evidence_level is EvidenceLevel.PROPOSED
    report = _evidence(
        tmp_path,
        claim,
        evidence_id="REPORT-1",
        kind=EvidenceKind.AGENT_REPORT,
        detail="The agent says the feature works.",
    )

    assessed = ledger.append_evidence(report)

    assert assessed.evidence_level is EvidenceLevel.PROPOSED
    assert assessed.display_state is ClaimDisplayState.PROPOSED
    assert assessed.eligible_evidence_ids == ("REPORT-1",)


def test_observation_and_test_require_exact_source_policy_and_spec_bindings(
    tmp_path: Path,
) -> None:
    ledger = ClaimEvidenceLedger(tmp_path / "claims.db")
    claim = _claim()
    ledger.propose(claim)
    wrong_observation = _evidence(
        tmp_path,
        claim,
        evidence_id="OBS-WRONG",
        kind=EvidenceKind.SOURCE_OBSERVATION,
        source_manifest_sha256=_digest("other-source"),
    )
    assert ledger.append_evidence(wrong_observation).evidence_level is EvidenceLevel.PROPOSED

    observation = _evidence(
        tmp_path,
        claim,
        evidence_id="OBS-RIGHT",
        kind=EvidenceKind.SOURCE_OBSERVATION,
    )
    observed = ledger.append_evidence(observation)
    assert observed.evidence_level is EvidenceLevel.OBSERVED
    assert observed.eligible_evidence_ids == ("OBS-RIGHT",)

    wrong_test = _evidence(
        tmp_path,
        claim,
        evidence_id="TEST-WRONG",
        kind=EvidenceKind.TEST_RUN,
        outcome=EvidenceOutcome.PASSED,
        test_spec_sha256=_digest("different-test"),
        run_id="run-wrong",
        independence_key="worker-wrong",
    )
    assert ledger.append_evidence(wrong_test).evidence_level is EvidenceLevel.OBSERVED

    tested = ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-1", "worker-a"))
    assert tested.evidence_level is EvidenceLevel.TESTED
    assert tested.display_state is ClaimDisplayState.TESTED


def test_replication_requires_two_distinct_independence_keys(tmp_path: Path) -> None:
    ledger = ClaimEvidenceLedger(tmp_path / "claims.db")
    claim = _claim()
    ledger.propose(claim)

    first = ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-1", "worker-a"))
    duplicate_source = ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-2", "worker-a"))
    replicated = ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-3", "worker-b"))

    assert first.evidence_level is EvidenceLevel.TESTED
    assert duplicate_source.evidence_level is EvidenceLevel.TESTED
    assert replicated.evidence_level is EvidenceLevel.REPLICATED
    assert replicated.display_state is ClaimDisplayState.REPLICATED


def test_identical_writes_are_idempotent_and_conflicting_ids_fail_closed(
    tmp_path: Path,
) -> None:
    ledger = ClaimEvidenceLedger(tmp_path / "claims.db")
    claim = _claim()
    ledger.propose(claim)
    assert ledger.propose(claim).evidence_level is EvidenceLevel.PROPOSED
    assert len(ledger.history(claim.claim_id)) == 1

    evidence = _passing_test(tmp_path, claim, "TEST-1", "worker-a")
    ledger.append_evidence(evidence)
    ledger.append_evidence(evidence)
    assert len(ledger.history(claim.claim_id)) == 2

    with pytest.raises(DuplicatePayloadError, match="different immutable content"):
        ledger.propose(replace(claim, assertion="Conflicting assertion."))
    with pytest.raises(DuplicatePayloadError, match="different immutable content"):
        ledger.append_evidence(replace(evidence, detail="conflicting payload"))


def test_assessment_is_order_independent(tmp_path: Path) -> None:
    claim = _claim()
    evidence = [
        _evidence(
            tmp_path,
            claim,
            evidence_id="OBS-1",
            kind=EvidenceKind.SOURCE_OBSERVATION,
        ),
        _passing_test(tmp_path, claim, "TEST-1", "worker-a"),
        _passing_test(tmp_path, claim, "TEST-2", "worker-b"),
    ]
    first = ClaimEvidenceLedger(tmp_path / "first.db")
    second = ClaimEvidenceLedger(tmp_path / "second.db")
    first.propose(claim)
    second.propose(claim)
    for item in evidence:
        first.append_evidence(item)
    for item in reversed(evidence):
        second.append_evidence(item)

    left = first.assess(claim.claim_id)
    right = second.assess(claim.claim_id)
    assert left.evidence_level is right.evidence_level is EvidenceLevel.REPLICATED
    assert left.eligible_evidence_ids == right.eligible_evidence_ids
    assert left.evidence_merkle_root == right.evidence_merkle_root


def test_authentication_is_orthogonal_and_requires_replication(tmp_path: Path) -> None:
    database = tmp_path / "claims.db"
    ledger = ClaimEvidenceLedger(database, authentication_keys={"local": b"secret"})
    claim = _claim()
    ledger.propose(claim)
    with pytest.raises(ClaimTransitionError, match="requires independently replicated"):
        ledger.authenticate(claim.claim_id, key_id="local")
    ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-1", "worker-a"))
    ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-2", "worker-b"))

    authenticated = ledger.authenticate(claim.claim_id, key_id="local")

    assert authenticated.evidence_level is EvidenceLevel.REPLICATED
    assert authenticated.authentication is AuthenticationState.AUTHENTICATED
    assert authenticated.display_state is ClaimDisplayState.AUTHENTICATED
    wrong_key = ClaimEvidenceLedger(
        database, authentication_keys={"local": b"wrong-secret"}
    ).assess(claim.claim_id)
    assert wrong_key.evidence_level is EvidenceLevel.REPLICATED
    assert wrong_key.authentication is AuthenticationState.INVALID
    assert wrong_key.display_state is ClaimDisplayState.REPLICATED


def test_hash_bound_artifact_changes_remove_eligibility_and_fail_integrity(
    tmp_path: Path,
) -> None:
    ledger = ClaimEvidenceLedger(tmp_path / "claims.db")
    claim = _claim()
    ledger.propose(claim)
    first = _passing_test(tmp_path, claim, "TEST-1", "worker-a")
    second = _passing_test(tmp_path, claim, "TEST-2", "worker-b")
    ledger.append_evidence(first)
    assert ledger.append_evidence(second).evidence_level is EvidenceLevel.REPLICATED

    Path(second.artifact_path).write_text("tampered", encoding="utf-8")

    assessment = ledger.assess(claim.claim_id)
    integrity = ledger.verify_integrity()
    assert assessment.evidence_level is EvidenceLevel.TESTED
    assert "TEST-2" not in assessment.eligible_evidence_ids
    assert not integrity.ok
    assert any("TEST-2" in error for error in integrity.errors)


def test_bound_counterevidence_rejects_and_supersession_preserves_history(
    tmp_path: Path,
) -> None:
    ledger = ClaimEvidenceLedger(tmp_path / "claims.db")
    claim = _claim()
    replacement = _claim("CLAIM-2")
    ledger.propose(claim)
    ledger.propose(replacement)
    counterevidence = _evidence(
        tmp_path,
        claim,
        evidence_id="COUNTER-1",
        kind=EvidenceKind.COUNTEREVIDENCE,
        outcome=EvidenceOutcome.FAILED,
        test_spec_sha256=claim.required_test_spec_sha256,
        run_id="failed-run",
    )

    rejected = ledger.append_evidence(counterevidence)
    prior_history = ledger.history(claim.claim_id)
    superseded = ledger.supersede(
        claim.claim_id,
        replacement_claim_id=replacement.claim_id,
        reason="A narrower corrected claim replaces the rejected statement.",
    )

    assert rejected.disposition is ClaimDisposition.REJECTED
    assert rejected.display_state is ClaimDisplayState.REJECTED
    assert superseded.disposition is ClaimDisposition.SUPERSEDED
    assert superseded.display_state is ClaimDisplayState.SUPERSEDED
    assert superseded.superseded_by_claim_id == replacement.claim_id
    assert ledger.history(claim.claim_id)[: len(prior_history)] == prior_history


def test_event_chain_tampering_is_detected(tmp_path: Path) -> None:
    database = tmp_path / "claims.db"
    ledger = ClaimEvidenceLedger(database)
    claim = _claim()
    ledger.propose(claim)
    ledger.append_evidence(_passing_test(tmp_path, claim, "TEST-1", "worker-a"))
    assert ledger.verify_integrity().ok

    with (
        sqlite3.connect(database) as connection,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        connection.execute(
            "UPDATE claim_evidence_state_events SET payload=? WHERE sequence=1",
            ('{"blocked":true}',),
        )

    # Simulate storage-level corruption after an attacker has bypassed the guard.
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER claim_evidence_state_events_no_update")
        connection.execute(
            "UPDATE claim_evidence_state_events SET payload=? WHERE sequence=1",
            ('{"tampered":true}',),
        )

    report = ledger.verify_integrity()
    assert not report.ok
    assert any("event payload hash mismatch" in error for error in report.errors)
    assert any("event sequence mismatch" in error for error in report.errors)
