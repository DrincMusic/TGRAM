"""Deterministic proof for recursive planning, reuse, and hard budget stops."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rlmgraph.execution import AdaptiveInvestigator, WorkerSpec
from rlmgraph.fingerprint import project_fingerprint, task_fingerprint
from rlmgraph.followup import FollowUpExecutor
from rlmgraph.models import (
    Assertion,
    Claim,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    PursuitConfig,
    ResolutionChoice,
    ResolutionResult,
    Task,
    TaskKind,
    TaskRoute,
    TaskStatus,
)
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.runner import RecursiveRunner
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore

KEY = "planner.fixture.contract"


class FixtureInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The current contract selects alpha.",
            confidence=0.99,
            files_examined=["contract.txt"],
            assertions=[Assertion(key=KEY, value="alpha")],
        )


class WeakLocalInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The local worker found a candidate but not authoritative evidence.",
            confidence=0.4,
            unresolved_questions=["Escalate to repository-capable Codex investigation."],
        )


class FixtureResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, task, left, right, project_root, context):
        self.calls += 1
        if not context.follow_up_claims:
            return ResolutionResult(
                selected_claim=ResolutionChoice.NEITHER,
                resolved_assertion=None,
                rationale="The contradictory claims lack current repository evidence.",
                confidence=0.35,
                unresolved_questions=["What value does contract.txt select?"],
            )
        return ResolutionResult(
            selected_claim=ResolutionChoice.LEFT,
            resolved_assertion=left.assertions[0],
            rationale="The targeted child task inspected the current contract.",
            confidence=0.99,
        )


def clear_neo4j_fixture(
    store: Neo4jGraphStore, prefix: str, project_root: str | None = None
) -> None:
    store.driver.execute_query(
        "MATCH (artifact) WHERE "
        "(artifact:PlanDecision OR artifact:PlanningRun OR artifact:ExecutionAttempt "
        "OR artifact:RoutePrediction OR artifact:RoutingPolicyUpdate) "
        "AND artifact.root_task_id STARTS WITH $prefix DETACH DELETE artifact",
        prefix=prefix,
    )
    task_ids = [
        task.id
        for task in store.tasks()
        if task.id.startswith(prefix)
        or (project_root is not None and task.project_root == project_root)
    ]
    if not task_ids:
        return
    store.driver.execute_query(
        "MATCH (task:Task)-[:HAS_ROUTE_PREDICTION]->(:RoutePrediction)"
        "-[:EVALUATES_PREDICTION]->(evaluation:RouteEvaluation) "
        "WHERE task.id IN $task_ids DETACH DELETE evaluation",
        task_ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (task:Task) WHERE task.id IN $task_ids "
        "OPTIONAL MATCH (task)-[:HAS_PLAN_DECISION|HAS_PLANNING_RUN|HAS_EXECUTION|HAS_ROUTE_PREDICTION|HAS_POLICY_UPDATE|ATTEMPTED]->(artifact) "
        "WITH collect(DISTINCT artifact) AS artifacts "
        "FOREACH (artifact IN artifacts | DETACH DELETE artifact)",
        task_ids=task_ids,
    )
    store.driver.execute_query(
        "MATCH (task:Task) WHERE task.id IN $task_ids DETACH DELETE task",
        task_ids=task_ids,
    )


def seed(store, project: Path, prefix: str) -> Task:
    state = project_fingerprint(project)
    root = Task(
        id=f"{prefix}-ROOT",
        question="Resolve the isolated contract contradiction.",
        fingerprint=task_fingerprint(f"{prefix}-root", state),
        project_fingerprint=state,
        project_root=str(project.resolve()),
        status=TaskStatus.RECURSE,
    )
    left = Claim(
        id=f"{prefix}-ALPHA",
        fingerprint=task_fingerprint(f"{prefix}-alpha", state),
        project_fingerprint=state,
        subject=root.question,
        producer="Fixture",
        conclusion="The contract selects alpha.",
        confidence=0.55,
        assertions=[Assertion(key=KEY, value="alpha")],
    )
    right = Claim(
        id=f"{prefix}-BETA",
        fingerprint=task_fingerprint(f"{prefix}-beta", state),
        project_fingerprint=state,
        subject=root.question,
        producer="Fixture",
        conclusion="The contract selects beta.",
        confidence=0.55,
        assertions=[Assertion(key=KEY, value="beta")],
    )
    resolution = Task(
        id=f"{prefix}-RESOLUTION",
        question="Resolve alpha versus beta from current evidence.",
        fingerprint=task_fingerprint(f"{prefix}-resolution", state),
        project_fingerprint=state,
        project_root=str(project.resolve()),
        kind=TaskKind.RESOLUTION,
        parent_task_id=root.id,
        conflicting_claim_ids=[left.id, right.id],
        disputed_assertion_key=KEY,
        depth=1,
    )
    store.save_task(root)
    store.save_claim(root, left)
    store.save_claim(root, right)
    store.save_task(resolution)
    store.save_edge(GraphEdge(source=root.id, relation=GraphRelation.SPAWNED, target=resolution.id))
    store.save_edge(GraphEdge(source=left.id, relation=GraphRelation.CONTRADICTS, target=right.id))
    return root


def execute(store, project: Path, prefix: str, retrieval_budget: int) -> dict:
    root = seed(store, project, prefix)
    resolver = FixtureResolver()
    local = WeakLocalInvestigator()
    codex = FixtureInvestigator()
    config = PursuitConfig(
        max_depth=3,
        max_codex_calls=4,
        max_retries_per_task=3,
        max_retrieval_tokens=retrieval_budget,
        max_duplicate_investigations=0,
        max_wall_time_seconds=30,
    )
    runner = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        config,
        FollowUpExecutor(
            store,
            AdaptiveInvestigator(
                store,
                [
                    WorkerSpec(TaskRoute.LOCAL_MODEL, local, "FixtureLocal", 0.05, 0.1),
                    WorkerSpec(TaskRoute.CODEX, codex, "FixtureCodex", 2.0, 8.0),
                ],
                config.minimum_confidence,
            ),
        ),
    )
    outcome = runner.pursue(root.id)
    replay = runner.pursue(root.id) if outcome.status == TaskStatus.DONE else None
    run = outcome.planning_run
    assert run is not None
    executions = [
        attempt
        for attempt in store.execution_attempts()
        if attempt.root_task_id == root.id
    ]
    return {
        "root_task_id": root.id,
        "status": outcome.status.value,
        "stopping_reason": outcome.stopping_reason.value,
        "model_calls": run.model_calls_used,
        "retrieval_tokens": run.retrieval_tokens_used,
        "retrieval_budget": run.max_retrieval_tokens,
        "duplicate_investigations": run.duplicate_investigations,
        "replay_model_calls": replay.codex_calls if replay else None,
        "plan_actions": [item.action.value for item in store.plan_decisions(root.id)],
        "execution_routes": [attempt.actual_route.value for attempt in executions],
        "execution_outcomes": [attempt.outcome.value for attempt in executions],
        "fallbacks": sum(bool(attempt.fallback_from_attempt_id) for attempt in executions),
        "estimated_cost_usd": round(
            sum(attempt.estimated_cost_usd for attempt in executions), 8
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "neo4j"), default="sqlite")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="rlmgraph-demo")
    parser.add_argument(
        "--observer",
        action="store_true",
        help="Replace only the isolated LIVE-DEMO lineage so Observer displays this proof.",
    )
    args = parser.parse_args()
    project = Path(__file__).parent / "planner_fixture"
    if args.backend == "neo4j":
        store = Neo4jGraphStore(args.uri, args.user, args.password)
        if args.observer:
            from live_neo4j_demo import reset_demo

            reset_demo(store)
        clear_neo4j_fixture(store, "PLANNER-DEMO-", str(project.resolve()))
    else:
        database = project / "planner-demo.db"
        database.unlink(missing_ok=True)
        store = SQLiteGraphStore(database)
    store.initialize()
    success_prefix = "LIVE-DEMO" if args.observer else "PLANNER-DEMO-SUCCESS"
    success = execute(store, project, success_prefix, 2000)
    if args.backend == "neo4j":
        clear_neo4j_fixture(store, "PLANNER-DEMO-BUDGET")
    exhausted = execute(store, project, "PLANNER-DEMO-BUDGET", 1)
    assert success["status"] == "DONE" and success["replay_model_calls"] == 0
    assert success["duplicate_investigations"] == 0
    assert success["retrieval_tokens"] <= success["retrieval_budget"]
    assert "REPLANNED" in success["plan_actions"]
    assert success["execution_routes"] == [
        "RESOLVER",
        "LOCAL_MODEL",
        "CODEX",
        "RESOLVER",
        "MEMORY",
    ]
    assert success["fallbacks"] == 1
    assert exhausted["stopping_reason"] == "RETRIEVAL_TOKEN_BUDGET"
    assert exhausted["model_calls"] == 0
    print(json.dumps({"backend": args.backend, "success": success, "exhausted": exhausted}, indent=2))


if __name__ == "__main__":
    main()
