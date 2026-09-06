from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .adapters import Investigator
from .models import Claim, GraphEdge, GraphRelation, TaskKind, TaskStatus
from .store import GraphStore


class FollowUpExecutor:
    """Execute a persisted evidence gap and attach its discovery to its resolution."""

    def __init__(self, store: GraphStore, investigator: Investigator) -> None:
        self.store = store
        self.investigator = investigator
        self.follow_up_calls = 0
        self.store.initialize()

    def execute(self, task_id: str) -> Claim:
        task = self.store.get_task(task_id)
        if task is None or task.kind != TaskKind.FOLLOW_UP:
            raise ValueError(f"Follow-up task not found: {task_id}")
        if task.status != TaskStatus.OPEN:
            raise ValueError(f"Follow-up task is not open: {task_id} ({task.status})")

        task.started_at = task.started_at or datetime.now(UTC)
        task.attempt_count += 1
        task.last_error = None
        self.store.save_task(task)
        try:
            result = self.investigator.investigate(task.question, Path(task.project_root))
        finally:
            self.follow_up_calls += max(
                1, int(getattr(self.investigator, "last_call_count", 1))
            )
        claim = Claim(
            fingerprint=task.fingerprint,
            project_fingerprint=task.project_fingerprint,
            subject=task.question,
            producer=type(self.investigator).__name__,
            conclusion=result.conclusion,
            confidence=result.confidence,
            evidence=result.evidence,
            files_examined=result.files_examined,
            files_changed=result.files_changed,
            unresolved_questions=result.unresolved_questions,
            assertions=result.assertions,
        )
        task.output_claim_id = claim.id
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        self.store.save_task(task)
        self.store.save_claim(task, claim)
        if task.parent_task_id:
            self.store.save_edge(
                GraphEdge(source=claim.id, relation=GraphRelation.INFORMS, target=task.parent_task_id)
            )
        return claim
