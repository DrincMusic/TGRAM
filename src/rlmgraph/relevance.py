from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Claim

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "because",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
}
ALIASES = {
    "failed": "fail",
    "failing": "fail",
    "fails": "fail",
    "failure": "fail",
    "percentages": "percent",
    "percentage": "percent",
    "percent": "percent",
}


def terms(text: str) -> set[str]:
    normalized: set[str] = set()
    for raw in TOKEN_PATTERN.findall(text.lower()):
        if raw in STOP_WORDS or len(raw) < 2:
            continue
        token = ALIASES.get(raw, raw)
        if token.endswith("ing") and len(token) > 6:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 5:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 4 and "_" not in token:
            token = token[:-1]
        normalized.add(token)
    return normalized


def claim_text(claim: Claim) -> str:
    evidence = " ".join(f"{item.path} {item.detail}" for item in claim.evidence)
    return " ".join(
        [claim.subject, claim.conclusion, evidence, *claim.files_examined]
    )


@dataclass(frozen=True)
class RelevanceMatch:
    claim: Claim
    score: float
    matched_terms: tuple[str, ...]
    reason: str


class ExplainableClaimMatcher:
    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold

    def best_match(self, question: str, claims: list[Claim]) -> RelevanceMatch | None:
        query_terms = terms(question)
        if not query_terms:
            return None
        ranked: list[RelevanceMatch] = []
        for claim in claims:
            document_terms = terms(claim_text(claim))
            matched = query_terms & document_terms
            if len(matched) < 2:
                continue
            coverage = len(matched) / len(query_terms)
            identifier_bonus = 0.2 if any("_" in term for term in matched) else 0.0
            score = min(1.0, (coverage + identifier_bonus) * claim.confidence)
            matched_terms = tuple(sorted(matched))
            reason = (
                "Unchanged project state; matched concepts "
                f"{', '.join(matched_terms)}; relevance {score:.2f} meets "
                f"threshold {self.threshold:.2f}."
            )
            ranked.append(RelevanceMatch(claim, score, matched_terms, reason))
        if not ranked:
            return None
        best = max(ranked, key=lambda match: (match.score, match.claim.confidence))
        return best if best.score >= self.threshold else None
