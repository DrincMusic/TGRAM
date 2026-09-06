from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rlmgraph.dashboard import _chat_turn_payload
from rlmgraph.models import (
    Assertion,
    ChatScope,
    ChatTurn,
    Claim,
    Evidence,
    InvestigationResult,
    Task,
    TaskStatus,
)
from rlmgraph.onboarding import ReadOnlyViolation
from rlmgraph.recursive_investigation import RecursiveInvestigationSupervisor
from rlmgraph.store import SQLiteGraphStore


def test_recursive_investigation_can_disable_wall_clock_expiration() -> None:
    supervisor = RecursiveInvestigationSupervisor(
        SimpleNamespace(), SimpleNamespace(),
        max_model_calls=32, max_wall_time_seconds=None,
    )

    assert supervisor._expired(float("-inf")) is False
    assert supervisor.max_model_calls == 32


def test_investigation_rejects_empty_provenance_paths() -> None:
    with pytest.raises(ValidationError):
        InvestigationResult(
            conclusion="Unsupported", confidence=.5, files_examined=[""]
        )
    with pytest.raises(ValidationError):
        InvestigationResult(
            conclusion="Unsupported", confidence=.5,
            evidence=[Evidence(path="", detail="No provenance")],
        )


class PlannerSynthesizer:
    def __init__(self) -> None:
        self.planning_prompts: list[str] = []
        self.synthesis_findings: list[Claim] = []

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.planning_prompts.append(question)
        return InvestigationResult(
            conclusion="Plan only", confidence=.5,
            unresolved_questions=[
                "What behavior is actually implemented?",
                "What evidence contradicts the stated design?",
            ],
        )

    def synthesize(self, question: str, findings: list[Claim]) -> InvestigationResult:
        self.synthesis_findings = findings
        return InvestigationResult(
            conclusion="The implementation and stated design disagree.", confidence=.9,
            evidence=[Evidence(path="core.py", line=1, detail="Observed implementation")],
            files_examined=["core.py"],
        )


class SynthesisTimeout(PlannerSynthesizer):
    def synthesize(self, question: str, findings: list[Claim]) -> InvestigationResult:
        raise TimeoutError("synthesis exceeded its deadline")


class BranchSupervisor:
    def __init__(self, store: SQLiteGraphStore, root: Path) -> None:
        self.store = store
        self.root = root
        self.questions: list[str] = []

    def run(self, question: str, project_root: Path, *, force_investigation: bool):
        self.questions.append(question)
        task = Task.create(question, self.root, f"fp-{len(self.questions)}", "state")
        task.output_claim_id = None
        task.status = TaskStatus.DONE
        claim = Claim(
            fingerprint=task.fingerprint, project_fingerprint="state",
            project_root=str(self.root), subject=question, producer="branch",
            conclusion=f"Finding for {question}", confidence=.8,
            evidence=[Evidence(path="core.py", line=len(self.questions), detail=question)],
            files_examined=["core.py"],
            unresolved_questions=(
                ["Which runtime path selects this behavior?"]
                if len(self.questions) == 1 else []
            ),
            assertions=[
                Assertion(
                    key="system.behavior",
                    value="implemented" if len(self.questions) == 1 else "not implemented",
                )
            ],
        )
        task.output_claim_id = claim.id
        self.store.save_task(task)
        self.store.save_claim(task, claim)
        return SimpleNamespace(
            task=task, claim=claim, cache_hit=False, investigation_calls=1,
        )


class BoundedInvestigator:
    def __init__(self) -> None:
        self.branch_calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        assert "Workflow fact search" in question
        if question.startswith("Plan a repository investigation"):
            assert not list(project_root.rglob("*.py"))
            assert "Indexed files:" in question and "core.py" in question
            return InvestigationResult(
                conclusion="Plan", confidence=.5,
                unresolved_questions=[
                    "Inspect the core behavior implementation.",
                    "Find counterevidence in the core implementation.",
                ],
            )
        self.branch_calls += 1
        assert sorted(path.name for path in project_root.rglob("*.py")) == ["core.py"]
        return InvestigationResult(
            conclusion=f"Bounded finding {self.branch_calls}", confidence=.8,
            evidence=[Evidence(path="core.py", line=1, detail="bounded")],
            files_examined=["core.py"],
        )

    def synthesize(self, question: str, findings: list[Claim]) -> InvestigationResult:
        return InvestigationResult(
            conclusion="Bounded synthesis", confidence=.85,
            evidence=[Evidence(path="core.py", line=1, detail="synthesized")],
            files_examined=["core.py"],
        )


class RejectingBranchInvestigator(BoundedInvestigator):
    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        if question.startswith("Plan a repository investigation"):
            return InvestigationResult(
                conclusion="Plan", confidence=.5,
                unresolved_questions=[
                    "Inspect forbidden core behavior.", "Inspect core behavior."
                ],
            )
        if "forbidden" in question:
            raise ReadOnlyViolation("reported an unauthorized path")
        return super().investigate(question, project_root)


