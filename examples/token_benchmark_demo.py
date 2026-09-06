"""Run the fixed-context versus active-memory benchmark on three isolated tasks."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rlmgraph.benchmark import BenchmarkCase, MemoryBenchmarkRunner
from rlmgraph.models import Claim, Evidence, GraphEdge, GraphRelation
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore

CASES = (
    (
        "cache-policy",
        "What invalidates the build cache?",
        "The build cache is invalidated by a compiler-version change.",
    ),
    (
        "discount-formula",
        "How is the discounted price calculated?",
        "The price is multiplied by one minus discount_percent divided by 100.",
    ),
    (
        "seam-continuity",
        "What preserves sampling across a face seam?",
        "Continuous face coordinates preserve the 3x3 sampling neighborhood.",
    ),
)


def build_cases(demo_root: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for case_id, question, answer_text in CASES:
        project = demo_root / case_id
        project.mkdir(parents=True)
        (project / "contract.txt").write_text(f"{answer_text}\n")
        evidence = [
            Claim(
                id=f"BENCH-{case_id}-EVIDENCE-{number}",
                fingerprint=f"{case_id}-evidence-{number}",
                project_root=str(project.resolve()),
                subject=f"Independent evidence {number} for {case_id}",
                producer="TokenBenchmarkFixture",
                conclusion=f"Evidence {number} independently supports: {answer_text}",
                confidence=1.0,
                evidence=[
                    Evidence(path="contract.txt", line=1, detail="Authoritative fixture")
                ],
                files_examined=["contract.txt"],
            )
            for number in range(2)
        ]
        noise = [
            Claim(
                id=f"BENCH-{case_id}-NOISE-{number:02d}",
                fingerprint=f"{case_id}-noise-{number}",
                project_root=str(project.resolve()),
                subject=f"Unrelated historical subsystem {number}",
                producer="TokenBenchmarkFixture",
                conclusion=(
                    "This intentionally verbose record describes an unrelated subsystem, its "
                    "prior implementation choices, abandoned alternatives, migration notes, "
                    "and diagnostic history. It belongs in fixed context but is unnecessary "
                    f"for answering benchmark case {case_id}."
                ),
                confidence=0.9,
            )
            for number in range(18)
        ]
        answer = Claim(
            id=f"BENCH-{case_id}-ANSWER",
            fingerprint=f"{case_id}-answer",
            project_root=str(project.resolve()),
            subject=question,
            producer="TokenBenchmarkFixture",
            conclusion=answer_text,
            confidence=1.0,
            source_claim_ids=[claim.id for claim in evidence],
            evidence=[Evidence(path="contract.txt", line=1, detail="Authoritative fixture")],
            files_examined=["contract.txt"],
        )
        cases.append(
            BenchmarkCase(
                id=case_id,
                question=question,
                project_root=project,
                claims=[*evidence, *noise, answer],
                expected_answer=answer_text,
                answer_claim_id=answer.id,
                required_evidence_ids=[claim.id for claim in evidence],
            )
        )
    return cases


def clear_neo4j(store: Neo4jGraphStore, project_roots: set[str]) -> None:
    task_ids = [task.id for task in store.tasks() if task.project_root in project_roots]
    if not task_ids:
        return
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids "
        "OPTIONAL MATCH (t)-[:HAS_RECONSTRUCTION]->(:Reconstruction)-[:HAS_STEP]->(s) "
        "WITH collect(DISTINCT s) AS nodes FOREACH (n IN nodes | DETACH DELETE n)",
        ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids "
        "OPTIONAL MATCH (t)-[:DISCOVERED|HAS_RECONSTRUCTION|HAS_BENCHMARK]->(artifact) "
        "WITH collect(DISTINCT artifact) AS nodes FOREACH (n IN nodes | DETACH DELETE n)",
        ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids DETACH DELETE t", ids=task_ids
    )


def attach_to_observer(store: Neo4jGraphStore, project_roots: set[str]) -> None:
    root = store.get_task("LIVE-DEMO-ROOT")
    if root is None:
        return
    for task in store.tasks():
        if task.project_root not in project_roots:
            continue
        task.parent_task_id = root.id
        task.depth = 1
        store.save_task(task)
        store.save_edge(
            GraphEdge(source=root.id, relation=GraphRelation.SPAWNED, target=task.id)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j", action="store_true")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="rlmgraph-demo")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    demo_root = root / ".rlmgraph" / "token-benchmark"
    expected_roots = {str((demo_root / case_id).resolve()) for case_id, _, _ in CASES}
    if args.neo4j:
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        store.initialize()
        clear_neo4j(store, expected_roots)
    if demo_root.exists():
        shutil.rmtree(demo_root)
    cases = build_cases(demo_root)
    if not args.neo4j:
        store = SQLiteGraphStore(demo_root / "benchmark.db")

    runner = MemoryBenchmarkRunner(store)
    runs = [runner.run(case) for case in cases]
    if args.neo4j:
        attach_to_observer(store, expected_roots)

    fixed_tokens = sum(run.fixed.input_tokens for run in runs)
    active_tokens = sum(run.active.input_tokens for run in runs)
    aggregate_reduction = 1 - active_tokens / fixed_tokens
    assert len(runs) >= 3
    assert all(run.passed for run in runs)
    assert aggregate_reduction >= 0.5
    assert all(run.fixed.duplicate_retrievals == 0 for run in runs)
    assert all(run.active.duplicate_retrievals == 0 for run in runs)

    print(
        json.dumps(
            {
                "backend": "neo4j" if args.neo4j else "sqlite",
                "encoding": "o200k_base",
                "isolated_fixture": str(demo_root),
                "case_count": len(runs),
                "fixed_input_tokens": fixed_tokens,
                "active_input_tokens": active_tokens,
                "aggregate_context_reduction": aggregate_reduction,
                "correctness_preserved": all(run.correctness_preserved for run in runs),
                "evidence_preserved": all(run.evidence_preserved for run in runs),
                "duplicate_retrievals": sum(
                    run.active.duplicate_retrievals for run in runs
                ),
                "cases": [
                    {
                        "id": run.case_id,
                        "fixed_tokens": run.fixed.input_tokens,
                        "active_tokens": run.active.input_tokens,
                        "reduction": run.token_reduction,
                        "fixed_wall_time_ms": run.fixed.wall_time_ms,
                        "active_wall_time_ms": run.active.wall_time_ms,
                        "traversal": run.traversal_node_ids,
                        "passed": run.passed,
                    }
                    for run in runs
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
