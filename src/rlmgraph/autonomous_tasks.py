from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .models import (
    AutonomousTask,
    AutonomousTaskPlan,
    AutonomousWorkPolicy,
    TicketBudget,
)
from .ticketing import TicketManager


class AutonomousTaskManager:
    """Prepare ordinary governed work from evidence-backed autonomy outcomes."""

    def __init__(self, store, system_root: Path) -> None:
        self.store = store
        self.system_root = system_root.resolve()

    def policy(self, session_id: str) -> AutonomousWorkPolicy:
        reader = getattr(self.store, "autonomous_work_policies", None)
        policies = list(reader()) if callable(reader) else []
        return next(
            (item for item in policies if item.session_id == session_id),
            AutonomousWorkPolicy(session_id=session_id),
        )

    def enable(self, session_id: str, actor: str) -> AutonomousWorkPolicy:
        policy = self.policy(session_id)
        policy.enabled = True
        policy.enabled_by = actor
        policy.enabled_at = policy.enabled_at or datetime.now(UTC)
        policy.updated_at = datetime.now(UTC)
        self.store.save_autonomous_work_policy(policy)
        return policy

    def disable(self, session_id: str) -> AutonomousWorkPolicy:
        policy = self.policy(session_id)
        policy.enabled = False
        policy.updated_at = datetime.now(UTC)
        self.store.save_autonomous_work_policy(policy)
        return policy

    def prepare_latest(self, session_id: str) -> tuple[AutonomousTask, AutonomousTaskPlan | None]:
        policy = self.policy(session_id)
        if not policy.enabled:
            raise ValueError("Autonomous task preparation is not enabled for this session.")
        existing = list(self.store.autonomous_tasks(session_id))
        if len(existing) >= policy.max_tasks_per_session:
            raise ValueError("The autonomous task budget is exhausted for this session.")
        used = {item.outcome_id for item in existing}
        outcomes = [
            item for item in self.store.concept_branch_outcomes(session_id)
            if item.id not in used and item.claim_ids
        ]
        if not outcomes:
            raise ValueError("No unused evidence-linked autonomous outcome is actionable yet.")
        outcome = outcomes[-1]
        branch = next(
            item for item in self.store.concept_branches(session_id)
            if item.id == outcome.branch_id
        )
        task = AutonomousTask(
            session_id=session_id,
            branch_id=branch.id,
            outcome_id=outcome.id,
            title=f"Investigate and address: {branch.concept}"[:180],
            objective=(
                f"Resolve the evidence-linked {outcome.status.lower()} concept branch: "
                f"{branch.concept}. {outcome.summary}"
            ),
        )
        self.store.save_autonomous_task(task)
        project = next(
            (
                item for item in self.store.projects()
                if Path(item.root).resolve() == self.system_root
                and item.read_only and item.explicitly_selected
            ),
            None,
        )
        if project is None:
            task.status = "BLOCKED"
            task.blocker = "RLMGraph is not explicitly registered as a read-only project."
            task.updated_at = datetime.now(UTC)
            self.store.save_autonomous_task(task)
            return task, None
        try:
            ticket = TicketManager(self.store).create(
                project_id=project.id,
                title=task.title,
                description=task.objective,
                acceptance_criteria=[
                    "The originating evidence-linked uncertainty is reproducibly resolved.",
                    "Focused tests cover the corrected behavior without weakening authority boundaries.",
                    "The exact source claims are revalidated against current project state.",
                ],
                constraints=[
                    "No source write occurs before separate plan approval.",
                    "Implementation remains disposable until separate promotion approval.",
                    "RLMGraph cannot approve its own plan or promotion.",
                ],
                priority=task.priority,
                dependency_ticket_ids=[],
                budget=TicketBudget(max_model_calls=6, max_worker_calls=6),
                created_by="RLMGraph autonomous task preparation",
                source_claim_ids=outcome.claim_ids,
            )
        except ValueError as exc:
            task.status = "BLOCKED"
            task.blocker = str(exc)
            task.updated_at = datetime.now(UTC)
            self.store.save_autonomous_task(task)
            return task, None
        plan = AutonomousTaskPlan(
            session_id=session_id,
            autonomous_task_id=task.id,
            ticket_id=ticket.id,
            objective=task.objective,
            steps=[
                "Reproduce and verify the originating evidence against current source and runtime state.",
                "Identify the smallest affected source and test boundary.",
                "Prepare a bounded implementation change in a disposable sandbox after approval.",
                "Run focused validation and compare it with the recorded baseline.",
            ],
            baseline_checks=[
                "Revalidate the source claims attached to the ticket.",
                "Run the smallest existing tests covering the affected behavior.",
                "Record contradictory evidence and unresolved dependencies before implementation.",
            ],
            acceptance_criteria=[item.description for item in ticket.acceptance_criteria],
            constraints=[item.description for item in ticket.constraints],
            source_claim_ids=outcome.claim_ids,
        )
        self.store.save_autonomous_task_plan(plan)
        task.ticket_id = ticket.id
        task.plan_id = plan.id
        task.status = "WAITING_FOR_USER_PLAN_APPROVAL"
        task.updated_at = datetime.now(UTC)
        self.store.save_autonomous_task(task)
        return task, plan
