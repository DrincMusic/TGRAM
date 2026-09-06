from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .fingerprint import file_content_hash, indexed_project_fingerprint, task_fingerprint
from .graph_debugging import GraphDirectedDebugger
from .models import (
    Assertion,
    Claim,
    Evidence,
    GraphEdge,
    GraphRelation,
    InvestigationResult,
    PostRepairReconciliation,
    PromotionStatus,
    RepairPromotion,
    SandboxCheckpoint,
    SandboxPromotionReconciliation,
    StoppingReason,
    Task,
    TaskKind,
    TaskStatus,
    TicketEvent,
)
from .onboarding import ProjectSelection, ReadOnlyProjectOnboarder, ReadOnlyViolation
from .provenance import capture_indexed_source_files, record_validity, supersede
from .store import GraphStore


class _ForbiddenInvestigator:
    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        raise RuntimeError("Reconciled follow-up unexpectedly repeated an investigation.")


class _ForbiddenSynthesizer:
    def synthesize(self, question: str, findings: list[Claim]) -> InvestigationResult:
        raise RuntimeError("Reconciled follow-up unexpectedly repeated synthesis.")


class PostRepairReconciler:
    """Refresh graph state after a verified real-project repair promotion."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.store.initialize()

    def reconcile(self, promotion_id: str) -> PostRepairReconciliation:
        promotion = self._promotion(promotion_id)
        if promotion.status != PromotionStatus.VERIFIED:
            raise ValueError("Only a final-test-verified promotion can be reconciled.")
        existing = next(
            (
                item
                for item in self.store.post_repair_reconciliations()
                if item.promotion_id == promotion.id
            ),
            None,
        )
        if existing is not None:
            return existing
        proposal = next(
            (item for item in self.store.repair_proposals() if item.id == promotion.proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"Repair proposal not found: {promotion.proposal_id}")
        selection = ProjectSelection.explicit(promotion.project_root)
        affected = sorted(change.path for change in promotion.changes)
        if not affected:
            raise ValueError("A promoted repair must identify at least one affected file.")

        scan = ReadOnlyProjectOnboarder(self.store).scan(selection)
        observed = sorted(
            change.path for change in scan.changes if change.kind.value != "UNCHANGED"
        )
        if observed != affected:
            raise ReadOnlyViolation(
                "Post-repair scan observed changes outside the promoted patch: "
                f"expected {affected}, observed {observed}"
            )
        if scan.parsed_file_count != len(affected):
            raise RuntimeError(
                "Post-repair scan did not parse exactly the promoted affected files."
            )
        files = self.store.project_files(scan.project_id)
        state = indexed_project_fingerprint(
            selection.root, [(item.path, item.content_hash) for item in files]
        )
        task = Task(
            question=f"Record the repaired state of {proposal.test_path}.",
            fingerprint=task_fingerprint(f"reconcile:{promotion.id}", state),
            project_fingerprint=state,
            project_root=str(selection.root),
            kind=TaskKind.FOLLOW_UP,
            parent_task_id=proposal.repair_task_id,
            relevant_files=affected,
            status=TaskStatus.DONE,
            attempt_count=0,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            stopping_reason=StoppingReason.COMPLETED,
        )
        replacement = Claim(
            fingerprint=task_fingerprint(f"repaired-state:{proposal.test_path}", state),
            project_fingerprint=state,
            project_root=str(selection.root),
            subject=f"Current repaired state of {proposal.test_path}",
            producer=type(self).__name__,
            conclusion=(
                f"The promoted repair is active and {proposal.test_path} passes in the "
                "explicitly selected project."
            ),
            confidence=1.0,
            evidence=[
                Evidence(
                    path=proposal.test_path,
                    detail=(
                        "Real-project final validation exited 0 after the approved patch: "
                        + (promotion.final_validation.stdout.strip() if promotion.final_validation else "")
                    ),
                )
            ],
            files_examined=affected,
            assertions=[
                Assertion(key=f"test.status:{proposal.test_path}", value="passing"),
                Assertion(key="repair.promotion", value=promotion.id),
            ],
            source_claim_ids=scan.invalidated_claim_ids,
        )
        replacement.source_files = capture_indexed_source_files(replacement, files)
        task.output_claim_id = replacement.id
        task.source_claim_ids = scan.invalidated_claim_ids
        self.store.save_task(task)
        self.store.save_claim(task, replacement)
        superseded_ids: list[str] = []
        for claim_id in scan.invalidated_claim_ids:
            obsolete = self.store.get_claim(claim_id)
            if obsolete is None:
                continue
            supersede(obsolete, replacement, state)
            self.store.update_claim(obsolete)
            self.store.save_edge(
                GraphEdge(
                    source=replacement.id,
                    relation=GraphRelation.SUPERSEDES,
                    target=obsolete.id,
                )
            )
            superseded_ids.append(obsolete.id)
        follow_up = GraphDirectedDebugger(
            self.store, _ForbiddenInvestigator(), _ForbiddenSynthesizer()
        ).debug(
            f"What is the current status of {proposal.test_path}?",
            selection.root,
            proposal.test_path,
        )
        if (
            follow_up.worker_calls != 0
            or follow_up.root_task.reuse_type != "reconciled-repair"
            or follow_up.diagnosis.id != replacement.id
        ):
            raise RuntimeError("Follow-up did not reuse the reconciled repaired-state claim.")
        reconciliation = PostRepairReconciliation(
            promotion_id=promotion.id,
            proposal_id=proposal.id,
            project_root=str(selection.root),
            previous_project_fingerprint=proposal.project_fingerprint,
            new_project_fingerprint=state,
            scan_id=scan.id,
            affected_paths=affected,
            parsed_paths=observed,
            parsed_file_count=scan.parsed_file_count,
            content_read_file_count=scan.content_read_file_count,
            reused_file_ids=scan.reused_file_ids,
            invalidated_claim_ids=scan.invalidated_claim_ids,
            superseded_claim_ids=superseded_ids,
            replacement_claim_id=replacement.id,
            follow_up_task_id=follow_up.root_task.id,
            follow_up_claim_id=follow_up.diagnosis.id,
            follow_up_reuse_type=follow_up.root_task.reuse_type or "",
            follow_up_worker_calls=follow_up.worker_calls,
        )
        self.store.save_post_repair_reconciliation(reconciliation)
        return reconciliation

    def _promotion(self, promotion_id: str) -> RepairPromotion:
        promotion = next(
            (item for item in self.store.repair_promotions() if item.id == promotion_id),
            None,
        )
        if promotion is None:
            raise ValueError(f"Repair promotion not found: {promotion_id}")
        return promotion


class SandboxPromotionReconciler:
    """Incrementally reconcile a successful sandbox promotion without source writes."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.store.initialize()

    def reconcile(self, ticket_id: str, attempt_id: str) -> SandboxPromotionReconciliation:
        attempt = next(
            (item for item in self.store.implementation_sandboxes(ticket_id) if item.id == attempt_id),
            None,
        )
        if attempt is None:
            raise ValueError(f"Sandbox attempt not found: {attempt_id}")
        promotion = attempt.promotion
        if attempt.status != "PROMOTED" or promotion is None or promotion.status != "PROMOTED":
            raise ValueError("Only a successfully promoted sandbox attempt can be reconciled.")
        if promotion.reconciliation is not None:
            return promotion.reconciliation
        changed = sorted({item.path for item in attempt.changes})
        if not changed:
            raise ValueError("A promoted sandbox must identify changed paths.")
        root = Path(attempt.project_root).resolve(strict=True)
        source_before = self._source_bytes(root)
        old_files = self.store.project_files(attempt.project_id)
        indexed_paths = {item.path for item in old_files}
        onboarder = ReadOnlyProjectOnboarder(self.store)
        current_sources = onboarder._sources(root)  # read-only preflight before graph mutation
        current_paths = {item.path for item in current_sources}
        if current_paths != indexed_paths:
            raise ReadOnlyViolation("Registered source paths changed after promotion; reconcile is stale.")
        current_manifest = indexed_project_fingerprint(
            root,
            [
                (item.path, file_content_hash(root / item.path))
                for item in old_files
            ],
        )
        if current_manifest != promotion.final_manifest_sha256:
            raise ReadOnlyViolation("Registered source changed after promotion; reconcile is stale.")
        dependents = self._dependents(changed, old_files, self.store.project_dependencies(attempt.project_id))
        forced = set(changed) | set(dependents)
        result = SandboxPromotionReconciliation(
            attempt_id=attempt.id,
            promotion_id=promotion.id,
            ticket_id=ticket_id,
            project_id=attempt.project_id,
            project_root=str(root),
            previous_manifest_sha256=attempt.initial_manifest_sha256,
            new_manifest_sha256=promotion.final_manifest_sha256 or "",
            scan_id="PENDING",
            changed_paths=changed,
            dependent_paths=dependents,
        )
        self._checkpoint(result, "CREATED", "Post-promotion reconciliation started.")
        scan = onboarder.scan(ProjectSelection.explicit(root), force_parse_paths=forced)
        observed = sorted(item.path for item in scan.changes if item.kind.value != "UNCHANGED")
        if observed != changed:
            raise ReadOnlyViolation(
                f"Reconciliation observed unexpected source changes: expected {changed}, observed {observed}"
            )
        files = self.store.project_files(attempt.project_id)
        parsed = sorted(item.path for item in files if item.id not in set(scan.reused_file_ids))
        if parsed != sorted(forced):
            raise RuntimeError(
                f"Incremental reconciliation parsed unexpected paths: expected {sorted(forced)}, parsed {parsed}"
            )
        state = indexed_project_fingerprint(root, [(item.path, item.content_hash) for item in files])
        if state != promotion.final_manifest_sha256:
            raise ReadOnlyViolation("Reconciled manifest does not match the promoted source state.")
        result.scan_id = scan.id
        result.new_manifest_sha256 = state
        result.parsed_paths = parsed
        result.reused_file_ids = scan.reused_file_ids
        invalidated = set(scan.invalidated_claim_ids)
        for claim in self.store.claims():
            paths = {item.path for item in claim.source_files} | set(claim.files_examined)
            if claim.project_root and Path(claim.project_root).resolve() == root and paths & forced:
                if record_validity(
                    claim,
                    False,
                    state,
                    "Invalidated by post-promotion reconciliation of source or dependency state.",
                ):
                    self.store.update_claim(claim)
                invalidated.add(claim.id)
        result.invalidated_claim_ids = sorted(invalidated)
        self._checkpoint(result, "INDEXED", f"Parsed {len(parsed)} promoted or dependent files.")
        replacements: list[Claim] = []
        for path in changed:
            task = Task.create(
                f"Record reconciled source state for {path}.",
                root,
                task_fingerprint(f"sandbox-reconcile:{promotion.id}:{path}", state),
                state,
            )
            task.kind = TaskKind.FOLLOW_UP
            task.status = TaskStatus.DONE
            task.attempt_count = 0
            task.completed_at = datetime.now(UTC)
            task.stopping_reason = StoppingReason.COMPLETED
            task.relevant_files = [path]
            replacement = Claim(
                fingerprint=task_fingerprint(f"reconciled-source:{path}", state),
                project_fingerprint=state,
                project_root=str(root),
                subject=f"Current reconciled source state for {path}",
                producer=type(self).__name__,
                conclusion=f"The promoted bytes for {path} are indexed in manifest {state}.",
                confidence=1,
                evidence=[Evidence(path=path, detail="Promoted content was incrementally reindexed.")],
                files_examined=[path],
                assertions=[Assertion(key=f"source.manifest:{path}", value=state)],
                source_claim_ids=result.invalidated_claim_ids,
            )
            replacement.source_files = capture_indexed_source_files(replacement, files)
            task.output_claim_id = replacement.id
            task.source_claim_ids = result.invalidated_claim_ids
            self.store.save_task(task)
            self.store.save_claim(task, replacement)
            replacements.append(replacement)
            result.replacement_task_ids.append(task.id)
            result.replacement_claim_ids.append(replacement.id)
        for claim_id in result.invalidated_claim_ids:
            obsolete = self.store.get_claim(claim_id)
            if obsolete is None or obsolete.id in result.replacement_claim_ids:
                continue
            replacement = next(
                (
                    item
                    for item in replacements
                    if set(item.files_examined)
                    & ({source.path for source in obsolete.source_files} | set(obsolete.files_examined))
                ),
                replacements[0],
            )
            supersede(obsolete, replacement, state)
            self.store.update_claim(obsolete)
            self.store.save_edge(
                GraphEdge(source=replacement.id, relation=GraphRelation.SUPERSEDES, target=obsolete.id)
            )
            result.superseded_claim_ids.append(obsolete.id)
        for record in self.store.project_workspace_records():
            if record.project_id != attempt.project_id:
                continue
            if record.indexed_manifest_sha256 == state and not set(record.affected_paths) & forced:
                continue
            record.status = "STALE"
            record.stale_evidence_rejected = True
            record.approval_status = "SUPERSEDED" if record.approval_status else None
            record.execution_authorized = False
            self.store.save_project_workspace_record(record)
            result.invalidated_workspace_record_ids.append(record.id)
        for decision in attempt.validation_decisions:
            if decision.path in forced and decision.status in {"PASSED", "SATISFIED"}:
                decision.status = "SUPERSEDED"
                result.superseded_validation_decision_ids.append(decision.id)
        result.evidence = [Evidence(path=path, detail=f"Reindexed under manifest {state}.") for path in parsed]
        result.source_unchanged_during_reconciliation = source_before == self._source_bytes(root)
        if not result.source_unchanged_during_reconciliation:
            raise ReadOnlyViolation("Registered source changed during graph reconciliation.")
        result.completed_at = datetime.now(UTC)
        self._checkpoint(result, "RECONCILED", f"Created {len(replacements)} replacement claims.")
        promotion.reconciliation = result
        attempt.checkpoints.append(
            SandboxCheckpoint(
                sequence=len(attempt.checkpoints) + 1,
                stage="RECONCILED",
                detail=f"Graph reconciled in {result.id}; no project writes performed.",
            )
        )
        self.store.save_implementation_sandbox(attempt)
        self.store.save_ticket_event(
            TicketEvent(
                ticket_id=ticket_id,
                kind="SANDBOX_PROMOTION_RECONCILED",
                detail=f"Promotion {promotion.id} reconciled into manifest {state}.",
                actor="Observer reconciliation",
                artifact_ids=[result.id, scan.id, *result.replacement_claim_ids],
            )
        )
        return result

    @staticmethod
    def _dependents(changed: list[str], files, dependencies) -> list[str]:
        path_to_id = {item.path: item.id for item in files}
        frontier = {path_to_id[path] for path in changed if path in path_to_id}
        found: set[str] = set()
        while frontier:
            paths = {
                item.source_path
                for item in dependencies
                if item.target_file_id in frontier and item.source_path not in set(changed) | found
            }
            if not paths:
                break
            found.update(paths)
            frontier = {path_to_id[path] for path in paths if path in path_to_id}
        return sorted(found)

    @staticmethod
    def _source_bytes(root: Path) -> dict[str, bytes]:
        return {
            item.relative_to(root).as_posix(): item.read_bytes()
            for item in root.rglob("*")
            if item.is_file()
        }

    @staticmethod
    def _checkpoint(result: SandboxPromotionReconciliation, stage: str, detail: str) -> None:
        result.checkpoints.append(
            SandboxCheckpoint(sequence=len(result.checkpoints) + 1, stage=stage, detail=detail)
        )
