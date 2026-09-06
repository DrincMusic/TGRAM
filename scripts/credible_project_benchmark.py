from __future__ import annotations

import json
import os
from pathlib import Path

from rlmgraph.credible_benchmark import (
    CredibleBenchmarkSuite,
    CredibleBenchmarkSuiteStore,
)
from rlmgraph.implementation_sandbox import CodexPlanImplementationWorker
from rlmgraph.model_call_ledger import configure_model_call_ledger
from rlmgraph.project_goal_benchmark import ProjectGoalBenchmarkStore
from rlmgraph.system_evaluation_memory import SystemEvaluationMemoryStore


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    state_root = Path(os.environ.get(
        "RLMGRAPH_CREDIBLE_BENCHMARK_ROOT",
        workspace / ".rlmgraph" / "credible-benchmark",
    ))
    state_root.mkdir(parents=True, exist_ok=True)
    executable = os.environ.get("RLMGRAPH_IMPLEMENTATION_EXECUTABLE")
    if not executable and os.name == "nt":
        bridge = workspace / "scripts" / "codex_wsl_bridge.cmd"
        executable = str(bridge) if bridge.is_file() else "codex"
    ledger = configure_model_call_ledger(state_root / "model-calls.db")
    suite = CredibleBenchmarkSuite(
        CodexPlanImplementationWorker(
            executable or "codex",
            model=os.environ.get("RLMGRAPH_IMPLEMENTATION_MODEL", "gpt-5.4"),
        ),
        ledger,
        ProjectGoalBenchmarkStore(state_root / "trials.db"),
        CredibleBenchmarkSuiteStore(state_root / "suites.db"),
        state_root / "runs",
        repetitions=int(os.environ.get("RLMGRAPH_CREDIBLE_REPETITIONS", "3")),
        random_seed=int(os.environ.get("RLMGRAPH_CREDIBLE_RANDOM_SEED", "73421")),
        quality_threshold=float(os.environ.get("RLMGRAPH_CREDIBLE_QUALITY_THRESHOLD", "0.8")),
        evaluation_store=SystemEvaluationMemoryStore(
            workspace / ".rlmgraph" / "system-evaluation-memory.jsonl"
        ),
        report_root=state_root,
        models=[os.environ.get("RLMGRAPH_IMPLEMENTATION_MODEL", "gpt-5.4")],
    )
    result = suite.run()
    output = state_root / f"suite-{result['id']}.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Full result: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
