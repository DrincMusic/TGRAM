from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from .adapters import Investigator
from .conflicts import detect_conflicts
from .fingerprint import indexed_project_fingerprint, task_fingerprint
from .models import (
    Claim,
    ClaimConflict,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    StoppingReason,
    Task,
    TaskKind,
    TaskRoute,
    TaskStatus,
)
from .onboarding import (
    BoundedReadOnlyWorkerBoundary,
    ProjectSelection,
    ReadOnlyProjectOnboarder,
    ReadOnlyViolation,
)
from .provenance import capture_indexed_source_files
from .relevance import terms
from .store import GraphStore
from .supervisor import GraphGroundedSupervisor
from .workflow_fact_search import WorkflowFactSearch


class RecursiveInvestigator(Investigator, Protocol):
    def synthesize(self, question: str, findings: list[Claim]) -> InvestigationResult: ...


@dataclass
class RecursiveRunResult:
    task: Task
    claim: Claim
    sub_tasks: list[Task] = field(default_factory=list)
    finding_claims: list[Claim] = field(default_factory=list)
    planning_questions: list[str] = field(default_factory=list)
    conflicts: list[ClaimConflict] = field(default_factory=list)
    cache_hit: bool = False
    reuse_type: str | None = None
    investigation_calls: int = 0
    elapsed_seconds: float = 0.0
    budget_exhausted: bool = False


@dataclass
class _BranchResult:
    task: Task
    claim: Claim
    cache_hit: bool
    investigation_calls: int


