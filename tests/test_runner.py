from pathlib import Path

from rlmgraph.followup import FollowUpExecutor
from rlmgraph.models import (
    Assertion,
    ClaimValidity,
    InvestigationResult,
    PursuitConfig,
    ResolutionChoice,
    ResolutionResult,
    StoppingReason,
    TaskStatus,
)
from rlmgraph.planner import RecursivePlanner
from rlmgraph.resolution import ResolutionExecutor
from rlmgraph.runner import RecursiveRunner
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor

KEY = "discounted_price.discount_percent.interpretation"


class ConflictInvestigator:
    def __init__(self) -> None:
        self.values = iter(["percentage", "fixed amount"])

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        value = next(self.values)
        return InvestigationResult(
            conclusion=value,
            confidence=0.9,
            files_examined=["widget.py"],
            assertions=[Assertion(key=KEY, value=value)],
        )


class Resolver:
    def __init__(self, confidence: float = 0.95, failures: int = 0) -> None:
        self.confidence = confidence
        self.failures = failures
        self.calls = 0

    def resolve(self, task, left, right, project_root, context):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError(f"transient failure {self.calls}")
        return ResolutionResult(
            selected_claim=ResolutionChoice.LEFT,
            resolved_assertion=left.assertions[0],
            rationale="Left claim is supported by the repository.",
            confidence=self.confidence,
        )


