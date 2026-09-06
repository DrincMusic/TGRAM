import hashlib
import sys
from pathlib import Path

import pytest
from test_implementation_sandbox import ChangeWorker, fixture, reviewable_attempt, tree

from rlmgraph.implementation_sandbox import ImplementationSandboxManager
from rlmgraph.models import ValidationWorkerLimits, ValidationWorkerSpec
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.validation_workers import BoundedValidationRunner


def spec(
    category: str,
    artifact_kind: str,
    *,
    worker_id: str = "configured-worker",
    arguments: list[str] | None = None,
    limits: ValidationWorkerLimits | None = None,
) -> ValidationWorkerSpec:
    return ValidationWorkerSpec(
        id=worker_id,
        name=f"Configured {category}",
        categories=[category],
        artifact_kinds=[artifact_kind],
        executable=sys.executable,
        arguments=arguments
        or ["-c", "import pathlib,sys; assert pathlib.Path(sys.argv[1]).is_file()", "{path}"],
        limits=limits
        or ValidationWorkerLimits(
            max_wall_time_seconds=5,
            max_processes=4,
            max_memory_bytes=512 * 1024 * 1024,
            max_output_bytes=2_000,
            allowed_paths=["src/service.py"],
            allowed_artifact_kinds=[artifact_kind],
            allowed_executables=[str(Path(sys.executable).resolve())],
        ),
        authorized_by="test policy",
        authorization_reason="Deterministic bounded fixture worker.",
        estimated_cost_usd=0.01,
    )


@pytest.mark.parametrize(
    ("category", "artifact_kind"),
    [("COMPILE", "CPP_SOURCE"), ("COMPILE", "MODULE_RULES")],
)
def test_configured_cpp_and_module_workers_are_routed_and_persisted(
    tmp_path: Path, category: str, artifact_kind: str
) -> None:
    root, store, tickets, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category = category
    decision.artifact_kind = artifact_kind
    store.save_implementation_sandbox(attempt)
    worker = spec(category, artifact_kind)
    manager = ImplementationSandboxManager(store, ChangeWorker(), validation_workers=[worker])

    result = manager.run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)

    execution = result.validation_worker_executions[-1]
    assert execution.status == "PASSED"
    assert execution.authorization_status == "AUTHORIZED"
    assert execution.policy_id and execution.policy_version == 1
    assert execution.policy_rule_id == "WORKER-ALLOWLIST"
    assert execution.limits.allowed_paths == ["src/service.py"]
    assert execution.observed_processes <= execution.limits.max_processes
    assert execution.peak_memory_bytes <= execution.limits.max_memory_bytes
    assert execution.cost_usd == 0.01
    assert result.validation_decisions[0].status == "PASSED"
    assert tree(root) == original
    assert SQLiteGraphStore(store.path).implementation_sandboxes(ticket.id)[0] == result
    usage = tickets.get(ticket.id).usage
    assert usage.worker_calls == 3
    event_count = len(store.ticket_events(ticket.id))
    repeated = manager.run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)
    assert len(repeated.validation_worker_executions) == len(result.validation_worker_executions)
    assert len(store.ticket_events(ticket.id)) == event_count
    assert tickets.get(ticket.id).usage == usage


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        (lambda pid: (2, 1, []), "process-count"),
        (lambda pid: (1, 10_000, []), "memory limit"),
    ],
)
def test_runner_enforces_process_and_memory_limits(probe, expected: str, tmp_path: Path) -> None:
    limits = ValidationWorkerLimits(
        max_wall_time_seconds=2,
        max_processes=1,
        max_memory_bytes=100,
        max_output_bytes=100,
        allowed_paths=["x"],
        allowed_artifact_kinds=["PYTHON"],
        allowed_executables=[str(Path(sys.executable).resolve())],
    )
    result = BoundedValidationRunner(resource_probe=probe).execute(
        [sys.executable, "-c", "import time; time.sleep(1)"], tmp_path, limits
    )
    assert result.exit_code != 0
    assert expected in result.failure_reason


