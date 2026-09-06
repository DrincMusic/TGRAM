from pathlib import Path

from rlmgraph.followup import FollowUpExecutor
from rlmgraph.models import (
    Assertion,
    ClusterStatus,
    GraphRelation,
    InvestigationResult,
    PursuitConfig,
    ResolutionChoice,
    ResolutionResult,
    TaskStatus,
)
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.runner import RecursiveRunner
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor

KEY = "discounted_price.discount_percent.interpretation"


class ThreeClaimInvestigator:
    def __init__(self, values=None) -> None:
        self.values = iter(values or ["percentage", "percentage", "fixed amount"])

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"discount_percent is {value}",
            confidence=0.7,
            assertions=[Assertion(key=KEY, value=value)],
        )


class ClusterResolver:
    def __init__(self, require_follow_up: bool = False) -> None:
        self.require_follow_up = require_follow_up
        self.calls = 0
        self.contexts = []

    def resolve_cluster(self, task, claims, project_root, context):
        self.calls += 1
        self.contexts.append(context)
        if self.require_follow_up and not context.follow_up_claims:
            return ResolutionResult(
                selected_claim=ResolutionChoice.NEITHER,
                resolved_assertion=None,
                rationale="The three hypotheses contain no authoritative evidence.",
                confidence=0.9,
                unresolved_questions=["What does the pricing contract define?"],
            )
        cluster = context.conflict_cluster
        selected = next(item for item in cluster.interpretations if item.value == "percentage")
        return ResolutionResult(
            selected_claim=ResolutionChoice.VALUE,
            selected_value="percentage",
            selected_claim_ids=selected.claim_ids,
            corroborated_claim_ids=cluster.corroborated_claim_ids,
            outlier_claim_ids=cluster.outlier_claim_ids,
            resolved_assertion=Assertion(key=KEY, value="percentage"),
            rationale="The contract supports both percentage claims and rejects the outlier.",
            confidence=0.98,
        )

    def resolve(self, task, left, right, project_root, context):
        raise AssertionError("A cluster must not use the pairwise resolver")


class ContractInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The contract defines discount_percent as a percentage.",
            confidence=0.99,
            files_examined=["CONTRACT.md"],
            assertions=[Assertion(key=KEY, value="percentage")],
        )


