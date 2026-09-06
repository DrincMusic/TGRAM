from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Protocol

from .fingerprint import file_content_hash, task_fingerprint
from .models import (
    Claim,
    GraphEdge,
    GraphRelation,
    PatchChange,
    RepairProposal,
    RepairRunResult,
    RepairStatus,
    RepairValidation,
    RepairWorkerResult,
    StoppingReason,
    Task,
    TaskKind,
    TaskStatus,
    TestExecution,
)
from .onboarding import IGNORED_DIRECTORIES, ProjectSelection, ReadOnlyViolation
from .store import GraphStore


class RepairWorker(Protocol):
    def repair(
        self, question: str, diagnosis: Claim, project_root: Path
    ) -> RepairWorkerResult: ...


def _tree_fingerprint(root: Path) -> str:
    records: list[tuple[str, str]] = []
    resolved_root = root.resolve()
    for directory, names, filenames in os.walk(resolved_root, followlinks=False):
        names[:] = sorted(name for name in names if name not in IGNORED_DIRECTORIES)
        for name in sorted(filenames):
            candidate = (Path(directory) / name).resolve()
            try:
                relative = candidate.relative_to(resolved_root)
            except ValueError:
                continue
            if candidate.is_file():
                records.append((relative.as_posix(), file_content_hash(candidate)))
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()


def _mirror_manifest(root: Path) -> dict[str, str]:
    return {
        item.relative_to(root).as_posix(): file_content_hash(item)
        for item in root.rglob("*")
        if item.is_file()
    }


