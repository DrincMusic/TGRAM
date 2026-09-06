import hashlib
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from rlmgraph.dashboard import (
    DashboardApplication,
    DemoController,
    _handler,
    default_observer_database,
)
from rlmgraph.interactive_workspace import InteractiveProjectWorkspaceController
from rlmgraph.models import Evidence, ProjectIdeaSuggestion, ProjectIdeaSuggestionResult
from rlmgraph.store import SQLiteGraphStore


def _manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _post(
    server: ThreadingHTTPServer, path: str, payload: dict[str, str]
) -> tuple[int, dict]:
    host, port = server.server_address
    request = Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": "http://localhost:3000"},
        method="POST",
    )
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        return error.code, json.loads(error.read())
    with response:
        return response.status, json.loads(response.read())


class FakeIdeaSuggester:
    model = "fixture-model"
    sandbox = "read-only"

    def __init__(self) -> None:
        self.last_authorized_paths = ["pricing.py", "tests/test_pricing.py"]
        self.last_source_bytes = 128

    def suggest(self, project_root: Path, indexed_paths: list[str]):
        assert project_root.name == "disposable-python-project"
        assert set(indexed_paths) == {"pricing.py", "tests/test_pricing.py"}
        return ProjectIdeaSuggestionResult(
            suggestions=[
                ProjectIdeaSuggestion(
                    title="Explain the shipping boundary",
                    detail="Make the threshold visible where a user makes the decision.",
                    rationale="The current behavior is encoded only in a comparison.",
                    evidence=[
                        Evidence(
                            path="pricing.py",
                            line=2,
                            detail="return total >= 50",
                        )
                    ],
                )
            ],
            files_examined=["pricing.py"],
            confidence=0.91,
        )


def test_default_observer_database_is_outside_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr("rlmgraph.dashboard.os.name", "nt")
    assert default_observer_database() == local_app_data / "RLMGraph" / "observer.db"


def test_project_connect_api_requires_a_nonempty_explicit_root_and_scans_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "disposable-python-project"
    (project_root / "tests").mkdir(parents=True)
    (project_root / "pricing.py").write_text(
        "def free_shipping(total):\n    return total >= 50\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_pricing.py").write_text(
        "from pricing import free_shipping\n\ndef test_boundary():\n    assert free_shipping(50)\n",
        encoding="utf-8",
    )
    before = _manifest(project_root)
    store = SQLiteGraphStore(tmp_path / "observer.db")
    store.initialize()
    application = DashboardApplication(
        store,
        DemoController(tmp_path),
        workspace_controller=InteractiveProjectWorkspaceController(
            store, idea_suggester=FakeIdeaSuggester()
        ),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(application))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        monkeypatch.setattr(
            "rlmgraph.dashboard.select_project_directory",
            lambda: str(project_root.resolve()),
        )
        status, selection = _post(server, "/api/projects/browse", {})
        assert status == 200
        assert selection == {
            "root": str(project_root.resolve()),
            "cancelled": False,
        }
        assert store.projects() == []
        assert _manifest(project_root) == before

        monkeypatch.setattr("rlmgraph.dashboard.select_project_directory", lambda: None)
        status, selection = _post(server, "/api/projects/browse", {})
        assert status == 200
        assert selection == {"root": None, "cancelled": True}

        status, error = _post(server, "/api/projects/connect", {"root": ""})
        assert status == 409
        assert error["error"] == "Select a local project folder before connecting."
        assert store.projects() == []

        status, result = _post(
            server, "/api/projects/connect", {"root": str(project_root)}
        )
        assert status == 201
        assert result["project"]["root"] == str(project_root.resolve())
        assert result["project"]["read_only"] is True
        assert result["scan"]["read_only_verified"] is True
        assert _manifest(project_root) == before

        status, suggestions = _post(
            server,
            "/api/projects/ideas/suggest",
            {"project_id": result["project"]["id"]},
        )
        assert status == 200
        assert suggestions["suggestions"][0]["title"] == "Explain the shipping boundary"
        assert suggestions["worker"] == {
            "name": "Codex CLI",
            "model": "fixture-model",
            "sandbox": "read-only",
            "calls": 1,
            "indexed_files": 2,
            "authorized_files": 2,
            "source_bytes": 128,
            "monetary_cost": None,
            "cost_basis": "Codex CLI account-backed execution; monetary cost is not exposed.",
        }
        assert suggestions["persistence"] == "NOT_SAVED"
        assert suggestions["authority"] == "NO_TICKET_RUN_OR_PROJECT_WRITE"
        assert store.projects()[0].ideas == []
        assert _manifest(project_root) == before

        status, project = _post(
            server,
            "/api/projects/organization",
            {"project_id": result["project"]["id"], "organization": "Checkout Labs"},
        )
        assert status == 200
        assert project["organization"] == "Checkout Labs"

        status, idea = _post(
            server,
            "/api/projects/ideas",
            {
                "project_id": result["project"]["id"],
                "title": "Explain shipping thresholds",
                "detail": "Keep the boundary visible in product language.",
            },
        )
        assert status == 201
        assert idea["status"] == "DRAFT"

        status, idea = _post(
            server,
            "/api/projects/ideas/status",
            {
                "project_id": result["project"]["id"],
                "idea_id": idea["id"],
                "status": "ARCHIVED",
            },
        )
        assert status == 200
        assert idea["status"] == "ARCHIVED"

        status, rescanned = _post(
            server, "/api/projects/connect", {"root": str(project_root)}
        )
        assert status == 201
        assert rescanned["project"]["organization"] == "Checkout Labs"
        assert rescanned["project"]["ideas"][0]["status"] == "ARCHIVED"
        assert _manifest(project_root) == before

        status, autonomous = _post(
            server,
            "/api/projects/access",
            {"project_id": result["project"]["id"], "execution_mode": "AUTONOMOUS_PROJECT"},
        )
        assert status == 200
        assert autonomous["execution_mode"] == "AUTONOMOUS_PROJECT"
        assert autonomous["read_only"] is True
        option = application.workspace_controller.options()["projects"][0]
        assert option["execution_mode"] == "AUTONOMOUS_PROJECT"
        assert option["write_capability"] is True

        status, protected = _post(
            server,
            "/api/projects/access",
            {"project_id": result["project"]["id"], "execution_mode": "PROTECTED"},
        )
        assert status == 200
        assert protected["execution_mode"] == "PROTECTED"

        new_root = tmp_path / "brand-new-project"
        status, created = _post(
            server, "/api/projects/create", {"root": str(new_root)}
        )
        assert status == 201
        assert created["project"]["root"] == str(new_root.resolve())
        assert created["created_files"] == ["manifest.md", "goals.json"]
        assert (new_root / "manifest.md").read_text(encoding="utf-8").startswith(
            "# brand-new-project"
        )
        assert json.loads((new_root / "goals.json").read_text(encoding="utf-8")) == []

        status, error = _post(
            server, "/api/projects/create", {"root": str(new_root)}
        )
        assert status == 409
        assert "already exists" in error["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
