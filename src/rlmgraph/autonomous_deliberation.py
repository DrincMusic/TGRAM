from __future__ import annotations

from datetime import UTC, datetime

from .models import (
    AutonomousCandidateScore,
    AutonomousDecision,
    AutonomousInquiry,
    AutonomyBudget,
    ConceptBranch,
    ConceptBranchOutcome,
    ConversationWorkResult,
)


class AutonomousDeliberationManager:
    """Select useful read-only questions from open concept branches under fixed budgets."""

    def __init__(self, store, budget: AutonomyBudget | None = None) -> None:
        self.store = store
        self.budget = budget or AutonomyBudget()

    def deliberate(self, session_id: str) -> tuple[AutonomousDecision, AutonomousInquiry | None]:
        decisions = list(self.store.autonomous_decisions(session_id))
        if len(decisions) >= self.budget.max_decisions_per_session:
            decision = AutonomousDecision(
                session_id=session_id,
                reason="The per-session autonomous decision budget is exhausted.",
                budget=self.budget,
                status="BUDGET_EXHAUSTED",
            )
            self.store.save_autonomous_decision(decision)
            return decision, None

        branches = list(self.store.concept_branches(session_id))
        prior_inquiries = list(self.store.autonomous_inquiries(session_id))
        if any(item.status in {"PENDING", "QUEUED", "RUNNING"} for item in prior_inquiries):
            decision = AutonomousDecision(
                session_id=session_id,
                reason="One autonomous inquiry is already queued or running.",
                budget=self.budget,
                status="ACTIVE_INQUIRY_EXISTS",
            )
            self.store.save_autonomous_decision(decision)
            return decision, None
        attempted = {item.branch_id for item in prior_inquiries}
        children = {branch.id: 0 for branch in branches}
        for branch in branches:
            if branch.parent_branch_id in children:
                children[branch.parent_branch_id] += 1
        eligible = [
            branch for branch in branches
            if branch.status == "EXPLORING"
            and branch.confidence >= self.budget.minimum_branch_confidence
            and branch.depth <= self.budget.maximum_branch_depth
            and branch.id not in attempted
        ]
        scores = sorted(
            (self._score(branch, children.get(branch.id, 0)) for branch in eligible),
            key=lambda item: (-item.total, item.branch_id),
        )[: self.budget.max_candidates_per_cycle]
        if not scores:
            decision = AutonomousDecision(
                session_id=session_id,
                candidates=[],
                reason="No uninvestigated concept branch satisfies the autonomy policy.",
                budget=self.budget,
                status="NO_ELIGIBLE_BRANCH",
            )
            self.store.save_autonomous_decision(decision)
            return decision, None

        selected = scores[0]
        branch = next(item for item in eligible if item.id == selected.branch_id)
        decision = AutonomousDecision(
            session_id=session_id,
            candidates=scores,
            selected_branch_id=branch.id,
            reason=(
                "Selected the highest bounded score across novelty, uncertainty, relevance, "
                "expected information gain, and estimated cost."
            ),
            budget=self.budget,
        )
        inquiry = AutonomousInquiry(
            session_id=session_id,
            decision_id=decision.id,
            branch_id=branch.id,
            question=self._question(branch),
            expected_information_gain=selected.expected_information_gain,
        )
        decision.inquiry_id = inquiry.id
        self.store.save_autonomous_decision(decision)
        self.store.save_autonomous_inquiry(inquiry)
        return decision, inquiry

    @staticmethod
    def _score(branch: ConceptBranch, child_count: int) -> AutonomousCandidateScore:
        novelty = 1 / (1 + child_count)
        uncertainty = 1 - branch.confidence
        relevance = min(1.0, len(branch.supporting_fact_ids) / 4)
        information_gain = min(1.0, .55 * uncertainty + .45 * novelty)
        estimated_cost = min(1.0, .2 + .1 * branch.depth)
        total = .25 * novelty + .3 * uncertainty + .2 * relevance + .35 * information_gain
        total -= .1 * estimated_cost
        return AutonomousCandidateScore(
            branch_id=branch.id,
            novelty=round(novelty, 4), uncertainty=round(uncertainty, 4),
            relevance=round(relevance, 4),
            expected_information_gain=round(information_gain, 4),
            estimated_cost=round(estimated_cost, 4),
            total=round(max(0.0, min(1.0, total)), 4),
        )

    @staticmethod
    def _question(branch: ConceptBranch) -> str:
        return (
            "Investigate current RLMGraph source, tests, and reproducible runtime evidence for this "
            f"concept branch: {branch.concept}. Proposed insight: {branch.insight} "
            "Determine what is implemented, what contradicts the insight, and which uncertainty "
            "would be most valuable to resolve next. Treat the branch as a hypothesis, not truth."
        )

    def complete(
        self, inquiry: AutonomousInquiry, result: ConversationWorkResult
    ) -> ConceptBranchOutcome:
        status = "SUPPORTED" if result.confidence >= .75 else "CHALLENGED"
        if not result.claim_ids:
            status = "STALLED"
        outcome = ConceptBranchOutcome(
            session_id=inquiry.session_id,
            branch_id=inquiry.branch_id,
            inquiry_id=inquiry.id,
            work_result_id=result.id,
            claim_ids=result.claim_ids,
            status=status,
            summary=result.answer_summary,
            confidence=result.confidence,
        )
        inquiry.status = "COMPLETED"
        inquiry.work_result_id = result.id
        inquiry.updated_at = datetime.now(UTC)
        self.store.save_autonomous_inquiry(inquiry)
        decision = next(
            item for item in self.store.autonomous_decisions(inquiry.session_id)
            if item.id == inquiry.decision_id
        )
        decision.status = "COMPLETED"
        decision.updated_at = datetime.now(UTC)
        self.store.save_autonomous_decision(decision)
        self.store.save_concept_branch_outcome(outcome)
        return outcome

    def fail(self, inquiry: AutonomousInquiry, reason: str) -> None:
        inquiry.status = "FAILED"
        inquiry.updated_at = datetime.now(UTC)
        self.store.save_autonomous_inquiry(inquiry)
        decision = next(
            item for item in self.store.autonomous_decisions(inquiry.session_id)
            if item.id == inquiry.decision_id
        )
        decision.status = "FAILED"
        decision.reason = f"{decision.reason} Worker failure: {reason}"[:1000]
        decision.updated_at = datetime.now(UTC)
        self.store.save_autonomous_decision(decision)