class SandboxedRepairValidator:
    """Propose and validate repairs in disposable, dependency-bounded mirrors."""

    def __init__(
        self,
        store: GraphStore,
        worker: RepairWorker,
        *,
        minimum_confidence: float = 0.75,
        max_attempts: int = 2,
        test_timeout_seconds: float = 30,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("Repair validation requires at least one attempt.")
        self.store = store
        self.worker = worker
        self.minimum_confidence = minimum_confidence
        self.max_attempts = max_attempts
        self.test_timeout_seconds = test_timeout_seconds
        self.worker_calls = 0
        self.store.initialize()

    def validate(
        self,
        diagnosis_claim_id: str,
        test_path: str,
        *,
        question: str | None = None,
    ) -> RepairRunResult:
        diagnosis = self.store.get_claim(diagnosis_claim_id)
        if diagnosis is None or not diagnosis.source_task_id:
            raise ValueError(f"Completed diagnosis not found: {diagnosis_claim_id}")
        diagnosis_task = self.store.get_task(diagnosis.source_task_id)
        if diagnosis_task is None or diagnosis_task.status != TaskStatus.DONE:
            raise ValueError("Repair validation requires a completed graph-directed diagnosis.")
        selection = ProjectSelection.explicit(diagnosis_task.project_root)
        normalized_test = test_path.replace("\\", "/")
        authorized = sorted(dict.fromkeys(diagnosis_task.relevant_files))
        if normalized_test not in authorized:
            raise ReadOnlyViolation("The selected test is outside the diagnosed dependency slice.")
        self._validate_authorized_paths(selection, authorized)
        command = [
            sys.executable,
            "-m",
            "pytest",
            normalized_test,
            "-q",
            "-p",
            "no:cacheprovider",
        ]
        signature = self._signature(diagnosis, authorized, command)
        replay = self._verified_replay(signature)
        prompt = question or f"Repair the verified diagnosis: {diagnosis.conclusion}"
        if replay:
            proposal, validation = replay
            task = self._create_task(diagnosis, diagnosis_task, prompt, authorized, 1)
            task.status = TaskStatus.DONE
            task.reuse_type = "verified-repair"
            task.reuse_reason = "An identical source slice already has a verified repair."
            task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.COMPLETED
            self.store.save_task(task)
            self.store.save_edge(
                GraphEdge(
                    source=task.id,
                    relation=GraphRelation.REUSED_REPAIR,
                    target=validation.id,
                )
            )
            return RepairRunResult(
                repair_task=task,
                proposal=proposal,
                validation=validation,
                attempts=[validation],
                worker_calls=0,
                model_calls=0,
                reused=True,
            )

        original_state = _tree_fingerprint(selection.root)
        attempts: list[RepairValidation] = []
        retry_tasks: list[Task] = []
        prior_task: Task | None = None
        last_task: Task | None = None
        last_proposal: RepairProposal | None = None
        start_calls = self.worker_calls
        for attempt_number in range(1, self.max_attempts + 1):
            task = self._create_task(
                diagnosis,
                diagnosis_task,
                prompt if attempt_number == 1 else self._retry_question(attempts[-1]),
                authorized,
                attempt_number,
                parent=prior_task,
            )
            if prior_task is not None:
                retry_tasks.append(task)
            proposal, validation = self._attempt(
                task,
                diagnosis,
                selection,
                normalized_test,
                authorized,
                command,
                signature,
                attempt_number,
                original_state,
            )
            attempts.append(validation)
            last_task, last_proposal = task, proposal
            if validation.status == RepairStatus.VERIFIED:
                break
            prior_task = task
        assert last_task is not None and last_proposal is not None
        return RepairRunResult(
            repair_task=last_task,
            proposal=last_proposal,
            validation=attempts[-1],
            attempts=attempts,
            retry_tasks=retry_tasks,
            worker_calls=self.worker_calls - start_calls,
            model_calls=sum(item.model_calls for item in self._proposals_for(attempts)),
        )

    def _attempt(
        self,
        task: Task,
        diagnosis: Claim,
        selection: ProjectSelection,
        test_path: str,
        authorized: list[str],
        command: list[str],
        signature: str,
        attempt_number: int,
        original_state: str,
    ) -> tuple[RepairProposal, RepairValidation]:
        with TemporaryDirectory(prefix="rlmgraph-repair-") as directory:
            mirror = Path(directory) / "project"
            mirror.mkdir()
            original_content: dict[str, bytes] = {}
            for relative in authorized:
                source = (selection.root / relative).resolve(strict=True)
                destination = mirror / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                original_content[relative] = destination.read_bytes()
            before_test = self._execute(command, mirror)
            if before_test.exit_code == 0:
                raise ValueError("The selected test does not fail in the disposable mirror.")
            worker_baseline = _mirror_manifest(mirror)
            task.started_at = datetime.now(UTC)
            task.attempt_count = 1
            self.store.save_task(task)
            result = self.worker.repair(task.question, diagnosis, mirror)
            self.worker_calls += 1
            worker_after = _mirror_manifest(mirror)
            changed = sorted(
                path
                for path in set(worker_baseline) | set(worker_after)
                if worker_baseline.get(path) != worker_after.get(path)
            )
            outside = sorted(set(changed) - set(authorized))
            if outside:
                raise ReadOnlyViolation(
                    "Repair worker changed files outside its authorized slice: "
                    + ", ".join(outside)
                )
            reported = sorted(path.replace("\\", "/") for path in result.files_changed)
            if reported != changed:
                raise ReadOnlyViolation(
                    "Repair worker change report does not match the mirror diff: "
                    f"reported {reported}, actual {changed}"
                )
            changes = [
                self._patch_change(path, original_content[path], mirror / path)
                for path in changed
            ]
            after_test = self._execute(command, mirror)
        original_unchanged = _tree_fingerprint(selection.root) == original_state
        if not original_unchanged:
            raise ReadOnlyViolation("The original project changed during repair validation.")
        verified = (
            bool(changes)
            and after_test.exit_code == 0
            and result.confidence >= self.minimum_confidence
        )
        status = RepairStatus.VERIFIED if verified else RepairStatus.REJECTED
        failure_reason = None
        if not verified:
            reasons: list[str] = []
            if not changes:
                reasons.append("worker produced no patch")
            if after_test.exit_code != 0:
                reasons.append(f"affected test still exits {after_test.exit_code}")
            if result.confidence < self.minimum_confidence:
                reasons.append(
                    f"confidence {result.confidence:.3f} is below {self.minimum_confidence:.3f}"
                )
            failure_reason = "; ".join(reasons)
        proposal = RepairProposal(
            repair_task_id=task.id,
            diagnosis_claim_id=diagnosis.id,
            project_root=str(selection.root),
            project_fingerprint=task.project_fingerprint,
            source_tree_fingerprint=original_state,
            test_path=test_path,
            authorized_paths=authorized,
            supporting_claim_ids=[diagnosis.id, *diagnosis.source_claim_ids],
            changes=changes,
            rationale=result.rationale,
            confidence=result.confidence,
            worker=type(self.worker).__name__,
            model_calls=result.model_calls,
            signature=signature,
            status=status,
        )
        validation = RepairValidation(
            repair_task_id=task.id,
            proposal_id=proposal.id,
            attempt=attempt_number,
            status=status,
            before=before_test,
            after=after_test,
            original_unchanged=original_unchanged,
            failure_reason=failure_reason,
        )
        task.status = TaskStatus.DONE if verified else TaskStatus.STOPPED
        task.completed_at = datetime.now(UTC)
        task.stopping_reason = (
            StoppingReason.COMPLETED if verified else StoppingReason.LOW_CONFIDENCE
        )
        task.last_error = failure_reason
        self.store.save_task(task)
        self.store.save_repair_proposal(proposal)
        self.store.save_repair_validation(validation)
        return proposal, validation

    def _create_task(
        self,
        diagnosis: Claim,
        diagnosis_task: Task,
        question: str,
        authorized: list[str],
        attempt: int,
        parent: Task | None = None,
    ) -> Task:
        task = Task(
            question=question,
            fingerprint=task_fingerprint(
                f"repair:{attempt}:{question}", diagnosis_task.project_fingerprint
            ),
            project_fingerprint=diagnosis_task.project_fingerprint,
            project_root=diagnosis_task.project_root,
            kind=TaskKind.FOLLOW_UP,
            parent_task_id=parent.id if parent else diagnosis_task.id,
            source_claim_ids=[diagnosis.id, *diagnosis.source_claim_ids],
            relevant_files=authorized,
            depth=(parent.depth + 1 if parent else diagnosis_task.depth + 1),
        )
        self.store.save_task(task)
        self.store.save_edge(
            GraphEdge(
                source=(parent.id if parent else diagnosis.id),
                relation=GraphRelation.SPAWNED if parent else GraphRelation.HAS_REPAIR,
                target=task.id,
            )
        )
        return task

    def _verified_replay(
        self, signature: str
    ) -> tuple[RepairProposal, RepairValidation] | None:
        proposals = [
            proposal
            for proposal in self.store.repair_proposals()
            if proposal.signature == signature and proposal.status == RepairStatus.VERIFIED
        ]
        for proposal in reversed(proposals):
            validation = next(
                (
                    item
                    for item in reversed(self.store.repair_validations())
                    if item.proposal_id == proposal.id
                    and item.status == RepairStatus.VERIFIED
                ),
                None,
            )
            if validation:
                return proposal, validation
        return None

    def _proposals_for(self, validations: list[RepairValidation]) -> list[RepairProposal]:
        ids = {item.proposal_id for item in validations}
        return [item for item in self.store.repair_proposals() if item.id in ids]

    @staticmethod
    def _signature(diagnosis: Claim, authorized: list[str], command: list[str]) -> str:
        payload = {
            "diagnosis": diagnosis.fingerprint,
            "sources": [(item.path, item.content_hash) for item in diagnosis.source_files],
            "authorized": authorized,
            "command": command,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _validate_authorized_paths(
        selection: ProjectSelection, authorized: list[str]
    ) -> None:
        for relative in authorized:
            path = Path(relative)
            if path.is_absolute():
                raise ReadOnlyViolation(f"Absolute repair path is forbidden: {relative}")
            candidate = (selection.root / path).resolve(strict=True)
            try:
                candidate.relative_to(selection.root)
            except ValueError as exc:
                raise ReadOnlyViolation(
                    f"Repair path escapes the selected project: {relative}"
                ) from exc

    def _execute(self, command: list[str], cwd: Path) -> TestExecution:
        started = perf_counter()
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.test_timeout_seconds,
            )
            return TestExecution(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout[-20_000:],
                stderr=completed.stderr[-20_000:],
                duration_ms=(perf_counter() - started) * 1000,
            )
        except subprocess.TimeoutExpired as exc:
            return TestExecution(
                command=command,
                exit_code=124,
                stdout=(exc.stdout or "")[-20_000:],
                stderr=(exc.stderr or "")[-20_000:],
                duration_ms=(perf_counter() - started) * 1000,
            )

    @staticmethod
    def _patch_change(path: str, before_bytes: bytes, after_path: Path) -> PatchChange:
        after_bytes = after_path.read_bytes()
        before = before_bytes.decode("utf-8")
        after = after_bytes.decode("utf-8")
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return PatchChange(
            path=path,
            before_hash=hashlib.sha256(before_bytes).hexdigest(),
            after_hash=hashlib.sha256(after_bytes).hexdigest(),
            unified_diff=diff,
            before_content=before,
            after_content=after,
        )

    @staticmethod
    def _retry_question(validation: RepairValidation) -> str:
        return (
            "The previous sandboxed repair was rejected: "
            f"{validation.failure_reason}. Propose a corrected bounded repair."
        )
