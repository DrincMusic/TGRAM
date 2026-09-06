"""Deterministic discovery -> graph memory -> related-task reuse proof."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from rlmgraph.models import Assertion, Evidence, InvestigationResult
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.supervisor import GraphGroundedSupervisor


class FixtureInvestigator:
    def __init__(self) -> None:
        self.calls = 0
        self.source_reads = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        implementation = (project_root / "pkg" / "pricing.py").read_text()
        test_source = (project_root / "tests" / "test_pricing.py").read_text()
        self.source_reads += 2
        divisor = "100" if "percent / 100" in implementation else "10"
        expected = "91" if "== 91" in test_source else "90"
        return InvestigationResult(
            conclusion=(
                f"The test expectation {expected} disagrees with percentage divisor {divisor}."
            ),
            confidence=0.98,
            evidence=[
                Evidence(
                    path="pkg/pricing.py",
                    line=6,
                    detail=f"Percentage divisor is {divisor}.",
                ),
                Evidence(
                    path="tests/test_pricing.py",
                    line=5,
                    detail=f"Expected value is {expected}.",
                ),
            ],
            files_examined=["pkg/pricing.py", "tests/test_pricing.py"],
            assertions=[Assertion(key="pricing.percent_divisor", value=divisor)],
        )


def clear_observer_fixture(store: Neo4jGraphStore, root: Path) -> None:
    project_ids = [
        item.id for item in store.projects() if Path(item.root).resolve() == root.resolve()
    ]
    claim_ids = [
        item.id
        for item in store.claims()
        if item.project_root and Path(item.project_root).resolve() == root.resolve()
    ]
    task_ids = [
        item.id for item in store.tasks() if Path(item.project_root).resolve() == root.resolve()
    ]
    ids = [*project_ids, *claim_ids, *task_ids]
    if ids or project_ids:
        store.driver.execute_query(
            "MATCH (n) WHERE n.id IN $ids OR n.project_id IN $project_ids DETACH DELETE n",
            ids=ids,
            project_ids=project_ids,
        )


def execute(store, project: Path) -> dict[str, object]:
    investigator = FixtureInvestigator()
    supervisor = GraphGroundedSupervisor(store, investigator)
    first = supervisor.run(
        "Why does the discounted price percent calculation test fail?", project
    )
    reads_after_first = investigator.source_reads
    second = supervisor.run(
        "Is the discounted price percent calculation failure already explained?", project
    )
    assert not first.cache_hit and first.investigation_calls == 1
    assert second.cache_hit and second.claim.id == first.claim.id
    assert second.investigation_calls == 0
    assert second.source_files_read == 0 and second.source_files_parsed == 0
    assert investigator.calls == 1 and investigator.source_reads == reads_after_first
    worker_reads_avoided = investigator.source_reads == reads_after_first
    implementation = project / "pkg" / "pricing.py"
    implementation.write_text(
        implementation.read_text().replace("percent / 100", "percent / 10")
    )
    third = supervisor.run(
        "Why does the discounted price percent calculation test fail?", project
    )
    invalidating_scan = next(
        scan
        for scan in store.project_scans()
        if first.claim.id in scan.invalidated_claim_ids
    )
    assert not third.cache_hit and third.investigation_calls == 1
    assert third.claim.id != first.claim.id
    assert first.claim.id in invalidating_scan.invalidated_claim_ids
    return {
        "discovery": {
            "task_id": first.task.id,
            "claim_id": first.claim.id,
            "confidence": first.claim.confidence,
            "source_files": [item.model_dump(mode="json") for item in first.claim.source_files],
            "investigation_calls": first.investigation_calls,
        },
        "related_task": {
            "task_id": second.task.id,
            "reused_claim_id": second.task.reused_claim_id,
            "reuse_type": second.reuse_type,
            "reuse_reason": second.reuse_reason,
            "source_files_read": second.source_files_read,
            "source_files_parsed": second.source_files_parsed,
            "investigation_calls": second.investigation_calls,
        },
        "proof": {
            "same_claim": second.claim.id == first.claim.id,
            "worker_source_reads_avoided": worker_reads_avoided,
            "model_calls_avoided": second.investigation_calls == 0,
        },
        "changed_source": {
            "task_id": third.task.id,
            "replacement_claim_id": third.claim.id,
            "invalidated_claim_ids": invalidating_scan.invalidated_claim_ids,
            "source_files_read": third.source_files_read,
            "source_files_parsed": third.source_files_parsed,
            "investigation_calls": third.investigation_calls,
            "forced_reinvestigation": not third.cache_hit,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).parent / "onboarding_fixture"
    if args.observer:
        generated = (Path(__file__).parents[1] / ".rlmgraph").resolve()
        project = generated / "investigation-reuse-demo"
        if project.parent != generated or project.name != "investigation-reuse-demo":
            raise RuntimeError(f"Refusing to replace unexpected path: {project}")
        if project.exists():
            shutil.rmtree(project)
        shutil.copytree(source, project)
        test_file = project / "tests" / "test_pricing.py"
        test_file.write_text(test_file.read_text().replace("== 90", "== 91"))
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        store.initialize()
        clear_observer_fixture(store, project)
        result = execute(store, project)
    else:
        with TemporaryDirectory(prefix="rlmgraph-reuse-") as directory:
            workspace = Path(directory)
            project = workspace / "fixture"
            shutil.copytree(source, project)
            test_file = project / "tests" / "test_pricing.py"
            test_file.write_text(test_file.read_text().replace("== 90", "== 91"))
            result = execute(SQLiteGraphStore(workspace / "memory.db"), project)
            gc.collect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
