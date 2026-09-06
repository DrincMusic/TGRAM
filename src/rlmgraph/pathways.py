from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .fingerprint import project_fingerprint
from .models import (
    BenchmarkRun,
    ClaimValidity,
    GraphEdge,
    PathwayBenchmarkResult,
    PathwayExpansion,
    PathwayLifecycle,
    PathwayPromotionDecision,
    PromotionOutcome,
    VirtualMemoryPathway,
)
from .provenance import assess_claim
from .reconstruction import count_o200k_tokens
from .store import GraphStore


def pathway_signature(node_ids: list[str], edges: list[GraphEdge]) -> str:
    payload = {
        "nodes": sorted(node_ids),
        "edges": [
            edge.model_dump(mode="json")
            for edge in sorted(edges, key=lambda item: (item.source, item.relation, item.target))
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PathwayPolicy:
    minimum_frequency: int = 3
    minimum_tokens_saved: int = 100
    minimum_confidence: float = 0.8
    minimum_stability: float = 1.0
    version: str = "virtual-pathway-v1"


class VirtualPathwayRegistry:
    def __init__(self, store: GraphStore, policy: PathwayPolicy | None = None) -> None:
        self.store = store
        self.store.initialize()
        self.policy = policy or PathwayPolicy()

    def observe(
        self, run: BenchmarkRun
    ) -> tuple[PathwayPromotionDecision, VirtualMemoryPathway | None]:
        signature = pathway_signature(run.traversal_node_ids, run.traversal_edges)
        candidates = [
            item
            for item in self.store.benchmark_runs()
            if item.project_root == run.project_root
            and pathway_signature(item.traversal_node_ids, item.traversal_edges) == signature
            and item.passed
        ]
        claims_by_id = {claim.id: claim for claim in self.store.claims()}
        claims = [claims_by_id[node_id] for node_id in run.traversal_node_ids]
        state = project_fingerprint(Path(run.project_root))
        validity = [
            claim.validity_status == ClaimValidity.CURRENT
            and assess_claim(claim, Path(run.project_root), state)[0]
            for claim in claims
        ]
        stale = [claim.id for claim, current in zip(claims, validity) if not current]
        contradicted_ids = {
            node_id
            for edge in self.store.edges()
            if edge.relation.value == "CONTRADICTS"
            for node_id in (edge.source, edge.target)
        }
        contradictory = [claim.id for claim in claims if claim.id in contradicted_ids]
        confidence = sum(claim.confidence for claim in claims) / len(claims)
        stability = sum(validity) / len(validity)
        token_costs = [
            count_o200k_tokens(
                {"question": item.question, "memory_tokens": ["[MEM:CANDIDATE]"]}
            )
            for item in candidates
        ]
        average_saved = (
            sum(item.active.input_tokens - cost for item, cost in zip(candidates, token_costs))
            / len(candidates)
            if candidates
            else 0.0
        )
        existing = next(
            (
                pathway
                for pathway in self.store.pathways()
                if pathway.signature == signature
                and pathway.lifecycle == PathwayLifecycle.ACTIVE
            ),
            None,
        )
        if existing is not None:
            existing = self.synchronize_validity(existing)
            if existing.lifecycle != PathwayLifecycle.ACTIVE:
                existing = None
        if contradictory:
            outcome = PromotionOutcome.REJECTED
            reason = "Contradictory claims cannot be compressed into a trusted pathway."
        elif stale:
            outcome = PromotionOutcome.REJECTED
            reason = "Stale source claims cannot be compressed into a virtual pathway."
        elif existing:
            outcome = PromotionOutcome.REJECTED
            reason = f"Active virtual pathway {existing.token} already represents this traversal."
        elif len(candidates) < self.policy.minimum_frequency:
            outcome = PromotionOutcome.REJECTED
            reason = (
                f"Traversal occurred {len(candidates)} time(s); policy requires "
                f"{self.policy.minimum_frequency}."
            )
        elif average_saved < self.policy.minimum_tokens_saved:
            outcome = PromotionOutcome.REJECTED
            reason = (
                f"Average savings {average_saved:.1f} tokens are below policy minimum "
                f"{self.policy.minimum_tokens_saved}."
            )
        elif confidence < self.policy.minimum_confidence:
            outcome = PromotionOutcome.REJECTED
            reason = "Pathway confidence is below promotion policy."
        elif stability < self.policy.minimum_stability:
            outcome = PromotionOutcome.REJECTED
            reason = "Pathway stability is below promotion policy."
        else:
            outcome = PromotionOutcome.ACCEPTED
            reason = (
                f"Traversal recurred {len(candidates)} times, remained stable, and saves "
                f"{average_saved:.1f} tokens on average."
            )
        decision = PathwayPromotionDecision(
            project_root=run.project_root,
            signature=signature,
            outcome=outcome,
            candidate_reconstruction_ids=[item.reconstruction_id for item in candidates],
            candidate_task_ids=[item.task_id for item in candidates],
            candidate_node_ids=run.traversal_node_ids,
            policy_version=self.policy.version,
            minimum_frequency=self.policy.minimum_frequency,
            minimum_tokens_saved=self.policy.minimum_tokens_saved,
            minimum_confidence=self.policy.minimum_confidence,
            minimum_stability=self.policy.minimum_stability,
            observed_frequency=len(candidates),
            observed_average_tokens_saved=average_saved,
            observed_confidence=confidence,
            observed_stability=stability,
            contradictory_claim_ids=contradictory,
            stale_claim_ids=stale,
            reason=reason,
        )
        pathway = None
        if outcome == PromotionOutcome.ACCEPTED:
            prior_versions = [
                item.version for item in self.store.pathways() if item.signature == signature
            ]
            version = max(prior_versions, default=0) + 1
            token = f"[MEM:{signature[:8].upper()}:v{version}]"
            source_files = list(
                {
                    (source.path, source.content_hash): source
                    for claim in claims
                    for source in claim.source_files
                }.values()
            )
            pathway = VirtualMemoryPathway(
                token=token,
                version=version,
                signature=signature,
                project_root=run.project_root,
                node_ids=run.traversal_node_ids,
                edges=run.traversal_edges,
                supporting_task_ids=decision.candidate_task_ids,
                supporting_reconstruction_ids=decision.candidate_reconstruction_ids,
                source_claim_ids=run.traversal_node_ids,
                source_files=source_files,
                access_frequency=len(candidates),
                average_tokens_saved=average_saved,
                confidence=confidence,
                stability=stability,
                validity_reason="Every pathway claim and source file is current.",
                valid_from=state,
                policy_decision_id=decision.id,
            )
            self.store.save_pathway(pathway)
            decision.pathway_id = pathway.id
            decision.token = pathway.token
        self.store.save_pathway_decision(decision)
        return decision, pathway

    def _current_pathway(self, token: str) -> VirtualMemoryPathway | None:
        return next((item for item in self.store.pathways() if item.token == token), None)

    def synchronize_validity(self, pathway: VirtualMemoryPathway) -> VirtualMemoryPathway:
        state = project_fingerprint(Path(pathway.project_root))
        claims = {claim.id: claim for claim in self.store.claims()}
        stale = [
            node_id
            for node_id in pathway.source_claim_ids
            if node_id not in claims
            or not assess_claim(claims[node_id], Path(pathway.project_root), state)[0]
        ]
        if stale and pathway.lifecycle != PathwayLifecycle.INVALIDATED:
            pathway.lifecycle = PathwayLifecycle.INVALIDATED
            pathway.valid_until = state
            pathway.validity_reason = "Source claims became stale: " + ", ".join(stale)
            self.store.save_pathway(pathway)
        return pathway

    def expand(
        self,
        token: str,
        *,
        depth: int = 4,
        max_tokens: int = 10_000,
    ) -> PathwayExpansion:
        expansion = PathwayExpansion(
            token=token,
            requested_depth=depth,
            reason="Virtual memory token was not found.",
        )
        visited: set[str] = set()
        claims_by_id = {claim.id: claim for claim in self.store.claims()}

        def visit(current_token: str, remaining: int) -> bool:
            if current_token in visited:
                expansion.reason = f"Cycle detected while expanding {current_token}."
                return False
            visited.add(current_token)
            pathway = self._current_pathway(current_token)
            if pathway is None:
                expansion.reason = f"Nested token {current_token} was not found."
                return False
            pathway = self.synchronize_validity(pathway)
            if pathway.lifecycle != PathwayLifecycle.ACTIVE:
                expansion.reason = pathway.validity_reason
                return False
            expansion.pathway_id = expansion.pathway_id or pathway.id
            expansion.expanded_tokens.append(current_token)
            expansion.expansion_trace.append(f"TOKEN {current_token}")
            if remaining >= 1:
                expansion.expansion_trace.append(f"PATHWAY {pathway.id} v{pathway.version}")
            if remaining >= 2:
                for node_id in pathway.node_ids:
                    if node_id not in expansion.claim_ids:
                        expansion.claim_ids.append(node_id)
                        expansion.expansion_trace.append(f"CLAIM {node_id}")
                for child in pathway.child_tokens:
                    if not visit(child, remaining - 1):
                        return False
            if remaining >= 3:
                expansion.evidence = list(
                    {
                        (item.path, item.detail, item.line): item
                        for node_id in expansion.claim_ids
                        if node_id in claims_by_id
                        for item in claims_by_id[node_id].evidence
                    }.values()
                )
                expansion.expansion_trace.extend(
                    f"EVIDENCE {item.path}:{item.line or '-'}" for item in expansion.evidence
                )
            if remaining >= 4:
                expansion.source_files = list(
                    {
                        (item.path, item.content_hash): item
                        for node_id in expansion.claim_ids
                        if node_id in claims_by_id
                        for item in claims_by_id[node_id].source_files
                    }.values()
                )
                expansion.expansion_trace.extend(
                    f"SOURCE {item.path}@{item.content_hash[:12]}"
                    for item in expansion.source_files
                )
            return True

        success = visit(token, depth)
        expansion.token_cost = count_o200k_tokens(expansion.model_dump(mode="json"))
        if expansion.token_cost > max_tokens:
            expansion.complete = False
            expansion.reason = (
                f"Expansion cost {expansion.token_cost} exceeds budget {max_tokens}."
            )
        elif success:
            expansion.complete = True
            expansion.reason = "Token expanded through pathway, claims, evidence, and source files."
        return expansion

    def benchmark_token(
        self,
        run: BenchmarkRun,
        pathway: VirtualMemoryPathway,
        *,
        answer_claim_id: str,
    ) -> PathwayBenchmarkResult:
        expansion = self.expand(pathway.token)
        token_input = count_o200k_tokens(
            {"question": run.question, "memory_tokens": [pathway.token]}
        )
        claims = {claim.id: claim for claim in self.store.claims()}
        answer = claims.get(answer_claim_id)
        correct = (
            expansion.complete
            and answer_claim_id in expansion.claim_ids
            and answer is not None
            and answer.conclusion == run.expected_answer
        )
        evidence_preserved = set(run.required_evidence_ids).issubset(expansion.claim_ids)
        result = PathwayBenchmarkResult(
            pathway_id=pathway.id,
            token=pathway.token,
            task_id=run.task_id,
            question=run.question,
            active_input_tokens=run.active.input_tokens,
            token_input_tokens=token_input,
            additional_reduction=(
                1 - token_input / run.active.input_tokens if run.active.input_tokens else 0.0
            ),
            correct=correct,
            evidence_preserved=evidence_preserved,
            expansion_complete=expansion.complete,
        )
        self.store.save_pathway_benchmark(result)
        return result