def prepare_cluster(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pricing.py").write_text("VALUE = 1\n")
    store = SQLiteGraphStore(tmp_path / "cluster.db")
    supervisor = Supervisor(store, ThreeClaimInvestigator())
    first = supervisor.run("Interpret discount_percent", project)
    second = supervisor.run("Interpret discount_percent", project, force_investigation=True)
    third = supervisor.run("Interpret discount_percent", project, force_investigation=True)
    return store, first, second, third


def test_three_claims_create_one_cluster_with_corroboration_and_outlier(tmp_path: Path) -> None:
    store, first, second, third = prepare_cluster(tmp_path)

    assert len(third.resolution_tasks) == 1
    assert len(third.conflict_clusters) == 1
    cluster = third.conflict_clusters[0]
    assert set(cluster.claim_ids) == {first.claim.id, second.claim.id, third.claim.id}
    assert set(cluster.corroborated_claim_ids) == {first.claim.id, second.claim.id}
    assert cluster.outlier_claim_ids == [third.claim.id]
    assert [(item.value, len(item.claim_ids)) for item in cluster.interpretations] == [
        ("percentage", 2),
        ("fixed amount", 1),
    ]
    assert third.resolution_tasks[0].conflict_cluster_id == cluster.id
    assert sum(edge.relation == GraphRelation.CORROBORATES for edge in store.edges()) == 1
    assert sum(edge.relation == GraphRelation.OUTLIER for edge in store.edges()) == 1
    assert len(store.conflict_clusters()) == 1


def test_cluster_resolution_adjudicates_every_original_claim(tmp_path: Path) -> None:
    store, first, second, third = prepare_cluster(tmp_path)
    task = third.resolution_tasks[0]
    resolver = ClusterResolver()

    outcome = ResolutionExecutor(store, resolver).execute(task.id)

    assert outcome.task.status == TaskStatus.DONE
    assert set(outcome.adjudicated_claim.resolved_claim_ids) == {
        first.claim.id,
        second.claim.id,
        third.claim.id,
    }
    cluster = store.get_conflict_cluster(task.conflict_cluster_id)
    assert cluster.status == ClusterStatus.RESOLVED
    assert cluster.selected_value == "percentage"
    assert cluster.resolved_claim_id == outcome.adjudicated_claim.id
    assert sum(edge.relation == GraphRelation.RESOLVES for edge in store.edges()) == 3
    assert any(edge.relation == GraphRelation.RESOLVES_CLUSTER for edge in store.edges())
    assert sum(edge.relation == GraphRelation.DERIVED_FROM for edge in store.edges()) == 3


def test_cluster_gathers_evidence_then_reuses_completed_work(tmp_path: Path) -> None:
    store, _, _, third = prepare_cluster(tmp_path)
    resolver = ClusterResolver(require_follow_up=True)
    investigator = ContractInvestigator()
    config = PursuitConfig(max_retries_per_task=3, max_codex_calls=4)
    runner = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        config,
        FollowUpExecutor(store, investigator),
    )

    first_run = runner.pursue(third.task.id)
    replay = runner.pursue(third.task.id)

    assert first_run.status == TaskStatus.DONE
    assert first_run.codex_calls == 3
    assert resolver.calls == 2
    assert investigator.calls == 1
    assert len(resolver.contexts[1].follow_up_claims) == 1
    assert replay.status == TaskStatus.DONE
    assert replay.codex_calls == 0
    assert resolver.calls == 2
    assert investigator.calls == 1


def test_cluster_can_remain_explicitly_unresolved(tmp_path: Path) -> None:
    store, _, _, third = prepare_cluster(tmp_path)
    resolver = ClusterResolver(require_follow_up=True)
    runner = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        PursuitConfig(max_retries_per_task=1, max_codex_calls=1),
    )

    outcome = runner.pursue(third.task.id)

    assert outcome.status == TaskStatus.STOPPED
    cluster = store.get_conflict_cluster(third.resolution_tasks[0].conflict_cluster_id)
    assert cluster.status == ClusterStatus.UNRESOLVED
    assert cluster.resolved_claim_id is None


def test_cluster_classifies_every_interpretation_without_calling_losing_groups_outliers(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pricing.py").write_text("VALUE = 1\n")
    store = SQLiteGraphStore(tmp_path / "cluster.db")
    supervisor = Supervisor(
        store,
        ThreeClaimInvestigator(
            ["percentage", "fixed amount", "percentage", "basis points", "fixed amount"]
        ),
    )

    runs = [
        supervisor.run(
            "Interpret discount_percent", project, force_investigation=index > 0
        )
        for index in range(5)
    ]
    cluster = runs[-1].conflict_clusters[0]

    assert len(store.conflict_clusters()) == 1
    assert len(
        [task for task in store.tasks() if task.conflict_cluster_id == cluster.id]
    ) == 1
    assert sorted(len(item.claim_ids) for item in cluster.interpretations) == [1, 2, 2]
    assert len(cluster.corroborated_claim_ids) == 4
    assert len(cluster.outlier_claim_ids) == 1
    assert sum(edge.relation == GraphRelation.CORROBORATES for edge in store.edges()) == 2
    assert sum(edge.relation == GraphRelation.CONTRADICTS for edge in store.edges()) == 8

    outcome = ResolutionExecutor(store, ClusterResolver()).execute(
        runs[-1].resolution_tasks[0].id
    )

    assert outcome.task.status == TaskStatus.DONE
    assert outcome.result is not None
    assert set(outcome.result.corroborated_claim_ids) == set(
        cluster.corroborated_claim_ids
    )
    assert outcome.result.outlier_claim_ids == cluster.outlier_claim_ids
