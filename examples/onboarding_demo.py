"""Reproducible read-only onboarding and incremental-refresh proof."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from rlmgraph.fingerprint import project_fingerprint, task_fingerprint
from rlmgraph.models import Claim, Evidence, InvestigationResult, Task
from rlmgraph.onboarding import (
    ProjectSelection,
    ReadOnlyProjectOnboarder,
    ReadOnlyViolation,
    ReadOnlyWorkerBoundary,
)
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore


class WriteAttempt:
    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        try:
            (project_root / "pkg" / "util.py").write_text("corrupted")
        except OSError:
            pass
        return InvestigationResult(
            conclusion="A write was attempted inside the disposable mirror.",
            confidence=0,
            files_changed=["pkg/util.py"],
        )


def reset_neo4j_project(store: Neo4jGraphStore, root: Path) -> None:
    projects = [project for project in store.projects() if project.root == str(root.resolve())]
    if not projects:
        return
    project_ids = [project.id for project in projects]
    fixture_claims = [
        claim
        for claim in store.claims()
        if claim.project_root and Path(claim.project_root).resolve() == root.resolve()
    ]
    fixture_ids = {
        item
        for claim in fixture_claims
        for item in (claim.id, claim.source_task_id)
        if item
    }
    if fixture_ids:
        store.driver.execute_query(
            "MATCH (n) WHERE n.id IN $ids DETACH DELETE n",
            ids=sorted(fixture_ids),
        )
    store.driver.execute_query(
        "MATCH (n) WHERE n.project_id IN $project_ids DETACH DELETE n",
        project_ids=project_ids,
    )
    store.driver.execute_query(
        "MATCH (p:Project) WHERE p.id IN $project_ids DETACH DELETE p",
        project_ids=project_ids,
    )


def run(store, project: Path) -> dict[str, object]:
    selection = ProjectSelection.explicit(project)
    onboarder = ReadOnlyProjectOnboarder(store)
    first = onboarder.scan(selection)
    second = onboarder.scan(selection)

    state = project_fingerprint(project)
    task = Task.create("What bounds clamp output?", project, task_fingerprint("clamp", state), state)
    store.save_task(task)
    claim = Claim(
        fingerprint=task.fingerprint,
        subject=task.question,
        producer="OnboardingFixture",
        conclusion="clamp has only a lower bound",
        confidence=0.95,
        evidence=[Evidence(path="pkg/util.py", line=2, detail="Returns max(0, value).")],
        files_examined=["pkg/util.py"],
    )
    store.save_claim(task, claim)

    (project / "pkg" / "util.py").write_text(
        "def clamp(value: float) -> float:\n    return min(100, max(0, value))\n"
    )
    (project / "pkg" / "pricing.py").rename(project / "pkg" / "discounts.py")
    (project / "tests" / "test_pricing.py").unlink()
    (project / "tests" / "test_discounts.py").write_text(
        "from pkg.discounts import Calculator\n\n"
        "def test_discounted() -> None:\n"
        "    assert Calculator().discounted(100, 10) == 90\n"
    )
    third = onboarder.scan(selection)

    original_hash = project_fingerprint(project)
    worker_rejected = False
    try:
        ReadOnlyWorkerBoundary(selection).investigate(WriteAttempt(), "Attempt a write")
    except ReadOnlyViolation:
        worker_rejected = True
    assert worker_rejected and project_fingerprint(project) == original_hash
    change_kinds = sorted({change.kind.value for change in third.changes})
    assert first.parsed_file_count == first.file_count
    assert second.parsed_file_count == 0 and second.model_calls == 0
    assert set(change_kinds) >= {"ADDED", "DELETED", "MODIFIED", "RENAMED", "UNCHANGED"}
    assert third.invalidated_claim_ids == [claim.id]
    return {
        "project_id": third.project_id,
        "explicit_root": third.root,
        "read_only_verified": all(scan.read_only_verified for scan in (first, second, third)),
        "initial": {
            "files": first.file_count,
            "symbols": first.symbol_count,
            "tests": first.test_count,
            "dependencies": first.dependency_count,
            "parsed": first.parsed_file_count,
        },
        "unchanged": {
            "parsed": second.parsed_file_count,
            "reused": len(second.reused_file_ids),
            "model_calls": second.model_calls,
        },
        "incremental": {
            "change_kinds": change_kinds,
            "parsed": third.parsed_file_count,
            "reused": len(third.reused_file_ids),
            "invalidated_claim_ids": third.invalidated_claim_ids,
        },
        "worker_write_rejected": worker_rejected,
        "original_project_unchanged_by_worker": project_fingerprint(project) == original_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j", action="store_true")
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).parent / "onboarding_fixture"
    if args.neo4j or args.observer:
        project = Path(__file__).parents[1] / ".rlmgraph" / "onboarding-demo"
        generated_root = (Path(__file__).parents[1] / ".rlmgraph").resolve()
        if project.resolve().parent != generated_root or project.name != "onboarding-demo":
            raise RuntimeError(f"Refusing to replace unexpected path: {project}")
        if project.exists():
            shutil.rmtree(project)
        shutil.copytree(source, project)
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        store.initialize()
        reset_neo4j_project(store, project)
        result = run(store, project)
    else:
        with TemporaryDirectory(prefix="rlmgraph-onboarding-") as directory:
            workspace = Path(directory)
            project = workspace / "selected-project"
            shutil.copytree(source, project)
            result = run(SQLiteGraphStore(workspace / "graph.db"), project)
            gc.collect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
