from __future__ import annotations

import shutil
from pathlib import Path

from rlmgraph.models import Assertion, ClaimValidity, Evidence, GraphRelation, InvestigationResult
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import GraphGroundedSupervisor

FIXTURE = Path(__file__).parents[1] / "examples" / "onboarding_fixture"


class FixtureDebugInvestigator:
    def __init__(self) -> None:
        self.calls = 0
        self.file_reads = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        implementation = (project_root / "pkg" / "pricing.py").read_text()
        test_source = (project_root / "tests" / "test_pricing.py").read_text()
        self.file_reads += 2
        divisor = "100" if "percent / 100" in implementation else "10"
        expected = "91" if "== 91" in test_source else "90"
        return InvestigationResult(
            conclusion=(
                f"The discounted price test uses stale expectation {expected}; "
                f"the implementation interprets percent using divisor {divisor}."
            ),
            confidence=0.98,
            evidence=[
                Evidence(
                    path="pkg/pricing.py",
                    line=6,
                    detail=f"discounted divides percent by {divisor}",
                ),
                Evidence(
                    path="tests/test_pricing.py",
                    line=5,
                    detail=f"test expects {expected}",
                ),
            ],
            files_examined=["pkg/pricing.py", "tests/test_pricing.py"],
            assertions=[Assertion(key="pricing.percent_divisor", value=divisor)],
        )


class ConflictingInvestigator:
    def __init__(self) -> None:
        self.values = iter(("100", "10"))

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"The percentage divisor is {value}.",
            confidence=0.95,
            evidence=[
                Evidence(path="pkg/pricing.py", line=6, detail=f"Divisor {value}.")
            ],
            files_examined=["pkg/pricing.py"],
            assertions=[Assertion(key="pricing.percent_divisor", value=value)],
        )


def project_copy(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    test_file = root / "tests" / "test_pricing.py"
    test_file.write_text(test_file.read_text().replace("== 90", "== 91"))
    return root


def test_related_task_reuses_indexed_discovery_without_source_reads(tmp_path: Path) -> None:
    project = project_copy(tmp_path)
    store = SQLiteGraphStore(tmp_path / "memory.db")
    investigator = FixtureDebugInvestigator()
    supervisor = GraphGroundedSupervisor(store, investigator)

    first = supervisor.run(
        "Why does the discounted price percent calculation test fail?", project
    )
    reads_after_discovery = investigator.file_reads
    second = supervisor.run(
        "Is the discounted price percent calculation failure already explained?", project
    )

    assert first.cache_hit is False
    assert first.investigation_calls == 1
    assert first.source_files_read == 4
    assert first.source_files_parsed == 4
    assert first.claim.source_files
    assert {item.path for item in first.claim.source_files} == {
        "pkg/pricing.py",
        "tests/test_pricing.py",
    }
    assert second.cache_hit is True
    assert second.reuse_type == "semantic"
    assert second.claim.id == first.claim.id
    assert second.task.reused_claim_id == first.claim.id
    assert second.investigation_calls == 0
    assert second.source_files_read == 0
    assert second.source_files_parsed == 0
    assert investigator.calls == 1
    assert investigator.file_reads == reads_after_discovery
    assert any(
        edge.source == first.task.id
        and edge.relation == GraphRelation.DISCOVERED
        and edge.target == first.claim.id
        for edge in store.edges()
    )
    assert any(
        edge.source == second.task.id
        and edge.relation == GraphRelation.REUSED
        and edge.target == first.claim.id
        for edge in store.edges()
    )


def test_supporting_source_change_forces_indexed_reinvestigation(tmp_path: Path) -> None:
    project = project_copy(tmp_path)
    store = SQLiteGraphStore(tmp_path / "memory.db")
    investigator = FixtureDebugInvestigator()
    supervisor = GraphGroundedSupervisor(store, investigator)
    first = supervisor.run(
        "Why does the discounted price percent calculation test fail?", project
    )
    supervisor.run(
        "Is the discounted price percent calculation failure already explained?", project
    )

    implementation = project / "pkg" / "pricing.py"
    implementation.write_text(implementation.read_text().replace("percent / 100", "percent / 10"))
    changed = supervisor.run(
        "Why does the discounted price percent calculation test fail?", project
    )

    stale = store.get_claim(first.claim.id)
    assert changed.cache_hit is False
    assert changed.investigation_calls == 1
    assert changed.source_files_read == 1
    assert changed.source_files_parsed == 1
    assert investigator.calls == 2
    assert changed.claim.id != first.claim.id
    assert changed.claim.assertions[0].value == "10"
    assert stale is not None
    assert stale.validity_status == ClaimValidity.SUPERSEDED
    assert any(
        first.claim.id in scan.invalidated_claim_ids
        for scan in store.project_scans()
    )


def test_conflicting_indexed_finding_creates_resolution_task(tmp_path: Path) -> None:
    project = project_copy(tmp_path)
    store = SQLiteGraphStore(tmp_path / "memory.db")
    supervisor = GraphGroundedSupervisor(store, ConflictingInvestigator())
    first = supervisor.run("What divisor controls the discounted price percent?", project)

    conflicting = supervisor.run(
        "What divisor controls the discounted price percent?",
        project,
        force_investigation=True,
    )

    assert first.cache_hit is False
    assert conflicting.cache_hit is False
    assert conflicting.conflicts
    assert len(conflicting.resolution_tasks) == 1
    assert conflicting.task.status.value == "RECURSE"
    assert conflicting.resolution_tasks[0].conflicting_claim_ids == [
        first.claim.id,
        conflicting.claim.id,
    ]
