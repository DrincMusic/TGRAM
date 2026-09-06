"""Durable WAITING_FOR_APPROVAL -> resume -> COMPLETED workflow proof."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from graph_debugging_demo import BoundedFixtureWorker, FixtureSynthesizer, prepare
from repair_validation_demo import FixtureRepairWorker, clear_observer_fixture

from rlmgraph.models import ApprovalDecision
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.store import Neo4jGraphStore, SQLiteGraphStore
from rlmgraph.workflow import MaintenanceWorkflowRunner

QUESTION = "Why does test_discounted fail?"
TEST_PATH = "tests/test_pricing.py"


def new_runner(store):
    return MaintenanceWorkflowRunner(
        store,
        BoundedFixtureWorker(),
        FixtureSynthesizer(),
        FixtureRepairWorker(),
    )


def execute(store, project: Path) -> dict[str, object]:
    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project))
    waiting = new_runner(store).start(QUESTION, project, TEST_PATH)
    assert waiting.status.value == "WAITING_FOR_APPROVAL"
    before_resume = {
        "tasks": len(store.tasks()),
        "proposals": len(store.repair_proposals()),
        "validations": len(store.repair_validations()),
    }
    waiting_again = new_runner(store).start(QUESTION, project, TEST_PATH)
    after_resume = {
        "tasks": len(store.tasks()),
        "proposals": len(store.repair_proposals()),
        "validations": len(store.repair_validations()),
    }
    assert waiting_again.id == waiting.id and before_resume == after_resume
    completed = new_runner(store).decide(
        waiting.id,
        decision=ApprovalDecision.APPROVED,
        approved_by="deterministic-workflow-reviewer",
        reason="Reviewed the persisted sandbox patch and before/after test proof.",
    )
    terminal_counts = {
        "tasks": len(store.tasks()),
        "proposals": len(store.repair_proposals()),
        "validations": len(store.repair_validations()),
        "approvals": len(store.repair_approvals()),
        "promotions": len(store.repair_promotions()),
        "reconciliations": len(store.post_repair_reconciliations()),
    }
    replay = new_runner(store).advance(completed.id)
    assert replay == completed
    assert terminal_counts == {
        "tasks": len(store.tasks()),
        "proposals": len(store.repair_proposals()),
        "validations": len(store.repair_validations()),
        "approvals": len(store.repair_approvals()),
        "promotions": len(store.repair_promotions()),
        "reconciliations": len(store.post_repair_reconciliations()),
    }
    lease = next(
        item for item in store.project_leases()
        if Path(item.project_root).resolve() == project.resolve()
    )
    return {
        "workflow_id": completed.id,
        "status_before_decision": waiting.status.value,
        "status_after_decision": completed.status.value,
        "artifact_ids": {
            "diagnosis_task": completed.diagnosis_task_id,
            "diagnosis_claim": completed.diagnosis_claim_id,
            "proposal": completed.proposal_id,
            "sandbox_validation": completed.sandbox_validation_id,
            "approval": completed.approval_id,
            "promotion": completed.promotion_id,
            "reconciliation": completed.reconciliation_id,
            "follow_up_task": completed.follow_up_task_id,
            "follow_up_claim": completed.follow_up_claim_id,
        },
        "worker_calls": {
            "diagnosis": completed.diagnosis_worker_calls,
            "repair": completed.repair_worker_calls,
            "follow_up": completed.follow_up_worker_calls,
        },
        "resume_created_no_artifacts": before_resume == after_resume,
        "terminal_resume_created_no_artifacts": True,
        "events": [item.model_dump(mode="json") for item in completed.events],
        "lease": lease.model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observer", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).parent / "onboarding_fixture"
    if args.observer:
        generated = (Path(__file__).parents[1] / ".rlmgraph").resolve()
        project = generated / "maintenance-workflow-demo"
        if project.parent != generated or project.name != "maintenance-workflow-demo":
            raise RuntimeError(f"Refusing to replace unexpected path: {project}")
        if project.exists():
            shutil.rmtree(project)
        prepare(source, project)
        store = Neo4jGraphStore("bolt://localhost:7687", "neo4j", "rlmgraph-demo")
        store.initialize()
        clear_observer_fixture(store, project)
        result = execute(store, project)
    else:
        with TemporaryDirectory(prefix="rlmgraph-workflow-demo-") as directory:
            workspace = Path(directory)
            project = workspace / "project"
            prepare(source, project)
            result = execute(SQLiteGraphStore(workspace / "graph.db"), project)
            gc.collect()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
