from __future__ import annotations

from .models import (
    DeductivePremise,
    DeductiveTheory,
    SelfAssessmentReport,
    WeaknessCandidate,
)


class DeductiveSelfAssessmentEngine:
    """Rank weakness theories from explicit evidence and durable operational state."""

    def __init__(self, store) -> None:
        self.store = store

    def assess(self, session_id: str, work_result) -> SelfAssessmentReport:
        claims = [self.store.get_claim(claim_id) for claim_id in work_result.claim_ids]
        claim = next((item for item in claims if item is not None), None)
        claim_text = claim.conclusion if claim is not None else work_result.answer_summary
        claim_confidence = claim.confidence if claim is not None else work_result.confidence
        claim_id = (
            claim.id if claim is not None else
            work_result.claim_ids[0] if work_result.claim_ids else work_result.id
        )
        common = [DeductivePremise(
            source_id=claim_id,
            source_kind="EVIDENCE_CLAIM",
            statement=claim_text,
            confidence=claim_confidence,
        )]
        candidates: list[WeaknessCandidate] = []
        theories: list[DeductiveTheory] = []
        lowered = claim_text.casefold()

        if any(term in lowered for term in ("rank", "scor", "compare", "decision mechanism")):
            theory = self._theory(
                session_id, "weakness.decision_quality", common,
                "MISSING_COMPARATIVE_MECHANISM_IMPLIES_UNRELIABLE_SUPERLATIVE",
                "RLMGraph cannot reliably identify its largest weakness when it lacks an "
                "implemented comparison and ranking mechanism.",
                claim_confidence,
                ["A current implementation demonstrably ranks multiple weakness candidates."],
                work_result.claim_ids,
            )
            theories.append(theory)
            candidates.append(self._candidate(
                "DECISION_QUALITY", theory, claim_confidence, .92, .8,
                .85 if work_result.unresolved_questions else .55,
            ))

        outcomes = list(self.store.concept_branch_outcomes(session_id))
        problematic = [item for item in outcomes if item.status in {"CHALLENGED", "STALLED"}]
        if problematic:
            premise = DeductivePremise(
                source_id=problematic[-1].id,
                source_kind="BRANCH_OUTCOME",
                statement=(
                    f"{len(problematic)} autonomous branch outcomes are challenged or stalled; "
                    f"latest: {problematic[-1].summary}"
                ),
                confidence=problematic[-1].confidence,
            )
            theory = self._theory(
                session_id, "weakness.reasoning_reliability", [*common, premise],
                "REPEATED_CHALLENGE_IMPLIES_REASONING_RELIABILITY_GAP",
                "Repeated challenged or stalled theories indicate a reasoning-reliability weakness.",
                min(claim_confidence, problematic[-1].confidence),
                ["Subsequent comparable branches complete with supported outcomes."],
                work_result.claim_ids,
            )
            theories.append(theory)
            candidates.append(self._candidate(
                "REASONING_RELIABILITY", theory, theory.confidence, .8,
                min(1.0, len(problematic) / 3), .65,
            ))

        tasks = list(self.store.autonomous_tasks(session_id))
        blocked = [item for item in tasks if item.status == "BLOCKED"]
        if blocked:
            premise = DeductivePremise(
                source_id=blocked[-1].id,
                source_kind="AUTONOMOUS_TASK",
                statement=f"Autonomous task preparation is blocked: {blocked[-1].blocker}",
                confidence=1.0,
            )
            theory = self._theory(
                session_id, "weakness.operational_autonomy", [*common, premise],
                "BLOCKED_ACTIONABLE_WORK_IMPLIES_OPERATIONAL_AUTONOMY_GAP",
                "RLMGraph's autonomy is operationally limited when evidence-backed work cannot "
                "advance to a draft ticket and proposed plan.",
                min(claim_confidence, .95),
                ["A comparable evidence-linked task reaches the plan-approval boundary."],
                work_result.claim_ids,
            )
            theories.append(theory)
            candidates.append(self._candidate(
                "OPERATIONAL_AUTONOMY", theory, theory.confidence, .88,
                min(1.0, len(blocked) / 2), .75,
            ))

        branches = list(self.store.concept_branches(session_id))
        investigated = {item.branch_id for item in self.store.autonomous_inquiries(session_id)}
        untested = [item for item in branches if item.id not in investigated]
        if untested:
            premise = DeductivePremise(
                source_id=untested[-1].id,
                source_kind="CONCEPT_BRANCH",
                statement=f"{len(untested)} durable concept branches have no investigation outcome.",
                confidence=untested[-1].confidence,
            )
            theory = self._theory(
                session_id, "weakness.theory_coverage", [*common, premise],
                "UNTESTED_THEORIES_IMPLY_COVERAGE_GAP",
                "Uninvestigated durable theories create a coverage weakness in RLMGraph's self-model.",
                min(claim_confidence, untested[-1].confidence),
                ["Every current high-value branch has an evidence-linked outcome."],
                work_result.claim_ids,
            )
            theories.append(theory)
            candidates.append(self._candidate(
                "THEORY_COVERAGE", theory, theory.confidence, .65,
                min(1.0, len(untested) / 4), .7,
            ))

        if not candidates:
            theory = self._theory(
                session_id, "weakness.evidence_resolution", common,
                "UNRESOLVED_EVIDENCE_PREVENTS_RELIABLE_SELF_ASSESSMENT",
                "The available evidence is insufficient to rank a current weakness reliably.",
                claim_confidence * .7,
                ["Multiple supported weakness candidates can be compared under one rubric."],
                work_result.claim_ids,
            )
            theories.append(theory)
            candidates.append(self._candidate(
                "EVIDENCE_RESOLUTION", theory, theory.confidence, .75, .5, 1.0,
            ))

        for theory in theories:
            self._save_theory(theory)
        ranked = sorted(candidates, key=lambda item: (-item.severity, item.category))
        selected = ranked[0]
        report = SelfAssessmentReport(
            session_id=session_id,
            work_result_id=work_result.id,
            source_claim_ids=work_result.claim_ids,
            candidates=ranked,
            selected_candidate_id=selected.id,
            conclusion=(
                f"Deductive ranking identifies {selected.category} as the strongest current "
                f"weakness (severity {selected.severity:.2f}): {selected.description}"
            ),
            confidence=selected.evidence_strength,
        )
        self.store.save_self_assessment_report(report)
        return report

    def _save_theory(self, theory: DeductiveTheory) -> None:
        existing = [
            item for item in self.store.deductive_theories(theory.session_id)
            if item.subject == theory.subject and item.status == "ACTIVE_THEORY"
        ]
        if existing:
            theory.supersedes_theory_id = existing[-1].id
            existing[-1].status = "SUPERSEDED"
            self.store.save_deductive_theory(existing[-1])
        self.store.save_deductive_theory(theory)

    @staticmethod
    def _theory(session_id, subject, premises, rule, conclusion, confidence, falsifiers, claims):
        return DeductiveTheory(
            session_id=session_id, subject=subject, premises=premises,
            inference_rule=rule, conclusion=conclusion, confidence=confidence,
            falsifiers=falsifiers, source_claim_ids=claims,
        )

    @staticmethod
    def _candidate(category, theory, evidence, impact, recurrence, unresolvedness):
        severity = .35 * evidence + .3 * impact + .2 * recurrence + .15 * unresolvedness
        return WeaknessCandidate(
            category=category, description=theory.conclusion, theory_id=theory.id,
            evidence_strength=round(evidence, 4), impact=round(impact, 4),
            recurrence=round(recurrence, 4), unresolvedness=round(unresolvedness, 4),
            severity=round(min(1.0, severity), 4),
        )
