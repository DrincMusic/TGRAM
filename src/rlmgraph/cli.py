from __future__ import annotations

import json
from pathlib import Path

import typer

from .adapters import (
    DEFAULT_CODEX_REPAIR_SANDBOX,
    DEFAULT_CODEX_SANDBOX,
    CodexCliInvestigator,
    CodexCliResolver,
    CodexCommandInvestigator,
)
from .evaluation import DeterministicEvaluationHarness
from .execution import AdaptiveInvestigator, WorkerSpec
from .followup import FollowUpExecutor
from .graph_debugging import GraphDirectedDebugger
from .models import ApprovalDecision, PursuitConfig, TaskRoute
from .onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from .operations import (
    SQLiteMaintenance,
    TicketAuditExporter,
    ensure_outside_registered_projects,
)
from .promotion import RepairPromoter
from .reconciliation import PostRepairReconciler
from .repair import SandboxedRepairValidator
from .resolution import ResolutionExecutor
from .runner import RecursiveRunner
from .store import SQLiteGraphStore
from .supervisor import GraphGroundedSupervisor, Supervisor
from .workflow import MaintenanceWorkflowRunner

app = typer.Typer(help="Inspect and run the RLMGraph prototype.")


@app.command("backup")
def backup_command(
    destination: Path = typer.Argument(...),  # noqa: B008
    database: Path = typer.Option(Path(".rlmgraph.db"), "--database"),  # noqa: B008
) -> None:
    """Create and verify a consistent SQLite backup."""
    store = SQLiteGraphStore(database)
    store.initialize()
    typer.echo(json.dumps(SQLiteMaintenance(store).backup(destination), indent=2))


@app.command("restore")
def restore_command(
    source: Path = typer.Argument(..., exists=True, dir_okay=False),  # noqa: B008
    confirmation: str = typer.Option(..., "--confirm"),
    database: Path = typer.Option(Path(".rlmgraph.db"), "--database"),  # noqa: B008
) -> None:
    """Restore a verified SQLite backup after creating a safety backup."""
    store = SQLiteGraphStore(database)
    store.initialize()
    typer.echo(json.dumps(
        SQLiteMaintenance(store).restore(source, confirmation=confirmation), indent=2
    ))


@app.command("migrate")
def migrate_command(
    database: Path = typer.Option(Path(".rlmgraph.db"), "--database"),  # noqa: B008
) -> None:
    """Apply idempotent schema migrations and report database health."""
    store = SQLiteGraphStore(database)
    typer.echo(json.dumps(SQLiteMaintenance(store).migrate(), indent=2))


@app.command("maintain")
def maintain_command(
    database: Path = typer.Option(Path(".rlmgraph.db"), "--database"),  # noqa: B008
) -> None:
    """Optimize and verify the SQLite workspace database."""
    store = SQLiteGraphStore(database)
    store.initialize()
    typer.echo(json.dumps(SQLiteMaintenance(store).optimize(), indent=2))


@app.command("export-ticket")
def export_ticket_command(
    ticket_id: str,
    destination: Path = typer.Argument(...),  # noqa: B008
    database: Path = typer.Option(Path(".rlmgraph.db"), "--database"),  # noqa: B008
) -> None:
    """Export a self-verifying ticket audit and evidence package."""
    store = SQLiteGraphStore(database)
    store.initialize()
    package = TicketAuditExporter(store).build(ticket_id)
    target = ensure_outside_registered_projects(store, destination)
    target.write_text(json.dumps(package, indent=2), encoding="utf-8")
    typer.echo(str(target))


@app.command("evaluate")
def evaluate_command(
    project: Path = typer.Option(  # noqa: B008
        ..., "--project", file_okay=False, resolve_path=True,
        help="Isolated directory for deterministic evaluation fixtures",
    ),
    database: Path = typer.Option(  # noqa: B008
        Path(".rlmgraph.db"), help="SQLite graph database"
    ),
    repetitions: int = typer.Option(2, min=2),
) -> None:
    """Run the three-strategy deterministic evaluation suite."""
    run = DeterministicEvaluationHarness(
        SQLiteGraphStore(database), project, repetitions=repetitions
    ).run()
    typer.echo(run.model_dump_json(indent=2))


