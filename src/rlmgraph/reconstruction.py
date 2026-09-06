from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import ClassVar, Protocol

import tiktoken

from .models import (
    Claim,
    GraphEdge,
    GraphRelation,
    MemoryTier,
    ReconstructionAction,
    ReconstructionSession,
    ReconstructionStatus,
    ReconstructionStep,
    Task,
)
from .relevance import claim_text, terms
from .store import GraphStore


@dataclass(frozen=True)
class ExpansionDecision:
    expand: bool
    score: float
    reason: str


class ExpansionPolicy(Protocol):
    def decide(
        self,
        query: str,
        frontier: Claim,
        candidate: Claim,
        relation: GraphRelation,
    ) -> ExpansionDecision: ...


class RelationAwareExpansionPolicy:
    """Small explainable policy boundary that can later be replaced by a model adapter."""

    dependency_relations: ClassVar[set[GraphRelation]] = {
        GraphRelation.DERIVED_FROM,
        GraphRelation.RESOLVES,
    }

    def decide(
        self,
        query: str,
        frontier: Claim,
        candidate: Claim,
        relation: GraphRelation,
    ) -> ExpansionDecision:
        if relation in self.dependency_relations or candidate.id in frontier.source_claim_ids:
            return ExpansionDecision(
                True,
                1.0,
                f"{relation.value} is an evidence/provenance dependency of {frontier.id}.",
            )
        query_terms = terms(query)
        overlap = query_terms & terms(claim_text(candidate))
        if relation == GraphRelation.CORROBORATES and len(overlap) >= 2:
            score = len(overlap) / max(1, len(query_terms))
            return ExpansionDecision(
                True,
                score,
                "Corroborating claim independently matches the active query cues: "
                + ", ".join(sorted(overlap)),
            )
        return ExpansionDecision(
            False,
            0.0,
            f"{relation.value} does not identify a necessary dependency for the active query.",
        )


