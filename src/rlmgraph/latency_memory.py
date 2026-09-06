"""Bounded measurements of chat stages; observations, not causal conclusions."""
import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import UTC, datetime

_STAGE_SOURCES = {
    "MEMORY_RECALL": ["src/rlmgraph/conversation_memory.py", "src/rlmgraph/episodic_recall.py"],
    "INTERPRETING": ["src/rlmgraph/observer_chat.py", "src/rlmgraph/adapters.py"],
    "CONVERSATION_MEMORY_RETRY": ["src/rlmgraph/conversation_memory.py"],
    "ROUTE_REVIEW": ["src/rlmgraph/adapters.py"],
    "ANSWER_GENERATION": ["src/rlmgraph/adapters.py"],
    "ANSWER_REVIEW": ["src/rlmgraph/adapters.py"],
    "MEMORY_SAVE": ["src/rlmgraph/observer_chat.py", "src/rlmgraph/conversation_memory.py", "src/rlmgraph/store.py"],
}


def latency_question(message):
    return bool(re.search(r"\b(?:latency|response time|bottleneck|why (?:are you|is tgram) (?:so )?slow|why.*taking so long)\b", message, re.IGNORECASE))


class ChatTiming:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.start = self.last = clock()
        self.stage = "REQUEST_SETUP"
        self.stages = defaultdict(float)

    def mark(self, stage):
        now = self.clock()
        self.stages[self.stage] += max(0, now - self.last) * 1000
        self.stage, self.last = stage, now

    def finish(self):
        self.mark("COMPLETE")
        return {"observed_at": datetime.now(UTC).isoformat(), "total_ms": round((self.last - self.start) * 1000, 2),
                "stages_ms": {key: round(value, 2) for key, value in self.stages.items()}}


def record_latency(ledger, profile_id, session_id, route, measurement):
    with ledger._connect() as connection:
        connection.execute("INSERT INTO chat_latency(profile_id, session_id, route, measurement) VALUES (?, ?, ?, ?)",
                           (profile_id, session_id, route, json.dumps(measurement)))
        connection.execute("DELETE FROM chat_latency WHERE id NOT IN (SELECT id FROM chat_latency ORDER BY id DESC LIMIT 200)")


def latency_observations(profile_id):
    from .model_call_ledger import model_call_ledger
    ledger = model_call_ledger()
    if ledger is None:
        return {"sample_count": 0, "limitation": "Chat stage measurements are not configured."}
    try:
        with ledger._connect() as connection:
            rows = connection.execute("SELECT measurement FROM chat_latency WHERE profile_id = ? ORDER BY id DESC LIMIT 30", (profile_id,)).fetchall()
    except sqlite3.Error:
        return {"sample_count": 0, "limitation": "Chat timing measurements are unavailable."}
    samples = [json.loads(row[0]) for row in rows]
    totals = sorted(item["total_ms"] for item in samples)
    stages = defaultdict(float)
    for item in samples:
        for stage, duration in item["stages_ms"].items():
            stages[stage] += duration
    return {
        "sample_count": len(samples), "latest_ms": samples[0]["total_ms"] if samples else None,
        "mean_ms": round(sum(totals) / len(totals), 2) if totals else None,
        "stages": [{"stage": stage, "total_ms": round(duration, 2),
                    "candidate_source_paths": _STAGE_SOURCES.get(stage, ["src/rlmgraph/observer_chat.py"]),
                    "share_percent": round(100 * duration / max(sum(totals), 1), 1)}
                   for stage, duration in sorted(stages.items(), key=lambda pair: -pair[1])[:8]],
        "limitation": "Recent backend wall-clock observations, not proof of root cause. Includes waiting within each stage; excludes browser rendering and transport. No CPU, disk or provider-internal profiling was performed.",
    }
