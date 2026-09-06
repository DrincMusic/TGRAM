# ruff: noqa: BLE001 - hidden acceptance treats arbitrary candidate failures as failed criteria
from __future__ import annotations

import json
import random
import sqlite3
import statistics
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .model_call_ledger import ModelCallLedger
from .project_goal_benchmark import (
    PairedProjectGoalBenchmark,
    ProjectGoalBenchmarkStore,
    ProjectWorker,
)
from .system_evaluation_memory import SystemEvaluationMemoryStore

Validator = Callable[[Path], dict[str, bool]]


@dataclass(frozen=True)
class CredibleProjectSpec:
    id: str
    goal: str
    milestones: tuple[str, ...]
    seed_files: dict[str, str]
    validate: Validator


def _namespace(path: Path) -> dict:
    namespace: dict = {}
    exec(  # noqa: S102 - candidate code is confined to the disposable benchmark process
        compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace
    )
    return namespace


def _raises(error_type: type[BaseException], function: Callable, *args) -> bool:
    try:
        function(*args)
    except error_type:
        return True
    except Exception:
        return False
    return False


def _counter_validation(root: Path) -> dict[str, bool]:
    try:
        counter = _namespace(root / "counter.py")["Counter"]
    except Exception:
        return {name: False for name in (
            "initial_value", "reject_invalid_initial", "increment_amount",
            "safe_decrement", "reset_and_snapshot",
        )}
    checks: dict[str, bool] = {}
    try:
        checks["initial_value"] = counter().value == 0 and counter(4).value == 4
    except Exception:
        checks["initial_value"] = False
    checks["reject_invalid_initial"] = all(
        _raises(ValueError, counter, value) for value in (-1, 1.5, True)
    )
    try:
        item = counter(2)
        checks["increment_amount"] = item.increment(3) == 5 and item.value == 5
    except Exception:
        checks["increment_amount"] = False
    try:
        item = counter(3)
        checks["safe_decrement"] = (
            item.decrement(2) == 1
            and _raises(ValueError, item.decrement, 2)
            and item.value == 1
        )
    except Exception:
        checks["safe_decrement"] = False
    try:
        item = counter(3)
        snapshot = item.snapshot()
        snapshot["value"] = 99
        checks["reset_and_snapshot"] = (
            item.value == 3 and item.reset() == 0 and item.snapshot() == {"value": 0}
        )
    except Exception:
        checks["reset_and_snapshot"] = False
    return checks


def _inventory_validation(root: Path) -> dict[str, bool]:
    try:
        inventory = _namespace(root / "inventory.py")["Inventory"]
    except Exception:
        return {name: False for name in (
            "add_quantity", "reject_invalid_add", "remove_stock",
            "ordered_snapshot", "total_units",
        )}
    checks: dict[str, bool] = {}
    try:
        item = inventory()
        checks["add_quantity"] = item.add("A", 2) == 2 and item.quantity("A") == 2
    except Exception:
        checks["add_quantity"] = False
    try:
        item = inventory()
        checks["reject_invalid_add"] = (
            _raises(ValueError, item.add, " ", 1)
            and _raises(ValueError, item.add, "A", 0)
            and _raises(ValueError, item.add, "A", True)
        )
    except Exception:
        checks["reject_invalid_add"] = False
    try:
        item = inventory()
        item.add("A", 3)
        checks["remove_stock"] = (
            item.remove("A", 2) == 1
            and _raises(ValueError, item.remove, "A", 2)
            and item.quantity("A") == 1
        )
    except Exception:
        checks["remove_stock"] = False
    try:
        item = inventory()
        item.add("b", 1); item.add("a", 2)
        snapshot = item.list_items(); snapshot[0]["quantity"] = 99
        checks["ordered_snapshot"] = (
            [entry["sku"] for entry in item.list_items()] == ["a", "b"]
            and item.quantity("a") == 2
        )
    except Exception:
        checks["ordered_snapshot"] = False
    try:
        item = inventory(); item.add("A", 2); item.add("B", 3)
        checks["total_units"] = item.total_units() == 5
    except Exception:
        checks["total_units"] = False
    return checks