class RecursiveInvestigationSupervisor:
    """Generic read-only question decomposition over the existing Task/Claim graph."""

    def __init__(
        self,
        store: GraphStore,
        investigator: RecursiveInvestigator,
        *,
        branch_supervisor: GraphGroundedSupervisor | None = None,
        max_depth: int = 2,
        max_branches: int = 4,
        max_model_calls: int = 8,
        max_wall_time_seconds: float | None = 180.0,
    ) -> None:
        if max_depth < 1 or max_branches < 2 or max_model_calls < 4:
            raise ValueError("Recursive investigation budgets are too small to support decomposition.")
        if max_wall_time_seconds is not None and max_wall_time_seconds <= 0:
            raise ValueError("Recursive investigation wall time must be positive or unlimited.")
        self.store = store
        self.investigator = investigator
        self.branch_supervisor = branch_supervisor
        self.max_depth = max_depth
        self.max_branches = max_branches
        self.max_model_calls = max_model_calls
        self.max_wall_time_seconds = max_wall_time_seconds

    def run(
        self, question: str, project_root: str | Path, *, force_investigation: bool = False,
        progress=None,
    ) -> RecursiveRunResult:
        started = time.monotonic()
        root_path = Path(project_root).resolve()
        scan = ReadOnlyProjectOnboarder(self.store).scan(ProjectSelection.explicit(root_path))
        files = self.store.project_files(scan.project_id)
        project_state = indexed_project_fingerprint(
            root_path, [(item.path, item.content_hash) for item in files]
        )
        root_fingerprint = task_fingerprint(f"recursive:{question}", project_state)
        if not force_investigation:
            replay = self._exact_replay(root_fingerprint, project_state)
            if replay is not None:
                return replay
        root = Task.create(
            question, root_path, root_fingerprint, project_state,
        )
        root.started_at = datetime.now(UTC)
        root.attempt_count = 1
        root.route = TaskRoute.CODEX
        self.store.save_task(root)

        catalog = self._planning_catalog(question, scan.project_id, files)
        search = WorkflowFactSearch(self.store).search(question, root_path, scan.project_id, files=files)
        catalog += search.context()
        if callable(progress):
            progress(
                "EVIDENCE_PLANNING",
                f"Planning evidence coverage from {len(files)} indexed files.",
            )
            progress("WORKFLOW_FACT_SEARCH", f"Found {len(search.hits)} relevant sources and findings; "
                     f"searched {search.files_searched} files, skipped {search.files_skipped}.")
        model_calls = 1
        branch_failures: list[str] = []
        try:
            with TemporaryDirectory(prefix="rlmgraph-plan-") as directory:
                plan_result = self.investigator.investigate(
                    self._planning_prompt(question, catalog), Path(directory)
                )
            planned = self._planned_questions(question, plan_result)
        except TimeoutError as error:
            planned = [question]
            branch_failures.append(
                f"Planning timed out; continued with the authoritative user question: {error}"
            )
            if callable(progress):
                progress(
                    "EVIDENCE_PLANNING_TIMEOUT",
                    "Planning reached its deadline; continuing with the original question.",
                )
        queue = [(root, item, 1) for item in planned]
        seen = {self._normalize(item) for item in planned}
        tasks: list[Task] = []
        findings: list[Claim] = []
        reused = 0
        budget_exhausted = False
        branch_ordinal = 0

        while queue:
            parent, branch_question, depth = queue.pop(0)
            if model_calls >= self.max_model_calls - 1 or self._expired(started):
                budget_exhausted = True
                break
            branch_ordinal += 1
            if callable(progress):
                progress(
                    "EVIDENCE_BRANCH",
                    f"Branch {branch_ordinal} · depth {depth}/{self.max_depth}: "
                    f"{branch_question}",
                )
            try:
                result = (
                    self.branch_supervisor.run(
                        branch_question, root_path, force_investigation=force_investigation
                    )
                    if self.branch_supervisor is not None
                    else self._investigate_bounded(
                        branch_question, root_path, scan.project_id, files,
                        project_state, force_investigation,
                    )
                )
            except (ReadOnlyViolation, RuntimeError, TimeoutError) as error:
                model_calls += 1
                failed = Task.create(
                    branch_question,
                    root_path,
                    task_fingerprint(f"rejected-branch:{branch_question}", project_state),
                    project_state,
                )
                failed.kind = TaskKind.FOLLOW_UP
                failed.parent_task_id = parent.id
                failed.depth = depth
                failed.route = TaskRoute.LOCAL_INVESTIGATOR
                failed.status = TaskStatus.STOPPED
                failed.started_at = failed.completed_at = datetime.now(UTC)
                failed.stopping_reason = StoppingReason.RETRY_EXHAUSTED
                failed.last_error = str(error)
                self.store.save_task(failed)
                self.store.save_edge(
                    GraphEdge(
                        source=parent.id, relation=GraphRelation.SPAWNED, target=failed.id
                    )
                )
                tasks.append(failed)
                branch_failures.append(
                    f"Rejected branch '{branch_question}': {error}"
                )
                if callable(progress):
                    progress(
                        "EVIDENCE_BRANCH_STOPPED",
                        f"Branch {branch_ordinal} stopped: {type(error).__name__}. Moving on.",
                    )
                continue
            model_calls += result.investigation_calls
            task = result.task
            task.kind = TaskKind.FOLLOW_UP
            task.parent_task_id = parent.id
            task.depth = depth
            self.store.save_task(task)
            self.store.save_edge(
                GraphEdge(source=parent.id, relation=GraphRelation.SPAWNED, target=task.id)
            )
            self.store.save_edge(
                GraphEdge(source=result.claim.id, relation=GraphRelation.INFORMS, target=root.id)
            )
            tasks.append(task)
            findings.append(result.claim)
            reused += int(result.cache_hit)

            if depth < self.max_depth:
                for gap in result.claim.unresolved_questions[: self.max_branches]:
                    normalized = self._normalize(gap)
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        queue.append((task, f"Resolve this evidence gap: {gap}", depth + 1))

        if not findings:
            root.status = TaskStatus.STOPPED
            root.stopping_reason = StoppingReason.CALL_BUDGET
            root.completed_at = datetime.now(UTC)
            self.store.save_task(root)
            raise RuntimeError("Recursive investigation exhausted its budget before any branch completed.")

        conflicts = [
            conflict
            for index, claim in enumerate(findings)
            for conflict in detect_conflicts(claim, findings[:index])
        ]
        for conflict in conflicts:
            self.store.save_edge(
                GraphEdge(
                    source=conflict.left_claim_id,
                    relation=GraphRelation.CONTRADICTS,
                    target=conflict.right_claim_id,
                )
            )

        synthesis_timeout = self._expired(started)
        if callable(progress):
            progress(
                "EVIDENCE_SYNTHESIS",
                f"Synthesizing {len(findings)} completed evidence branch(es).",
            )
        try:
            synthesis = (
                self._fallback_synthesis(findings, "The total evidence deadline was reached.")
                if synthesis_timeout
                else self.investigator.synthesize(question, findings)
            )
        except TimeoutError as error:
            synthesis_timeout = True
            synthesis = self._fallback_synthesis(findings, str(error))
            if callable(progress):
                progress(
                    "EVIDENCE_PARTIAL_RESULT",
                    "Synthesis reached its deadline; returning the strongest completed branch.",
                )
        if synthesis_timeout:
            budget_exhausted = True
        synthesis.unresolved_questions = list(
            dict.fromkeys([*synthesis.unresolved_questions, *branch_failures])
        )
        model_calls += 1
        final_claim = Claim(
            fingerprint=task_fingerprint(
                f"recursive-synthesis:{question}",
                task_fingerprint("\0".join(item.id for item in findings), project_state),
            ),
            project_fingerprint=project_state,
            project_root=str(root_path),
            subject=question,
            producer=type(self.investigator).__name__,
            source_claim_ids=[item.id for item in findings],
            **synthesis.model_dump(),
        )
        root.output_claim_id = final_claim.id
        root.source_claim_ids = [item.id for item in findings]
        root.completed_at = datetime.now(UTC)
        root.status = (
            TaskStatus.RECURSE
            if budget_exhausted or final_claim.unresolved_questions
            else TaskStatus.DONE
        )
        root.stopping_reason = (
            StoppingReason.CALL_BUDGET
            if budget_exhausted
            else StoppingReason.LOW_CONFIDENCE
            if final_claim.unresolved_questions
            else StoppingReason.COMPLETED
        )
        root.reuse_type = "recursive-memory" if reused == len(tasks) else None
        root.reuse_reason = (
            "Every recursive branch reused a current graph claim."
            if root.reuse_type else None
        )
        self.store.save_task(root)
        self.store.save_claim(root, final_claim)
        for finding in findings:
            self.store.save_edge(
                GraphEdge(
                    source=final_claim.id,
                    relation=GraphRelation.SYNTHESIZED_FROM,
                    target=finding.id,
                )
            )
        return RecursiveRunResult(
            task=root,
            claim=final_claim,
            sub_tasks=tasks,
            finding_claims=findings,
            planning_questions=planned,
            conflicts=conflicts,
            cache_hit=bool(tasks) and reused == len(tasks),
            reuse_type=root.reuse_type,
            investigation_calls=model_calls,
            elapsed_seconds=time.monotonic() - started,
            budget_exhausted=budget_exhausted,
        )

    @staticmethod
    def _fallback_synthesis(findings: list[Claim], reason: str) -> InvestigationResult:
        strongest = max(findings, key=lambda item: item.confidence)
        return InvestigationResult(
            conclusion=strongest.conclusion,
            evidence=strongest.evidence,
            confidence=strongest.confidence,
            files_examined=strongest.files_examined,
            unresolved_questions=[
                *strongest.unresolved_questions,
                f"Partial evidence returned because synthesis did not complete: {reason}",
            ],
            assertions=strongest.assertions,
        )

    def _exact_replay(
        self, root_fingerprint: str, project_state: str
    ) -> RecursiveRunResult | None:
        root = next(
            (
                task
                for task in reversed(self.store.tasks())
                if task.fingerprint == root_fingerprint
                and task.project_fingerprint == project_state
                and task.status == TaskStatus.DONE
                and task.output_claim_id
            ),
            None,
        )
        if root is None:
            return None
        claim = self.store.get_claim(root.output_claim_id)
        if claim is None or claim.validity_status.value != "CURRENT":
            return None
        findings = [
            item
            for claim_id in root.source_claim_ids
            if (item := self.store.get_claim(claim_id)) is not None
            and item.validity_status.value == "CURRENT"
        ]
        if len(findings) != len(root.source_claim_ids):
            return None
        descendants: list[Task] = []
        parent_ids = {root.id}
        remaining = self.store.tasks()
        while True:
            children = [task for task in remaining if task.parent_task_id in parent_ids]
            children = [task for task in children if task not in descendants]
            if not children:
                break
            descendants.extend(children)
            parent_ids.update(task.id for task in children)
        return RecursiveRunResult(
            task=root,
            claim=claim,
            sub_tasks=descendants,
            finding_claims=findings,
            planning_questions=[
                task.question for task in descendants if task.parent_task_id == root.id
            ],
            conflicts=[
                conflict
                for index, finding in enumerate(findings)
                for conflict in detect_conflicts(finding, findings[:index])
            ],
            cache_hit=True,
            reuse_type="exact-recursive-replay",
            investigation_calls=0,
        )

    def _investigate_bounded(
        self,
        question: str,
        root: Path,
        project_id: str,
        files,
        project_state: str,
        force_investigation: bool,
    ) -> _BranchResult:
        search = WorkflowFactSearch(self.store).search(question, root, project_id, files=files)
        paths = {hit.path for hit in search.hits if hit.path}
        searched = [item for item in files if item.path in paths]
        selected = list({item.id: item for item in
                         [*searched, *self._select_files(question, project_id, files)]}.values())[:24]
        if not selected:
            raise RuntimeError(
                "Recursive planning produced a branch with no relevant indexed evidence slice."
            )
        slice_state = task_fingerprint(
            "\0".join(f"{item.path}:{item.content_hash}" for item in selected), project_state
        )
        fingerprint = task_fingerprint(question, slice_state)
        task = Task(
            question=question, fingerprint=fingerprint,
            project_fingerprint=project_state, project_root=str(root),
            kind=TaskKind.FOLLOW_UP,
            relevant_files=[item.path for item in selected],
        )
        reusable = None
        if not force_investigation:
            prior_task = next(
                (
                    item for item in reversed(self.store.tasks())
                    if item.id != task.id and item.fingerprint == fingerprint
                    and item.status == TaskStatus.DONE and item.output_claim_id
                ),
                None,
            )
            reusable = self.store.get_claim(prior_task.output_claim_id) if prior_task else None
            if reusable is not None and reusable.validity_status.value != "CURRENT":
                reusable = None
        if reusable is not None:
            task.status = TaskStatus.DONE
            task.route = TaskRoute.MEMORY
            task.output_claim_id = reusable.id
            task.reused_claim_id = reusable.id
            task.reuse_type = "recursive-slice"
            task.reuse_reason = "Exact subquestion and unchanged bounded indexed source slice."
            task.started_at = task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.COMPLETED
            self.store.save_task(task)
            self.store.save_edge(
                GraphEdge(source=task.id, relation=GraphRelation.REUSED, target=reusable.id)
            )
            return _BranchResult(task, reusable, True, 0)

        task.started_at = datetime.now(UTC)
        task.attempt_count = 1
        task.route = TaskRoute.LOCAL_INVESTIGATOR
        self.store.save_task(task)
        result = BoundedReadOnlyWorkerBoundary(
            ProjectSelection.explicit(root), [item.path for item in selected]
        ).investigate(self.investigator, question + search.context())
        claim = Claim(
            fingerprint=fingerprint, project_fingerprint=project_state,
            project_root=str(root), subject=question,
            producer=type(self.investigator).__name__, **result.model_dump(),
        )
        claim.source_files = capture_indexed_source_files(claim, selected)
        task.output_claim_id = claim.id
        task.status = TaskStatus.RECURSE if claim.unresolved_questions else TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        task.stopping_reason = (
            StoppingReason.LOW_CONFIDENCE
            if claim.unresolved_questions else StoppingReason.COMPLETED
        )
        self.store.save_task(task)
        self.store.save_claim(task, claim)
        return _BranchResult(task, claim, False, 1)

    def _select_files(self, question: str, project_id: str, files) -> list:
        query_terms = terms(question)
        symbols = self.store.project_symbols(project_id)
        symbol_terms: dict[str, set[str]] = {}
        for symbol in symbols:
            symbol_terms.setdefault(symbol.file_id, set()).update(terms(symbol.name))
        ranked = []
        for file in files:
            path_terms = terms(file.path.replace("/", " ").replace(".", " "))
            matched = query_terms & (path_terms | symbol_terms.get(file.id, set()))
            if matched:
                ranked.append((len(matched), int(file.is_test), file.path, file))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        selected = [item[3] for item in ranked[:16]]
        if not selected:
            return []
        selected_ids = {item.id for item in selected}
        by_id = {item.id: item for item in files}
        for dependency in self.store.project_dependencies(project_id):
            if len(selected) >= 24:
                break
            adjacent = None
            if dependency.source_file_id in selected_ids and dependency.target_file_id:
                adjacent = dependency.target_file_id
            elif dependency.target_file_id in selected_ids:
                adjacent = dependency.source_file_id
            if adjacent and adjacent in by_id and adjacent not in selected_ids:
                selected_ids.add(adjacent)
                selected.append(by_id[adjacent])
        return sorted(selected, key=lambda item: item.path)

    def _planning_catalog(self, question: str, project_id: str, files) -> str:
        query_terms = terms(question)
        ranked_paths = sorted(
            files,
            key=lambda file: (
                -len(query_terms & terms(file.path.replace("/", " ").replace(".", " "))),
                file.path,
            ),
        )[:120]
        symbols = sorted(
            self.store.project_symbols(project_id),
            key=lambda symbol: (
                -len(query_terms & terms(symbol.name)), symbol.name, symbol.source_path
            ),
        )[:160]
        return (
            "Indexed files:\n"
            + "\n".join(
                f"- {item.path} ({item.language}{', test' if item.is_test else ''})"
                for item in ranked_paths
            )
            + "\nIndexed symbols:\n"
            + "\n".join(f"- {item.name} — {item.source_path}" for item in symbols)
        )

    def _expired(self, started: float) -> bool:
        return (
            self.max_wall_time_seconds is not None
            and time.monotonic() - started >= self.max_wall_time_seconds
        )

    def _planned_questions(
        self, original: str, result: InvestigationResult
    ) -> list[str]:
        questions = [
            " ".join(item.split())
            for item in result.unresolved_questions
            if item and " ".join(item.split())
        ]
        unique = list(dict.fromkeys(questions))[: self.max_branches]
        return unique if len(unique) >= 2 else [original]

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _planning_prompt(question: str, catalog: str) -> str:
        return (
            "Plan a repository investigation without answering it. Put two to four independent, "
            "evidence-seeking subquestions in unresolved_questions. Each subquestion must test a "
            "material part of the premise and be answerable from repository evidence. Include a "
            "counterevidence or falsification branch when appropriate. If the question genuinely "
            "cannot benefit from decomposition, return no unresolved questions. Do not treat "
            "documentation as proof of implementation. You have the bounded index catalog and "
            "retrieved excerpts below, but no direct repository access during planning. Name concrete indexed files or "
            "symbols in each subquestion so a minimal evidence slice can be selected. Original "
            f"question: {question}\n\n{catalog}"
        )
