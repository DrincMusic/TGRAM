from __future__ import annotations

import ast
import base64
import difflib
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import perf_counter
from typing import ClassVar, Protocol

from .adapters import CodexCliInvestigator
from .fingerprint import file_content_hash, indexed_project_fingerprint
from .governance import ProjectGovernance
from .models import (
    Evidence,
    ImplementationSandboxAttempt,
    ObserverActivityState,
    PatchChange,
    ProjectLeaseEventKind,
    RepairWorkerResult,
    SandboxCheckpoint,
    SandboxExternalValidationReport,
    SandboxMutationJournal,
    SandboxMutationJournalEntry,
    SandboxPromotionApproval,
    SandboxPromotionRecord,
    SandboxValidationDecision,
    SandboxValidationWorkerExecution,
    TestExecution,
    ValidationWorkerLimits,
    ValidationWorkerSpec,
)
from .onboarding import ReadOnlyViolation
from .project_symbol_memory import ProjectSymbolMemory
from .scheduler import ResourceAwareScheduler, SchedulingCancelled
from .ticketing import TicketManager
from .validation_workers import BoundedValidationRunner


class PlanImplementationWorker(Protocol):
    def implement(
        self, request: str, evidence: list[Evidence], sandbox_root: Path
    ) -> RepairWorkerResult: ...