def _notes_validation(root: Path) -> dict[str, bool]:
    try:
        notebook = _namespace(root / "notes.py")["NoteBook"]
    except Exception:
        return {name: False for name in (
            "reject_blank", "stable_ids", "defensive_get", "update_note", "search_notes",
        )}
    checks: dict[str, bool] = {}
    try:
        item = notebook()
        checks["reject_blank"] = _raises(ValueError, item.add, "  ")
    except Exception:
        checks["reject_blank"] = False
    try:
        item = notebook()
        checks["stable_ids"] = item.add("one") == 1 and item.add("two") == 2
    except Exception:
        checks["stable_ids"] = False
    try:
        item = notebook(); note_id = item.add("one"); note = item.get(note_id)
        note["text"] = "changed"
        checks["defensive_get"] = item.get(note_id) == {"id": 1, "text": "one"}
    except Exception:
        checks["defensive_get"] = False
    try:
        item = notebook(); note_id = item.add("one")
        checks["update_note"] = (
            item.update(note_id, "updated") == {"id": 1, "text": "updated"}
            and _raises(ValueError, item.update, 99, "missing")
        )
    except Exception:
        checks["update_note"] = False
    try:
        item = notebook(); item.add("Alpha launch"); item.add("beta"); item.add("ALPHA two")
        checks["search_notes"] = [note["id"] for note in item.search("alpha")] == [1, 3]
    except Exception:
        checks["search_notes"] = False
    return checks


DEFAULT_CREDIBLE_PROJECTS = (
    CredibleProjectSpec(
        id="counter",
        goal="Build a validated mutable counter with safe arithmetic and defensive state export.",
        milestones=(
            "Allow Counter(initial=0) with a non-negative integer initial value.",
            "Reject negative, boolean, and non-integer initial values with ValueError.",
            "Support increment(amount=1) for positive integers and return the new value.",
            "Add decrement(amount=1), rejecting invalid amounts and values below zero.",
            "Add reset() and snapshot() returning a defensive {'value': current} dictionary.",
        ),
        seed_files={
            "counter.py": (
                "class Counter:\n"
                "    def __init__(self):\n        self.value = 0\n\n"
                "    def increment(self):\n        self.value += 1\n        return self.value\n"
            ),
            "README.md": "# Counter\n",
        },
        validate=_counter_validation,
    ),
    CredibleProjectSpec(
        id="inventory",
        goal="Build a deterministic inventory with validated stock changes and defensive queries.",
        milestones=(
            "Support add(sku, quantity=1) and quantity(sku), returning current stock.",
            "Reject blank SKUs and non-positive or boolean quantities with ValueError.",
            "Add remove(sku, quantity=1) without allowing stock to become negative.",
            "Add list_items() as defensive dictionaries sorted by SKU.",
            "Add total_units() returning the sum of all current stock.",
        ),
        seed_files={
            "inventory.py": (
                "class Inventory:\n"
                "    def __init__(self):\n        self._items = {}\n\n"
                "    def add(self, sku):\n"
                "        self._items[sku] = self._items.get(sku, 0) + 1\n"
                "        return self._items[sku]\n\n"
                "    def quantity(self, sku):\n        return self._items.get(sku, 0)\n"
            ),
            "README.md": "# Inventory\n",
        },
        validate=_inventory_validation,
    ),
    CredibleProjectSpec(
        id="notes",
        goal="Build a durable ordered note collection with defensive access, updates, and search.",
        milestones=(
            "Reject blank note text with ValueError.",
            "Make add(text) return stable positive integer note IDs.",
            "Add get(note_id) returning a defensive note dictionary.",
            "Add update(note_id, text), returning the updated copy and rejecting unknown IDs.",
            "Add case-insensitive search(query) in stable note-ID order.",
        ),
        seed_files={
            "notes.py": (
                "class NoteBook:\n"
                "    def __init__(self):\n        self._notes = []\n\n"
                "    def add(self, text):\n        self._notes.append(text)\n"
            ),
            "README.md": "# Notes\n",
        },
        validate=_notes_validation,
    ),
)


