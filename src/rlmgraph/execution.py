from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .adapters import Investigator
from .models import (
    ExecutionAttempt,
    ExecutionOutcome,
    InvestigationResult,
    Task,
    TaskRoute,
)
from .planner import token_estimate
from .store import GraphStore


@dataclass(frozen=True)
class WorkerSpec:
    route: TaskRoute
    investigator: Investigator
    name: str
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


class ExecutionLedger:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def root_task_id(self, task: Task) -> str:
        current = task
        seen: set[str] = set()
        while current.parent_task_id and current.id not in seen:
            seen.add(current.id)
            parent = self.store.get_task(current.parent_task_id)
            if parent is None:
                break
            current = parent
        return current.id

    def record(
        self,
        task: Task,
        *,
        planned_route: TaskRoute,
        actual_route: TaskRoute,
        worker: str,
        outcome: ExecutionOutcome,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        confidence: float | None = None,
        fallback_from_attempt_id: str | None = None,
        fallback_reason: str | None = None,
        error: str | None = None,
        route_prediction_id: str | None = None,
    ) -> ExecutionAttempt:
        prior = self.store.execution_attempts(task.id)
        attempt = ExecutionAttempt(
            root_task_id=self.root_task_id(task),
            task_id=task.id,
            sequence=len(prior) + 1,
            planned_route=planned_route,
            actual_route=actual_route,
            worker=worker,
            outcome=outcome,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            confidence=confidence,
            fallback_from_attempt_id=fallback_from_attempt_id,
            fallback_reason=fallback_reason,
            error=error,
            task_category=task_category(task),
            task_difficulty=task.difficulty,
            route_prediction_id=route_prediction_id,
        )
        self.store.save_execution_attempt(attempt)
        return attempt


class AdaptiveInvestigator:
    """Dispatch a follow-up to its planned worker and escalate weak/failed local work."""

    def __init__(
        self,
        store: GraphStore,
        workers: list[WorkerSpec],
        minimum_confidence: float = 0.75,
        routing_policy=None,
    ) -> None:
        self.store = store
        self.workers = {worker.route: worker for worker in workers}
        self.minimum_confidence = minimum_confidence
        self.ledger = ExecutionLedger(store)
        self.last_call_count = 0
        self.max_calls_for_execution = 2
        self.max_retrieval_tokens_for_execution = 2**31 - 1
        self.route_prediction_id: str | None = None
        if routing_policy is None:
            from .routing_policy import LearnedRoutingPolicy

            routing_policy = LearnedRoutingPolicy(store)
        self.routing_policy = routing_policy

    def configure_budget(self, max_calls: int, max_retrieval_tokens: int) -> None:
        self.max_calls_for_execution = max(1, max_calls)
        self.max_retrieval_tokens_for_execution = max_retrieval_tokens

    def investigate(self, question: str, project_root) -> InvestigationResult:
        task = self._open_task(question, str(project_root.resolve()))
        planned = task.route or TaskRoute.LOCAL_MODEL
        primary_route = (
            TaskRoute.LOCAL_MODEL
            if planned == TaskRoute.LOCAL_INVESTIGATOR
            else planned
        )
        prediction = self.routing_policy.predict(
            task,
            self.workers,
            primary_route,
            {
                "max_worker_calls": self.max_calls_for_execution,
                "max_worker_retrieval_tokens": self.max_retrieval_tokens_for_execution,
                "minimum_confidence": self.minimum_confidence,
            },
        )
        self.route_prediction_id = prediction.id
        primary_route = prediction.chosen_route
        routes = [primary_route]
        if primary_route == TaskRoute.LOCAL_MODEL and TaskRoute.CODEX in self.workers:
            routes.append(TaskRoute.CODEX)
        self.last_call_count = 0
        fallback_from: str | None = None
        fallback_reason: str | None = None
        last_error: Exception | None = None
        last_result: InvestigationResult | None = None
        for route in routes:
            if self.last_call_count >= self.max_calls_for_execution:
                break
            if (
                self.last_call_count > 0
                and token_estimate(question) > self.max_retrieval_tokens_for_execution
            ):
                break
            spec = self.workers.get(route)
            if spec is None:
                last_error = RuntimeError(f"No worker registered for route {route.value}")
                missing = self.ledger.record(
                    task,
                    planned_route=planned,
                    actual_route=route,
                    worker="UNREGISTERED",
                    outcome=ExecutionOutcome.FAILED,
                    fallback_from_attempt_id=fallback_from,
                    fallback_reason=fallback_reason,
                    error=str(last_error),
                    route_prediction_id=self.route_prediction_id,
                )
                fallback_from = missing.id
                fallback_reason = str(last_error)
                continue
            started = perf_counter()
            input_tokens = token_estimate(question)
            self.last_call_count += 1
            try:
                result = spec.investigator.investigate(question, project_root)
            except Exception as exc:  # noqa: BLE001 - fallback boundary
                latency = (perf_counter() - started) * 1000
                failed = self.ledger.record(
                    task,
                    planned_route=planned,
                    actual_route=route,
                    worker=spec.name,
                    outcome=ExecutionOutcome.FAILED,
                    input_tokens=input_tokens,
                    estimated_cost_usd=input_tokens * spec.input_cost_per_million / 1_000_000,
                    latency_ms=latency,
                    fallback_from_attempt_id=fallback_from,
                    fallback_reason=fallback_reason,
                    error=str(exc),
                    route_prediction_id=self.route_prediction_id,
                )
                fallback_from = failed.id
                fallback_reason = f"{spec.name} failed: {exc}"
                last_error = exc
                continue
            latency = (perf_counter() - started) * 1000
            last_result = result
            output_tokens = token_estimate(result.model_dump_json())
            weak = result.confidence < self.minimum_confidence or bool(
                result.unresolved_questions
            )
            outcome = (
                ExecutionOutcome.LOW_CONFIDENCE if weak else ExecutionOutcome.SUCCEEDED
            )
            attempt = self.ledger.record(
                task,
                planned_route=planned,
                actual_route=route,
                worker=spec.name,
                outcome=outcome,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=(
                    input_tokens * spec.input_cost_per_million
                    + output_tokens * spec.output_cost_per_million
                )
                / 1_000_000,
                latency_ms=latency,
                confidence=result.confidence,
                fallback_from_attempt_id=fallback_from,
                fallback_reason=fallback_reason,
                route_prediction_id=self.route_prediction_id,
            )
            if not weak or route == routes[-1]:
                self.routing_policy.evaluate(prediction)
                return result
            fallback_from = attempt.id
            fallback_reason = (
                f"{spec.name} returned confidence {result.confidence:.3f} "
                f"with {len(result.unresolved_questions)} unresolved question(s)."
            )
        if last_error is not None:
            if self.store.execution_attempts(task.id):
                self.routing_policy.evaluate(prediction)
            raise last_error
        if last_result is not None:
            self.routing_policy.evaluate(prediction)
            return last_result
        raise RuntimeError(f"No executable worker for planned route {planned.value}")

    def _open_task(self, question: str, project_root: str) -> Task:
        candidates = [
            task
            for task in self.store.tasks()
            if task.question == question
            and task.project_root == project_root
            and task.status.value == "OPEN"
        ]
        if not candidates:
            raise ValueError(f"No open task matches adaptive investigation: {question}")
        return max(candidates, key=lambda task: task.created_at)


def task_category(task: Task) -> str:
    if task.difficulty < 0.4:
        band = "LOW"
    elif task.difficulty < 0.75:
        band = "MEDIUM"
    else:
        band = "HIGH"
    return f"{task.kind.value}:{band}"