class CodexPlanImplementationWorker:
    """Expose Codex only to the disposable mirror, never the registered project root."""

    SUPPORTED_REASONING_EFFORTS: ClassVar[set[str]] = {
        "none", "low", "medium", "high", "xhigh", "max",
    }

    def __init__(
        self,
        executable: str = "codex",
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if (
            reasoning_effort is not None
            and reasoning_effort not in self.SUPPORTED_REASONING_EFFORTS
        ):
            raise ValueError(f"Unsupported implementation reasoning effort: {reasoning_effort}")
        self.adapter = CodexCliInvestigator(
            executable=executable, model=model, sandbox="read-only"
        )
        self.reasoning_effort = reasoning_effort

    def implement(
        self, request: str, evidence: list[Evidence], sandbox_root: Path
    ) -> RepairWorkerResult:
        del evidence
        root = sandbox_root.resolve(strict=True)
        symbol_memory = ProjectSymbolMemory(
            root.parent / f"{root.name}-symbol-memory.json"
        )
        symbol_memory.refresh(root)
        symbol_context = symbol_memory.retrieve(request, project_root=root)
        if not symbol_context:
            raise ValueError("The bounded project has no addressable Python symbols.")

        with TemporaryDirectory(prefix="rlmgraph-single-call-") as directory:
            patch = self.adapter.single_call_surgical_edit(
                request,
                symbol_context,
                Path(directory),
                reasoning_effort=getattr(self, "reasoning_effort", None),
            )

        changed: list[str] = []
        authorized = {
            (item["path"], item["symbol"]): item for item in symbol_context
        }
        edits_by_path: dict[str, list] = {}
        seen: set[tuple[str, str]] = set()
        for edit in patch.edits:
            relative = edit.path.replace("\\", "/")
            key = (relative, edit.target_symbol)
            context = authorized.get(key)
            if context is None or key in seen:
                raise ValueError(f"Surgical edit referenced an unauthorized symbol: {key}")
            target = (root / relative).resolve(strict=True)
            target.relative_to(root)
            live_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
            live_segment = "".join(
                live_lines[context["start_line"] - 1 : context["end_line"]]
            )
            live_hash = hashlib.sha256(live_segment.encode()).hexdigest()
            if live_hash != context["content_hash"]:
                raise ValueError(
                    f"Authorized symbol changed during the model call: {edit.target_symbol}"
                )
            if len(edit.content) > 12_000:
                raise ValueError("Surgical edit content exceeded its bounded size.")
            seen.add(key)
            edits_by_path.setdefault(relative, []).append((edit, context))

        staged: dict[Path, tuple[str, str]] = {}
        for relative, edits in edits_by_path.items():
            target = (root / relative).resolve(strict=True)
            target.relative_to(root)
            source = target.read_text(encoding="utf-8")
            lines = source.splitlines(keepends=True)
            for edit, context in sorted(
                edits, key=lambda item: item[1]["start_line"], reverse=True
            ):
                start, end = context["start_line"] - 1, context["end_line"]
                original_line = lines[start] if start < len(lines) else ""
                indentation = original_line[: len(original_line) - len(original_line.lstrip())]
                normalized = textwrap.dedent(edit.content).strip("\r\n")
                content = textwrap.indent(normalized, indentation) + "\n"
                if edit.operation == "REPLACE_SYMBOL":
                    lines[start:end] = [content]
                else:
                    lines[end:end] = [content]
            updated = "".join(lines)
            ast.parse(updated)
            if updated != source:
                staged[target] = (relative, updated)
        for target, (relative, updated) in staged.items():
            target.write_text(updated, encoding="utf-8")
            changed.append(relative)
        symbol_memory.refresh(root)
        return RepairWorkerResult(
            rationale=patch.rationale,
            confidence=patch.confidence,
            files_read=sorted({item["path"] for item in symbol_context}),
            files_changed=changed,
            file_change_reasons={path: "\n".join(dict.fromkeys(
                edit.change_reason for edit in patch.edits
                if edit.path.replace("\\", "/") == path and edit.change_reason
            )) for path in changed},
            model_calls=1,
        )

    def implement_full_context(
        self, request: str, evidence: list[Evidence], sandbox_root: Path,
    ) -> RepairWorkerResult:
        """Baseline path: one call receives complete current files and replaces whole files."""
        del evidence
        root = sandbox_root.resolve(strict=True)
        source_files: dict[str, str] = {}
        total_characters = 0
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            total_characters += len(content)
            if len(source_files) >= 20 or total_characters > 120_000:
                raise ValueError("Baseline full-file context exceeded its controlled bound.")
            source_files[path.relative_to(root).as_posix()] = content
        if not source_files:
            raise ValueError("The baseline project has no UTF-8 source files.")
        with TemporaryDirectory(prefix="rlmgraph-baseline-call-") as directory:
            patch = self.adapter.single_call_patch(request, source_files, Path(directory))
        staged: dict[Path, tuple[str, str]] = {}
        seen: set[str] = set()
        for replacement in patch.replacements:
            relative = replacement.path.replace("\\", "/")
            if relative not in source_files or relative in seen:
                raise ValueError(f"Baseline replacement referenced an unauthorized file: {relative}")
            seen.add(relative)
            target = (root / relative).resolve(strict=True)
            target.relative_to(root)
            if target.suffix == ".py":
                ast.parse(replacement.content)
            if replacement.content != source_files[relative]:
                staged[target] = (relative, replacement.content)
        for target, (_, content) in staged.items():
            target.write_text(content, encoding="utf-8")
        return RepairWorkerResult(
            rationale=patch.rationale, confidence=patch.confidence,
            files_read=sorted(source_files),
            files_changed=[relative for relative, _ in staged.values()],
            file_change_reasons={item.path.replace("\\", "/"): item.change_reason
                                 for item in patch.replacements if item.change_reason},
            model_calls=1,
        )

    def evidence_configuration(self) -> dict[str, object]:
        command = [
            self.adapter.executable, "exec", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules",
            "--sandbox", self.adapter.sandbox, "--color", "never",
            "--output-schema", "<temporary-schema>", "--output-last-message",
            "<temporary-result>", "--cd", "<empty-model-root>",
        ]
        if self.adapter.model:
            command.extend(["--model", self.adapter.model])
        reasoning_effort = getattr(self, "reasoning_effort", None)
        if reasoning_effort:
            command.extend([
                "--config", f'model_reasoning_effort="{reasoning_effort}"',
            ])
        command.append("-")
        return {
            "provider": "OpenAI Codex CLI",
            "executable": self.adapter.executable,
            "model": self.adapter.model or "Codex CLI configured default",
            "reasoning_effort": (
                getattr(self, "reasoning_effort", None) or "Codex CLI configured default"
            ),
            "sandbox": self.adapter.sandbox,
            "command": command,
        }


class ImplementationSandboxManager:
    """Run an approved ticket plan inside a disposable authorized-file mirror."""

    def __init__(
        self,
        store,
        worker: PlanImplementationWorker,
        *,
        validation_timeout_seconds: float = 30,
        fault_injector: Callable[[str], None] | None = None,
        validation_workers: list[ValidationWorkerSpec] | None = None,
        validation_runner: BoundedValidationRunner | None = None,
        max_external_report_bytes: int = 1_000_000,
    ) -> None:
        self.store = store
        self.worker = worker
        self.validation_timeout_seconds = validation_timeout_seconds
        self.fault_injector = fault_injector
        workers = validation_workers if validation_workers is not None else [
            ValidationWorkerSpec(
                id="BUILTIN-PYTHON-PYTEST",
                name="Bounded Python pytest",
                categories=["PYTHON_TEST"],
                artifact_kinds=["PYTHON"],
                executable=sys.executable,
                arguments=["-m", "pytest", "{path}", "-q", "-p", "no:cacheprovider"],
                limits=ValidationWorkerLimits(
                    max_wall_time_seconds=validation_timeout_seconds,
                    max_processes=4,
                    max_memory_bytes=512 * 1024 * 1024,
                    max_output_bytes=20_000,
                    allowed_artifact_kinds=["PYTHON"],
                    allowed_executables=[str(Path(sys.executable).resolve())],
                ),
                authorized_by="RLMGraph built-in policy",
                authorization_reason="Targeted pytest within the approved sandbox path slice.",
            ),
            ValidationWorkerSpec(
                id="BUILTIN-PYTHON-SYNTAX",
                name="Bounded Python syntax validation",
                categories=["PYTHON_TEST"],
                artifact_kinds=["PYTHON"],
                executable=sys.executable,
                arguments=[
                    "-c",
                    "import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], 'exec')",
                    "{path}",
                ],
                limits=ValidationWorkerLimits(
                    max_wall_time_seconds=validation_timeout_seconds,
                    max_processes=2,
                    max_memory_bytes=256 * 1024 * 1024,
                    max_output_bytes=20_000,
                    allowed_artifact_kinds=["PYTHON"],
                    allowed_executables=[str(Path(sys.executable).resolve())],
                ),
                authorized_by="RLMGraph built-in policy",
                authorization_reason="Syntax-only Python validation within one approved path.",
            ),
        ]
        self.validation_workers = {item.id: item for item in workers}
        self.validation_runner = validation_runner or BoundedValidationRunner()
        self.max_external_report_bytes = max_external_report_bytes

    def recover_incomplete_promotions(
        self, project_root: str | Path | None = None
    ) -> list[ImplementationSandboxAttempt]:
        """Recover every durable, non-terminal sandbox mutation journal.

        This is safe to call repeatedly: terminal journals are skipped and recovery
        classifies exact on-disk bytes before deciding whether to finish or roll back.
        """
        wanted = str(Path(project_root).resolve()).casefold() if project_root else None
        recovered = []
        for candidate in self.store.implementation_sandboxes():
            journal = candidate.promotion.mutation_journal if candidate.promotion else None
            if journal is None or journal.terminal:
                continue
            if wanted is not None and str(Path(candidate.project_root).resolve()).casefold() != wanted:
                continue
            recovered.append(self.recover_promotion(candidate.ticket_id, candidate.id))
        return recovered

    def recover_promotion(
        self, ticket_id: str, attempt_id: str
    ) -> ImplementationSandboxAttempt:
        attempt = self._attempt(ticket_id, attempt_id)
        promotion = attempt.promotion
        journal = promotion.mutation_journal if promotion else None
        if promotion is None or journal is None:
            raise ValueError("Sandbox promotion has no durable mutation journal.")
        if journal.terminal:
            return attempt
        root = Path(journal.project_root).resolve(strict=True)
        if str(root).casefold() != str(Path(attempt.project_root).resolve()).casefold():
            raise ReadOnlyViolation("Mutation journal project boundary does not match its sandbox attempt.")
        holder = f"sandbox-recovery:{attempt.id}"
        prior_lease = next(
            (
                item for item in self.store.project_leases()
                if str(Path(item.project_root).resolve()).casefold() == str(root).casefold()
            ),
            None,
        )
        prior_fence_matches = bool(
            prior_lease
            and prior_lease.id == journal.lease_id
            and prior_lease.fencing_token == journal.fencing_token
        )
        if not prior_fence_matches:
            raise RuntimeError("Mutation recovery rejected a stale fencing token or lease identity.")
        acquisition = self.store.acquire_project_lease(
            str(root), holder, attempt.id, recovery_journal_id=journal.id
        )
        if not acquisition.acquired:
            raise RuntimeError("Incomplete promotion recovery is waiting for its active mutation lease to expire.")
        lease = acquisition.lease
        if lease.fencing_token != journal.fencing_token:
            if not acquisition.reclaimed and prior_lease.status.value != "RELEASED":
                self.store.release_project_lease(str(root), holder, lease.fencing_token)
                raise RuntimeError("Mutation recovery rejected a stale fencing token.")
            journal.evidence.append(Evidence(
                path=journal.project_root,
                detail=f"Expired fence {journal.fencing_token} reclaimed as fence {lease.fencing_token}.",
            ))
            journal.fencing_token = lease.fencing_token
            journal.lease_id = lease.id
            journal.lease_holder_id = holder
        journal.recovery_count += 1
        interrupted_stage = journal.stage
        self.store.record_project_lease_event(
            str(root),
            holder,
            lease.fencing_token,
            ProjectLeaseEventKind.RECOVERY_STARTED,
            f"Recovering sandbox mutation journal {journal.id}.",
            workflow_id=attempt.id,
        )
        self._journal_checkpoint(attempt, "RECOVERY_STARTED", "Classifying exact project bytes under the recovery fence.")
        started = perf_counter()
        try:
            paths = self._journal_paths(root, attempt, journal)
            states = self._journal_states(paths, journal)
            if "UNKNOWN" in states:
                raise ReadOnlyViolation("Recovery found unverifiable source bytes; no additional source writes were made.")
            all_after = all(state == "AFTER" for state in states)
            provably_applied = all_after and interrupted_stage in {
                "APPLIED", "VALIDATING", "VALIDATED", "COMMITTING"
            }
            if provably_applied:
                self._finish_recovered_application(attempt, root, started)
            else:
                self._rollback_from_journal(attempt, root, paths)
        except Exception as exc:  # noqa: BLE001 - persist recovery failure for human action
            journal.failure_reason = str(exc)
            journal.stage = "RECOVERY_FAILED"
            journal.rollback_state = "FAILED" if journal.rollback_state == "IN_PROGRESS" else journal.rollback_state
            promotion.failure_reason = str(exc)
            promotion.status = "RECOVERY_FAILED"
            attempt.status = "RECOVERY_FAILED"
            self._journal_checkpoint(attempt, "RECOVERY_FAILED", str(exc))
        finally:
            journal.updated_at = datetime.now(UTC)
            self.store.save_implementation_sandbox(attempt)
            self._record_recovery_ticket_event(attempt)
            self.store.record_project_lease_event(
                str(root),
                holder,
                lease.fencing_token,
                ProjectLeaseEventKind.RECOVERY_COMPLETED,
                f"Sandbox mutation recovery ended in {attempt.status}.",
                workflow_id=attempt.id,
            )
            self.store.release_project_lease(str(root), holder, lease.fencing_token)
            self._promotion_checkpoint(attempt, "RECOVERY_LEASE_RELEASED", "Recovery mutation lease released.")
            ticket = TicketManager(self.store).check_budget(ticket_id)
            ticket.usage.wall_time_seconds += perf_counter() - started
            ticket.updated_at = datetime.now(UTC)
            self.store.save_project_ticket(ticket)
        return attempt

    def run(self, ticket_id: str, plan_record_id: str) -> ImplementationSandboxAttempt:
        tickets = TicketManager(self.store)
        ticket = tickets.check_budget(ticket_id)
        plan = next(
            (
                item
                for item in self.store.project_workspace_records()
                if item.id == plan_record_id and item.ticket_id == ticket.id
            ),
            None,
        )
        if not plan or plan.kind != "CHANGE_PLAN":
            raise ValueError("Sandbox implementation requires a ticket-attached change plan.")
        if plan.project_id != ticket.project_id or ProjectGovernance.canonical_root(plan.project_root) != ProjectGovernance.canonical_root(ticket.project_root):
            raise ReadOnlyViolation("Approved plan project identity does not match its ticket boundary.")
        if plan.approval_status != "APPROVED":
            raise ValueError("Sandbox implementation requires explicit plan approval.")
        governance = ProjectGovernance(self.store)
        policy = governance.policy(ticket.project_id)
        plan_binding, _, _ = governance.plan_binding(policy, plan)
        approved, missing, expired = governance.evaluate(
            policy,
            action="PLAN",
            artifact_kinds=governance.artifact_kinds(plan.affected_paths),
            binding_sha256=plan_binding,
            history=plan.approval_history,
        )
        plan.approval_missing = missing
        plan.approval_expiration_reasons = expired
        if not approved:
            plan.approval_status = "EXPIRED" if expired else "PENDING"
            self.store.save_project_workspace_record(plan)
            raise ValueError(
                "Sandbox implementation requires current plan approvals: "
                + "; ".join([*missing, *expired])
            )
        project = next((item for item in self.store.projects() if item.id == ticket.project_id), None)
        if not project or not project.read_only or not project.explicitly_selected:
            raise ReadOnlyViolation("The ticket project is not an explicitly registered source.")
        root = Path(project.root).resolve(strict=True)
        authorized = sorted(dict.fromkeys(path.replace("\\", "/") for path in plan.affected_paths))
        if not authorized:
            raise ValueError("The approved plan has no authorized implementation paths.")
        sources = self._authorized_sources(root, authorized)
        initial_manifest = self._current_manifest(project.id, root)
        if initial_manifest != plan.final_manifest_sha256:
            plan.approval_status = "EXPIRED"
            plan.approval_expiration_reasons = list(dict.fromkeys([
                *plan.approval_expiration_reasons,
                "Registered source manifest changed after plan approval.",
            ]))
            self.store.save_project_workspace_record(plan)
            raise ReadOnlyViolation("The registered source changed after planning; create a new plan.")
        attempt = ImplementationSandboxAttempt(
            ticket_id=ticket.id,
            plan_record_id=plan.id,
            project_id=project.id,
            project_root=str(root),
            authorized_paths=authorized,
            worker=type(self.worker).__name__,
            worker_configuration=(
                self.worker.evidence_configuration()
                if hasattr(self.worker, "evidence_configuration") else {}
            ),
            process_policy={
                "worker_root": "disposable authorized-file mirror",
                "registered_project_worker_access": False,
                "allowed_files": authorized,
                "subprocess_timeout_seconds": 900,
                "generated_files_allowed": False,
            },
            network_policy={
                "provider_transport": "Required for the Codex model call.",
                "model_generated_tool_network": (
                    "No tool call is requested by the surgical worker; OS-level network denial "
                    "is not established by this record."
                ),
                "validation_network": (
                    "Built-in validation commands are local, but OS-level network denial is not "
                    "established by the validation runner."
                ),
                "repository_credentials_supplied": False,
            },
            initial_manifest_sha256=initial_manifest,
            final_manifest_sha256=initial_manifest,
        )
        self._checkpoint(attempt, "CREATED", "Disposable authorized-file mirror allocated.")
        started = perf_counter()
        try:
            remaining = ticket.budget.max_wall_time_seconds - ticket.usage.wall_time_seconds
            if remaining <= 0:
                raise RuntimeError("Ticket wall-time budget is exhausted.")
            with TemporaryDirectory(prefix="rlmgraph-implementation-") as directory:
                mirror = Path(directory) / "project"
                mirror.mkdir()
                baseline: dict[str, bytes] = {}
                for relative, source in sources.items():
                    destination = mirror / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    baseline[relative] = destination.read_bytes()
                self._checkpoint(
                    attempt,
                    "ISOLATED",
                    f"Mirror contains exactly {len(baseline)} authorized files.",
                )
                attempt.worker_calls = 1
                result = self.worker.implement(plan.prompt, plan.evidence, mirror)
                attempt.model_calls = result.model_calls
                reported_reads = sorted(dict.fromkeys(
                    path.replace("\\", "/") for path in result.files_read
                ))
                unsafe_reads = sorted(set(reported_reads) - set(authorized))
                if unsafe_reads:
                    raise ReadOnlyViolation(
                        "Sandbox worker reported reads outside authorized paths: "
                        + ", ".join(unsafe_reads)
                    )
                attempt.files_read = reported_reads
                actual = self._changed_paths(mirror, baseline)
                reported = sorted(path.replace("\\", "/") for path in result.files_changed)
                if actual != reported:
                    raise ReadOnlyViolation(
                        f"Worker change report does not match sandbox diff: reported {reported}, actual {actual}"
                    )
                outside = sorted(set(actual) - set(authorized))
                if outside:
                    raise ReadOnlyViolation(
                        "Sandbox worker changed unauthorized paths: " + ", ".join(outside)
                    )
                attempt.changes = [self._patch(relative, baseline[relative], mirror / relative) for relative in actual]
                for change in attempt.changes:
                    change.change_reason = result.file_change_reasons.get(change.path) or None
                attempt.patch_sha256 = self._patch_sha256(attempt)
                self._checkpoint(
                    attempt,
                    "PATCH_CAPTURED",
                    f"Captured {len(attempt.changes)} authorized reviewable diffs.",
                )
                commands = self._validation_commands(plan.validation_commands, project.id, authorized)
                attempt.validation_decisions = self._validation_decisions(
                    project.id, [item.path for item in attempt.changes], commands
                )
                attempt.validation_evidence = [
                    evidence
                    for decision in attempt.validation_decisions
                    for evidence in decision.evidence
                ]
                self._checkpoint(
                    attempt,
                    "VALIDATION_ROUTED",
                    f"Recorded {len(attempt.validation_decisions)} artifact-aware validation decisions.",
                )
                for decision in [
                    item for item in attempt.validation_decisions if item.status == "PENDING"
                ]:
                    if ticket.usage.worker_calls + attempt.worker_calls >= ticket.budget.max_worker_calls:
                        decision.status = "REQUIRED"
                        decision.evidence.append(
                            Evidence(
                                path=decision.path,
                                detail="Configured validation worker was not run because the ticket worker-call budget has no remaining slot.",
                            )
                        )
                        continue
                    validation_remaining = remaining - (perf_counter() - started)
                    if validation_remaining <= 0:
                        raise RuntimeError("Ticket wall-time budget was exhausted before validation completed.")
                    spec = self.validation_workers.get("BUILTIN-PYTHON-PYTEST")
                    if spec is None or not spec.enabled:
                        decision.status = "REQUIRED"
                        continue
                    before_validation = {
                        item.relative_to(mirror).as_posix(): item.read_bytes()
                        for item in mirror.rglob("*") if item.is_file()
                    }
                    execution = self._execute_worker(
                        ticket.id, attempt, decision, spec, mirror, self._patch_sha256(attempt)
                    )
                    after_validation = {
                        item.relative_to(mirror).as_posix(): item.read_bytes()
                        for item in mirror.rglob("*") if item.is_file()
                    }
                    if after_validation != before_validation:
                        execution.status = "REJECTED"
                        execution.failure_reason = (
                            "Validation worker modified its read-only validation slice."
                        )
                        execution.exit_code = 125
                    attempt.validation_worker_executions.append(execution)
                    attempt.worker_calls += 1
                    attempt.validations.append(
                        TestExecution(
                            command=execution.command,
                            exit_code=execution.exit_code if execution.exit_code is not None else 125,
                            stdout=execution.stdout,
                            stderr=execution.stderr,
                            duration_ms=execution.duration_ms,
                        )
                    )
                    execution_index = len(attempt.validations) - 1
                    decision.execution_index = execution_index
                    decision.worker_execution_id = execution.id
                    decision.status = "PASSED" if execution.status == "PASSED" else "FAILED"
                    decision.evidence.extend(execution.evidence)
                attempt.validation_evidence = [
                    evidence
                    for decision in attempt.validation_decisions
                    for evidence in decision.evidence
                ]
                if any(item.status == "FAILED" for item in attempt.validation_decisions):
                    attempt.status = "FAILED"
                    attempt.failure_reason = "One or more bounded non-Unreal validations failed."
                elif not attempt.changes:
                    attempt.status = "FAILED"
                    attempt.failure_reason = "Implementation worker produced no reviewable diff."
                else:
                    attempt.status = "READY_FOR_REVIEW"
                self._checkpoint(
                    attempt,
                    "VALIDATED",
                    f"Completed {len(attempt.validations)} bounded validation commands; manual requirements remain review gates.",
                )
        except Exception as exc:  # noqa: BLE001 - persist failed sandbox boundary
            attempt.status = "FAILED"
            attempt.failure_reason = str(exc)
            self._checkpoint(attempt, "FAILED", str(exc))
        finally:
            attempt.filesystem_disposed = True
            attempt.elapsed_seconds = perf_counter() - started
            attempt.final_manifest_sha256 = self._current_manifest(project.id, root)
            attempt.original_unchanged = attempt.final_manifest_sha256 == initial_manifest
            if not attempt.original_unchanged:
                attempt.status = "FAILED"
                attempt.failure_reason = "Registered project source changed during sandbox execution."
            attempt.completed_at = datetime.now(UTC)
            self._checkpoint(attempt, "DISPOSED", "Disposable filesystem mirror removed.")
            tickets.attach_sandbox_attempt(ticket.id, attempt)
        return attempt

    def discard(self, ticket_id: str, attempt_id: str) -> ImplementationSandboxAttempt:
        attempt = next(
            (
                item
                for item in self.store.implementation_sandboxes(ticket_id)
                if item.id == attempt_id
            ),
            None,
        )
        if not attempt:
            raise ValueError(f"Sandbox attempt not found: {attempt_id}")
        attempt.status = "DISCARDED"
        attempt.filesystem_disposed = True
        attempt.discarded_at = datetime.now(UTC)
        attempt.execution_authorized = False
        self._checkpoint(attempt, "DISCARDED", "Reviewable proposal discarded; source unchanged.")
        self.store.save_implementation_sandbox(attempt)
        return attempt

    def satisfy_validation(
        self,
        ticket_id: str,
        attempt_id: str,
        decision_id: str,
        *,
        actor: str,
        detail: str,
        governance_decision: str = "APPROVED",
    ) -> ImplementationSandboxAttempt:
        attempt = self._attempt(ticket_id, attempt_id)
        if attempt.status != "READY_FOR_REVIEW" or attempt.promotion is not None:
            raise ValueError("Only an unpromoted reviewable sandbox can receive validation evidence.")
        if not actor.strip() or not detail.strip():
            raise ValueError("A human identity and validation evidence detail are required.")
        decision = next(
            (item for item in attempt.validation_decisions if item.id == decision_id), None
        )
        if decision is None:
            raise ValueError(f"Sandbox validation decision not found: {decision_id}")
        if decision.status not in {"REQUIRED", "SATISFIED"}:
            raise ValueError("Only manual validation requirements can be attested.")
        if decision.category != "REVIEW":
            raise ValueError(
                "Executable and Editor validation requires a configured worker or integrity-checked external report."
            )
        governance = ProjectGovernance(self.store)
        policy = governance.policy(attempt.project_id)
        patch_sha = self._patch_sha256(attempt)
        binding = governance.binding(
            project_id=attempt.project_id,
            project_root=governance.canonical_root(attempt.project_root),
            artifact_id=decision.id,
            source_manifest_sha256=attempt.initial_manifest_sha256,
            patch_sha256=patch_sha,
            requirement={
                "path": decision.path, "artifact_kind": decision.artifact_kind,
                "category": decision.category, "requirement": decision.requirement,
            },
            policy_id=policy.id,
            policy_version=policy.version,
        )
        records = governance.record_decisions(
            policy,
            action="ATTESTATION",
            artifact_id=decision.id,
            artifact_kinds=[decision.artifact_kind],
            decision="DENIED" if governance_decision.upper() in {"DENIED", "REJECTED"} else "APPROVED",
            actor=actor,
            reason=detail,
            binding_sha256=binding,
            source_manifest_sha256=attempt.initial_manifest_sha256,
            patch_sha256=patch_sha,
            requirements_sha256=governance.binding(requirement=decision.requirement),
        )
        decision.attestation_history.extend(records)
        satisfied, missing, _ = governance.evaluate(
            policy,
            action="ATTESTATION",
            artifact_kinds=[decision.artifact_kind],
            binding_sha256=binding,
            history=decision.attestation_history,
        )
        decision.attestation_missing = missing
        if satisfied:
            evidence = Evidence(path=decision.path, detail=detail.strip())
            decision.status = "SATISFIED"
            decision.satisfied_by = ", ".join(sorted({
                item.actor for item in decision.attestation_history
                if item.decision == "APPROVED" and item.binding_sha256 == binding
            }))
            decision.satisfied_at = datetime.now(UTC)
            decision.evidence.append(evidence)
            attempt.validation_evidence.append(evidence)
        self._checkpoint(
            attempt,
            "VALIDATION_SATISFIED",
            f"{decision.category} attestation recorded by {actor.strip()} under policy "
            f"{policy.id} v{policy.version}; {'satisfied' if satisfied else 'additional reviewers required'}.",
        )
        return attempt

    def configured_workers(self) -> list[ValidationWorkerSpec]:
        return list(self.validation_workers.values())

    def run_validation_worker(
        self, ticket_id: str, attempt_id: str, decision_id: str, worker_id: str
    ) -> ImplementationSandboxAttempt:
        tickets = TicketManager(self.store)
        attempt = self._attempt(ticket_id, attempt_id)
        if attempt.promotion is not None or attempt.status not in {"READY_FOR_REVIEW", "FAILED"}:
            raise ValueError("Validation workers require an unpromoted reviewable sandbox attempt.")
        decision = self._validation_decision(attempt, decision_id)
        spec = self.validation_workers.get(worker_id)
        if spec is None or not spec.enabled:
            raise ValueError("The requested validation worker is unavailable or disabled.")
        policy = ProjectGovernance(self.store).policy(attempt.project_id)
        ProjectGovernance.assert_worker(policy, spec.id)
        patch_sha = self._patch_sha256(attempt)
        duplicate = next(
            (
                item for item in attempt.validation_worker_executions
                if item.decision_id == decision.id
                and item.worker_id == spec.id
                and item.patch_sha256 == patch_sha
                and item.status in {"PASSED", "FAILED", "REJECTED", "LIMIT_EXCEEDED"}
            ),
            None,
        )
        if duplicate:
            return attempt
        ticket = tickets.check_budget(ticket_id)
        project = next((item for item in self.store.projects() if item.id == attempt.project_id), None)
        if project is None:
            raise ValueError("Sandbox project record no longer exists.")
        root = Path(project.root).resolve(strict=True)
        if self._current_manifest(project.id, root) != attempt.initial_manifest_sha256:
            raise ReadOnlyViolation("Registered source changed; validation worker evidence would be stale.")
        started = perf_counter()
        with TemporaryDirectory(prefix="rlmgraph-validation-") as directory:
            mirror = Path(directory) / "project"
            baseline = self._build_validation_mirror(root, mirror, attempt)
            execution = self._execute_worker(
                ticket_id, attempt, decision, spec, mirror, patch_sha
            )
            current = {
                item.relative_to(mirror).as_posix(): item.read_bytes()
                for item in mirror.rglob("*") if item.is_file()
            }
            if current != baseline:
                execution.status = "REJECTED"
                execution.failure_reason = "Validation worker modified its read-only validation slice."
                execution.exit_code = execution.exit_code if execution.exit_code not in {None, 0} else 125
        attempt.validation_worker_executions.append(execution)
        decision.worker_execution_id = execution.id
        decision.execution_index = None
        decision.status = "PASSED" if execution.status == "PASSED" else "REQUIRED"
        decision.satisfied_by = spec.name if execution.status == "PASSED" else None
        decision.satisfied_at = datetime.now(UTC) if execution.status == "PASSED" else None
        decision.evidence.extend(execution.evidence)
        attempt.validation_evidence = [
            evidence for item in attempt.validation_decisions for evidence in item.evidence
        ]
        if attempt.changes and all(
            item.status in {"PASSED", "SATISFIED"} for item in attempt.validation_decisions
        ):
            attempt.status = "READY_FOR_REVIEW"
            attempt.failure_reason = None
        self._checkpoint(
            attempt,
            "VALIDATION_WORKER_COMPLETED",
            f"{spec.name} ended as {execution.status} for {decision.path}.",
        )
        ticket.usage.worker_calls += 1
        ticket.usage.wall_time_seconds += perf_counter() - started
        ticket.updated_at = datetime.now(UTC)
        self.store.save_project_ticket(ticket)
        self._ticket_validation_event(attempt, execution.id, execution.status, spec.name)
        return attempt

    def import_external_validation_report(
        self,
        ticket_id: str,
        attempt_id: str,
        decision_id: str,
        *,
        actor: str,
        report_kind: str,
        artifact_path: str,
        source_manifest_sha256: str,
        patch_sha256: str,
        report_bytes: bytes,
        report_sha256: str,
        status: str,
        detail: str,
    ) -> ImplementationSandboxAttempt:
        attempt = self._attempt(ticket_id, attempt_id)
        if attempt.promotion is not None or attempt.status != "READY_FOR_REVIEW":
            raise ValueError("External reports require an unpromoted reviewable sandbox attempt.")
        decision = self._validation_decision(attempt, decision_id)
        normalized_path = artifact_path.replace("\\", "/")
        actor, detail, status = actor.strip(), detail.strip(), status.upper()
        if not actor or not detail or status not in {"PASSED", "FAILED"}:
            raise ValueError("External validation report identity, detail, and valid status are required.")
        if not decision.requires_unreal_editor or report_kind != "UNREAL_EDITOR":
            raise ValueError("Only an Unreal Editor requirement accepts an external Editor report.")
        if normalized_path != decision.path or normalized_path not in attempt.authorized_paths:
            raise ReadOnlyViolation("External validation report is outside the authorized artifact scope.")
        if source_manifest_sha256 != attempt.initial_manifest_sha256:
            raise ReadOnlyViolation("External validation report source manifest is stale.")
        expected_patch = self._patch_sha256(attempt)
        if patch_sha256 != expected_patch:
            raise ReadOnlyViolation("External validation report patch identity is stale.")
        digest = hashlib.sha256(report_bytes).hexdigest()
        if len(report_bytes) > self.max_external_report_bytes:
            raise ValueError("External validation report exceeds the configured size limit.")
        if digest != report_sha256:
            raise ValueError("External validation report integrity hash does not match its bytes.")
        duplicate = next(
            (
                item for item in attempt.external_validation_reports
                if item.decision_id == decision.id and item.report_sha256 == digest
            ),
            None,
        )
        if duplicate:
            return attempt
        if decision.status != "REQUIRED":
            raise ValueError("External report can only satisfy an unmet validation requirement.")
        project = next(item for item in self.store.projects() if item.id == attempt.project_id)
        if self._current_manifest(project.id, Path(project.root).resolve(strict=True)) != source_manifest_sha256:
            raise ReadOnlyViolation("Registered source changed before external report import.")
        evidence = Evidence(path=decision.path, detail=detail)
        governance = ProjectGovernance(self.store)
        policy = governance.policy(attempt.project_id)
        attestation_binding = governance.binding(
            project_id=attempt.project_id,
            project_root=governance.canonical_root(attempt.project_root),
            artifact_id=decision.id,
            source_manifest_sha256=attempt.initial_manifest_sha256,
            patch_sha256=expected_patch,
            requirement={
                "path": decision.path, "artifact_kind": decision.artifact_kind,
                "category": decision.category, "requirement": decision.requirement,
            },
            policy_id=policy.id,
            policy_version=policy.version,
        )
        governance_records = governance.record_decisions(
            policy,
            action="ATTESTATION",
            artifact_id=decision.id,
            artifact_kinds=[decision.artifact_kind],
            decision="APPROVED" if status == "PASSED" else "DENIED",
            actor=actor,
            reason=detail,
            binding_sha256=attestation_binding,
            source_manifest_sha256=source_manifest_sha256,
            patch_sha256=patch_sha256,
            requirements_sha256=governance.binding(requirement=decision.requirement),
            evidence_sha256=digest,
        )
        report = SandboxExternalValidationReport(
            ticket_id=ticket_id,
            project_id=attempt.project_id,
            project_root=attempt.project_root,
            attempt_id=attempt.id,
            decision_id=decision.id,
            report_kind=report_kind,
            artifact_path=normalized_path,
            source_manifest_sha256=source_manifest_sha256,
            patch_sha256=patch_sha256,
            report_sha256=digest,
            report_bytes_base64=base64.b64encode(report_bytes).decode("ascii"),
            status=status,
            detail=detail,
            recorded_by=actor,
            policy_id=policy.id,
            policy_version=policy.version,
            rule_ids=[item.rule_id for item in governance_records],
            binding_sha256=attestation_binding,
            evidence=[evidence],
        )
        attempt.external_validation_reports.append(report)
        decision.attestation_history.extend(governance_records)
        attested, missing, _ = governance.evaluate(
            policy,
            action="ATTESTATION",
            artifact_kinds=[decision.artifact_kind],
            binding_sha256=attestation_binding,
            history=decision.attestation_history,
        )
        decision.attestation_missing = missing
        decision.external_report_id = report.id
        decision.status = "SATISFIED" if status == "PASSED" and attested else "REQUIRED"
        decision.satisfied_by = actor if status == "PASSED" and attested else None
        decision.satisfied_at = datetime.now(UTC) if status == "PASSED" and attested else None
        decision.evidence.append(evidence)
        attempt.validation_evidence.append(evidence)
        self._checkpoint(
            attempt,
            "EXTERNAL_VALIDATION_REPORT_IMPORTED",
            f"Integrity-checked {report_kind} report recorded as {status} for {decision.path}.",
        )
        self._ticket_validation_event(attempt, report.id, status, report_kind)
        return attempt

    def approve_promotion(
        self,
        ticket_id: str,
        attempt_id: str,
        *,
        actor: str,
        reason: str,
        decision: str = "APPROVED",
    ) -> ImplementationSandboxAttempt:
        attempt = self._attempt(ticket_id, attempt_id)
        policy = ProjectGovernance(self.store).policy(attempt.project_id)
        ProjectGovernance.assert_actor(policy.promotion_approvers, actor.strip(), "Promotion approval")
        if attempt.status != "READY_FOR_REVIEW" or attempt.promotion is not None:
            raise ValueError("Only an unpromoted reviewable sandbox can receive a promotion decision.")
        actor, reason, decision = actor.strip(), reason.strip(), decision.upper()
        if not actor or not reason:
            raise ValueError("A human identity and promotion decision reason are required.")
        if decision not in {"APPROVED", "REJECTED", "DENIED"}:
            raise ValueError("Promotion decision must be APPROVED or REJECTED.")
        incomplete = [
            item for item in attempt.validation_decisions if item.status not in {"PASSED", "SATISFIED"}
        ]
        if decision == "APPROVED" and incomplete:
            raise ValueError(
                "Promotion requires every validation decision to be satisfied: "
                + ", ".join(f"{item.path} ({item.status})" for item in incomplete)
            )
        artifact_kinds = sorted({item.artifact_kind for item in attempt.validation_decisions})
        if decision == "APPROVED":
            ProjectGovernance.assert_required_validations(
                policy, attempt.validation_decisions, artifact_kinds
            )
        project = next((item for item in self.store.projects() if item.id == attempt.project_id), None)
        if project is None:
            raise ValueError("Sandbox project record no longer exists.")
        root = Path(project.root).resolve(strict=True)
        current = self._current_manifest(project.id, root)
        if current != attempt.initial_manifest_sha256:
            raise ReadOnlyViolation("Registered source changed after sandbox validation; create a new attempt.")
        governance = ProjectGovernance(self.store)
        patch_sha = self._patch_sha256(attempt)
        binding, requirements_sha, evidence_sha = governance.attempt_binding(
            policy, attempt, patch_sha
        )
        records = governance.record_decisions(
            policy,
            action="PROMOTION",
            artifact_id=attempt.id,
            artifact_kinds=artifact_kinds,
            decision="DENIED" if decision in {"DENIED", "REJECTED"} else "APPROVED",
            actor=actor,
            reason=reason,
            binding_sha256=binding,
            source_manifest_sha256=current,
            patch_sha256=patch_sha,
            requirements_sha256=requirements_sha,
            evidence_sha256=evidence_sha,
        )
        attempt.promotion_approval_history.extend(records)
        approved, missing, expired = governance.evaluate(
            policy,
            action="PROMOTION",
            artifact_kinds=artifact_kinds,
            binding_sha256=binding,
            history=attempt.promotion_approval_history,
        )
        attempt.promotion_approval_missing = missing
        attempt.promotion_approval_expiration_reasons = expired
        if approved and decision == "APPROVED":
            attempt.promotion_approval = SandboxPromotionApproval(
                decision=decision,
                project_id=attempt.project_id,
                project_root=attempt.project_root,
                approved_by=", ".join(sorted({
                    item.actor for item in attempt.promotion_approval_history
                    if item.decision == "APPROVED" and item.binding_sha256 == binding
                })),
                reason=reason,
                source_manifest_sha256=current,
                policy_id=policy.id,
                policy_version=policy.version,
                rule_ids=sorted({
                    item.rule_id for item in attempt.promotion_approval_history
                    if item.decision == "APPROVED"
                    and item.binding_sha256 == binding
                    and item.policy_version == policy.version
                }),
                binding_sha256=binding,
                requirements_sha256=requirements_sha,
                evidence_sha256=evidence_sha,
            )
        else:
            attempt.promotion_approval = None
        if decision in {"REJECTED", "DENIED"}:
            attempt.status = "PROMOTION_REJECTED"
        self._checkpoint(
            attempt,
            "PROMOTION_" + decision,
            f"Promotion decision recorded by {actor} under policy {policy.id} v{policy.version}; "
            f"rules {', '.join(item.rule_id for item in records)}; "
            f"{'approval threshold met' if approved else 'additional reviewers required'}.",
        )
        return attempt

    def promote(self, ticket_id: str, attempt_id: str) -> ImplementationSandboxAttempt:
        tickets = TicketManager(self.store)
        ticket = tickets.check_budget(ticket_id)
        attempt = self._attempt(ticket_id, attempt_id)
        policy = ProjectGovernance(self.store).policy(attempt.project_id)
        artifact_kinds = sorted({item.artifact_kind for item in attempt.validation_decisions})
        ProjectGovernance.assert_required_validations(
            policy, attempt.validation_decisions, artifact_kinds
        )
        approval = attempt.promotion_approval
        if attempt.status != "READY_FOR_REVIEW" or approval is None or approval.decision != "APPROVED":
            raise ValueError("Sandbox promotion requires a separate explicit approval.")
        governed_project = ProjectGovernance(self.store).project(attempt.project_id)
        governed_root = Path(governed_project.root).resolve(strict=True)
        if self._current_manifest(governed_project.id, governed_root) != attempt.initial_manifest_sha256:
            attempt.promotion_approval_expiration_reasons = list(dict.fromkeys([
                *attempt.promotion_approval_expiration_reasons,
                "Registered source manifest changed after promotion approval.",
            ]))
            self.store.save_implementation_sandbox(attempt)
        patch_sha = self._patch_sha256(attempt)
        binding, _, _ = ProjectGovernance.attempt_binding(policy, attempt, patch_sha)
        approved, missing, expired = ProjectGovernance(self.store).evaluate(
            policy,
            action="PROMOTION",
            artifact_kinds=artifact_kinds,
            binding_sha256=binding,
            history=attempt.promotion_approval_history,
        )
        attempt.promotion_approval_missing = missing
        attempt.promotion_approval_expiration_reasons = expired
        if not approved or approval.binding_sha256 not in {None, binding}:
            attempt.promotion_approval = None
            self.store.save_implementation_sandbox(attempt)
            raise ValueError(
                "Sandbox promotion approval expired or is incomplete: "
                + "; ".join([*missing, *expired, "bound artifact changed"])
            )
        if approval.project_id not in {None, attempt.project_id} or (
            approval.project_root
            and ProjectGovernance.canonical_root(approval.project_root)
            != ProjectGovernance.canonical_root(attempt.project_root)
        ):
            raise ReadOnlyViolation("Promotion approval does not match the sandbox project boundary.")
        if attempt.promotion is not None:
            raise ValueError("Sandbox promotion has already been attempted.")
        if any(item.status not in {"PASSED", "SATISFIED"} for item in attempt.validation_decisions):
            raise ValueError("Sandbox promotion requires all validation gates to remain satisfied.")
        if not attempt.changes:
            raise ValueError("Sandbox promotion requires at least one reviewable change.")
        project = next((item for item in self.store.projects() if item.id == attempt.project_id), None)
        if project is None or not project.explicitly_selected or not project.read_only:
            raise ReadOnlyViolation("Promotion requires the explicitly registered project boundary.")
        root = Path(project.root).resolve(strict=True)
        holder = f"sandbox-promotion:{attempt.id}"
        acquisition = self.store.acquire_project_lease(str(root), holder, attempt.id)
        if not acquisition.acquired:
            raise RuntimeError("Registered project mutation lease is held by another workflow.")
        lease = acquisition.lease
        promotion = SandboxPromotionRecord(
            approval_id=approval.id,
            project_id=attempt.project_id,
            project_root=attempt.project_root,
            initial_manifest_sha256=attempt.initial_manifest_sha256,
            lease_id=lease.id,
            fencing_token=lease.fencing_token,
        )
        attempt.promotion = promotion
        self._promotion_checkpoint(attempt, "LEASE_ACQUIRED", "Exclusive project mutation lease acquired.")
        started = perf_counter()
        originals: dict[Path, bytes] = {}
        modes: dict[Path, int] = {}
        applied = False
        try:
            current = self._current_manifest(project.id, root)
            if current != approval.source_manifest_sha256 or current != attempt.initial_manifest_sha256:
                raise ReadOnlyViolation("Registered source changed after promotion approval; approval is stale.")
            paths = self._promotion_paths(root, attempt)
            for change, target in zip(attempt.changes, paths, strict=True):
                if file_content_hash(target) != change.before_hash:
                    raise ReadOnlyViolation(f"Source precondition failed for {change.path}.")
                originals[target] = target.read_bytes()
                modes[target] = stat.S_IMODE(target.stat().st_mode)
            commands = self._promotion_commands(attempt)
            promotion.mutation_journal = SandboxMutationJournal(
                ticket_id=ticket.id,
                attempt_id=attempt.id,
                promotion_id=promotion.id,
                approval_id=approval.id,
                project_id=project.id,
                project_root=str(root),
                authorized_paths=list(attempt.authorized_paths),
                initial_manifest_sha256=attempt.initial_manifest_sha256,
                approved_manifest_sha256=approval.source_manifest_sha256,
                lease_id=lease.id,
                lease_holder_id=holder,
                fencing_token=lease.fencing_token,
                validation_commands=commands,
                entries=[
                    SandboxMutationJournalEntry(
                        path=change.path,
                        before_sha256=change.before_hash,
                        after_sha256=change.after_hash,
                        before_bytes_base64=base64.b64encode(originals[target]).decode("ascii"),
                        after_bytes_base64=base64.b64encode(self._change_bytes(change, True)).decode("ascii"),
                        original_mode=modes[target],
                    )
                    for change, target in zip(attempt.changes, paths, strict=True)
                ],
            )
            self._journal_checkpoint(
                attempt,
                "PREPARED",
                "Durable exact-byte mutation journal persisted before project-file replacement.",
            )
            self._inject_fault("PREPARED")
            self._promotion_checkpoint(
                attempt, "PRECONDITIONS_VERIFIED", "Manifest, changed paths, and source hashes verified."
            )
            promotion.status = "APPLYING"
            applied = True
            promotion.mutation_journal.stage = "APPLYING"
            custom_replacer = (
                type(self) is not ImplementationSandboxManager
                and "_replace_bytes" in type(self).__dict__
            )
            if custom_replacer:
                for entry in promotion.mutation_journal.entries:
                    entry.staged = True
                    entry.replacement_started = True
                self._journal_checkpoint(attempt, "REPLACEMENT_STARTED", "Approved replacements started.")
                self._replace_bytes(paths, attempt.changes, modes)
            else:
                for index, (change, target) in enumerate(zip(attempt.changes, paths, strict=True)):
                    entry = promotion.mutation_journal.entries[index]
                    entry.staged = True
                    entry.replacement_started = True
                    self._journal_checkpoint(attempt, "REPLACEMENT_STARTED", f"Replacement started for {entry.path}.")
                    self._inject_fault("REPLACEMENT_STARTED")
                    self._replace_single(target, self._change_bytes(change, True), modes[target], ".rlmgraph-promote-")
                    entry.replacement_completed = True
                    self._journal_checkpoint(attempt, "REPLACEMENT_COMPLETED", f"Replacement completed for {entry.path}.")
                    self._inject_fault("REPLACEMENT_COMPLETED")
            for change, target, entry in zip(
                attempt.changes, paths, promotion.mutation_journal.entries, strict=True
            ):
                if file_content_hash(target) != change.after_hash:
                    raise OSError(f"Applied content hash mismatch for {change.path}.")
                if not entry.replacement_completed:
                    entry.replacement_completed = True
                    self._journal_checkpoint(attempt, "REPLACEMENT_COMPLETED", f"Replacement completed for {entry.path}.")
            promotion.applied_manifest_sha256 = self._current_manifest(project.id, root)
            promotion.status = "APPLIED"
            promotion.mutation_journal.stage = "APPLIED"
            promotion.mutation_journal.proposed_manifest_sha256 = promotion.applied_manifest_sha256
            self._promotion_checkpoint(attempt, "APPLIED", "Exact approved bytes atomically replaced authorized files.")
            self._inject_fault("APPLIED")
            remaining = ticket.budget.max_wall_time_seconds - ticket.usage.wall_time_seconds
            promotion.mutation_journal.stage = "VALIDATING"
            promotion.mutation_journal.validation_state = "IN_PROGRESS"
            self._journal_checkpoint(attempt, "VALIDATING", "Bounded post-application validation started.")
            for command in commands:
                available = remaining - (perf_counter() - started)
                if available <= 0:
                    raise RuntimeError("Ticket wall-time budget exhausted during post-application validation.")
                promotion.validations.append(
                    self._execute(command, root, min(self.validation_timeout_seconds, available))
                )
                self._journal_checkpoint(
                    attempt,
                    "VALIDATION_RECORDED",
                    f"Persisted bounded validation result {len(promotion.validations)} of {len(commands)}.",
                )
                self._inject_fault("VALIDATION_RECORDED")
            stable = self._current_manifest(project.id, root) == promotion.applied_manifest_sha256
            if any(item.exit_code != 0 for item in promotion.validations) or not stable:
                reasons = []
                if any(item.exit_code != 0 for item in promotion.validations):
                    reasons.append("bounded post-application validation failed")
                if not stable:
                    reasons.append("post-application validation changed indexed source")
                raise RuntimeError("; ".join(reasons))
            promotion.status = "PROMOTED"
            promotion.final_manifest_sha256 = promotion.applied_manifest_sha256
            promotion.completed_at = datetime.now(UTC)
            promotion.evidence.extend(
                Evidence(
                    path=";".join(change.path for change in attempt.changes),
                    detail=f"Bounded post-application validation exited {item.exit_code} in {item.duration_ms:.1f}ms.",
                )
                for item in promotion.validations
            )
            attempt.status = "PROMOTED"
            promotion.mutation_journal.stage = "PROMOTED"
            promotion.mutation_journal.validation_state = "PASSED"
            promotion.mutation_journal.final_manifest_sha256 = promotion.final_manifest_sha256
            promotion.mutation_journal.recovery_required = False
            promotion.mutation_journal.terminal = True
            promotion.mutation_journal.completed_at = datetime.now(UTC)
            self._journal_checkpoint(attempt, "PROMOTED", "Journal reached verified promoted terminal state.")
            self._promotion_checkpoint(attempt, "PROMOTED", "Promotion completed; graph reconciliation remains pending.")
        except Exception as exc:  # noqa: BLE001 - persist and roll back the approved mutation boundary
            promotion.failure_reason = str(exc)
            if applied:
                if promotion.mutation_journal:
                    promotion.mutation_journal.rollback_state = "IN_PROGRESS"
                    promotion.mutation_journal.stage = "ROLLING_BACK"
                    self._journal_checkpoint(attempt, "ROLLING_BACK", "Restoring exact original bytes after failure.")
                rollback_error = None
                try:
                    self._restore_bytes(originals, modes)
                except OSError as rollback_exc:
                    rollback_error = rollback_exc
                promotion.rollback_verified = rollback_error is None and all(
                    target.read_bytes() == content for target, content in originals.items()
                ) and self._current_manifest(project.id, root) == attempt.initial_manifest_sha256
                if rollback_error is not None:
                    promotion.failure_reason = (
                        f"{promotion.failure_reason}; rollback failed: {rollback_error}"
                    )
                if promotion.rollback_verified:
                    if promotion.mutation_journal:
                        for entry in promotion.mutation_journal.entries:
                            entry.rollback_completed = True
                        promotion.mutation_journal.rollback_state = "VERIFIED"
                    for command in self._promotion_commands(attempt):
                        promotion.rollback_validations.append(
                            self._execute(command, root, min(self.validation_timeout_seconds, 30))
                        )
            else:
                promotion.rollback_verified = True
            promotion.final_manifest_sha256 = self._current_manifest(project.id, root)
            promotion.status = (
                "ROLLED_BACK"
                if applied and promotion.rollback_verified
                else "PRECONDITION_FAILED"
                if not applied
                else "ROLLBACK_FAILED"
            )
            promotion.completed_at = datetime.now(UTC)
            attempt.status = promotion.status
            if promotion.mutation_journal:
                promotion.mutation_journal.stage = promotion.status
                promotion.mutation_journal.final_manifest_sha256 = promotion.final_manifest_sha256
                promotion.mutation_journal.rollback_state = (
                    "VERIFIED" if promotion.rollback_verified else "FAILED"
                )
                promotion.mutation_journal.recovery_required = not bool(promotion.rollback_verified)
                promotion.mutation_journal.terminal = bool(promotion.rollback_verified)
                promotion.mutation_journal.failure_reason = promotion.failure_reason
                if promotion.mutation_journal.terminal:
                    promotion.mutation_journal.completed_at = datetime.now(UTC)
            self._promotion_checkpoint(
                attempt,
                promotion.status,
                "Exact original bytes restored after promotion failure."
                if applied and promotion.rollback_verified
                else "Promotion rejected before source writes."
                if not applied
                else "Automatic rollback could not prove exact source restoration.",
            )
        finally:
            promotion.evidence.append(
                Evidence(
                    path=attempt.changes[0].path,
                    detail=f"Promotion result: {promotion.status}.",
                )
            )
            self.store.save_implementation_sandbox(attempt)
            self.store.release_project_lease(str(root), holder, lease.fencing_token)
            self._promotion_checkpoint(attempt, "LEASE_RELEASED", "Exclusive mutation lease released.")
            elapsed = perf_counter() - started
            ticket.usage.wall_time_seconds += elapsed
            ticket.updated_at = datetime.now(UTC)
            self.store.save_project_ticket(ticket)
        return attempt

    def _attempt(self, ticket_id: str, attempt_id: str) -> ImplementationSandboxAttempt:
        attempt = next(
            (item for item in self.store.implementation_sandboxes(ticket_id) if item.id == attempt_id),
            None,
        )
        if attempt is None:
            raise ValueError(f"Sandbox attempt not found: {attempt_id}")
        ticket = TicketManager(self.store).get(ticket_id)
        project = ProjectGovernance(self.store).project(ticket.project_id)
        if attempt.ticket_id != ticket.id or attempt.project_id != ticket.project_id:
            raise ReadOnlyViolation("Sandbox attempt does not match its ticket project identity.")
        if ProjectGovernance.canonical_root(attempt.project_root) != ProjectGovernance.canonical_root(project.root):
            raise ReadOnlyViolation("Sandbox attempt project root does not match its registered project.")
        return attempt

    def _promotion_paths(self, root: Path, attempt: ImplementationSandboxAttempt) -> list[Path]:
        authorized = set(attempt.authorized_paths)
        paths = []
        for change in attempt.changes:
            if change.path not in authorized:
                raise ReadOnlyViolation(f"Patch path is not authorized: {change.path}")
            relative = Path(change.path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ReadOnlyViolation(f"Patch path escapes the registered project: {change.path}")
            target = (root / relative).resolve(strict=True)
            target.relative_to(root)
            if not target.is_file() or target.is_symlink():
                raise ReadOnlyViolation(f"Patch target is not a regular source file: {change.path}")
            paths.append(target)
        return paths

    @staticmethod
    def _promotion_commands(attempt: ImplementationSandboxAttempt) -> list[list[str]]:
        commands = []
        authorized = set(attempt.authorized_paths)
        for execution in attempt.validations:
            command = execution.command
            if (
                len(command) < 4
                or command[0] != sys.executable
                or command[1:3] != ["-m", "pytest"]
            ):
                raise ReadOnlyViolation(
                    "Persisted validation command is not a bounded Python test."
                )
            paths = [item.replace("\\", "/") for item in command[3:] if item.endswith(".py")]
            if not paths or any(path not in authorized for path in paths):
                raise ReadOnlyViolation(
                    "Persisted validation command escapes the approved path slice."
                )
            commands.append(command)
        return commands

    @staticmethod
    def _change_bytes(change: PatchChange, after: bool) -> bytes:
        encoded = change.after_bytes_base64 if after else change.before_bytes_base64
        if encoded is not None:
            return base64.b64decode(encoded, validate=True)
        content = change.after_content if after else change.before_content
        if content is None:
            raise ValueError("Promotion patch does not contain exact recoverable bytes.")
        return content.encode("utf-8")

    def _journal_paths(
        self, root: Path, attempt: ImplementationSandboxAttempt, journal: SandboxMutationJournal
    ) -> list[Path]:
        if journal.ticket_id != attempt.ticket_id or journal.attempt_id != attempt.id:
            raise ReadOnlyViolation("Mutation journal origin does not match its sandbox attempt.")
        if journal.approval_id != attempt.promotion_approval.id:
            raise ReadOnlyViolation("Mutation journal approval does not match the approved promotion.")
        if journal.authorized_paths != attempt.authorized_paths:
            raise ReadOnlyViolation("Mutation journal authorized paths changed after approval.")
        if not journal.entries or [item.path for item in journal.entries] != [
            item.path for item in attempt.changes
        ]:
            raise ReadOnlyViolation("Mutation journal is incomplete for the approved changed paths.")
        paths = self._promotion_paths(root, attempt)
        for entry, change in zip(journal.entries, attempt.changes, strict=True):
            before = base64.b64decode(entry.before_bytes_base64, validate=True)
            after = base64.b64decode(entry.after_bytes_base64, validate=True)
            if hashlib.sha256(before).hexdigest() != entry.before_sha256 or entry.before_sha256 != change.before_hash:
                raise ReadOnlyViolation(f"Mutation journal original bytes are unverifiable for {entry.path}.")
            if hashlib.sha256(after).hexdigest() != entry.after_sha256 or entry.after_sha256 != change.after_hash:
                raise ReadOnlyViolation(f"Mutation journal proposed bytes are unverifiable for {entry.path}.")
        return paths

    @staticmethod
    def _journal_states(paths: list[Path], journal: SandboxMutationJournal) -> list[str]:
        states = []
        for path, entry in zip(paths, journal.entries, strict=True):
            digest = file_content_hash(path)
            states.append(
                "BEFORE" if digest == entry.before_sha256 else "AFTER" if digest == entry.after_sha256 else "UNKNOWN"
            )
        return states

    def _finish_recovered_application(
        self, attempt: ImplementationSandboxAttempt, root: Path, started: float
    ) -> None:
        promotion = attempt.promotion
        journal = promotion.mutation_journal
        project = next(item for item in self.store.projects() if item.id == attempt.project_id)
        current = self._current_manifest(project.id, root)
        if journal.proposed_manifest_sha256 and current != journal.proposed_manifest_sha256:
            raise ReadOnlyViolation("Applied source manifest does not match the journaled proposal.")
        journal.proposed_manifest_sha256 = current
        journal.stage = "VALIDATING"
        journal.validation_state = "IN_PROGRESS"
        ticket = TicketManager(self.store).check_budget(attempt.ticket_id)
        for command in journal.validation_commands[len(promotion.validations):]:
            available = (
                ticket.budget.max_wall_time_seconds
                - ticket.usage.wall_time_seconds
                - (perf_counter() - started)
            )
            if available <= 0:
                raise RuntimeError("Ticket wall-time budget exhausted during recovered validation.")
            promotion.validations.append(
                self._execute(command, root, min(self.validation_timeout_seconds, available))
            )
            self._journal_checkpoint(
                attempt, "RECOVERY_VALIDATION_RECORDED", "Persisted one recovered bounded validation result."
            )
        if len(promotion.validations) != len(journal.validation_commands):
            raise RuntimeError("Recovered validation history is incomplete.")
        if any(item.exit_code != 0 for item in promotion.validations):
            self._rollback_from_journal(attempt, root, self._journal_paths(root, attempt, journal))
            return
        if self._current_manifest(project.id, root) != current:
            raise RuntimeError("Recovered validation changed indexed project source.")
        promotion.applied_manifest_sha256 = current
        promotion.final_manifest_sha256 = current
        promotion.status = "PROMOTED"
        promotion.completed_at = datetime.now(UTC)
        attempt.status = "PROMOTED"
        journal.stage = "PROMOTED"
        journal.validation_state = "PASSED"
        journal.final_manifest_sha256 = current
        journal.recovery_required = False
        journal.terminal = True
        journal.completed_at = datetime.now(UTC)
        self._journal_checkpoint(attempt, "RECOVERY_PROMOTED", "Recovered application and validation reached a verified terminal state.")
        self._promotion_checkpoint(attempt, "PROMOTED", "Recovered promotion completed; graph reconciliation remains pending.")

    def _rollback_from_journal(
        self, attempt: ImplementationSandboxAttempt, root: Path, paths: list[Path]
    ) -> None:
        promotion = attempt.promotion
        journal = promotion.mutation_journal
        journal.stage = "ROLLING_BACK"
        journal.rollback_state = "IN_PROGRESS"
        self._journal_checkpoint(attempt, "RECOVERY_ROLLBACK_STARTED", "Restoring all journaled original bytes.")
        try:
            for path, entry in zip(paths, journal.entries, strict=True):
                original = base64.b64decode(entry.before_bytes_base64, validate=True)
                self._replace_single(path, original, entry.original_mode, ".rlmgraph-recovery-")
                if file_content_hash(path) != entry.before_sha256:
                    raise OSError(f"Recovered rollback hash mismatch for {entry.path}.")
                entry.rollback_completed = True
                self._journal_checkpoint(attempt, "RECOVERY_PATH_ROLLED_BACK", f"Restored {entry.path}.")
            project = next(item for item in self.store.projects() if item.id == attempt.project_id)
            final = self._current_manifest(project.id, root)
            if final != journal.initial_manifest_sha256:
                raise OSError("Recovered rollback did not restore the exact original project manifest.")
        except Exception:
            journal.rollback_state = "FAILED"
            raise
        promotion.rollback_verified = True
        promotion.final_manifest_sha256 = final
        promotion.status = "ROLLED_BACK"
        promotion.completed_at = datetime.now(UTC)
        attempt.status = "ROLLED_BACK"
        journal.stage = "ROLLED_BACK"
        journal.rollback_state = "VERIFIED"
        journal.final_manifest_sha256 = final
        ticket = TicketManager(self.store).check_budget(attempt.ticket_id)
        journal.validation_state = "ROLLBACK_SOURCE_VERIFIED"
        for command in journal.validation_commands[len(promotion.rollback_validations):]:
            available = ticket.budget.max_wall_time_seconds - ticket.usage.wall_time_seconds
            if available <= 0:
                break
            promotion.rollback_validations.append(
                self._execute(command, root, min(self.validation_timeout_seconds, available))
            )
            self._journal_checkpoint(
                attempt,
                "RECOVERY_ROLLBACK_VALIDATION_RECORDED",
                "Persisted one budget-bounded rollback validation result.",
            )
        journal.recovery_required = False
        journal.terminal = True
        journal.completed_at = datetime.now(UTC)
        self._journal_checkpoint(attempt, "RECOVERY_ROLLED_BACK", "Exact original bytes and manifest were restored.")
        self._promotion_checkpoint(attempt, "ROLLED_BACK", "Crash recovery restored exact original project bytes.")

    @staticmethod
    def _replace_single(target: Path, content: bytes, mode: int, prefix: str) -> None:
        staged = None
        try:
            with NamedTemporaryFile(mode="wb", prefix=prefix, dir=target.parent, delete=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                staged = Path(handle.name)
            os.chmod(staged, mode)
            os.replace(staged, target)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    @classmethod
    def _replace_bytes(cls, paths: list[Path], changes: list[PatchChange], modes: dict[Path, int]) -> None:
        staged = []
        try:
            for target, change in zip(paths, changes, strict=True):
                with NamedTemporaryFile(mode="wb", prefix=".rlmgraph-promote-", dir=target.parent, delete=False) as handle:
                    handle.write(cls._change_bytes(change, True))
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
    def _restore_bytes(originals: dict[Path, bytes], modes: dict[Path, int]) -> None:
        for target, content in originals.items():
            staged = None
            try:
                with NamedTemporaryFile(
                    mode="wb", prefix=".rlmgraph-rollback-", dir=target.parent, delete=False
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged = Path(handle.name)
                os.chmod(staged, modes[target])
                os.replace(staged, target)
            finally:
                if staged is not None:
                    staged.unlink(missing_ok=True)

    def _promotion_checkpoint(self, attempt: ImplementationSandboxAttempt, stage: str, detail: str) -> None:
        promotion = attempt.promotion
        if promotion is None:
            raise RuntimeError("Promotion checkpoint requires an active promotion record.")
        checkpoint = SandboxCheckpoint(
            sequence=len(promotion.checkpoints) + 1, stage=stage, detail=detail
        )
        promotion.checkpoints.append(checkpoint)
        attempt.checkpoints.append(
            SandboxCheckpoint(sequence=len(attempt.checkpoints) + 1, stage=f"PROMOTION_{stage}", detail=detail)
        )
        self.store.save_implementation_sandbox(attempt)

    def _journal_checkpoint(self, attempt: ImplementationSandboxAttempt, stage: str, detail: str) -> None:
        promotion = attempt.promotion
        journal = promotion.mutation_journal if promotion else None
        if journal is None:
            raise RuntimeError("Mutation journal checkpoint requires a durable journal.")
        journal.stage = stage if stage not in {
            "REPLACEMENT_STARTED", "REPLACEMENT_COMPLETED", "VALIDATION_RECORDED",
            "RECOVERY_STARTED", "RECOVERY_VALIDATION_RECORDED", "RECOVERY_PATH_ROLLED_BACK"
        } else journal.stage
        journal.updated_at = datetime.now(UTC)
        journal.checkpoints.append(
            SandboxCheckpoint(sequence=len(journal.checkpoints) + 1, stage=stage, detail=detail)
        )
        journal.evidence.append(Evidence(path=journal.project_root, detail=detail))
        self.store.save_implementation_sandbox(attempt)

    def _inject_fault(self, stage: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(stage)

    def _record_recovery_ticket_event(self, attempt: ImplementationSandboxAttempt) -> None:
        promotion = attempt.promotion
        journal = promotion.mutation_journal if promotion else None
        if journal is None:
            return
        kind = "SANDBOX_PROMOTION_RECOVERED" if journal.terminal else "SANDBOX_PROMOTION_RECOVERY_FAILED"
        if any(
            event.kind == kind and journal.id in event.artifact_ids
            for event in self.store.ticket_events(attempt.ticket_id)
        ):
            return
        TicketManager(self.store)._event(
            attempt.ticket_id,
            kind,
            f"Crash-safe promotion recovery ended in {attempt.status} at fence {journal.fencing_token}.",
            "sandbox recovery",
            [attempt.id, promotion.id, journal.id],
        )

    def _authorized_sources(self, root: Path, authorized: list[str]) -> dict[str, Path]:
        sources = {}
        for relative in authorized:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ReadOnlyViolation(f"Authorized path escapes project scope: {relative}")
            source = (root / path).resolve(strict=True)
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise ReadOnlyViolation(f"Authorized path escapes project scope: {relative}") from exc
            if not source.is_file() or source.is_symlink():
                raise ReadOnlyViolation(f"Authorized path is not a regular source file: {relative}")
            sources[relative] = source
        return sources

    @staticmethod
    def _validation_decision(
        attempt: ImplementationSandboxAttempt, decision_id: str
    ) -> SandboxValidationDecision:
        decision = next((item for item in attempt.validation_decisions if item.id == decision_id), None)
        if decision is None:
            raise ValueError(f"Sandbox validation decision not found: {decision_id}")
        return decision

    @staticmethod
    def _patch_sha256(attempt: ImplementationSandboxAttempt) -> str:
        payload = "\n".join(
            f"{item.path}\0{item.before_hash}\0{item.after_hash}" for item in attempt.changes
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_validation_mirror(
        self, root: Path, mirror: Path, attempt: ImplementationSandboxAttempt
    ) -> dict[str, bytes]:
        mirror.mkdir()
        proposed = {item.path: self._change_bytes(item, True) for item in attempt.changes}
        baseline = {}
        for relative, source in self._authorized_sources(root, attempt.authorized_paths).items():
            target = mirror / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            content = proposed.get(relative, source.read_bytes())
            target.write_bytes(content)
            mode = stat.S_IMODE(source.stat().st_mode)
            os.chmod(target, mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
            baseline[relative] = content
        return baseline

    def _execute_worker(
        self,
        ticket_id: str,
        attempt: ImplementationSandboxAttempt,
        decision: SandboxValidationDecision,
        spec: ValidationWorkerSpec,
        mirror: Path,
        patch_sha: str,
    ) -> SandboxValidationWorkerExecution:
        limits = spec.limits.model_copy(deep=True)
        limits.allowed_paths = limits.allowed_paths or [decision.path]
        limits.allowed_argument_templates = limits.allowed_argument_templates or [spec.arguments]
        executable = str(Path(spec.executable).resolve(strict=True))
        execution = SandboxValidationWorkerExecution(
            ticket_id=ticket_id,
            project_id=attempt.project_id,
            project_root=attempt.project_root,
            attempt_id=attempt.id,
            decision_id=decision.id,
            worker_id=spec.id,
            worker_name=spec.name,
            category=decision.category,
            artifact_kind=decision.artifact_kind,
            path=decision.path,
            source_manifest_sha256=attempt.initial_manifest_sha256,
            patch_sha256=patch_sha,
            authorization_status="AUTHORIZED",
            policy_id=ProjectGovernance(self.store).policy(attempt.project_id).id,
            policy_version=ProjectGovernance(self.store).policy(attempt.project_id).version,
            policy_rule_id="WORKER-ALLOWLIST",
            limits=limits,
            cost_usd=spec.estimated_cost_usd,
        )
        rejection = None
        if decision.category not in spec.categories or decision.artifact_kind not in spec.artifact_kinds:
            rejection = "Validation worker is not authorized for this category or artifact kind."
        elif decision.path not in attempt.authorized_paths or decision.path not in limits.allowed_paths:
            rejection = "Validation worker path is outside its explicit allowed paths."
        elif decision.artifact_kind not in limits.allowed_artifact_kinds:
            rejection = "Validation worker artifact kind is outside its explicit allowlist."
        elif executable not in {str(Path(item).resolve()) for item in limits.allowed_executables}:
            rejection = "Validation worker executable is outside its explicit allowlist."
        elif spec.arguments not in limits.allowed_argument_templates:
            rejection = "Validation worker command arguments are outside its explicit allowlist."
        relative = Path(decision.path)
        if relative.is_absolute() or ".." in relative.parts:
            rejection = "Validation worker path escapes the approved validation slice."
        target = (mirror / relative).resolve(strict=True)
        try:
            target.relative_to(mirror.resolve())
        except ValueError:
            rejection = "Validation worker target escapes the disposable mirror."
        if target.is_symlink() or not target.is_file():
            rejection = "Validation worker target is not a regular mirrored artifact."
        if any("{" in item or "}" in item for item in spec.arguments if item != "{path}"):
            rejection = "Validation worker contains an unsupported command template."
        command = [executable, *[decision.path if item == "{path}" else item for item in spec.arguments]]
        execution.command = command
        if rejection:
            execution.authorization_status = "REJECTED"
            execution.status = "REJECTED"
            execution.failure_reason = rejection
            execution.exit_code = 125
            execution.completed_at = datetime.now(UTC)
            execution.evidence.append(Evidence(path=decision.path, detail=rejection))
            return execution
        ticket = TicketManager(self.store).check_budget(ticket_id)
        remaining = ticket.budget.max_wall_time_seconds - ticket.usage.wall_time_seconds
        if remaining <= 0:
            execution.status = "REJECTED"
            execution.failure_reason = "Ticket wall-time budget is exhausted."
            execution.exit_code = 125
            execution.completed_at = datetime.now(UTC)
            return execution
        limits.max_wall_time_seconds = min(limits.max_wall_time_seconds, remaining)
        execution.checkpoints.append(
            SandboxCheckpoint(sequence=1, stage="AUTHORIZED", detail=spec.authorization_reason)
        )
        result = self.validation_runner.execute(command, mirror, limits)
        execution.exit_code = result.exit_code
        execution.stdout = result.stdout
        execution.stderr = result.stderr
        execution.duration_ms = result.duration_ms
        execution.observed_processes = result.observed_processes
        execution.peak_memory_bytes = result.peak_memory_bytes
        execution.output_bytes = result.output_bytes
        execution.failure_reason = result.failure_reason
        execution.status = (
            "LIMIT_EXCEEDED" if result.failure_reason and "exceeded" in result.failure_reason
            else "PASSED" if result.exit_code == 0 and result.failure_reason is None
            else "FAILED"
        )
        execution.evidence.append(
            Evidence(
                path=decision.path,
                detail=(
                    f"{spec.name} ended as {execution.status}: exit {result.exit_code}, "
                    f"{result.duration_ms:.1f}ms, {result.observed_processes} process(es), "
                    f"peak memory {result.peak_memory_bytes} bytes, output {result.output_bytes} bytes."
                ),
            )
        )
        execution.checkpoints.append(
            SandboxCheckpoint(sequence=2, stage=execution.status, detail=execution.evidence[-1].detail)
        )
        execution.completed_at = datetime.now(UTC)
        return execution

    def _ticket_validation_event(
        self, attempt: ImplementationSandboxAttempt, artifact_id: str, status: str, worker: str
    ) -> None:
        if any(
            event.kind == "SANDBOX_VALIDATION_INTEGRATION_RECORDED"
            and artifact_id in event.artifact_ids
            for event in self.store.ticket_events(attempt.ticket_id)
        ):
            return
        TicketManager(self.store)._event(
            attempt.ticket_id,
            "SANDBOX_VALIDATION_INTEGRATION_RECORDED",
            f"{worker} validation integration recorded as {status}.",
            "Observer validation",
            [attempt.id, artifact_id],
        )

    def _current_manifest(self, project_id: str, root: Path) -> str:
        entries = []
        for item in self.store.project_files(project_id):
            path = (root / item.path).resolve(strict=True)
            path.relative_to(root)
            entries.append((item.path, file_content_hash(path)))
        return indexed_project_fingerprint(root, entries)

    @staticmethod
    def _changed_paths(mirror: Path, baseline: dict[str, bytes]) -> list[str]:
        current = {
            item.relative_to(mirror).as_posix(): item.read_bytes()
            for item in mirror.rglob("*")
            if item.is_file()
        }
        return sorted(
            path
            for path in set(baseline) | set(current)
            if baseline.get(path) != current.get(path)
        )

    @staticmethod
    def _patch(relative: str, before_bytes: bytes, after_path: Path) -> PatchChange:
        after_bytes = after_path.read_bytes() if after_path.exists() else b""
        before = before_bytes.decode("utf-8", errors="replace")
        after = after_bytes.decode("utf-8", errors="replace")
        return PatchChange(
            path=relative,
            before_hash=hashlib.sha256(before_bytes).hexdigest(),
            after_hash=hashlib.sha256(after_bytes).hexdigest(),
            unified_diff="".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                )
            ),
            before_content=before,
            after_content=after,
            before_bytes_base64=base64.b64encode(before_bytes).decode("ascii"),
            after_bytes_base64=base64.b64encode(after_bytes).decode("ascii"),
        )

    def _validation_commands(
        self, planned: list[list[str]], project_id: str, authorized: list[str]
    ) -> list[list[str]]:
        if planned:
            commands = []
            for command in planned:
                if (
                    len(command) < 2
                    or command[0] not in {"python", "pytest"}
                    or (command[0] == "python" and command[1:3] != ["-m", "pytest"])
                ):
                    raise ReadOnlyViolation("Only bounded Python test commands are allowed in this milestone.")
                normalized = [sys.executable, *command[1:]] if command[0] == "python" else [sys.executable, "-m", *command]
                paths = [item.replace("\\", "/") for item in command if item.endswith(".py")]
                if not paths or any(path not in authorized for path in paths):
                    raise ReadOnlyViolation("Planned validation references a path outside the authorized slice.")
                commands.append(normalized)
            return commands
        tests = sorted(
            {
                item.source_path
                for item in self.store.project_tests(project_id)
                if item.source_path in authorized and item.source_path.endswith(".py")
            }
        )
        return [
            [sys.executable, "-m", "pytest", path, "-q", "-p", "no:cacheprovider"]
            for path in tests
        ]

    def _validation_decisions(
        self, project_id: str, changed_paths: list[str], commands: list[list[str]]
    ) -> list[SandboxValidationDecision]:
        unreal = {item.path.replace("\\", "/"): item for item in self.store.unreal_artifacts(project_id)}
        project_files = {
            item.path.replace("\\", "/"): item for item in self.store.project_files(project_id)
        }
        commanded_python = {
            item.replace("\\", "/")
            for command in commands
            for item in command
            if item.endswith(".py")
        }
        decisions = []
        for path in changed_paths:
            artifact = unreal.get(path)
            kind = artifact.kind if artifact else self._fallback_artifact_kind(path, project_files.get(path))
            evidence = [
                Evidence(
                    path=path,
                    detail=(
                        f"Validation route classified from Unreal index metadata as {kind}."
                        if artifact
                        else f"Validation route classified from indexed path metadata as {kind}."
                    ),
                )
            ]
            if kind in {"CPP_SOURCE", "CPP_HEADER", "MODULE_RULES", "TARGET_RULES"}:
                category = "COMPILE"
                requirement = "Compile the affected Unreal target/module in a separately bounded worker before promotion."
                status = "REQUIRED"
                editor = False
            elif kind in {"BLUEPRINT", "MAP", "ASSET"}:
                category = "UNREAL_EDITOR"
                requirement = "Open and validate the affected artifact in Unreal Editor, including references and load/save integrity."
                status = "REQUIRED"
                editor = True
            elif kind in {"CONFIG", "PROJECT_DESCRIPTOR", "PLUGIN_DESCRIPTOR"}:
                category = "UNREAL_EDITOR_CONFIG"
                requirement = "Validate configuration parsing and affected project/plugin behavior in Unreal Editor."
                status = "REQUIRED"
                editor = True
            elif kind == "PYTHON" and path in commanded_python:
                category = "PYTHON_TEST"
                requirement = "Run the indexed targeted Python test under the ticket wall-time budget."
                status = "PENDING"
                editor = False
            elif kind == "PYTHON":
                category = "PYTHON_TEST"
                requirement = "No indexed targeted Python test is available in the authorized slice; add or identify one before promotion."
                status = "REQUIRED"
                editor = False
            else:
                category = "REVIEW"
                requirement = "Perform artifact-specific human review before promotion."
                status = "REQUIRED"
                editor = False
            decisions.append(
                SandboxValidationDecision(
                    path=path,
                    artifact_kind=kind,
                    category=category,
                    requirement=requirement,
                    status=status,
                    requires_unreal_editor=editor,
                    evidence=evidence,
                )
            )
        return decisions

    @staticmethod
    def _fallback_artifact_kind(path: str, project_file) -> str:
        name = Path(path).name
        suffix = Path(path).suffix.casefold()
        if name.endswith(".Build.cs"):
            return "MODULE_RULES"
        if name.endswith(".Target.cs"):
            return "TARGET_RULES"
        return {
            ".cpp": "CPP_SOURCE", ".h": "CPP_HEADER", ".py": "PYTHON",
            ".uasset": "BLUEPRINT" if "/Blueprints/" in f"/{path}" else "ASSET",
            ".umap": "MAP", ".ini": "CONFIG", ".uproject": "PROJECT_DESCRIPTOR",
            ".uplugin": "PLUGIN_DESCRIPTOR",
        }.get(suffix, "PYTHON" if getattr(project_file, "language", "") == "python" else "OTHER")

    @staticmethod
    def _execute(command: list[str], cwd: Path, timeout: float) -> TestExecution:
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
                timeout=timeout,
            )
            return TestExecution(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout[-20_000:],
                stderr=completed.stderr[-20_000:],
                duration_ms=(perf_counter() - started) * 1000,
            )
        except subprocess.TimeoutExpired as exc:
            return TestExecution(
                command=command,
                exit_code=124,
                stdout=str(exc.stdout or "")[-20_000:],
                stderr=str(exc.stderr or "")[-20_000:],
                duration_ms=(perf_counter() - started) * 1000,
            )

    def _checkpoint(self, attempt: ImplementationSandboxAttempt, stage: str, detail: str) -> None:
        attempt.checkpoints.append(
            SandboxCheckpoint(sequence=len(attempt.checkpoints) + 1, stage=stage, detail=detail)
        )
        self.store.save_implementation_sandbox(attempt)


class InteractiveSandboxController:
    def __init__(
        self, manager: ImplementationSandboxManager, *, run_guard=None,
        scheduler: ResourceAwareScheduler | None = None,
    ) -> None:
        self.manager = manager
        self.run_guard = run_guard or threading.Lock()
        self.scheduler = scheduler
        self._lock = threading.Lock()
        self._state = self._restored_state()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "attempt_id": None,
            "scheduled_work_id": None,
            "operation": None,
            "ticket_id": None,
            "plan_record_id": None,
            "status": "IDLE",
            "stage": "Ready.",
            "error": None,
        }

    def _restored_state(self) -> dict:
        persisted = next(
            (
                item for item in self.manager.store.observer_activities()
                if item.id == "OBSERVER-SANDBOX"
            ),
            None,
        )
        if not persisted:
            return self._idle_state()
        state = {**self._idle_state(), **persisted.resume_payload}
        if state["status"] in {"QUEUED", "RUNNING"}:
            state.update(
                status="INTERRUPTED",
                stage="The backend restarted during implementation. Resume from the work queue.",
                error=None,
            )
            self._persist_state(state)
        return state

    def _persist_state(self, state: dict) -> None:
        status = str(state.get("status", "IDLE"))
        self.manager.store.save_observer_activity(ObserverActivityState(
            id="OBSERVER-SANDBOX",
            activity_kind="IMPLEMENTATION_SANDBOX",
            status=status,
            ticket_id=state.get("ticket_id"),
            artifact_id=state.get("attempt_id"),
            stage=str(state.get("stage", "Ready.")),
            resumable=status == "INTERRUPTED",
            resume_payload=dict(state),
            error=state.get("error"),
        ))

    def _update(self, **values) -> None:
        with self._lock:
            self._state.update(values)
            self._persist_state(self._state)

    def start(self, ticket_id: str, plan_record_id: str) -> dict:
        with self._lock:
            if self._state["status"] in {
                "QUEUED", "RUNNING", "WAITING_FOR_CAPACITY", "WAITING_FOR_LEASE",
                "CANCELLATION_REQUESTED",
            }:
                raise RuntimeError("A sandbox implementation is already active.")
            scheduled = self.scheduler.enqueue(
                ticket_id=ticket_id,
                work_kind="IMPLEMENTATION_SANDBOX",
                artifact_id=plan_record_id,
                required_validation_categories=["PATCH", "SOURCE_INTEGRITY"],
                predicted_latency_seconds=60,
                predicted_worker_calls=1,
                capacity_units=1,
            ) if self.scheduler else None
            self._state = {
                "attempt_id": None,
                "scheduled_work_id": scheduled.id if scheduled else None,
                "operation": "IMPLEMENTATION",
                "ticket_id": ticket_id,
                "plan_record_id": plan_record_id,
                "status": "QUEUED",
                "stage": "Waiting for the bounded implementation worker.",
                "error": None,
            }
            self._persist_state(self._state)
        threading.Thread(
            target=self._run,
            args=(ticket_id, plan_record_id, scheduled.id if scheduled else None),
            daemon=True,
        ).start()
        return self.snapshot()

    def _run(
        self, ticket_id: str, plan_record_id: str, scheduled_work_id: str | None = None
    ) -> None:
        try:
            if scheduled_work_id and self.scheduler:
                while self.scheduler.try_claim(scheduled_work_id) is None:
                    item = self.scheduler.get(scheduled_work_id)
                    if item.status in {"CANCELLED", "FAILED", "BLOCKED_BUDGET"}:
                        raise SchedulingCancelled(
                            item.blocked_reason or item.cancellation_reason or "Scheduled work stopped."
                        )
                    threading.Event().wait(0.05)
                self.scheduler.checkpoint(
                    scheduled_work_id, "MIRROR_PREFLIGHT",
                    "Implementation worker admitted; approval and source will be rechecked.",
                )
                self._update(
                    status="RUNNING",
                    stage="Building and validating the disposable mirror.",
                )
                attempt = self.manager.run(ticket_id, plan_record_id)
                self.scheduler.attach_evidence(scheduled_work_id, [attempt.id])
                self.scheduler.checkpoint(
                    scheduled_work_id, "PROPOSAL_PERSISTED",
                    "Sandbox proposal, validation routing, and evidence persisted; mirror disposed.",
                    worker_calls_used=attempt.worker_calls,
                    wall_time_seconds_used=attempt.elapsed_seconds,
                    evidence_ids=[attempt.id],
                )
                self.scheduler.complete(
                    scheduled_work_id,
                    detail="Sandbox implementation completed and scheduler capacity released.",
                )
            else:
                with self.run_guard:
                    self._update(
                        status="RUNNING",
                        stage="Building and validating the disposable mirror.",
                    )
                    attempt = self.manager.run(ticket_id, plan_record_id)
            self._update(
                attempt_id=attempt.id,
                status=attempt.status,
                stage="Reviewable diff captured; disposable filesystem removed.",
            )
        except SchedulingCancelled as exc:
            self._update(status="CANCELLED", stage="Sandbox work cancelled safely.", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - background controller boundary
            self._update(status="FAILED", stage="Sandbox attempt failed.", error=str(exc))
            if scheduled_work_id and self.scheduler:
                item = self.scheduler.get(scheduled_work_id)
                if item.status not in {"CANCELLED", "FAILED"}:
                    self.scheduler.complete(scheduled_work_id, status="FAILED", detail=str(exc))

    def resume(self) -> dict:
        with self._lock:
            state = dict(self._state)
        if state["status"] != "INTERRUPTED":
            raise ValueError("Only an interrupted implementation can be resumed.")
        scheduled_work_id = state.get("scheduled_work_id")
        if scheduled_work_id and self.scheduler:
            self.scheduler.resume(str(scheduled_work_id))
            self._update(
                status="QUEUED",
                stage="Interrupted implementation returned to the durable scheduler queue.",
            )
            target = self._run_promotion if state.get("operation") == "PROMOTION" else self._run
            args = (
                (str(state["ticket_id"]), str(state["attempt_id"]), str(scheduled_work_id))
                if state.get("operation") == "PROMOTION"
                else (str(state["ticket_id"]), str(state["plan_record_id"]), str(scheduled_work_id))
            )
            threading.Thread(target=target, args=args, daemon=True).start()
            return self.snapshot()
        return self.start(str(state["ticket_id"]), str(state["plan_record_id"]))

    def cancel(self, *, actor: str, reason: str) -> dict:
        with self._lock:
            scheduled_work_id = self._state.get("scheduled_work_id")
        if not scheduled_work_id or self.scheduler is None:
            raise ValueError("The active sandbox activity is not managed by the scheduler.")
        item = self.scheduler.request_cancellation(
            str(scheduled_work_id), actor=actor, reason=reason
        )
        if item.status == "CANCELLED":
            self._update(status="CANCELLED", stage="Sandbox work cancelled before admission.", error=reason)
        return self.snapshot()

    def discard(self, ticket_id: str, attempt_id: str) -> dict:
        attempt = self.manager.discard(ticket_id, attempt_id)
        self._update(
            attempt_id=attempt.id,
            ticket_id=ticket_id,
            status=attempt.status,
            stage="Sandbox proposal discarded; registered source unchanged.",
        )
        return self.snapshot()

    def satisfy_validation(
        self, ticket_id: str, attempt_id: str, decision_id: str, actor: str, detail: str,
        governance_decision: str = "APPROVED",
    ) -> dict:
        attempt = self.manager.satisfy_validation(
            ticket_id, attempt_id, decision_id, actor=actor, detail=detail,
            governance_decision=governance_decision,
        )
        return attempt.model_dump(mode="json")

    def run_validation_worker(
        self, ticket_id: str, attempt_id: str, decision_id: str, worker_id: str
    ) -> dict:
        attempt = self.manager.run_validation_worker(
            ticket_id, attempt_id, decision_id, worker_id
        )
        return attempt.model_dump(mode="json")

    def import_external_validation_report(
        self,
        ticket_id: str,
        attempt_id: str,
        decision_id: str,
        *,
        actor: str,
        report_kind: str,
        artifact_path: str,
        source_manifest_sha256: str,
        patch_sha256: str,
        report_bytes_base64: str,
        report_sha256: str,
        status: str,
        detail: str,
    ) -> dict:
        report_bytes = base64.b64decode(report_bytes_base64, validate=True)
        attempt = self.manager.import_external_validation_report(
            ticket_id,
            attempt_id,
            decision_id,
            actor=actor,
            report_kind=report_kind,
            artifact_path=artifact_path,
            source_manifest_sha256=source_manifest_sha256,
            patch_sha256=patch_sha256,
            report_bytes=report_bytes,
            report_sha256=report_sha256,
            status=status,
            detail=detail,
        )
        return attempt.model_dump(mode="json")

    def approve_promotion(
        self, ticket_id: str, attempt_id: str, actor: str, reason: str, decision: str
    ) -> dict:
        attempt = self.manager.approve_promotion(
            ticket_id, attempt_id, actor=actor, reason=reason, decision=decision
        )
        return attempt.model_dump(mode="json")

    def promote(self, ticket_id: str, attempt_id: str) -> dict:
        if self.scheduler:
            scheduled = self.scheduler.enqueue(
                ticket_id=ticket_id,
                work_kind="SANDBOX_PROMOTION",
                artifact_id=attempt_id,
                required_validation_categories=["FINAL_VALIDATION", "SOURCE_INTEGRITY"],
                predicted_latency_seconds=30,
                predicted_worker_calls=1,
                capacity_units=1,
                requires_project_lease=True,
            )
            self._update(
                attempt_id=attempt_id,
                ticket_id=ticket_id,
                scheduled_work_id=scheduled.id,
                operation="PROMOTION",
                status=scheduled.status,
                stage=scheduled.blocked_reason or "Promotion queued for capacity and mutation lease admission.",
                error=None,
            )
            threading.Thread(
                target=self._run_promotion,
                args=(ticket_id, attempt_id, scheduled.id),
                daemon=True,
            ).start()
            return scheduled.model_dump(mode="json")
        attempt = self.manager.promote(ticket_id, attempt_id)
        self._update(
            attempt_id=attempt.id,
            ticket_id=ticket_id,
            status=attempt.status,
            stage="Approved sandbox promotion completed.",
        )
        return attempt.model_dump(mode="json")

    def _run_promotion(
        self, ticket_id: str, attempt_id: str, scheduled_work_id: str
    ) -> None:
        try:
            assert self.scheduler is not None
            while self.scheduler.try_claim(scheduled_work_id) is None:
                item = self.scheduler.get(scheduled_work_id)
                self._update(
                    status=item.status,
                    stage=item.blocked_reason or "Promotion is waiting for scheduler admission.",
                )
                if item.status in {"CANCELLED", "FAILED", "BLOCKED_BUDGET"}:
                    raise SchedulingCancelled(
                        item.blocked_reason or item.cancellation_reason or "Scheduled promotion stopped."
                    )
                threading.Event().wait(0.05)
            self._update(
                status="RUNNING",
                stage="Promotion admitted; rechecking approvals, source, and mutation lease.",
            )
            self.scheduler.checkpoint(
                scheduled_work_id, "PROMOTION_PREFLIGHT",
                "Capacity admitted; promotion safety boundaries are being rechecked.",
            )
            attempt = self.manager.promote(ticket_id, attempt_id)
            evidence_ids = [attempt.id]
            if attempt.promotion:
                evidence_ids.append(attempt.promotion.id)
            current = self.scheduler.attach_evidence(scheduled_work_id, evidence_ids)
            if current.cancellation_requested:
                self.scheduler.complete(
                    scheduled_work_id,
                    detail="Cancellation arrived after mutation began; the durable promotion outcome was preserved.",
                )
                self._update(
                    attempt_id=attempt.id,
                    status=attempt.status,
                    stage="Promotion completed safely before cancellation could take effect.",
                )
                return
            self.scheduler.checkpoint(
                scheduled_work_id, "PROMOTION_PERSISTED",
                "Promotion outcome, validation, mutation journal, and evidence persisted.",
                evidence_ids=evidence_ids,
            )
            self.scheduler.complete(
                scheduled_work_id,
                detail="Promotion reached a durable outcome and scheduler capacity was released.",
            )
            self._update(
                attempt_id=attempt.id,
                status=attempt.status,
                stage="Approved sandbox promotion completed.",
            )
        except SchedulingCancelled as exc:
            self._update(status="CANCELLED", stage="Promotion cancelled before mutation.", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - background promotion boundary
            self._update(status="FAILED", stage="Scheduled promotion stopped safely.", error=str(exc))
            item = self.scheduler.get(scheduled_work_id)
            if item.status not in {"CANCELLED", "FAILED"}:
                self.scheduler.complete(scheduled_work_id, status="FAILED", detail=str(exc))

    def recover(self, ticket_id: str, attempt_id: str) -> dict:
        attempt = self.manager.recover_promotion(ticket_id, attempt_id)
        self._update(
            attempt_id=attempt.id,
            ticket_id=ticket_id,
            status=attempt.status,
            stage="Crash-safe promotion recovery reached a durable outcome.",
        )
        return attempt.model_dump(mode="json")

    def reconcile(self, ticket_id: str, attempt_id: str) -> dict:
        from .reconciliation import SandboxPromotionReconciler

        result = SandboxPromotionReconciler(self.manager.store).reconcile(ticket_id, attempt_id)
        self._update(
            attempt_id=attempt_id,
            ticket_id=ticket_id,
            status="RECONCILED",
            stage="Promoted source and graph state reconciled.",
        )
        return result.model_dump(mode="json")

    def snapshot(self) -> dict:
        with self._lock:
            return {
                **self._state,
                "validation_workers": [
                    item.model_dump(mode="json") for item in self.manager.configured_workers()
                ],
            }
