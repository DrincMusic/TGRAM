from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .adapters import Investigator
from .conflicts import build_conflict_cluster, detect_conflicts, normalize_assertion
from .consolidation import GovernedMemoryConsolidator, synchronize_dependency_validity
from .fingerprint import indexed_project_fingerprint, project_fingerprint, task_fingerprint
from .models import (
    Claim,
    ClaimConflict,
    ClusterStatus,
    ConflictCluster,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    MemoryTier,
    PathwayExpansion,
    ProjectFile,
    ProjectScan,
    ReconstructionSession,
    RunResult,
    StoppingReason,
    Task,
    TaskKind,
    TaskStatus,
)
from .onboarding import ProjectSelection, ReadOnlyProjectOnboarder, ReadOnlyWorkerBoundary
from .pathways import VirtualPathwayRegistry
from .provenance import (
    assess_claim,
    assess_claim_from_index,
    capture_indexed_source_files,
    record_validity,
    supersede,
)
from .reconstruction import ActiveMemoryReconstructor, tier_priority
from .relevance import ExplainableClaimMatcher, RelevanceMatch
from .store import GraphStore
from .workflow_fact_search import WorkflowFactSearch


class SupervisorState(TypedDict, total=False):
    task: Task
    claim: Claim
    cached_claim: Claim | None
    relevance_match: RelevanceMatch | None
    reuse_type: str | None
    investigation: InvestigationResult
    cache_hit: bool
    force_investigation: bool
    conflicts: list[ClaimConflict]
    resolution_tasks: list[Task]
    conflict_clusters: list[ConflictCluster]
    reconstruction: ReconstructionSession
    indexed_files: list[ProjectFile]
    project_scan: ProjectScan


