"""Prove governed virtual pathway tokens on an isolated recurring traversal."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rlmgraph.benchmark import BenchmarkCase, MemoryBenchmarkRunner
from rlmgraph.models import (
    Claim,
    Evidence,
    GraphEdge,
    GraphRelation,
    PathwayLifecycle,
    PromotionOutcome,
)
from rlmgraph.pathways import VirtualPathwayRegistry
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore


def build_case(project: Path) -> BenchmarkCase:
    project.mkdir(parents=True, exist_ok=True)
    (project / "contract.txt").write_text("Evidence continuity requires stable coordinates.\n")
    evidence = [
        Claim(
            id=f"PATH-DEMO-EVIDENCE-{index}",
            fingerprint=f"path-demo-evidence-{index}",
            project_root=str(project.resolve()),
            subject=f"Independent continuity evidence {index}",
            producer="PathwayTokenFixture",
            conclusion="Stable coordinates preserve continuity.",
            confidence=1.0,
            evidence=[Evidence(path="contract.txt", line=1, detail="Stable contract")],
            files_examined=["contract.txt"],
        )
        for index in range(2)
    ]
    noise = [
        Claim(
            id=f"PATH-DEMO-NOISE-{index:02d}",
            fingerprint=f"path-demo-noise-{index}",
            project_root=str(project.resolve()),
            subject=f"Unrelated subsystem {index}",
            producer="PathwayTokenFixture",
            conclusion=(
                "Verbose unrelated architecture, migration history, failed experiments, and "
                "diagnostic notes that a fixed or ordinary active context should not repeatedly "
                "materialize when a stable pathway token is available."
            ),
            confidence=0.9,
        )
        for index in range(18)
    ]
    question = "What preserves evidence continuity?"
    answer = Claim(
        id="PATH-DEMO-ANSWER",
        fingerprint="path-demo-answer",
        project_root=str(project.resolve()),
        subject=question,
        producer="PathwayTokenFixture",
        conclusion="Evidence continuity requires stable coordinates.",
        confidence=1.0,
        evidence=[Evidence(path="contract.txt", line=1, detail="Stable contract")],
        files_examined=["contract.txt"],
        source_claim_ids=[claim.id for claim in evidence],
    )
    return BenchmarkCase(
        id="recurring-continuity-pathway",
        question=question,
        project_root=project,
        claims=[*evidence, *noise, answer],
        expected_answer=answer.conclusion,
        answer_claim_id=answer.id,
        required_evidence_ids=[claim.id for claim in evidence],
    )


def clear_neo4j(store: Neo4jGraphStore, project_root: str) -> None:
    task_ids = [task.id for task in store.tasks() if task.project_root == project_root]
    store.driver.execute_query(
        "MATCH (p:VirtualMemoryPathway {project_root: $project_root}) "
        "OPTIONAL MATCH (p)-[:HAS_BENCHMARK]->(b) DETACH DELETE b",
        project_root=project_root,
    )
    store.driver.execute_query(
        "MATCH (p:VirtualMemoryPathway {project_root: $project_root}) DETACH DELETE p",
        project_root=project_root,
    )
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
        "OPTIONAL MATCH (t)-[:DISCOVERED|HAS_RECONSTRUCTION|HAS_BENCHMARK|HAS_PATHWAY_DECISION]->(artifact) "
        "WITH collect(DISTINCT artifact) AS nodes FOREACH (n IN nodes | DETACH DELETE n)",
        ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids DETACH DELETE t", ids=task_ids
    )


def attach_to_observer(store: Neo4jGraphStore, project_root: str) -> None:
    root = store.get_task("LIVE-DEMO-ROOT")
    if root is None:
        return
    for task in store.tasks():
        if task.project_root != project_root:
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
    demo_root = root / ".rlmgraph" / "pathway-token-demo"
    project = demo_root / "project"
    project_root = str(project.resolve())
    if args.neo4j:
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        store.initialize()
        clear_neo4j(store, project_root)
    if demo_root.exists():
        shutil.rmtree(demo_root)
    demo_root.mkdir(parents=True)
    if not args.neo4j:
        store = SQLiteGraphStore(demo_root / "pathways.db")

    runner = MemoryBenchmarkRunner(store)
    registry = VirtualPathwayRegistry(store)
    decisions = []
    runs = []
    pathway = None
    for _ in range(3):
        run = runner.run(build_case(project))
        decision, promoted = registry.observe(run)
        decisions.append(decision)
        runs.append(run)
        pathway = promoted or pathway
    assert pathway is not None
    expansion = registry.expand(pathway.token)
    token_result = registry.benchmark_token(
        runs[-1], pathway, answer_claim_id="PATH-DEMO-ANSWER"
    )
    old_token = pathway.token

    (project / "contract.txt").write_text("Changed evidence invalidates the pathway.\n")
    stale_expansion = registry.expand(old_token)
    invalidated = next(item for item in store.pathways() if item.token == old_token)
    assert invalidated.lifecycle == PathwayLifecycle.INVALIDATED

    (project / "contract.txt").write_text(
        "Evidence continuity requires stable coordinates.\n"
    )
    replacement_run = runner.run(build_case(project))
    replacement_decision, replacement = registry.observe(replacement_run)
    assert replacement is not None and replacement.version == 2
    if args.neo4j:
        attach_to_observer(store, project_root)

    assert [decision.outcome for decision in decisions] == [
        PromotionOutcome.REJECTED,
        PromotionOutcome.REJECTED,
        PromotionOutcome.ACCEPTED,
    ]
    assert expansion.complete and expansion.evidence and expansion.source_files
    assert token_result.correct and token_result.evidence_preserved
    assert token_result.additional_reduction > 0.5
    assert stale_expansion.complete is False
    assert replacement_decision.outcome == PromotionOutcome.ACCEPTED

    print(
        json.dumps(
            {
                "backend": "neo4j" if args.neo4j else "sqlite",
                "isolated_fixture": str(demo_root),
                "promotion_outcomes": [item.outcome.value for item in decisions],
                "token_v1": old_token,
                "token_v2": replacement.token,
                "access_frequency": pathway.access_frequency,
                "active_input_tokens": token_result.active_input_tokens,
                "virtual_token_input_tokens": token_result.token_input_tokens,
                "additional_reduction": token_result.additional_reduction,
                "correct": token_result.correct,
                "evidence_preserved": token_result.evidence_preserved,
                "expansion_trace": expansion.expansion_trace,
                "stale_token_expands": stale_expansion.complete,
                "stale_lifecycle": invalidated.lifecycle.value,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
