from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from typing import Protocol

from .models import (
    ConceptBranch,
    ConversationFact,
    MemoryAssociation,
    MemoryAssociationType,
    MemoryCluster,
    MemoryRelationshipInterpretation,
)


class RelationshipInterpreter(Protocol):
    def interpret_relationship(
        self, association: MemoryAssociation, facts: list[ConversationFact]
    ) -> MemoryRelationshipInterpretation: ...


class TypedRelationshipInterpreter:
    """Deterministic fallback; a disposable LLM adapter may implement the same contract."""

    def interpret_relationship(
        self, association: MemoryAssociation, facts: list[ConversationFact]
    ) -> MemoryRelationshipInterpretation:
        values = [fact.value for fact in facts]
        differences = []
        if len({value.casefold() for value in values}) > 1:
            differences.append("The connected memories retain different values: " + "; ".join(values))
        abstraction = association.shared_pattern
        if association.relation == MemoryAssociationType.ANALOGOUS_TO:
            abstraction = f"reusable relation pattern: {association.shared_pattern}"
        elif association.relation == MemoryAssociationType.CONTRASTS_WITH:
            abstraction = f"alternative values for one relation: {association.shared_pattern}"
        return MemoryRelationshipInterpretation(
            session_id=association.session_id,
            association_id=association.id,
            source_memory_ids=association.source_memory_ids,
            relationship=association.relation,
            shared_pattern=association.shared_pattern,
            differences=differences,
            possible_abstraction=abstraction,
            confidence=association.confidence,
        )


class MemoryClusterer:
    """Build a bounded hierarchy in which clusters can become members of higher clusters."""

    _WORDS = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

    def __init__(self, store, *, maximum_members: int = 8, maximum_depth: int = 4) -> None:
        self.store = store
        self.maximum_members = maximum_members
        self.maximum_depth = maximum_depth

    @classmethod
    def _terms(cls, text: str) -> list[str]:
        ignored = {"a", "an", "and", "both", "for", "in", "of", "or", "the", "to"}
        return sorted({word for word in cls._WORDS.findall(text.casefold()) if word not in ignored})

    @staticmethod
    def _signature(level: int, members: list[str]) -> str:
        digest = sha256((str(level) + ":" + ":".join(sorted(members))).encode()).hexdigest()[:20]
        return f"memory-cluster-v1:{level}:{digest}"

    def rebuild(self, session_id: str) -> list[MemoryCluster]:
        interpretation_reader = getattr(self.store, "memory_relationship_interpretations", None)
        cluster_reader = getattr(self.store, "memory_clusters", None)
        writer = getattr(self.store, "save_memory_cluster", None)
        if not all(callable(item) for item in (interpretation_reader, cluster_reader, writer)):
            return []
        interpretations = list(interpretation_reader(session_id))
        existing = list(cluster_reader(session_id))
        signatures = {cluster.signature for cluster in existing}
        created: list[MemoryCluster] = []

        groups: dict[str, list[MemoryRelationshipInterpretation]] = defaultdict(list)
        for item in interpretations:
            key = f"{item.relationship.value}:{item.shared_pattern}".casefold()
            groups[key].append(item)
        for items in groups.values():
            abstraction = items[0].possible_abstraction
            fact_ids = list(dict.fromkeys(
                memory_id for item in items for memory_id in item.source_memory_ids
            ))[: self.maximum_members]
            if len(items) < 2 or len(fact_ids) < 2:
                continue
            signature = self._signature(1, fact_ids)
            if signature in signatures:
                continue
            cluster = MemoryCluster(
                session_id=session_id,
                signature=signature,
                label=abstraction,
                defining_pattern=items[0].shared_pattern,
                abstraction_level=1,
                member_memory_ids=fact_ids,
                supporting_fact_ids=fact_ids,
                relationship_interpretation_ids=[item.id for item in items[:8]],
                centroid_terms=self._terms(abstraction)[:16],
                confidence=round(sum(item.confidence for item in items) / len(items), 4),
            )
            writer(cluster)
            existing.append(cluster)
            created.append(cluster)
            signatures.add(signature)

        for level in range(2, self.maximum_depth + 1):
            prior = [cluster for cluster in existing if cluster.abstraction_level == level - 1]
            components = self._components(prior)
            made_level = False
            for component in components:
                members = component[: self.maximum_members]
                if len(members) < 2:
                    continue
                member_ids = [item.id for item in members]
                signature = self._signature(level, member_ids)
                if signature in signatures:
                    continue
                common = set(members[0].centroid_terms)
                for item in members[1:]:
                    common &= set(item.centroid_terms)
                terms = sorted(common) or sorted({term for item in members for term in item.centroid_terms})[:8]
                supporting = list(dict.fromkeys(
                    fact_id for item in members for fact_id in item.supporting_fact_ids
                ))
                cluster = MemoryCluster(
                    session_id=session_id,
                    signature=signature,
                    label="higher-order pattern: " + ", ".join(terms[:6]),
                    defining_pattern="recurring concepts across lower-level memory clusters",
                    abstraction_level=level,
                    member_memory_ids=member_ids,
                    supporting_fact_ids=supporting,
                    relationship_interpretation_ids=list(dict.fromkeys(
                        interpretation_id for item in members
                        for interpretation_id in item.relationship_interpretation_ids
                    ))[:8],
                    centroid_terms=terms[:16],
                    confidence=round(sum(item.confidence for item in members) / len(members), 4),
                )
                writer(cluster)
                existing.append(cluster)
                created.append(cluster)
                signatures.add(signature)
                made_level = True
            if not made_level:
                break
        return created

    @staticmethod
    def _components(clusters: list[MemoryCluster]) -> list[list[MemoryCluster]]:
        remaining = {item.id: item for item in clusters}
        components = []
        while remaining:
            _, seed = remaining.popitem()
            component, frontier = [seed], [seed]
            while frontier:
                current = frontier.pop()
                current_terms = set(current.centroid_terms)
                neighbors = [
                    item for item in remaining.values()
                    if current_terms.intersection(item.centroid_terms)
                ]
                for item in neighbors:
                    remaining.pop(item.id)
                    component.append(item)
                    frontier.append(item)
            components.append(component)
        return components