class SpecProjectBenchmark(PairedProjectGoalBenchmark):
    def __init__(self, *args, spec: CredibleProjectSpec, arm_order: tuple[str, str], **kwargs):
        super().__init__(*args, **kwargs)
        self.spec = spec
        self.goal = spec.goal
        self.milestones = list(spec.milestones)
        self.milestone_limit = len(spec.milestones)
        self.arm_mode = "paired"
        self.arm_execution_order = arm_order
        self.continue_previous_project = False

    def _create_seed(self, root: Path, previous: dict | None) -> None:
        del previous
        root.mkdir(parents=True)
        for relative, content in self.spec.seed_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _validate(self, root: Path) -> dict[str, bool]:
        return self.spec.validate(root)


class CredibleBenchmarkSuiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS credible_benchmark_suites "
                "(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save(self, payload: dict) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO credible_benchmark_suites VALUES (?, ?, ?)",
                (payload["id"], payload["created_at"], json.dumps(payload)),
            )

    def latest(self) -> dict | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM credible_benchmark_suites "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else None


class CredibleBenchmarkSuite:
    """Repeated, randomized, hidden-validator projects with quality-gated savings."""

    def __init__(
        self, worker: ProjectWorker, ledger: ModelCallLedger,
        trial_store: ProjectGoalBenchmarkStore, suite_store: CredibleBenchmarkSuiteStore,
        runs_root: Path, *, projects: tuple[CredibleProjectSpec, ...] = DEFAULT_CREDIBLE_PROJECTS,
        repetitions: int = 3, random_seed: int = 73421, quality_threshold: float = 0.8,
        evaluation_store: SystemEvaluationMemoryStore | None = None,
        report_root: Path | None = None,
        models: list[str] | None = None,
        invalidates_evaluation_ids: list[str] | None = None,
    ) -> None:
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        if not 0 < quality_threshold <= 1:
            raise ValueError("quality_threshold must be in (0, 1]")
        if len(projects) < 2:
            raise ValueError("credible comparison requires multiple project families")
        self.worker = worker
        self.ledger = ledger
        self.trial_store = trial_store
        self.suite_store = suite_store
        self.runs_root = runs_root
        self.projects = projects
        self.repetitions = repetitions
        self.random_seed = random_seed
        self.quality_threshold = quality_threshold
        self.evaluation_store = evaluation_store
        self.report_root = report_root
        self.models = models or [str(getattr(getattr(worker, "adapter", None), "model", None) or "provider-default")]
        self.invalidates_evaluation_ids = invalidates_evaluation_ids or []

    def run(self) -> dict:
        suite_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        randomizer = random.Random(self.random_seed)
        schedule = [
            (spec, repetition)
            for repetition in range(1, self.repetitions + 1)
            for spec in self.projects
        ]
        randomizer.shuffle(schedule)
        trials: list[dict] = []
        for sequence, (spec, repetition) in enumerate(schedule, 1):
            order = ["baseline", "rlmgraph"]
            randomizer.shuffle(order)
            benchmark = SpecProjectBenchmark(
                self.worker, self.ledger, self.trial_store,
                self.runs_root / suite_id / f"trial-{sequence:03d}",
                spec=spec, arm_order=(order[0], order[1]),
            )
            raw = benchmark.run()
            baseline_quality = raw["baseline"]["criteria_passed"] / raw["criteria_total"]
            rlm_quality = raw["rlmgraph"]["criteria_passed"] / raw["criteria_total"]
            trials.append({
                "sequence": sequence,
                "project": spec.id,
                "repetition": repetition,
                "run_id": raw["id"],
                "arm_order": order,
                "criteria_total": raw["criteria_total"],
                "baseline_tokens": raw["baseline_tokens"],
                "rlmgraph_tokens": raw["rlmgraph_tokens"],
                "baseline_pass_rate": baseline_quality,
                "rlmgraph_pass_rate": rlm_quality,
                "baseline_calls": raw["baseline"]["model_call_count"],
                "rlmgraph_calls": raw["rlmgraph"]["model_call_count"],
                "repair_calls": raw["rlmgraph_autonomous_repair"]["repair_model_calls"],
                "raw_savings_percent": raw["savings_percent"],
                "both_meet_quality_threshold": (
                    baseline_quality >= self.quality_threshold
                    and rlm_quality >= self.quality_threshold
                ),
            })

        baseline_pass_rate = sum(
            trial["baseline_pass_rate"] for trial in trials
        ) / len(trials)
        rlm_pass_rate = sum(
            trial["rlmgraph_pass_rate"] for trial in trials
        ) / len(trials)
        every_trial_qualified = all(
            trial["both_meet_quality_threshold"] for trial in trials
        )
        baseline_median = statistics.median(
            trial["baseline_tokens"] for trial in trials
        )
        rlm_median = statistics.median(
            trial["rlmgraph_tokens"] for trial in trials
        )
        gated_savings = (
            round((baseline_median - rlm_median) / baseline_median * 100, 1)
            if every_trial_qualified and baseline_median else None
        )
        project_summaries: dict[str, dict] = {}
        for spec in self.projects:
            project_trials = [trial for trial in trials if trial["project"] == spec.id]
            project_gate = all(
                trial["both_meet_quality_threshold"] for trial in project_trials
            )
            project_baseline_median = statistics.median(
                trial["baseline_tokens"] for trial in project_trials
            )
            project_rlm_median = statistics.median(
                trial["rlmgraph_tokens"] for trial in project_trials
            )
            project_summaries[spec.id] = {
                "trial_count": len(project_trials),
                "quality_gate_passed": project_gate,
                "baseline_pass_rate": round(statistics.mean(
                    trial["baseline_pass_rate"] for trial in project_trials
                ), 4),
                "rlmgraph_pass_rate": round(statistics.mean(
                    trial["rlmgraph_pass_rate"] for trial in project_trials
                ), 4),
                "baseline_median_tokens": project_baseline_median,
                "rlmgraph_median_tokens": project_rlm_median,
                "quality_gated_median_savings_percent": (
                    round(
                        (project_baseline_median - project_rlm_median)
                        / project_baseline_median * 100,
                        1,
                    )
                    if project_gate and project_baseline_median else None
                ),
            }
        if every_trial_qualified:
            verdict = "VALID_SAVINGS_COMPARISON"
        elif any(
            trial["baseline_pass_rate"] < self.quality_threshold for trial in trials
        ):
            verdict = "INCONCLUSIVE_BASELINE_BELOW_QUALITY_THRESHOLD"
        else:
            verdict = "INVALID_RLMGRAPH_BELOW_QUALITY_THRESHOLD"
        result = {
            "id": suite_id,
            "created_at": created_at,
            "status": "COMPLETED",
            "random_seed": self.random_seed,
            "quality_threshold": self.quality_threshold,
            "project_count": len(self.projects),
            "repetitions": self.repetitions,
            "trial_count": len(trials),
            "hidden_acceptance_tests": True,
            "fresh_state_per_arm": True,
            "randomized_arm_order": True,
            "repair_tokens_included": True,
            "trials": trials,
            "projects": project_summaries,
            "summary": {
                "verdict": verdict,
                "quality_gate_passed": every_trial_qualified,
                "baseline_pass_rate": round(baseline_pass_rate, 4),
                "rlmgraph_pass_rate": round(rlm_pass_rate, 4),
                "baseline_median_tokens": baseline_median,
                "rlmgraph_median_tokens": rlm_median,
                "quality_gated_median_savings_percent": gated_savings,
                "raw_median_savings_withheld": not every_trial_qualified,
            },
        }
        self.suite_store.save(result)
        if self.evaluation_store is not None:
            report_root = self.report_root or self.runs_root.parent
            report_path = report_root / f"suite-{suite_id}.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            self.evaluation_store.remember_credible_suite(
                result,
                report_path,
                models=self.models,
                invalidates_evaluation_ids=self.invalidates_evaluation_ids,
            )
        return result
