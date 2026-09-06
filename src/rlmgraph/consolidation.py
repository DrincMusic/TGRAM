from __future__ import annotations

from dataclasses import dataclass

from .conflicts import normalize_assertion
from .models import (
    Assertion,
    Claim,
    ClaimValidity,
    GraphEdge,
    GraphRelation,
    MemoryLifecycle,
    MemoryTier,
    PromotionDecision,
    PromotionOutcome,
    Task,
    TierTransition,
    ValidityEvent,
)
from .store import GraphStore


@dataclass(frozen=True)
class ConsolidationPolicy:
    semantic_minimum_episodes: int = 2
    semantic_minimum_confidence: float = 0.8
    procedural_minimum_reuses: int = 2
    procedural_minimum_confidence: float = 0.85
    version: str = "governed-memory-v1"


class GovernedMemoryConsolidator:
    def __init__(
        self, store: GraphStore, policy: ConsolidationPolicy | None = None
    ) -> None:
        self.store = store
        self.policy = policy or ConsolidationPolicy()

    def evaluate_episodic(self, task: Task, trigger: Claim) -> list[PromotionDecision]:
        decisions: list[PromotionDecision] = []
        for assertion in trigger.assertions:
            key = normalize_assertion(assertion.key)
            candidates = [
                claim
                for claim in self.store.claims()
                if claim.project_root == trigger.project_root
                and claim.memory_tier == MemoryTier.EPISODIC
                and any(normalize_assertion(item.key) == key for item in claim.assertions)
            ]
            decision = self._semantic_decision(task, assertion, candidates)
            if decision.outcome == PromotionOutcome.ACCEPTED:
                promoted = self._create_semantic(task, assertion, candidates, decision)
                decision.promoted_claim_id = promoted.id
                decision.accepted_claim_ids = promoted.source_claim_ids
                self.store.save_promotion_decision(decision)
            else:
                self.store.save_promotion_decision(decision)
            decisions.append(decision)
        return decisions

    def _semantic_decision(
        self, task: Task, assertion: Assertion, candidates: list[Claim]
    ) -> PromotionDecision:
        normalized_value = normalize_assertion(assertion.value)
        current = [
            claim for claim in candidates if claim.validity_status == ClaimValidity.CURRENT
        ]
        matching = [
            claim
            for claim in current
            if any(
                normalize_assertion(item.key) == normalize_assertion(assertion.key)
                and normalize_assertion(item.value) == normalized_value
                for item in claim.assertions
            )
        ]
        contradictory = [claim for claim in current if claim not in matching]
        stale = [claim for claim in candidates if claim.validity_status != ClaimValidity.CURRENT]
        strong = [
            claim
            for claim in matching
            if claim.confidence >= self.policy.semantic_minimum_confidence
        ]
        independent_tasks = {claim.source_task_id for claim in strong if claim.source_task_id}
        observed_confidence = (
            sum(claim.confidence for claim in matching) / len(matching) if matching else 0.0
        )
        existing = next(
            (
                claim
                for claim in self.store.claims()
                if claim.project_root == task.project_root
                and claim.memory_tier == MemoryTier.SEMANTIC
                and claim.validity_status == ClaimValidity.CURRENT
                and any(
                    normalize_assertion(item.key) == normalize_assertion(assertion.key)
                    and normalize_assertion(item.value) == normalized_value
                    for item in claim.assertions
                )
            ),
            None,
        )
        if existing:
            outcome = PromotionOutcome.REJECTED
            reason = f"Active semantic memory {existing.id} already represents this knowledge."
        elif contradictory:
            outcome = PromotionOutcome.REJECTED
            reason = "Contradictory current episodes must be resolved before consolidation."
        elif len(strong) < self.policy.semantic_minimum_episodes:
            outcome = PromotionOutcome.REJECTED
            weak_count = len(matching) - len(strong)
            reason = (
                f"Only {len(strong)} strong episode(s); policy requires "
                f"{self.policy.semantic_minimum_episodes} at confidence "
                f">= {self.policy.semantic_minimum_confidence:.2f}"
                + (f"; {weak_count} candidate(s) were below confidence." if weak_count else ".")
                + (f" {len(stale)} stale candidate(s) were excluded." if stale else "")
            )
        elif len(independent_tasks) < self.policy.semantic_minimum_episodes:
            outcome = PromotionOutcome.REJECTED
            reason = "Supporting episodes are not independent task experiences."
        else:
            outcome = PromotionOutcome.ACCEPTED
            reason = (
                f"{len(strong)} independent current episodes meet confidence and consistency policy."
            )
        rejected = (
            [claim for claim in candidates if claim not in strong]
            if outcome == PromotionOutcome.ACCEPTED
            else candidates
        )
        return PromotionDecision(
            task_id=task.id,
            project_root=task.project_root,
            assertion_key=assertion.key,
            from_tier=MemoryTier.EPISODIC,
            to_tier=MemoryTier.SEMANTIC,
            outcome=outcome,
            candidate_claim_ids=[claim.id for claim in candidates],
            accepted_claim_ids=[claim.id for claim in strong] if outcome == PromotionOutcome.ACCEPTED else [],
            rejected_claim_ids=[claim.id for claim in rejected],
            contradictory_claim_ids=[claim.id for claim in contradictory],
            stale_claim_ids=[claim.id for claim in stale],
            policy_version=self.policy.version,
            minimum_support=self.policy.semantic_minimum_episodes,
            minimum_confidence=self.policy.semantic_minimum_confidence,
            observed_support=len(strong),
            observed_confidence=observed_confidence,
            reason=reason,
        )

    def _create_semantic(
        self,
        task: Task,
        assertion: Assertion,
        candidates: list[Claim],
        decision: PromotionDecision,
    ) -> Claim:
        accepted_ids = set(decision.accepted_claim_ids)
        accepted = [claim for claim in candidates if claim.id in accepted_ids]
        evidence = list(
            {
                (item.path, item.detail, item.line): item
                for claim in accepted
                for item in claim.evidence
            }.values()
        )
        semantic = Claim(
            fingerprint=task.fingerprint,
            project_fingerprint=task.project_fingerprint,
            project_root=task.project_root,
            subject=accepted[0].subject,
            producer=type(self).__name__,
            conclusion=(
                f"Validated project knowledge: {assertion.key} is {assertion.value}."
            ),
            confidence=sum(claim.confidence for claim in accepted) / len(accepted),
            evidence=evidence,
            files_examined=sorted(
                {path for claim in accepted for path in claim.files_examined}
            ),
            assertions=[assertion],
            source_claim_ids=[claim.id for claim in accepted],
            memory_tier=MemoryTier.SEMANTIC,
            memory_policy_decision_id=decision.id,
            tier_history=[
                TierTransition(
                    from_tier=MemoryTier.EPISODIC,
                    to_tier=MemoryTier.SEMANTIC,
                    reason=decision.reason,
                    decision_id=decision.id,
                )
            ],
        )
        self.store.save_claim(task, semantic)
        for source in accepted:
            source.memory_lifecycle = MemoryLifecycle.PROMOTED
            source.promoted_to_claim_id = semantic.id
            self.store.update_claim(source)
            self.store.save_edge(
                GraphEdge(
                    source=semantic.id,
                    relation=GraphRelation.CONSOLIDATED_FROM,
                    target=source.id,
                )
            )
        return semantic

    def evaluate_procedural(self, task: Task, semantic: Claim) -> PromotionDecision:
        assertion = semantic.assertions[0] if semantic.assertions else Assertion(key="memory", value="")
        existing = next(
            (
                claim
                for claim in self.store.claims()
                if claim.project_root == semantic.project_root
                and claim.memory_tier == MemoryTier.PROCEDURAL
                and claim.validity_status == ClaimValidity.CURRENT
                and any(
                    normalize_assertion(item.key) == normalize_assertion(assertion.key)
                    for item in claim.assertions
                )
            ),
            None,
        )
        eligible = (
            semantic.validity_status == ClaimValidity.CURRENT
            and semantic.confidence >= self.policy.procedural_minimum_confidence
            and semantic.successful_reuse_count >= self.policy.procedural_minimum_reuses
            and existing is None
        )
        if existing:
            reason = f"Active procedural memory {existing.id} already exists."
        elif semantic.validity_status != ClaimValidity.CURRENT:
            reason = "Semantic memory is stale and cannot become procedure."
        elif semantic.confidence < self.policy.procedural_minimum_confidence:
            reason = "Semantic confidence is below procedural policy."
        elif semantic.successful_reuse_count < self.policy.procedural_minimum_reuses:
            reason = (
                f"Semantic memory has {semantic.successful_reuse_count} successful reuse(s); "
                f"policy requires {self.policy.procedural_minimum_reuses}."
            )
        else:
            reason = "Stable semantic knowledge has enough successful reuse to become procedure."
        decision = PromotionDecision(
            task_id=task.id,
            project_root=task.project_root,
            assertion_key=assertion.key,
            from_tier=MemoryTier.SEMANTIC,
            to_tier=MemoryTier.PROCEDURAL,
            outcome=PromotionOutcome.ACCEPTED if eligible else PromotionOutcome.REJECTED,
            candidate_claim_ids=[semantic.id],
            accepted_claim_ids=[semantic.id] if eligible else [],
            rejected_claim_ids=[] if eligible else [semantic.id],
            stale_claim_ids=(
                [semantic.id]
                if semantic.validity_status != ClaimValidity.CURRENT
                else []
            ),
            policy_version=self.policy.version,
            minimum_support=self.policy.procedural_minimum_reuses,
            minimum_confidence=self.policy.procedural_minimum_confidence,
            observed_support=semantic.successful_reuse_count,
            observed_confidence=semantic.confidence,
            reason=reason,
        )
        if eligible:
            procedural = Claim(
                fingerprint=task.fingerprint,
                project_fingerprint=task.project_fingerprint,
                project_root=task.project_root,
                subject=semantic.subject,
                producer=type(self).__name__,
                conclusion=f"Project procedure: use {assertion.value} for {assertion.key}.",
                confidence=semantic.confidence,
                evidence=semantic.evidence,
                files_examined=semantic.files_examined,
                assertions=[assertion],
                source_claim_ids=[semantic.id],
                memory_tier=MemoryTier.PROCEDURAL,
                memory_policy_decision_id=decision.id,
                tier_history=[
                    TierTransition(
                        from_tier=MemoryTier.SEMANTIC,
                        to_tier=MemoryTier.PROCEDURAL,
                        reason=reason,
                        decision_id=decision.id,
                    )
                ],
            )
            self.store.save_claim(task, procedural)
            semantic.memory_lifecycle = MemoryLifecycle.PROMOTED
            semantic.promoted_to_claim_id = procedural.id
            self.store.update_claim(semantic)
            self.store.save_edge(
                GraphEdge(
                    source=procedural.id,
                    relation=GraphRelation.CONSOLIDATED_FROM,
                    target=semantic.id,
                )
            )
            decision.promoted_claim_id = procedural.id
        self.store.save_promotion_decision(decision)
        return decision


