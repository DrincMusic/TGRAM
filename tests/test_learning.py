import pytest

from rlmgraph.learning import ApplicationReport, LessonDraft, LessonLibrary
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.workflow_fact_search import WorkflowFactSearch


def fixture(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "core.py").write_text("value = 1\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    project = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root)).project_id
    return root, store, project, LessonLibrary(store)


def draft():
    return LessonDraft(topic="Caching tradeoffs", statement="Caching may reduce repeated lookup latency.",
        source_kind="GPT_EXPLANATION", source_ref="conversation:test", source_excerpt="Try caching repeated lookups.",
        applies_when="Repeated database lookup requests", limitations="Measure invalidation costs and memory usage.")


def test_lesson_is_sourced_deduplicated_and_used_by_workflow(tmp_path):
    root, store, project, library = fixture(tmp_path)
    first = library.learn(project, draft(), "user")
    assert library.learn(project, draft(), "user")["id"] == first["id"]
    assert len(library.list(project)) == 1
    assert first["status"] == "UNTESTED"
    hits = WorkflowFactSearch(store).search("database lookup latency", root, project).hits
    assert any(hit.reference == first["id"] and hit.kind == "SOURCED_LESSON" for hit in hits)
    assert library.search("unrelatedzz", project) == []
    other = tmp_path / "other"
    other.mkdir()
    (other / "core.py").write_text("value = 2\n")
    other_id = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(other)).project_id
    assert library.search("caching", other_id) == []
    with pytest.raises(ValueError, match="not found"):
        library.report(other_id, first["id"], ApplicationReport(outcome="HELPED", context="test",
            observation="faster", evidence_ref="run:1"), "user")


def test_experience_keeps_failures_without_promoting_reports_to_truth(tmp_path):
    _, _, project, library = fixture(tmp_path)
    lesson = library.learn(project, draft(), "user")
    for i in range(15):
        report = ApplicationReport(outcome="DID_NOT_HELP" if i == 14 else "HELPED",
            context="lookup experiment", observation=f"measurement {i}", evidence_ref=f"run:{i}")
        lesson = library.report(project, lesson["id"], report, "user")
    assert len(lesson["reports"]) == 12
    assert lesson["status"] == "CONTESTED"
    assert lesson["reports"][-1]["evidence_ref"] == "run:14"
    assert len(library.search("lookup", project)[0]["reports"]) == 2
    for _ in range(13):
        lesson = library.report(project, lesson["id"], ApplicationReport(outcome="HELPED",
            context="another trial", observation="lower latency", evidence_ref="run:new"), "user")
    assert lesson["status"] == "CONTESTED"  # Forgetting detailed notes cannot erase a failure.
    assert lesson["outcome_counts"]["DID_NOT_HELP"] == 1
    with pytest.raises(ValueError):
        library.learn(project, draft().model_copy(update={"limitations": " "}), "user")


def test_lesson_http_requires_login_and_records_server_actor(tmp_path):
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from types import SimpleNamespace
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from rlmgraph.dashboard import _handler
    from rlmgraph.local_profiles import LocalProfileStore

    _, store, project, _ = fixture(tmp_path)
    profiles = LocalProfileStore(tmp_path / "profiles.json")
    login = profiles.create("Learner", "example password")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(SimpleNamespace(store=store, local_profiles=profiles)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/lessons"
    payload = json.dumps({"project_id": project, "lesson": draft().model_dump(), "actor": "forged"}).encode()
    try:
        with pytest.raises(HTTPError):
            urlopen(Request(url, data=payload), timeout=5)
        with urlopen(Request(url, data=payload, headers={"Authorization": f"Bearer {login['token']}"}), timeout=5) as response:
            lesson = json.load(response)["lesson"]
        assert lesson["recorded_by"] == login["profile"]["id"]
        with urlopen(Request(url + f"?project_id={project}", headers={"Authorization": f"Bearer {login['token']}"}), timeout=5) as response:
            assert json.load(response)["lessons"][0]["id"] == lesson["id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
