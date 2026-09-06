from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .sqlite_utils import ClosingSQLiteConnection

TERMINAL_STATUSES = {"DONE", "BLOCKED"}


@dataclass(frozen=True)
class TaskLease:
    task_id: int
    objective: str
    acceptance: str
    dependencies: list[int]
    attempt: int
    lease_id: str
    prior_failure: str


class ProjectTaskGraph:
    """Persistent evidence-gated task scheduler above disposable workers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS project_tasks (
                    task_id INTEGER PRIMARY KEY,
                    objective TEXT NOT NULL,
                    acceptance TEXT NOT NULL,
                    dependencies TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_id TEXT NOT NULL DEFAULT '',
                    memory_refs TEXT NOT NULL DEFAULT '[]',
                    result TEXT NOT NULL DEFAULT '{}',
                    evidence TEXT NOT NULL DEFAULT '[]',
                    failure TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    invalidated_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            self.path, timeout=10, factory=ClosingSQLiteConnection
        )

    def initialize(self, tasks: list[dict]) -> None:
        with self._connect() as connection:
            for task in tasks:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_tasks
                    (task_id, objective, acceptance, dependencies, priority, status)
                    VALUES (?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        int(task["task_id"]), str(task["objective"]),
                        str(task.get("acceptance", task["objective"])),
                        json.dumps(list(task.get("dependencies", []))),
                        int(task.get("priority", 0)),
                    ),
                )

    def claim_next(self, *, max_attempts: int = 2) -> TaskLease | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT task_id, objective, acceptance, dependencies, attempt_count, failure
                FROM project_tasks
                WHERE status IN ('PENDING', 'READY', 'FAILED', 'INVALIDATED')
                      AND attempt_count < ?
                ORDER BY CASE status WHEN 'FAILED' THEN 0 WHEN 'INVALIDATED' THEN 1 ELSE 2 END,
                         priority DESC, task_id
                """,
                (max_attempts,),
            ).fetchall()
            completed = {
                row[0] for row in connection.execute(
                    "SELECT task_id FROM project_tasks WHERE status = 'DONE'"
                )
            }
            selected = next(
                (row for row in rows if set(json.loads(row[3])).issubset(completed)), None
            )
            if selected is None:
                return None
            lease_id = str(uuid.uuid4())
            attempt = int(selected[4]) + 1
            connection.execute(
                "UPDATE project_tasks SET status='IN_PROGRESS', attempt_count=?, lease_id=? "
                "WHERE task_id=?",
                (attempt, lease_id, selected[0]),
            )
        return TaskLease(
            task_id=int(selected[0]), objective=str(selected[1]),
            acceptance=str(selected[2]), dependencies=json.loads(selected[3]),
            attempt=attempt, lease_id=lease_id, prior_failure=str(selected[5]),
        )

    def begin_verification(
        self, lease: TaskLease, *, result: dict, memory_refs: list[str],
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE project_tasks SET status='VERIFYING', result=?, memory_refs=? "
                "WHERE task_id=? AND lease_id=? AND status='IN_PROGRESS'",
                (json.dumps(result), json.dumps(memory_refs), lease.task_id, lease.lease_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Task lease is stale or task is in an invalid state.")

    def complete(
        self, lease: TaskLease, *, evidence: list[dict], memory_refs: list[str] | None = None,
    ) -> None:
        if not evidence:
            raise ValueError("Completion requires verification evidence.")
        fields = {
            "evidence": json.dumps(evidence), "failure": "",
            "completed_at": datetime.now(UTC).isoformat(),
        }
        if memory_refs is not None:
            fields["memory_refs"] = json.dumps(memory_refs)
        self._transition_leased(lease, "DONE", **fields)

    def fail(
        self, lease: TaskLease, *, reason: str, evidence: list[dict],
        memory_refs: list[str] | None = None,
    ) -> None:
        fields = {"failure": reason[:2000], "evidence": json.dumps(evidence)}
        if memory_refs is not None:
            fields["memory_refs"] = json.dumps(memory_refs)
        self._transition_leased(lease, "FAILED", **fields)

    def block_exhausted(self, *, max_attempts: int = 2) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE project_tasks SET status='BLOCKED' "
                "WHERE status='FAILED' AND attempt_count >= ?",
                (max_attempts,),
            )
            return cursor.rowcount

    def invalidate(self, task_id: int, reason: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM project_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None or row[0] != "DONE":
                raise ValueError("Only completed tasks can be invalidated.")
            rows = connection.execute(
                "SELECT task_id, dependencies FROM project_tasks"
            ).fetchall()
            affected = {task_id}
            changed = True
            while changed:
                changed = False
                for candidate, dependencies in rows:
                    if candidate not in affected and affected.intersection(json.loads(dependencies)):
                        affected.add(candidate)
                        changed = True
            placeholders = ",".join("?" for _ in affected)
            connection.execute(
                f"UPDATE project_tasks SET status='INVALIDATED', invalidated_reason=?, "
                f"completed_at='', attempt_count=0, failure='' "
                f"WHERE task_id IN ({placeholders})",
                (reason[:2000], *sorted(affected)),
            )

    def recover_interrupted(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE project_tasks SET status='FAILED', lease_id='', "
                "failure='Worker interrupted before verification completed' "
                "WHERE status IN ('IN_PROGRESS','VERIFYING')"
            )
            return cursor.rowcount

    def reconcile_complete(self, task_id: int, *, evidence: dict) -> bool:
        """Promote a previously failed task when later final evidence proves it now passes."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, evidence FROM project_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None or row[0] == "DONE":
                return False
            combined = [*json.loads(row[1]), evidence]
            cursor = connection.execute(
                "UPDATE project_tasks SET status='DONE', evidence=?, failure='', "
                "completed_at=?, invalidated_reason='' WHERE task_id=?",
                (json.dumps(combined), datetime.now(UTC).isoformat(), task_id),
            )
            return cursor.rowcount == 1

    def snapshot(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, objective, acceptance, dependencies, priority, status, "
                "attempt_count, memory_refs, result, evidence, failure, completed_at, "
                "invalidated_reason FROM project_tasks ORDER BY task_id"
            ).fetchall()
        return [
            {
                "task_id": row[0], "objective": row[1], "acceptance": row[2],
                "dependencies": json.loads(row[3]), "priority": row[4], "status": row[5],
                "attempt_count": row[6], "memory_refs": json.loads(row[7]),
                "result": json.loads(row[8]), "evidence": json.loads(row[9]),
                "failure": row[10], "completed_at": row[11],
                "invalidated_reason": row[12],
            }
            for row in rows
        ]

    def progress(self) -> dict[str, int]:
        snapshot = self.snapshot()
        counts: dict[str, int] = {"TOTAL": len(snapshot)}
        for task in snapshot:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        return counts

    def _transition_leased(self, lease: TaskLease, status: str, **fields: str) -> None:
        assignments = ["status=?", "lease_id=''"] + [f"{name}=?" for name in fields]
        values = [status, *fields.values(), lease.task_id, lease.lease_id]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE project_tasks SET {', '.join(assignments)} "
                "WHERE task_id=? AND lease_id=? AND status IN ('IN_PROGRESS','VERIFYING')",
                values,
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Task lease is stale or task is in an invalid state.")