def estimate_context_tokens(claims: list[Claim]) -> int:
    """Count the exact serialized context with OpenAI's o200k_base tokenizer."""
    payload = json.dumps(
        [claim.model_dump(mode="json") for claim in sorted(claims, key=lambda item: item.id)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(tiktoken.get_encoding("o200k_base").encode(payload))


def count_o200k_tokens(payload: object) -> int:
    """Count an exact canonical JSON payload with the benchmark's declared encoding."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return len(tiktoken.get_encoding("o200k_base").encode(serialized))


def seed_score(query: str, claim: Claim) -> float:
    query_terms = terms(query)
    if not query_terms:
        return 0.0
    matched = query_terms & terms(claim_text(claim))
    exact = " ".join(query.lower().split()) == " ".join(claim.subject.lower().split())
    coverage = len(matched) / len(query_terms)
    return 1.0 if exact else min(0.99, coverage * claim.confidence)


def tier_priority(claim: Claim) -> int:
    return {
        MemoryTier.WORKING: 0,
        MemoryTier.EPISODIC: 1,
        MemoryTier.SEMANTIC: 2,
        MemoryTier.PROCEDURAL: 3,
    }[claim.memory_tier]


class ActiveMemoryReconstructor:
    def __init__(
        self,
        store: GraphStore,
        policy: ExpansionPolicy | None = None,
        *,
        seed_count: int = 2,
        max_depth: int = 3,
        baseline_depth: int = 3,
    ) -> None:
        self.store = store
        self.policy = policy or RelationAwareExpansionPolicy()
        self.seed_count = seed_count
        self.max_depth = max_depth
        self.baseline_depth = baseline_depth

    def reconstruct(
        self,
        task: Task,
        claims: list[Claim],
        *,
        required_evidence_ids: list[str] | None = None,
    ) -> ReconstructionSession:
        claim_by_id = {claim.id: claim for claim in claims}
        graph_edges = [
            edge
            for edge in self.store.edges()
            if edge.source in claim_by_id and edge.target in claim_by_id
        ]
        ranked = sorted(
            (
                (seed_score(task.question, claim), claim)
                for claim in claims
            ),
            key=lambda item: (
                tier_priority(item[1]),
                item[0],
                item[1].confidence,
                item[1].id,
            ),
            reverse=True,
        )
        seeds = [claim for score, claim in ranked[: self.seed_count] if score > 0]
        session = ReconstructionSession(
            task_id=task.id,
            query=task.question,
            required_evidence_ids=required_evidence_ids or [],
        )
        selected: dict[str, Claim] = {}
        pruned: set[str] = set()
        steps: list[ReconstructionStep] = []
        frontier: deque[tuple[Claim, int]] = deque()
        sequence = 0
        for seed in seeds:
            score = seed_score(task.question, seed)
            selected[seed.id] = seed
            frontier.append((seed, 0))
            steps.append(
                ReconstructionStep(
                    sequence=sequence,
                    action=ReconstructionAction.SEED,
                    node_id=seed.id,
                    score=score,
                    reason=f"Top lexical/evidence seed for the task (score {score:.2f}).",
                    token_estimate=estimate_context_tokens([seed]),
                )
            )
            sequence += 1

        adjacency: dict[str, list[tuple[Claim, GraphRelation, GraphEdge]]] = {}
        for edge in graph_edges:
            adjacency.setdefault(edge.source, []).append(
                (claim_by_id[edge.target], edge.relation, edge)
            )
        while frontier:
            current, depth = frontier.popleft()
            if depth >= self.max_depth:
                continue
            for candidate, relation, edge in adjacency.get(current.id, []):
                if candidate.id in selected:
                    continue
                decision = self.policy.decide(task.question, current, candidate, relation)
                if decision.expand:
                    selected[candidate.id] = candidate
                    frontier.append((candidate, depth + 1))
                    steps.append(
                        ReconstructionStep(
                            sequence=sequence,
                            action=ReconstructionAction.EXPAND,
                            node_id=candidate.id,
                            frontier_node_id=current.id,
                            relation=relation,
                            score=decision.score,
                            reason=decision.reason,
                            token_estimate=estimate_context_tokens([candidate]),
                        )
                    )
                elif candidate.id not in pruned:
                    pruned.add(candidate.id)
                    steps.append(
                        ReconstructionStep(
                            sequence=sequence,
                            action=ReconstructionAction.PRUNE,
                            node_id=candidate.id,
                            frontier_node_id=current.id,
                            relation=relation,
                            score=decision.score,
                            reason=decision.reason,
                            token_estimate=estimate_context_tokens([candidate]),
                        )
                    )
                sequence += 1

        baseline_ids = self._fixed_neighborhood([claim.id for claim in seeds], graph_edges)
        selected_ids = list(selected)
        selected_edges = [
            edge
            for edge in graph_edges
            if edge.source in selected and edge.target in selected
        ]
        required = set(required_evidence_ids or [])
        session.seed_node_ids = [claim.id for claim in seeds]
        session.selected_node_ids = selected_ids
        session.pruned_node_ids = sorted(pruned - set(selected_ids))
        session.context_edges = selected_edges
        session.steps = steps
        session.baseline_node_ids = baseline_ids
        session.reconstructed_token_estimate = estimate_context_tokens(list(selected.values()))
        session.baseline_token_estimate = estimate_context_tokens(
            [claim_by_id[node_id] for node_id in baseline_ids]
        )
        session.evidence_preserved = required.issubset(selected) if required else None
        session.status = (
            ReconstructionStatus.COMPLETE
            if session.evidence_preserved is not False
            else ReconstructionStatus.INCOMPLETE
        )
        return session

    def _fixed_neighborhood(
        self, seeds: list[str], edges: list[GraphEdge]
    ) -> list[str]:
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)
        visited = set(seeds)
        queue: deque[tuple[str, int]] = deque((seed, 0) for seed in seeds)
        while queue:
            node_id, depth = queue.popleft()
            if depth >= self.baseline_depth:
                continue
            for candidate in adjacency.get(node_id, set()):
                if candidate in visited:
                    continue
                visited.add(candidate)
                queue.append((candidate, depth + 1))
        return sorted(visited)
