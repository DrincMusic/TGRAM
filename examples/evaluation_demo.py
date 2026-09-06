"""Three-strategy deterministic evaluation, optionally published to Observer Neo4j."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from rlmgraph.evaluation import DeterministicEvaluationHarness
from rlmgraph.models import EvaluationStrategy
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore


def summary(run) -> dict[str, object]:
    totals = {
        strategy.value: {
            "worker_calls": sum(item.worker_calls for item in run.results if item.strategy == strategy),
            "model_calls": sum(item.model_calls for item in run.results if item.strategy == strategy),
            "retrieved_tokens": sum(item.retrieved_tokens for item in run.results if item.strategy == strategy),
            "latency_ms": sum(item.latency_ms for item in run.results if item.strategy == strategy),
            "observed_latency_ms": sum(item.observed_latency_ms for item in run.results if item.strategy == strategy),
            "duplicate_investigations": sum(item.duplicate_investigations for item in run.results if item.strategy == strategy),
            "memory_reuses": sum(item.memory_reuses for item in run.results if item.strategy == strategy),
        }
        for strategy in EvaluationStrategy
    }
    return {
        "evaluation_id": run.id,
        "passed": run.passed,
        "gates": {
            "correctness_preserved": run.correctness_preserved,
            "evidence_preserved": run.evidence_preserved,
            "fewer_repeat_worker_calls": run.fewer_repeat_worker_calls,
            "fewer_tokens_than_static": run.fewer_tokens_than_static,
            "stale_or_conflicting_memory_blocked": run.stale_or_conflicting_memory_blocked,
            "recovery_verified": run.recovery_verified,
            "reproducible": run.reproducible,
        },
        "totals": totals,
        "result_count": len(run.results),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    if args.observer:
        root = (Path(__file__).parents[1] / ".rlmgraph" / "evaluation-demo").resolve()
        if root.exists():
            shutil.rmtree(root)
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        store.initialize()
        store.driver.execute_query(
            "MATCH (run:EvaluationRun) WHERE run.suite_version=$version "
            "OPTIONAL MATCH (run)-[:HAS_EVALUATION_RESULT]->(result) "
            "DETACH DELETE run, result",
            version="deterministic-evaluation-v1",
        )
        run = DeterministicEvaluationHarness(store, root).run()
    else:
        with TemporaryDirectory(prefix="rlmgraph-evaluation-") as directory:
            root = Path(directory)
            run = DeterministicEvaluationHarness(
                SQLiteGraphStore(root / "evaluation.db"), root / "fixture"
            ).run()
            gc.collect()
    print(json.dumps(summary(run), indent=2))


if __name__ == "__main__":
    main()