def test_runner_enforces_timeout_output_and_process_failure(tmp_path: Path) -> None:
    base = {
        "max_processes": 4,
        "max_memory_bytes": 512 * 1024 * 1024,
        "allowed_paths": ["x"],
        "allowed_artifact_kinds": ["PYTHON"],
        "allowed_executables": [str(Path(sys.executable).resolve())],
    }
    timeout = BoundedValidationRunner().execute(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        tmp_path,
        ValidationWorkerLimits(max_wall_time_seconds=0.05, max_output_bytes=100, **base),
    )
    assert "wall-time" in timeout.failure_reason
    output = BoundedValidationRunner().execute(
        [sys.executable, "-c", "print('x' * 500)"],
        tmp_path,
        ValidationWorkerLimits(max_wall_time_seconds=2, max_output_bytes=20, **base),
    )
    assert "output-size" in output.failure_reason and len(output.stdout.encode()) <= 20
    failed = BoundedValidationRunner().execute(
        [sys.executable, "-c", "raise SystemExit(7)"],
        tmp_path,
        ValidationWorkerLimits(max_wall_time_seconds=2, max_output_bytes=100, **base),
    )
    assert failed.exit_code == 7 and failed.failure_reason is None


def test_worker_rejects_wrong_path_artifact_executable_and_source_writes(tmp_path: Path) -> None:
    root, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category, decision.artifact_kind = "COMPILE", "CPP_SOURCE"
    store.save_implementation_sandbox(attempt)
    bad_limits = ValidationWorkerLimits(
        max_wall_time_seconds=2,
        max_processes=4,
        max_memory_bytes=512 * 1024 * 1024,
        max_output_bytes=100,
        allowed_paths=["tests/test_service.py"],
        allowed_artifact_kinds=["MODULE_RULES"],
        allowed_executables=["not-python"],
    )
    worker = spec("COMPILE", "CPP_SOURCE", limits=bad_limits)
    manager = ImplementationSandboxManager(store, ChangeWorker(), validation_workers=[worker])
    rejected = manager.run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)
    assert rejected.validation_worker_executions[-1].status == "REJECTED"
    assert rejected.validation_decisions[0].status == "REQUIRED"
    assert tree(root) == original


def test_worker_write_attempt_remains_unmet_and_never_touches_source(tmp_path: Path) -> None:
    root, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category, decision.artifact_kind = "COMPILE", "CPP_SOURCE"
    store.save_implementation_sandbox(attempt)
    write_worker = spec(
        "COMPILE",
        "CPP_SOURCE",
        arguments=["-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad')", "{path}"],
    )
    result = ImplementationSandboxManager(
        store, ChangeWorker(), validation_workers=[write_worker]
    ).run_validation_worker(ticket.id, attempt.id, decision.id, write_worker.id)
    assert result.validation_worker_executions[-1].status in {"FAILED", "REJECTED"}
    assert result.validation_decisions[0].status == "REQUIRED"
    assert tree(root) == original


@pytest.mark.parametrize(
    ("arguments", "wall_time", "expected"),
    [
        (["-c", "import time; time.sleep(1)", "{path}"], 0.05, "LIMIT_EXCEEDED"),
        (["-c", "raise SystemExit(7)", "{path}"], 2, "FAILED"),
    ],
)
def test_worker_timeout_and_process_failure_are_durably_unmet(
    tmp_path: Path, arguments: list[str], wall_time: float, expected: str
) -> None:
    _, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category, decision.artifact_kind = "COMPILE", "CPP_SOURCE"
    store.save_implementation_sandbox(attempt)
    limits = ValidationWorkerLimits(
        max_wall_time_seconds=wall_time,
        max_processes=4,
        max_memory_bytes=512 * 1024 * 1024,
        max_output_bytes=100,
        allowed_paths=[decision.path],
        allowed_artifact_kinds=["CPP_SOURCE"],
        allowed_executables=[str(Path(sys.executable).resolve())],
    )
    worker = spec("COMPILE", "CPP_SOURCE", arguments=arguments, limits=limits)
    result = ImplementationSandboxManager(
        store, ChangeWorker(), validation_workers=[worker]
    ).run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)
    execution = result.validation_worker_executions[-1]
    assert execution.status == expected
    assert execution.completed_at
    if expected == "LIMIT_EXCEEDED":
        assert execution.failure_reason
    assert result.validation_decisions[0].status == "REQUIRED"
    persisted = SQLiteGraphStore(store.path).implementation_sandboxes(ticket.id)[0]
    assert persisted.validation_worker_executions[-1] == execution


