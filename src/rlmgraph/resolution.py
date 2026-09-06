from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .adapters import Resolver
from .conflicts import normalize_assertion
from .models import (
    Claim,
    ClaimKind,
    ClusterStatus,
    ConflictCluster,
    ConflictVerdict,
    GraphEdge,
    GraphRelation,
    ResolutionAttempt,
    ResolutionChoice,
    ResolutionContext,
    ResolutionRunResult,
    StoppingReason,
    TaskKind,
    TaskStatus,
    VerdictStatus,
)
from .store import GraphStore


class ResolutionExecutor:
    def __init__(
        self,
        store: GraphStore,
        resolver: Resolver,
        confidence_threshold: float = 0.75,
        max_resolution_attempts: int = 2,
    ) -> None:
        self.store = store
        self.resolver = resolver
        self.confidence_threshold = confidence_threshold
        self.max_resolution_attempts = max_resolution_attempts
        self.resolution_calls = 0
        self.store.initialize()

    def execute(self, task_id: str) -> ResolutionRunResult:
        task = self.store.get_task(task_id)
        if task is None:
            raise ValueError(f"Resolution task not found: {task_id}")
        if task.kind != TaskKind.RESOLUTION:
            raise ValueError(f"Task is not a resolution task: {task_id}")
        if task.status != TaskStatus.OPEN:
            raise ValueError(f"Resolution task is not open: {task_id} ({task.status})")
        if len(task.conflicting_claim_ids) < 2:
            raise ValueError(f"Resolution task must reference at least two claims: {task_id}")
        claims = [self.store.get_claim(claim_id) for claim_id in task.conflicting_claim_ids]
        if any(claim is None for claim in claims):
            raise ValueError(f"Resolution task references a missing claim: {task_id}")
        resolved_claims = [claim for claim in claims if claim is not None]
        left, right = resolved_claims[:2]
        cluster = (
            self.store.get_conflict_cluster(task.conflict_cluster_id)
            if task.conflict_cluster_id
            else None
        )

        task.started_at = task.started_at or datetime.now(UTC)
        task.attempt_count += 1
        task.last_error = None
        self.store.save_task(task)
        self.resolution_calls += 1
        evidence_claims = [
            claim
            for child in self.store.tasks()
            if child.parent_task_id == task.id and child.output_claim_id
            if (claim := self.store.get_claim(child.output_claim_id)) is not None
        ]
        context = ResolutionContext(
            follow_up_claims=evidence_claims,
            previous_attempts=self.store.resolution_attempts(task.id),
            conflict_cluster=cluster,
        )
        if cluster is not None:
            cluster_resolver = self.resolver
            if not hasattr(cluster_resolver, "resolve_cluster"):
                raise TypeError("Resolver does not support multi-claim conflict clusters")
            result = cluster_resolver.resolve_cluster(  # type: ignore[attr-defined]
                task, resolved_claims, Path(task.project_root), context
            )
        else:
            result = self.resolver.resolve(task, left, right, Path(task.project_root), context)
        attempt = ResolutionAttempt(
            task_id=task.id,
            result=result,
            evidence_claim_ids=[claim.id for claim in evidence_claims],
        )
        self.store.save_resolution_attempt(attempt)
        successful = (
            self._is_cluster_successful(task.disputed_assertion_key, result, cluster)
            if cluster is not None
            else self._is_successful(task.disputed_assertion_key, result, left, right)
        )
        verdict = self._build_verdict(
            task, resolved_claims, result, attempt, evidence_claims, successful
        )
        task.conflict_verdict_id = verdict.id
        self.store.save_conflict_verdict(verdict)
        if not successful:
            task.status = TaskStatus.RECURSE
            task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.LOW_CONFIDENCE
            self.store.save_task(task)
            return ResolutionRunResult(task=task, result=result, verdict=verdict, resolution_calls=1)

        assert result.resolved_assertion is not None
        adjudicated = Claim(
            fingerprint=task.fingerprint,
            project_fingerprint=task.project_fingerprint,
            subject=(
                " | ".join(dict.fromkeys(claim.subject for claim in resolved_claims))
                + f" | {result.resolved_assertion.key}"
            ),
            producer=type(self.resolver).__name__,
            kind=ClaimKind.ADJUDICATED,
            resolution_task_id=task.id,
            resolved_claim_ids=[claim.id for claim in resolved_claims],
            conclusion=result.rationale,
            confidence=result.confidence,
            evidence=result.evidence,
            files_examined=sorted(
                {path for claim in resolved_claims for path in claim.files_examined}
            ),
            assertions=[result.resolved_assertion],
            conflict_verdict_id=verdict.id,
        )
        task.status = TaskStatus.DONE
        task.resolved_claim_id = adjudicated.id
        task.completed_at = datetime.now(UTC)
        task.stopping_reason = StoppingReason.COMPLETED
        self.store.save_task(task)
        self.store.save_claim(task, adjudicated)
        self.store.save_edge(
            GraphEdge(
                source=task.id,
                relation=GraphRelation.PRODUCED,
                target=adjudicated.id,
            )
        )
        for original_id in task.conflicting_claim_ids:
            self.store.save_edge(
                GraphEdge(
                    source=adjudicated.id,
                    relation=GraphRelation.RESOLVES,
                    target=original_id,
                )
            )
        if cluster is not None:
            cluster.status = ClusterStatus.RESOLVED
            cluster.resolved_claim_id = adjudicated.id
            cluster.selected_value = result.resolved_assertion.value
            self.store.save_conflict_cluster(cluster)
            self.store.save_edge(
                GraphEdge(
                    source=adjudicated.id,
                    relation=GraphRelation.RESOLVES_CLUSTER,
                    target=cluster.id,
                )
            )
        return ResolutionRunResult(
            task=task,
            result=result,
            adjudicated_claim=adjudicated,
            verdict=verdict,
            resolution_calls=1,
        )

    def _build_verdict(
        self,
        task,
        claims: list[Claim],
        result,
        attempt: ResolutionAttempt,
        evidence_claims: list[Claim],
        successful: bool,
    ) -> ConflictVerdict:
        selected_value = (
            result.resolved_assertion.value
            if successful and result.resolved_assertion is not None
            else None
        )
        supporting: list[str] = []
        contradicting: list[str] = []
        if selected_value is not None:
            normalized_key = normalize_assertion(task.disputed_assertion_key or "")
            normalized_value = normalize_assertion(selected_value)
            for claim in claims:
                assertion = next(
                    (
                        item
                        for item in claim.assertions
                        if normalize_assertion(item.key) == normalized_key
                    ),
                    None,
                )
                destination = (
                    supporting
                    if assertion is not None
                    and normalize_assertion(assertion.value) == normalized_value
                    else contradicting
                )
                destination.append(claim.id)
        existing = self.store.conflict_verdicts(task.id)
        values = {
            "resolution_task_id": task.id,
            "conflict_cluster_id": task.conflict_cluster_id,
            "assertion_key": task.disputed_assertion_key or "",
            "status": VerdictStatus.RESOLVED if successful else VerdictStatus.UNRESOLVED,
            "selected_value": selected_value,
            "confidence": result.confidence,
            "rationale": result.rationale,
            "evidence": result.evidence,
            "claim_ids": [claim.id for claim in claims],
            "supporting_claim_ids": supporting,
            "contradicting_claim_ids": contradicting,
            "evidence_claim_ids": list(
                dict.fromkeys([*(claim.id for claim in claims), *(c.id for c in evidence_claims)])
            ),
            "resolver_attempt_id": attempt.id,
            "unresolved_questions": result.unresolved_questions,
            "confidence_threshold": self.confidence_threshold,
            "max_resolution_attempts": self.max_resolution_attempts,
            "created_at": existing[-1].created_at if existing else datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        if existing:
            values["id"] = existing[-1].id
        return ConflictVerdict.model_validate(values)

    def _is_successful(self, assertion_key, result, left: Claim, right: Claim) -> bool:
        if result.selected_claim == ResolutionChoice.NEITHER:
            return False
        if result.confidence < self.confidence_threshold or result.unresolved_questions:
            return False
        if result.resolved_assertion is None or assertion_key is None:
            return False
        if normalize_assertion(result.resolved_assertion.key) != normalize_assertion(assertion_key):
            return False
        selected = left if result.selected_claim == ResolutionChoice.LEFT else right
        expected = next(
            (
                assertion
                for assertion in selected.assertions
                if normalize_assertion(assertion.key) == normalize_assertion(assertion_key)
            ),
            None,
        )
        return expected is not None and normalize_assertion(
            expected.value
        ) == normalize_assertion(result.resolved_assertion.value)

    def _is_cluster_successful(
        self,
        assertion_key: str | None,
        result,
        cluster: ConflictCluster | None,
    ) -> bool:
        if cluster is None or result.selected_claim != ResolutionChoice.VALUE:
            return False
        if result.confidence < self.confidence_threshold or result.unresolved_questions:
            return False
        if result.resolved_assertion is None or assertion_key is None or result.selected_value is None:
            return False
        if normalize_assertion(result.resolved_assertion.key) != normalize_assertion(assertion_key):
            return False
        if normalize_assertion(result.resolved_assertion.value) != normalize_assertion(
            result.selected_value
        ):
            return False
        interpretation = next(
            (
                item
                for item in cluster.interpretations
                if item.normalized_value == normalize_assertion(result.selected_value)
            ),
            None,
        )
        if interpretation is None:
            return False
        selected_ids = set(interpretation.claim_ids)
        return (
            set(result.selected_claim_ids) == selected_ids
            and set(result.corroborated_claim_ids)
            == set(cluster.corroborated_claim_ids)
            and set(result.outlier_claim_ids) == set(cluster.outlier_claim_ids)
        )
