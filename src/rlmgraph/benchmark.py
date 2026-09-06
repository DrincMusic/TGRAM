from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from .fingerprint import project_fingerprint, task_fingerprint
from .models import (
    BenchmarkOutcome,
    BenchmarkRun,
    Claim,
    ReconstructionAction,
    StoppingReason,
    Task,
    TaskStatus,
)
from .reconstruction import ActiveMemoryReconstructor, count_o200k_tokens
from .store import GraphStore


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    question: str
    project_root: Path
    claims: list[Claim]
    expected_answer: str
    answer_claim_id: str
    required_evidence_ids: list[str]
    minimum_reduction: float = 0.5


class MemoryBenchmarkRunner:
    """Compare complete fixed context with active graph reconstruction deterministically."""

    def __init__(self, store: GraphStore, reconstructor: ActiveMemoryReconstructor | None = None):
        self.store = store
        self.store.initialize()
        self.reconstructor = reconstructor or ActiveMemoryReconstructor(store, seed_count=1)

    @staticmethod
    def _input_payload(question: str, claims: list[Claim]) -> dict[str, object]:
        return {
            "question": question,
            "claims": [
                {
                    "id": claim.id,
                    "subject": claim.subject,
                    "conclusion": claim.conclusion,
                    "confidence": claim.confidence,
                    "evidence": [item.model_dump(mode="json") for item in claim.evidence],
                    "files_examined": claim.files_examined,
                    "assertions": [
                        item.model_dump(mode="json") for item in claim.assertions
                    ],
                    "source_claim_ids": claim.source_claim_ids,
                    "memory_tier": claim.memory_tier.value,
                    "validity_status": claim.validity_status.value,
                }
                for claim in sorted(claims, key=lambda item: item.id)
            ],
        }

    @staticmethod
    def _duplicates(node_ids: list[str]) -> int:
        return len(node_ids) - len(set(node_ids))

    def _evaluate(
        self,
        case: BenchmarkCase,
        context: list[Claim],
        started_at: float,
    ) -> BenchmarkOutcome:
        by_id = {claim.id: claim for claim in context}
        evidence_complete = set(case.required_evidence_ids).issubset(by_id)
        answer_claim = by_id.get(case.answer_claim_id)
        answer = answer_claim.conclusion if answer_claim and evidence_complete else "INSUFFICIENT_EVIDENCE"
        input_tokens = count_o200k_tokens(self._input_payload(case.question, context))
        output_tokens = count_o200k_tokens({"answer": answer})
        node_ids = [claim.id for claim in context]
        return BenchmarkOutcome(
            answer=answer,
            correct=answer == case.expected_answer,
            evidence_complete=evidence_complete,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            wall_time_ms=(perf_counter() - started_at) * 1000,
            context_node_ids=node_ids,
            accessed_evidence_ids=[
                node_id for node_id in case.required_evidence_ids if node_id in by_id
            ],
            duplicate_retrievals=self._duplicates(node_ids),
        )

    def run(self, case: BenchmarkCase) -> BenchmarkRun:
        state = project_fingerprint(case.project_root)
        task = Task.create(
            case.question,
            case.project_root,
            task_fingerprint(case.question, state),
            state,
        )
        self.store.save_task(task)
        for claim in case.claims:
            self.store.save_claim(task, claim)

        fixed_started = perf_counter()
        fixed = self._evaluate(case, case.claims, fixed_started)

        active_started = perf_counter()
        reconstruction = self.reconstructor.reconstruct(
            task,
            case.claims,
            required_evidence_ids=case.required_evidence_ids,
        )
        active_context = [
            claim for claim in case.claims if claim.id in reconstruction.selected_node_ids
        ]
        active = self._evaluate(case, active_context, active_started)
        self.store.save_reconstruction(reconstruction)
        task.status = TaskStatus.DONE
        task.stopping_reason = StoppingReason.COMPLETED
        task.completed_at = datetime.now(UTC)
        self.store.save_task(task)

        reduction = (
            1 - active.input_tokens / fixed.input_tokens if fixed.input_tokens else 0.0
        )
        traversal_node_ids = [
            step.node_id
            for step in reconstruction.steps
            if step.action != ReconstructionAction.PRUNE
        ]
        run = BenchmarkRun(
            task_id=task.id,
            reconstruction_id=reconstruction.id,
            case_id=case.id,
            project_root=str(case.project_root.resolve()),
            question=case.question,
            expected_answer=case.expected_answer,
            required_evidence_ids=case.required_evidence_ids,
            fixed=fixed,
            active=active,
            traversal_node_ids=traversal_node_ids,
            traversal_edges=reconstruction.context_edges,
            token_reduction=reduction,
            correctness_preserved=fixed.correct and active.correct,
            evidence_preserved=fixed.evidence_complete and active.evidence_complete,
            passed=(
                reduction >= case.minimum_reduction
                and fixed.correct
                and active.correct
                and fixed.evidence_complete
                and active.evidence_complete
            ),
        )
        self.store.save_benchmark_run(run)
        return run