def test_ticket_budget_and_stale_source_block_worker_before_invocation(tmp_path: Path) -> None:
    root, store, tickets, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category, decision.artifact_kind = "COMPILE", "CPP_SOURCE"
    store.save_implementation_sandbox(attempt)
    worker = spec("COMPILE", "CPP_SOURCE")
    manager = ImplementationSandboxManager(store, ChangeWorker(), validation_workers=[worker])
    initial_execution_count = len(attempt.validation_worker_executions)
    exhausted = tickets.get(ticket.id)
    exhausted.usage.worker_calls = exhausted.budget.max_worker_calls
    store.save_project_ticket(exhausted)
    with pytest.raises(RuntimeError, match="worker-call"):
        manager.run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)
    assert (
        len(store.implementation_sandboxes(ticket.id)[0].validation_worker_executions)
        == initial_execution_count
    )
    assert tree(root) == original
    exhausted.usage.worker_calls -= 1
    store.save_project_ticket(exhausted)
    (root / "src/unrelated.py").write_text("DRIFT = True\n", encoding="utf-8")
    with pytest.raises(Exception, match="stale"):
        manager.run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)
    assert (root / "src/unrelated.py").read_text(encoding="utf-8") == "DRIFT = True\n"


def test_missing_worker_remains_an_unmet_requirement(tmp_path: Path) -> None:
    _, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    decision = next(item for item in attempt.validation_decisions if item.status == "REQUIRED")
    manager = ImplementationSandboxManager(store, ChangeWorker(), validation_workers=[])
    with pytest.raises(ValueError, match="unavailable"):
        manager.run_validation_worker(ticket.id, attempt.id, decision.id, "missing")
    persisted = store.implementation_sandboxes(ticket.id)[0]
    assert next(item for item in persisted.validation_decisions if item.id == decision.id).status == "REQUIRED"


def test_initial_validation_respects_projected_worker_budget_and_remains_unmet(tmp_path: Path) -> None:
    _, store, tickets, ticket, plan = fixture(tmp_path)
    tickets.approve_plan(ticket.id, plan.id, actor="reviewer", reason="Reviewed.")
    budgeted = tickets.get(ticket.id)
    budgeted.budget.max_worker_calls = 1
    store.save_project_ticket(budgeted)
    attempt = ImplementationSandboxManager(store, ChangeWorker()).run(ticket.id, plan.id)
    decision = next(item for item in attempt.validation_decisions if item.path == "tests/test_service.py")
    assert decision.status == "REQUIRED"
    assert "worker-call budget" in decision.evidence[-1].detail
    assert tickets.get(ticket.id).usage.worker_calls == 1


