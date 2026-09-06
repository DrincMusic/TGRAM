from __future__ import annotations

import re

from .models import Claim, ClaimConflict, ConflictCluster, Interpretation


def normalize_assertion(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9_]+", text.lower()))


def detect_conflicts(new_claim: Claim, existing_claims: list[Claim]) -> list[ClaimConflict]:
    conflicts: list[ClaimConflict] = []
    new_assertions = {
        normalize_assertion(assertion.key): assertion for assertion in new_claim.assertions
    }
    for existing in existing_claims:
        if existing.id == new_claim.id:
            continue
        for assertion in existing.assertions:
            key = normalize_assertion(assertion.key)
            candidate = new_assertions.get(key)
            if candidate is None:
                continue
            if normalize_assertion(assertion.value) == normalize_assertion(candidate.value):
                continue
            conflicts.append(
                ClaimConflict(
                    left_claim_id=existing.id,
                    right_claim_id=new_claim.id,
                    assertion_key=candidate.key,
                    left_value=assertion.value,
                    right_value=candidate.value,
                )
            )
    return conflicts


def cluster_interpretations(
    assertion_key: str, claims: list[Claim]
) -> tuple[list[Interpretation], list[str], list[str]]:
    groups: dict[str, Interpretation] = {}
    normalized_key = normalize_assertion(assertion_key)
    for claim in claims:
        assertion = next(
            (
                item
                for item in claim.assertions
                if normalize_assertion(item.key) == normalized_key
            ),
            None,
        )
        if assertion is None:
            continue
        normalized_value = normalize_assertion(assertion.value)
        interpretation = groups.setdefault(
            normalized_value,
            Interpretation(value=assertion.value, normalized_value=normalized_value),
        )
        if claim.id not in interpretation.claim_ids:
            interpretation.claim_ids.append(claim.id)
    interpretations = list(groups.values())
    corroborated = [
        claim_id
        for interpretation in interpretations
        if len(interpretation.claim_ids) > 1
        for claim_id in interpretation.claim_ids
    ]
    outliers = [
        interpretation.claim_ids[0]
        for interpretation in interpretations
        if len(interpretation.claim_ids) == 1
    ]
    return interpretations, corroborated, outliers


def build_conflict_cluster(
    project_fingerprint: str,
    assertion_key: str,
    claims: list[Claim],
    existing: ConflictCluster | None = None,
) -> ConflictCluster:
    interpretations, corroborated, outliers = cluster_interpretations(assertion_key, claims)
    cluster = existing or ConflictCluster(
        project_fingerprint=project_fingerprint,
        assertion_key=assertion_key,
    )
    cluster.claim_ids = [claim_id for item in interpretations for claim_id in item.claim_ids]
    cluster.interpretations = interpretations
    cluster.corroborated_claim_ids = corroborated
    cluster.outlier_claim_ids = outliers
    return cluster
