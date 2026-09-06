from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rlmgraph.fingerprint import indexed_project_fingerprint, task_fingerprint
from rlmgraph.models import (
    Assertion,
    Claim,
    Evidence,
    GraphRelation,
    RepairStatus,
    RepairWorkerResult,
    Task,
    TaskStatus,
)
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder, ReadOnlyViolation
from rlmgraph.provenance import capture_indexed_source_files
from rlmgraph.repair import SandboxedRepairValidator
from rlmgraph.store import SQLiteGraphStore

FIXTURE = Path(__file__).parents[1] / "examples" / "onboarding_fixture"
SLICE = ["pkg/pricing.py", "pkg/util.py", "tests/test_pricing.py"]


def diagnosed_fixture(tmp_path: Path):
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project)
    test_file = project / "tests" / "test_pricing.py"
    test_file.write_text(test_file.read_text().replace("== 90", "== 91"))
    (project / "pkg" / "unrelated.py").write_text("UNRELATED = True\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    scan = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    files = store.project_files(scan.project_id)
    state = indexed_project_fingerprint(
        project, [(item.path, item.content_hash) for item in files]
    )
    task = Task.create(
        "Why does test_discounted fail?",
        project,
        task_fingerprint("Why does test_discounted fail?", state),
        state,
    )
    task.relevant_files = SLICE
    task.status = TaskStatus.DONE
    store.save_task(task)
    diagnosis = Claim(
        fingerprint=task_fingerprint("diagnosis", state),
        project_fingerprint=state,
        subject=task.question,
        producer="FixtureSynthesizer",
        conclusion="The test expects stale value 91; the implementation correctly returns 90.",
        confidence=0.99,
        evidence=[
            Evidence(path="tests/test_pricing.py", line=5, detail="Expects 91."),
            Evidence(path="pkg/pricing.py", line=6, detail="Returns 90."),
        ],
        files_examined=["tests/test_pricing.py", "pkg/pricing.py"],
        assertions=[Assertion(key="pricing.failure", value="stale expectation")],
    )
    diagnosis.source_files = capture_indexed_source_files(diagnosis, files)
    task.output_claim_id = diagnosis.id
    store.save_task(task)
    store.save_claim(task, diagnosis)
    return project, store, task, diagnosis


class ValidRepairWorker:
    def __init__(self) -> None:
        self.calls = 0
        self.roots: list[Path] = []

    def repair(self, question: str, diagnosis: Claim, project_root: Path) -> RepairWorkerResult:
        self.calls += 1
        self.roots.append(project_root)
        target = project_root / "tests" / "test_pricing.py"
        target.write_text(target.read_text().replace("== 91", "== 90"))
        return RepairWorkerResult(
            rationale="Update the stale expectation to the computed value.",
            confidence=0.99,
            files_changed=["tests/test_pricing.py"],
        )


def test_valid_repair_is_proven_in_mirror_and_original_is_unchanged(tmp_path: Path) -> None:
    project, store, diagnosis_task, diagnosis = diagnosed_fixture(tmp_path)
    original = {
        item.relative_to(project).as_posix(): item.read_bytes()
        for item in project.rglob("*")
        if item.is_file()
    }
    worker = ValidRepairWorker()

    result = SandboxedRepairValidator(store, worker).validate(
        diagnosis.id, "tests/test_pricing.py"
    )

    assert result.validation.status == RepairStatus.VERIFIED
    assert result.validation.before.exit_code != 0
    assert "1 failed" in result.validation.before.stdout
    assert result.validation.after.exit_code == 0
    assert "1 passed" in result.validation.after.stdout
    assert result.validation.before.command[3] == "tests/test_pricing.py"
    assert result.validation.after.command == result.validation.before.command
    assert result.validation.original_unchanged is True
    assert result.worker_calls == result.model_calls == worker.calls == 1
    assert result.proposal.authorized_paths == SLICE
    assert result.proposal.supporting_claim_ids == [diagnosis.id]
    assert [item.path for item in result.proposal.changes] == ["tests/test_pricing.py"]
    assert "-    assert Calculator().discounted(100, 10) == 91" in result.proposal.changes[0].unified_diff
    assert "+    assert Calculator().discounted(100, 10) == 90" in result.proposal.changes[0].unified_diff
    assert all(not root.is_relative_to(project) for root in worker.roots)
    assert {
        item.relative_to(project).as_posix(): item.read_bytes()
        for item in project.rglob("*")
        if item.is_file()
    } == original
    persisted = store.repair_validations(result.repair_task.id)
    assert persisted == [result.validation]
    edges = store.edges()
    assert any(
        edge.source == diagnosis.id
        and edge.relation == GraphRelation.HAS_REPAIR
        and edge.target == result.repair_task.id
        for edge in edges
    )
    assert any(edge.relation == GraphRelation.PROPOSED_PATCH for edge in edges)
    assert any(edge.relation == GraphRelation.VALIDATED_BY for edge in edges)
    assert any(edge.relation == GraphRelation.VERIFIED_REPAIR for edge in edges)
    assert result.repair_task.parent_task_id == diagnosis_task.id


def test_verified_repair_replays_without_worker_or_test_execution(tmp_path: Path) -> None:
    _project, store, _task, diagnosis = diagnosed_fixture(tmp_path)
    worker = ValidRepairWorker()
    validator = SandboxedRepairValidator(store, worker)
    first = validator.validate(diagnosis.id, "tests/test_pricing.py")
    calls = worker.calls

    replay = validator.validate(diagnosis.id, "tests/test_pricing.py")

    assert first.reused is False
    assert replay.reused is True
    assert replay.worker_calls == replay.model_calls == 0
    assert replay.proposal.id == first.proposal.id
    assert replay.validation.id == first.validation.id
    assert worker.calls == calls
    assert replay.repair_task.reuse_type == "verified-repair"
    assert any(
        edge.source == replay.repair_task.id
        and edge.relation == GraphRelation.REUSED_REPAIR
        and edge.target == first.validation.id
        for edge in store.edges()
    )


class RetryRepairWorker:
    def __init__(self) -> None:
        self.calls = 0

    def repair(self, question: str, diagnosis: Claim, project_root: Path) -> RepairWorkerResult:
        self.calls += 1
        target = project_root / "tests" / "test_pricing.py"
        replacement = "== 92" if self.calls == 1 else "== 90"
        target.write_text(target.read_text().replace("== 91", replacement))
        return RepairWorkerResult(
            rationale="First guess, then corrected expectation.",
            confidence=0.95,
            files_changed=["tests/test_pricing.py"],
        )


def test_invalid_repair_is_rejected_then_retried_with_validation_evidence(
    tmp_path: Path,
) -> None:
    _project, store, _task, diagnosis = diagnosed_fixture(tmp_path)
    worker = RetryRepairWorker()

    result = SandboxedRepairValidator(store, worker, max_attempts=2).validate(
        diagnosis.id, "tests/test_pricing.py"
    )

    assert [item.status for item in result.attempts] == [
        RepairStatus.REJECTED,
        RepairStatus.VERIFIED,
    ]
    assert result.attempts[0].after.exit_code != 0
    assert "affected test still exits" in result.attempts[0].failure_reason
    assert result.attempts[1].after.exit_code == 0
    assert len(result.retry_tasks) == 1
    assert result.retry_tasks[0].parent_task_id == store.repair_proposals()[0].repair_task_id
    assert result.worker_calls == result.model_calls == worker.calls == 2


class OutsideSliceRepairWorker:
    def repair(self, question: str, diagnosis: Claim, project_root: Path) -> RepairWorkerResult:
        target = project_root / "pkg" / "new_file.py"
        target.write_text("OUTSIDE = True\n")
        return RepairWorkerResult(
            rationale="Unauthorized expansion.",
            confidence=0.9,
            files_changed=["pkg/new_file.py"],
        )


def test_repair_rejects_writes_outside_the_authorized_slice(tmp_path: Path) -> None:
    project, store, _task, diagnosis = diagnosed_fixture(tmp_path)
    original = (project / "tests" / "test_pricing.py").read_text()

    with pytest.raises(ReadOnlyViolation, match="outside its authorized slice"):
        SandboxedRepairValidator(store, OutsideSliceRepairWorker()).validate(
            diagnosis.id, "tests/test_pricing.py"
        )

    assert (project / "tests" / "test_pricing.py").read_text() == original
