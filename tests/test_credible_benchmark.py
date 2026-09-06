from types import SimpleNamespace

from rlmgraph.credible_benchmark import (
    CredibleBenchmarkSuite,
    CredibleBenchmarkSuiteStore,
    CredibleProjectSpec,
)
from rlmgraph.model_call_ledger import ModelCallLedger
from rlmgraph.project_goal_benchmark import ProjectGoalBenchmarkStore
from rlmgraph.system_evaluation_memory import SystemEvaluationMemoryStore


class SuiteWorker:
    def __init__(self, ledger: ModelCallLedger) -> None:
        self.ledger = ledger
        self.adapter = self
        self.forgotten: list[str | None] = []

    def _run(self, root):
        self.ledger.record(
            role="implementation", operation="CredibleTrial", provider="fixture",
            model="fixture", status="SUCCEEDED", latency_ms=1,
            input_tokens=100 if root.name == "baseline" else 40,
            output_tokens=10, token_source="PROVIDER",
        )
        (root / "proof.txt").write_text("passed", encoding="utf-8")
        return SimpleNamespace(
            rationale="completed hidden contract", files_changed=["proof.txt"],
            confidence=1.0,
        )

    def implement(self, request, evidence, sandbox_root):
        del request, evidence
        return self._run(sandbox_root)

    def persistent_project_turn(self, request, project_root, session_id):
        del request
        return self._run(project_root), session_id or f"session-{project_root.parent.name}"

    def forget_persistent_session(self, session_id):
        self.forgotten.append(session_id)


def projects(*, baseline_passes: bool = True):
    def make(project_id):
        def validate(root):
            passed = (root / "proof.txt").exists()
            if root.name == "baseline" and not baseline_passes:
                passed = False
            return {f"{project_id}_hidden": passed}

        return CredibleProjectSpec(
            id=project_id, goal=f"Complete {project_id}",
            milestones=(f"Implement the {project_id} hidden contract.",),
            seed_files={"module.py": "def seed():\n    return 1\n"},
            validate=validate,
        )

    return (make("alpha"), make("beta"))


def build_suite(tmp_path, *, baseline_passes=True):
    ledger = ModelCallLedger(tmp_path / "calls.db")
    worker = SuiteWorker(ledger)
    evaluation_store = SystemEvaluationMemoryStore(tmp_path / "system-evaluations.jsonl")
    suite = CredibleBenchmarkSuite(
        worker, ledger,
        ProjectGoalBenchmarkStore(tmp_path / "trials.db"),
        CredibleBenchmarkSuiteStore(tmp_path / "suites.db"),
        tmp_path / "runs", projects=projects(baseline_passes=baseline_passes),
        repetitions=2, random_seed=17, quality_threshold=0.8,
        evaluation_store=evaluation_store, report_root=tmp_path / "reports",
        models=["fixture-model"],
    )
    return suite, worker, evaluation_store


def test_credible_suite_repeats_fresh_projects_and_quality_gates_savings(tmp_path) -> None:
    suite, worker, evaluation_store = build_suite(tmp_path)

    result = suite.run()

    assert result["trial_count"] == 4
    assert {(trial["project"], trial["repetition"]) for trial in result["trials"]} == {
        ("alpha", 1), ("alpha", 2), ("beta", 1), ("beta", 2),
    }
    assert all(sorted(trial["arm_order"]) == ["baseline", "rlmgraph"] for trial in result["trials"])
    assert {tuple(trial["arm_order"]) for trial in result["trials"]} == {
        ("baseline", "rlmgraph"), ("rlmgraph", "baseline"),
    }
    assert len({trial["run_id"] for trial in result["trials"]}) == 4
    assert result["summary"]["quality_gate_passed"] is True
    assert result["summary"]["quality_gated_median_savings_percent"] is not None
    assert result["summary"]["raw_median_savings_withheld"] is False
    assert set(result["projects"]) == {"alpha", "beta"}
    assert all(
        summary["trial_count"] == 2 and summary["quality_gate_passed"] is True
        for summary in result["projects"].values()
    )
    assert all(trial["repair_calls"] == 0 for trial in result["trials"])
    assert len(worker.forgotten) == 4
    assert suite.suite_store.latest()["id"] == result["id"]
    evaluation = evaluation_store.records()[0]
    assert evaluation.suite_id == result["id"]
    assert evaluation.evidence_eligible is True
    assert evaluation.models == ["fixture-model"]
    assert (tmp_path / "reports" / f"suite-{result['id']}.json").is_file()


def test_credible_suite_withholds_savings_when_baseline_quality_is_too_low(tmp_path) -> None:
    suite, _, evaluation_store = build_suite(tmp_path, baseline_passes=False)

    result = suite.run()

    assert result["summary"]["quality_gate_passed"] is False
    assert result["summary"]["quality_gated_median_savings_percent"] is None
    assert result["summary"]["raw_median_savings_withheld"] is True
    assert result["summary"]["verdict"] == (
        "INCONCLUSIVE_BASELINE_BELOW_QUALITY_THRESHOLD"
    )
    assert evaluation_store.records()[0].evidence_eligible is False
