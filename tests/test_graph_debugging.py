from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rlmgraph.graph_debugging import GraphDirectedDebugger, ProjectNotOnboardedError
from rlmgraph.models import Assertion, Evidence, GraphRelation, InvestigationResult
from rlmgraph.onboarding import (
    BoundedReadOnlyWorkerBoundary,
    ProjectSelection,
    ReadOnlyProjectOnboarder,
    ReadOnlyViolation,
)
from rlmgraph.store import SQLiteGraphStore

FIXTURE = Path(__file__).parents[1] / "examples" / "onboarding_fixture"


def fixture(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project)
    test_file = project / "tests" / "test_pricing.py"
    test_file.write_text(test_file.read_text().replace("== 90", "== 91"))
    (project / "pkg" / "unrelated.py").write_text("SECRET = 'never inspect me'\n")
    return project


class SliceWorker:
    def __init__(self) -> None:
        self.calls = 0
        self.supplied: list[list[str]] = []

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        supplied = sorted(
            item.relative_to(project_root).as_posix()
            for item in project_root.rglob("*")
            if item.is_file()
        )
        self.supplied.append(supplied)
        assert len(supplied) == 1
        path = supplied[0]
        content = (project_root / path).read_text()
        if path == "tests/test_pricing.py":
            assert "== 91" in content
            conclusion = "The test expects 91."
            assertion = Assertion(key="pricing.test_expected", value="91")
        elif path == "pkg/pricing.py":
            assert "percent / 100" in content
            conclusion = "Ten percent of 100 produces 90."
            assertion = Assertion(key="pricing.actual_result", value="90")
        else:
            assert path == "pkg/util.py" and "max(0, value)" in content
            conclusion = "Clamp does not alter the positive result."
            assertion = Assertion(key="pricing.clamp_effect", value="none")
        return InvestigationResult(
            conclusion=conclusion,
            confidence=0.96,
            evidence=[Evidence(path=path, line=1, detail=conclusion)],
            files_examined=[path],
            assertions=[assertion],
        )


class DiagnosisSynthesizer:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, question: str, findings) -> InvestigationResult:
        self.calls += 1
        values = {item.assertions[0].key: item.assertions[0].value for item in findings}
        assert values["pricing.test_expected"] == "91"
        assert values["pricing.actual_result"] == "90"
        return InvestigationResult(
            conclusion="The test fails because its expected value 91 is stale; the code returns 90.",
            confidence=0.99,
            evidence=[
                Evidence(path="tests/test_pricing.py", line=5, detail="Expects 91."),
                Evidence(path="pkg/pricing.py", line=6, detail="Computes 90."),
            ],
            files_examined=["tests/test_pricing.py", "pkg/pricing.py"],
            assertions=[Assertion(key="pricing.failure_cause", value="stale expectation")],
        )


def test_debugger_requires_an_existing_project_index(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    debugger = GraphDirectedDebugger(
        SQLiteGraphStore(tmp_path / "graph.db"), SliceWorker(), DiagnosisSynthesizer()
    )

    with pytest.raises(ProjectNotOnboardedError, match="run onboarding first"):
        debugger.debug("Why is the test failing?", project, "tests/test_pricing.py")


def test_debugger_enforces_dependency_and_wall_time_limits(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))

    file_bounded = GraphDirectedDebugger(
        store,
        SliceWorker(),
        DiagnosisSynthesizer(),
        max_dependency_files=2,
    )
    with pytest.raises(ReadOnlyViolation, match="file limit"):
        file_bounded.debug(
            "Why does test_discounted fail?",
            project,
            "tests/test_pricing.py",
            refresh_index=False,
        )

    time_bounded = GraphDirectedDebugger(
        store,
        SliceWorker(),
        DiagnosisSynthesizer(),
        max_wall_time_seconds=0,
    )
    with pytest.raises(ReadOnlyViolation, match="wall-time"):
        time_bounded.debug(
            "Why does test_discounted fail?",
            project,
            "tests/test_pricing.py",
            refresh_index=False,
        )


