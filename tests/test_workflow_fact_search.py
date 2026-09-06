from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.workflow_fact_search import WorkflowFactSearch


def setup_search(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "neutral.py").write_text("# Conversation pagination preserves chronology\nVALUE = 1\n")
    (root / "other.py").write_text("# Connection pooling reduces database latency\nVALUE = 2\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    scan = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))
    return root, store, scan.project_id


def test_search_finds_content_and_requeries_for_branch(tmp_path):
    root, store, project = setup_search(tmp_path)
    search = WorkflowFactSearch(store)
    first = search.search("pagination chronology", root, project)
    assert [hit.path for hit in first.hits] == ["neutral.py"]
    assert first.hits[0].line == 1
    assert first.hits[0].matched_terms == ["chronology", "pagination"]
    second = search.search("database latency", root, project)
    assert [hit.path for hit in second.hits] == ["other.py"]
    assert "not proof of absence" in second.context()
    assert search.search("unrelatedzz", root, project).hits == []


def test_search_excludes_changed_foreign_and_escaping_files_and_reports_bounds(tmp_path):
    root, store, project = setup_search(tmp_path)
    search = WorkflowFactSearch(store)
    files = store.project_files(project)
    foreign = files[0].model_copy(update={"project_id": "another-project"})
    escaped = files[0].model_copy(update={"path": "../outside.py"})
    assert search.search("pagination", root, project, files=[foreign, escaped]).hits == []
    (root / "neutral.py").write_text("# pagination but modified after indexing\n")
    changed = search.search("pagination", root, project)
    assert changed.hits == []
    assert changed.files_skipped == 1
    bounded = search.search("latency", root, project, max_bytes=0)
    assert bounded.files_searched == 0
    assert bounded.files_skipped == 2
