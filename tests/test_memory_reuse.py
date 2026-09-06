from pathlib import Path

from rlmgraph.models import Evidence, InvestigationResult
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class CountingInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The fixture fails because its expected value is stale.",
            evidence=[Evidence(path="tests/test_widget.py", line=12, detail="Expected 3, got 4")],
            confidence=0.93,
            files_examined=["tests/test_widget.py", "src/widget.py"],
        )


def test_second_task_reuses_first_discovery(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("VALUE = 4\n")
    investigator = CountingInvestigator()
    store = SQLiteGraphStore(tmp_path / "graph.db")
    supervisor = Supervisor(store, investigator)

    first = supervisor.run("Why is this test failing?", project)
    second = supervisor.run("Why is this test failing?", project)

    assert first.cache_hit is False
    assert first.investigation_calls == 1
    assert second.cache_hit is True
    assert second.reuse_type == "exact"
    assert second.relevance_score == 1.0
    assert second.reuse_reason == "Exact normalized question and unchanged project state."
    assert second.investigation_calls == 0
    assert second.task.reused_claim_id == first.claim.id
    assert second.reconstruction is not None
    assert second.task.reconstruction_id == second.reconstruction.id
    assert second.reconstruction.seed_node_ids == [first.claim.id]
    assert store.get_reconstruction(second.reconstruction.id) is not None
    assert investigator.calls == 1


def test_differently_worded_task_reuses_relevant_claim(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("VALUE = 4\n")
    investigator = CountingInvestigator()
    supervisor = Supervisor(SQLiteGraphStore(tmp_path / "graph.db"), investigator)

    first = supervisor.run("Why does the widget test expect the wrong value?", project)
    second = supervisor.run("Is the widget test expected value stale?", project)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.reuse_type == "semantic"
    assert second.investigation_calls == 0
    assert second.task.reused_claim_id == first.claim.id
    assert second.relevance_score is not None and second.relevance_score >= 0.6
    assert second.reuse_reason is not None
    assert "Unchanged project state" in second.reuse_reason
    assert "matched concepts" in second.reuse_reason
    assert investigator.calls == 1
    persisted_task = SQLiteGraphStore(tmp_path / "graph.db").tasks()[-1]
    assert persisted_task.reuse_type == "semantic"
    assert persisted_task.relevance_score == second.relevance_score
    assert persisted_task.reuse_reason == second.reuse_reason


def test_unrelated_task_does_not_reuse_claim(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("VALUE = 4\n")
    investigator = CountingInvestigator()
    supervisor = Supervisor(SQLiteGraphStore(tmp_path / "graph.db"), investigator)
    supervisor.run("Why does the widget test expect the wrong value?", project)

    result = supervisor.run("How is widget data serialized to JSON?", project)

    assert result.cache_hit is False
    assert result.reuse_type is None
    assert result.investigation_calls == 1
    assert investigator.calls == 2


def test_project_change_invalidates_discovery(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "widget.py"
    source.write_text("VALUE = 4\n")
    investigator = CountingInvestigator()
    supervisor = Supervisor(SQLiteGraphStore(tmp_path / "graph.db"), investigator)
    supervisor.run("Why is this test failing?", project)

    source.write_text("VALUE = 4000\n")
    result = supervisor.run("Why is this test failing?", project)

    assert result.cache_hit is False
    assert investigator.calls == 2


def test_memory_database_does_not_invalidate_its_own_discovery(tmp_path: Path) -> None:
    investigator = CountingInvestigator()
    supervisor = Supervisor(SQLiteGraphStore(tmp_path / ".rlmgraph.db"), investigator)

    supervisor.run("Why is this test failing?", tmp_path)
    result = supervisor.run("Why is this test failing?", tmp_path)

    assert result.cache_hit is True
    assert investigator.calls == 1
