from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .models import SelfImprovementProposal, TicketBudget
from .ticketing import TicketManager


class SelfIterationManager:
    """Draft and explicitly accept self-work without granting execution or approval authority."""

    def __init__(self, store, system_root: Path) -> None:
        self.store = store
        self.system_root = system_root.resolve()

    def propose_latest(self, session_id: str) -> SelfImprovementProposal:
        results = list(self.store.conversation_work_results(session_id))
        if not results:
            raise ValueError("No completed investigation is available for an improvement proposal.")
        result = results[-1]
        request = next(
            (item for item in self.store.conversation_work_requests(session_id)
             if item.id == result.request_id),
            None,
        )
        if request is None or request.scope.value != "SYSTEM":
            raise ValueError("Self-improvement proposals require a completed RLMGraph system investigation.")
        if not result.claim_ids:
            raise ValueError("The investigation has no evidence-backed claim to anchor the proposal.")
        proposal = SelfImprovementProposal(
            session_id=session_id,
            work_request_id=request.id,
            work_result_id=result.id,
            source_claim_ids=result.claim_ids,
            originating_prompt=request.exact_user_prompt,
            title=f"Address self-investigation: {request.objective}"[:180],
            objective=request.objective,
            acceptance_criteria=[
                "The user-visible failure described by the originating prompt is no longer reproducible.",
                (
                    "After restart, rerunning the exact originating prompt returns evidence-backed "
                    "output linked to current source, tests, or runtime observations."
                ),
            ],
            constraints=[
                "Use the ordinary disposable implementation and validation workflow.",
                "Do not weaken conversation/worker authority boundaries or self-approve promotion.",
            ],
        )
        self.store.save_self_improvement_proposal(proposal)
        return proposal

    def accept(self, proposal_id: str, actor: str, reason: str):
        proposal = next(
            (item for item in self.store.self_improvement_proposals() if item.id == proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"Unknown self-improvement proposal: {proposal_id}")
        if proposal.status != "DRAFT":
            raise ValueError("Only a draft self-improvement proposal can be accepted.")
        project = next(
            (
                item for item in self.store.projects()
                if Path(item.root).resolve() == self.system_root
                and item.read_only and item.explicitly_selected
            ),
            None,
        )
        if project is None:
            raise ValueError("RLMGraph must be explicitly registered read-only before creating self-work.")
        ticket = TicketManager(self.store).create(
            project_id=project.id,
            title=proposal.title,
            description=(
                f"User-originating objective: {proposal.objective} "
                f"Originating prompt: {proposal.originating_prompt}"
            ),
            acceptance_criteria=proposal.acceptance_criteria,
            constraints=proposal.constraints,
            priority="MEDIUM",
            dependency_ticket_ids=[],
            budget=TicketBudget(),
            created_by=actor,
            source_claim_ids=proposal.source_claim_ids,
        )
        proposal.status = "ACCEPTED"
        proposal.accepted_by = actor
        proposal.acceptance_reason = reason
        proposal.ticket_id = ticket.id
        proposal.updated_at = datetime.now(UTC)
        self.store.save_self_improvement_proposal(proposal)
        return proposal, ticket
