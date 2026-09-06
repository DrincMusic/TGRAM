"""Live HTTP continuity proof: start, persist, terminate, restart, and reload chat."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORT = 18787


def request(path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        f"http://127.0.0.1:{PORT}{path}", data=body,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urlopen(req, timeout=2) as response:
        return json.load(response)


def start(database: Path) -> subprocess.Popen:
    env = {**os.environ, "RLMGRAPH_DATABASE": str(database), "PYTHONPATH": str(ROOT / "src")}
    process = subprocess.Popen(
        [sys.executable, "-c", f"from rlmgraph.dashboard import serve; serve(port={PORT})"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            request("/api/health")
            return process
        except Exception:  # noqa: BLE001 - bounded readiness probe
            time.sleep(.1)
    process.terminate()
    raise RuntimeError("backend did not become ready")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rlmgraph-chat-restart-") as directory:
        database = Path(directory) / "proof.db"
        first_process = start(database)
        try:
            first = request("/api/chat", {
                "message": "What is my token usage?", "history": [],
                "project_id": None, "ticket_id": None,
            })
        finally:
            first_process.terminate()
            first_process.wait(timeout=10)
        second_process = start(database)
        try:
            sessions = request("/api/chat/sessions")["sessions"]
            restored = next(item for item in sessions if item["id"] == first["session_id"])
            assert len(restored["turns"]) == 1
            print(json.dumps({
                "restart_continuity": True, "session_id": restored["id"],
                "turns": len(restored["turns"]), "route": restored["turns"][0]["route"],
                "authority": restored["turns"][0]["authority"],
            }))
        finally:
            second_process.terminate()
            second_process.wait(timeout=10)
            # Windows may release SQLite's file handle just after process termination.
            time.sleep(.25)


if __name__ == "__main__":
    main()
