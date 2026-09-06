"""Explicit conversation requests enter the existing governed task controllers."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from .models import ProjectExecutionMode, TicketBudget

_START = re.compile(
    r"^(?:please )?(?:start (?:working on|work on|task:?|the task)|"
    r"work on|can you (?:please )?start working on|"
    r"(?:(?:can you|could you) (?:please )?)?(?P<verb>fix|implement))\s+(?P<objective>.+?)[.!?]?$",
    re.IGNORECASE,
)
_STATUS = re.compile(
    r"^(?:task status|how is (?:the|my) task (?:going|progressing)|what is the task status)[?!.]?$",
    re.IGNORECASE,
)


class ConversationTaskController:
    def start_reviewed_request(self, message, project_id, actor):
        """Enter the ordinary task workflow after semantic routing has confirmed CHANGE."""
        with self._lock:
            return self._handle(message, None, project_id, None, actor, objective=message)

    @staticmethod
    def is_status_request(message):
        return bool(_STATUS.fullmatch(message.strip()))

    def __init__(self, store, tickets, workspace, automatic):
        self.store, self.tickets, self.workspace, self.automatic = (
            store,
            tickets,
            workspace,
            automatic,
        )
        self._lock = threading.Lock()

    def handle(self, message, project_id, ticket_id, actor):
        if re.fullmatch(
            r"(?:please )?start (?:this|the selected) task[.!]?", message.strip(), re.IGNORECASE
        ):
            message = "start working on this task"
        request = _START.fullmatch(message.strip())
        if not request and not _STATUS.fullmatch(message.strip()):
            return None
        with self._lock:
            return self._handle(message, request, project_id, ticket_id, actor)

    def _handle(self, message, request, project_id, ticket_id, actor, objective=None):
        if request is None and objective is None:
            if not ticket_id:
                return self._reply(
                    "There is no task selected in this conversation. Tell me which task to check."
                )
            ticket = self.tickets.get(ticket_id)
            state = self.workspace.snapshot()
            automatic = self.automatic.snapshot()
            detail = automatic if automatic.get("ticket_id") == ticket.id else state
            stage = detail.get("stage") if detail.get("ticket_id") == ticket.id else None
            if stage and detail.get("error"):
                stage = f"{stage} {detail['error']}"
            if stage and detail.get("status") == "COMPLETED" and project_id:
                project = next(
                    (p for p in self.store.projects() if p.id == ticket.project_id), None
                )
                if project and project.execution_mode == ProjectExecutionMode.PROTECTED:
                    stage = f"{stage} Review and approve the plan in Tickets before implementation."
            return self._reply(
                f"{ticket.title}: {ticket.status.lower().replace('_', ' ')}. "
                + (
                    str(stage)
                    if stage
                    else "Open its ticket for the current plan and validation results."
                ),
                ticket,
            )
        if objective is None:
            objective = request.group("objective").strip()
            if request.group("verb"):
                objective = f"{request.group('verb')} {objective}"
        named = re.fullmatch(r"(.+?)\s+in project\s+(.+)", objective, re.IGNORECASE)
        if named:
            objective, name = named.groups()
            matches = [
                p
                for p in self.store.projects()
                if name.casefold()
                in {
                    p.id.casefold(),
                    Path(p.root).name.casefold(),
                    str(p.root).casefold(),
                }
            ]
            if len(matches) != 1:
                return self._reply(
                    f"I need one connected project matching {name}. Use its project ID or select it in Projects."
                )
            project_id = matches[0].id
            ticket_id = None
        if not project_id:
            return self._reply(
                "Select a connected project, or say ‘start working on [task] in project [name]’."
            )
        project = next((p for p in self.store.projects() if p.id == project_id), None)
        if project is None or project.execution_mode == ProjectExecutionMode.READ_ONLY:
            return self._reply(
                "This project does not allow implementation tasks. Choose a project with an appropriate execution mode in Projects."
            )
        if len(objective) > 500:
            return self._reply("Please give this task a focused outcome of at most 500 characters.")
        # Exact title/id matching and active-task reuse prevent a retry from creating duplicates.
        candidates = [
            t
            for t in self.store.project_tickets()
            if t.project_id == project_id
            and (
                t.id.casefold() == objective.casefold()
                or t.title.casefold() == objective.casefold()
                or t.description.casefold() == objective.casefold()
            )
        ]
        if objective.casefold() in {"this task", "the selected task", "it"}:
            candidates = [
                t
                for t in self.store.project_tickets()
                if t.id == ticket_id and t.project_id == project_id
            ]
            if not candidates:
                return self._reply("Tell me the task outcome or select an existing ticket first.")
        if len(candidates) > 1:
            return self._reply(
                "Several tickets match that description. Ask again using the exact ticket ID."
            )
        ticket = candidates[0] if candidates else None
        if ticket and ticket.status not in {"DRAFT", "READY"}:
            return self._reply(
                f"{ticket.title} is already {ticket.status.lower().replace('_', ' ')}. I haven’t started a duplicate run.",
                ticket,
            )
        if any(
            controller.snapshot().get("status") in {"QUEUED", "RUNNING"}
            for controller in (self.workspace, self.automatic)
        ):
            return self._reply(
                "Another task is running. Let it finish before starting this one.", ticket
            )
        if ticket is None:
            ticket = self.tickets.create(
                project_id=project_id,
                title=objective[:180],
                description=objective,
                acceptance_criteria=[objective],
                constraints=[],
                priority="MEDIUM",
                dependency_ticket_ids=[],
                budget=TicketBudget(),
                created_by=actor,
            )
        try:
            if project.execution_mode in {
                ProjectExecutionMode.AUTONOMOUS_SANDBOX,
                ProjectExecutionMode.AUTONOMOUS_PROJECT,
            }:
                if ticket.status == "DRAFT":
                    self.tickets.transition(ticket.id, "READY", actor=actor, reason=message)
                self.automatic.start(project_id, ticket_id=ticket.id)
                answer = f"Started {ticket.title}. I’ll plan, implement, and validate this ticket under the project’s existing {project.execution_mode.value.lower().replace('_', ' ')} mode."
            else:
                self.workspace.start_change_plan(
                    project_id,
                    ticket.description,
                    [c.description for c in ticket.acceptance_criteria],
                    ticket.id,
                )
                self.tickets.transition(ticket.id, "ACTIVE", actor=actor, reason=message)
                answer = f"Started investigating and planning {ticket.title}. This project requires plan approval before implementation; the plan will appear in Tickets."
        except (ValueError, RuntimeError, OSError) as error:
            return self._reply(
                f"Created or found {ticket.title}, but could not start it: {error}. The ticket remains available; retry using its ID.",
                ticket,
            )
        return self._reply(answer + " Ask ‘task status’ to check progress.", ticket)

    @staticmethod
    def _reply(answer, ticket=None):
        return {
            "answer": answer,
            "route": "RLM_CONVERSATION_TASK",
            "operation_route": "TASK_WORKFLOW",
            "scope": "PROJECT" if ticket else "SYSTEM",
            "routing_confidence": 1.0,
            "authority": "EXISTING_PROJECT_WORKFLOW",
            "project_id": ticket.project_id if ticket else None,
            "ticket_id": ticket.id if ticket else None,
            "evidence": [],
        }