@app.command()
def onboard(
    project: Path = typer.Option(  # noqa: B008
        ...,
        "--project",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Explicit repository root to scan read-only",
    ),
    database: Path = typer.Option(  # noqa: B008
        Path(".rlmgraph.db"),
        help="Graph database path; it must be outside the selected project",
    ),
) -> None:
    """Build or incrementally refresh a read-only project graph."""
    scan = ReadOnlyProjectOnboarder(SQLiteGraphStore(database)).scan(
        ProjectSelection.explicit(project)
    )
    typer.echo(scan.model_dump_json(indent=2))


@app.command()
def pursue(
    task_id: str,
    database: Path = Path(".rlmgraph.db"),
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(
        DEFAULT_CODEX_SANDBOX,
        help="Codex sandbox (Windows read-only ACL setup may be unavailable)",
    ),
    max_depth: int = typer.Option(4, min=0),
    max_codex_calls: int = typer.Option(8, min=0),
    max_retries: int = typer.Option(2, min=1),
    minimum_confidence: float = typer.Option(0.75, min=0, max=1),
) -> None:
    """Recursively pursue a task tree until completion or a safety limit."""
    store = SQLiteGraphStore(database)
    executor = ResolutionExecutor(store, CodexCliResolver(codex, model, sandbox), minimum_confidence)
    runner = RecursiveRunner(
        store,
        executor,
        PursuitConfig(
            max_depth=max_depth,
            max_codex_calls=max_codex_calls,
            max_retries_per_task=max_retries,
            minimum_confidence=minimum_confidence,
        ),
        FollowUpExecutor(
            store,
            AdaptiveInvestigator(
                store,
                [
                    WorkerSpec(
                        TaskRoute.CODEX,
                        CodexCliInvestigator(codex, model, sandbox),
                        "CodexCliInvestigator",
                    )
                ],
                minimum_confidence,
            ),
        ),
    )
    typer.echo(runner.pursue(task_id).model_dump_json(indent=2))


@app.command()
def resolve(
    task_id: str,
    database: Path = Path(".rlmgraph.db"),
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(
        DEFAULT_CODEX_SANDBOX,
        help="Codex sandbox (Windows read-only ACL setup may be unavailable)",
    ),
    confidence_threshold: float = typer.Option(0.75, min=0, max=1),
) -> None:
    """Execute one open resolution task with Codex."""
    executor = ResolutionExecutor(
        SQLiteGraphStore(database),
        CodexCliResolver(codex, model, sandbox),
        confidence_threshold,
    )
    typer.echo(executor.execute(task_id).model_dump_json(indent=2))


@app.command()
def investigate(
    question: str,
    project: Path = Path("."),
    database: Path = Path(".rlmgraph.db"),
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(
        DEFAULT_CODEX_SANDBOX,
        help="Codex sandbox (Windows read-only ACL setup may be unavailable)",
    ),
    force: bool = typer.Option(False, help="Force an independent Codex investigation"),
) -> None:
    """Investigate with Codex, or reuse a matching persisted discovery."""
    supervisor = Supervisor(
        SQLiteGraphStore(database), CodexCliInvestigator(codex, model, sandbox)
    )
    typer.echo(
        supervisor.run(question, project, force_investigation=force).model_dump_json(indent=2)
    )


@app.command("investigate-indexed")
def investigate_indexed(
    question: str,
    project: Path = typer.Option(  # noqa: B008
        ...,
        "--project",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Explicit read-only repository root",
    ),
    database: Path = typer.Option(  # noqa: B008
        ...,
        "--database",
        help="Graph database path outside the selected repository",
    ),
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(DEFAULT_CODEX_SANDBOX, help="Codex sandbox"),
    force: bool = typer.Option(False, help="Force an independent investigation"),
) -> None:
    """Investigate through the read-only project graph, or reuse grounded memory."""
    supervisor = GraphGroundedSupervisor(
        SQLiteGraphStore(database), CodexCliInvestigator(codex, model, sandbox)
    )
    result = supervisor.run(question, project, force_investigation=force)
    typer.echo(result.model_dump_json(indent=2))


