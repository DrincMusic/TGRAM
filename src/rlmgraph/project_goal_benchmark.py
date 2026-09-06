from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Protocol

from .model_call_ledger import ModelCallLedger, model_call_scope
from .project_action_memory import ProjectActionMemory
from .project_cold_archive import ProjectColdArchive
from .project_context import ProjectContextCompiler
from .project_task_graph import ProjectTaskGraph
from .repair_outcome_memory import RepairOutcomeMemoryStore


class ProjectWorker(Protocol):
    def implement(self, request: str, evidence: list, sandbox_root: Path): ...


class ProjectGoalBenchmarkStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS project_goal_benchmarks "
                "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save(self, payload: dict) -> None:
        import sqlite3

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO project_goal_benchmarks VALUES (?, ?, ?)",
                (payload["id"], payload["created_at"], json.dumps(payload)),
            )

    def latest(self) -> dict | None:
        import sqlite3

        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM project_goal_benchmarks ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else None


class PairedProjectGoalBenchmark:
    workers_per_milestone: ClassVar[int] = 1
    arm_execution_order: tuple[str, str] = ("baseline", "rlmgraph")
    repair_max_attempts: ClassVar[int] = max(
        0, int(os.environ.get("RLMGRAPH_REPAIR_MAX_ATTEMPTS", "2"))
    )
    continue_previous_project: ClassVar[bool] = False
    milestone_limit: ClassVar[int] = int(
        os.environ.get("RLMGRAPH_BENCHMARK_MILESTONE_LIMIT", "100")
    )
    arm_mode: ClassVar[str] = os.environ.get(
        "RLMGRAPH_BENCHMARK_ARM", "paired"
    ).strip().casefold()
    legacy_goal: ClassVar[str] = (
        "Evolve the transaction ledger into a durable, serializable, queryable ledger while "
        "preserving backward compatibility with its existing record(amount) and total() API."
    )
    legacy_milestones: ClassVar[list[str]] = [
        "Preserve record(amount) returning a stable positive integer transaction ID.",
        "Preserve total() and return the net total of non-refunded transactions.",
        "Reject zero transaction amounts with ValueError.",
        "Reject negative transaction amounts with ValueError.",
        "Reject non-finite transaction amounts such as NaN and infinity with ValueError.",
        "Support record(amount, category='general', note='') without breaking old callers.",
        "Normalize non-empty categories case-insensitively and reject blank categories.",
        "Add refund(transaction_id) and return a stable positive integer refund ID.",
        "Reject refunds for unknown transaction IDs with ValueError.",
        "Reject duplicate refunds with ValueError.",
        "Add get(transaction_id) returning amount, category, note, and ACTIVE or REFUNDED status.",
        "Add transactions(include_refunded=True) in deterministic transaction-ID order.",
        "Add category_total(category) using only active transactions.",
        "Add category_summary() mapping normalized categories to active net totals.",
        "Add search(query) performing case-insensitive note search in deterministic order.",
        "Add summary() with transaction_count, refund_count, active_count, and net_total.",
        "Support len(ledger) as the number of original transactions.",
        "Add export_data() and TransactionLedger.from_data(data) round-trip support.",
        "Add to_json() and TransactionLedger.from_json(payload) round-trip support.",
        "Document every public operation in README.md and preserve all earlier requirements.",
        "Allow record(..., tags=()) and normalize tags to unique lowercase strings.",
        "Reject blank tags with ValueError.",
        "Reject a scalar string passed as tags with ValueError.",
        "Expose normalized tags from get(transaction_id).",
        "Preserve tags in transactions() results.",
        "Add transactions_with_tag(tag) in deterministic transaction-ID order.",
        "Make tag lookup case-insensitive.",
        "Add tag_summary() mapping tags to active transaction counts.",
        "Exclude refunded transactions from tag_summary().",
        "Preserve tags through data and JSON round trips.",
        "Allow record(..., metadata=None) with a JSON-object metadata value.",
        "Reject non-dictionary metadata with ValueError.",
        "Return defensive metadata copies from get().",
        "Preserve metadata in transactions() results.",
        "Add update_metadata(transaction_id, updates) and return the updated record.",
        "Reject update_metadata for unknown IDs with ValueError.",
        "Reject non-dictionary metadata updates with ValueError.",
        "Ensure metadata updates do not alter amount, category, note, or tags.",
        "Preserve metadata through data and JSON round trips.",
        "Keep caller-owned metadata mutations from changing stored records.",
        "Allow record(..., currency='USD') using uppercase three-letter currency codes.",
        "Normalize lowercase currency codes to uppercase.",
        "Reject blank currency codes with ValueError.",
        "Reject currency codes that are not exactly three ASCII letters.",
        "Expose currency from get() and transactions().",
        "Add currency_total(currency) over active transactions.",
        "Make currency_total lookup case-insensitive.",
        "Add currency_summary() with deterministic currency keys.",
        "Exclude refunded transactions from currency totals.",
        "Preserve currencies through data and JSON round trips.",
        "Add update_note(transaction_id, note) returning the updated record.",
        "Reject update_note for unknown IDs with ValueError.",
        "Make updated notes immediately searchable.",
        "Add update_category(transaction_id, category) returning the updated record.",
        "Normalize updated categories case-insensitively.",
        "Reject blank updated categories with ValueError.",
        "Reject update_category for unknown IDs with ValueError.",
        "Reflect category updates immediately in category totals.",
        "Preserve note and category updates through serialization.",
        "Do not allow update operations to change transaction IDs.",
        "Extend transactions() with category=None filtering.",
        "Extend transactions() with currency=None filtering.",
        "Extend transactions() with tag=None filtering.",
        "Extend transactions() with min_amount=None filtering.",
        "Extend transactions() with max_amount=None filtering.",
        "Reject non-finite min_amount and max_amount filters with ValueError.",
        "Reject min_amount greater than max_amount with ValueError.",
        "Allow filters to be composed in one transactions() call.",
        "Keep filtered transactions in deterministic transaction-ID order.",
        "Honor include_refunded=False alongside every filter.",
        "Extend transactions() with sort_by='id' supporting id, amount, category, and note.",
        "Reject unsupported sort fields with ValueError.",
        "Extend transactions() with descending=False.",
        "Use transaction ID as the deterministic tie breaker for sorting.",
        "Extend transactions() with offset=0.",
        "Reject negative offsets with ValueError.",
        "Extend transactions() with limit=None.",
        "Reject negative limits with ValueError.",
        "Apply filtering before sorting and pagination.",
        "Return an empty list when offset exceeds the result size.",
        "Add statistics() with count, total, minimum, maximum, and average for active transactions.",
        "Return zero count and total plus None min/max/average for an empty ledger.",
        "Allow statistics(category=...) filtering.",
        "Allow statistics(currency=...) filtering.",
        "Make statistics filters case-insensitive.",
        "Exclude refunded transactions from statistics.",
        "Add largest_transaction() returning the largest active transaction.",
        "Return None from largest_transaction() when no active transactions exist.",
        "Resolve largest-transaction ties by lowest transaction ID.",
        "Keep analytics correct after category and note updates.",
        "Add audit_log() returning immutable-style event dictionaries in event order.",
        "Record a RECORD audit event for every successful transaction.",
        "Record a REFUND audit event for every successful refund.",
        "Record UPDATE_NOTE, UPDATE_CATEGORY, and UPDATE_METADATA audit events.",
        "Do not append audit events for rejected operations.",
        "Give audit events stable positive sequential event IDs.",
        "Return defensive copies from audit_log().",
        "Preserve the audit log through data and JSON round trips.",
        "Continue audit event IDs correctly after deserialization.",
        "Document tags, metadata, currency, updates, filters, sorting, pagination, analytics, and audit logging.",
    ]
    goal: ClassVar[str] = (
        "Build a durable dependency-aware project board from the provided minimal seed, with task "
        "lifecycle management, scheduling, querying, analytics, serialization, and audit history."
    )
    milestones: ClassVar[list[str]] = [
        "Create ProjectBoard and allow an optional non-blank board name.",
        "Reject blank board names with ValueError.",
        "Add create_task(title) returning stable positive integer IDs.",
        "Reject blank task titles with ValueError.",
        "Preserve task insertion order independently of later updates.",
        "Add get_task(task_id) returning a defensive task dictionary.",
        "Reject unknown task IDs in get_task with ValueError.",
        "Add len(board) as the number of tasks.",
        "Add task_ids() in ascending stable-ID order.",
        "Ensure rejected task creation does not consume an ID.",
        "Support descriptions with an empty default.",
        "Add update_title(task_id, title) with blank-title validation.",
        "Add update_description(task_id, description).",
        "Make update methods return the updated defensive task dictionary.",
        "Reject updates for unknown task IDs with ValueError.",
        "Support normalized LOW, MEDIUM, HIGH, and CRITICAL priorities.",
        "Default task priority to MEDIUM.",
        "Reject unsupported priorities with ValueError.",
        "Add update_priority(task_id, priority).",
        "Preserve title, description, and priority through later lifecycle changes.",
        "Default every task status to TODO.",
        "Support TODO, IN_PROGRESS, BLOCKED, and DONE statuses.",
        "Reject unsupported statuses with ValueError.",
        "Add set_status(task_id, status).",
        "Add start_task(task_id) as an IN_PROGRESS transition.",
        "Add block_task(task_id) as a BLOCKED transition.",
        "Add reopen_task(task_id) as a TODO transition.",
        "Add complete_task(task_id) as a DONE transition.",
        "Reject completing an already completed task with ValueError.",
        "Track completed_count correctly across reopen and recomplete transitions.",
        "Support normalized unique lowercase task tags while preserving first-seen order.",
        "Reject scalar strings passed as a tag collection.",
        "Reject blank tags with ValueError.",
        "Add add_tag(task_id, tag) idempotently.",
        "Add remove_tag(task_id, tag) idempotently.",
        "Expose tags as a defensive list.",
        "Add tasks_with_tag(tag) using case-insensitive lookup.",
        "Keep tag query results in stable task-ID order.",
        "Add tag_summary() mapping tags to task counts.",
        "Reflect tag additions and removals immediately in tag_summary().",
        "Support optional non-blank assignees.",
        "Normalize assignee surrounding whitespace.",
        "Reject blank assignee strings with ValueError.",
        "Add assign(task_id, assignee).",
        "Add unassign(task_id).",
        "Add tasks_for_assignee(assignee) with case-insensitive matching.",
        "Keep assignee query results in stable task-ID order.",
        "Add assignee_summary() mapping assignees to task counts.",
        "Represent unassigned tasks separately in board summary counts.",
        "Preserve assignee state through task lifecycle changes.",
        "Support optional positive finite estimate_hours.",
        "Reject zero, negative, NaN, and infinite estimates with ValueError.",
        "Add set_estimate(task_id, hours).",
        "Add clear_estimate(task_id).",
        "Add estimated_hours(status=None) aggregation.",
        "Make estimate status filtering case-insensitive.",
        "Add remaining_hours() excluding DONE tasks.",
        "Add completed_hours() including only DONE tasks.",
        "Return zero for hour aggregations when no tasks have estimates.",
        "Support optional ISO YYYY-MM-DD due dates.",
        "Reject invalid calendar dates and non-ISO formats with ValueError.",
        "Add set_due_date(task_id, due_date).",
        "Add clear_due_date(task_id).",
        "Add due_on(date) in stable task-ID order.",
        "Add due_before(date, include_done=False).",
        "Exclude completed tasks from due_before by default.",
        "Allow completed tasks in due_before when include_done=True.",
        "Add overdue(as_of) as an alias for incomplete tasks due before a date.",
        "Preserve due dates through unrelated task updates.",
        "Add dependency links between existing tasks.",
        "Reject self-dependencies with ValueError.",
        "Reject unknown dependency IDs with ValueError.",
        "Make duplicate dependency additions idempotent.",
        "Reject direct and transitive dependency cycles with ValueError.",
        "Add remove_dependency(task_id, dependency_id) idempotently.",
        "Expose dependency IDs in deterministic order.",
        "Add blockers(task_id) returning unfinished dependency tasks.",
        "Reject completing a task with unfinished dependencies.",
        "Allow completion after all dependencies are DONE.",
        "Add ready_tasks() for TODO tasks with no unfinished dependencies.",
        "Keep ready_tasks in priority-descending then ID order.",
        "Add critical_path() returning task IDs for a deterministic longest dependency chain.",
        "Resolve equal critical paths by lexicographically smallest ID sequence.",
        "Keep dependency state intact through serialization.",
        "Add tasks() with optional status, priority, tag, and assignee filters.",
        "Allow task filters to compose.",
        "Add case-insensitive title and description search returning task dictionaries in ID order.",
        "Add sorting by id, title, priority, status, due_date, and estimate_hours, with priority ascending LOW to CRITICAL.",
        "Reject unsupported sort fields with ValueError.",
        "Support descending sort with task ID as deterministic tie breaker.",
        "Support non-negative offset and limit pagination.",
        "Reject negative offset and limit with ValueError.",
        "Apply filtering before sorting and pagination.",
        "Add summary() with task_count, status_counts, priority_counts, assigned_count, unassigned_count, estimated_hours, remaining_hours, and completed_hours.",
        "Add completion_percentage() rounded to one decimal place.",
        "Add export_data() and ProjectBoard.from_data(data) round-trip support.",
        "Add to_json() and ProjectBoard.from_json(payload) deterministic round-trip support.",
        "Add audit_log() with stable sequential IDs, uppercase type names, and defensive event dictionaries.",
        "Audit successful creates, updates, lifecycle transitions, assignments, and dependency changes.",
        "Do not audit rejected operations and document every public feature in README.md.",
    ]

    def __init__(
        self, worker: ProjectWorker, ledger: ModelCallLedger,
        store: ProjectGoalBenchmarkStore, runs_root: Path,
    ) -> None:
        self.worker = worker
        self.ledger = ledger
        self.store = store
        self.runs_root = runs_root

    def run(self) -> dict:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        previous_result = self.store.latest() if self.continue_previous_project else None
        root = self.runs_root / run_id
        seed = root / "seed"
        baseline_root = root / "baseline"
        rlm_root = root / "rlmgraph"
        self._create_seed(seed, previous_result)
        shutil.copytree(seed, baseline_root)
        shutil.copytree(seed, rlm_root)
        baseline_enabled = self.arm_mode != "rlmgraph"
        baseline_steps: list[dict] = []
        rlm_steps: list[dict] = []
        if baseline_enabled:
            order = tuple(self.arm_execution_order)
            if sorted(order) != ["baseline", "rlmgraph"]:
                raise ValueError("arm_execution_order must contain baseline and rlmgraph once each.")
            for selected_arm in order:
                if selected_arm == "baseline":
                    baseline_steps = self._run_arm(
                        run_id, "BASELINE_PROJECT", baseline_root, True, previous_result
                    )
                else:
                    rlm_steps = self._run_arm(
                        run_id, "RLMGRAPH_PROJECT", rlm_root, False, previous_result
                    )
        else:
            rlm_steps = self._run_arm(
                run_id, "RLMGRAPH_PROJECT", rlm_root, False, previous_result
            )
        active_milestones = self._active_milestones()
        baseline_validation = (
            dict(list(self._validate(baseline_root).items())[: len(active_milestones)])
            if baseline_enabled else {}
        )
        rlm_validation = dict(
            list(self._validate(rlm_root).items())[: len(active_milestones)]
        )
        task_graph = ProjectTaskGraph(root / "rlmgraph-task-state.db")
        cold_archive = ProjectColdArchive(root / "rlmgraph-cold-archive.db")
        for task_id, (criterion, passed) in enumerate(rlm_validation.items(), 1):
            if passed:
                task_graph.reconcile_complete(
                    task_id,
                    evidence={
                        "kind": "final_validation_reconciliation",
                        "criterion": criterion,
                        "passed": True,
                    },
                )
        baseline_usage = self.ledger.summary(
            benchmark_run_id=run_id, benchmark_arm="BASELINE_PROJECT"
        )
        rlm_usage = self.ledger.summary(
            benchmark_run_id=run_id, benchmark_arm="RLMGRAPH_PROJECT"
        )
        baseline_tokens = int(baseline_usage["metered_total_tokens"])
        rlm_tokens = int(rlm_usage["metered_total_tokens"])
        baseline_passed = sum(baseline_validation.values())
        rlm_passed = sum(rlm_validation.values())
        task_snapshot = task_graph.snapshot()
        repaired_tasks = sum(
            1 for task in task_snapshot
            if any(
                item.get("kind") == "autonomous_repair" and item.get("passed") is True
                for item in task.get("evidence", []) if isinstance(item, dict)
            )
        )
        repair_steps = [
            step for step in rlm_steps if step.get("phase") == "REPAIR"
        ]
        result = {
            "id": run_id, "created_at": created_at, "status": "COMPLETED",
            "benchmark_mode": "PAIRED" if baseline_enabled else "RLMGRAPH_ONLY",
            "arm_execution_order": list(self.arm_execution_order) if baseline_enabled else ["rlmgraph"],
            "goal": self.goal, "milestones": active_milestones,
            "baseline": {
                "status": "COMPLETED" if baseline_enabled else "SKIPPED",
                **baseline_usage, "steps": baseline_steps,
                "validation": baseline_validation, "criteria_passed": baseline_passed,
                "tokens_per_criterion": round(baseline_tokens / baseline_passed, 1)
                if baseline_passed else None,
            },
            "rlmgraph": {
                "status": "COMPLETED",
                **rlm_usage, "steps": rlm_steps,
                "validation": rlm_validation, "criteria_passed": rlm_passed,
                "tokens_per_criterion": round(rlm_tokens / rlm_passed, 1)
                if rlm_passed else None,
            },
            "baseline_tokens": baseline_tokens, "rlmgraph_tokens": rlm_tokens,
            "criteria_total": len(rlm_validation),
            "tokens_saved": baseline_tokens - rlm_tokens if baseline_enabled else 0,
            "savings_percent": (
                round((baseline_tokens - rlm_tokens) / baseline_tokens * 100, 1)
                if baseline_tokens else 0.0
            ),
            "quality_preserved": (
                rlm_passed >= baseline_passed if baseline_enabled
                else rlm_passed == len(rlm_validation)
            ),
            "project_roots": {"baseline": str(baseline_root), "rlmgraph": str(rlm_root)},
            "continued_from_run_id": previous_result.get("id") if previous_result else None,
            "memory_continuity": {
                "baseline": "persistent_prior_project_context",
                "rlmgraph": "durable_compact_project_memory",
                "rlmgraph_workers_per_milestone": self.workers_per_milestone,
                "rlmgraph_worker_context": "fresh_bounded_context_per_pass",
            },
            "rlmgraph_task_control": {
                "progress": task_graph.progress(),
                "tasks": task_snapshot,
                "state_path": str(task_graph.path),
            },
            "rlmgraph_autonomous_repair": {
                "enabled": self.repair_max_attempts > 0,
                "max_attempts_per_failed_task": self.repair_max_attempts,
                "repair_model_calls": len(repair_steps),
                "repaired_tasks": repaired_tasks,
                "blocked_tasks": sum(
                    1 for task in task_snapshot if task.get("status") == "BLOCKED"
                ),
                "requires_deterministic_failure_evidence": True,
                "full_regression_validation_after_each_repair": True,
            },
            "rlmgraph_archive": {
                "event_count": cold_archive.count(),
                "state_path": str(cold_archive.path),
                "implicit_context_access": False,
            },
        }
        self.store.save(result)
        return result

    def _run_arm(
        self, run_id: str, arm: str, root: Path, persistent_transcript: bool,
        previous_result: dict | None,
    ) -> list[dict]:
        if not persistent_transcript:
            return self._run_graph_managed_arm(run_id, arm, root, previous_result)
        adapter = getattr(self.worker, "adapter", None)
        if adapter is None or not hasattr(adapter, "persistent_project_turn"):
            raise RuntimeError("The controlled baseline requires a persistent Codex session.")
        steps: list[dict] = []
        completed: list[str] = []
        prior_context = self._baseline_prior_context(previous_result)
        session_id: str | None = None
        try:
            for index, milestone in enumerate(self._active_milestones(), 1):
                request = (
                    "You are the persistent Codex GPT-5.4 control session. Work directly in the current "
                    "project copy. Complete exactly the current task, preserve requirements established "
                    "in earlier turns, run a focused check, and do not work ahead. Return the required "
                    "structured result after editing.\n\n"
                    f"PROJECT GOAL:\n{self.goal}\n\nCURRENT TASK {index}:\n{milestone}\n\n"
                    f"COMPLETED TASKS:\n{json.dumps(completed)}\n\n{prior_context}"
                )
                with model_call_scope(
                    benchmark_run_id=run_id, benchmark_arm=arm,
                    milestone_index=str(index), milestone_worker="1",
                    milestone_phase="IMPLEMENT",
                ):
                    outcome, session_id = adapter.persistent_project_turn(
                        request, root, session_id
                    )
                completed.append(milestone)
                steps.append({
                    "execution": "full_context_task_worker", "milestone_index": index,
                    "milestone": milestone, "rationale": outcome.rationale,
                    "files_changed": outcome.files_changed, "confidence": outcome.confidence,
                    "session_id": session_id,
                })
        finally:
            forget = getattr(adapter, "forget_persistent_session", None)
            if callable(forget):
                forget(session_id)
        return steps

    def _run_graph_managed_arm(
        self, run_id: str, arm: str, root: Path, previous_result: dict | None,
    ) -> list[dict]:
        """Advance durable milestones with fresh, bounded workers and independent review."""
        action_memory = ProjectActionMemory(root.parent / "rlmgraph-action-memory.jsonl")
        repair_memory = RepairOutcomeMemoryStore(
            root.parent / "rlmgraph-repair-memory.jsonl"
        )
        task_graph = ProjectTaskGraph(root.parent / "rlmgraph-task-state.db")
        cold_archive = ProjectColdArchive(root.parent / "rlmgraph-cold-archive.db")
        context_compiler = ProjectContextCompiler(char_budget=5000, memory_char_budget=1800)
        task_graph.initialize([
            {
                "task_id": index,
                "objective": milestone,
                "acceptance": f"Independently verify this contract: {milestone}",
                "dependencies": [],
                "priority": len(self._active_milestones()) - index,
            }
            for index, milestone in enumerate(self._active_milestones(), 1)
        ])
        task_graph.recover_interrupted()
        if previous_result and not action_memory.records():
            for step in previous_result.get("rlmgraph", {}).get("steps", []):
                if not isinstance(step, dict):
                    continue
                action_memory.remember(
                    milestone_index=int(step.get("milestone_index", 0)),
                    milestone=str(step.get("milestone", previous_result.get("goal", ""))),
                    phase=str(step.get("phase", "PRIOR_ITERATION")),
                    rationale=str(step.get("rationale", "Prior project action.")),
                    files_changed=list(step.get("files_changed", [])),
                    confidence=float(step.get("confidence", 0.5)),
                )
        steps: list[dict] = []
        while (lease := task_graph.claim_next(max_attempts=1)) is not None:
            milestone_index, milestone = lease.task_id, lease.objective
            implementation = self._execute_project_worker(
                run_id=run_id, arm=arm, root=root, lease=lease, milestone=milestone,
                phase="IMPLEMENT", worker_index=1,
                action_memory=action_memory, cold_archive=cold_archive,
                context_compiler=context_compiler,
            )
            steps.append(implementation["step"])
            attempt_records = [implementation["memory_ref"]]
            task_graph.begin_verification(
                lease, result=implementation["result"], memory_refs=attempt_records,
            )
            validation_items = list(self._validate(root).items())
            criterion_name, passed = validation_items[milestone_index - 1]
            validation_archive_id = cold_archive.append(
                kind="deterministic_validation",
                payload={"criterion": criterion_name, "passed": passed},
                task_id=lease.task_id, attempt=lease.attempt, phase="VERIFY",
            )
            evidence = [{
                "kind": "deterministic_acceptance",
                "criterion": criterion_name,
                "passed": passed,
                "archive_ref": validation_archive_id,
                "implementation": implementation["result"],
            }]
            if not passed:
                previously_passing = {
                    name for name, ok in validation_items[: milestone_index - 1] if ok
                }
                for repair_attempt in range(1, self.repair_max_attempts + 1):
                    repair_objective = (
                        f"{milestone}\n\nAUTONOMOUS REPAIR EVIDENCE:\n"
                        f"The deterministic criterion `{criterion_name}` failed after the prior "
                        f"implementation. Repair attempt {repair_attempt} of "
                        f"{self.repair_max_attempts}. Diagnose the live implementation, make the "
                        "smallest corrective edit, and preserve every previously passing criterion."
                    )
                    repair = self._execute_project_worker(
                        run_id=run_id, arm=arm, root=root, lease=lease,
                        milestone=repair_objective, phase="REPAIR",
                        worker_index=repair_attempt, action_memory=action_memory,
                        cold_archive=cold_archive, context_compiler=context_compiler,
                    )
                    steps.append(repair["step"])
                    attempt_records.append(repair["memory_ref"])
                    repaired_validation = dict(self._validate(root))
                    repaired_target = bool(repaired_validation.get(criterion_name, False))
                    regressions = sorted(
                        name for name in previously_passing
                        if not repaired_validation.get(name, False)
                    )
                    repair_passed = repaired_target and not regressions
                    repair_archive_id = cold_archive.append(
                        kind="autonomous_repair_validation",
                        payload={
                            "criterion": criterion_name,
                            "attempt": repair_attempt,
                            "target_passed": repaired_target,
                            "regressions": regressions,
                            "passed": repair_passed,
                        },
                        task_id=lease.task_id, attempt=lease.attempt, phase="REPAIR_VERIFY",
                    )
                    evidence.append({
                        "kind": "autonomous_repair",
                        "criterion": criterion_name,
                        "repair_attempt": repair_attempt,
                        "passed": repair_passed,
                        "target_passed": repaired_target,
                        "regressions": regressions,
                        "archive_ref": repair_archive_id,
                        "repair": repair["result"],
                    })
                    repair_memory.remember(
                        task_id=lease.task_id, criterion=criterion_name,
                        diagnosis=repair["step"]["rationale"],
                        attempted_change=repair["step"]["rationale"],
                        attempt=repair_attempt, target_passed=repaired_target,
                        regressions=regressions,
                        action_memory_id=repair["memory_ref"],
                        evidence_refs=[
                            validation_archive_id, repair["result"]["archive_ref"],
                            repair_archive_id,
                        ],
                    )
                    if repair_passed:
                        passed = True
                        break
            if passed:
                task_graph.complete(lease, evidence=evidence, memory_refs=attempt_records)
            else:
                task_graph.fail(
                    lease,
                    reason=f"Deterministic criterion {criterion_name} failed.",
                    evidence=evidence,
                    memory_refs=attempt_records,
                )
                task_graph.block_exhausted(max_attempts=1)
        return steps

    def _execute_project_worker(
        self, *, run_id: str, arm: str, root: Path, lease, milestone: str,
        phase: str, worker_index: int,
        action_memory: ProjectActionMemory, cold_archive: ProjectColdArchive,
        context_compiler: ProjectContextCompiler,
    ) -> dict:
        recalled = action_memory.retrieve(
            f"{milestone} {lease.prior_failure} {phase}",
            current_milestone=lease.task_id,
        )
        compiled = context_compiler.compile(
            lease=lease, project_intent=self.goal, phase=phase, memories=recalled,
            pass_index=1, pass_count=1,
        )
        request_archive_id = cold_archive.append(
            kind="worker_request",
            payload={"prompt": compiled.prompt, "recalled_memory": recalled},
            task_id=lease.task_id, attempt=lease.attempt, phase=phase,
        )
        with model_call_scope(
            benchmark_run_id=run_id, benchmark_arm=arm,
            milestone_index=str(lease.task_id), milestone_worker=str(worker_index),
            milestone_phase=phase,
        ):
            outcome = self.worker.implement(compiled.prompt, [], root)
        outcome_archive_id = cold_archive.append(
            kind="worker_result",
            payload={
                "rationale": outcome.rationale, "files_changed": outcome.files_changed,
                "confidence": outcome.confidence,
            },
            task_id=lease.task_id, attempt=lease.attempt, phase=phase,
        )
        memory_record = action_memory.remember(
            milestone_index=lease.task_id, milestone=milestone, phase=phase,
            rationale=outcome.rationale, files_changed=outcome.files_changed,
            confidence=outcome.confidence, archive_ref=outcome_archive_id,
        )
        result = {
            "phase": phase, "archive_ref": outcome_archive_id,
            "memory_ref": memory_record.id, "confidence": outcome.confidence,
        }
        return {
            "result": result,
            "memory_ref": memory_record.id,
            "step": {
                "execution": "bounded_milestone_worker", "milestone_index": lease.task_id,
                "milestone": milestone, "worker_index": worker_index, "phase": phase,
                "rationale": " ".join(outcome.rationale.split())[:280],
                "files_changed": outcome.files_changed, "confidence": outcome.confidence,
                "memory_record_id": memory_record.id,
                "recalled_memory_count": len(recalled), "attempt": lease.attempt,
                "request_archive_id": request_archive_id,
                "result_archive_id": outcome_archive_id,
                "compiled_context_characters": compiled.characters,
                "compiled_context_estimated_tokens": compiled.estimated_tokens,
            },
        }

    def _active_milestones(self) -> list[str]:
        limit = max(1, min(len(self.milestones), int(self.milestone_limit)))
        return self.milestones[:limit]

    @staticmethod
    def _baseline_prior_context(previous: dict | None) -> str:
        if not previous:
            return "PRIOR PROJECT CONTEXT: This is the first iteration."
        baseline = previous.get("baseline", {})
        return (
            "PRIOR PERSISTENT PROJECT CONTEXT:\n"
            f"Previous run: {previous.get('id')}\n"
            f"Previous goal: {previous.get('goal')}\n"
            f"Previous requirements: {json.dumps(previous.get('milestones', []))}\n"
            f"Previous worker outcome: {json.dumps(baseline.get('steps', []))}\n"
            f"Previous validation: {json.dumps(baseline.get('validation', {}))}"
        )

    @staticmethod
    def _durable_project_memory(previous: dict | None) -> str:
        if not previous:
            return json.dumps({"lineage": [], "known_state": "first iteration"})
        rlm = previous.get("rlmgraph", {})
        memory = {
            "lineage": [previous.get("id")],
            "prior_goal": previous.get("goal"),
            "requirements_completed": [
                requirement
                for requirement, passed in zip(
                    previous.get("milestones", []),
                    rlm.get("validation", {}).values(), strict=False,
                )
                if passed
            ],
            "validation": rlm.get("validation", {}),
            "implementation_outcome": rlm.get("steps", []),
            "quality_preserved": previous.get("quality_preserved"),
            "instruction": (
                "Treat these verified facts as durable memory. Preserve them while extending "
                "the current project; inspect files whenever memory and live evidence disagree."
            ),
        }
        return json.dumps(memory, sort_keys=True)

    def _create_seed(self, root: Path, previous: dict | None) -> None:
        if previous:
            previous_root = Path(previous.get("project_roots", {}).get("rlmgraph", ""))
            if previous_root.is_dir():
                shutil.copytree(previous_root, root)
                return
        root.mkdir(parents=True)
        (root / "taskboard.py").write_text(
            "class ProjectBoard:\n"
            "    def __init__(self, name='Project'):\n"
            "        self.name = name\n"
            "        self._tasks = []\n\n"
            "    def create_task(self, title):\n"
            "        self._tasks.append({'id': len(self._tasks) + 1, 'title': title})\n"
            "        return len(self._tasks)\n\n"
            "    def __len__(self):\n"
            "        return len(self._tasks)\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text("# Project Board\n", encoding="utf-8")

    @staticmethod
    def _source_snapshot(root: Path) -> str:
        return "\n\n".join(
            f"FILE {path.name}\n{path.read_text(encoding='utf-8', errors='replace')}"
            for path in sorted(root.iterdir()) if path.is_file()
        )

    @staticmethod
    def _validate(root: Path) -> dict[str, bool]:
        return PairedProjectGoalBenchmark._validate_taskboard(root)

    @staticmethod
    def _validate_legacy_ledger(root: Path) -> dict[str, bool]:
        script = r'''
import json, math, sys
sys.path.insert(0, sys.argv[1])
results = {}
try:
    from ledger import TransactionLedger
except Exception:
    TransactionLedger = None

def check(name, fn):
    try: results[name] = bool(fn())
    except Exception: results[name] = False

def raises_value(fn):
    try: fn()
    except ValueError: return True
    except Exception: return False
    return False

check("construct", lambda: TransactionLedger is not None and TransactionLedger() is not None)
l = TransactionLedger() if TransactionLedger else None
check("stable_id", lambda: isinstance(l.record(10), int) and len(l) == 1)
check("backward_total", lambda: l.total() == 10)
check("reject_zero", lambda: raises_value(lambda: l.record(0)))
check("reject_negative", lambda: raises_value(lambda: l.record(-1)))
check("reject_nan", lambda: raises_value(lambda: l.record(float("nan"))))
check("reject_infinity", lambda: raises_value(lambda: l.record(float("inf"))))
check("extended_record", lambda: isinstance(l.record(5, category="Food", note="Team lunch"), int))
check("category_normalization", lambda: l.get(2)["category"] == "food")
check("reject_blank_category", lambda: raises_value(lambda: l.record(1, category=" ")))
check("refund", lambda: isinstance(l.refund(1), int) and l.total() == 5)
check("unknown_refund", lambda: raises_value(lambda: l.refund(999)))
check("duplicate_refund", lambda: raises_value(lambda: l.refund(1)))
check("get_status", lambda: l.get(1)["status"] == "REFUNDED" and l.get(2)["status"] == "ACTIVE")
check("ordered_transactions", lambda: [x["id"] for x in l.transactions()] == [1, 2])
check("category_queries", lambda: l.category_total("FOOD") == 5 and l.category_summary()["food"] == 5)
check("note_search", lambda: [x["id"] for x in l.search("LUNCH")] == [2])
check("summary", lambda: l.summary() == {"transaction_count": 2, "refund_count": 1, "active_count": 1, "net_total": 5})
check("data_roundtrip", lambda: TransactionLedger.from_data(l.export_data()).summary() == l.summary())
check("json_and_docs", lambda: TransactionLedger.from_json(l.to_json()).summary() == l.summary() and all(word in open(sys.argv[1]+"/README.md", encoding="utf-8").read().casefold() for word in ("refund", "summary", "json", "category", "search")))

def rich():
    x = TransactionLedger()
    x.record(10, category="Food", note="Team lunch", tags=["Team", "meal", "TEAM"], metadata={"source": "card"}, currency="usd")
    x.record(20, category="Travel", note="Airport taxi", tags=["team", "trip"], metadata={"source": "cash"}, currency="eur")
    x.record(30, category="Food", note="Client dinner", tags=["client"], metadata={}, currency="USD")
    return x

def mutates_metadata_copy():
    x = rich(); value = x.get(1); value["metadata"]["source"] = "changed"
    return x.get(1)["metadata"]["source"] == "card"

def caller_metadata_copy():
    metadata = {"nested": {"value": 1}}; x = TransactionLedger()
    x.record(1, metadata=metadata); metadata["nested"]["value"] = 2
    return x.get(1)["metadata"]["nested"]["value"] == 1

def rejected_without_audit(action):
    x = rich(); before = len(x.audit_log())
    try: action(x)
    except ValueError: pass
    return len(x.audit_log()) == before

check("tags_record", lambda: rich().get(1)["tags"] == ["team", "meal"])
check("tags_blank", lambda: raises_value(lambda: TransactionLedger().record(1, tags=[" "])))
check("tags_scalar", lambda: raises_value(lambda: TransactionLedger().record(1, tags="team")))
check("tags_get", lambda: "team" in rich().get(1)["tags"])
check("tags_transactions", lambda: rich().transactions()[0]["tags"] == ["team", "meal"])
check("transactions_with_tag", lambda: [v["id"] for v in rich().transactions_with_tag("team")] == [1, 2])
check("tag_casefold", lambda: len(rich().transactions_with_tag("TEAM")) == 2)
check("tag_summary", lambda: rich().tag_summary() == {"client": 1, "meal": 1, "team": 2, "trip": 1})
check("tag_refund_exclusion", lambda: (lambda x: (x.refund(2), x.tag_summary()["team"] == 1)[1])(rich()))
check("tags_roundtrip", lambda: TransactionLedger.from_json(rich().to_json()).get(1)["tags"] == ["team", "meal"])
check("metadata_record", lambda: rich().get(1)["metadata"] == {"source": "card"})
check("metadata_reject_type", lambda: raises_value(lambda: TransactionLedger().record(1, metadata=[])))
check("metadata_defensive_get", mutates_metadata_copy)
check("metadata_transactions", lambda: rich().transactions()[1]["metadata"] == {"source": "cash"})
check("metadata_update", lambda: (lambda x: x.update_metadata(1, {"approved": True})["metadata"]["approved"])(rich()))
check("metadata_update_unknown", lambda: raises_value(lambda: rich().update_metadata(999, {})))
check("metadata_update_reject_type", lambda: raises_value(lambda: rich().update_metadata(1, [])))
check("metadata_update_isolated", lambda: (lambda x: (x.update_metadata(1, {"x": 1}), x.get(1)["amount"] == 10 and x.get(1)["category"] == "food")[1])(rich()))
check("metadata_roundtrip", lambda: TransactionLedger.from_data(rich().export_data()).get(2)["metadata"] == {"source": "cash"})
check("metadata_caller_copy", caller_metadata_copy)
check("currency_default", lambda: TransactionLedger.from_json((lambda x: (x.record(1), x.to_json())[1])(TransactionLedger())).get(1)["currency"] == "USD")
check("currency_normalize", lambda: rich().get(1)["currency"] == "USD")
check("currency_blank", lambda: raises_value(lambda: TransactionLedger().record(1, currency=" ")))
check("currency_format", lambda: raises_value(lambda: TransactionLedger().record(1, currency="US1")))
check("currency_exposed", lambda: rich().transactions()[1]["currency"] == "EUR")
check("currency_total", lambda: rich().currency_total("USD") == 40)
check("currency_casefold", lambda: rich().currency_total("eur") == 20)
check("currency_summary", lambda: rich().currency_summary() == {"EUR": 20, "USD": 40})
check("currency_refund_exclusion", lambda: (lambda x: (x.refund(1), x.currency_total("USD") == 30)[1])(rich()))
check("currency_roundtrip", lambda: TransactionLedger.from_json(rich().to_json()).get(2)["currency"] == "EUR")
check("update_note", lambda: (lambda x: x.update_note(1, "Changed")["note"] == "Changed")(rich()))
check("update_note_unknown", lambda: raises_value(lambda: rich().update_note(999, "x")))
check("update_note_search", lambda: (lambda x: (x.update_note(1, "Unique needle"), [v["id"] for v in x.search("NEEDLE")] == [1])[1])(rich()))
check("update_category", lambda: (lambda x: x.update_category(1, "Office")["category"] == "office")(rich()))
check("update_category_normalize", lambda: (lambda x: x.update_category(1, " OFFICE ")["category"] == "office")(rich()))
check("update_category_blank", lambda: raises_value(lambda: rich().update_category(1, " ")))
check("update_category_unknown", lambda: raises_value(lambda: rich().update_category(999, "x")))
check("update_category_totals", lambda: (lambda x: (x.update_category(1, "Travel"), x.category_total("travel") == 30)[1])(rich()))
check("updates_roundtrip", lambda: (lambda x: (x.update_note(1, "n"), x.update_category(1, "c"), TransactionLedger.from_json(x.to_json()).get(1)["note"] == "n" and TransactionLedger.from_json(x.to_json()).get(1)["category"] == "c")[2])(rich()))
check("updates_stable_id", lambda: (lambda x: x.update_note(2, "n")["id"] == 2)(rich()))
check("filter_category", lambda: [v["id"] for v in rich().transactions(category="food")] == [1, 3])
check("filter_currency", lambda: [v["id"] for v in rich().transactions(currency="eur")] == [2])
check("filter_tag", lambda: [v["id"] for v in rich().transactions(tag="team")] == [1, 2])
check("filter_min", lambda: [v["id"] for v in rich().transactions(min_amount=20)] == [2, 3])
check("filter_max", lambda: [v["id"] for v in rich().transactions(max_amount=20)] == [1, 2])
check("filter_nonfinite", lambda: raises_value(lambda: rich().transactions(min_amount=float("nan"))))
check("filter_range", lambda: raises_value(lambda: rich().transactions(min_amount=3, max_amount=2)))
check("filter_composition", lambda: [v["id"] for v in rich().transactions(category="food", currency="usd", min_amount=20)] == [3])
check("filter_order", lambda: [v["id"] for v in rich().transactions(min_amount=1)] == [1, 2, 3])
check("filter_refunds", lambda: (lambda x: (x.refund(1), [v["id"] for v in x.transactions(category="food", include_refunded=False)] == [3])[1])(rich()))
check("sort_fields", lambda: [v["id"] for v in rich().transactions(sort_by="amount")] == [1, 2, 3] and [v["id"] for v in rich().transactions(sort_by="category")] == [1, 3, 2])
check("sort_reject", lambda: raises_value(lambda: rich().transactions(sort_by="missing")))
check("sort_descending", lambda: [v["id"] for v in rich().transactions(sort_by="amount", descending=True)] == [3, 2, 1])
check("sort_tiebreaker", lambda: (lambda x: [v["id"] for v in x.transactions(sort_by="amount")] == [1, 2])(TransactionLedger.from_data({"transactions":[{"id":2,"amount":1},{"id":1,"amount":1}],"refunds":[]})))
check("pagination_offset", lambda: [v["id"] for v in rich().transactions(offset=1)] == [2, 3])
check("pagination_negative_offset", lambda: raises_value(lambda: rich().transactions(offset=-1)))
check("pagination_limit", lambda: [v["id"] for v in rich().transactions(limit=2)] == [1, 2])
check("pagination_negative_limit", lambda: raises_value(lambda: rich().transactions(limit=-1)))
check("pagination_pipeline", lambda: [v["id"] for v in rich().transactions(category="food", sort_by="amount", descending=True, offset=1, limit=1)] == [1])
check("pagination_exhausted", lambda: rich().transactions(offset=99) == [])
check("statistics", lambda: rich().statistics() == {"count": 3, "total": 60, "minimum": 10, "maximum": 30, "average": 20})
check("statistics_empty", lambda: TransactionLedger().statistics() == {"count": 0, "total": 0, "minimum": None, "maximum": None, "average": None})
check("statistics_category", lambda: rich().statistics(category="food")["total"] == 40)
check("statistics_currency", lambda: rich().statistics(currency="EUR")["count"] == 1)
check("statistics_casefold", lambda: rich().statistics(category="FOOD", currency="usd")["count"] == 2)
check("statistics_refunds", lambda: (lambda x: (x.refund(3), x.statistics()["total"] == 30)[1])(rich()))
check("largest", lambda: rich().largest_transaction()["id"] == 3)
check("largest_empty", lambda: TransactionLedger().largest_transaction() is None)
check("largest_tie", lambda: (lambda x: (x.record(5), x.record(5), x.largest_transaction()["id"] == 1)[2])(TransactionLedger()))
check("analytics_after_updates", lambda: (lambda x: (x.update_category(3, "travel"), x.statistics(category="travel")["total"] == 50)[1])(rich()))
check("audit_log", lambda: isinstance(rich().audit_log(), list))
check("audit_record", lambda: [e["type"] for e in rich().audit_log()][:3] == ["RECORD", "RECORD", "RECORD"])
check("audit_refund", lambda: (lambda x: (x.refund(1), x.audit_log()[-1]["type"] == "REFUND")[1])(rich()))
check("audit_updates", lambda: (lambda x: (x.update_note(1,"n"), x.update_category(1,"c"), x.update_metadata(1,{"x":1}), [e["type"] for e in x.audit_log()][-3:] == ["UPDATE_NOTE","UPDATE_CATEGORY","UPDATE_METADATA"])[3])(rich()))
check("audit_rejections", lambda: rejected_without_audit(lambda x: x.refund(999)))
check("audit_ids", lambda: [e["id"] for e in rich().audit_log()] == [1, 2, 3])
check("audit_defensive", lambda: (lambda x: (x.audit_log().clear(), len(x.audit_log()) == 3)[1])(rich()))
check("audit_roundtrip", lambda: TransactionLedger.from_json(rich().to_json()).audit_log() == rich().audit_log())
check("audit_continuation", lambda: (lambda x: (x.record(1), x.audit_log()[-1]["id"] == 4)[1])(TransactionLedger.from_json(rich().to_json())))
check("extended_docs", lambda: all(word in open(sys.argv[1]+"/README.md", encoding="utf-8").read().casefold() for word in ("tags", "metadata", "currency", "filter", "sort", "pagination", "statistics", "audit")))
print(json.dumps(results))
'''
        completed = subprocess.run(
            [sys.executable, "-c", script, str(root)], capture_output=True,
            text=True, check=False, timeout=20,
        )
        if completed.returncode != 0:
            return {f"criterion_{index}": False for index in range(1, 101)}
        return json.loads(completed.stdout)

    @staticmethod
    def _validate_taskboard(root: Path) -> dict[str, bool]:
        script = r'''
import json, math, sys
sys.path.insert(0, sys.argv[1])
results = {}
try:
    from taskboard import ProjectBoard
except Exception:
    ProjectBoard = None

def check(name, fn):
    try: results[name] = bool(fn())
    except Exception: results[name] = False

def raises_value(fn):
    try: fn()
    except ValueError: return True
    except Exception: return False
    return False

def basic():
    b = ProjectBoard("Launch")
    for title in ("Design", "Build", "Test"): b.create_task(title)
    for task_id, description in enumerate(("Create design", "Write code", "Check code"), 1): b.update_description(task_id, description)
    for task_id, priority in enumerate(("high", "critical", "medium"), 1): b.update_priority(task_id, priority)
    for task_id, tags in enumerate((("UI", "team"), ("team", "code"), ("qa",)), 1):
        for tag in tags: b.add_tag(task_id, tag)
    b.assign(1, " Alice "); b.assign(2, "Bob")
    for task_id, hours in enumerate((3, 5, 2), 1): b.set_estimate(task_id, hours)
    for task_id, due in enumerate(("2030-01-02", "2030-01-03", "2030-01-04"), 1): b.set_due_date(task_id, due)
    return b

def minimal():
    b = ProjectBoard("Launch")
    for title in ("Design", "Build", "Test"): b.create_task(title)
    return b

check("construct_name", lambda: ProjectBoard("Launch").name == "Launch")
check("reject_blank_name", lambda: raises_value(lambda: ProjectBoard(" ")))
check("stable_create_id", lambda: ProjectBoard().create_task("A") == 1)
check("reject_blank_title", lambda: raises_value(lambda: ProjectBoard().create_task(" ")))
check("insertion_order", lambda: [minimal().get_task(i)["title"] for i in (1,2,3)] == ["Design","Build","Test"])
check("defensive_get", lambda: (lambda b: (b.get_task(1).update({"title":"x"}), b.get_task(1)["title"] == "Design")[1])(minimal()))
check("get_unknown", lambda: raises_value(lambda: ProjectBoard().get_task(99)))
check("length", lambda: len(minimal()) == 3)
check("task_ids", lambda: minimal().task_ids() == [1,2,3])
check("rejected_id_not_consumed", lambda: (lambda b: (raises_value(lambda: b.create_task(" ")), b.create_task("A") == 1)[1])(ProjectBoard()))
check("description_default", lambda: (lambda b: (b.create_task("A"), b.get_task(1)["description"] == "")[1])(ProjectBoard()))
check("update_title", lambda: (lambda b: b.update_title(1,"New")["title"] == "New")(basic()))
check("update_description", lambda: (lambda b: b.update_description(1,"New text")["description"] == "New text")(basic()))
check("update_returns_copy", lambda: (lambda b: (b.update_title(1,"New").update({"title":"bad"}), b.get_task(1)["title"] == "New")[1])(basic()))
check("update_unknown", lambda: raises_value(lambda: ProjectBoard().update_title(99,"x")))
check("priority_normalize", lambda: basic().get_task(1)["priority"] == "HIGH")
check("priority_default", lambda: (lambda b: (b.create_task("A"), b.get_task(1)["priority"] == "MEDIUM")[1])(ProjectBoard()))
check("priority_reject", lambda: raises_value(lambda: ProjectBoard().create_task("A", priority="urgent")))
check("priority_update", lambda: (lambda b: b.update_priority(1,"low")["priority"] == "LOW")(basic()))
check("fields_preserved", lambda: (lambda b: (b.start_task(1), b.get_task(1)["title"] == "Design" and b.get_task(1)["description"] == "Create design" and b.get_task(1)["priority"] == "HIGH")[1])(basic()))
check("status_default", lambda: basic().get_task(1)["status"] == "TODO")
check("statuses_supported", lambda: all((lambda b,s: b.set_status(1,s)["status"] == s)(basic(),s) for s in ("TODO","IN_PROGRESS","BLOCKED","DONE")))
check("status_reject", lambda: raises_value(lambda: basic().set_status(1,"WAITING")))
check("set_status", lambda: basic().set_status(1,"blocked")["status"] == "BLOCKED")
check("start_task", lambda: basic().start_task(1)["status"] == "IN_PROGRESS")
check("block_task", lambda: basic().block_task(1)["status"] == "BLOCKED")
check("reopen_task", lambda: (lambda b: (b.set_status(1,"DONE"), b.reopen_task(1)["status"] == "TODO")[1])(basic()))
check("complete_task", lambda: basic().complete_task(1)["status"] == "DONE")
check("duplicate_complete", lambda: (lambda b: (b.complete_task(1), raises_value(lambda: b.complete_task(1)))[1])(basic()))
check("completed_count", lambda: (lambda b: (b.complete_task(1), b.reopen_task(1), b.complete_task(1), b.summary()["status_counts"]["DONE"] == 1)[3])(basic()))
check("tags_normalized", lambda: basic().get_task(1)["tags"] == ["ui","team"])
check("tags_scalar_reject", lambda: raises_value(lambda: ProjectBoard().create_task("A", tags="tag")))
check("tags_blank_reject", lambda: raises_value(lambda: ProjectBoard().create_task("A", tags=[" "])))
check("add_tag", lambda: (lambda b: (b.add_tag(1,"New"), b.add_tag(1,"new"), b.get_task(1)["tags"].count("new") == 1)[2])(basic()))
check("remove_tag", lambda: (lambda b: (b.remove_tag(1,"UI"), b.remove_tag(1,"ui"), "ui" not in b.get_task(1)["tags"])[2])(basic()))
check("tags_defensive", lambda: (lambda b: (b.get_task(1)["tags"].append("bad"), "bad" not in b.get_task(1)["tags"])[1])(basic()))
check("tasks_with_tag", lambda: [x["id"] for x in basic().tasks_with_tag("TEAM")] == [1,2])
check("tag_query_order", lambda: [x["id"] for x in basic().tasks_with_tag("team")] == [1,2])
check("tag_summary", lambda: basic().tag_summary() == {"code":1,"qa":1,"team":2,"ui":1})
check("tag_summary_updates", lambda: (lambda b: (b.add_tag(3,"team"), b.remove_tag(1,"team"), b.tag_summary()["team"] == 2)[2])(basic()))
check("assignee_optional", lambda: basic().get_task(3)["assignee"] is None)
check("assignee_trim", lambda: basic().get_task(1)["assignee"] == "Alice")
check("assignee_blank_reject", lambda: raises_value(lambda: ProjectBoard().create_task("A",assignee=" ")))
check("assign", lambda: basic().assign(3," Cara ")["assignee"] == "Cara")
check("unassign", lambda: basic().unassign(1)["assignee"] is None)
check("assignee_query", lambda: [x["id"] for x in basic().tasks_for_assignee("alice")] == [1])
check("assignee_order", lambda: (lambda b: (b.assign(3,"Alice"), [x["id"] for x in b.tasks_for_assignee("ALICE")] == [1,3])[1])(basic()))
check("assignee_summary", lambda: basic().assignee_summary() == {"Alice":1,"Bob":1})
check("unassigned_summary", lambda: basic().summary()["unassigned_count"] == 1)
check("assignee_lifecycle", lambda: (lambda b: (b.complete_task(1), b.get_task(1)["assignee"] == "Alice")[1])(basic()))
check("estimate_positive", lambda: basic().get_task(1)["estimate_hours"] == 3)
check("estimate_reject", lambda: all(raises_value(lambda v=v: ProjectBoard().create_task("A",estimate_hours=v)) for v in (0,-1,float("nan"),float("inf"))))
check("set_estimate", lambda: basic().set_estimate(1,4)["estimate_hours"] == 4)
check("clear_estimate", lambda: basic().clear_estimate(1)["estimate_hours"] is None)
check("estimated_hours", lambda: basic().estimated_hours() == 10)
check("estimate_status_filter", lambda: (lambda b: (b.start_task(1), b.estimated_hours(status="in_progress") == 3)[1])(basic()))
check("remaining_hours", lambda: (lambda b: (b.complete_task(1), b.remaining_hours() == 7)[1])(basic()))
check("completed_hours", lambda: (lambda b: (b.complete_task(1), b.completed_hours() == 3)[1])(basic()))
check("empty_hours", lambda: ProjectBoard().estimated_hours() == 0 and ProjectBoard().remaining_hours() == 0)
check("due_date_iso", lambda: basic().get_task(1)["due_date"] == "2030-01-02")
check("due_date_reject", lambda: all(raises_value(lambda v=v: ProjectBoard().create_task("A",due_date=v)) for v in ("2030-02-30","01/02/2030")))
check("set_due", lambda: basic().set_due_date(1,"2031-02-03")["due_date"] == "2031-02-03")
check("clear_due", lambda: basic().clear_due_date(1)["due_date"] is None)
check("due_on", lambda: [x["id"] for x in basic().due_on("2030-01-03")] == [2])
check("due_before", lambda: [x["id"] for x in basic().due_before("2030-01-04")] == [1,2])
check("due_excludes_done", lambda: (lambda b: (b.complete_task(1), [x["id"] for x in b.due_before("2030-01-04")] == [2])[1])(basic()))
check("due_includes_done", lambda: (lambda b: (b.complete_task(1), [x["id"] for x in b.due_before("2030-01-04",include_done=True)] == [1,2])[1])(basic()))
check("overdue", lambda: [x["id"] for x in basic().overdue("2030-01-04")] == [1,2])
check("due_preserved", lambda: (lambda b: (b.update_title(1,"x"), b.get_task(1)["due_date"] == "2030-01-02")[1])(basic()))
check("add_dependency", lambda: (lambda b: (b.add_dependency(2,1), b.get_task(2)["dependencies"] == [1])[1])(basic()))
check("self_dependency", lambda: raises_value(lambda: basic().add_dependency(1,1)))
check("unknown_dependency", lambda: raises_value(lambda: basic().add_dependency(1,99)))
check("duplicate_dependency", lambda: (lambda b: (b.add_dependency(2,1),b.add_dependency(2,1),b.get_task(2)["dependencies"] == [1])[2])(basic()))
check("dependency_cycle", lambda: (lambda b: (b.add_dependency(2,1), raises_value(lambda: b.add_dependency(1,2)))[1])(basic()))
check("remove_dependency", lambda: (lambda b: (b.add_dependency(2,1),b.remove_dependency(2,1),b.remove_dependency(2,1),b.get_task(2)["dependencies"] == [])[3])(basic()))
check("dependency_order", lambda: (lambda b: (b.add_dependency(3,2),b.add_dependency(3,1),b.get_task(3)["dependencies"] == [1,2])[2])(basic()))
check("blockers", lambda: (lambda b: (b.add_dependency(3,1),[x["id"] for x in b.blockers(3)] == [1])[1])(basic()))
check("blocked_completion", lambda: (lambda b: (b.add_dependency(2,1),raises_value(lambda: b.complete_task(2)))[1])(basic()))
check("dependency_completion", lambda: (lambda b: (b.add_dependency(2,1),b.complete_task(1),b.complete_task(2)["status"] == "DONE")[2])(basic()))
check("ready_tasks", lambda: (lambda b: (b.add_dependency(2,1),[x["id"] for x in b.ready_tasks()] == [1,3])[1])(basic()))
check("ready_priority_order", lambda: [x["id"] for x in basic().ready_tasks()] == [2,1,3])
check("critical_path", lambda: (lambda b: (b.add_dependency(2,1),b.add_dependency(3,2),b.critical_path() == [1,2,3])[2])(basic()))
check("critical_tie", lambda: (lambda b: (b.add_dependency(3,1),b.add_dependency(3,2),b.critical_path() == [1,3])[2])(basic()))
check("dependency_roundtrip", lambda: (lambda b: (b.add_dependency(2,1),ProjectBoard.from_json(b.to_json()).get_task(2)["dependencies"] == [1])[1])(basic()))
check("task_filters", lambda: [x["id"] for x in basic().tasks(priority="HIGH",tag="team",assignee="alice",status="todo")] == [1])
check("filter_composition", lambda: [x["id"] for x in basic().tasks(tag="team",priority="CRITICAL")] == [2])
check("search", lambda: [x["id"] for x in basic().search("CODE")] == [2,3])
check("sort_fields", lambda: [x["id"] for x in basic().tasks(sort_by="priority")] == [1,3,2] and [x["id"] for x in basic().tasks(sort_by="title")] == [2,1,3])
check("sort_reject", lambda: raises_value(lambda: basic().tasks(sort_by="missing")))
check("sort_descending", lambda: [x["id"] for x in basic().tasks(sort_by="estimate_hours",descending=True)] == [2,1,3])
check("pagination", lambda: [x["id"] for x in basic().tasks(offset=1,limit=1)] == [2])
check("pagination_reject", lambda: raises_value(lambda: basic().tasks(offset=-1)) and raises_value(lambda: basic().tasks(limit=-1)))
check("query_pipeline", lambda: [x["id"] for x in basic().tasks(tag="team",sort_by="priority",descending=True,offset=1,limit=1)] == [1])
check("summary", lambda: basic().summary()["task_count"] == 3 and basic().summary()["priority_counts"]["CRITICAL"] == 1 and basic().summary()["estimated_hours"] == 10)
check("completion_percentage", lambda: (lambda b: (b.complete_task(1),b.completion_percentage() == 33.3)[1])(basic()))
check("data_roundtrip", lambda: ProjectBoard.from_data(basic().export_data()).task_ids() == [1,2,3])
check("json_roundtrip", lambda: ProjectBoard.from_json(basic().to_json()).to_json() == basic().to_json())
check("audit_ids_defensive", lambda: (lambda b: [e["id"] for e in b.audit_log()] == list(range(1,len(b.audit_log())+1)) and (b.audit_log().clear() is None) and len(b.audit_log()) > 0)(basic()))
check("audit_operations", lambda: (lambda b: (b.update_title(1,"x"),b.start_task(1),b.assign(3,"c"),b.add_dependency(2,1), all(t in [e["type"] for e in b.audit_log()] for t in ("CREATE_TASK","UPDATE_TITLE","START_TASK","ASSIGN","ADD_DEPENDENCY")))[4])(basic()))
check("audit_reject_and_docs", lambda: (lambda b: (lambda n: raises_value(lambda: b.add_dependency(1,1)) and len(b.audit_log()) == n)(len(b.audit_log())))(basic()) and all(w in open(sys.argv[1]+"/README.md",encoding="utf-8").read().casefold() for w in ("dependency","priority","assignee","due date","audit","serialization")))
print(json.dumps(results))
'''
        completed = subprocess.run(
            [sys.executable, "-c", script, str(root)], capture_output=True,
            text=True, check=False, timeout=30,
        )
        if completed.returncode != 0:
            return {f"criterion_{index}": False for index in range(1, 101)}
        payload = json.loads(completed.stdout)
        if len(payload) != 100:
            return {f"criterion_{index}": False for index in range(1, 101)}
        return payload


class ProjectGoalBenchmarkController:
    def __init__(self, benchmark: PairedProjectGoalBenchmark) -> None:
        self.benchmark = benchmark
        self.status = "IDLE"
        self.error = ""
        self.result = benchmark.store.latest()
        self._thread: threading.Thread | None = None

    def start(self) -> dict:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("A paired project benchmark is already running.")
        self.status, self.error = "RUNNING", ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.snapshot()

    def _run(self) -> None:
        try:
            self.result = self.benchmark.run()
            self.status = "COMPLETED"
        except Exception as exc:  # noqa: BLE001 - background failure is surfaced in the UI
            self.error, self.status = str(exc), "FAILED"

    def snapshot(self) -> dict:
        return {"status": self.status, "error": self.error, "result": self.result}
