from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

import tiktoken

from .sqlite_utils import ClosingSQLiteConnection

_call_context: ContextVar[dict[str, str] | None] = ContextVar(
    "model_call_context", default=None
)


@contextmanager
def model_call_scope(**context: str) -> Iterator[None]:
    token = _call_context.set({**(_call_context.get() or {}), **context})
    try:
        yield
    finally:
        _call_context.reset(token)


def estimate_tokens(value: str) -> int:
    """Conservative provider-neutral estimate used only when usage is unavailable."""
    return max(1, (len(value) + 3) // 4)


def exact_tokens(value: str) -> int:
    """Count locally observable text with the same encoding used by benchmarks."""
    return len(tiktoken.get_encoding("o200k_base").encode(value))


class ModelCallLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS chat_latency (id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, session_id TEXT, route TEXT NOT NULL, measurement TEXT NOT NULL)")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS model_calls (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    role TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    token_source TEXT NOT NULL,
                    error TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO ledger_settings(key, value) VALUES "
                "('measurement_started_at', ?)",
                (datetime.now(UTC).isoformat(),),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            self.path, timeout=10, factory=ClosingSQLiteConnection
        )

    @property
    def measurement_started_at(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM ledger_settings WHERE key = 'measurement_started_at'"
            ).fetchone()
        return str(row[0])

    def record(
        self, *, role: str, operation: str, provider: str, model: str,
        status: str, latency_ms: float, input_tokens: int, output_tokens: int,
        token_source: str, error: str = "", metadata: dict | None = None,
    ) -> None:
        values = (
            str(uuid.uuid4()), datetime.now(UTC).isoformat(), role, operation,
            provider, model or "provider-default", status, latency_ms,
            max(0, input_tokens), max(0, output_tokens), token_source,
            error[:2000], json.dumps(
                {**(_call_context.get() or {}), **(metadata or {})}, sort_keys=True
            ),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO model_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def summary(
        self, *, benchmark_run_id: str = "", benchmark_arm: str = "",
        benchmark_task: str = "",
    ) -> dict[str, int | float]:
        clauses: list[str] = ["occurred_at >= ?"]
        parameters: list[str] = [self.measurement_started_at]
        if benchmark_run_id:
            clauses.append("json_extract(metadata, '$.benchmark_run_id') = ?")
            parameters.append(benchmark_run_id)
        if benchmark_arm:
            clauses.append("json_extract(metadata, '$.benchmark_arm') = ?")
            parameters.append(benchmark_arm)
        if benchmark_task:
            clauses.append("json_extract(metadata, '$.benchmark_task') = ?")
            parameters.append(benchmark_task)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) calls,
                       COALESCE(SUM(input_tokens + output_tokens), 0) total,
                       COALESCE(SUM(CASE WHEN token_source = 'PROVIDER' THEN
                           input_tokens + output_tokens ELSE 0 END), 0) measured,
                       COALESCE(SUM(CASE WHEN token_source = 'ESTIMATE' THEN
                           input_tokens + output_tokens ELSE 0 END), 0) estimated,
                       COALESCE(SUM(CASE WHEN token_source = 'PROVIDER' THEN 1 ELSE 0 END), 0)
                           measured_calls,
                       COALESCE(SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END), 0) failed
                       ,COALESCE(SUM(CAST(json_extract(metadata, '$.local_observed_input_tokens') AS INTEGER)), 0) local_input
                       ,COALESCE(SUM(CAST(json_extract(metadata, '$.provider_unexplained_input_tokens') AS INTEGER)), 0) unexplained
                       ,COALESCE(SUM(CAST(json_extract(metadata, '$.provider_cached_input_tokens') AS INTEGER)), 0) cached
                       ,COALESCE(SUM(CAST(json_extract(metadata, '$.provider_uncached_input_tokens') AS INTEGER)), 0) uncached
                       ,COALESCE(SUM(CAST(json_extract(metadata, '$.provider_unexplained_uncached_input_tokens') AS INTEGER)), 0) unexplained_uncached
                FROM model_calls
                """ + where,
                parameters,
            ).fetchone()
            excluded = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(input_tokens + output_tokens), 0) "
                "FROM model_calls WHERE occurred_at < ?",
                (self.measurement_started_at,),
            ).fetchone()
        calls = int(row[0])
        measured_calls = int(row[4])
        return {
            "model_call_count": calls,
            "metered_total_tokens": int(row[1]),
            "provider_measured_tokens": int(row[2]),
            "estimated_tokens": int(row[3]),
            "provider_measured_calls": measured_calls,
            "estimated_call_count": calls - measured_calls,
            "failed_model_calls": int(row[5]),
            "local_observed_input_tokens": int(row[6]),
            "provider_unexplained_input_tokens": int(row[7]),
            "provider_cached_input_tokens": int(row[8]),
            "provider_uncached_input_tokens": int(row[9]),
            "provider_unexplained_uncached_input_tokens": int(row[10]),
            "provider_measurement_coverage_percent": (
                round(measured_calls / calls * 100, 1) if calls else 0.0
            ),
            "measurement_started_at": self.measurement_started_at,
            "excluded_historical_calls": int(excluded[0]),
            "excluded_historical_tokens": int(excluded[1]),
        }

    def diagnostics(self, limit: int = 25) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT occurred_at, role, operation, provider, model, status, input_tokens, "
                "output_tokens, token_source, latency_ms, metadata FROM model_calls "
                "WHERE occurred_at >= ? ORDER BY occurred_at DESC LIMIT ?",
                (self.measurement_started_at, max(1, min(limit, 200))),
            ).fetchall()
        return [
            {
                "occurred_at": row[0], "role": row[1], "operation": row[2],
                "provider": row[3], "model": row[4], "status": row[5],
                "provider_input_tokens": row[6], "provider_output_tokens": row[7],
                "token_source": row[8], "latency_ms": row[9],
                **json.loads(row[10]),
            }
            for row in rows
        ]


_ledger: ModelCallLedger | None = None


def configure_model_call_ledger(path: str | Path) -> ModelCallLedger:
    global _ledger
    _ledger = ModelCallLedger(path)
    return _ledger


@contextmanager
def scoped_model_call_ledger(ledger: ModelCallLedger) -> Iterator[ModelCallLedger]:
    """Temporarily route model-call accounting without leaking global configuration."""
    global _ledger
    previous = _ledger
    _ledger = ledger
    try:
        yield ledger
    finally:
        _ledger = previous


def model_call_ledger() -> ModelCallLedger | None:
    return _ledger