class ConceptBranchManager:
    """Open a bounded branch whenever an interpretation contributes a novel abstraction."""

    _WORDS = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

    def __init__(self, store, *, maximum_depth: int = 4) -> None:
        self.store = store
        self.maximum_depth = maximum_depth

    def consider(
        self, interpretation: MemoryRelationshipInterpretation
    ) -> ConceptBranch | None:
        reader = getattr(self.store, "concept_branches", None)
        writer = getattr(self.store, "save_concept_branch", None)
        if not callable(reader) or not callable(writer):
            return None
        normalized = " ".join(interpretation.possible_abstraction.casefold().split())
        signature = "concept-branch-v1:" + sha256(normalized.encode()).hexdigest()[:20]
        existing = list(reader(interpretation.session_id))
        if any(item.signature == signature for item in existing):
            return None
        terms = set(self._WORDS.findall(normalized))
        parents = []
        for branch in existing:
            branch_terms = set(self._WORDS.findall(branch.concept.casefold()))
            overlap = len(terms & branch_terms) / max(len(terms | branch_terms), 1)
            if overlap > 0 and branch.depth < self.maximum_depth:
                parents.append((overlap, branch))
        parent = max(parents, key=lambda item: (item[0], item[1].confidence))[1] if parents else None
        branch = ConceptBranch(
            session_id=interpretation.session_id,
            signature=signature,
            concept=interpretation.possible_abstraction,
            insight=(
                f"{interpretation.shared_pattern}. "
                + (" ".join(interpretation.differences) or "No material difference was identified.")
            ),
            origin_interpretation_id=interpretation.id,
            supporting_fact_ids=interpretation.source_memory_ids,
            parent_branch_id=parent.id if parent else None,
            depth=(parent.depth + 1) if parent else 1,
            confidence=interpretation.confidence,
        )
        writer(branch)
        return branch