def test_graph_directed_debugging_traces_bounds_and_synthesizes(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    worker = SliceWorker()
    synthesizer = DiagnosisSynthesizer()
    debugger = GraphDirectedDebugger(store, worker, synthesizer)

    result = debugger.debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )

    expected_slice = ["pkg/pricing.py", "pkg/util.py", "tests/test_pricing.py"]
    assert result.root_task.status.value == "DONE"
    assert result.diagnosis.conclusion.endswith("the code returns 90.")
    assert result.dependency_slice.paths == expected_slice
    assert result.dependency_slice.excluded_paths == [
        "pkg/__init__.py",
        "pkg/unrelated.py",
    ]
    assert result.project_scan.content_read_file_count == 0
    assert result.project_scan.parsed_file_count == 0
    assert result.worker_calls == 3
    assert result.reused_subtasks == 0
    assert result.analyzed_files == expected_slice
    assert result.supplied_files == expected_slice
    assert worker.supplied == [[path] for path in expected_slice]
    assert synthesizer.calls == 1
    assert "pkg/unrelated.py" not in result.analyzed_files
    assert all(task.relevant_files == supplied for task, supplied in zip(result.sub_tasks, worker.supplied))
    edges = store.edges()
    assert sum(edge.relation == GraphRelation.SPAWNED for edge in edges) == 3
    assert sum(edge.relation == GraphRelation.AUTHORIZED_FILE for edge in edges) == 3
    assert sum(edge.relation == GraphRelation.TRACED_DEPENDENCY for edge in edges) == 2
    assert sum(edge.relation == GraphRelation.SYNTHESIZED_FROM for edge in edges) == 3


def test_equivalent_debug_run_reuses_every_bounded_subtask(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    worker = SliceWorker()
    debugger = GraphDirectedDebugger(store, worker, DiagnosisSynthesizer())
    first = debugger.debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )
    calls_after_first = worker.calls

    second = debugger.debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )

    assert first.reused_subtasks == 0
    assert second.reused_subtasks == 3
    assert second.worker_calls == 0
    assert second.project_scan.content_read_file_count == 0
    assert second.project_scan.parsed_file_count == 0
    assert worker.calls == calls_after_first
    assert all(task.reused_claim_id for task in second.sub_tasks)
    assert all(task.reuse_type == "dependency-slice" for task in second.sub_tasks)


def test_identical_content_never_reuses_across_project_roots(tmp_path: Path) -> None:
    first_project = fixture(tmp_path / "first")
    second_project = fixture(tmp_path / "second")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    onboarder = ReadOnlyProjectOnboarder(store)
    onboarder.scan(ProjectSelection.explicit(first_project))
    onboarder.scan(ProjectSelection.explicit(second_project))
    worker = SliceWorker()
    debugger = GraphDirectedDebugger(store, worker, DiagnosisSynthesizer())
    debugger.debug(
        "Why does test_discounted fail?", first_project, "tests/test_pricing.py"
    )

    second = debugger.debug(
        "Why does test_discounted fail?", second_project, "tests/test_pricing.py"
    )

    assert second.reused_subtasks == 0
    assert second.worker_calls == 3
    assert worker.calls == 6


class GapWorker(SliceWorker):
    def __init__(self) -> None:
        super().__init__()
        self.util_calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        supplied = [item for item in project_root.rglob("*") if item.is_file()]
        if supplied[0].relative_to(project_root).as_posix() != "pkg/util.py":
            return super().investigate(question, project_root)
        self.calls += 1
        self.util_calls += 1
        self.supplied.append(["pkg/util.py"])
        unresolved = ["Confirm whether clamp changes positive values."] if self.util_calls == 1 else []
        return InvestigationResult(
            conclusion="Clamp appears to preserve positive values.",
            confidence=0.7 if unresolved else 0.96,
            evidence=[Evidence(path="pkg/util.py", line=2, detail="Uses max(0, value).")],
            files_examined=["pkg/util.py"],
            unresolved_questions=unresolved,
            assertions=[Assertion(key="pricing.clamp_effect", value="none")],
        )


