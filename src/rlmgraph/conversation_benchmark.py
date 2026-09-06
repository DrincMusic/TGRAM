from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from .model_call_ledger import ModelCallLedger, model_call_scope


class BaselineConversationResponse(BaseModel):
    answer: str


class ConversationBenchmarkStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS conversation_benchmarks "
                "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save(self, payload: dict) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO conversation_benchmarks VALUES (?, ?, ?)",
                (payload["id"], payload["created_at"], json.dumps(payload)),
            )

    def latest(self) -> dict | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM conversation_benchmarks ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else None

    def all(self) -> list[dict]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload FROM conversation_benchmarks ORDER BY created_at DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


class PairedConversationBenchmark:
    prompts: ClassVar[list[str]] = [
        "Remember this benchmark fact: the project codename is Atlas and its launch city is Reno.",
        "Correction: Atlas now has Boise as its final launch city and uses SQLite for durable state.",
        "What are the project codename, final launch city, and durable-state database? Answer all three.",
    ]
    required_terms: ClassVar[list[str]] = ["atlas", "boise", "sqlite"]

    def __init__(self, observer_chat, ledger: ModelCallLedger, store: ConversationBenchmarkStore, root: Path) -> None:
        self.observer_chat = observer_chat
        self.ledger = ledger
        self.store = store
        self.root = root

    def run(self) -> dict:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        baseline_answers = self._run_baseline(run_id)
        rlm_answers = self._run_rlm(run_id)
        baseline = self.ledger.summary(benchmark_run_id=run_id, benchmark_arm="BASELINE")
        rlm = self.ledger.summary(benchmark_run_id=run_id, benchmark_arm="RLMGRAPH")
        baseline_tokens = int(baseline["metered_total_tokens"])
        rlm_tokens = int(rlm["metered_total_tokens"])
        savings = baseline_tokens - rlm_tokens
        baseline_quality = self._quality(baseline_answers[-1])
        rlm_quality = self._quality(rlm_answers[-1])
        result = {
            "id": run_id,
            "created_at": created_at,
            "status": "COMPLETED",
            "model": self.observer_chat.interpreter.model or "provider-default",
            "prompts": self.prompts,
            "required_terms": self.required_terms,
            "baseline": {**baseline, "answers": baseline_answers, "quality": baseline_quality},
            "rlmgraph": {**rlm, "answers": rlm_answers, "quality": rlm_quality},
            "baseline_tokens": baseline_tokens,
            "rlmgraph_tokens": rlm_tokens,
            "tokens_saved": savings,
            "savings_percent": round(savings / baseline_tokens * 100, 1) if baseline_tokens else 0.0,
            "quality_preserved": rlm_quality >= baseline_quality,
        }
        self.store.save(result)
        return result

    def _run_baseline(self, run_id: str) -> list[str]:
        transcript: list[dict[str, str]] = []
        answers: list[str] = []
        with model_call_scope(benchmark_run_id=run_id, benchmark_arm="BASELINE"):
            for message in self.prompts:
                transcript.append({"role": "user", "content": message})
                prompt = (
                    "You are the persistent full-transcript baseline. Use the complete conversation "
                    "below without graph memory, selective retrieval, summarization, or compaction. "
                    "Answer the latest user message naturally and return only the structured response.\n\n"
                    + json.dumps(transcript, indent=2)
                )
                result = self.observer_chat.interpreter._run_structured(
                    prompt, self.root, BaselineConversationResponse, timeout_seconds=120
                )
                answers.append(result.answer)
                transcript.append({"role": "assistant", "content": result.answer})
        return answers

    def _run_rlm(self, run_id: str) -> list[str]:
        session_id = f"benchmark-{run_id}"
        history: list[dict[str, str]] = []
        answers: list[str] = []
        with model_call_scope(benchmark_run_id=run_id, benchmark_arm="RLMGRAPH"):
            for message in self.prompts:
                result = self.observer_chat.safe_reply(
                    message, history, None, None, session_id, "SYSTEM", "DIRECT", None
                )
                answer = str(result.get("answer", ""))
                answers.append(answer)
                history.extend([
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": answer},
                ])
        return answers

    def _quality(self, answer: str) -> float:
        normalized = answer.casefold()
        matches = sum(term.casefold() in normalized for term in self.required_terms)
        return round(matches / len(self.required_terms), 3)


class ConversationBenchmarkController:
    def __init__(self, benchmark: PairedConversationBenchmark) -> None:
        self.benchmark = benchmark
        self.status = "IDLE"
        self.error = ""
        self.result = benchmark.store.latest()
        self._thread: threading.Thread | None = None

    def start(self) -> dict:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("A controlled conversation comparison is already running.")
        self.status = "RUNNING"
        self.error = ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.snapshot()

    def _run(self) -> None:
        try:
            self.result = self.benchmark.run()
            self.status = "COMPLETED"
        except Exception as exc:  # noqa: BLE001 - background failures must reach the UI
            self.error = str(exc)
            self.status = "FAILED"

    def snapshot(self) -> dict:
        return {"status": self.status, "error": self.error, "result": self.result}