def test_rejected_branch_is_visible_and_does_not_abort_other_branches(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "core.py").write_text("CORE_BEHAVIOR = True\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    result = RecursiveInvestigationSupervisor(
        store, RejectingBranchInvestigator()
    ).run("How does core behavior work?", project)

    rejected = [task for task in result.sub_tasks if task.status == TaskStatus.STOPPED]
    assert len(rejected) == 1
    assert "unauthorized path" in (rejected[0].last_error or "")
    assert result.finding_claims
    assert result.task.status == TaskStatus.RECURSE
    assert any("Rejected branch" in gap for gap in result.claim.unresolved_questions)


def test_generic_recursive_investigation_persists_visible_task_tree_and_conflicts(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "core.py").write_text("BEHAVIOR = 'actual'\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    investigator = PlannerSynthesizer()
    branches = BranchSupervisor(store, project)
    supervisor = RecursiveInvestigationSupervisor(
        store, investigator, branch_supervisor=branches,
        max_depth=2, max_branches=3, max_model_calls=8,
    )
    progress = []

    result = supervisor.run(
        "Does this system implement its stated recursive behavior?",
        project, force_investigation=True,
        progress=lambda stage, detail: progress.append((stage, detail)),
    )

    assert result.planning_questions == [
        "What behavior is actually implemented?",
        "What evidence contradicts the stated design?",
    ]
    assert len(result.sub_tasks) == 3
    assert {task.depth for task in result.sub_tasks} == {1, 2}
    assert all(task.parent_task_id for task in result.sub_tasks)
    assert any(task.parent_task_id != result.task.id for task in result.sub_tasks)
    assert result.claim.source_claim_ids == [item.id for item in result.finding_claims]
    assert investigator.synthesis_findings == result.finding_claims
    assert result.conflicts
    assert result.investigation_calls == 5  # plan + three branches + synthesis
    assert result.task.status.value == "DONE"
    edges = store.edges()
    assert sum(edge.relation.value == "SPAWNED" for edge in edges) == 3
    assert sum(edge.relation.value == "SYNTHESIZED_FROM" for edge in edges) == 3
    assert any(edge.relation.value == "CONTRADICTS" for edge in edges)
    assert not result.budget_exhausted
    assert progress[0][0] == "EVIDENCE_PLANNING"
    assert any(stage == "EVIDENCE_BRANCH" and "depth" in detail for stage, detail in progress)
    assert progress[-1][0] == "EVIDENCE_SYNTHESIS"

    turn = ChatTurn(
        session_id="SESSION-1", ordinal=1, user_message="Does it recurse?",
        answer=result.claim.conclusion, scope=ChatScope.SYSTEM,
        route="RLM_SYSTEM_INVESTIGATION", routing_confidence=1,
        claim_confidence=result.claim.confidence, task_id=result.task.id,
        claim_id=result.claim.id,
    )
    restored = _chat_turn_payload(store, turn)
    assert len(restored["task_tree"]) == 4
    assert {item["depth"] for item in restored["task_tree"]} == {0, 1, 2}


def test_synthesis_timeout_returns_strongest_completed_branch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "core.py").write_text("BEHAVIOR = 'actual'\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    result = RecursiveInvestigationSupervisor(
        store, SynthesisTimeout(),
        branch_supervisor=BranchSupervisor(store, project),
        max_depth=1, max_branches=2, max_model_calls=6,
    ).run("What is implemented?", project, force_investigation=True)

    assert result.claim.conclusion.startswith("Finding for")
    assert result.budget_exhausted is True
    assert any(
        "Partial evidence returned" in gap for gap in result.claim.unresolved_questions
    )


def test_recursive_branches_use_bounded_indexed_slices_and_exact_slice_reuse(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "core.py").write_text("CORE_BEHAVIOR = True\n", encoding="utf-8")
    (project / "unrelated.py").write_text("SECRET_CONTEXT = True\n", encoding="utf-8")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    investigator = BoundedInvestigator()
    supervisor = RecursiveInvestigationSupervisor(store, investigator)

    first = supervisor.run("How does core behavior work?", project)
    assert investigator.branch_calls == 2
    assert all(task.relevant_files == ["core.py"] for task in first.sub_tasks)
    assert all(claim.files_examined == ["core.py"] for claim in first.finding_claims)

    second = supervisor.run("How does core behavior work?", project)
    assert investigator.branch_calls == 2
    assert second.cache_hit is True
    assert second.reuse_type == "exact-recursive-replay"
    assert second.investigation_calls == 0
    assert [claim.id for claim in second.finding_claims] == [
        claim.id for claim in first.finding_claims
    ]