@app.command("debug-indexed")
def debug_indexed(
    question: str,
    test: str = typer.Option(..., "--test", help="Indexed test file path relative to project"),
    project: Path = typer.Option(  # noqa: B008
        ...,
        "--project",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Explicit read-only repository root",
    ),
    database: Path = typer.Option(  # noqa: B008
        ..., "--database", help="Existing project graph outside the repository"
    ),
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(DEFAULT_CODEX_SANDBOX, help="Codex sandbox"),
) -> None:
    """Trace one indexed test, investigate bounded slices, and synthesize a diagnosis."""
    adapter = CodexCliInvestigator(codex, model, sandbox)
    result = GraphDirectedDebugger(
        SQLiteGraphStore(database), adapter, adapter
    ).debug(question, project, test)
    typer.echo(result.model_dump_json(indent=2))


@app.command("repair-validate")
def repair_validate(
    diagnosis: str = typer.Option(..., "--diagnosis", help="Completed diagnosis claim ID"),
    test: str = typer.Option(..., "--test", help="Affected test path relative to project"),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(DEFAULT_CODEX_REPAIR_SANDBOX, help="Codex repair sandbox"),
    max_attempts: int = typer.Option(2, min=1, help="Maximum sandboxed repair attempts"),
) -> None:
    """Patch a disposable bounded mirror and prove the affected test before/after."""
    result = SandboxedRepairValidator(
        SQLiteGraphStore(database),
        CodexCliInvestigator(codex, model, sandbox),
        max_attempts=max_attempts,
    ).validate(diagnosis, test)
    typer.echo(result.model_dump_json(indent=2))


@app.command("repair-review")
def repair_review(
    proposal: str = typer.Option(..., "--proposal", help="Verified repair proposal ID"),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
) -> None:
    """Present the exact verified patch and sandbox proof without modifying source."""
    repair, validation = RepairPromoter(SQLiteGraphStore(database)).review(proposal)
    typer.echo(
        json.dumps(
            {
                "proposal": repair.model_dump(mode="json"),
                "sandbox_validation": validation.model_dump(mode="json"),
                "next_step": (
                    "Run repair-promote with the explicit project, --approve, "
                    "--approved-by, and --reason after reviewing this evidence."
                ),
            },
            indent=2,
        )
    )