def synchronize_dependency_validity(store: GraphStore, project_state: str) -> None:
    claims = store.claims()
    by_id = {claim.id: claim for claim in claims}
    changed = True
    while changed:
        changed = False
        for claim in claims:
            if claim.memory_tier not in {MemoryTier.SEMANTIC, MemoryTier.PROCEDURAL}:
                continue
            dependencies = [by_id[item] for item in claim.source_claim_ids if item in by_id]
            invalid = [
                item for item in dependencies if item.validity_status != ClaimValidity.CURRENT
            ]
            if claim.validity_status != ClaimValidity.CURRENT:
                if claim.memory_lifecycle != MemoryLifecycle.INVALIDATED:
                    claim.memory_lifecycle = MemoryLifecycle.INVALIDATED
                    store.update_claim(claim)
                    changed = True
            elif invalid:
                claim.validity_status = ClaimValidity.INVALIDATED
                claim.memory_lifecycle = MemoryLifecycle.INVALIDATED
                claim.valid_until = project_state
                claim.validity_reason = (
                    "Dependent memory invalidated because source claims are stale: "
                    + ", ".join(item.id for item in invalid)
                )
                claim.validity_history.append(
                    ValidityEvent(
                        status=ClaimValidity.INVALIDATED,
                        project_fingerprint=project_state,
                        reason=claim.validity_reason,
                    )
                )
                store.update_claim(claim)
                changed = True
            elif not invalid:
                target = (
                    MemoryLifecycle.PROMOTED
                    if claim.promoted_to_claim_id
                    else MemoryLifecycle.ACTIVE
                )
                if claim.memory_lifecycle != target:
                    claim.memory_lifecycle = target
                    store.update_claim(claim)