def test_evidence_gap_creates_another_bounded_subtask(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    worker = GapWorker()

    result = GraphDirectedDebugger(store, worker, DiagnosisSynthesizer()).debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )

    gaps = [task for task in result.sub_tasks if task.question.startswith("Resolve evidence gap")]
    assert len(gaps) == 1
    assert gaps[0].relevant_files == ["pkg/util.py"]
    assert gaps[0].depth == 2
    assert worker.util_calls == 2
    assert result.root_task.status.value == "DONE"


class ConflictWorker:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        paths = sorted(
            item.relative_to(project_root).as_posix()
            for item in project_root.rglob("*")
            if item.is_file()
        )
        if len(paths) == 2:
            return InvestigationResult(
                conclusion="Direct calculation resolves the disagreement in favor of 90.",
                confidence=0.99,
                evidence=[
                    Evidence(path="pkg/pricing.py", line=6, detail="Returns 90."),
                    Evidence(path="tests/test_pricing.py", line=5, detail="Expects 91."),
                ],
                files_examined=paths,
                assertions=[Assertion(key="pricing.observed_result", value="90")],
            )
        path = paths[0]
        value = "91" if path == "tests/test_pricing.py" else "90"
        key = "pricing.observed_result" if path != "pkg/util.py" else "pricing.clamp"
        return InvestigationResult(
            conclusion=f"{path} indicates {value}.",
            confidence=0.95,
            evidence=[Evidence(path=path, line=1, detail=f"Indicates {value}.")],
            files_examined=[path],
            assertions=[Assertion(key=key, value=value)],
        )


class ConflictSynthesizer:
    def synthesize(self, question: str, findings) -> InvestigationResult:
        assert any("resolves the disagreement" in item.conclusion for item in findings)
        return InvestigationResult(
            conclusion="The bounded resolution confirms a stale expected value.",
            confidence=0.99,
            evidence=[Evidence(path="pkg/pricing.py", line=6, detail="Returns 90.")],
            files_examined=["pkg/pricing.py"],
        )


def test_disagreement_creates_a_bounded_resolution_subtask(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    worker = ConflictWorker()

    result = GraphDirectedDebugger(store, worker, ConflictSynthesizer()).debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )

    resolution = [task for task in result.sub_tasks if task.conflicting_claim_ids]
    assert len(resolution) == 1
    assert resolution[0].relevant_files == ["pkg/pricing.py", "tests/test_pricing.py"]
    assert len(resolution[0].conflicting_claim_ids) == 2
    assert worker.calls == 4
    assert result.root_task.status.value == "DONE"
    assert any(edge.relation == GraphRelation.CONTRADICTS for edge in store.edges())


class OutOfSliceWorker:
    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        assert not (project_root / "pkg" / "unrelated.py").exists()
        return InvestigationResult(
            conclusion="I claim I inspected an unauthorized file.",
            confidence=0.5,
            files_examined=["pkg/unrelated.py"],
        )


class WriteWorker:
    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        target = project_root / "pkg" / "pricing.py"
        target.chmod(0o666)
        target.write_text("corrupted\n")
        return InvestigationResult(conclusion="changed", confidence=0.1)


def test_bounded_boundary_rejects_out_of_slice_reports_and_writes(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    selection = ProjectSelection.explicit(project)
    boundary = BoundedReadOnlyWorkerBoundary(selection, ["pkg/pricing.py"])
    original = (project / "pkg" / "pricing.py").read_text()

    with pytest.raises(ReadOnlyViolation, match="outside its authorized slice"):
        boundary.investigate(OutOfSliceWorker(), "Inspect")
    with pytest.raises(ReadOnlyViolation, match="attempted to change its slice"):
        boundary.investigate(WriteWorker(), "Write")

    assert (project / "pkg" / "pricing.py").read_text() == original