def conflict(tmp_path: Path, name: str = "project"):
    project = tmp_path / name
    project.mkdir()
    (project / "widget.py").write_text("VALUE = 1\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    supervisor = Supervisor(store, ConflictInvestigator())
    supervisor.run("What does discount_percent mean?", project)
    parent = supervisor.run(
        "What does discount_percent mean?", project, force_investigation=True
    )
    return store, parent.task, parent.resolution_tasks[0]


def runner(store, resolver, **config):
    settings = PursuitConfig(**config)
    return RecursiveRunner(
        store, ResolutionExecutor(store, resolver, settings.minimum_confidence), settings
    )


def test_runner_automatically_completes_child_and_parent(tmp_path: Path) -> None:
    store, parent, child = conflict(tmp_path)
    resolver = Resolver()

    outcome = runner(store, resolver).pursue(parent.id)

    assert outcome.status == TaskStatus.DONE
    assert outcome.stopping_reason == StoppingReason.COMPLETED
    assert outcome.codex_calls == 1
    assert [task.id for task in outcome.tasks] == [parent.id, child.id]
    persisted_parent = store.get_task(parent.id)
    persisted_child = store.get_task(child.id)
    assert persisted_parent.status == TaskStatus.DONE
    assert persisted_child.status == TaskStatus.DONE
    assert persisted_child.depth == 1
    assert persisted_child.attempt_count == 1
    assert persisted_child.started_at is not None
    assert persisted_child.completed_at is not None
    assert persisted_child.stopping_reason == StoppingReason.COMPLETED
    execution = store.execution_attempts(child.id)
    assert len(execution) == 1
    assert execution[0].actual_route.value == "RESOLVER"
    assert execution[0].outcome.value == "SUCCEEDED"


def test_runner_stops_at_depth_limit(tmp_path: Path) -> None:
    store, parent, child = conflict(tmp_path)

    outcome = runner(store, Resolver(), max_depth=0).pursue(parent.id)

    assert outcome.status == TaskStatus.STOPPED
    assert outcome.stopping_reason == StoppingReason.MAX_DEPTH
    assert outcome.codex_calls == 0
    assert store.get_task(child.id).stopping_reason == StoppingReason.MAX_DEPTH
    assert store.get_task(parent.id).stopping_reason == StoppingReason.MAX_DEPTH


def test_runner_call_budget_stop_can_resume_without_replaying_done_work(
    tmp_path: Path,
) -> None:
    store, parent, child = conflict(tmp_path)
    first_resolver = Resolver()
    first = runner(store, first_resolver, max_codex_calls=0).pursue(parent.id)
    assert first.stopping_reason == StoppingReason.CALL_BUDGET
    assert first_resolver.calls == 0
    assert store.get_task(parent.id).stopping_reason == StoppingReason.CALL_BUDGET

    second_resolver = Resolver()
    second = runner(store, second_resolver, max_codex_calls=1).pursue(parent.id)
    assert second.status == TaskStatus.DONE
    assert second.codex_calls == 1
    assert second_resolver.calls == 1
    assert store.get_task(child.id).attempt_count == 1

    third_resolver = Resolver()
    third = runner(store, third_resolver, max_codex_calls=1).pursue(parent.id)
    assert third.status == TaskStatus.DONE
    assert third.codex_calls == 0
    assert third_resolver.calls == 0


def test_runner_retries_then_records_exhaustion(tmp_path: Path) -> None:
    store, parent, child = conflict(tmp_path)
    resolver = Resolver(failures=5)

    outcome = runner(store, resolver, max_retries_per_task=2).pursue(parent.id)

    assert outcome.stopping_reason == StoppingReason.RETRY_EXHAUSTED
    assert outcome.codex_calls == 2
    persisted = store.get_task(child.id)
    assert persisted.attempt_count == 2
    assert persisted.status == TaskStatus.STOPPED
    assert "transient failure 2" in persisted.last_error
    assert store.get_task(parent.id).stopping_reason == StoppingReason.RETRY_EXHAUSTED


def test_runner_detects_lineage_cycle_without_calling_resolver(tmp_path: Path) -> None:
    store, _, child = conflict(tmp_path)
    child.parent_task_id = child.id
    store.save_task(child)
    resolver = Resolver()

    outcome = runner(store, resolver).pursue(child.id)

    assert outcome.stopping_reason == StoppingReason.CYCLE_DETECTED
    assert outcome.codex_calls == 0
    assert resolver.calls == 0


def test_runner_processes_nested_children(tmp_path: Path) -> None:
    store, _, first_child = conflict(tmp_path, "project-one")
    _, _, second_child = conflict(tmp_path, "project-two")
    second_child.parent_task_id = first_child.id
    second_child.depth = first_child.depth + 1
    store.save_task(second_child)

    outcome = runner(store, Resolver()).pursue(first_child.id)

    assert outcome.status == TaskStatus.DONE
    assert outcome.codex_calls == 2
    assert [task.id for task in outcome.tasks] == [first_child.id, second_child.id]


def test_runner_stops_on_low_confidence(tmp_path: Path) -> None:
    store, parent, child = conflict(tmp_path)

    outcome = runner(store, Resolver(confidence=0.2)).pursue(parent.id)

    assert outcome.stopping_reason == StoppingReason.LOW_CONFIDENCE
    assert outcome.codex_calls == 1
    assert store.get_task(child.id).status == TaskStatus.RECURSE
    assert store.get_task(parent.id).stopping_reason == StoppingReason.LOW_CONFIDENCE


class EvidenceInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(
            conclusion="The implementation treats the value as a percentage.",
            confidence=0.98,
            files_examined=["widget.py"],
            assertions=[Assertion(key=KEY, value="percentage")],
        )


class EvidenceAwareResolver:
    def __init__(self) -> None:
        self.contexts = []

    def resolve(self, task, left, right, project_root, context):
        self.contexts.append(context)
        if not context.follow_up_claims:
            return ResolutionResult(
                selected_claim=ResolutionChoice.NEITHER,
                resolved_assertion=None,
                rationale="The conflicting reports do not cite the implementation contract.",
                confidence=0.4,
                unresolved_questions=["What behavior does widget.py implement?"],
            )
        return ResolutionResult(
            selected_claim=ResolutionChoice.LEFT,
            resolved_assertion=left.assertions[0],
            rationale="The targeted follow-up inspected the implementation.",
            confidence=0.98,
        )


def test_runner_gathers_targeted_evidence_then_retries_resolution(tmp_path: Path) -> None:
    store, parent, resolution_task = conflict(tmp_path)
    resolver = EvidenceAwareResolver()
    investigator = EvidenceInvestigator()
    settings = PursuitConfig(max_retries_per_task=3, max_codex_calls=4)
    recursive = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        settings,
        FollowUpExecutor(store, investigator),
    )

    outcome = recursive.pursue(parent.id)

    assert outcome.status == TaskStatus.DONE
    assert outcome.codex_calls == 3
    assert investigator.calls == 1
    assert len(resolver.contexts) == 2
    assert resolver.contexts[0].follow_up_claims == []
    assert len(resolver.contexts[1].follow_up_claims) == 1
    assert len(resolver.contexts[1].previous_attempts) == 1
    follow_ups = [task for task in outcome.tasks if task.kind.value == "FOLLOW_UP"]
    assert len(follow_ups) == 1
    assert follow_ups[0].output_claim_id is not None
    assert len(store.resolution_attempts(resolution_task.id)) == 2

    planning_run = outcome.planning_run
    assert planning_run is not None
    assert planning_run.status == TaskStatus.DONE
    assert planning_run.model_calls_used == 3
    assert planning_run.retrieval_tokens_used <= planning_run.max_retrieval_tokens
    decisions = store.plan_decisions(parent.id)
    assert {item.action.value for item in decisions} >= {
        "CREATED",
        "ROUTED",
        "CONSUMED",
        "COMPLETED",
    }
    created = next(item for item in decisions if item.action.value == "CREATED")
    assert created.priority > 0
    assert created.route is not None
    assert created.dependency_task_ids == [resolution_task.id]

    replay = recursive.pursue(parent.id)
    assert replay.status == TaskStatus.DONE
    assert replay.codex_calls == 0
    assert investigator.calls == 1
    assert len(resolver.contexts) == 2
    assert len(store.resolution_attempts(resolution_task.id)) == 2


