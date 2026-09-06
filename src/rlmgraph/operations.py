from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from .authority import ManagedKeyring
from .store import SQLiteGraphStore

PORTABLE_EXPORT_VERSION = 1
SQLITE_SCHEMA_VERSION = 4


def ensure_outside_registered_projects(store, path: str | Path) -> Path:
    target = Path(path).resolve()
    for project in store.projects():
        root = Path(project.root).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        raise ValueError(
            f"Operational output must stay outside registered project root: {root}"
        )
    return target


class TicketAuditExporter:
    """Build a project-scoped audit; optionally authenticate it with a managed key."""

    def __init__(self, store, keyring: ManagedKeyring | None = None) -> None:
        self.store = store
        self.keyring = keyring

    def build(self, ticket_id: str) -> dict:
        ticket = next(
            (item for item in self.store.project_tickets() if item.id == ticket_id), None
        )
        if not ticket:
            raise ValueError(f"Ticket not found: {ticket_id}")
        records = [
            item.model_dump(mode="json")
            for item in self.store.project_workspace_records()
            if item.ticket_id == ticket.id and item.project_id == ticket.project_id
        ]
        validations = [
            item.model_dump(mode="json")
            for item in self.store.ticket_validation_results(ticket.id)
            if item.project_id in {None, ticket.project_id}
        ]
        attempts = [
            item.model_dump(mode="json")
            for item in self.store.implementation_sandboxes(ticket.id)
            if item.project_id == ticket.project_id
        ]
        package = {
            "format": "RLMGRAPH_TICKET_AUDIT",
            "version": PORTABLE_EXPORT_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "ticket": ticket.model_dump(mode="json"),
            "project_governance_policy": next(
                (
                    item.model_dump(mode="json")
                    for item in self.store.project_governance_policies()
                    if item.project_id == ticket.project_id
                ),
                None,
            ),
            "events": [
                item.model_dump(mode="json")
                for item in self.store.ticket_events(ticket.id)
                if item.project_id in {None, ticket.project_id}
            ],
            "workspace_records": records,
            "validation_results": validations,
            "implementation_sandboxes": attempts,
            "scheduled_work": [
                item.model_dump(mode="json")
                for item in getattr(self.store, "scheduled_work", list)()
                if item.ticket_id == ticket.id and item.project_id == ticket.project_id
            ],
        }
        canonical = json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
        package["sha256"] = hashlib.sha256(canonical).hexdigest()
        if self.keyring:
            package["authentication"] = self.keyring.sign("RLMGRAPH_AUDIT_V1", canonical)
            package["authentication"]["trust_model"] = "managed-installation-shared-secret"
        return package

    @staticmethod
    def verify(package: dict, keyring: ManagedKeyring | None = None, *, require_authenticated: bool = False) -> bool:
        expected = package.get("sha256")
        unsigned = {key: value for key, value in package.items() if key not in {"sha256", "authentication"}}
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        checksum_valid = bool(expected) and hashlib.sha256(canonical).hexdigest() == expected
        authentication = package.get("authentication")
        if not authentication:
            return checksum_valid and not require_authenticated
        if not checksum_valid or keyring is None:
            return False
        signature = {key: authentication[key] for key in ("algorithm", "key_id", "value")}
        valid, _ = keyring.verify("RLMGRAPH_AUDIT_V1", canonical, signature)
        return valid


class SQLiteMaintenance:
    """Bounded backup, restore, migration, integrity, and optimization operations."""

    REQUIRED_TABLES: ClassVar[set[str]] = {
        "project_tickets",
        "ticket_events",
        "project_workspace_records",
        "ticket_validation_results",
        "implementation_sandboxes",
        "observer_activities",
        "scheduled_work",
        "project_governance_policies",
        "schema_metadata",
    }

    def __init__(self, store: SQLiteGraphStore) -> None:
        self.store = store

    def status(self) -> dict:
        with self.store.connect() as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            row = db.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()
            tables = {
                item[0]
                for item in db.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
        return {
            "backend": "SQLITE",
            "database_path": str(Path(self.store.path).resolve()),
            "schema_version": int(row[0]) if row else 0,
            "expected_schema_version": SQLITE_SCHEMA_VERSION,
            "integrity": integrity,
            "required_tables_present": self.REQUIRED_TABLES.issubset(tables),
        }

    def migrate(self) -> dict:
        self.store.initialize()
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SQLITE_SCHEMA_VERSION)),
            )
            db.execute(f"PRAGMA user_version={SQLITE_SCHEMA_VERSION}")
            db.execute("PRAGMA optimize")
        return self.status()

    def backup(self, destination: str | Path) -> dict:
        target = ensure_outside_registered_projects(self.store, destination)
        source = Path(self.store.path).resolve(strict=True)
        if target == source:
            raise ValueError("Backup destination must differ from the active database.")
        if target.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise ValueError("Backup destination must use .db, .sqlite, or .sqlite3.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.store.connect() as source_db, sqlite3.connect(target) as target_db:
            source_db.backup(target_db)
        integrity = self._validate_database(target)
        return {
            "path": str(target),
            "bytes": target.stat().st_size,
            "integrity": integrity,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def restore(self, source: str | Path, *, confirmation: str) -> dict:
        backup = Path(source).resolve(strict=True)
        active = Path(self.store.path).resolve(strict=True)
        if backup == active:
            raise ValueError("Restore source must differ from the active database.")
        expected = f"RESTORE {backup.name}"
        if confirmation != expected:
            raise ValueError(f"Restore confirmation must be exactly: {expected}")
        self._validate_database(backup)
        safety = active.with_name(
            f"{active.stem}.pre-restore-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}{active.suffix}"
        )
        self.backup(safety)
        with sqlite3.connect(backup) as source_db, self.store.connect() as active_db:
            source_db.backup(active_db)
        status = self.status()
        if status["integrity"] != "ok" or not status["required_tables_present"]:
            raise RuntimeError("Restored database failed post-restore verification.")
        return {**status, "restored_from": str(backup), "safety_backup": str(safety)}

    def optimize(self) -> dict:
        with self.store.connect() as db:
            db.execute("PRAGMA optimize")
        return self.status()

    @classmethod
    def _validate_database(cls, path: Path) -> str:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                item[0]
                for item in db.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
        if integrity != "ok":
            raise ValueError(f"Database integrity check failed: {integrity}")
        missing = sorted(cls.REQUIRED_TABLES - tables)
        if missing:
            raise ValueError("Backup is missing required tables: " + ", ".join(missing))
        return integrity
