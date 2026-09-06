"""Deterministic FAIL -> DIAGNOSE -> PATCH -> TEST -> VERIFIED proof."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from graph_debugging_demo import (
    BoundedFixtureWorker,
    FixtureSynthesizer,
    prepare,
)

from rlmgraph.graph_debugging import GraphDirectedDebugger
from rlmgraph.models import ApprovalDecision, Claim, RepairWorkerResult
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.promotion import RepairPromoter
from rlmgraph.repair import SandboxedRepairValidator
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore


class FixtureRepairWorker:
    def __init__(self) -> None:
        self.calls = 0

    def repair(
        self, question: str, diagnosis: Claim, project_root: Path
    ) -> RepairWorkerResult:
        self.calls += 1
        target = project_root / "tests" / "test_pricing.py"
        target.write_text(target.read_text().replace("== 91", "== 90"))
        return RepairWorkerResult(
            rationale="Replace the stale expected value with the diagnosed result.",
            confidence=0.99,
            files_changed=["tests/test_pricing.py"],
            model_calls=1,
        )


def clear_observer_fixture(store: Neo4jGraphStore, root: Path) -> None:
    project_ids = [
        item.id for item in store.projects() if Path(item.root).resolve() == root.resolve()
    ]
    tasks = [
        item for item in store.tasks() if Path(item.project_root).resolve() == root.resolve()
    ]
    task_ids = [item.id for item in tasks]
    claim_ids = [
        item.id
        for item in store.claims()
        if item.project_root and Path(item.project_root).resolve() == root.resolve()
    ]
    proposals = [
        item for item in store.repair_proposals() if item.repair_task_id in task_ids
    ]
    proposal_ids = [item.id for item in proposals]
    validation_ids = [
        item.id
        for item in store.repair_validations()
        if item.proposal_id in proposal_ids
    ]
    approval_ids = [
        item.id for item in store.repair_approvals() if item.proposal_id in proposal_ids
    ]
    promotion_ids = [
        item.id for item in store.repair_promotions() if item.proposal_id in proposal_ids
    ]
    reconciliation_ids = [
        item.id
        for item in store.post_repair_reconciliations()
        if item.promotion_id in promotion_ids
    ]
    workflow_ids = [
        item.id
        for item in store.maintenance_workflows()
        if Path(item.project_root).resolve() == root.resolve()
    ]
    lease_ids = [
        item.id
        for item in store.project_leases()
        if Path(item.project_root).resolve() == root.resolve()
    ]
    ids = [
        *project_ids,
        *task_ids,
        *claim_ids,
        *proposal_ids,
        *validation_ids,
        *approval_ids,
        *promotion_ids,
        *reconciliation_ids,
        *workflow_ids,
        *lease_ids,
    ]
    if ids or project_ids:
        store.driver.execute_query(
            "MATCH (n) WHERE n.id IN $ids OR n.project_id IN $project_ids DETACH DELETE n",
            ids=ids,
            project_ids=project_ids,
        )


def execute(store, project: Path) -> dict[str, object]:
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    debug = GraphDirectedDebugger(
        store, BoundedFixtureWorker(), FixtureSynthesizer()
    ).debug("Why does test_discounted fail?", project, "tests/test_pricing.py")
    original = {
        item.relative_to(project).as_posix(): item.read_bytes()
        for item in project.rglob("*")
        if item.is_file()
    }
    worker = FixtureRepairWorker()
    validator = SandboxedRepairValidator(store, worker)
    repair = validator.validate(debug.diagnosis.id, "tests/test_pricing.py")
    replay = validator.validate(debug.diagnosis.id, "tests/test_pricing.py")
    after = {
        item.relative_to(project).as_posix(): item.read_bytes()
        for item in project.rglob("*")
        if item.is_file()
    }
    assert repair.validation.before.exit_code != 0
    assert repair.validation.after.exit_code == 0
    assert repair.validation.original_unchanged and original == after
    assert replay.reused and replay.worker_calls == 0 and worker.calls == 1
    promotion = RepairPromoter(store).decide(
        repair.proposal.id,
        project,
        decision=ApprovalDecision.APPROVED,
        approved_by="deterministic-demo-reviewer",
        reason="Exact diff and sandbox before/after proof reviewed for the isolated fixture.",
    )
    assert promotion.promotion is not None
    assert promotion.promotion.status.value == "VERIFIED"
    reconciliation = store.post_repair_reconciliations(promotion.promotion.id)[0]
    assert reconciliation.parsed_paths == ["tests/test_pricing.py"]
    assert reconciliation.follow_up_worker_calls == 0
    return {
        "diagnosis": {
            "task_id": debug.root_task.id,
            "claim_id": debug.diagnosis.id,
            "conclusion": debug.diagnosis.conclusion,
            "supporting_claim_ids": debug.diagnosis.source_claim_ids,
        },
        "repair": {
            "task_id": repair.repair_task.id,
            "proposal_id": repair.proposal.id,
            "authorized_paths": repair.proposal.authorized_paths,
            "files_changed": [item.path for item in repair.proposal.changes],
            "unified_diff": repair.proposal.changes[0].unified_diff,
            "confidence": repair.proposal.confidence,
            "worker_calls": repair.worker_calls,
            "model_calls": repair.model_calls,
        },
        "validation": {
            "id": repair.validation.id,
            "status": repair.validation.status.value,
            "command": repair.validation.before.command,
            "before_exit_code": repair.validation.before.exit_code,
            "after_exit_code": repair.validation.after.exit_code,
            "before_output": repair.validation.before.stdout,
            "after_output": repair.validation.after.stdout,
            "original_unchanged": repair.validation.original_unchanged,
        },
        "replay": {
            "reused_validation_id": replay.validation.id,
            "worker_calls": replay.worker_calls,
            "model_calls": replay.model_calls,
        },
        "promotion": {
            "approval_id": promotion.approval.id,
            "decision": promotion.approval.decision.value,
            "approved_by": promotion.approval.approved_by,
            "promotion_id": promotion.promotion.id,
            "status": promotion.promotion.status.value,
            "final_exit_code": promotion.promotion.final_validation.exit_code,
            "events": [
                item.model_dump(mode="json") for item in promotion.promotion.events
            ],
            "real_project_changed_only_after_approval": (
                "== 90" in (project / "tests" / "test_pricing.py").read_text()
            ),
        },
        "reconciliation": reconciliation.model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).parent / "onboarding_fixture"
    if args.observer:
        generated = (Path(__file__).parents[1] / ".rlmgraph").resolve()
        project = generated / "sandboxed-repair-demo"
        if project.parent != generated or project.name != "sandboxed-repair-demo":
            raise RuntimeError(f"Refusing to replace unexpected path: {project}")
        if project.exists():
            shutil.rmtree(project)
        prepare(source, project)
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        store.initialize()
        clear_observer_fixture(store, project)
        result = execute(store, project)
    else:
        with TemporaryDirectory(prefix="rlmgraph-repair-demo-") as directory:
            workspace = Path(directory)
            project = workspace / "project"
            prepare(source, project)
            result = execute(SQLiteGraphStore(workspace / "graph.db"), project)
            gc.collect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
