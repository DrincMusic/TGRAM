from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from .models import (
    ExecutionOutcome,
    RouteEvaluation,
    RoutePrediction,
    RoutingPolicyUpdate,
    Task,
    TaskRoute,
    WorkerRouteEstimate,
)
from .planner import token_estimate
from .store import GraphStore


@dataclass(frozen=True)
class RoutingPolicyConfig:
    minimum_evidence: int = 3
    required_success_probability: float = 0.75


def routing_category(task: Task) -> str:
    if task.difficulty < 0.4:
        band = "LOW"
    elif task.difficulty < 0.75:
        band = "MEDIUM"
    else:
        band = "HIGH"
    return f"{task.kind.value}:{band}"


class LearnedRoutingPolicy:
    """Evidence-gated, versioned choice of the cheapest sufficiently reliable worker."""

    def __init__(
        self,
        store: GraphStore,
        config: RoutingPolicyConfig | None = None,
    ) -> None:
        self.store = store
        self.config = config or RoutingPolicyConfig()

    def predict(
        self,
        task: Task,
        workers: dict[TaskRoute, Any],
        static_route: TaskRoute,
        fixed_safety_limits: dict[str, float | int],
    ) -> RoutePrediction:
        category = routing_category(task)
        current_route = self._current_route(category, static_route)
        estimates = [
            self._estimate(task, route, worker, category)
            for route, worker in workers.items()
        ]
        qualified = [estimate for estimate in estimates if estimate.eligible]
        chosen = min(
            qualified,
            key=lambda estimate: (
                estimate.predicted_cost_usd,
                estimate.predicted_latency_ms,
                -estimate.predicted_success_probability,
            ),
            default=None,
        )
        if chosen is None:
            chosen_route = current_route
            current_worker = workers.get(current_route)
            chosen_worker = current_worker.name if current_worker else "UNREGISTERED"
            reason = (
                "Current governed route retained: no alternative has enough calibrated "
                "evidence at the required success probability."
            )
        else:
            chosen_route = chosen.route
            chosen_worker = chosen.worker
            reason = (
                f"Selected cheapest eligible worker at "
                f"{chosen.predicted_success_probability:.3f} predicted success, "
                f"${chosen.predicted_cost_usd:.6f}, and "
                f"{chosen.predicted_latency_ms:.2f}ms predicted latency."
            )
        changed = chosen_route != static_route
        policy_changed = chosen_route != current_route
        version = self._policy_version()
        if policy_changed:
            version = self._accept_update(
                task,
                category,
                current_route,
                chosen_route,
                chosen,
                fixed_safety_limits,
                version,
            )
        prediction = RoutePrediction(
            root_task_id=self._root_task_id(task),
            task_id=task.id,
            task_category=category,
            policy_version=version,
            static_route=static_route,
            chosen_route=chosen_route,
            chosen_worker=chosen_worker,
            required_success_probability=self.config.required_success_probability,
            minimum_evidence=self.config.minimum_evidence,
            changed_static_route=changed,
            reason=reason,
            candidates=estimates,
            fixed_safety_limits=fixed_safety_limits,
        )
        self.store.save_route_prediction(prediction)
        return prediction

    def evaluate(self, prediction: RoutePrediction) -> RouteEvaluation:
        attempts = [
            attempt
            for attempt in self.store.execution_attempts(prediction.task_id)
            if attempt.route_prediction_id == prediction.id
        ]
        if not attempts:
            raise ValueError(f"Prediction has no execution attempts: {prediction.id}")
        chosen = next(
            (
                candidate
                for candidate in prediction.candidates
                if candidate.route == prediction.chosen_route
                and candidate.worker == prediction.chosen_worker
            ),
            None,
        )
        predicted_probability = (
            chosen.predicted_success_probability if chosen is not None else 0.5
        )
        predicted_cost = chosen.predicted_cost_usd if chosen is not None else 0.0
        predicted_latency = chosen.predicted_latency_ms if chosen is not None else 0.0
        predicted_tokens = chosen.predicted_tokens if chosen is not None else 0.0
        final = attempts[-1]
        actual_cost = sum(attempt.estimated_cost_usd for attempt in attempts)
        actual_latency = sum(attempt.latency_ms for attempt in attempts)
        actual_tokens = sum(attempt.total_tokens for attempt in attempts)
        evaluation = RouteEvaluation(
            prediction_id=prediction.id,
            task_id=prediction.task_id,
            policy_version=prediction.policy_version,
            predicted_route=prediction.chosen_route,
            actual_final_route=final.actual_route,
            predicted_success_probability=predicted_probability,
            actual_success=final.outcome == ExecutionOutcome.SUCCEEDED,
            predicted_cost_usd=predicted_cost,
            actual_cost_usd=actual_cost,
            cost_error_usd=abs(predicted_cost - actual_cost),
            predicted_latency_ms=predicted_latency,
            actual_latency_ms=actual_latency,
            latency_error_ms=abs(predicted_latency - actual_latency),
            predicted_tokens=predicted_tokens,
            actual_tokens=actual_tokens,
            worker_calls=sum(attempt.worker != "UNREGISTERED" for attempt in attempts),
            fallback_count=sum(bool(attempt.fallback_from_attempt_id) for attempt in attempts),
        )
        self.store.save_route_evaluation(evaluation)
        return evaluation

    def _estimate(
        self,
        task: Task,
        route: TaskRoute,
        worker: Any,
        category: str,
    ) -> WorkerRouteEstimate:
        evidence = [
            attempt
            for attempt in self.store.execution_attempts()
            if attempt.actual_route == route
            and attempt.worker == worker.name
            and attempt.task_category == category
        ]
        successes = [
            attempt
            for attempt in evidence
            if attempt.outcome in {ExecutionOutcome.SUCCEEDED, ExecutionOutcome.REUSED}
        ]
        sample_count = len(evidence)
        success_count = len(successes)
        probability = (success_count + 1) / (sample_count + 2)
        confidences = [
            attempt.confidence for attempt in evidence if attempt.confidence is not None
        ]
        reported = mean(confidences) if confidences else 0.5
        empirical = success_count / sample_count if sample_count else 0.0
        input_tokens = token_estimate(task.question)
        predicted_cost = (
            mean(attempt.estimated_cost_usd for attempt in evidence)
            if evidence
            else input_tokens * worker.input_cost_per_million / 1_000_000
        )
        predicted_latency = (
            mean(attempt.latency_ms for attempt in evidence) if evidence else 0.0
        )
        predicted_tokens = (
            mean(attempt.total_tokens for attempt in evidence)
            if evidence
            else float(input_tokens)
        )
        return WorkerRouteEstimate(
            route=route,
            worker=worker.name,
            sample_count=sample_count,
            success_count=success_count,
            predicted_success_probability=probability,
            mean_reported_confidence=reported,
            calibration_error=abs(reported - empirical),
            predicted_cost_usd=predicted_cost,
            predicted_latency_ms=predicted_latency,
            predicted_tokens=predicted_tokens,
            eligible=(
                sample_count >= self.config.minimum_evidence
                and probability >= self.config.required_success_probability
            ),
            evidence_execution_ids=[attempt.id for attempt in evidence],
        )

    def _accept_update(
        self,
        task: Task,
        category: str,
        from_route: TaskRoute,
        to_route: TaskRoute,
        chosen: WorkerRouteEstimate | None,
        fixed_safety_limits: dict[str, float | int],
        current_version: int,
    ) -> int:
        assert chosen is not None
        version = current_version + 1
        update = RoutingPolicyUpdate(
            version=version,
            previous_version=current_version,
            root_task_id=self._root_task_id(task),
            triggering_task_id=task.id,
            task_category=category,
            from_route=from_route,
            to_route=to_route,
            accepted=True,
            reason=(
                f"Changed route only after {chosen.sample_count} persisted executions; "
                f"predicted success {chosen.predicted_success_probability:.3f} meets "
                f"fixed threshold {self.config.required_success_probability:.3f}."
            ),
            minimum_evidence=self.config.minimum_evidence,
            required_success_probability=self.config.required_success_probability,
            evidence_execution_ids=chosen.evidence_execution_ids,
            fixed_safety_limits=fixed_safety_limits,
        )
        self.store.save_routing_policy_update(update)
        return version

    def _policy_version(self) -> int:
        return max(
            (update.version for update in self.store.routing_policy_updates() if update.accepted),
            default=0,
        )

    def _current_route(self, category: str, static_route: TaskRoute) -> TaskRoute:
        latest = next(
            (
                update
                for update in reversed(self.store.routing_policy_updates())
                if update.accepted and update.task_category == category
            ),
            None,
        )
        return latest.to_route if latest is not None else static_route

    def _root_task_id(self, task: Task) -> str:
        current = task
        seen: set[str] = set()
        while current.parent_task_id and current.id not in seen:
            seen.add(current.id)
            parent = self.store.get_task(current.parent_task_id)
            if parent is None:
                break
            current = parent
        return current.id