def test_external_unreal_report_import_is_scoped_current_integrity_checked_and_idempotent(
    tmp_path: Path,
) -> None:
    root, store, _, ticket, _, manager, attempt = reviewable_attempt(tmp_path)
    original = tree(root)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category = "UNREAL_EDITOR"
    decision.artifact_kind = "ASSET"
    decision.requires_unreal_editor = True
    store.save_implementation_sandbox(attempt)
    report_bytes = b'{"artifact":"src/service.py","result":"passed"}'
    digest = hashlib.sha256(report_bytes).hexdigest()
    patch = manager._patch_sha256(attempt)

    result = manager.import_external_validation_report(
        ticket.id,
        attempt.id,
        decision.id,
        actor="Editor validator",
        report_kind="UNREAL_EDITOR",
        artifact_path=decision.path,
        source_manifest_sha256=attempt.initial_manifest_sha256,
        patch_sha256=patch,
        report_bytes=report_bytes,
        report_sha256=digest,
        status="PASSED",
        detail="External Editor validation passed without granting launch authority.",
    )
    assert result.validation_decisions[0].status == "SATISFIED"
    assert result.external_validation_reports[0].recorded_by == "Editor validator"
    event_count = len(store.ticket_events(ticket.id))
    repeated = manager.import_external_validation_report(
        ticket.id, attempt.id, decision.id, actor="Editor validator",
        report_kind="UNREAL_EDITOR", artifact_path=decision.path,
        source_manifest_sha256=attempt.initial_manifest_sha256, patch_sha256=patch,
        report_bytes=report_bytes, report_sha256=digest, status="PASSED", detail="same",
    )
    assert len(repeated.external_validation_reports) == 1
    assert len(store.ticket_events(ticket.id)) == event_count
    assert tree(root) == original
    for overrides, match in [
        ({"artifact_path": "tests/test_service.py"}, "authorized artifact scope"),
        ({"source_manifest_sha256": "stale"}, "source manifest is stale"),
        ({"patch_sha256": "stale"}, "patch identity is stale"),
    ]:
        parameters = {
            "actor": "Editor validator",
            "report_kind": "UNREAL_EDITOR",
            "artifact_path": decision.path,
            "source_manifest_sha256": attempt.initial_manifest_sha256,
            "patch_sha256": patch,
            "report_bytes": b"another report",
            "report_sha256": hashlib.sha256(b"another report").hexdigest(),
            "status": "PASSED",
            "detail": "scoped report",
            **overrides,
        }
        with pytest.raises(Exception, match=match):
            manager.import_external_validation_report(
                ticket.id, attempt.id, decision.id, **parameters
            )
    with pytest.raises(ValueError, match="integrity"):
        manager.import_external_validation_report(
            ticket.id, attempt.id, decision.id, actor="Editor validator",
            report_kind="UNREAL_EDITOR", artifact_path=decision.path,
            source_manifest_sha256=attempt.initial_manifest_sha256, patch_sha256=patch,
            report_bytes=b"different", report_sha256=digest, status="PASSED", detail="bad",
        )
    bounded = ImplementationSandboxManager(
        store, ChangeWorker(), max_external_report_bytes=10
    )
    with pytest.raises(ValueError, match="size limit"):
        bounded.import_external_validation_report(
            ticket.id, attempt.id, decision.id, actor="Editor validator",
            report_kind="UNREAL_EDITOR", artifact_path=decision.path,
            source_manifest_sha256=attempt.initial_manifest_sha256, patch_sha256=patch,
            report_bytes=b"more than ten bytes", report_sha256=hashlib.sha256(b"more than ten bytes").hexdigest(),
            status="PASSED", detail="oversized",
        )


def test_neo4j_serializes_worker_executions_and_external_reports(tmp_path: Path) -> None:
    _, store, _, ticket, _, _, attempt = reviewable_attempt(tmp_path)
    decision = next(item for item in attempt.validation_decisions if item.path == "src/service.py")
    decision.category, decision.artifact_kind = "COMPILE", "CPP_SOURCE"
    store.save_implementation_sandbox(attempt)
    worker = spec("COMPILE", "CPP_SOURCE")
    attempt = ImplementationSandboxManager(
        store, ChangeWorker(), validation_workers=[worker]
    ).run_validation_worker(ticket.id, attempt.id, decision.id, worker.id)

    class RecordingDriver:
        def __init__(self):
            self.calls = []

        def execute_query(self, query, **parameters):
            self.calls.append((query, parameters))
            return [], None, None

    neo = object.__new__(Neo4jGraphStore)
    neo.driver = RecordingDriver()
    neo.save_implementation_sandbox(attempt)
    payload = next(parameters["payload"] for _, parameters in neo.driver.calls if "attempt.payload" in _)
    assert '"validation_worker_executions"' in payload
    assert '"external_validation_reports"' in payload
    assert '"configured-worker"' in payload