class MemoryAssociationEngine:
    """Find bounded semantic and structural patterns without promoting them to truth."""

    _WORDS = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

    def __init__(
        self, store, *, maximum_per_memory: int = 8,
        interpreter: RelationshipInterpreter | None = None,
    ) -> None:
        self.store = store
        self.maximum_per_memory = maximum_per_memory
        self.interpreter = interpreter or TypedRelationshipInterpreter()
        self.fallback_interpreter = TypedRelationshipInterpreter()
        self.clusterer = MemoryClusterer(store, maximum_members=maximum_per_memory)
        self.branches = ConceptBranchManager(store)

    @classmethod
    def _terms(cls, fact: ConversationFact) -> set[str]:
        return set(cls._WORDS.findall(
            f"{fact.subject} {fact.predicate} {fact.value}".casefold()
        ))

    def discover(self, fact: ConversationFact) -> list[MemoryAssociation]:
        reader = getattr(self.store, "conversation_facts", None)
        writer = getattr(self.store, "save_memory_association", None)
        if not callable(reader) or not callable(writer):
            return []
        session_reader = getattr(self.store, "chat_sessions", None)
        session_ids = (
            [item.id for item in session_reader()]
            if callable(session_reader) else [fact.session_id]
        )
        if fact.session_id not in session_ids:
            session_ids.append(fact.session_id)
        existing = [
            item for remembered_session_id in session_ids
            for item in reader(remembered_session_id)
            if item.id != fact.id
        ]
        candidates = [item for item in (self._compare(fact, prior) for prior in existing) if item]
        candidates.sort(key=lambda item: (-item.confidence, item.source_memory_ids))
        saved = candidates[: self.maximum_per_memory]
        for index, association in enumerate(saved):
            writer(association)
            supporting = [
                item for item in existing + [fact]
                if item.id in association.source_memory_ids
            ]
            # At most one potentially expensive semantic call per new memory; remaining local
            # edges receive the deterministic typed interpretation and can be enriched later.
            selected_interpreter = self.interpreter if index == 0 else self.fallback_interpreter
            try:
                interpretation = selected_interpreter.interpret_relationship(
                    association, supporting
                )
                if (
                    interpretation.association_id != association.id
                    or interpretation.session_id != association.session_id
                    or interpretation.source_memory_ids != association.source_memory_ids
                    or interpretation.relationship != association.relation
                    or interpretation.status != association.status
                ):
                    raise ValueError("Relationship interpreter changed immutable provenance.")
            except Exception:  # noqa: BLE001 - optional disposable interpreter boundary
                interpretation = self.fallback_interpreter.interpret_relationship(
                    association, supporting
                )
            interpretation_writer = getattr(
                self.store, "save_memory_relationship_interpretation", None
            )
            if callable(interpretation_writer):
                interpretation_writer(interpretation)
                self.branches.consider(interpretation)
        if saved:
            self.clusterer.rebuild(fact.session_id)
        return saved

    def _compare(
        self, current: ConversationFact, prior: ConversationFact
    ) -> MemoryAssociation | None:
        left, right = self._terms(current), self._terms(prior)
        semantic = len(left & right) / max(len(left | right), 1)
        same_subject = current.subject.casefold() == prior.subject.casefold()
        same_predicate = current.predicate.casefold() == prior.predicate.casefold()
        same_kind = current.kind == prior.kind
        structural = min(1.0, .5 * same_subject + .3 * same_predicate + .2 * same_kind)

        if current.supersedes_fact_id == prior.id:
            relation = MemoryAssociationType.SUPERSEDES
            pattern = "newer memory revises the same subject and predicate"
            confidence = max(current.confidence, .95)
        elif same_subject and same_predicate and current.value.casefold() != prior.value.casefold():
            relation = MemoryAssociationType.CONTRASTS_WITH
            pattern = "same subject and relation, different value"
            confidence = .55 * structural + .25 * semantic + .2 * min(
                current.confidence, prior.confidence
            )
        elif same_predicate or (same_kind and semantic >= .2):
            relation = MemoryAssociationType.ANALOGOUS_TO
            pattern = (
                f"both memories use relation '{current.predicate}'"
                if same_predicate else f"both memories have kind '{current.kind.value}'"
            )
            confidence = .5 * structural + .3 * semantic + .2 * min(
                current.confidence, prior.confidence
            )
        elif semantic >= .2:
            relation = MemoryAssociationType.SIMILAR_TO
            pattern = "overlapping concepts: " + ", ".join(sorted(left & right)[:6])
            confidence = .7 * semantic + .3 * min(current.confidence, prior.confidence)
        else:
            return None

        return MemoryAssociation(
            session_id=current.session_id,
            source_memory_ids=[prior.id, current.id],
            relation=relation,
            explanation=(
                f"Memory '{prior.subject} {prior.predicate} {prior.value}' and memory "
                f"'{current.subject} {current.predicate} {current.value}' exhibit: {pattern}."
            ),
            shared_pattern=pattern,
            semantic_score=round(semantic, 4),
            structural_score=round(structural, 4),
            confidence=round(min(1.0, confidence), 4),
            supporting_memory_ids=[prior.id, current.id],
        )
