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
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class UnusedInvestigator:
    def investigate(self, question: str, project_root: Path):
        raise AssertionError("Virtual token expansion must not invoke investigation")


def recurring_case(root: Path, confidence: float = 1.0) -> BenchmarkCase:
    root.mkdir(parents=True, exist_ok=True)
    (root / "contract.txt").write_text("stable-rule\n")
    evidence = [
        Claim(
            id=f"SHARED-EVIDENCE-{index}",
            fingerprint=f"shared-evidence-{index}",
            project_root=str(root.resolve()),
            subject=f"Independent supporting evidence {index}",
            producer="PathwayFixture",
            conclusion="The contract supports stable-rule.",
            confidence=confidence,
            evidence=[Evidence(path="contract.txt", line=1, detail="Stable fixture")],
            files_examined=["contract.txt"],
        )
        for index in range(2)
    ]
    noise = [
        Claim(
            id=f"SHARED-NOISE-{index}",
            fingerprint=f"shared-noise-{index}",
            project_root=str(root.resolve()),
            subject=f"Unrelated subsystem {index}",
            producer="PathwayFixture",
            conclusion="Verbose irrelevant history " * 10,
            confidence=0.9,
        )
        for index in range(12)
    ]
    question = "What stable rule governs this fixture?"
    answer = Claim(
        id="SHARED-ANSWER",
        fingerprint="shared-answer",
        project_root=str(root.resolve()),
        subject=question,
        producer="PathwayFixture",
        conclusion="stable-rule",
        confidence=confidence,
        evidence=[Evidence(path="contract.txt", line=1, detail="Stable fixture")],
        files_examined=["contract.txt"],
        source_claim_ids=[claim.id for claim in evidence],
    )
    return BenchmarkCase(
        id="recurring-path",
        question=question,
        project_root=root,
        claims=[*evidence, *noise, answer],
        expected_answer="stable-rule",
        answer_claim_id=answer.id,
        required_evidence_ids=[claim.id for claim in evidence],
    )


def test_recurring_stable_pathway_promotes_expands_and_saves_more_tokens(
    tmp_path: Path,
) -> None:
    store = SQLiteGraphStore(tmp_path / "pathways.db")
    runner = MemoryBenchmarkRunner(store)
    registry = VirtualPathwayRegistry(store)
    decisions = []
    pathway = None
    runs = []
    for _ in range(3):
        run = runner.run(recurring_case(tmp_path / "project"))
        runs.append(run)
        decision, promoted = registry.observe(run)
        decisions.append(decision)
        pathway = promoted or pathway

    assert [item.outcome for item in decisions] == [
        PromotionOutcome.REJECTED,
        PromotionOutcome.REJECTED,
        PromotionOutcome.ACCEPTED,
    ]
    assert pathway is not None
    assert pathway.token.startswith("[MEM:") and pathway.token.endswith(":v1]")
    assert pathway.access_frequency == 3
    assert len(pathway.supporting_reconstruction_ids) == 3
    assert len(pathway.source_claim_ids) == 3
    assert pathway.source_files

    shallow = registry.expand(pathway.token, depth=1)
    full = registry.expand(pathway.token, depth=4)
    assert shallow.complete and not shallow.claim_ids
    assert full.complete
    assert full.claim_ids == pathway.node_ids
    assert full.evidence and full.source_files
    assert any(item.startswith("TOKEN ") for item in full.expansion_trace)
    assert any(item.startswith("PATHWAY ") for item in full.expansion_trace)
    assert any(item.startswith("CLAIM ") for item in full.expansion_trace)
    assert any(item.startswith("EVIDENCE ") for item in full.expansion_trace)
    assert any(item.startswith("SOURCE ") for item in full.expansion_trace)
    assert registry.expand(pathway.token, max_tokens=1).complete is False

    token_result = registry.benchmark_token(
        runs[-1], pathway, answer_claim_id="SHARED-ANSWER"
    )
    assert token_result.correct
    assert token_result.evidence_preserved
    assert token_result.expansion_complete
    assert token_result.token_input_tokens < token_result.active_input_tokens
    assert token_result.additional_reduction > 0.5
    assert store.pathway_benchmarks()[0] == token_result
    assert any(
        edge.source == pathway.id
        and edge.relation == GraphRelation.PATHWAY_INCLUDES
        for edge in store.edges()
    )
    supervisor_expansion = Supervisor(store, UnusedInvestigator()).expand_memory(
        pathway.token
    )
    assert supervisor_expansion.complete
    assert supervisor_expansion.claim_ids == pathway.node_ids

    old_token = pathway.token
    (tmp_path / "project" / "contract.txt").write_text("changed-rule\n")
    stale_decision, stale_pathway = registry.observe(runs[-1])
    assert stale_decision.outcome == PromotionOutcome.REJECTED
    assert stale_decision.stale_claim_ids
    assert stale_pathway is None
    invalid = registry.expand(old_token)
    assert invalid.complete is False
    assert store.pathways()[0].lifecycle == PathwayLifecycle.INVALIDATED

    (tmp_path / "project" / "contract.txt").write_text("stable-rule\n")
    new_run = runner.run(recurring_case(tmp_path / "project"))
    _, replacement = registry.observe(new_run)
    assert replacement is not None
    assert replacement.version == 2
    assert replacement.token != old_token


def test_one_off_weak_and_contradictory_pathways_are_rejected(tmp_path: Path) -> None:
    one_store = SQLiteGraphStore(tmp_path / "one.db")
    one_runner = MemoryBenchmarkRunner(one_store)
    one_registry = VirtualPathwayRegistry(one_store)
    decision, pathway = one_registry.observe(
        one_runner.run(recurring_case(tmp_path / "one-project"))
    )
    assert decision.outcome == PromotionOutcome.REJECTED
    assert "requires 3" in decision.reason
    assert pathway is None

    weak_store = SQLiteGraphStore(tmp_path / "weak.db")
    weak_runner = MemoryBenchmarkRunner(weak_store)
    weak_registry = VirtualPathwayRegistry(weak_store)
    for _ in range(3):
        weak_run = weak_runner.run(recurring_case(tmp_path / "weak-project", 0.5))
    weak_decision, weak_pathway = weak_registry.observe(weak_run)
    assert weak_decision.outcome == PromotionOutcome.REJECTED
    assert "confidence" in weak_decision.reason
    assert weak_pathway is None

    conflict_store = SQLiteGraphStore(tmp_path / "conflict.db")
    conflict_runner = MemoryBenchmarkRunner(conflict_store)
    conflict_registry = VirtualPathwayRegistry(conflict_store)
    for _ in range(3):
        conflict_run = conflict_runner.run(recurring_case(tmp_path / "conflict-project"))
    conflict_store.save_edge(
        GraphEdge(
            source="SHARED-ANSWER",
            relation=GraphRelation.CONTRADICTS,
            target="SHARED-EVIDENCE-0",
        )
    )
    conflict_decision, conflict_pathway = conflict_registry.observe(conflict_run)
    assert conflict_decision.outcome == PromotionOutcome.REJECTED
    assert conflict_decision.contradictory_claim_ids
    assert conflict_pathway is None
