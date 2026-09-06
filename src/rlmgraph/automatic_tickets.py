from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import ClassVar

from .models import ObserverActivityState, ProjectExecutionMode


class AutomaticTicketRunner:
    """Serially execute tickets under a project's explicit autonomous mode."""

    TERMINAL_WORK: ClassVar[set[str]] = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}
    TERMINAL_SANDBOX: ClassVar[set[str]] = {
        "READY_FOR_REVIEW", "FAILED", "DISCARDED", "PROMOTED", "PROMOTION_FAILED",
        "RECOVERY_FAILED", "RECONCILED",
    }

    def __init__(self, store, workspace, sandbox, tickets) -> None:
        self.store = store
        self.workspace = workspace
        self.sandbox = sandbox
        self.tickets = tickets
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._state = self._idle()
        self._target_ticket_id: str | None = None

    @staticmethod
    def _idle() -> dict:
        return {
            "status": "IDLE", "project_id": None, "ticket_id": None,
            "completed": 0, "failed": 0, "remaining": 0,
            "stage": "Automatic disposable ticket execution is idle.", "error": None,
        }

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, project_id: str, ticket_id: str | None = None) -> dict:
        project = next((item for item in self.store.projects() if item.id == project_id), None)
        if project is None:
            raise ValueError("Automatic ticket project is not registered.")
        if project.execution_mode not in {
            ProjectExecutionMode.AUTONOMOUS_SANDBOX,
            ProjectExecutionMode.AUTONOMOUS_PROJECT,
        }:
            raise ValueError("Automatic execution requires Autonomous Sandbox or Autonomous Project mode.")
        with self._lock:
            if self._state["status"] == "RUNNING":
                raise RuntimeError("Automatic ticket execution is already running.")
            if ticket_id is not None and not any(
                item.id == ticket_id and item.project_id == project_id and item.status == "READY"
                for item in self.store.project_tickets()
            ):
                raise ValueError("The requested ticket must be ready in the selected project.")
            self._target_ticket_id = ticket_id
            ready = self._ready(project_id)
            self._stop.clear()
            self._state = {
                **self._idle(), "status": "RUNNING", "project_id": project_id,
                "remaining": len(ready), "stage": "Selecting the next ready ticket.",
                "started_at": datetime.now(UTC).isoformat(),
            }
            self._persist()
        threading.Thread(target=self._run, args=(project_id,), daemon=True).start()
        return self.snapshot()

    def stop(self) -> dict:
        self._stop.set()
        self._update(stage="Stop requested; the current bounded operation will finish safely.")
        return self.snapshot()

    def _ready(self, project_id: str):
        return sorted(
            (item for item in self.store.project_tickets()
             if item.project_id == project_id and item.status == "READY"
             and (self._target_ticket_id is None or item.id == self._target_ticket_id)),
            key=lambda item: item.created_at,
        )

    def _run(self, project_id: str) -> None:
        try:
            while not self._stop.is_set():
                project = next(
                    (item for item in self.store.projects() if item.id == project_id), None
                )
                if project is None or project.execution_mode not in {
                    ProjectExecutionMode.AUTONOMOUS_SANDBOX,
                    ProjectExecutionMode.AUTONOMOUS_PROJECT,
                }:
                    raise RuntimeError("Automatic project execution is no longer authorized.")
                ready = self._ready(project_id)
                if not ready:
                    break
                ticket = ready[0]
                self._update(ticket_id=ticket.id, remaining=len(ready),
                             stage=f"Planning: {ticket.title}")
                try:
                    self.tickets.transition(
                        ticket.id, "ACTIVE", actor="Disposable automatic runner",
                        reason="Selected from the explicitly authorized disposable queue.",
                    )
                    self.workspace.start_change_plan(
                        project_id, ticket.description,
                        [item.description for item in ticket.acceptance_criteria], ticket.id,
                    )
                    workspace = self._wait(self.workspace.snapshot, self.TERMINAL_WORK)
                    if workspace["status"] != "COMPLETED":
                        raise RuntimeError(workspace.get("error") or "Automatic planning failed.")
                    plan_id = str(workspace["result_id"])
                    self.tickets.approve_plan(
                        ticket.id, plan_id, actor="Disposable automatic runner",
                        reason="Automatic local approval is restricted to the disposable mutation marker.",
                    )
                    self._update(stage=f"Implementing: {ticket.title}")
                    self.sandbox.start(ticket.id, plan_id)
                    sandbox_state = self._wait(self.sandbox.snapshot, self.TERMINAL_SANDBOX)
                    attempt_id = sandbox_state.get("attempt_id")
                    if sandbox_state["status"] != "READY_FOR_REVIEW" or not attempt_id:
                        raise RuntimeError(sandbox_state.get("error") or self._attempt_failure(ticket.id))
                    attempt = self._complete_validations(ticket.id, str(attempt_id))
                    if attempt.status != "READY_FOR_REVIEW":
                        raise RuntimeError(attempt.failure_reason or "Automatic validation did not pass.")
                    if project.execution_mode == ProjectExecutionMode.AUTONOMOUS_PROJECT:
                        self.sandbox.approve_promotion(
                            ticket.id, attempt.id, "TGRAM autonomous runner",
                            "Project execution mode pre-authorizes validated bounded promotion.", "APPROVED",
                        )
                        self._update(stage=f"Promoting: {ticket.title}")
                        self.sandbox.promote(ticket.id, attempt.id)
                        promoted = self._wait(self.sandbox.snapshot, self.TERMINAL_SANDBOX)
                        if promoted["status"] != "PROMOTED":
                            raise RuntimeError(promoted.get("error") or "Automatic promotion failed.")
                        self.sandbox.reconcile(ticket.id, attempt.id)
                    self.tickets.transition(
                        ticket.id, "AWAITING_REVIEW", actor="Disposable automatic runner",
                        reason=("Implementation promoted and reconciled; criteria await evidence review."
                                if project.execution_mode == ProjectExecutionMode.AUTONOMOUS_PROJECT
                                else "Validated changes remain only in the autonomous sandbox."),
                    )
                    self._update(completed=self.snapshot()["completed"] + 1)
                except Exception as exc:  # noqa: BLE001 - durable per-ticket failure boundary
                    current = self.tickets.get(ticket.id)
                    if current.status not in {"BLOCKED", "SATISFIED", "CLOSED"}:
                        self.tickets.transition(
                            ticket.id, "BLOCKED", actor="Disposable automatic runner",
                            reason=f"Automatic execution stopped for this ticket: {exc}",
                        )
                    self._update(failed=self.snapshot()["failed"] + 1, error=str(exc))
            status = "STOPPED" if self._stop.is_set() else "COMPLETED"
            self._update(status=status, ticket_id=None, remaining=len(self._ready(project_id)),
                         stage=f"Automatic ticket execution {status.lower()}.")
        except Exception as exc:  # noqa: BLE001 - runner boundary
            self._update(status="FAILED", error=str(exc), stage="Automatic ticket runner failed.")

    def _complete_validations(self, ticket_id: str, attempt_id: str):
        attempt = self._attempt(ticket_id, attempt_id)
        for decision in attempt.validation_decisions:
            if decision.status not in {"REQUIRED", "SATISFIED"}:
                continue
            if decision.category == "REVIEW":
                self.sandbox.satisfy_validation(
                    ticket_id, attempt_id, decision.id, "TGRAM autonomous runner",
                    "The selected autonomous execution mode authorizes bounded review.",
                )
            else:
                preferred_id = (
                    "BUILTIN-PYTHON-PYTEST"
                    if decision.path.startswith("tests/")
                    else "BUILTIN-PYTHON-SYNTAX"
                )
                eligible = [
                    item for item in self.sandbox.manager.configured_workers()
                    if item.enabled and decision.category in item.categories
                    and decision.artifact_kind in item.artifact_kinds
                ]
                worker = next((item for item in eligible if item.id == preferred_id), None)
                worker = worker or (eligible[0] if eligible else None)
                if worker:
                    self.sandbox.run_validation_worker(ticket_id, attempt_id, decision.id, worker.id)
        return self._attempt(ticket_id, attempt_id)

    def _attempt(self, ticket_id: str, attempt_id: str):
        return next(item for item in self.store.implementation_sandboxes(ticket_id)
                    if item.id == attempt_id)

    def _attempt_failure(self, ticket_id: str) -> str:
        attempts = self.store.implementation_sandboxes(ticket_id)
        return attempts[-1].failure_reason if attempts else "Implementation produced no attempt."

    def _wait(self, snapshot, terminal: set[str], timeout: float = 1200) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = snapshot()
            if state["status"] in terminal:
                return state
            if self._stop.is_set():
                raise RuntimeError("Automatic execution stop requested.")
            time.sleep(0.2)
        raise TimeoutError("Automatic ticket operation exceeded its bounded wait.")

    def _update(self, **values) -> None:
        with self._lock:
            self._state.update(values)
            self._persist()

    def _persist(self) -> None:
        self.store.save_observer_activity(ObserverActivityState(
            id="OBSERVER-AUTOMATIC-TICKETS", activity_kind="AUTOMATIC_TICKETS",
            status=self._state["status"], ticket_id=self._state.get("ticket_id"),
            project_id=self._state.get("project_id"), stage=self._state["stage"],
            resume_payload=dict(self._state), error=self._state.get("error"),
        ))