class Supervisor:
    def __init__(
        self,
        store: GraphStore,
        investigator: Investigator,
        matcher: ExplainableClaimMatcher | None = None,
        reconstructor: ActiveMemoryReconstructor | None = None,
        consolidator: GovernedMemoryConsolidator | None = None,
        pathway_registry: VirtualPathwayRegistry | None = None,
        onboarder: ReadOnlyProjectOnboarder | None = None,
    ) -> None:
        self.store = store
        self.investigator = investigator
        self.matcher = matcher or ExplainableClaimMatcher()
        self.reconstructor = reconstructor or ActiveMemoryReconstructor(store)
        self.consolidator = consolidator or GovernedMemoryConsolidator(store)
        self.pathway_registry = pathway_registry or VirtualPathwayRegistry(store)
        self.onboarder = onboarder
        self.investigation_calls = 0
        self.store.initialize()
        self.graph = self._build_graph()

    def expand_memory(
        self, token: str, *, depth: int = 4, max_tokens: int = 10_000
    ) -> PathwayExpansion:
        """Supervisor-facing escape hatch from a virtual token to exact provenance."""
        return self.pathway_registry.expand(token, depth=depth, max_tokens=max_tokens)

    def _build_graph(self):
        graph = StateGraph(SupervisorState)
        graph.add_node("remember_task", self._remember_task)
        graph.add_node("search_memory", self._search_memory)
        graph.add_node("investigate", self._investigate)
        graph.add_node("record_discovery", self._record_discovery)
        graph.add_node("reuse_discovery", self._reuse_discovery)
        graph.add_edge(START, "remember_task")
        graph.add_edge("remember_task", "search_memory")
        graph.add_conditional_edges(
            "search_memory",
            lambda state: "reuse" if state["cached_claim"] else "investigate",
            {"reuse": "reuse_discovery", "investigate": "investigate"},
        )
        graph.add_edge("investigate", "record_discovery")
        graph.add_edge("record_discovery", END)
        graph.add_edge("reuse_discovery", END)
        return graph.compile()

    def run(
        self,
        question: str,
        project_root: str | Path = ".",
        *,
        force_investigation: bool = False,
    ) -> RunResult:
        root = Path(project_root)
        scan = None
        indexed_files: list[ProjectFile] = []
        if self.onboarder is not None:
            scan = self.onboarder.scan(ProjectSelection.explicit(root))
            indexed_files = self.store.project_files(scan.project_id)
            project_state = indexed_project_fingerprint(
                root, [(item.path, item.content_hash) for item in indexed_files]
            )
        else:
            project_state = project_fingerprint(root)
        fingerprint = task_fingerprint(question, project_state)
        task = Task.create(question, root, fingerprint, project_state)
        before = self.investigation_calls
        initial: SupervisorState = {
            "task": task,
            "force_investigation": force_investigation,
        }
        if scan is not None:
            initial["project_scan"] = scan
            initial["indexed_files"] = indexed_files
        state = self.graph.invoke(initial)
        return RunResult(
            task=state["task"],
            claim=state["claim"],
            cache_hit=state["cache_hit"],
            reuse_type=state.get("reuse_type"),
            relevance_score=(
                state["relevance_match"].score if state.get("relevance_match") else None
            ),
            reuse_reason=(
                state["relevance_match"].reason if state.get("relevance_match") else None
            ),
            conflicts=state.get("conflicts", []),
            resolution_tasks=state.get("resolution_tasks", []),
            conflict_clusters=state.get("conflict_clusters", []),
            investigation_calls=self.investigation_calls - before,
            reconstruction=state.get("reconstruction"),
            project_scan_id=scan.id if scan else None,
            source_files_read=scan.content_read_file_count if scan else 0,
            source_files_parsed=scan.parsed_file_count if scan else 0,
        )

    def _remember_task(self, state: SupervisorState) -> SupervisorState:
        task = state["task"]
        task.started_at = task.started_at or datetime.now(UTC)
        task.attempt_count += 1
        self.store.save_task(task)
        return {"task": task}

    def _search_memory(self, state: SupervisorState) -> SupervisorState:
        task = state["task"]
        valid_claims: list[Claim] = []
        for claim in self.store.claims():
            if claim.project_root:
                if Path(claim.project_root).resolve() != Path(task.project_root).resolve():
                    continue
            elif claim.project_fingerprint != task.project_fingerprint:
                continue
            if state.get("indexed_files") is not None:
                valid, reason = assess_claim_from_index(
                    claim, state["indexed_files"], task.project_fingerprint
                )
            else:
                valid, reason = assess_claim(
                    claim, Path(task.project_root), task.project_fingerprint
                )
            if record_validity(claim, valid, task.project_fingerprint, reason):
                self.store.update_claim(claim)
            if valid:
                valid_claims.append(claim)
        synchronize_dependency_validity(self.store, task.project_fingerprint)
        valid_claims = [
            claim
            for claim in self.store.claims()
            if claim.validity_status.value == "CURRENT"
            and (
                Path(claim.project_root).resolve() == Path(task.project_root).resolve()
                if claim.project_root
                else claim.project_fingerprint == task.project_fingerprint
            )
        ]
        contradicted_ids = {
            node_id
            for edge in self.store.edges()
            if edge.relation == GraphRelation.CONTRADICTS
            for node_id in (edge.source, edge.target)
        }
        reusable_claims = [
            claim for claim in valid_claims if claim.id not in contradicted_ids
        ]
        reconstruction = self.reconstructor.reconstruct(task, reusable_claims)
        self.store.save_reconstruction(reconstruction)
        task.reconstruction_id = reconstruction.id
        self.store.save_task(task)
        selected_ids = set(reconstruction.selected_node_ids)
        reusable_claims = [claim for claim in reusable_claims if claim.id in selected_ids]
        if state.get("force_investigation"):
            return {
                "cached_claim": None,
                "relevance_match": None,
                "reuse_type": None,
                "reconstruction": reconstruction,
            }
        governed_match = self.matcher.best_match(
            task.question,
            sorted(
                (
                    claim
                    for claim in reusable_claims
                    if claim.memory_tier
                    in {MemoryTier.SEMANTIC, MemoryTier.PROCEDURAL}
                ),
                key=tier_priority,
                reverse=True,
            ),
        )
        if governed_match:
            return {
                "cached_claim": governed_match.claim,
                "relevance_match": governed_match,
                "reuse_type": governed_match.claim.memory_tier.value.lower(),
                "reconstruction": reconstruction,
            }
        exact = next(
            (
                claim
                for claim in sorted(reusable_claims, key=tier_priority, reverse=True)
                if " ".join(claim.subject.lower().split())
                == " ".join(task.question.lower().split())
            ),
            None,
        )
        if exact:
            same_state = exact.project_fingerprint == task.project_fingerprint
            match = RelevanceMatch(
                claim=exact,
                score=1.0,
                matched_terms=(),
                reason=(
                    "Exact normalized question and unchanged project state."
                    if same_state
                    else "Exact question; every supporting source remains content-identical."
                ),
            )
            return {
                "cached_claim": exact,
                "relevance_match": match,
                "reuse_type": "exact" if same_state else "provenance",
                "reconstruction": reconstruction,
            }
        match = self.matcher.best_match(
            task.question, reusable_claims
        )
        if match:
            return {
                "cached_claim": match.claim,
                "relevance_match": match,
                "reuse_type": "semantic",
                "reconstruction": reconstruction,
            }
        return {
            "cached_claim": None,
            "relevance_match": None,
            "reuse_type": None,
            "reconstruction": reconstruction,
        }

    def _investigate(self, state: SupervisorState) -> SupervisorState:
        self.investigation_calls += 1
        task = state["task"]
        if self.onboarder is not None:
            search = WorkflowFactSearch(self.store).search(
                task.question, Path(task.project_root), state["project_scan"].project_id,
                files=state["indexed_files"],
            )
            result = ReadOnlyWorkerBoundary(
                ProjectSelection.explicit(task.project_root)
            ).investigate(self.investigator, task.question + search.context())
        else:
            result = self.investigator.investigate(task.question, Path(task.project_root))
        return {"investigation": result, "cache_hit": False}

    def _record_discovery(self, state: SupervisorState) -> SupervisorState:
        task, result = state["task"], state["investigation"]
        existing_claims = self.store.find_claims(task.project_fingerprint)
        historical_claims = [
            claim
            for claim in self.store.claims()
            if (
                Path(claim.project_root).resolve() == Path(task.project_root).resolve()
                if claim.project_root
                else claim.project_fingerprint == task.project_fingerprint
            )
        ]
        claim = Claim(
            fingerprint=task.fingerprint,
            project_fingerprint=task.project_fingerprint,
            subject=task.question,
            producer=type(self.investigator).__name__,
            **result.model_dump(),
        )
        if state.get("indexed_files") is not None:
            claim.source_files = capture_indexed_source_files(
                claim, state["indexed_files"]
            )
        task.status = TaskStatus.RECURSE if result.unresolved_questions else TaskStatus.DONE
        if task.status == TaskStatus.DONE:
            task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.COMPLETED
        else:
            task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.LOW_CONFIDENCE
        self.store.save_task(task)
        self.store.save_claim(task, claim)
        new_keys = {normalize_assertion(item.key) for item in claim.assertions}
        for historical in historical_claims:
            historical_keys = {normalize_assertion(item.key) for item in historical.assertions}
            if (
                historical.validity_status.value == "INVALIDATED"
                and historical.memory_tier == claim.memory_tier
                and new_keys.intersection(historical_keys)
            ):
                supersede(historical, claim, task.project_fingerprint)
                self.store.update_claim(historical)
                self.store.save_edge(
                    GraphEdge(
                        source=claim.id,
                        relation=GraphRelation.SUPERSEDES,
                        target=historical.id,
                    )
                )
        conflicts = detect_conflicts(claim, existing_claims)
        resolution_tasks: list[Task] = []
        conflict_clusters: list[ConflictCluster] = []
        handled_keys: set[str] = set()
        all_claims = [*existing_claims, claim]
        for conflict in conflicts:
            normalized_key = normalize_assertion(conflict.assertion_key)
            if normalized_key in handled_keys:
                continue
            handled_keys.add(normalized_key)
            participating = [
                candidate
                for candidate in all_claims
                if any(
                    normalize_assertion(item.key) == normalized_key
                    for item in candidate.assertions
                )
            ]
            if len(participating) >= 3:
                resolution, cluster = self.create_conflict_resolution_task(
                    task, conflict.assertion_key, participating
                )
                resolution_tasks.append(resolution)
                conflict_clusters.append(cluster)
            else:
                resolution_tasks.extend(
                    self._create_resolution_task(task, item)
                    for item in conflicts
                    if normalize_assertion(item.assertion_key) == normalized_key
                )
        if conflicts:
            task.status = TaskStatus.RECURSE
            task.completed_at = None
            task.stopping_reason = None
            self.store.save_task(task)
        self.consolidator.evaluate_episodic(task, claim)
        return {
            "task": task,
            "claim": claim,
            "conflicts": conflicts,
            "resolution_tasks": resolution_tasks,
            "conflict_clusters": conflict_clusters,
        }

    def create_conflict_resolution_task(
        self, parent: Task, assertion_key: str, claims: list[Claim]
    ) -> tuple[Task, ConflictCluster]:
        """Persist one provenance-complete cluster and its bounded resolution task."""
        if len(claims) < 2:
            raise ValueError("A conflict resolution task requires at least two claims.")
        if any(claim.project_fingerprint != parent.project_fingerprint for claim in claims):
            raise ValueError("Conflict claims must match the parent project state.")
        existing_cluster = next(
            (
                cluster
                for cluster in self.store.conflict_clusters()
                if cluster.project_fingerprint == parent.project_fingerprint
                and normalize_assertion(cluster.assertion_key)
                == normalize_assertion(assertion_key)
            ),
            None,
        )
        cluster = build_conflict_cluster(
            parent.project_fingerprint, assertion_key, claims, existing_cluster
        )
        cluster.status = ClusterStatus.OPEN
        interpretations = ", ".join(
            f"'{item.value}' ({len(item.claim_ids)} claim{'s' if len(item.claim_ids) != 1 else ''})"
            for item in cluster.interpretations
        )
        question = (
            f"Resolve conflict cluster for assertion '{assertion_key}' across "
            f"{len(cluster.claim_ids)} claims: {interpretations}."
        )
        resolution = next(
            (
                task
                for task in self.store.tasks()
                if task.kind == TaskKind.RESOLUTION
                and task.project_fingerprint == parent.project_fingerprint
                and normalize_assertion(task.disputed_assertion_key or "")
                == normalize_assertion(assertion_key)
            ),
            None,
        )
        if resolution is None:
            resolution = Task.create(
                question,
                Path(parent.project_root),
                task_fingerprint(question, parent.project_fingerprint),
                parent.project_fingerprint,
            )
            resolution.kind = TaskKind.RESOLUTION
            resolution.depth = parent.depth + 1
        resolution.question = question
        resolution.parent_task_id = parent.id
        resolution.conflicting_claim_ids = cluster.claim_ids
        resolution.disputed_assertion_key = assertion_key
        resolution.conflict_cluster_id = cluster.id
        resolution.status = TaskStatus.OPEN
        resolution.completed_at = None
        resolution.stopping_reason = None
        cluster.resolution_task_id = resolution.id
        self.store.save_conflict_cluster(cluster)
        self.store.save_task(resolution)
        self.store.save_edge(
            GraphEdge(source=parent.id, relation=GraphRelation.SPAWNED, target=resolution.id)
        )
        self.store.save_edge(
            GraphEdge(
                source=resolution.id,
                relation=GraphRelation.HAS_CLUSTER,
                target=cluster.id,
            )
        )
        for claim_id in cluster.claim_ids:
            self.store.save_edge(
                GraphEdge(source=claim_id, relation=GraphRelation.SUPPORTS, target=cluster.id)
            )
        for claim_id in cluster.outlier_claim_ids:
            self.store.save_edge(
                GraphEdge(source=claim_id, relation=GraphRelation.OUTLIER, target=cluster.id)
            )
        for interpretation in cluster.interpretations:
            for index, left in enumerate(interpretation.claim_ids):
                for right in interpretation.claim_ids[index + 1 :]:
                    self.store.save_edge(
                        GraphEdge(
                            source=left,
                            relation=GraphRelation.CORROBORATES,
                            target=right,
                        )
                    )
        for index, interpretation in enumerate(cluster.interpretations):
            for other in cluster.interpretations[index + 1 :]:
                for left in interpretation.claim_ids:
                    for right in other.claim_ids:
                        self.store.save_edge(
                            GraphEdge(
                                source=left,
                                relation=GraphRelation.CONTRADICTS,
                                target=right,
                            )
                        )
        for claim_id in cluster.claim_ids:
            self.store.save_edge(
                GraphEdge(
                    source=resolution.id,
                    relation=GraphRelation.CONSIDERS,
                    target=claim_id,
                )
            )
        return resolution, cluster

    def _create_resolution_task(self, parent: Task, conflict: ClaimConflict) -> Task:
        left, right = conflict.left_claim_id, conflict.right_claim_id
        question = (
            f"Resolve contradiction for assertion '{conflict.assertion_key}': "
            f"{left} says '{conflict.left_value}', while {right} says "
            f"'{conflict.right_value}'."
        )
        existing = next(
            (
                task
                for task in self.store.tasks()
                if task.kind == TaskKind.RESOLUTION
                and task.project_fingerprint == parent.project_fingerprint
                and task.disputed_assertion_key == conflict.assertion_key
                and set(task.conflicting_claim_ids) == {left, right}
            ),
            None,
        )
        if existing is not None:
            return existing
        resolution = Task.create(
            question,
            Path(parent.project_root),
            task_fingerprint(question, parent.project_fingerprint),
            parent.project_fingerprint,
        )
        resolution.kind = TaskKind.RESOLUTION
        resolution.parent_task_id = parent.id
        resolution.depth = parent.depth + 1
        resolution.conflicting_claim_ids = [left, right]
        resolution.disputed_assertion_key = conflict.assertion_key
        self.store.save_task(resolution)
        self.store.save_edge(
            GraphEdge(source=parent.id, relation=GraphRelation.SPAWNED, target=resolution.id)
        )
        self.store.save_edge(
            GraphEdge(source=left, relation=GraphRelation.CONTRADICTS, target=right)
        )
        for claim_id in resolution.conflicting_claim_ids:
            self.store.save_edge(
                GraphEdge(source=resolution.id, relation=GraphRelation.CONSIDERS, target=claim_id)
            )
        return resolution

    def _reuse_discovery(self, state: SupervisorState) -> SupervisorState:
        task, claim = state["task"], state["cached_claim"]
        assert claim is not None
        task.status = TaskStatus.DONE
        task.reused_claim_id = claim.id
        task.reused_verdict_id = claim.conflict_verdict_id
        task.reuse_type = state["reuse_type"]
        task.relevance_score = state["relevance_match"].score
        task.reuse_reason = state["relevance_match"].reason
        task.completed_at = datetime.now(UTC)
        task.stopping_reason = StoppingReason.COMPLETED
        claim.successful_reuse_count += 1
        self.store.update_claim(claim)
        if claim.memory_tier == MemoryTier.SEMANTIC:
            self.consolidator.evaluate_procedural(task, claim)
        self.store.save_task(task)
        self.store.save_edge(
            GraphEdge(source=task.id, relation=GraphRelation.REUSED, target=claim.id)
        )
        if claim.conflict_verdict_id:
            self.store.save_edge(
                GraphEdge(
                    source=task.id,
                    relation=GraphRelation.REUSED_VERDICT,
                    target=claim.conflict_verdict_id,
                )
            )
        return {
            "task": task,
            "claim": claim,
            "cache_hit": True,
            "relevance_match": state["relevance_match"],
            "reuse_type": state["reuse_type"],
        }


class GraphGroundedSupervisor(Supervisor):
    """Supervisor whose repository state and provenance come from project onboarding."""

    def __init__(self, store: GraphStore, investigator: Investigator, **kwargs) -> None:
        super().__init__(
            store,
            investigator,
            onboarder=ReadOnlyProjectOnboarder(store),
            **kwargs,
        )
