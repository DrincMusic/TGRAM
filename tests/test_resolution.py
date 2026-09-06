from pathlib import Path

import pytest

from rlmgraph.models import (
    Assertion,
    ClaimKind,
    GraphRelation,
    InvestigationResult,
    ResolutionChoice,
    ResolutionResult,
    TaskStatus,
)
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor

KEY = "discounted_price.discount_percent.interpretation"


class SequenceInvestigator:
    def __init__(self) -> None:
        self.values = iter(["percentage", "fixed amount"])

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = next(self.values)
        return InvestigationResult(
            conclusion=f"discount_percent is {value}",
            confidence=0.9,
            files_examined=["widget.py"],
            assertions=[Assertion(key=KEY, value=value)],
        )


class StaticResolver:
    def __init__(self, result: ResolutionResult) -> None:
        self.result = result
        self.calls = 0
        self.received = None

    def resolve(self, task, left, right, project_root, context):
        self.calls += 1
        self.received = (task, left, right, project_root, context)
        return self.result


class NoCallInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        raise AssertionError("post-resolution task should reuse the adjudicated claim")


def prepare_conflict(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("def discounted_price(price, percent): return price-percent\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    supervisor = Supervisor(store, SequenceInvestigator())
    first = supervisor.run("What does discount_percent represent?", project)
    second = supervisor.run(
        "What does discount_percent represent?", project, force_investigation=True
    )
    return project, store, first, second, second.resolution_tasks[0]


def resolution(choice: ResolutionChoice, value: str | None, confidence: float = 0.95):
    return ResolutionResult(
        selected_claim=choice,
        resolved_assertion=Assertion(key=KEY, value=value) if value else None,
        rationale=f"Repository evidence establishes {value}.",
        confidence=confidence,
    )


@pytest.mark.parametrize(
    ("choice", "value"),
    [
        (ResolutionChoice.LEFT, "percentage"),
        (ResolutionChoice.RIGHT, "fixed amount"),
    ],
)
def test_successful_resolution_persists_adjudication_and_enables_reuse(
    tmp_path: Path, choice: ResolutionChoice, value: str
) -> None:
    project, store, first, second, task = prepare_conflict(tmp_path)
    resolver = StaticResolver(resolution(choice, value))

    outcome = ResolutionExecutor(store, resolver).execute(task.id)

    assert resolver.calls == 1
    assert {resolver.received[1].id, resolver.received[2].id} == {
        first.claim.id,
        second.claim.id,
    }
    assert outcome.task.status == TaskStatus.DONE
    assert outcome.adjudicated_claim is not None
    adjudicated = outcome.adjudicated_claim
    assert adjudicated.kind == ClaimKind.ADJUDICATED
    assert adjudicated.assertions == [Assertion(key=KEY, value=value)]
    assert adjudicated.resolved_claim_ids == [first.claim.id, second.claim.id]
    assert outcome.task.resolved_claim_id == adjudicated.id
    assert len(store.claims()) == 3

    edges = store.edges()
    assert any(edge.relation == GraphRelation.CONTRADICTS for edge in edges)
    assert any(
        edge.source == task.id
        and edge.relation == GraphRelation.PRODUCED
        and edge.target == adjudicated.id
        for edge in edges
    )
    assert sum(
        edge.source == adjudicated.id and edge.relation == GraphRelation.RESOLVES
        for edge in edges
    ) == 2

    no_call = NoCallInvestigator()
    later = Supervisor(store, no_call).run(
        "How does discounted_price interpret discount_percent?", project
    )
    assert later.cache_hit is True
    assert later.reuse_type == "semantic"
    assert later.claim.id == adjudicated.id
    assert later.investigation_calls == 0
    assert no_call.calls == 0


@pytest.mark.parametrize(
    "result",
    [
        resolution(ResolutionChoice.NEITHER, None),
        resolution(ResolutionChoice.LEFT, "percentage", confidence=0.4),
        ResolutionResult(
            selected_claim=ResolutionChoice.LEFT,
            resolved_assertion=Assertion(key=KEY, value="percentage"),
            rationale="Evidence is incomplete.",
            confidence=0.95,
            unresolved_questions=["Which contract is authoritative?"],
        ),
    ],
)
def test_unresolved_or_low_confidence_resolution_recurses(
    tmp_path: Path, result: ResolutionResult
) -> None:
    _, store, _, _, task = prepare_conflict(tmp_path)

    outcome = ResolutionExecutor(store, StaticResolver(result)).execute(task.id)

    assert outcome.task.status == TaskStatus.RECURSE
    assert outcome.adjudicated_claim is None
    assert len(store.claims()) == 2
    assert not any(edge.relation == GraphRelation.PRODUCED for edge in store.edges())
