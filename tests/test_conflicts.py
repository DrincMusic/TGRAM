from pathlib import Path

from rlmgraph.models import (
    Assertion,
    GraphRelation,
    InvestigationResult,
    TaskKind,
    TaskStatus,
)
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class SequenceInvestigator:
    def __init__(self, results: list[InvestigationResult]) -> None:
        self.results = iter(results)
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return next(self.results)


def result(value: str) -> InvestigationResult:
    return InvestigationResult(
        conclusion=f"discount_percent is interpreted as {value}.",
        confidence=0.95,
        files_examined=["widget.py"],
        assertions=[
            Assertion(
                key="discounted_price.discount_percent.interpretation",
                value=value,
            )
        ],
    )


def test_conflicting_claims_create_edge_and_resolution_task(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("def discounted_price(): ...\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = SequenceInvestigator(
        [result("percentage"), result("fixed amount"), result("percentage")]
    )
    supervisor = Supervisor(store, investigator)

    first = supervisor.run("What does discount_percent represent?", project)
    second = supervisor.run(
        "What does discount_percent represent?",
        project,
        force_investigation=True,
    )

    assert second.cache_hit is False
    assert second.investigation_calls == 1
    assert second.task.status == TaskStatus.RECURSE
    assert len(second.conflicts) == 1
    conflict = second.conflicts[0]
    assert conflict.left_claim_id == first.claim.id
    assert conflict.right_claim_id == second.claim.id
    assert conflict.assertion_key == "discounted_price.discount_percent.interpretation"
    assert {conflict.left_value, conflict.right_value} == {"percentage", "fixed amount"}

    assert len(second.resolution_tasks) == 1
    resolution = second.resolution_tasks[0]
    assert resolution.kind == TaskKind.RESOLUTION
    assert resolution.status == TaskStatus.OPEN
    assert resolution.parent_task_id == second.task.id
    assert resolution.conflicting_claim_ids == [first.claim.id, second.claim.id]
    assert first.claim.id in resolution.question
    assert second.claim.id in resolution.question

    edges = store.edges()
    assert any(
        edge.source == first.claim.id
        and edge.relation == GraphRelation.CONTRADICTS
        and edge.target == second.claim.id
        for edge in edges
    )
    assert sum(edge.relation == GraphRelation.CONSIDERS for edge in edges) == 2
    persisted_resolution = next(task for task in store.tasks() if task.id == resolution.id)
    assert persisted_resolution.conflicting_claim_ids == [first.claim.id, second.claim.id]
    assert investigator.calls == 2
    assert len(store.claims()) == 2
    duplicate = supervisor._create_resolution_task(second.task, conflict)
    assert duplicate.id == resolution.id
    assert sum(task.kind == TaskKind.RESOLUTION for task in store.tasks()) == 1

    third = supervisor.run("What does discount_percent represent?", project)
    assert third.cache_hit is False
    assert third.investigation_calls == 1


def test_agreeing_claims_do_not_create_resolution_task(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "widget.py").write_text("def discounted_price(): ...\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = SequenceInvestigator([result("percentage"), result("Percentage")])
    supervisor = Supervisor(store, investigator)
    supervisor.run("What does discount_percent represent?", project)

    second = supervisor.run(
        "How is discount_percent interpreted?", project, force_investigation=True
    )

    assert second.task.status == TaskStatus.DONE
    assert second.conflicts == []
    assert second.resolution_tasks == []
    assert not any(edge.relation == GraphRelation.CONTRADICTS for edge in store.edges())
