"""Live proof that recursive graph memory adds durable behavior over a direct call."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from rlmgraph.adapters import CodexCliInvestigator
from rlmgraph.recursive_investigation import RecursiveInvestigationSupervisor
from rlmgraph.store import SQLiteGraphStore

ROOT = Path(__file__).resolve().parents[1]
QUESTION = (
    "Does RLMGraph autonomously create or execute self-improvement work after finding a "
    "weakness? Identify the exact implemented boundaries, seek counterevidence, and distinguish "
    "runtime-enforced behavior from documentation claims."
)


def evidence_paths(result) -> list[str]:
    return sorted({item.path for item in result.evidence})


def main() -> None:
    investigator = CodexCliInvestigator()
    direct = investigator.investigate(QUESTION, ROOT)

    with tempfile.TemporaryDirectory(
        prefix="rlmgraph-live-recursion-", ignore_cleanup_errors=True
    ) as directory:
        database = Path(directory) / "memory.db"
        first_store = SQLiteGraphStore(database)
        first_store.initialize()
        first = RecursiveInvestigationSupervisor(first_store, investigator).run(QUESTION, ROOT)

        # Reconstruct every service object to prove reuse comes from durable graph state.
        restarted_store = SQLiteGraphStore(database)
        restarted_store.initialize()
        restarted = RecursiveInvestigationSupervisor(restarted_store, investigator).run(
            QUESTION, ROOT
        )

        checks = {
            "decomposed": len(first.sub_tasks) >= 2,
            "synthesis_tracks_branch_claims": (
                first.claim.source_claim_ids == [claim.id for claim in first.finding_claims]
            ),
            "task_tree_persisted": all(
                restarted_store.get_task(task.id) is not None for task in first.sub_tasks
            ),
            "restart_reused_every_branch": restarted.cache_hit,
            "restart_used_fewer_model_calls": (
                restarted.investigation_calls < first.investigation_calls
            ),
            "reused_claim_ids_are_exact": (
                [claim.id for claim in restarted.finding_claims]
                == [claim.id for claim in first.finding_claims]
            ),
            "recursive_evidence_not_narrower_than_direct": (
                len({item.path for claim in first.finding_claims for item in claim.evidence})
                >= len(evidence_paths(direct))
            ),
        }
        report = {
            "question": QUESTION,
            "baseline": {
                "calls": 1,
                "confidence": direct.confidence,
                "evidence_paths": evidence_paths(direct),
                "conclusion": direct.conclusion,
            },
            "recursive_fresh": {
                "calls": first.investigation_calls,
                "subtasks": len(first.sub_tasks),
                "depth": max(task.depth for task in first.sub_tasks),
                "conflicts": len(first.conflicts),
                "evidence_paths": sorted(
                    {item.path for claim in first.finding_claims for item in claim.evidence}
                ),
                "conclusion": first.claim.conclusion,
            },
            "recursive_after_restart": {
                "calls": restarted.investigation_calls,
                "cache_hit": restarted.cache_hit,
                "reuse_type": restarted.reuse_type,
                "reused_claim_ids": [claim.id for claim in restarted.finding_claims],
            },
            "checks": checks,
            "passed": all(checks.values()),
        }
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise SystemExit("live recursive-memory proof failed")


if __name__ == "__main__":
    main()