@app.command("repair-promote")
def repair_promote(
    proposal: str = typer.Option(..., "--proposal", help="Verified repair proposal ID"),
    project: Path = typer.Option(  # noqa: B008
        ...,
        "--project",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Explicitly selected project root",
    ),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
    approve: bool | None = typer.Option(
        None,
        "--approve/--reject",
        help="Explicit human decision; omission is refused",
    ),
    approved_by: str = typer.Option(..., "--approved-by", help="Human reviewer identity"),
    reason: str = typer.Option(..., "--reason", help="Human review rationale"),
) -> None:
    """Record human review and transactionally promote or reject a verified repair."""
    if approve is None:
        raise typer.BadParameter("Choose exactly one of --approve or --reject.")
    result = RepairPromoter(SQLiteGraphStore(database)).decide(
        proposal,
        project,
        decision=ApprovalDecision.APPROVED if approve else ApprovalDecision.REJECTED,
        approved_by=approved_by,
        reason=reason,
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command("repair-reconcile")
def repair_reconcile(
    promotion: str = typer.Option(
        ..., "--promotion", help="Final-test-verified promotion ID"
    ),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
) -> None:
    """Idempotently reconcile a successful promotion into current graph memory."""
    result = PostRepairReconciler(SQLiteGraphStore(database)).reconcile(promotion)
    typer.echo(result.model_dump_json(indent=2))


def _maintenance_runner(
    database: Path, codex: str, model: str | None, sandbox: str
) -> MaintenanceWorkflowRunner:
    reader = CodexCliInvestigator(codex, model, DEFAULT_CODEX_SANDBOX)
    repairer = CodexCliInvestigator(codex, model, sandbox)
    return MaintenanceWorkflowRunner(
        SQLiteGraphStore(database), reader, reader, repairer
    )


@app.command("workflow-start")
def workflow_start(
    question: str = typer.Argument(..., help="Failing-test maintenance question"),
    project: Path = typer.Option(  # noqa: B008
        ..., "--project", exists=True, file_okay=False, dir_okay=True, resolve_path=True
    ),
    test: str = typer.Option(..., "--test", help="Indexed failing test path"),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(DEFAULT_CODEX_REPAIR_SANDBOX, help="Codex sandbox"),
) -> None:
    """Run or recover diagnosis and sandbox repair, then persist the approval pause."""
    result = _maintenance_runner(database, codex, model, sandbox).start(
        question, project, test
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command("workflow-resume")
def workflow_resume(
    workflow: str = typer.Option(..., "--workflow", help="Maintenance workflow ID"),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(DEFAULT_CODEX_REPAIR_SANDBOX, help="Codex sandbox"),
) -> None:
    """Resume from persisted artifacts without repeating completed workflow stages."""
    result = _maintenance_runner(database, codex, model, sandbox).advance(workflow)
    typer.echo(result.model_dump_json(indent=2))


@app.command("workflow-decide")
def workflow_decide(
    workflow: str = typer.Option(..., "--workflow", help="Maintenance workflow ID"),
    database: Path = typer.Option(..., "--database", help="Persistent graph database"),  # noqa: B008
    approve: bool | None = typer.Option(
        None, "--approve/--reject", help="Explicit human decision; omission is refused"
    ),
    approved_by: str = typer.Option(..., "--approved-by", help="Human reviewer identity"),
    reason: str = typer.Option(..., "--reason", help="Human review rationale"),
    codex: str = typer.Option("codex", help="Codex CLI executable"),
    model: str | None = typer.Option(None, help="Optional Codex model override"),
    sandbox: str = typer.Option(DEFAULT_CODEX_REPAIR_SANDBOX, help="Codex sandbox"),
) -> None:
    """Persist a human decision and continue the durable maintenance workflow."""
    if approve is None:
        raise typer.BadParameter("Choose exactly one of --approve or --reject.")
    result = _maintenance_runner(database, codex, model, sandbox).decide(
        workflow,
        decision=ApprovalDecision.APPROVED if approve else ApprovalDecision.REJECTED,
        approved_by=approved_by,
        reason=reason,
    )
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def run(
    question: str,
    project: Path = Path("."),
    database: Path = Path(".rlmgraph.db"),
    adapter_command: str = typer.Option(..., help="Executable that emits InvestigationResult JSON"),
) -> None:
    supervisor = Supervisor(SQLiteGraphStore(database), CodexCommandInvestigator([adapter_command]))
    typer.echo(supervisor.run(question, project).model_dump_json(indent=2))


@app.command()
def inspect(database: Path = Path(".rlmgraph.db")) -> None:
    store = SQLiteGraphStore(database)
    store.initialize()
    typer.echo(
        json.dumps(
            {
                "tasks": [task.model_dump(mode="json") for task in store.tasks()],
                "claims": [claim.model_dump(mode="json") for claim in store.claims()],
                "edges": [edge.model_dump(mode="json") for edge in store.edges()],
                "resolution_attempts": [
                    attempt.model_dump(mode="json")
                    for task in store.tasks()
                    for attempt in store.resolution_attempts(task.id)
                ],
                "projects": [item.model_dump(mode="json") for item in store.projects()],
                "project_scans": [
                    item.model_dump(mode="json") for item in store.project_scans()
                ],
                "project_files": [
                    item.model_dump(mode="json")
                    for item in store.project_files(include_deleted=True)
                ],
                "project_symbols": [
                    item.model_dump(mode="json") for item in store.project_symbols()
                ],
                "project_tests": [
                    item.model_dump(mode="json") for item in store.project_tests()
                ],
                "project_dependencies": [
                    item.model_dump(mode="json")
                    for item in store.project_dependencies()
                ],
                "repair_proposals": [
                    item.model_dump(mode="json") for item in store.repair_proposals()
                ],
                "repair_validations": [
                    item.model_dump(mode="json") for item in store.repair_validations()
                ],
                "repair_approvals": [
                    item.model_dump(mode="json") for item in store.repair_approvals()
                ],
                "repair_promotions": [
                    item.model_dump(mode="json") for item in store.repair_promotions()
                ],
                "post_repair_reconciliations": [
                    item.model_dump(mode="json")
                    for item in store.post_repair_reconciliations()
                ],
                "maintenance_workflows": [
                    item.model_dump(mode="json")
                    for item in store.maintenance_workflows()
                ],
                "project_leases": [
                    item.model_dump(mode="json") for item in store.project_leases()
                ],
                "evaluation_runs": [
                    item.model_dump(mode="json") for item in store.evaluation_runs()
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
