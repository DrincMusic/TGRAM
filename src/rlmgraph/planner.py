from __future__ import annotations

import math
from datetime import UTC, datetime

from .models import (
    PlanDecision,
    PlanningAction,
    PlanningRun,
    PursuitConfig,
    StoppingReason,
    Task,
    TaskKind,
    TaskRoute,
    TaskStatus,
)
from .store import GraphStore


def token_estimate(text: str) -> int:
    """Stable conservative token estimate used for pre-call budget admission."""
    return max(1, math.ceil(len(text) / 4))


class RecursivePlanner:
    """Persisted policy layer for uncertainty, routing, priority, and budgets."""

    def __init__(self, store: GraphStore, root_task_id: str, config: PursuitConfig) -> None:
        self.store = store
        self.root_task_id = root_task_id
        self.config = config
        self.run = PlanningRun(
            root_task_id=root_task_id,
            max_model_calls=config.max_codex_calls,
            max_retrieval_tokens=config.max_retrieval_tokens,
            max_depth=config.max_depth,
            max_duplicate_investigations=config.max_duplicate_investigations,
            max_wall_time_seconds=config.max_wall_time_seconds,
        )
        self.store.save_planning_run(self.run)

    def assess(self, task: Task, reason: str, *, action: PlanningAction) -> Task:
        task.uncertainty = self._uncertainty(task)
        task.difficulty = min(1.0, 0.2 + 0.15 * task.depth + 0.1 * len(task.source_claim_ids))
        task.priority = round(100 * task.uncertainty + 10 * task.difficulty - task.depth, 3)
        task.route = self._route(task)
        self.store.save_task(task)
        self.record(task, action, reason)
        return task

    def record(
        self,
        task: Task,
        action: PlanningAction,
        reason: str,
        *,
        stopping_reason: StoppingReason | None = None,
    ) -> PlanDecision:
        decision = PlanDecision(
            root_task_id=self.root_task_id,
            task_id=task.id,
            action=action,
            reason=reason,
            priority=task.priority,
            uncertainty=task.uncertainty,
            difficulty=task.difficulty,
            route=task.route,
            dependency_task_ids=task.dependency_task_ids,
            model_calls_used=self.run.model_calls_used,
            retrieval_tokens_used=self.run.retrieval_tokens_used,
            duplicate_investigations=self.run.duplicate_investigations,
            elapsed_seconds=self.run.elapsed_seconds,
            stopping_reason=stopping_reason,
        )
        self.store.save_plan_decision(decision)
        return decision

    def admit_call(self, task: Task, retrieval_text: str) -> StoppingReason | None:
        self.tick()
        if task.depth > self.config.max_depth:
            return StoppingReason.MAX_DEPTH
        if self.run.model_calls_used >= self.config.max_codex_calls:
            return StoppingReason.CALL_BUDGET
        requested = token_estimate(retrieval_text)
        if self.run.retrieval_tokens_used + requested > self.config.max_retrieval_tokens:
            return StoppingReason.RETRIEVAL_TOKEN_BUDGET
        if self.run.elapsed_seconds >= self.config.max_wall_time_seconds:
            return StoppingReason.WALL_TIME_BUDGET
        if self.run.duplicate_investigations > self.config.max_duplicate_investigations:
            return StoppingReason.DUPLICATE_BUDGET
        self.run.model_calls_used += 1
        self.run.retrieval_tokens_used += requested
        self.store.save_planning_run(self.run)
        self.record(
            task,
            PlanningAction.CONSUMED,
            f"Admitted model call with {requested} retrieval tokens.",
        )
        return None

    def note_duplicate_avoided(self, task: Task, reused_task_id: str) -> None:
        self.record(
            task,
            PlanningAction.REUSED,
            f"Reused completed investigation {reused_task_id}; duplicate model call avoided.",
        )

    def tick(self) -> None:
        self.run.elapsed_seconds = max(
            0.0, (datetime.now(UTC) - self.run.started_at).total_seconds()
        )

    def finish(self, status: TaskStatus, reason: StoppingReason) -> PlanningRun:
        self.tick()
        self.run.status = status
        self.run.stopping_reason = reason
        self.run.completed_at = datetime.now(UTC)
        self.store.save_planning_run(self.run)
        root = self.store.get_task(self.root_task_id)
        if root is not None:
            self.record(
                root,
                PlanningAction.COMPLETED if status == TaskStatus.DONE else PlanningAction.STOPPED,
                f"Planning run ended with {reason.value}.",
                stopping_reason=reason,
            )
        return self.run

    @staticmethod
    def retrieval_context(task: Task, store: GraphStore) -> str:
        parts = [task.question, task.evidence_gap or "", task.disputed_assertion_key or ""]
        for claim_id in task.source_claim_ids + task.conflicting_claim_ids:
            claim = store.get_claim(claim_id)
            if claim is not None:
                parts.extend([claim.conclusion, *(item.detail for item in claim.evidence)])
        return "\n".join(parts)

    def _uncertainty(self, task: Task) -> float:
        if task.status == TaskStatus.DONE:
            return 0.0
        if task.evidence_gap:
            return 0.9
        if task.kind == TaskKind.RESOLUTION:
            confidences = [
                claim.confidence
                for claim_id in task.conflicting_claim_ids
                if (claim := self.store.get_claim(claim_id)) is not None
            ]
            weak = 1.0 - min(confidences, default=0.0)
            return min(1.0, max(0.8, weak))
        return 0.6

    @staticmethod
    def _route(task: Task) -> TaskRoute:
        if task.status == TaskStatus.DONE or task.reused_claim_id:
            return TaskRoute.MEMORY
        if task.kind == TaskKind.RESOLUTION:
            return TaskRoute.RESOLVER
        if task.difficulty >= 0.75 or task.uncertainty >= 0.95:
            return TaskRoute.CODEX
        return TaskRoute.LOCAL_MODEL
