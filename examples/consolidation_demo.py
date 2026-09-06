"""Prove governed memory consolidation and rejection on an isolated fixture."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rlmgraph.models import (
    Assertion,
    ClaimValidity,
    Evidence,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    MemoryLifecycle,
    MemoryTier,
    PromotionOutcome,
)
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class FixtureInvestigator:
    def __init__(self, assertion_key: str, confidence: float = 0.95) -> None:
        self.assertion_key = assertion_key
        self.confidence = confidence

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = (project_root / "contract.txt").read_text().strip()
        return InvestigationResult(
            conclusion=f"The governed rule is {value}.",
            confidence=self.confidence,
            evidence=[Evidence(path="contract.txt", line=1, detail="Authoritative fixture")],
            files_examined=["contract.txt"],
            assertions=[Assertion(key=self.assertion_key, value=value)],
        )


class ContradictoryInvestigator:
    def __init__(self) -> None:
        self.values = iter(("alpha", "beta"))

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"The ambiguous observation says {value}.",
            confidence=0.95,
            evidence=[Evidence(path="contract.txt", line=1, detail="Unchanged fixture")],
            files_examined=["contract.txt"],
            assertions=[Assertion(key="demo.contradictory.rule", value=value)],
        )


def _project(parent: Path, name: str, value: str) -> Path:
    project = parent / name
    project.mkdir(parents=True)
    (project / "contract.txt").write_text(f"{value}\n")
    return project


def _clear_neo4j_fixture(store: Neo4jGraphStore, projects: list[Path]) -> None:
    roots = {str(project.resolve()) for project in projects}
    task_ids = [task.id for task in store.tasks() if task.project_root in roots]
    if not task_ids:
        return
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids "
        "OPTIONAL MATCH (t)-[:HAS_RECONSTRUCTION]->(:Reconstruction)-[:HAS_STEP]->(s) "
        "WITH collect(DISTINCT s) AS steps FOREACH (n IN steps | DETACH DELETE n)",
        ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids "
        "OPTIONAL MATCH (t)-[:DISCOVERED|HAS_RECONSTRUCTION|HAS_PROMOTION]->(artifact) "
        "WITH collect(DISTINCT artifact) AS artifacts "
        "FOREACH (n IN artifacts | DETACH DELETE n)",
        ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (t:Task) WHERE t.id IN $ids DETACH DELETE t", ids=task_ids
    )


def _attach_to_observer(store: Neo4jGraphStore, projects: list[Path]) -> None:
    root = store.get_task("LIVE-DEMO-ROOT")
    if root is None:
        return
    roots = {str(project.resolve()) for project in projects}
    for task in store.tasks():
        if task.project_root not in roots or task.parent_task_id is not None:
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
    demo_root = root / ".rlmgraph" / "consolidation-demo"
    project_paths = [demo_root / name for name in ("accepted", "weak", "contradictory")]
    if args.neo4j:
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        store.initialize()
        _clear_neo4j_fixture(store, project_paths)
    if demo_root.exists():
        shutil.rmtree(demo_root)
    accepted_project = _project(demo_root, "accepted", "safe-mode")
    weak_project = _project(demo_root, "weak", "weak-mode")
    contradictory_project = _project(demo_root, "contradictory", "unchanged")
    projects = [accepted_project, weak_project, contradictory_project]
    if not args.neo4j:
        store = SQLiteGraphStore(demo_root / "memory.db")

    question = "What is the governed fixture rule?"
    accepted = Supervisor(store, FixtureInvestigator("demo.accepted.rule"))
    accepted.run(question, accepted_project)
    accepted.run(question, accepted_project, force_investigation=True)
    accepted.run(question, accepted_project)
    accepted.run(question, accepted_project)
    preferred = accepted.run(question, accepted_project)

    semantic = next(
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.SEMANTIC
    )
    procedural = next(
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.PROCEDURAL
    )
    assert preferred.claim.id == procedural.id
    assert preferred.reuse_type == "procedural"

    weak = Supervisor(store, FixtureInvestigator("demo.weak.rule", confidence=0.5))
    weak.run("What is the weak fixture rule?", weak_project)
    weak.run("What is the weak fixture rule?", weak_project, force_investigation=True)

    contradictory = Supervisor(store, ContradictoryInvestigator())
    contradictory.run("What is the ambiguous fixture rule?", contradictory_project)
    contradictory.run(
        "What is the ambiguous fixture rule?",
        contradictory_project,
        force_investigation=True,
    )

    (accepted_project / "contract.txt").write_text("new-mode\n")
    stale_result = accepted.run(question, accepted_project)
    semantic = store.get_claim(semantic.id)
    procedural = store.get_claim(procedural.id)
    assert semantic is not None and procedural is not None
    assert not stale_result.cache_hit
    assert semantic.validity_status == ClaimValidity.INVALIDATED
    assert procedural.memory_lifecycle == MemoryLifecycle.INVALIDATED

    if args.neo4j:
        _attach_to_observer(store, projects)

    decisions = [
        decision
        for decision in store.promotion_decisions()
        if decision.project_root in {str(project.resolve()) for project in projects}
    ]
    fixture_claims = [claim for claim in store.claims() if claim.project_root in {str(project.resolve()) for project in projects}]
    rejection_reasons = [
        decision.reason
        for decision in decisions
        if decision.outcome == PromotionOutcome.REJECTED
    ]
    assert any("requires 2" in reason for reason in rejection_reasons)
    assert any("confidence" in reason.lower() for reason in rejection_reasons)
    assert any("Contradictory" in reason for reason in rejection_reasons)
    assert any(decision.stale_claim_ids for decision in decisions)
    assert any(decision.outcome == PromotionOutcome.ACCEPTED for decision in decisions)

    print(
        json.dumps(
            {
                "backend": "neo4j" if args.neo4j else "sqlite",
                "isolated_fixture": str(demo_root),
                "accepted_promotions": sum(
                    decision.outcome == PromotionOutcome.ACCEPTED for decision in decisions
                ),
                "rejected_promotions": sum(
                    decision.outcome == PromotionOutcome.REJECTED for decision in decisions
                ),
                "rejection_reasons": rejection_reasons,
                "procedural_preferred_before_invalidation": preferred.reuse_type,
                "stale_memory_reused": stale_result.cache_hit,
                "semantic_status_after_source_change": semantic.validity_status.value,
                "procedural_status_after_source_change": procedural.validity_status.value,
                "tiers_persisted": sorted(
                    {claim.memory_tier.value for claim in fixture_claims}
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
