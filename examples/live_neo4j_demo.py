"""Run the real-Codex RESOLUTION -> FOLLOW_UP -> RESOLUTION proof in Neo4j."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rlmgraph.adapters import CodexCliInvestigator, CodexCliResolver
from rlmgraph.conflicts import build_conflict_cluster
from rlmgraph.execution import AdaptiveInvestigator, WorkerSpec
from rlmgraph.fingerprint import project_fingerprint, task_fingerprint
from rlmgraph.followup import FollowUpExecutor
from rlmgraph.models import (
    Assertion,
    Claim,
    GraphEdge,
    GraphRelation,
    PursuitConfig,
    Task,
    TaskKind,
    TaskRoute,
    TaskStatus,
)
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.runner import RecursiveRunner
from rlmgraph.store import Neo4jGraphStore

PREFIX = "LIVE-DEMO-"
KEY = "discounted_price.discount_percent.interpretation"


def reset_demo(store: Neo4jGraphStore) -> None:
    """Delete only nodes owned by this reproducible demo."""
    tasks = store.tasks()
    task_ids = {task.id for task in tasks if task.id.startswith(PREFIX)}
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task.parent_task_id in task_ids and task.id not in task_ids:
                task_ids.add(task.id)
                changed = True
    if not task_ids:
        return
    store.driver.execute_query(
        "MATCH (task:Task)-[:HAS_ROUTE_PREDICTION]->(:RoutePrediction)"
        "-[:EVALUATES_PREDICTION]->(evaluation:RouteEvaluation) "
        "WHERE task.id IN $task_ids DETACH DELETE evaluation",
        task_ids=sorted(task_ids),
    )
    store.driver.execute_query(
        "MATCH (task:Task)-[:HAS_RECONSTRUCTION]->(:Reconstruction)"
        "-[:SUPPORTS_PATHWAY]->(pathway:VirtualMemoryPathway) "
        "WHERE task.id IN $task_ids "
        "OPTIONAL MATCH (pathway)-[:HAS_BENCHMARK]->(benchmark) "
        "WITH collect(DISTINCT benchmark) AS nodes "
        "FOREACH (node IN nodes | DETACH DELETE node)",
        task_ids=sorted(task_ids),
    )
    store.driver.execute_query(
        "MATCH (task:Task)-[:HAS_RECONSTRUCTION]->(:Reconstruction)"
        "-[:SUPPORTS_PATHWAY]->(pathway:VirtualMemoryPathway) "
        "WHERE task.id IN $task_ids WITH collect(DISTINCT pathway) AS nodes "
        "FOREACH (node IN nodes | DETACH DELETE node)",
        task_ids=sorted(task_ids),
    )
    store.driver.execute_query(
        "MATCH (task:Task) WHERE task.id IN $task_ids "
        "MATCH (task)-[:HAS_RECONSTRUCTION]->(:Reconstruction)-[:HAS_STEP]->(step) "
        "DETACH DELETE step",
        task_ids=sorted(task_ids),
    )
    store.driver.execute_query(
        "MATCH (task:Task) WHERE task.id IN $task_ids "
        "MATCH (task)-[:DISCOVERED|PRODUCED|ATTEMPTED|HAS_CLUSTER|HAS_VERDICT|HAS_RECONSTRUCTION|HAS_PROMOTION|HAS_BENCHMARK|HAS_PATHWAY_DECISION|HAS_PLAN_DECISION|HAS_PLANNING_RUN|HAS_EXECUTION|HAS_ROUTE_PREDICTION|HAS_POLICY_UPDATE]->(artifact) "
        "WITH DISTINCT artifact DETACH DELETE artifact",
        task_ids=sorted(task_ids),
    )
    store.driver.execute_query(
        "MATCH (task:Task) WHERE task.id IN $task_ids DETACH DELETE task",
        task_ids=sorted(task_ids),
    )


def seed(store: Neo4jGraphStore, project: Path) -> tuple[Task, Task]:
    state = project_fingerprint(project)
    root = Task(
        id=f"{PREFIX}ROOT",
        question="Determine whether discount_percent is a percentage or a fixed amount.",
        fingerprint=task_fingerprint("live evidence-gap root", state),
        project_fingerprint=state,
        project_root=str(project.resolve()),
        status=TaskStatus.RECURSE,
    )
    left = Claim(
        id=f"{PREFIX}CLAIM-PERCENT-A",
        fingerprint=task_fingerprint("live left hypothesis", state),
        project_fingerprint=state,
        subject=root.question,
        producer="SeededHypothesis",
        conclusion="discount_percent is a percentage.",
        confidence=0.5,
        assertions=[Assertion(key=KEY, value="percentage")],
    )
    corroborating = Claim(
        id=f"{PREFIX}CLAIM-PERCENT-B",
        fingerprint=task_fingerprint("live corroborating hypothesis", state),
        project_fingerprint=state,
        subject=root.question,
        producer="IndependentSeededHypothesis",
        conclusion="discount_percent is a percentage.",
        confidence=0.5,
        assertions=[Assertion(key=KEY, value="percentage")],
    )
    right = Claim(
        id=f"{PREFIX}CLAIM-OUTLIER",
        fingerprint=task_fingerprint("live right hypothesis", state),
        project_fingerprint=state,
        subject=root.question,
        producer="SeededHypothesis",
        conclusion="discount_percent is a fixed amount.",
        confidence=0.5,
        assertions=[Assertion(key=KEY, value="fixed amount")],
    )
    cluster = build_conflict_cluster(state, KEY, [left, corroborating, right])
    cluster.id = f"{PREFIX}CLUSTER"
    resolution = Task(
        id=f"{PREFIX}RESOLUTION",
        question=(
            "Resolve the discount_percent interpretation using authoritative repository evidence."
        ),
        fingerprint=task_fingerprint("live evidence-gap resolution", state),
        project_fingerprint=state,
        project_root=str(project.resolve()),
        kind=TaskKind.RESOLUTION,
        parent_task_id=root.id,
        conflicting_claim_ids=cluster.claim_ids,
        disputed_assertion_key=KEY,
        conflict_cluster_id=cluster.id,
        depth=1,
    )
    cluster.resolution_task_id = resolution.id
    store.save_task(root)
    store.save_claim(root, left)
    store.save_claim(root, corroborating)
    store.save_claim(root, right)
    store.save_conflict_cluster(cluster)
    store.save_task(resolution)
    store.save_edge(GraphEdge(source=root.id, relation=GraphRelation.SPAWNED, target=resolution.id))
    store.save_edge(
        GraphEdge(source=left.id, relation=GraphRelation.CORROBORATES, target=corroborating.id)
    )
    for supporting in (left, corroborating, right):
        store.save_edge(
            GraphEdge(source=supporting.id, relation=GraphRelation.SUPPORTS, target=cluster.id)
        )
    store.save_edge(GraphEdge(source=right.id, relation=GraphRelation.OUTLIER, target=cluster.id))
    store.save_edge(GraphEdge(source=left.id, relation=GraphRelation.CONTRADICTS, target=right.id))
    store.save_edge(
        GraphEdge(source=corroborating.id, relation=GraphRelation.CONTRADICTS, target=right.id)
    )
    store.save_edge(
        GraphEdge(source=resolution.id, relation=GraphRelation.HAS_CLUSTER, target=cluster.id)
    )
    for claim in (left, corroborating, right):
        store.save_edge(
            GraphEdge(source=resolution.id, relation=GraphRelation.CONSIDERS, target=claim.id)
        )
    return root, resolution


def make_runner(store: Neo4jGraphStore, codex: str, model: str | None) -> RecursiveRunner:
    resolver = CodexCliResolver(codex, model, inspect_repository=False)
    investigator = CodexCliInvestigator(codex, model)
    config = PursuitConfig(max_depth=4, max_codex_calls=6, max_retries_per_task=3)
    return RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver, config.minimum_confidence),
        config,
        FollowUpExecutor(
            store,
            AdaptiveInvestigator(
                store,
                [WorkerSpec(TaskRoute.CODEX, investigator, "CodexCliInvestigator")],
                config.minimum_confidence,
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="rlmgraph-demo")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--reset-only", action="store_true")
    args = parser.parse_args()

    project = Path(__file__).parent / "evidence_gap"
    store = Neo4jGraphStore(args.uri, args.user, args.password)
    store.initialize()
    if args.reset or args.reset_only:
        reset_demo(store)
    root = store.get_task(f"{PREFIX}ROOT")
    resolution = store.get_task(f"{PREFIX}RESOLUTION")
    if root is None or resolution is None:
        root, resolution = seed(store, project)
    if args.reset_only:
        print(json.dumps({"root_task_id": root.id, "status": root.status}, indent=2))
        return

    first = make_runner(store, args.codex, args.model).pursue(root.id)
    attempts = store.resolution_attempts(resolution.id)
    lineage = first.tasks
    follow_ups = [task for task in lineage if task.kind == TaskKind.FOLLOW_UP]
    node_ids = {task.id for task in lineage}
    node_ids.update(attempt.id for attempt in attempts)
    node_ids.update(resolution.conflicting_claim_ids)
    node_ids.update(task.output_claim_id for task in follow_ups if task.output_claim_id)
    persisted_resolution = store.get_task(resolution.id)
    if persisted_resolution and persisted_resolution.resolved_claim_id:
        node_ids.add(persisted_resolution.resolved_claim_id)
    demo_edges = [
        edge
        for edge in store.edges()
        if edge.source in node_ids or edge.target in node_ids
    ]
    if first.status != TaskStatus.DONE:
        raise RuntimeError(f"Live recursive run did not finish: {first.model_dump_json()}")
    if len(attempts) < 2 or not follow_ups:
        raise RuntimeError("Expected two resolution attempts and at least one FOLLOW_UP")
    if attempts[0].result.selected_claim.value != "neither":
        raise RuntimeError("The evidence-gated first resolution did not identify missing evidence")
    if not any(edge.relation == GraphRelation.INFORMS for edge in demo_edges):
        raise RuntimeError("Neo4j is missing the FOLLOW_UP claim's INFORMS edge")

    replay = make_runner(store, args.codex, args.model).pursue(root.id)
    if replay.codex_calls != 0:
        raise RuntimeError("Replay repeated completed Codex work")

    print(
        json.dumps(
            {
                "path": ["RESOLUTION", "FOLLOW_UP", "RESOLUTION", "DONE"],
                "current_run_codex_calls": first.codex_calls,
                "replay_codex_calls": replay.codex_calls,
                "root_status": store.get_task(root.id).status,
                "resolution_attempts": len(attempts),
                "conflict_cluster_id": persisted_resolution.conflict_cluster_id,
                "follow_up_task_ids": [task.id for task in follow_ups],
                "follow_up_claim_ids": [task.output_claim_id for task in follow_ups],
                "neo4j_edges": [edge.model_dump(mode="json") for edge in demo_edges],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
