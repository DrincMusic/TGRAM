from __future__ import annotations

import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path

from .models import ScheduledWorkItem, SchedulerCheckpoint, SchedulerLimits
from .store import GraphStore
from .ticketing import TicketManager

TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
ACTIVE_STATUSES = {"RUNNING", "CANCELLATION_REQUESTED"}
PRIORITY_WEIGHT = {"URGENT": 400.0, "HIGH": 300.0, "MEDIUM": 200.0, "LOW": 100.0}


class SchedulingCancelled(RuntimeError):
    """Raised at a cooperative checkpoint after cancellation was requested."""


class ResourceAwareScheduler:
    """Durable admission, prioritization, checkpoint, and cancellation boundary."""

    def __init__(
        self,
        store: GraphStore,
        *,
        limits: SchedulerLimits | None = None,
        temporary_root: str | Path | None = None,
    ) -> None:
        self.store = store
        self.limits = limits or SchedulerLimits()
        self.temporary_root = Path(temporary_root).resolve() if temporary_root else None
        self._lock = threading.Lock()
        self.restore_interrupted()

    def enqueue(
        self,
        *,
        ticket_id: str,
        work_kind: str,
        artifact_id: str | None = None,
        required_validation_categories: list[str] | None = None,
        predicted_cost_usd: float = 0,
        predicted_latency_seconds: float = 0,
        predicted_worker_calls: int = 1,
        capacity_units: int = 1,
        requires_project_lease: bool = False,
    ) -> ScheduledWorkItem:
        ticket = TicketManager(self.store).get(ticket_id)
        reasons = self._budget_reasons(ticket, predicted_worker_calls, predicted_latency_seconds)
        priority = ticket.priority.upper()
        validations = sorted(set(required_validation_categories or []))
        score = (
            PRIORITY_WEIGHT.get(priority, PRIORITY_WEIGHT["MEDIUM"])
            + len(validations) * 5
            - predicted_cost_usd * 10
            - predicted_latency_seconds / 60
            - max(0, capacity_units - 1) * 2
        )
        item = ScheduledWorkItem(
            ticket_id=ticket.id,
            project_id=ticket.project_id,
            project_root=ticket.project_root,
            work_kind=work_kind.upper(),
            artifact_id=artifact_id,
            status="BLOCKED_BUDGET" if reasons else "QUEUED",
            priority=priority,
            required_validation_categories=validations,
            predicted_cost_usd=predicted_cost_usd,
            predicted_latency_seconds=predicted_latency_seconds,
            predicted_worker_calls=predicted_worker_calls,
            capacity_units=capacity_units,
            requires_project_lease=requires_project_lease,
            scheduling_score=score,
            scheduling_reasons=[
                f"priority={priority}",
                f"predicted_cost_usd={predicted_cost_usd:g}",
                f"predicted_latency_seconds={predicted_latency_seconds:g}",
                f"capacity_units={capacity_units}",
                f"validation_needs={','.join(validations) or 'none'}",
            ],
            blocked_reason="; ".join(reasons) if reasons else None,
        )
        self._checkpoint(item, "ENQUEUED", item.blocked_reason or "Work admitted to the durable queue.")
        return item

    def claim_next(self) -> ScheduledWorkItem | None:
        with self._lock:
            items = self.store.scheduled_work()
            active = [item for item in items if item.status in ACTIVE_STATUSES]
            if len(active) >= self.limits.global_concurrency:
                for item in items:
                    if item.status in {"QUEUED", "WAITING_FOR_CAPACITY"}:
                        self._block(
                            item, "WAITING_FOR_CAPACITY",
                            "Global concurrency limit is occupied.",
                        )
                return None
            available_units = self.limits.capacity_units - sum(item.capacity_units for item in active)
            candidates = sorted(
                (item for item in items if item.status in {"QUEUED", "WAITING_FOR_CAPACITY", "WAITING_FOR_LEASE"}),
                key=lambda item: (-item.scheduling_score, item.enqueued_at, item.id),
            )
            for item in candidates:
                ticket = TicketManager(self.store).get(item.ticket_id)
                budget_reasons = self._budget_reasons(
                    ticket, item.predicted_worker_calls, item.predicted_latency_seconds
                )
                if budget_reasons:
                    self._block(item, "BLOCKED_BUDGET", "; ".join(budget_reasons))
                    continue
                if sum(other.project_id == item.project_id for other in active) >= self.limits.per_project_concurrency:
                    self._block(item, "WAITING_FOR_CAPACITY", "Project concurrency limit is occupied.")
                    continue
                if sum(other.ticket_id == item.ticket_id for other in active) >= self.limits.per_ticket_concurrency:
                    self._block(item, "WAITING_FOR_CAPACITY", "Ticket concurrency limit is occupied.")
                    continue
                if item.capacity_units > available_units:
                    self._block(item, "WAITING_FOR_CAPACITY", "Global capacity units are occupied.")
                    continue
                lease_reason = self._lease_contention(item)
                if lease_reason:
                    self._block(item, "WAITING_FOR_LEASE", lease_reason)
                    continue
                item.status = "RUNNING"
                item.blocked_reason = None
                item.started_at = item.started_at or datetime.now(UTC)
                self._checkpoint(item, "STARTED", "Scheduler capacity and current budget admitted the work.")
                return item
            return None

    def try_claim(self, item_id: str) -> ScheduledWorkItem | None:
        """Claim one item only when it is currently the highest-ranked admissible candidate."""
        with self._lock:
            items = self.store.scheduled_work()
            target = next((item for item in items if item.id == item_id), None)
            if target is None:
                raise ValueError(f"Scheduled work not found: {item_id}")
            if target.status == "RUNNING":
                return target
            if target.status not in {"QUEUED", "WAITING_FOR_CAPACITY", "WAITING_FOR_LEASE"}:
                return None
            active = [item for item in items if item.status in ACTIVE_STATUSES]
            ranked = sorted(
                (item for item in items if item.status in {"QUEUED", "WAITING_FOR_CAPACITY", "WAITING_FOR_LEASE"}),
                key=lambda item: (-item.scheduling_score, item.enqueued_at, item.id),
            )
            used_units = sum(item.capacity_units for item in active)
            for candidate in ranked:
                if candidate.id == target.id:
                    break
                ticket = TicketManager(self.store).get(candidate.ticket_id)
                reasons = self._budget_reasons(
                    ticket, candidate.predicted_worker_calls, candidate.predicted_latency_seconds
                )
                if reasons:
                    self._block(candidate, "BLOCKED_BUDGET", "; ".join(reasons))
                    continue
                if sum(item.project_id == candidate.project_id for item in active) >= self.limits.per_project_concurrency:
                    self._block(candidate, "WAITING_FOR_CAPACITY", "Project concurrency limit is occupied.")
                    continue
                if sum(item.ticket_id == candidate.ticket_id for item in active) >= self.limits.per_ticket_concurrency:
                    self._block(candidate, "WAITING_FOR_CAPACITY", "Ticket concurrency limit is occupied.")
                    continue
                if candidate.capacity_units + used_units > self.limits.capacity_units:
                    self._block(candidate, "WAITING_FOR_CAPACITY", "Global capacity units are occupied.")
                    continue
                lease_reason = self._lease_contention(candidate)
                if lease_reason:
                    self._block(candidate, "WAITING_FOR_LEASE", lease_reason)
                    continue
                return None
            if len(active) >= self.limits.global_concurrency:
                self._block(target, "WAITING_FOR_CAPACITY", "Global concurrency limit is occupied.")
                return None
            if sum(item.project_id == target.project_id for item in active) >= self.limits.per_project_concurrency:
                self._block(target, "WAITING_FOR_CAPACITY", "Project concurrency limit is occupied.")
                return None
            if sum(item.ticket_id == target.ticket_id for item in active) >= self.limits.per_ticket_concurrency:
                self._block(target, "WAITING_FOR_CAPACITY", "Ticket concurrency limit is occupied.")
                return None
            if target.capacity_units + used_units > self.limits.capacity_units:
                self._block(target, "WAITING_FOR_CAPACITY", "Global capacity units are occupied.")
                return None
            ticket = TicketManager(self.store).get(target.ticket_id)
            reasons = self._budget_reasons(
                ticket, target.predicted_worker_calls, target.predicted_latency_seconds
            )
            if reasons:
                self._block(target, "BLOCKED_BUDGET", "; ".join(reasons))
                return None
            lease_reason = self._lease_contention(target)
            if lease_reason:
                self._block(target, "WAITING_FOR_LEASE", lease_reason)
                return None
            target.status = "RUNNING"
            target.blocked_reason = None
            target.started_at = target.started_at or datetime.now(UTC)
            self._checkpoint(target, "STARTED", "Scheduler capacity and current budget admitted the work.")
            return target

    def checkpoint(
        self,
        item_id: str,
        stage: str,
        detail: str,
        *,
        worker_calls_used: int = 0,
        wall_time_seconds_used: float = 0,
        evidence_ids: list[str] | None = None,
    ) -> ScheduledWorkItem:
        item = self.get(item_id)
        if item.cancellation_requested:
            self.cancel(item.id, actor=item.cancelled_by or "scheduler", reason=item.cancellation_reason or "Cancellation requested.")
            raise SchedulingCancelled(item.cancellation_reason or "Scheduled work was cancelled.")
        item.evidence_ids.extend(value for value in evidence_ids or [] if value not in item.evidence_ids)
        self._checkpoint(
            item, stage, detail, worker_calls_used=worker_calls_used,
            wall_time_seconds_used=wall_time_seconds_used, evidence_ids=evidence_ids or [],
        )
        return item

    def complete(self, item_id: str, *, status: str = "COMPLETED", detail: str = "Work completed.") -> ScheduledWorkItem:
        status = status.upper()
        if status not in {"COMPLETED", "FAILED"}:
            raise ValueError("Scheduled completion status must be COMPLETED or FAILED.")
        item = self.get(item_id)
        item.status = status
        item.completed_at = datetime.now(UTC)
        self._dispose_resources(item)
        self._checkpoint(item, status, detail)
        return item

    def request_cancellation(self, item_id: str, *, actor: str, reason: str) -> ScheduledWorkItem:
        item = self.get(item_id)
        if item.status in TERMINAL_STATUSES:
            return item
        if not actor.strip() or not reason.strip():
            raise ValueError("Cancellation requires an actor and reason.")
        item.cancellation_requested = True
        item.cancelled_by = actor.strip()
        item.cancellation_reason = reason.strip()
        if item.status in {"QUEUED", "WAITING_FOR_CAPACITY", "WAITING_FOR_LEASE", "BLOCKED_BUDGET", "INTERRUPTED"}:
            return self.cancel(item.id, actor=actor, reason=reason, current=item)
        item.status = "CANCELLATION_REQUESTED"
        self._checkpoint(item, "CANCELLATION_REQUESTED", reason.strip())
        return item

    def cancel(
        self, item_id: str, *, actor: str, reason: str, current: ScheduledWorkItem | None = None
    ) -> ScheduledWorkItem:
        item = current or self.get(item_id)
        item.cancellation_requested = True
        item.cancelled_by = actor.strip()
        item.cancellation_reason = reason.strip()
        item.status = "CANCELLED"
        item.completed_at = datetime.now(UTC)
        self._dispose_resources(item)
        self._checkpoint(item, "CANCELLED", reason.strip())
        return item

    def resume(self, item_id: str) -> ScheduledWorkItem:
        item = self.get(item_id)
        if item.status != "INTERRUPTED" or not item.resumable:
            raise ValueError("Only resumable interrupted work can return to the queue.")
        item.status = "QUEUED"
        item.blocked_reason = None
        self._checkpoint(item, "RESUMED", "Interrupted work returned to the durable queue.")
        return item

    def register_temporary_resource(self, item_id: str, path: str | Path) -> ScheduledWorkItem:
        item = self.get(item_id)
        resolved = str(Path(path).resolve())
        if resolved not in item.temporary_resources:
            item.temporary_resources.append(resolved)
        item.resources_disposed = False
        self.store.save_scheduled_work(item)
        return item

    def attach_evidence(self, item_id: str, evidence_ids: list[str]) -> ScheduledWorkItem:
        """Persist evidence independently of whether cancellation is pending."""
        item = self.get(item_id)
        item.evidence_ids.extend(value for value in evidence_ids if value not in item.evidence_ids)
        item.updated_at = datetime.now(UTC)
        self.store.save_scheduled_work(item)
        return item

    def restore_interrupted(self) -> list[ScheduledWorkItem]:
        restored = []
        for item in self.store.scheduled_work():
            if item.status in ACTIVE_STATUSES:
                item.status = "INTERRUPTED"
                item.blocked_reason = "Scheduler process restarted while work was active."
                self._checkpoint(item, "INTERRUPTED", item.blocked_reason)
                restored.append(item)
        return restored

    def get(self, item_id: str) -> ScheduledWorkItem:
        item = next((value for value in self.store.scheduled_work() if value.id == item_id), None)
        if item is None:
            raise ValueError(f"Scheduled work not found: {item_id}")
        return item

    def _budget_reasons(self, ticket, worker_calls: int, wall_time: float) -> list[str]:
        reasons = []
        if ticket.usage.worker_calls + worker_calls > ticket.budget.max_worker_calls:
            reasons.append("Predicted worker calls exceed the ticket budget")
        if ticket.usage.wall_time_seconds + wall_time > ticket.budget.max_wall_time_seconds:
            reasons.append("Predicted latency exceeds the ticket wall-time budget")
        if ticket.usage.tokens >= ticket.budget.max_tokens:
            reasons.append("Ticket token budget is exhausted")
        if ticket.usage.model_calls >= ticket.budget.max_model_calls:
            reasons.append("Ticket model-call budget is exhausted")
        return reasons

    def _lease_contention(self, item: ScheduledWorkItem) -> str | None:
        if not item.requires_project_lease:
            return None
        now = datetime.now(UTC)
        lease = next(
            (value for value in self.store.project_leases() if value.project_root.casefold() == item.project_root.casefold()),
            None,
        )
        if lease and lease.status.value == "ACTIVE" and lease.expires_at > now:
            return f"Project mutation lease is held by {lease.holder_id} until {lease.expires_at.isoformat()}."
        return None

    def _block(self, item: ScheduledWorkItem, status: str, reason: str) -> None:
        if item.status != status or item.blocked_reason != reason:
            item.status = status
            item.blocked_reason = reason
            self._checkpoint(item, status, reason)

    def _checkpoint(
        self, item: ScheduledWorkItem, stage: str, detail: str, *,
        worker_calls_used: int = 0, wall_time_seconds_used: float = 0,
        evidence_ids: list[str] | None = None,
    ) -> None:
        item.checkpoints.append(SchedulerCheckpoint(
            sequence=len(item.checkpoints) + 1, stage=stage, detail=detail,
            worker_calls_used=worker_calls_used,
            wall_time_seconds_used=wall_time_seconds_used,
            evidence_ids=evidence_ids or [],
        ))
        item.updated_at = datetime.now(UTC)
        self.store.save_scheduled_work(item)

    def _dispose_resources(self, item: ScheduledWorkItem) -> None:
        if not item.temporary_resources:
            item.resources_disposed = True
            return
        if self.temporary_root is None:
            item.resources_disposed = False
            return
        root = self.temporary_root.resolve()
        for value in item.temporary_resources:
            target = Path(value).resolve()
            if target == root or root not in target.parents:
                raise RuntimeError("Scheduler refused to dispose a resource outside its temporary root.")
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        item.resources_disposed = True
