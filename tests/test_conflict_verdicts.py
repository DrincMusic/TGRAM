from pathlib import Path

from rlmgraph.models import (
    Assertion,
    Evidence,
    GraphRelation,
    InvestigationResult,
    PursuitConfig,
    ResolutionChoice,
    ResolutionResult,
    TaskKind,
    TaskStatus,
    VerdictStatus,
)
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.runner import RecursiveRunner
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor

KEY = "discounted_price.discount_percent.interpretation"


class TwoFindingInvestigator:
    def __init__(self) -> None:
        self.values = iter(("percentage", "fixed amount"))
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"The value is interpreted as {value}.",
            confidence=0.9,
            evidence=[Evidence(path="widget.py", line=1, detail=f"Worker observed {value}.")],
            files_examined=["widget.py"],
            assertions=[Assertion(key=KEY, value=value)],
        )


class EvidenceResolver:
    def __init__(self, *, abstain: bool = False) -> None:
        self.abstain = abstain
        self.calls = 0

    def resolve(self, task, left, right, project_root, context):
        self.calls += 1
        if self.abstain:
            return ResolutionResult(
                selected_claim=ResolutionChoice.NEITHER,
                resolved_assertion=None,
                rationale="Neither worker supplied authoritative evidence.",
                confidence=0.45,
                unresolved_questions=["Which repository contract is authoritative?"],
            )
        return ResolutionResult(
            selected_claim=ResolutionChoice.LEFT,
            resolved_assertion=left.assertions[0],
            rationale="The implementation contract supports percentage semantics.",
            evidence=[Evidence(path="widget.py", line=1, detail="The implementation divides by 100.")],
            confidence=0.96,
        )


class NoCallInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        raise AssertionError("a related task must reuse the persisted verdict")


def prepare(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("RATE = percent / 100\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = TwoFindingInvestigator()
    supervisor = Supervisor(store, investigator)
    first = supervisor.run("What does discount_percent mean?", project)
    second = supervisor.run(
        "What does discount_percent mean?", project, force_investigation=True
    )
    return project, store, investigator, first, second


def test_bounded_resolution_persists_provenance_and_reuses_verdict(tmp_path: Path) -> None:
    project, store, investigator, first, second = prepare(tmp_path)
    resolver = EvidenceResolver()
    config = PursuitConfig(max_retries_per_task=1, max_codex_calls=1)
    recursive = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        config,
    )

    outcome = recursive.pursue(second.task.id)

    resolution_tasks = [task for task in store.tasks() if task.kind == TaskKind.RESOLUTION]
    assert len(resolution_tasks) == 1
    assert resolver.calls == 1
    assert outcome.status == TaskStatus.DONE
    verdicts = store.conflict_verdicts(resolution_tasks[0].id)
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.status == VerdictStatus.RESOLVED
    assert verdict.selected_value == "percentage"
    assert verdict.confidence == 0.96
    assert verdict.evidence == [
        Evidence(path="widget.py", line=1, detail="The implementation divides by 100.")
    ]
    assert verdict.confidence_threshold == config.minimum_confidence
    assert verdict.max_resolution_attempts == 1
    assert verdict.claim_ids == [first.claim.id, second.claim.id]
    assert verdict.supporting_claim_ids == [first.claim.id]
    assert verdict.contradicting_claim_ids == [second.claim.id]
    assert set(verdict.evidence_claim_ids) == {first.claim.id, second.claim.id}
    assert outcome.tasks[-1].conflict_verdict_id == verdict.id

    edges = store.edges()
    assert any(
        edge.source == resolution_tasks[0].id
        and edge.relation == GraphRelation.HAS_VERDICT
        and edge.target == verdict.id
        for edge in edges
    )
    assert any(
        edge.source == first.claim.id
        and edge.relation == GraphRelation.SUPPORTS_VERDICT
        and edge.target == verdict.id
        for edge in edges
    )
    assert any(
        edge.source == second.claim.id
        and edge.relation == GraphRelation.CONTRADICTS_VERDICT
        and edge.target == verdict.id
        for edge in edges
    )

    no_call = NoCallInvestigator()
    later = Supervisor(store, no_call).run(
        "How is discount_percent interpreted by discounted_price?", project
    )
    assert later.cache_hit is True
    assert later.investigation_calls == 0
    assert investigator.calls == 2
    assert no_call.calls == 0
    assert later.task.reused_verdict_id == verdict.id
    assert any(
        edge.source == later.task.id
        and edge.relation == GraphRelation.REUSED_VERDICT
        and edge.target == verdict.id
        for edge in store.edges()
    )


def test_weak_evidence_persists_unresolved_verdict_instead_of_guessing(
    tmp_path: Path,
) -> None:
    _, store, _, first, second = prepare(tmp_path)
    task = second.resolution_tasks[0]
    resolver = EvidenceResolver(abstain=True)

    outcome = ResolutionExecutor(
        store,
        resolver,
        confidence_threshold=0.75,
        max_resolution_attempts=1,
    ).execute(task.id)

    assert resolver.calls == 1
    assert outcome.task.status == TaskStatus.RECURSE
    assert outcome.adjudicated_claim is None
    assert outcome.verdict.status == VerdictStatus.UNRESOLVED
    assert outcome.verdict.selected_value is None
    assert outcome.verdict.supporting_claim_ids == []
    assert outcome.verdict.contradicting_claim_ids == []
    assert set(outcome.verdict.evidence_claim_ids) == {first.claim.id, second.claim.id}
    assert outcome.verdict.unresolved_questions == [
        "Which repository contract is authoritative?"
    ]
    assert outcome.verdict.max_resolution_attempts == 1
    assert len(store.conflict_verdicts(task.id)) == 1
    assert not any(claim.conflict_verdict_id for claim in store.claims())
