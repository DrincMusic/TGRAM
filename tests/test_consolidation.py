from pathlib import Path

from rlmgraph.models import (
    Assertion,
    ClaimValidity,
    Evidence,
    GraphRelation,
    InvestigationResult,
    MemoryLifecycle,
    MemoryTier,
    PromotionOutcome,
)
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class ContractInvestigator:
    def __init__(self, confidence: float = 0.95) -> None:
        self.confidence = confidence
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        value = (project_root / "contract.txt").read_text().strip()
        return InvestigationResult(
            conclusion=f"The governed rule is {value}.",
            confidence=self.confidence,
            evidence=[Evidence(path="contract.txt", line=1, detail="Authoritative rule")],
            files_examined=["contract.txt"],
            assertions=[Assertion(key="governed.rule", value=value)],
        )


class ConflictingInvestigator:
    def __init__(self) -> None:
        self.values = iter(["alpha", "beta"])

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"The governed rule is {value}.",
            confidence=0.95,
            evidence=[Evidence(path="contract.txt", line=1, detail="Ambiguous fixture")],
            assertions=[Assertion(key="governed.rule", value=value)],
        )


def project_at(tmp_path: Path, value: str = "safe-mode") -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "contract.txt").write_text(f"{value}\n")
    return project


def test_independent_episodes_consolidate_then_reuse_promotes_procedure(
    tmp_path: Path,
) -> None:
    project = project_at(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = ContractInvestigator()
    supervisor = Supervisor(store, investigator)

    first = supervisor.run("What is the governed project rule?", project)
    supervisor.run(
        "What is the governed project rule?", project, force_investigation=True
    )

    episodes = [
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.EPISODIC
    ]
    semantic = next(
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.SEMANTIC
    )
    decisions = store.promotion_decisions()
    assert first.claim.memory_tier == MemoryTier.EPISODIC
    assert [item.to_tier for item in first.claim.tier_history] == [
        MemoryTier.WORKING,
        MemoryTier.EPISODIC,
    ]
    assert len(episodes) == 2
    assert semantic.source_claim_ids == [claim.id for claim in episodes]
    assert semantic.memory_policy_decision_id == decisions[-1].id
    assert all(claim.memory_lifecycle == MemoryLifecycle.PROMOTED for claim in episodes)
    assert decisions[0].outcome == PromotionOutcome.REJECTED
    assert "requires 2" in decisions[0].reason
    assert decisions[1].outcome == PromotionOutcome.ACCEPTED
    assert decisions[1].observed_support == 2
    assert decisions[1].minimum_confidence == 0.8

    first_reuse = supervisor.run("What is the governed project rule?", project)
    second_reuse = supervisor.run("What is the governed project rule?", project)
    procedural = next(
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.PROCEDURAL
    )
    third_reuse = supervisor.run("What is the governed project rule?", project)

    assert first_reuse.claim.id == semantic.id
    assert first_reuse.reuse_type == "semantic"
    assert second_reuse.claim.id == semantic.id
    assert third_reuse.claim.id == procedural.id
    assert third_reuse.reuse_type == "procedural"
    assert semantic.id in procedural.source_claim_ids
    assert procedural.memory_policy_decision_id is not None
    assert store.get_claim(semantic.id).successful_reuse_count == 2
    assert store.get_claim(semantic.id).memory_lifecycle == MemoryLifecycle.PROMOTED
    assert store.promotion_decisions()[-2].outcome == PromotionOutcome.REJECTED
    assert store.promotion_decisions()[-1].outcome == PromotionOutcome.ACCEPTED
    assert any(
        edge.source == procedural.id
        and edge.relation == GraphRelation.CONSOLIDATED_FROM
        and edge.target == semantic.id
        for edge in store.edges()
    )
    assert any(edge.relation == GraphRelation.PROMOTED_TO for edge in store.edges())


def test_weak_single_and_contradictory_episodes_are_rejected(tmp_path: Path) -> None:
    weak_project = project_at(tmp_path / "weak")
    weak_store = SQLiteGraphStore(tmp_path / "weak.db")
    weak = Supervisor(weak_store, ContractInvestigator(confidence=0.5))
    weak.run("What is the governed project rule?", weak_project)
    weak.run(
        "What is the governed project rule?", weak_project, force_investigation=True
    )

    assert all(
        decision.outcome == PromotionOutcome.REJECTED
        for decision in weak_store.promotion_decisions()
    )
    assert not any(
        claim.memory_tier == MemoryTier.SEMANTIC for claim in weak_store.claims()
    )

    conflict_project = project_at(tmp_path / "conflict", "unchanged-source")
    conflict_store = SQLiteGraphStore(tmp_path / "conflict.db")
    conflict = Supervisor(conflict_store, ConflictingInvestigator())
    conflict.run("What is the governed project rule?", conflict_project)
    conflict.run(
        "What is the governed project rule?", conflict_project, force_investigation=True
    )

    last = conflict_store.promotion_decisions()[-1]
    assert last.outcome == PromotionOutcome.REJECTED
    assert last.contradictory_claim_ids
    assert set(last.rejected_claim_ids) == set(last.candidate_claim_ids)
    assert "Contradictory current episodes" in last.reason
    assert not any(
        claim.memory_tier == MemoryTier.SEMANTIC for claim in conflict_store.claims()
    )


def test_stale_episode_invalidates_dependent_semantic_and_procedural_memory(
    tmp_path: Path,
) -> None:
    project = project_at(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    supervisor = Supervisor(store, ContractInvestigator())
    supervisor.run("What is the governed project rule?", project)
    supervisor.run(
        "What is the governed project rule?", project, force_investigation=True
    )
    supervisor.run("What is the governed project rule?", project)
    supervisor.run("What is the governed project rule?", project)
    semantic = next(
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.SEMANTIC
    )
    procedural = next(
        claim for claim in store.claims() if claim.memory_tier == MemoryTier.PROCEDURAL
    )

    (project / "contract.txt").write_text("new-mode\n")
    result = supervisor.run("What is the governed project rule?", project)

    stale_semantic = store.get_claim(semantic.id)
    stale_procedural = store.get_claim(procedural.id)
    assert result.cache_hit is False
    assert stale_semantic.validity_status == ClaimValidity.INVALIDATED
    assert stale_semantic.memory_lifecycle == MemoryLifecycle.INVALIDATED
    assert stale_procedural.validity_status == ClaimValidity.INVALIDATED
    assert stale_procedural.memory_lifecycle == MemoryLifecycle.INVALIDATED
    assert semantic.id != result.claim.id and procedural.id != result.claim.id
    assert store.promotion_decisions()[-1].stale_claim_ids
