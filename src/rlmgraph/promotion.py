from __future__ import annotations

import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

from .fingerprint import file_content_hash
from .models import (
    ApprovalDecision,
    PromotionEvent,
    PromotionRunResult,
    PromotionStatus,
    RepairApproval,
    RepairPromotion,
    RepairProposal,
    RepairStatus,
    RepairValidation,
    TestExecution,
)
from .onboarding import ProjectSelection, ReadOnlyViolation
from .reconciliation import PostRepairReconciler
from .repair import _tree_fingerprint
from .store import GraphStore


class RepairPromoter:
    """Apply a verified repair only after a durable, explicit human decision."""

    def __init__(self, store: GraphStore, *, test_timeout_seconds: float = 30) -> None:
        self.store = store
        self.test_timeout_seconds = test_timeout_seconds
        self.store.initialize()

    def review(self, proposal_id: str) -> tuple[RepairProposal, RepairValidation]:
        proposal = next(
            (item for item in self.store.repair_proposals() if item.id == proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"Repair proposal not found: {proposal_id}")
        validation = next(
            (
                item
                for item in reversed(self.store.repair_validations())
                if item.proposal_id == proposal.id
                and item.status == RepairStatus.VERIFIED
            ),
            None,
        )
        if proposal.status != RepairStatus.VERIFIED or validation is None:
            raise ValueError("Only a sandbox-verified repair can be promoted.")
        return proposal, validation

    def decide(
        self,
        proposal_id: str,
        project_root: str | Path,
        *,
        decision: ApprovalDecision,
        approved_by: str,
        reason: str,
    ) -> PromotionRunResult:
        proposal, validation = self.review(proposal_id)
        selection = ProjectSelection.explicit(project_root)
        if selection.root != Path(proposal.project_root).resolve():
            raise ReadOnlyViolation(
                "The explicitly selected project does not match the repair proposal."
            )
        if not approved_by.strip() or not reason.strip():
            raise ValueError("A human identity and decision reason are required.")
        self._require_onboarded_selection(selection)
        approval = RepairApproval(
            proposal_id=proposal.id,
            validation_id=validation.id,
            project_root=str(selection.root),
            proposal_signature=proposal.signature,
            source_tree_fingerprint=proposal.source_tree_fingerprint,
            decision=decision,
            approved_by=approved_by.strip(),
            reason=reason.strip(),
        )
        self.store.save_repair_approval(approval)
        if decision == ApprovalDecision.REJECTED:
            return PromotionRunResult(approval=approval)
        try:
            promotion = self._promote(proposal, validation, approval, selection)
        except (ValueError, ReadOnlyViolation) as exc:
            promotion = RepairPromotion(
                proposal_id=proposal.id,
                validation_id=validation.id,
                approval_id=approval.id,
                project_root=str(selection.root),
                status=PromotionStatus.APPLICATION_FAILED,
                changes=proposal.changes,
                original_tree_fingerprint=_tree_fingerprint(selection.root),
                failure_reason=f"promotion precondition failed: {exc}",
                events=[
                    PromotionEvent(
                        status=PromotionStatus.APPROVED,
                        detail="Human approval recorded.",
                    ),
                    PromotionEvent(
                        status=PromotionStatus.APPLICATION_FAILED,
                        detail=f"Promotion refused before source writes: {exc}",
                    ),
                ],
                completed_at=datetime.now(UTC),
            )
            self.store.save_repair_promotion(promotion)
            raise
        return PromotionRunResult(approval=approval, promotion=promotion)

    def resume_approval(self, approval_id: str) -> PromotionRunResult:
        """Resume an already persisted decision without creating another approval."""
        approval = next(
            (item for item in self.store.repair_approvals() if item.id == approval_id),
            None,
        )
        if approval is None:
            raise ValueError(f"Repair approval not found: {approval_id}")
        if approval.decision == ApprovalDecision.REJECTED:
            return PromotionRunResult(approval=approval)
        proposal, validation = self.review(approval.proposal_id)
        selection = ProjectSelection.explicit(approval.project_root)
        existing = next(
            (
                item
                for item in reversed(self.store.repair_promotions(proposal.id))
                if item.approval_id == approval.id
            ),
            None,
        )
        if existing is None:
            return PromotionRunResult(
                approval=approval,
                promotion=self._promote(proposal, validation, approval, selection),
            )
        if existing.status == PromotionStatus.VERIFIED:
            PostRepairReconciler(self.store).reconcile(existing.id)
            return PromotionRunResult(approval=approval, promotion=existing)
        if existing.status in {
            PromotionStatus.ROLLED_BACK,
            PromotionStatus.APPLICATION_FAILED,
        }:
            return PromotionRunResult(approval=approval, promotion=existing)
        return PromotionRunResult(
            approval=approval,
            promotion=self._recover_interrupted(existing, proposal, selection),
        )

    def _recover_interrupted(
        self,
        promotion: RepairPromotion,
        proposal: RepairProposal,
        selection: ProjectSelection,
    ) -> RepairPromotion:
        if any(change.before_content is None for change in proposal.changes):
            promotion.status = PromotionStatus.APPLICATION_FAILED
            promotion.failure_reason = "Interrupted promotion lacks recoverable original bytes."
            promotion.completed_at = datetime.now(UTC)
            promotion.events.append(
                PromotionEvent(
                    status=PromotionStatus.APPLICATION_FAILED,
                    detail=promotion.failure_reason,
                )
            )
            self.store.save_repair_promotion(promotion)
            return promotion
        paths = self._validated_paths(selection, proposal)
        modes = {target: stat.S_IMODE(target.stat().st_mode) for target in paths}
        originals = {
            target: (change.before_content or "").encode("utf-8")
            for change, target in zip(proposal.changes, paths, strict=True)
        }
        rollback_error: OSError | None = None
        try:
            self._restore_all(originals, modes)
        except OSError as exc:
            rollback_error = exc
        promotion.rollback_tree_fingerprint = _tree_fingerprint(selection.root)
        promotion.rollback_verified = rollback_error is None and (
            promotion.rollback_tree_fingerprint == promotion.original_tree_fingerprint
        )
        promotion.rollback_validation = self._execute(
            self._test_command(proposal.test_path), selection.root
        )
        promotion.status = (
            PromotionStatus.ROLLED_BACK
            if promotion.rollback_verified
            else PromotionStatus.APPLICATION_FAILED
        )
        promotion.failure_reason = (
            "Interrupted promotion was automatically rolled back during resume."
            if promotion.rollback_verified
            else f"Interrupted promotion rollback failed: {rollback_error}"
        )
        promotion.completed_at = datetime.now(UTC)
        promotion.events.append(
            PromotionEvent(status=promotion.status, detail=promotion.failure_reason)
        )
        self.store.save_repair_promotion(promotion)
        return promotion

    def _promote(
        self,
        proposal: RepairProposal,
        validation: RepairValidation,
        approval: RepairApproval,
        selection: ProjectSelection,
    ) -> RepairPromotion:
        if not proposal.source_tree_fingerprint:
            raise ValueError("Proposal predates promotion-safe source binding; revalidate it.")
        if not proposal.changes or any(
            change.after_content is None for change in proposal.changes
        ):
            raise ValueError("Proposal does not contain the exact verified patch content.")
        current_tree = _tree_fingerprint(selection.root)
        if current_tree != proposal.source_tree_fingerprint:
            raise ReadOnlyViolation(
                "The selected project changed after sandbox validation; revalidate the repair."
            )
        paths = self._validated_paths(selection, proposal)
        for change, target in zip(proposal.changes, paths, strict=True):
            if file_content_hash(target) != change.before_hash:
                raise ReadOnlyViolation(f"Source precondition failed for {change.path}.")

        promotion = RepairPromotion(
            proposal_id=proposal.id,
            validation_id=validation.id,
            approval_id=approval.id,
            project_root=str(selection.root),
            status=PromotionStatus.APPROVED,
            changes=proposal.changes,
            original_tree_fingerprint=current_tree,
            events=[PromotionEvent(status=PromotionStatus.APPROVED, detail="Human approval recorded.")],
        )
        self.store.save_repair_promotion(promotion)
        originals = {target: target.read_bytes() for target in paths}
        modes = {target: stat.S_IMODE(target.stat().st_mode) for target in paths}
        applied = False
        try:
            promotion.status = PromotionStatus.APPLYING
            promotion.events.append(
                PromotionEvent(
                    status=PromotionStatus.APPLYING,
                    detail="All source hashes matched; atomically replacing authorized files.",
                )
            )
            self.store.save_repair_promotion(promotion)
            applied = True
            self._replace_all(paths, proposal, modes)
            for change, target in zip(proposal.changes, paths, strict=True):
                if file_content_hash(target) != change.after_hash:
                    raise OSError(f"Applied content hash mismatch for {change.path}.")
            promotion.applied_tree_fingerprint = _tree_fingerprint(selection.root)
            promotion.status = PromotionStatus.APPLIED
            promotion.events.append(
                PromotionEvent(
                    status=PromotionStatus.APPLIED,
                    detail="Verified sandbox bytes applied to every authorized target.",
                )
            )
            self.store.save_repair_promotion(promotion)
            command = self._test_command(proposal.test_path)
            promotion.final_validation = self._execute(command, selection.root)
            stable_after_test = (
                _tree_fingerprint(selection.root) == promotion.applied_tree_fingerprint
            )
            if promotion.final_validation.exit_code == 0 and stable_after_test:
                promotion.status = PromotionStatus.VERIFIED
                promotion.completed_at = datetime.now(UTC)
                promotion.events.append(
                    PromotionEvent(
                        status=PromotionStatus.VERIFIED,
                        detail="Affected test passed in the explicitly selected project.",
                    )
                )
                self.store.save_repair_promotion(promotion)
                PostRepairReconciler(self.store).reconcile(promotion.id)
                return promotion
            reasons = []
            if promotion.final_validation.exit_code != 0:
                reasons.append(
                    f"real-project test exited {promotion.final_validation.exit_code}"
                )
            if not stable_after_test:
                reasons.append("real-project test changed project contents")
            promotion.failure_reason = "; ".join(reasons)
        except OSError as exc:
            promotion.failure_reason = f"application failed: {exc}"
        rollback_error: OSError | None = None
        if applied:
            try:
                self._restore_all(originals, modes)
            except OSError as exc:
                rollback_error = exc
                promotion.failure_reason = (
                    f"{promotion.failure_reason}; rollback failed: {exc}"
                )
        promotion.rollback_tree_fingerprint = _tree_fingerprint(selection.root)
        promotion.rollback_verified = rollback_error is None and (
            promotion.rollback_tree_fingerprint == promotion.original_tree_fingerprint
        )
        promotion.rollback_validation = self._execute(
            self._test_command(proposal.test_path), selection.root
        )
        promotion.status = (
            PromotionStatus.ROLLED_BACK
            if promotion.rollback_verified
            else PromotionStatus.APPLICATION_FAILED
        )
        promotion.completed_at = datetime.now(UTC)
        promotion.events.append(
            PromotionEvent(
                status=promotion.status,
                detail=(
                    "Original project bytes restored after failed final validation."
                    if promotion.rollback_verified
                    else "Automatic rollback could not restore the original tree fingerprint."
                ),
            )
        )
        self.store.save_repair_promotion(promotion)
        return promotion

    def _require_onboarded_selection(self, selection: ProjectSelection) -> None:
        selected = [
            project
            for project in self.store.projects()
            if Path(project.root).resolve() == selection.root
            and project.explicitly_selected
        ]
        if not selected:
            raise ReadOnlyViolation(
                "Promotion requires an explicitly selected, onboarded project record."
            )

    @staticmethod
    def _validated_paths(
        selection: ProjectSelection, proposal: RepairProposal
    ) -> list[Path]:
        paths: list[Path] = []
        authorized = set(proposal.authorized_paths)
        for change in proposal.changes:
            if change.path not in authorized:
                raise ReadOnlyViolation(f"Patch path is not authorized: {change.path}")
            relative = Path(change.path)
            if relative.is_absolute():
                raise ReadOnlyViolation(f"Absolute patch path is forbidden: {change.path}")
            target = (selection.root / relative).resolve(strict=True)
            try:
                target.relative_to(selection.root)
            except ValueError as exc:
                raise ReadOnlyViolation(
                    f"Patch path escapes the selected project: {change.path}"
                ) from exc
            if not target.is_file():
                raise ReadOnlyViolation(f"Patch target is not a regular file: {change.path}")
            paths.append(target)
        return paths

    @staticmethod
    def _replace_all(
        paths: list[Path], proposal: RepairProposal, modes: dict[Path, int]
    ) -> None:
        staged: list[tuple[Path, Path]] = []
        try:
            for change, target in zip(proposal.changes, paths, strict=True):
                with NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    prefix=".rlmgraph-promote-",
                    dir=target.parent,
                    delete=False,
                ) as handle:
                    handle.write(change.after_content or "")
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged_path = Path(handle.name)
                os.chmod(staged_path, modes[target])
                staged.append((staged_path, target))
            for staged_path, target in staged:
                os.replace(staged_path, target)
        finally:
            for staged_path, _ in staged:
                staged_path.unlink(missing_ok=True)

    @staticmethod
    def _restore_all(originals: dict[Path, bytes], modes: dict[Path, int]) -> None:
        for target, content in originals.items():
            with NamedTemporaryFile(
                mode="wb",
                prefix=".rlmgraph-rollback-",
                dir=target.parent,
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                staged = Path(handle.name)
            os.chmod(staged, modes[target])
            os.replace(staged, target)

    @staticmethod
    def _test_command(test_path: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "pytest",
            test_path,
            "-q",
            "-p",
            "no:cacheprovider",
        ]

    def _execute(self, command: list[str], cwd: Path) -> TestExecution:
        started = perf_counter()
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.test_timeout_seconds,
            )
            return TestExecution(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout[-20_000:],
                stderr=completed.stderr[-20_000:],
                duration_ms=(perf_counter() - started) * 1000,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
            return TestExecution(
                command=command,
                exit_code=124,
                stdout=stdout[-20_000:],
                stderr=stderr[-20_000:],
                duration_ms=(perf_counter() - started) * 1000,
            )
