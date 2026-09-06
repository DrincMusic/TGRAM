from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .sqlite_utils import ClosingSQLiteConnection


class ProjectColdArchive:
    """Immutable full-fidelity events. Archive payloads are never implicit prompt context."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_events (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    task_id INTEGER,
                    attempt INTEGER,
                    phase TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            self.path, timeout=10, factory=ClosingSQLiteConnection
        )

    def append(
        self, *, kind: str, payload: dict, task_id: int | None = None,
        attempt: int | None = None, phase: str = "",
    ) -> str:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        event_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO archive_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, datetime.now(UTC).isoformat(), kind, task_id, attempt,
                    phase, hashlib.sha256(serialized.encode()).hexdigest(), serialized,
                ),
            )
        return event_id

    def get(self, event_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, occurred_at, kind, task_id, attempt, phase, content_hash, payload "
                "FROM archive_events WHERE id=?", (event_id,),
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return {
            "id": row[0], "occurred_at": row[1], "kind": row[2], "task_id": row[3],
            "attempt": row[4], "phase": row[5], "content_hash": row[6],
            "payload": json.loads(row[7]),
        }

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM archive_events").fetchone()[0])
