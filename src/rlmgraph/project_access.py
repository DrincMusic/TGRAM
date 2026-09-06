"""Answer project-access questions from local state without asking a language model."""

from __future__ import annotations

import os
import re
from pathlib import Path

_QUESTION = re.compile(
    r"^(?:can you|could you|are you (?:actually )?able to|do you have (?:access|permission) to) "
    r"(?:(?P<action>work (?:inside(?: of)?|within|in|on)|access|inspect|read|edit|modify) )?"
    r"(?P<target>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)


def project_access_question(message: str) -> tuple[str, str] | None:
    match = _QUESTION.fullmatch(" ".join(message.split()))
    if not match:
        return None
    action = match.group("action")
    if (
        action
        and action.casefold() in {"read", "inspect", "edit", "modify", "work on"}
        and not re.search(r"\b(?:project|repository|repo)\b", match.group("target"), re.IGNORECASE)
    ):
        return None
    # Leave general capability questions and action requests on their existing routes.
    if action is None and not message.lower().startswith(
        ("do you have access to", "do you have permission to")
    ):
        return None
    target = match.group("target").strip(" \"'‘’“”?")
    target = re.sub(r"^(?:the )?(?:project|repository|repo)(?:\s*[:,]\s*|\s+)", "", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+(?:project|repository|repo)$", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^the\s+", "", target, flags=re.IGNORECASE)
    return ((action or "access").casefold(), target.strip(" \"'‘’“”"))


def project_access_followup(message, turns):
    challenge = re.compile(
        r"^(?:(?:it|that|the project) (?:should (?:be already|already be)|is already) "
        r"(?:connected|registered)|(?:are you sure|check again|got what|what did you get))\s*[.!?]*$",
        re.IGNORECASE,
    )
    if not challenge.fullmatch(message.strip()):
        return None
    for turn in reversed(turns[-4:]):
        question = project_access_question(turn.user_message)
        if question:
            return question
        if not challenge.fullmatch(turn.user_message.strip()):
            break
    return None


def project_access_reply(store, question: tuple[str, str], selected_id: str | None) -> dict:
    action, target = question
    projects = list(store.projects())
    implicit = target.casefold() in {"this", "that", "it", "current", "selected"}

    def aliases(project):
        root = str(project.root).replace("\\", "/").rstrip("/")
        return {str(project.id).casefold(), root.casefold(), root.rsplit("/", 1)[-1].casefold()}

    matches = [
        project
        for project in projects
        if (
            project.id == selected_id
            if implicit
            else target.replace("\\", "/").rstrip("/").casefold() in aliases(project)
        )
    ]
    capability = {"requested_project": target, "project_id": None, "available": False}
    evidence = [
        {"source": "project_registry", "detail": "Checked registered project IDs and folder names."}
    ]
    if not matches:
        answer = (
            "No—not yet. Select a connected project so I can check its access."
            if implicit
            else f"No—not currently. I couldn’t find a connected project named {target}. "
            "Connect it in Projects, then ask me again."
        )
    elif len(matches) > 1:
        answer = (
            f"I can’t give a reliable yes or no for {target} until you identify which project: "
            + "; ".join(f"{project.id} ({project.root})" for project in matches)
            + ". Ask again using its full path or project ID."
        )
    else:
        project = matches[0]
        capability["project_id"] = project.id
        capability["root"] = project.root
        accessible = False
        try:
            # Probe only the registered directory, never an arbitrary path from the prompt.
            with os.scandir(Path(project.root)) as entries:
                next(entries, None)
            accessible = True
        except OSError:
            pass
        selected = bool(getattr(project, "explicitly_selected", False))
        read_only = bool(getattr(project, "read_only", False))
        capability.update(
            directory_accessible=accessible, explicitly_selected=selected, read_only=read_only
        )
        evidence.append(
            {
                "source": "local_project_access",
                "path": project.root,
                "detail": f"Directory accessible: {accessible}; explicitly connected: {selected}; read-only boundary: {read_only}.",
            }
        )
        if not selected:
            answer = f"No—not yet. {target} is recorded but hasn’t been explicitly connected for work. Connect it in Projects first."
        elif not accessible:
            answer = f"No—not right now. {target} is connected, but I can’t open its folder at {project.root}. Restore access or reconnect its current location."
        elif not read_only:
            answer = f"No—not through the current investigation workflow. {target} is missing the required read-only project boundary. Reconnect it in Projects."
        elif action in {"edit", "modify"}:
            answer = f"No—not directly from this conversation. I can inspect {target} and help prepare a change, but applying changes requires the project’s ticket, validation, and approval workflow."
        else:
            capability["available"] = True
            answer = f"Yes—I can work with {target} at {project.root} for read-only investigation and change planning. "
            answer += "The project index may need refreshing before work starts. "
            answer += "Applying changes goes through tickets, validation, and approval. This access check does not confirm that every file is readable or that the model provider is online."
    return {
        "answer": answer,
        "route": "RLM_PROJECT_ACCESS",
        "operation_route": "PROJECT_ACCESS_CHECK",
        "scope": "SYSTEM",
        "investigation_mode": "DIRECT",
        "routing_confidence": 1.0,
        "routing_reason": "Answered from registered project state and a local directory access check.",
        "authority": "READ_ONLY_PROJECT_ACCESS_CHECK_NO_MODEL_CALL",
        "claim_confidence": None,
        "project_id": capability["project_id"],
        "project_access": capability,
        "evidence": evidence,
    }
