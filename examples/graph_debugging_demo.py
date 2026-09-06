"""Deterministic indexed test -> bounded subtasks -> final diagnosis proof."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from rlmgraph.graph_debugging import GraphDirectedDebugger
from rlmgraph.models import Assertion, Evidence, InvestigationResult
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore


class BoundedFixtureWorker:
    def __init__(self) -> None:
        self.calls = 0
        self.supplied: list[list[str]] = []

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        paths = sorted(
            item.relative_to(project_root).as_posix()
            for item in project_root.rglob("*")
            if item.is_file()
        )
        self.supplied.append(paths)
        if len(paths) != 1:
            raise RuntimeError(f"Worker received an unbounded slice: {paths}")
        path = paths[0]
        content = (project_root / path).read_text()
        if path == "tests/test_pricing.py":
            assert "== 91" in content
            conclusion, key, value = "The test expects 91.", "pricing.test_expected", "91"
        elif path == "pkg/pricing.py":
            assert "percent / 100" in content
            conclusion, key, value = "The implementation returns 90.", "pricing.actual", "90"
        else:
            assert path == "pkg/util.py" and "max(0, value)" in content
            conclusion, key, value = "Clamp preserves positive 90.", "pricing.clamp", "90"
        return InvestigationResult(
            conclusion=conclusion,
            confidence=0.97,
            evidence=[Evidence(path=path, line=1, detail=conclusion)],
            files_examined=[path],
            assertions=[Assertion(key=key, value=value)],
        )


class FixtureSynthesizer:
    def synthesize(self, question: str, findings) -> InvestigationResult:
        assert any(item.conclusion == "The test expects 91." for item in findings)
        assert any(item.conclusion == "The implementation returns 90." for item in findings)
        return InvestigationResult(
            conclusion="The failing test has a stale expectation: it expects 91 but the code returns 90.",
            confidence=0.99,
            evidence=[
                Evidence(path="tests/test_pricing.py", line=5, detail="Expected value is 91."),
                Evidence(path="pkg/pricing.py", line=6, detail="Percentage calculation returns 90."),
            ],
            files_examined=["tests/test_pricing.py", "pkg/pricing.py"],
            assertions=[Assertion(key="pricing.failure", value="stale test expectation")],
        )


def prepare(source: Path, project: Path) -> None:
    shutil.copytree(source, project)
    test_file = project / "tests" / "test_pricing.py"
    test_file.write_text(test_file.read_text().replace("== 90", "== 91"))
    (project / "pkg" / "unrelated.py").write_text("SECRET = 'not in dependency slice'\n")


def clear_observer_fixture(store: Neo4jGraphStore, root: Path) -> None:
    project_ids = [
        item.id for item in store.projects() if Path(item.root).resolve() == root.resolve()
    ]
    task_ids = [
        item.id for item in store.tasks() if Path(item.project_root).resolve() == root.resolve()
    ]
    claim_ids = [
        item.id
        for item in store.claims()
        if item.project_root and Path(item.project_root).resolve() == root.resolve()
    ]
    ids = [*project_ids, *task_ids, *claim_ids]
    if ids or project_ids:
        store.driver.execute_query(
            "MATCH (n) WHERE n.id IN $ids OR n.project_id IN $project_ids DETACH DELETE n",
            ids=ids,
            project_ids=project_ids,
        )


def execute(store, project: Path) -> dict[str, object]:
    initial = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    worker = BoundedFixtureWorker()
    debugger = GraphDirectedDebugger(store, worker, FixtureSynthesizer())
    first = debugger.debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )
    calls_after_first = worker.calls
    replay = debugger.debug(
        "Why does test_discounted fail?", project, "tests/test_pricing.py"
    )
    expected = ["pkg/pricing.py", "pkg/util.py", "tests/test_pricing.py"]
    assert first.dependency_slice.paths == expected
    assert first.project_scan.content_read_file_count == 0
    assert first.project_scan.parsed_file_count == 0
    assert first.analyzed_files == expected
    assert "pkg/unrelated.py" in first.dependency_slice.excluded_paths
    assert all(len(paths) == 1 for paths in worker.supplied)
    assert replay.reused_subtasks == 3 and replay.worker_calls == 0
    assert worker.calls == calls_after_first
    return {
        "initial_index": {
            "files": initial.file_count,
            "parsed": initial.parsed_file_count,
        },
        "dependency_trace": first.dependency_slice.model_dump(mode="json"),
        "bounded_investigation": {
            "root_task_id": first.root_task.id,
            "subtask_ids": [item.id for item in first.sub_tasks],
            "supplied_per_worker": worker.supplied,
            "analyzed_files": first.analyzed_files,
            "worker_calls": first.worker_calls,
            "scan_source_reads": first.project_scan.content_read_file_count,
            "scan_parses": first.project_scan.parsed_file_count,
        },
        "diagnosis": {
            "claim_id": first.diagnosis.id,
            "conclusion": first.diagnosis.conclusion,
            "confidence": first.diagnosis.confidence,
            "source_claim_ids": first.diagnosis.source_claim_ids,
        },
        "replay": {
            "reused_subtasks": replay.reused_subtasks,
            "worker_calls": replay.worker_calls,
            "scan_source_reads": replay.project_scan.content_read_file_count,
            "scan_parses": replay.project_scan.parsed_file_count,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).parent / "onboarding_fixture"
    if args.observer:
        generated = (Path(__file__).parents[1] / ".rlmgraph").resolve()
        project = generated / "graph-debugging-demo"
        if project.parent != generated or project.name != "graph-debugging-demo":
            raise RuntimeError(f"Refusing to replace unexpected path: {project}")
        if project.exists():
            shutil.rmtree(project)
        prepare(source, project)
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        store.initialize()
        clear_observer_fixture(store, project)
        result = execute(store, project)
    else:
        with TemporaryDirectory(prefix="rlmgraph-debug-") as directory:
            workspace = Path(directory)
            project = workspace / "project"
            prepare(source, project)
            result = execute(SQLiteGraphStore(workspace / "graph.db"), project)
            gc.collect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
