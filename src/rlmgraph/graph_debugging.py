from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .adapters import Investigator
from .conflicts import detect_conflicts
from .fingerprint import indexed_project_fingerprint, task_fingerprint
from .models import (
    Claim,
    DependencySlice,
    GraphDebugResult,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    ProjectDependency,
    ProjectFile,
    ProjectTest,
    StoppingReason,
    Task,
    TaskKind,
    TaskStatus,
)
from .onboarding import (
    BoundedReadOnlyWorkerBoundary,
    ProjectSelection,
    ProjectSelectionError,
    ReadOnlyProjectOnboarder,
    ReadOnlyViolation,
)
from .provenance import capture_indexed_source_files
from .store import GraphStore


class DebugSynthesizer(Protocol):
    def synthesize(self, question: str, findings: list[Claim]) -> InvestigationResult: ...


class ProjectNotOnboardedError(ProjectSelectionError):
    pass


def _slice_state(files: list[ProjectFile]) -> str:
    payload = [(item.path, item.content_hash) for item in sorted(files, key=lambda item: item.path)]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


class GraphDirectedDebugger:
    """Trace one indexed test and delegate only dependency-bounded investigations."""

    def __init__(
        self,
        store: GraphStore,
        investigator: Investigator,
        synthesizer: DebugSynthesizer,
        *,
        minimum_confidence: float = 0.75,
        max_gap_depth: int = 1,
        max_dependency_files: int = 64,
        max_wall_time_seconds: float | None = None,
    ) -> None:
        self.store = store
        self.investigator = investigator
        self.synthesizer = synthesizer
        self.minimum_confidence = minimum_confidence
        self.max_gap_depth = max_gap_depth
        self.max_dependency_files = max_dependency_files
        self.max_wall_time_seconds = max_wall_time_seconds
        self.worker_calls = 0
        self._index_cache: dict[
            str, tuple[list[ProjectFile], list[ProjectTest], list[ProjectDependency]]
        ] = {}
        self.store.initialize()

    def debug(
        self,
        question: str,
        project_root: str | Path,
        test_path: str,
        *,
        refresh_index: bool = True,
    ) -> GraphDebugResult:
        deadline = (
            time.monotonic() + self.max_wall_time_seconds
            if self.max_wall_time_seconds is not None
            else None
        )
        selection = ProjectSelection.explicit(project_root)
        project = next(
            (
                item
                for item in self.store.projects()
                if Path(item.root).resolve() == selection.root
            ),
            None,
        )
        if project is None:
            raise ProjectNotOnboardedError(
                "Graph-directed debugging requires an existing project index; run onboarding first."
            )
        if refresh_index:
            scan = ReadOnlyProjectOnboarder(self.store).scan(selection)
        else:
            scans = self.store.project_scans(project.id)
            if not scans:
                raise ProjectNotOnboardedError(
                    "Graph-directed debugging requires a completed project scan."
                )
            scan = scans[-1]
        cached_index = self._index_cache.get(scan.id)
        if cached_index is None:
            cached_index = (
                self.store.project_files(scan.project_id),
                self.store.project_tests(scan.project_id),
                self.store.project_dependencies(scan.project_id),
            )
            self._index_cache = {scan.id: cached_index}
        files, indexed_tests, indexed_dependencies = cached_index
        project_state = indexed_project_fingerprint(
            selection.root, [(item.path, item.content_hash) for item in files]
        )
        dependency_slice = self.trace_test(
            scan.project_id,
            test_path,
            files=files,
            tests=indexed_tests,
            dependencies=indexed_dependencies,
        )
        if len(dependency_slice.file_ids) > self.max_dependency_files:
            raise ReadOnlyViolation(
                "Dependency slice exceeds the bounded diagnostic file limit: "
                f"{len(dependency_slice.file_ids)} > {self.max_dependency_files}."
            )
        slice_files = [item for item in files if item.id in dependency_slice.file_ids]
        root = Task.create(
            question,
            selection.root,
            task_fingerprint(question, project_state),
            project_state,
        )
        root.relevant_files = dependency_slice.paths
        root.started_at = datetime.now(UTC)
        root.attempt_count = 1
        self.store.save_task(root)
        for dependency_id in dependency_slice.dependency_ids:
            self.store.save_edge(
                GraphEdge(
                    source=root.id,
                    relation=GraphRelation.TRACED_DEPENDENCY,
                    target=dependency_id,
                )
            )

        repaired_state = next(
            (
                claim
                for claim in reversed(self.store.claims())
                if claim.project_fingerprint == project_state
                and claim.project_root
                and Path(claim.project_root).resolve() == selection.root
                and claim.validity_status.value == "CURRENT"
                and any(
                    assertion.key == f"test.status:{dependency_slice.test_path}"
                    and assertion.value == "passing"
                    for assertion in claim.assertions
                )
            ),
            None,
        )
        if repaired_state is not None:
            root.attempt_count = 0
            root.output_claim_id = repaired_state.id
            root.source_claim_ids = [repaired_state.id]
            root.status = TaskStatus.DONE
            root.completed_at = datetime.now(UTC)
            root.stopping_reason = StoppingReason.COMPLETED
            root.reused_claim_id = repaired_state.id
            root.reuse_type = "reconciled-repair"
            root.reuse_reason = (
                "The current indexed project state contains a final-test-verified repair "
                "claim for this exact test."
            )
            repaired_state.successful_reuse_count += 1
            self.store.update_claim(repaired_state)
            self.store.save_task(root)
            self.store.save_edge(
                GraphEdge(
                    source=root.id,
                    relation=GraphRelation.REUSED,
                    target=repaired_state.id,
                )
            )
            return GraphDebugResult(
                root_task=root,
                diagnosis=repaired_state,
                dependency_slice=dependency_slice,
                project_scan=scan,
                worker_calls=0,
                reused_subtasks=0,
            )

        start_calls = self.worker_calls
        sub_tasks: list[Task] = []
        findings: list[Claim] = []
        reused = 0
        for file in slice_files:
            if deadline is not None and time.monotonic() >= deadline:
                raise ReadOnlyViolation("Diagnostic exceeded its wall-time safety limit.")
            task, claim, was_reused = self._investigate_slice(
                root,
                selection,
                question=(
                    f"Diagnose '{question}' by inspecting only the authorized file {file.path}. "
                    "Report only evidence available in that file."
                ),
                allowed=[file],
            )
            sub_tasks.append(task)
            findings.append(claim)
            reused += int(was_reused)
            gap_tasks, gap_claims = self._pursue_gaps(task, claim, selection, [file])
            sub_tasks.extend(gap_tasks)
            findings.extend(gap_claims)

        if deadline is not None and time.monotonic() >= deadline:
            raise ReadOnlyViolation("Diagnostic exceeded its wall-time safety limit.")

        conflict_tasks, conflict_claims = self._resolve_disagreements(
            root, selection, slice_files, findings
        )
        sub_tasks.extend(conflict_tasks)
        findings.extend(conflict_claims)
        diagnosis_result = self.synthesizer.synthesize(question, findings)
        self._validate_reported_paths(diagnosis_result, dependency_slice.paths)
        diagnosis = Claim(
            fingerprint=task_fingerprint(
                "synthesis:" + question,
                hashlib.sha256("\0".join(item.id for item in findings).encode()).hexdigest(),
            ),
            project_fingerprint=project_state,
            subject=question,
            producer=type(self.synthesizer).__name__,
            source_claim_ids=[item.id for item in findings],
            **diagnosis_result.model_dump(),
        )
        diagnosis.source_files = capture_indexed_source_files(diagnosis, slice_files)
        root.output_claim_id = diagnosis.id
        root.source_claim_ids = diagnosis.source_claim_ids
        root.status = (
            TaskStatus.DONE
            if diagnosis.confidence >= self.minimum_confidence
            and not diagnosis.unresolved_questions
            else TaskStatus.RECURSE
        )
        root.completed_at = datetime.now(UTC)
        root.stopping_reason = (
            StoppingReason.COMPLETED
            if root.status == TaskStatus.DONE
            else StoppingReason.LOW_CONFIDENCE
        )
        self.store.save_task(root)
        self.store.save_claim(root, diagnosis)
        for claim in findings:
            self.store.save_edge(
                GraphEdge(
                    source=diagnosis.id,
                    relation=GraphRelation.SYNTHESIZED_FROM,
                    target=claim.id,
                )
            )
        analyzed = sorted(
            {
                path
                for claim in findings
                for path in [*claim.files_examined, *(item.path for item in claim.evidence)]
            }
        )
        return GraphDebugResult(
            root_task=root,
            sub_tasks=sub_tasks,
            finding_claims=findings,
            diagnosis=diagnosis,
            dependency_slice=dependency_slice,
            project_scan=scan,
            worker_calls=self.worker_calls - start_calls,
            reused_subtasks=reused,
            analyzed_files=analyzed,
            supplied_files=sorted(
                {path for task in sub_tasks for path in task.relevant_files}
            ),
        )

    def trace_test(
        self,
        project_id: str,
        test_path: str,
        *,
        files: list[ProjectFile] | None = None,
        tests: list[ProjectTest] | None = None,
        dependencies: list[ProjectDependency] | None = None,
    ) -> DependencySlice:
        normalized = test_path.replace("\\", "/")
        files = files if files is not None else self.store.project_files(project_id)
        by_id = {item.id: item for item in files}
        test = next(
            (
                item
                for item in (
                    tests if tests is not None else self.store.project_tests(project_id)
                )
                if item.source_path == normalized
            ),
            None,
        )
        test_file = next((item for item in files if item.path == normalized and item.is_test), None)
        if test is None or test_file is None:
            raise ValueError(f"Indexed test not found: {normalized}")
        dependencies = (
            dependencies
            if dependencies is not None
            else self.store.project_dependencies(project_id)
        )
        by_source: dict[str, list[ProjectDependency]] = {}
        for dependency in dependencies:
            by_source.setdefault(dependency.source_file_id, []).append(dependency)
        selected = {test_file.id}
        selected_dependencies: list[str] = []
        queue = [test_file.id]
        while queue:
            source_id = queue.pop(0)
            for dependency in by_source.get(source_id, []):
                if not dependency.target_file_id:
                    continue
                selected_dependencies.append(dependency.id)
                if dependency.target_file_id not in selected:
                    selected.add(dependency.target_file_id)
                    queue.append(dependency.target_file_id)
        paths = sorted(by_id[item].path for item in selected)
        return DependencySlice(
            test_path=normalized,
            test_file_id=test_file.id,
            file_ids=sorted(selected),
            paths=paths,
            dependency_ids=list(dict.fromkeys(selected_dependencies)),
            excluded_paths=sorted(item.path for item in files if item.id not in selected),
        )

    def _investigate_slice(
        self,
        parent: Task,
        selection: ProjectSelection,
        question: str,
        allowed: list[ProjectFile],
    ) -> tuple[Task, Claim, bool]:
        fingerprint = task_fingerprint(question, _slice_state(allowed))
        task = Task(
            question=question,
            fingerprint=fingerprint,
            project_fingerprint=parent.project_fingerprint,
            project_root=parent.project_root,
            kind=TaskKind.FOLLOW_UP,
            parent_task_id=parent.id,
            depth=parent.depth + 1,
            relevant_files=sorted(item.path for item in allowed),
        )
        self.store.save_task(task)
        self.store.save_edge(
            GraphEdge(source=parent.id, relation=GraphRelation.SPAWNED, target=task.id)
        )
        for file in allowed:
            self.store.save_edge(
                GraphEdge(
                    source=task.id,
                    relation=GraphRelation.AUTHORIZED_FILE,
                    target=file.id,
                )
            )
        reusable_task = next(
            (
                item
                for item in reversed(self.store.tasks())
                if item.id != task.id
                and item.fingerprint == fingerprint
                and Path(item.project_root).resolve()
                == Path(parent.project_root).resolve()
                and item.status == TaskStatus.DONE
                and item.output_claim_id
            ),
            None,
        )
        reusable_claim = (
            self.store.get_claim(reusable_task.output_claim_id)
            if reusable_task and reusable_task.output_claim_id
            else None
        )
        if reusable_claim and reusable_claim.validity_status.value == "CURRENT":
            task.status = TaskStatus.DONE
            task.output_claim_id = reusable_claim.id
            task.reused_claim_id = reusable_claim.id
            task.reuse_type = "dependency-slice"
            task.reuse_reason = "Equivalent bounded subtask and unchanged authorized source slice."
            task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.COMPLETED
            self.store.save_task(task)
            self.store.save_edge(
                GraphEdge(
                    source=task.id,
                    relation=GraphRelation.REUSED,
                    target=reusable_claim.id,
                )
            )
            return task, reusable_claim, True
        task.started_at = datetime.now(UTC)
        task.attempt_count = 1
        self.store.save_task(task)
        result = BoundedReadOnlyWorkerBoundary(
            selection, task.relevant_files
        ).investigate(self.investigator, question)
        self.worker_calls += 1
        claim = Claim(
            fingerprint=fingerprint,
            project_fingerprint=parent.project_fingerprint,
            subject=question,
            producer=type(self.investigator).__name__,
            **result.model_dump(),
        )
        claim.source_files = capture_indexed_source_files(claim, allowed)
        task.output_claim_id = claim.id
        task.status = TaskStatus.RECURSE if result.unresolved_questions else TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        task.stopping_reason = (
            StoppingReason.LOW_CONFIDENCE
            if result.unresolved_questions
            else StoppingReason.COMPLETED
        )
        self.store.save_task(task)
        self.store.save_claim(task, claim)
        self.store.save_edge(
            GraphEdge(source=claim.id, relation=GraphRelation.INFORMS, target=parent.id)
        )
        return task, claim, False

    def _pursue_gaps(
        self,
        parent: Task,
        claim: Claim,
        selection: ProjectSelection,
        allowed: list[ProjectFile],
    ) -> tuple[list[Task], list[Claim]]:
        if parent.depth > self.max_gap_depth or not claim.unresolved_questions:
            return [], []
        tasks: list[Task] = []
        claims: list[Claim] = []
        for gap in claim.unresolved_questions:
            task, finding, _ = self._investigate_slice(
                parent, selection, f"Resolve evidence gap: {gap}", allowed
            )
            tasks.append(task)
            claims.append(finding)
        return tasks, claims

    def _resolve_disagreements(
        self,
        root: Task,
        selection: ProjectSelection,
        files: list[ProjectFile],
        claims: list[Claim],
    ) -> tuple[list[Task], list[Claim]]:
        conflicts = [
            conflict
            for index, claim in enumerate(claims)
            for conflict in detect_conflicts(claim, claims[:index])
        ]
        if not conflicts:
            return [], []
        by_id = {claim.id: claim for claim in claims}
        files_by_path = {item.path: item for item in files}
        tasks: list[Task] = []
        findings: list[Claim] = []
        handled: set[tuple[str, str, str]] = set()
        for conflict in conflicts:
            key = tuple(sorted((conflict.left_claim_id, conflict.right_claim_id))) + (
                conflict.assertion_key,
            )
            if key in handled:
                continue
            handled.add(key)
            participants = [by_id[conflict.left_claim_id], by_id[conflict.right_claim_id]]
            paths = {
                source.path for claim in participants for source in claim.source_files
            }
            allowed = [files_by_path[path] for path in sorted(paths) if path in files_by_path]
            task, finding, _ = self._investigate_slice(
                root,
                selection,
                (
                    f"Resolve conflicting '{conflict.assertion_key}' findings: "
                    f"'{conflict.left_value}' versus '{conflict.right_value}'."
                ),
                allowed,
            )
            task.conflicting_claim_ids = [item.id for item in participants]
            self.store.save_task(task)
            for participant in participants:
                self.store.save_edge(
                    GraphEdge(
                        source=participant.id,
                        relation=GraphRelation.CONTRADICTS,
                        target=(
                            participants[1].id
                            if participant.id == participants[0].id
                            else participants[0].id
                        ),
                    )
                )
            tasks.append(task)
            findings.append(finding)
        return tasks, findings

    @staticmethod
    def _validate_reported_paths(result: InvestigationResult, allowed: list[str]) -> None:
        if result.files_changed:
            raise ReadOnlyViolation(
                "A graph-directed synthesis must not report project changes."
            )
        reported = {
            path.replace("\\", "/")
            for path in [
                *result.files_examined,
                *(item.path for item in result.evidence),
            ]
        }
        outside = sorted(reported - set(allowed))
        if outside:
            raise ReadOnlyViolation(
                "Synthesis cited evidence outside the traced dependency slice: "
                + ", ".join(outside)
            )