def test_runner_hard_stops_before_exceeding_retrieval_budget(tmp_path: Path) -> None:
    store, parent, child = conflict(tmp_path)
    resolver = Resolver()

    outcome = runner(store, resolver, max_retrieval_tokens=1).pursue(parent.id)

    assert outcome.stopping_reason == StoppingReason.RETRIEVAL_TOKEN_BUDGET
    assert resolver.calls == 0
    assert outcome.planning_run is not None
    assert outcome.planning_run.retrieval_tokens_used == 0
    assert outcome.planning_run.retrieval_tokens_used <= 1
    stopped = [item for item in store.plan_decisions(parent.id) if item.action.value == "STOPPED"]
    assert any(item.task_id == child.id for item in stopped)


def test_runner_hard_stops_on_wall_time_without_call(tmp_path: Path) -> None:
    store, parent, _ = conflict(tmp_path)
    resolver = Resolver()

    outcome = runner(store, resolver, max_wall_time_seconds=0).pursue(parent.id)

    assert outcome.stopping_reason == StoppingReason.WALL_TIME_BUDGET
    assert resolver.calls == 0
    assert outcome.planning_run is not None
    assert outcome.planning_run.elapsed_seconds >= 0


def test_runner_reuses_equivalent_completed_follow_up(tmp_path: Path) -> None:
    store, parent, _resolution_task = conflict(tmp_path)
    question = "What behavior does widget.py implement?"
    fingerprint = __import__("rlmgraph.fingerprint", fromlist=["task_fingerprint"]).task_fingerprint(
        question, parent.project_fingerprint
    )
    from rlmgraph.models import Task, TaskKind

    prior = Task(
        question=question,
        fingerprint=fingerprint,
        project_fingerprint=parent.project_fingerprint,
        project_root=parent.project_root,
        kind=TaskKind.FOLLOW_UP,
        parent_task_id=None,
        status=TaskStatus.DONE,
        output_claim_id=store.claims()[0].id,
    )
    store.save_task(prior)
    resolver = EvidenceAwareResolver()
    investigator = EvidenceInvestigator()
    recursive = RecursiveRunner(
        store,
        ResolutionExecutor(store, resolver),
        PursuitConfig(max_codex_calls=3),
        FollowUpExecutor(store, investigator),
    )

    outcome = recursive.pursue(parent.id)

    assert outcome.status == TaskStatus.DONE
    assert investigator.calls == 0
    assert outcome.codex_calls == 2
    follow_up = next(task for task in outcome.tasks if task.kind == TaskKind.FOLLOW_UP)
    assert follow_up.reused_claim_id == prior.output_claim_id
    reused = [item for item in store.plan_decisions(parent.id) if item.action.value == "REUSED"]
    assert reused
    assert outcome.planning_run is not None
    assert outcome.planning_run.duplicate_investigations == 0
    memory_attempts = store.execution_attempts(follow_up.id)
    assert len(memory_attempts) == 1
    assert memory_attempts[0].actual_route.value == "MEMORY"
    assert memory_attempts[0].outcome.value == "REUSED"


def test_planner_converts_weak_and_stale_evidence_into_distinct_tasks(
    tmp_path: Path,
) -> None:
    store, parent, resolution_task = conflict(tmp_path)
    weak_stale = store.get_claim(resolution_task.conflicting_claim_ids[0])
    assert weak_stale is not None
    weak_stale.confidence = 0.2
    weak_stale.validity_status = ClaimValidity.INVALIDATED
    store.update_claim(weak_stale)
    recursive = runner(store, Resolver())
    planner = RecursivePlanner(store, parent.id, recursive.config)

    children = recursive._create_follow_ups(resolution_task, [], planner)

    assert len(children) == 2
    questions = {child.question for child in children}
    assert any("stale dependency" in question for question in questions)
    assert any("weakly supported" in question for question in questions)
    assert all(child.priority > 0 and child.route is not None for child in children)
