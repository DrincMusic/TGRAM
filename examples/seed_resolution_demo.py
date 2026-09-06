"""Seed two intentionally conflicting claims for the live resolution demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rlmgraph.models import Assertion, Evidence, InvestigationResult
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor

KEY = "discounted_price.discount_percent.interpretation"


class DemoInvestigator:
    def __init__(self) -> None:
        self.results = iter(
            [
                InvestigationResult(
                    conclusion="discount_percent is applied as a percentage of price.",
                    confidence=0.7,
                    evidence=[
                        Evidence(
                            path="test_widget.py",
                            line=9,
                            detail="The test expects 10 percent off 50 to equal 45.",
                        )
                    ],
                    files_examined=["widget.py", "test_widget.py"],
                    assertions=[Assertion(key=KEY, value="percentage")],
                ),
                InvestigationResult(
                    conclusion="discount_percent is subtracted as a fixed amount.",
                    confidence=0.9,
                    evidence=[
                        Evidence(
                            path="widget.py",
                            line=3,
                            detail="The function returns price - discount_percent.",
                        )
                    ],
                    files_examined=["widget.py", "test_widget.py"],
                    assertions=[Assertion(key=KEY, value="fixed amount")],
                ),
            ]
        )

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        return next(self.results)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    supervisor = Supervisor(SQLiteGraphStore(args.database), DemoInvestigator())
    question = "How is discount_percent interpreted by discounted_price?"
    first = supervisor.run(question, args.project)
    second = supervisor.run(question, args.project, force_investigation=True)
    print(
        json.dumps(
            {
                "left_claim_id": first.claim.id,
                "right_claim_id": second.claim.id,
                "root_task_id": second.task.id,
                "resolution_task_id": second.resolution_tasks[0].id,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
