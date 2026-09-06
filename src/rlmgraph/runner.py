from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from time import perf_counter

from .execution import ExecutionLedger
from .fingerprint import task_fingerprint
from .followup import FollowUpExecutor
from .models import (
    ClaimValidity,
    ClusterStatus,
    ExecutionOutcome,
    GraphEdge,
    GraphRelation,
    PlanningAction,
    PursuitConfig,
    PursuitResult,
    StoppingReason,
    Task,
    TaskKind,
    TaskRoute,
    TaskStatus,
)
from .planner import RecursivePlanner, token_estimate
from .resolution import ResolutionExecutor
from .store import GraphStore


class RecursiveRunner:
    """Persisted, bounded scheduler for a root task and all of its descendants."""

    def __init__(
        self,
        store: GraphStore,
        resolution_executor: ResolutionExecutor,
        config: PursuitConfig | None = None,
        follow_up_executor: FollowUpExecutor | None = None,
    ) -> None:
        self.store = store
        self.resolution_executor = resolution_executor
        self.follow_up_executor = follow_up_executor
        self.config = config or PursuitConfig()
        self.resolution_executor.confidence_threshold = self.config.minimum_confidence
        self.resolution_executor.max_resolution_attempts = self.config.max_retries_per_task
        self.store.initialize()

    def pursue(self, root_task_id: str, initial_codex_calls: int = 0) -> PursuitResult:
        if self.store.get_task(root_task_id) is None:
            raise ValueError(f"Root task not found: {root_task_id}")
        queue = deque([root_task_id])
        queued = {root_task_id}
        codex_calls = initial_codex_calls
        stop_reason: StoppingReason | None = None
        planner = RecursivePlanner(self.store, root_task_id, self.config)
        execution_ledger = ExecutionLedger(self.store)
        planner.run.model_calls_used = initial_codex_calls
        root_task = self.store.get_task(root_task_id)
        assert root_task is not None
        planner.assess(
            root_task,
            "Root task entered the recursive plan.",
            action=PlanningAction.PRIORITIZED,
        )
        if root_task.status == TaskStatus.DONE:
            execution_ledger.record(
                root_task,
                planned_route=TaskRoute.MEMORY,
                actual_route=TaskRoute.MEMORY,
                worker="GraphMemory",
                outcome=ExecutionOutcome.REUSED,
                fallback_reason="Completed task graph satisfied the replay without a model call.",
            )

        while queue:
            task_id = queue.popleft()
            queued.discard(task_id)
            task = self.store.get_task(task_id)
            assert task is not None
            if task.route is None:
                planner.assess(
                    task,
                    "Selected route from task kind, uncertainty, confidence, and difficulty.",
                    action=PlanningAction.ROUTED,
                )
            children = self._children(task.id)

            if task.kind == TaskKind.INVESTIGATION:
                if children:
                    self._enqueue(children, queue, queued)
                    continue
                if task.status == TaskStatus.RECURSE:
                    planner.record(
                        task,
                        PlanningAction.STOPPED,
                        "Investigation remains uncertain and has no schedulable child.",
                        stopping_reason=StoppingReason.LOW_CONFIDENCE,
                    )
                    stop_reason = stop_reason or StoppingReason.LOW_CONFIDENCE
                continue

            if task.kind == TaskKind.FOLLOW_UP:
                if task.status == TaskStatus.DONE:
                    self._requeue_parent(task, queue, queued)
                    continue
                reusable = self._completed_equivalent(task)
                if reusable is not None:
                    task.status = TaskStatus.DONE
                    task.output_claim_id = reusable.output_claim_id
                    task.reused_claim_id = reusable.output_claim_id
                    task.reuse_type = "completed-investigation"
                    task.completed_at = datetime.now(UTC)
                    self.store.save_task(task)
                    planner.note_duplicate_avoided(task, reusable.id)
                    execution_ledger.record(
                        task,
                        planned_route=TaskRoute.MEMORY,
                        actual_route=TaskRoute.MEMORY,
                        worker="GraphMemory",
                        outcome=ExecutionOutcome.REUSED,
                        confidence=(
                            self.store.get_claim(reusable.output_claim_id).confidence
                            if reusable.output_claim_id
                            and self.store.get_claim(reusable.output_claim_id)
                            else None
                        ),
                        fallback_reason=f"Reused completed task {reusable.id}.",
                    )
                    self._requeue_parent(task, queue, queued)
                    continue
                if self.follow_up_executor is None:
                    self._stop(task, StoppingReason.LOW_CONFIDENCE, planner)
                    stop_reason = stop_reason or StoppingReason.LOW_CONFIDENCE
                    continue
                budget_stop = planner.admit_call(
                    task, planner.retrieval_context(task, self.store)
                )
                if budget_stop is not None:
                    self._stop(task, budget_stop, planner)
                    stop_reason = stop_reason or budget_stop
                    continue
                investigator = self.follow_up_executor.investigator
                if hasattr(investigator, "configure_budget"):
                    investigator.configure_budget(
                        1 + self.config.max_codex_calls - planner.run.model_calls_used,
                        self.config.max_retrieval_tokens
                        - planner.run.retrieval_tokens_used,
                    )
                if task.status == TaskStatus.STOPPED:
                    if (
                        task.stopping_reason == StoppingReason.RETRY_EXHAUSTED
                        and task.attempt_count >= self.config.max_retries_per_task
                    ):
                        stop_reason = stop_reason or StoppingReason.RETRY_EXHAUSTED
                        continue
                    task.status = TaskStatus.OPEN
                    task.stopping_reason = None
                    task.completed_at = None
                    self.store.save_task(task)
                before = self.follow_up_executor.follow_up_calls
                try:
                    self.follow_up_executor.execute(task.id)
                except Exception as exc:  # noqa: BLE001
                    codex_calls += self.follow_up_executor.follow_up_calls - before
                    extra_calls = max(
                        0, self.follow_up_executor.follow_up_calls - before - 1
                    )
                    if extra_calls:
                        planner.run.model_calls_used += extra_calls
                        planner.run.retrieval_tokens_used += (
                            extra_calls * token_estimate(task.question)
                        )
                        self.store.save_planning_run(planner.run)
                    task = self.store.get_task(task.id) or task
                    task.last_error = str(exc)
                    if task.attempt_count >= self.config.max_retries_per_task:
                        self._stop(task, StoppingReason.RETRY_EXHAUSTED, planner)
                        stop_reason = stop_reason or StoppingReason.RETRY_EXHAUSTED
                    else:
                        self._enqueue([task], queue, queued)
                    continue
                codex_calls += self.follow_up_executor.follow_up_calls - before
                extra_calls = max(
                    0, self.follow_up_executor.follow_up_calls - before - 1
                )
                if extra_calls:
                    extra_tokens = extra_calls * token_estimate(task.question)
                    planner.run.model_calls_used += extra_calls
                    planner.run.retrieval_tokens_used += extra_tokens
                    self.store.save_planning_run(planner.run)
                task = self.store.get_task(task.id) or task
                self._requeue_parent(task, queue, queued)
                continue

            if task.status == TaskStatus.DONE:
                continue
            if self._has_cycle(task):
                self._stop(task, StoppingReason.CYCLE_DETECTED, planner)
                stop_reason = stop_reason or StoppingReason.CYCLE_DETECTED
                continue
            incomplete = [child for child in children if child.status != TaskStatus.DONE]
            if incomplete:
                terminal_child = next(
                    (
                        child
                        for child in incomplete
                        if child.status == TaskStatus.STOPPED
                        and child.stopping_reason
                        in {
                            StoppingReason.MAX_DEPTH,
                            StoppingReason.RETRY_EXHAUSTED,
                            StoppingReason.CYCLE_DETECTED,
                        }
                    ),
                    None,
                )
                if terminal_child is not None:
                    reason = terminal_child.stopping_reason or StoppingReason.LOW_CONFIDENCE
                    self._stop(task, reason, planner)
                    stop_reason = stop_reason or reason
                    continue
                self._enqueue(incomplete, queue, queued)
                self._enqueue([task], queue, queued)
                continue
            if task.status == TaskStatus.RECURSE:
                planner.record(
                    task,
                    PlanningAction.STOPPED,
                    "No additional evidence task could reduce the remaining uncertainty.",
                    stopping_reason=StoppingReason.LOW_CONFIDENCE,
                )
                stop_reason = stop_reason or StoppingReason.LOW_CONFIDENCE
                continue
            if task.status == TaskStatus.STOPPED:
                task.status = TaskStatus.OPEN
                task.stopping_reason = None
                task.completed_at = None
                self.store.save_task(task)

            while task.attempt_count < self.config.max_retries_per_task:
                budget_stop = planner.admit_call(
                    task, planner.retrieval_context(task, self.store)
                )
                if budget_stop is not None:
                    self._stop(task, budget_stop, planner)
                    stop_reason = stop_reason or budget_stop
                    break
                before = self.resolution_executor.resolution_calls
                attempt_before = task.attempt_count
                execution_started = perf_counter()
                execution_input_tokens = token_estimate(
                    planner.retrieval_context(task, self.store)
                )
                try:
                    outcome = self.resolution_executor.execute(task.id)
                except Exception as exc:  # noqa: BLE001 - retry boundary records tool failures
                    execution_ledger.record(
                        task,
                        planned_route=task.route or TaskRoute.RESOLVER,
                        actual_route=TaskRoute.RESOLVER,
                        worker=type(self.resolution_executor.resolver).__name__,
                        outcome=ExecutionOutcome.FAILED,
                        input_tokens=execution_input_tokens,
                        latency_ms=(perf_counter() - execution_started) * 1000,
                        error=str(exc),
                    )
                    codex_calls += self.resolution_executor.resolution_calls - before
                    task = self.store.get_task(task.id) or task
                    if task.attempt_count == attempt_before:
                        task.attempt_count += 1
                    task.last_error = str(exc)
                    self.store.save_task(task)
                    if task.attempt_count >= self.config.max_retries_per_task:
                        self._stop(task, StoppingReason.RETRY_EXHAUSTED, planner)
                        stop_reason = stop_reason or StoppingReason.RETRY_EXHAUSTED
                    continue
                codex_calls += self.resolution_executor.resolution_calls - before
                execution_ledger.record(
                    task,
                    planned_route=task.route or TaskRoute.RESOLVER,
                    actual_route=TaskRoute.RESOLVER,
                    worker=type(self.resolution_executor.resolver).__name__,
                    outcome=(
                        ExecutionOutcome.SUCCEEDED
                        if outcome.task.status == TaskStatus.DONE
                        else ExecutionOutcome.LOW_CONFIDENCE
                    ),
                    input_tokens=execution_input_tokens,
                    output_tokens=token_estimate(outcome.result.model_dump_json()),
                    latency_ms=(perf_counter() - execution_started) * 1000,
                    confidence=outcome.result.confidence,
                )
                task = outcome.task
                if task.status == TaskStatus.DONE:
                    self._propagate_completion(task)
                else:
                    if self.follow_up_executor is None:
                        self._mark_cluster_unresolved(task)
                        self._propagate_stopping(
                            task, StoppingReason.LOW_CONFIDENCE, planner
                        )
                        stop_reason = stop_reason or StoppingReason.LOW_CONFIDENCE
                        break
                    follow_ups = self._create_follow_ups(
                        task,
                        outcome.result.unresolved_questions,
                        planner,
                        execution_ledger,
                    )
                    if follow_ups:
                        task.status = TaskStatus.OPEN
                        task.stopping_reason = None
                        task.completed_at = None
                        self.store.save_task(task)
                        planner.record(
                            task,
                            PlanningAction.REPLANNED,
                            f"Resolution remained uncertain; added {len(follow_ups)} prioritized evidence task(s).",
                        )
                        self._enqueue(follow_ups, queue, queued)
                        self._enqueue([task], queue, queued)
                    elif task.attempt_count < self.config.max_retries_per_task:
                        task.status = TaskStatus.OPEN
                        task.stopping_reason = None
                        task.completed_at = None
                        self.store.save_task(task)
                        self._enqueue([task], queue, queued)
                    else:
                        self._stop(task, StoppingReason.RETRY_EXHAUSTED, planner)
                        stop_reason = stop_reason or StoppingReason.RETRY_EXHAUSTED
                break
            if task.status != TaskStatus.DONE:
                self._enqueue(self._children(task.id), queue, queued)

        root = self.store.get_task(root_task_id)
        assert root is not None
        if stop_reason is None and root.status == TaskStatus.DONE:
            stop_reason = StoppingReason.COMPLETED
        elif stop_reason is None:
            stop_reason = root.stopping_reason or StoppingReason.LOW_CONFIDENCE
        status = TaskStatus.DONE if stop_reason == StoppingReason.COMPLETED else TaskStatus.STOPPED
        planning_run = planner.finish(status, stop_reason)
        return PursuitResult(
            root_task_id=root_task_id,
            tasks=self._lineage(root_task_id),
            codex_calls=codex_calls,
            status=status,
            stopping_reason=stop_reason,
            planning_run=planning_run,
        )

    def _children(self, task_id: str) -> list[Task]:
        return [task for task in self.store.tasks() if task.parent_task_id == task_id]

    def _create_follow_ups(
        self,
        parent: Task,
        questions: list[str],
        planner: RecursivePlanner,
        execution_ledger: ExecutionLedger | None = None,
    ) -> list[Task]:
        gaps = [question.strip() for question in questions if question.strip()]
        if not gaps:
            claims = [
                claim
                for claim_id in parent.conflicting_claim_ids
                if (claim := self.store.get_claim(claim_id)) is not None
            ]
            stale = [claim for claim in claims if claim.validity_status != ClaimValidity.CURRENT]
            weak = [claim for claim in claims if claim.confidence < self.config.minimum_confidence]
            if stale:
                gaps.append(
                    "Refresh stale dependency evidence for "
                    f"'{parent.disputed_assertion_key}' from the current repository state."
                )
            if weak:
                gaps.append(
                    "Find stronger repository evidence for the weakly supported assertion "
                    f"'{parent.disputed_assertion_key}'."
                )
            if not gaps:
                gaps.append(
                    "Resolve the contradiction by finding repository evidence that determines "
                    f"'{parent.disputed_assertion_key}'."
                )
        existing = {child.fingerprint: child for child in self._children(parent.id)}
        created: list[Task] = []
        for gap in gaps:
            fingerprint = task_fingerprint(gap, parent.project_fingerprint)
            if fingerprint in existing:
                planner.note_duplicate_avoided(existing[fingerprint], existing[fingerprint].id)
                continue
            reusable = next(
                (
                    task
                    for task in self.store.tasks()
                    if task.fingerprint == fingerprint
                    and task.project_fingerprint == parent.project_fingerprint
                    and task.status == TaskStatus.DONE
                    and task.output_claim_id
                ),
                None,
            )
            child = Task(
                question=gap,
                fingerprint=fingerprint,
                project_fingerprint=parent.project_fingerprint,
                project_root=parent.project_root,
                kind=TaskKind.FOLLOW_UP,
                parent_task_id=parent.id,
                evidence_gap=gap,
                source_claim_ids=parent.conflicting_claim_ids,
                depth=parent.depth + 1,
                dependency_task_ids=[parent.id],
            )
            if reusable is not None:
                child.status = TaskStatus.DONE
                child.output_claim_id = reusable.output_claim_id
                child.reused_claim_id = reusable.output_claim_id
                child.reuse_type = "completed-investigation"
                child.completed_at = datetime.now(UTC)
            self.store.save_task(child)
            self.store.save_edge(
                GraphEdge(source=parent.id, relation=GraphRelation.SPAWNED, target=child.id)
            )
            created.append(child)
            existing[fingerprint] = child
            planner.assess(
                child,
                (
                    f"Reused completed investigation {reusable.id}."
                    if reusable is not None
                    else "Created from an unresolved question or evidence gap."
                ),
                action=(
                    PlanningAction.REUSED if reusable is not None else PlanningAction.CREATED
                ),
            )
            if reusable is not None and execution_ledger is not None:
                execution_ledger.record(
                    child,
                    planned_route=TaskRoute.MEMORY,
                    actual_route=TaskRoute.MEMORY,
                    worker="GraphMemory",
                    outcome=ExecutionOutcome.REUSED,
                    confidence=(
                        self.store.get_claim(reusable.output_claim_id).confidence
                        if reusable.output_claim_id
                        and self.store.get_claim(reusable.output_claim_id)
                        else None
                    ),
                    fallback_reason=f"Reused completed task {reusable.id}.",
                )
        return created

    def _completed_equivalent(self, task: Task) -> Task | None:
        return next(
            (
                candidate
                for candidate in self.store.tasks()
                if candidate.id != task.id
                and candidate.fingerprint == task.fingerprint
                and candidate.project_fingerprint == task.project_fingerprint
                and candidate.status == TaskStatus.DONE
                and candidate.output_claim_id
            ),
            None,
        )

    def _requeue_parent(self, child: Task, queue, queued: set[str]) -> None:
        if not child.parent_task_id:
            return
        parent = self.store.get_task(child.parent_task_id)
        if parent is not None:
            self._enqueue([parent], queue, queued)

    def _enqueue(self, children, queue, queued: set[str]) -> None:
        for child in children:
            if child.id not in queued:
                queue.append(child.id)
                queued.add(child.id)
        ordered = sorted(
            queue,
            key=lambda task_id: self._queue_priority(task_id),
            reverse=True,
        )
        queue.clear()
        queue.extend(ordered)

    def _queue_priority(self, task_id: str) -> float:
        task = self.store.get_task(task_id)
        if task is None:
            return -10000.0
        blocked = any(child.status != TaskStatus.DONE for child in self._children(task.id))
        return task.priority - (1000.0 if blocked else 0.0)

    def _has_cycle(self, task: Task) -> bool:
        seen_ids = {task.id}
        seen_fingerprints = {task.fingerprint}
        parent_id = task.parent_task_id
        while parent_id:
            if parent_id in seen_ids:
                return True
            parent = self.store.get_task(parent_id)
            if parent is None:
                return False
            if parent.fingerprint in seen_fingerprints:
                return True
            seen_ids.add(parent.id)
            seen_fingerprints.add(parent.fingerprint)
            parent_id = parent.parent_task_id
        return False

    def _propagate_completion(self, child: Task) -> None:
        parent_id = child.parent_task_id
        while parent_id:
            parent = self.store.get_task(parent_id)
            if parent is None:
                return
            if parent.kind == TaskKind.RESOLUTION:
                return
            siblings = self._children(parent.id)
            if not siblings or any(item.status != TaskStatus.DONE for item in siblings):
                return
            parent.status = TaskStatus.DONE
            parent.completed_at = datetime.now(UTC)
            parent.stopping_reason = StoppingReason.COMPLETED
            self.store.save_task(parent)
            parent_id = parent.parent_task_id

    def _stop(
        self, task: Task, reason: StoppingReason, planner: RecursivePlanner | None = None
    ) -> None:
        task.status = TaskStatus.STOPPED
        task.stopping_reason = reason
        task.completed_at = datetime.now(UTC)
        self.store.save_task(task)
        if planner is not None:
            planner.record(
                task,
                PlanningAction.STOPPED,
                f"Hard budget or terminal policy stopped this task: {reason.value}.",
                stopping_reason=reason,
            )
        self._mark_cluster_unresolved(task)
        self._propagate_stopping(task, reason, planner)

    def _mark_cluster_unresolved(self, task: Task) -> None:
        if not task.conflict_cluster_id:
            return
        cluster = self.store.get_conflict_cluster(task.conflict_cluster_id)
        if cluster is not None and cluster.status != ClusterStatus.RESOLVED:
            cluster.status = ClusterStatus.UNRESOLVED
            self.store.save_conflict_cluster(cluster)

    def _propagate_stopping(
        self,
        child: Task,
        reason: StoppingReason,
        planner: RecursivePlanner | None = None,
    ) -> None:
        parent_id = child.parent_task_id
        seen = {child.id}
        while parent_id and parent_id not in seen:
            parent = self.store.get_task(parent_id)
            if parent is None or parent.status == TaskStatus.DONE:
                return
            seen.add(parent.id)
            parent.status = TaskStatus.STOPPED
            parent.stopping_reason = reason
            parent.completed_at = datetime.now(UTC)
            self.store.save_task(parent)
            if planner is not None:
                planner.record(
                    parent,
                    PlanningAction.STOPPED,
                    f"Dependency {child.id} stopped with {reason.value}.",
                    stopping_reason=reason,
                )
            parent_id = parent.parent_task_id

    def _lineage(self, root_task_id: str) -> list[Task]:
        tasks = {task.id: task for task in self.store.tasks()}
        included: list[Task] = []
        for task in tasks.values():
            current: Task | None = task
            seen: set[str] = set()
            while current and current.id not in seen:
                if current.id == root_task_id:
                    included.append(task)
                    break
                seen.add(current.id)
                current = tasks.get(current.parent_task_id or "")
        return sorted(included, key=lambda task: (task.depth, task.created_at, task.id))
