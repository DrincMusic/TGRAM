from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .fingerprint import file_content_hash, indexed_project_fingerprint
from .models import Evidence, ObserverActivityState, ProjectWorkspaceRecord
from .onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from .scheduler import ResourceAwareScheduler, SchedulingCancelled
from .store import GraphStore
from .ticketing import TicketManager

MAX_REQUEST_CHARACTERS = 1000
MAX_ACCEPTANCE_CRITERIA = 8
MAX_ACCEPTANCE_CRITERION_CHARACTERS = 300
MAX_SELECTED_FILES = 24


class InteractiveProjectWorkspaceController:
    """Neutral, read-only workspace for every explicitly registered project."""

    def __init__(
        self, store: GraphStore, run_guard=None,
        scheduler: ResourceAwareScheduler | None = None,
        idea_suggester=None,
    ) -> None:
        self.store = store
        self._run_guard = run_guard or threading.Lock()
        self.scheduler = scheduler
        self.idea_suggester = idea_suggester
        self._lock = threading.Lock()
        self._state = self._restored_state()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "job_id": None,
            "scheduled_work_id": None,
            "kind": None,
            "project_id": None,
            "project_name": None,
            "ticket_id": None,
            "criteria": [],
            "status": "IDLE",
            "stage": "Choose a project, then ask a question or propose a change.",
            "prompt": "",
            "started_at": None,
            "completed_at": None,
            "elapsed_seconds": 0.0,
            "result_id": None,
            "answer": "",
            "evidence_count": 0,
            "dependency_count": 0,
            "source_integrity_verified": None,
            "read_only_verified": None,
            "approval_status": None,
            "execution_authorized": False,
            "error": None,
        }

    def _restored_state(self) -> dict:
        persisted = next(
            (
                item for item in self.store.observer_activities()
                if item.id == "OBSERVER-WORKSPACE"
            ),
            None,
        )
        if not persisted:
            return self._idle_state()
        state = {**self._idle_state(), **persisted.resume_payload}
        if state["status"] in {"QUEUED", "RUNNING"}:
            state.update(
                status="INTERRUPTED",
                stage="The backend restarted during this activity. Resume it from the work queue.",
                error=None,
            )
            self._persist_state(state)
        return state

    def _persist_state(self, state: dict) -> None:
        status = str(state.get("status", "IDLE"))
        self.store.save_observer_activity(ObserverActivityState(
            id="OBSERVER-WORKSPACE",
            activity_kind="PROJECT_WORKSPACE",
            status=status,
            ticket_id=state.get("ticket_id"),
            project_id=state.get("project_id"),
            artifact_id=state.get("result_id"),
            stage=str(state.get("stage", "Ready.")),
            resumable=status == "INTERRUPTED",
            resume_payload=dict(state),
            error=state.get("error"),
            started_at=state.get("started_at"),
            completed_at=state.get("completed_at"),
        ))

    def options(self) -> dict:
        projects = []
        for project in self.store.projects():
            if not project.explicitly_selected:
                continue
            root = Path(project.root).resolve()
            manifest_path = root / "manifest.md"
            goals_path = root / "goals.json"
            try:
                project_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else project.project_manifest
            except (OSError, UnicodeError):
                project_manifest = project.project_manifest
            try:
                raw_goals = json.loads(goals_path.read_text(encoding="utf-8")) if goals_path.is_file() else (
                    [{"title": "Imported project goals", "goal": project.project_goals}]
                    if project.project_goals.strip() else []
                )
                project_goals = [
                    {"title": str(item["title"]), "goal": str(item["goal"])}
                    for item in raw_goals
                    if isinstance(item, dict) and item.get("title") and item.get("goal")
                ] if isinstance(raw_goals, list) else []
            except (OSError, UnicodeError, json.JSONDecodeError):
                project_goals = []
            scans = self.store.project_scans(project.id)
            generic_scan = max(scans, key=lambda item: item.completed_at) if scans else None
            unreal_scan = None
            projects.append(
                {
                    "id": project.id,
                    "name": root.name,
                    "root": str(root),
                    "organization": project.organization,
                    "execution_mode": project.execution_mode.value,
                    "project_manifest": project_manifest,
                    "project_goals": project_goals,
                    "ideas": [idea.model_dump(mode="json") for idea in project.ideas],
                    "read_only": project.read_only,
                    "write_capability": project.execution_mode.value == "AUTONOMOUS_PROJECT",
                    "index_current": bool(unreal_scan or generic_scan),
                    "index_scan_id": unreal_scan.id if unreal_scan else generic_scan.id if generic_scan else None,
                    "artifact_count": (
                        unreal_scan.artifact_count
                        if unreal_scan
                        else generic_scan.file_count
                        if generic_scan
                        else 0
                    ),
                    "dependency_count": (
                        unreal_scan.dependency_count
                        if unreal_scan
                        else generic_scan.dependency_count
                        if generic_scan
                        else 0
                    ),
                    "adapter": "UNREAL_GRAPH" if unreal_scan else "SOURCE_GRAPH",
                }
            )
        return {
            "projects": sorted(projects, key=lambda item: item["name"].casefold()),
            "limits": {
                "request_characters": MAX_REQUEST_CHARACTERS,
                "acceptance_criteria": MAX_ACCEPTANCE_CRITERIA,
                "criterion_characters": MAX_ACCEPTANCE_CRITERION_CHARACTERS,
                "concurrent_jobs": 1,
                "project_writes": 0,
                "unreal_launches": 0,
                "compilations": 0,
            },
        }

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start_diagnostic(
        self, project_id: str, question: str, ticket_id: str | None = None
    ) -> dict:
        return self._start("DIAGNOSTIC", project_id, question, [], ticket_id)

    def start_change_plan(
        self,
        project_id: str,
        request: str,
        acceptance_criteria: list[str],
        ticket_id: str | None = None,
    ) -> dict:
        if not isinstance(acceptance_criteria, list):
            raise TypeError("Acceptance criteria must be a list of strings.")
        criteria = [" ".join(str(item).split()) for item in acceptance_criteria if str(item).strip()]
        if len(criteria) > MAX_ACCEPTANCE_CRITERIA:
            raise ValueError(f"At most {MAX_ACCEPTANCE_CRITERIA} acceptance criteria are allowed.")
        if any(len(item) > MAX_ACCEPTANCE_CRITERION_CHARACTERS for item in criteria):
            raise ValueError(
                f"Each acceptance criterion is limited to {MAX_ACCEPTANCE_CRITERION_CHARACTERS} characters."
            )
        return self._start("CHANGE_PLAN", project_id, request, criteria, ticket_id)

    def suggest_ideas(self, project_id: str) -> dict:
        if self.idea_suggester is None:
            raise RuntimeError("AI suggestions are unavailable because no AI worker is configured.")
        option = next(
            (item for item in self.options()["projects"] if item["id"] == project_id), None
        )
        if not option:
            raise ValueError("Select an explicitly registered read-only project.")
        if not option["index_current"] or not self._project_index_current(project_id):
            raise RuntimeError("The selected project index is stale. Re-index before suggesting ideas.")
        with self._lock:
            if self._state["status"] in {"QUEUED", "RUNNING"}:
                raise RuntimeError("Another read-only project analysis is already running.")
        if not self._run_guard.acquire(blocking=False):
            raise RuntimeError("Another interactive read-only workflow is already running.")
        try:
            project = ProjectGovernance(self.store).project(project_id)
            root = Path(project.root).resolve(strict=True)
            unreal_scan = None
            indexed_before, current_before = self._manifests(project.id, root, unreal_scan)
            if indexed_before != current_before:
                raise RuntimeError("The selected project index became stale before AI analysis.")
            indexed_paths = [item.path for item in self.store.project_files(project.id)]
            if not indexed_paths:
                text_suffixes = {
                    ".build.cs", ".cpp", ".cs", ".h", ".hpp", ".ini", ".json",
                    ".md", ".py", ".toml", ".txt", ".uplugin", ".uproject", ".yaml", ".yml",
                }
                indexed_paths = [
                    item.path
                    for item in self.store.unreal_artifacts(project.id)
                    if any(item.path.casefold().endswith(suffix) for suffix in text_suffixes)
                ]
            result = self.idea_suggester.suggest(root, indexed_paths)
            _, current_after = self._manifests(project.id, root, unreal_scan)
            if current_before != current_after:
                raise RuntimeError("Project source changed during AI suggestion analysis.")
            authorized_paths = list(
                getattr(self.idea_suggester, "last_authorized_paths", indexed_paths)
            )
            return {
                "project_id": project.id,
                "project_name": option["name"],
                "index_scan_id": option["index_scan_id"],
                "indexed_manifest_sha256": indexed_before,
                "source_integrity_verified": True,
                "read_only_verified": True,
                "suggestions": [
                    suggestion.model_dump(mode="json") for suggestion in result.suggestions
                ],
                "confidence": result.confidence,
                "files_examined": result.files_examined,
                "worker": {
                    "name": "Codex CLI",
                    "model": getattr(self.idea_suggester, "model", None) or "CLI default",
                    "sandbox": getattr(self.idea_suggester, "sandbox", "read-only"),
                    "calls": 1,
                    "indexed_files": len(indexed_paths),
                    "authorized_files": len(authorized_paths),
                    "source_bytes": int(
                        getattr(self.idea_suggester, "last_source_bytes", 0)
                    ),
                    "monetary_cost": None,
                    "cost_basis": (
                        "Codex CLI account-backed execution; monetary cost is not exposed."
                    ),
                },
                "persistence": "NOT_SAVED",
                "authority": "NO_TICKET_RUN_OR_PROJECT_WRITE",
            }
        finally:
            self._run_guard.release()

    def _start(
        self,
        kind: str,
        project_id: str,
        prompt: str,
        criteria: list[str],
        ticket_id: str | None,
    ) -> dict:
        prompt = " ".join(prompt.split())
        if not prompt:
            raise ValueError("A question or proposed change is required.")
        if len(prompt) > MAX_REQUEST_CHARACTERS:
            raise ValueError(f"Request exceeds the {MAX_REQUEST_CHARACTERS}-character limit.")
        option = next(
            (item for item in self.options()["projects"] if item["id"] == project_id), None
        )
        if not option:
            raise ValueError("Select an explicitly registered read-only project.")
        ProjectGovernance(self.store).policy(project_id)
        ticket_manager = TicketManager(self.store)
        ticket = None
        if ticket_id:
            ticket = ticket_manager.check_budget(ticket_id)
            if ticket.project_id != project_id:
                raise ValueError("Workspace project must match the originating ticket project.")
        if not self._project_index_current(project_id):
            project = ProjectGovernance(self.store).project(project_id)
            root = Path(project.root).resolve(strict=True)
            ReadOnlyProjectOnboarder(self.store).scan(ProjectSelection.explicit(root))
        if ticket is not None:
            ticket_manager.assert_current_source_claims(ticket)
        with self._lock:
            if self._state["status"] in {"QUEUED", "RUNNING"}:
                raise RuntimeError("A workspace job is already running.")
            guard_acquired = self.scheduler is None and self._run_guard.acquire(blocking=False)
            if self.scheduler is None and not guard_acquired:
                raise RuntimeError("Another interactive read-only workflow is already running.")
            job_id = f"WORKSPACE-{uuid4().hex[:12]}"
            scheduled = self.scheduler.enqueue(
                ticket_id=ticket_id,
                work_kind=f"WORKSPACE_{kind}",
                artifact_id=job_id,
                required_validation_categories=["READ_ONLY_SOURCE_INTEGRITY"],
                predicted_latency_seconds=30,
                predicted_worker_calls=1,
            ) if self.scheduler is not None and ticket_id else None
            self._state = {
                **self._idle_state(),
                "job_id": job_id,
                "scheduled_work_id": scheduled.id if scheduled else None,
                "kind": kind,
                "project_id": project_id,
                "project_name": option["name"],
                "ticket_id": ticket_id,
                "criteria": criteria,
                "status": "QUEUED",
                "stage": "Queued inside the single-job read-only boundary.",
                "prompt": prompt,
                "started_at": datetime.now(UTC).isoformat(),
            }
            self._persist_state(self._state)
        threading.Thread(
            target=self._run,
            args=(job_id, kind, project_id, prompt, criteria, ticket_id, scheduled.id if scheduled else None),
            daemon=True,
        ).start()
        return self.snapshot()

    def _update(self, job_id: str, **values) -> None:
        with self._lock:
            if self._state["job_id"] == job_id:
                self._state.update(values)
                self._persist_state(self._state)

    def resume(self) -> dict:
        with self._lock:
            state = dict(self._state)
        if state["status"] != "INTERRUPTED":
            raise ValueError("Only an interrupted workspace activity can be resumed.")
        scheduled_work_id = state.get("scheduled_work_id")
        if scheduled_work_id and self.scheduler:
            self.scheduler.resume(str(scheduled_work_id))
            self._update(
                str(state["job_id"]), status="QUEUED",
                stage="Interrupted workspace work returned to the durable scheduler queue.",
            )
            threading.Thread(
                target=self._run,
                args=(
                    str(state["job_id"]), str(state["kind"]), str(state["project_id"]),
                    str(state["prompt"]), list(state.get("criteria", [])),
                    state.get("ticket_id"), str(scheduled_work_id),
                ),
                daemon=True,
            ).start()
            return self.snapshot()
        return self._start(
            str(state["kind"]), str(state["project_id"]), str(state["prompt"]),
            list(state.get("criteria", [])), state.get("ticket_id"),
        )

    def _run(
        self,
        job_id: str,
        kind: str,
        project_id: str,
        prompt: str,
        criteria: list[str],
        ticket_id: str | None,
        scheduled_work_id: str | None,
    ) -> None:
        started = time.monotonic()
        guard_acquired = scheduled_work_id is None
        try:
            if scheduled_work_id and self.scheduler:
                while self.scheduler.try_claim(scheduled_work_id) is None:
                    item = self.scheduler.get(scheduled_work_id)
                    if item.status in {"CANCELLED", "FAILED", "BLOCKED_BUDGET"}:
                        raise SchedulingCancelled(item.blocked_reason or item.cancellation_reason or "Scheduled work stopped.")
                    time.sleep(0.05)
                self.scheduler.checkpoint(
                    scheduled_work_id, "SOURCE_PREFLIGHT",
                    "Workspace worker admitted; verifying current read-only source.",
                )
            else:
                # Legacy callers reserve the shared guard before starting this thread.
                pass
            self._update(
                job_id,
                status="RUNNING",
                stage="Verifying the selected project's current read-only index.",
            )
            project = ProjectGovernance(self.store).project(project_id)
            root = Path(project.root).resolve(strict=True)
            unreal_scan = None
            indexed_before, current_before = self._manifests(project.id, root, unreal_scan)
            if indexed_before != current_before:
                raise RuntimeError("The selected project index became stale before execution.")
            self._update(
                job_id,
                stage=(
                    "Traversing graph evidence and dependencies."
                    if kind == "DIAGNOSTIC"
                    else "Building the impact report, risks, steps, and validation contract."
                ),
            )
            record = self._source_record(project, root, kind, prompt, criteria)
            self._update(
                job_id,
                stage="Rechecking source integrity before publishing the result.",
            )
            _, current_after = self._manifests(project.id, root, unreal_scan)
            if current_before != current_after:
                raise RuntimeError("Project source changed during the interactive workflow.")
            record.final_manifest_sha256 = current_after
            record.source_integrity_verified = True
            record.ticket_id = ticket_id
            record.elapsed_seconds = round(time.monotonic() - started, 3)
            if ticket_id:
                TicketManager(self.store).attach_workspace_record(ticket_id, record)
            else:
                self.store.save_project_workspace_record(record)
            if scheduled_work_id and self.scheduler:
                self.scheduler.attach_evidence(scheduled_work_id, [record.id])
                self.scheduler.checkpoint(
                    scheduled_work_id, "RESULT_PERSISTED", "Workspace result and evidence persisted.",
                    wall_time_seconds_used=record.elapsed_seconds, evidence_ids=[record.id],
                )
                self.scheduler.complete(
                    scheduled_work_id, detail="Read-only workspace work completed and capacity released."
                )
            self._update(
                job_id,
                status="COMPLETED",
                stage="Read-only workspace result is ready.",
                completed_at=datetime.now(UTC).isoformat(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                result_id=record.id,
                answer=record.answer,
                evidence_count=len(record.evidence),
                dependency_count=len(record.dependency_ids),
                source_integrity_verified=True,
                read_only_verified=True,
                approval_status=record.approval_status,
                execution_authorized=False,
            )
        except SchedulingCancelled as exc:
            self._update(
                job_id, status="CANCELLED", stage="Workspace job cancelled safely.",
                completed_at=datetime.now(UTC).isoformat(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                execution_authorized=False, error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - background workflow boundary
            self._update(
                job_id,
                status="FAILED",
                stage="Workspace job stopped at a safety boundary.",
                completed_at=datetime.now(UTC).isoformat(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                source_integrity_verified=False,
                read_only_verified=False,
                execution_authorized=False,
                error=str(exc),
            )
            if scheduled_work_id and self.scheduler:
                item = self.scheduler.get(scheduled_work_id)
                if item.status not in {"CANCELLED", "FAILED"}:
                    self.scheduler.complete(scheduled_work_id, status="FAILED", detail=str(exc))
        finally:
            if guard_acquired:
                self._run_guard.release()

    def cancel(self, *, actor: str, reason: str) -> dict:
        with self._lock:
            scheduled_work_id = self._state.get("scheduled_work_id")
        if not scheduled_work_id or self.scheduler is None:
            raise ValueError("The active workspace activity is not managed by the scheduler.")
        item = self.scheduler.request_cancellation(
            str(scheduled_work_id), actor=actor, reason=reason
        )
        if item.status == "CANCELLED":
            self._update(
                str(self._state.get("job_id")), status="CANCELLED",
                stage="Workspace job cancelled before worker admission.", error=reason,
            )
        return self.snapshot()

    def _source_record(self, project, root, kind, prompt, criteria):
        from .workflow_fact_search import WorkflowFactSearch

        files = self.store.project_files(project.id)
        dependencies = self.store.project_dependencies(project.id)
        scans = self.store.project_scans(project.id)
        if not files or not scans:
            raise RuntimeError("The selected project has no usable source index.")
        scan = max(scans, key=lambda item: item.completed_at)
        tokens = self._tokens(prompt)
        symbol_tokens: dict[str, set[str]] = defaultdict(set)
        for symbol in self.store.project_symbols(project.id):
            symbol_tokens[symbol.file_id].update(self._tokens(symbol.name))
        scores = {
            item.id: self._file_score(item, tokens)
            + 6 * len(tokens & symbol_tokens.get(item.id, set()))
            for item in files
        }
        search = WorkflowFactSearch(self.store).search(
            " ".join(sorted(self._tokens(" ".join([prompt, *criteria])))),
            root, project.id, files=files,
        )
        for hit in search.hits:
            if hit.kind == "SOURCE_EXCERPT" and hit.reference in scores:
                scores[hit.reference] += 6 * hit.score
        ranked = sorted(files, key=lambda item: (-scores[item.id], item.path))
        seeds = [item for item in ranked if scores[item.id] > 0][:6] or ranked[:3]
        selected_ids = {item.id for item in seeds}
        adjacency = defaultdict(list)
        for dependency in dependencies:
            if dependency.target_file_id:
                adjacency[dependency.source_file_id].append((dependency.target_file_id, dependency.id))
                adjacency[dependency.target_file_id].append((dependency.source_file_id, dependency.id))
        traversed = []
        queue = deque((item.id, 0) for item in seeds)
        while queue and len(selected_ids) < MAX_SELECTED_FILES:
            file_id, depth = queue.popleft()
            if depth >= 3:
                continue
            for neighbor, dependency_id in adjacency[file_id]:
                if neighbor in selected_ids:
                    continue
                selected_ids.add(neighbor)
                traversed.append(dependency_id)
                queue.append((neighbor, depth + 1))
        by_id = {item.id: item for item in files}
        selected = sorted((by_id[item] for item in selected_ids if item in by_id), key=lambda x: x.path)
        evidence = [self._file_evidence(root, item, tokens) for item in selected]
        for hit in search.hits:
            if hit.kind == "SOURCE_EXCERPT" and hit.reference in selected_ids:
                evidence.append(Evidence(
                    path=hit.path, line=hit.line,
                    detail=f"Task search matched {', '.join(hit.matched_terms)}: {hit.text}",
                ))
        groups = defaultdict(list)
        for item in selected:
            groups["tests" if item.is_test else item.language or "source"].append(item.path)
        indexed, current = self._manifests(project.id, root, None)
        base = {
            "project_id": project.id,
            "project_root": str(root),
            "project_name": root.name,
            "kind": kind,
            "prompt": prompt,
            "acceptance_criteria": criteria,
            "affected_file_ids": [item.id for item in selected],
            "affected_paths": [item.path for item in selected],
            "dependency_ids": sorted(set(traversed)),
            "dependency_paths": [item.path for item in selected],
            "evidence": evidence,
            "impact_groups": dict(sorted(groups.items())),
            "index_scan_id": scan.id,
            "indexed_manifest_sha256": indexed,
            "final_manifest_sha256": current,
            "source_integrity_verified": indexed == current,
            "read_only_verified": project.read_only and scan.read_only_verified,
            "execution_authorized": False,
        }
        if kind == "DIAGNOSTIC":
            details = "; ".join(item.detail for item in evidence[:8])
            return ProjectWorkspaceRecord(
                **base,
                status="COMPLETED",
                answer=f"The indexed project evidence points to {len(selected)} files: {details}",
            )
        return ProjectWorkspaceRecord(
            **base,
            status="AWAITING_HUMAN_APPROVAL",
            answer=f"Read-only impact analysis selected {len(selected)} files across {len(groups)} source groups.",
            steps=[
                "Confirm the requested behavior and affected public contracts.",
                "Implement only the graph-selected files after separate authorization.",
                "Run the selected tests and project-specific validation before promotion.",
            ],
            risks=[
                "Graph reachability may not capture runtime or dynamically loaded dependencies.",
                "Human approval of this plan does not authorize source modification.",
            ],
            validation_requirements=[
                "Re-index and verify the source manifest immediately before implementation.",
                "Run affected indexed tests and attach their results.",
                "Review every changed path against the approved impact report.",
            ],
            validation_commands=[
                ["python", "-m", "pytest", item.path, "-q", "-p", "no:cacheprovider"]
                for item in selected
                if item.is_test and item.path.endswith(".py")
            ],
            approval_required=True,
            approval_status="PENDING",
        )

    def _manifests(self, project_id: str, root: Path, unreal_scan):
        files = self.store.project_files(project_id)
        indexed = indexed_project_fingerprint(root, [(item.path, item.content_hash) for item in files])
        current_entries = []
        for item in files:
            try:
                path = (root / item.path).resolve(strict=True)
                path.relative_to(root)
                content_hash = file_content_hash(path)
            except (OSError, ValueError):
                content_hash = "MISSING_OR_OUTSIDE_PROJECT"
            current_entries.append((item.path, content_hash))
        return indexed, indexed_project_fingerprint(root, current_entries)

    def _project_index_current(self, project_id: str) -> bool:
        project = next((item for item in self.store.projects() if item.id == project_id), None)
        if not project or not project.read_only or not project.explicitly_selected:
            return False
        root = Path(project.root).resolve(strict=True)
        unreal_scan = None
        scans = self.store.project_scans(project.id)
        if not unreal_scan and not scans:
            return False
        indexed, current = self._manifests(project.id, root, unreal_scan)
        return indexed == current

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9_]+", text.casefold())) - {
            "a", "an", "and", "create", "for", "in", "of", "on", "the", "to"
        }

    @staticmethod
    def _file_score(item, tokens: set[str]) -> int:
        path = item.path.casefold()
        words = set(re.findall(r"[a-z0-9_]+", path))
        return len(tokens & words) * 4 + sum(
            1 for token in tokens if len(token) >= 4 and token in path
        )

    @staticmethod
    def _file_evidence(root: Path, item, tokens: set[str]) -> Evidence:
        path = (root / item.path).resolve(strict=True)
        path.relative_to(root)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        line_no, detail = next(
            (
                (number, line.strip())
                for number, line in enumerate(lines, 1)
                if tokens & set(re.findall(r"[a-z0-9_]+", line.casefold()))
            ),
            (1, lines[0].strip() if lines else item.path),
        )
        return Evidence(path=item.path, line=line_no, detail=detail[:500])

    @staticmethod
    def _group_unreal(artifacts) -> dict[str, list[str]]:
        groups = defaultdict(list)
        for item in artifacts:
            groups[item.kind].append(item.path)
        return dict(sorted(groups.items()))

    @staticmethod
    def _diagnostic_contract(question: str) -> tuple[str, set[str]]:
        tokens = set(re.findall(r"[a-z0-9_]+", question.casefold()))
        if tokens & {"spawn", "landing", "player", "runtime"}:
            return "runtime spawn", {"CPP_HEADER", "CPP_SOURCE"}
        if tokens & {"blueprint", "map", "level", "game"}:
            return "blueprint map", {"BLUEPRINT", "MAP"}
        if tokens & {"terrain", "biome", "pipeline", "test", "tool"}:
            return "offline terrain", {"TEST", "TOOL_SOURCE"}
        if tokens & {"config", "configuration", "cesium", "plugin", "module"}:
            return "configuration and modules", {"CONFIG", "MODULE_RULES"}
        return "project overview", {"PROJECT_DESCRIPTOR"}
from .governance import ProjectGovernance
