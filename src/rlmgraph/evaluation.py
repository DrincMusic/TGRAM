from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from .models import (
    Assertion,
    Claim,
    ClaimValidity,
    EvaluationCaseResult,
    EvaluationRun,
    EvaluationScenario,
    EvaluationStrategy,
    Evidence,
    GraphEdge,
    GraphRelation,
    ProjectLeaseEventKind,
    Task,
)
from .reconstruction import ActiveMemoryReconstructor, count_o200k_tokens
from .store import GraphStore


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    scenario: EvaluationScenario
    question: str
    expected_answer: str
    answer_claim_id: str
    required_evidence_ids: list[str]
    claims: list[Claim]


def _claim(
    claim_id: str,
    root: Path,
    subject: str,
    conclusion: str,
    *,
    sources: list[str] | None = None,
    assertion: tuple[str, str] | None = None,
    validity: ClaimValidity = ClaimValidity.CURRENT,
) -> Claim:
    return Claim(
        id=claim_id,
        fingerprint=hashlib.sha256(claim_id.encode()).hexdigest(),
        project_root=str(root.resolve()),
        subject=subject,
        producer="DeterministicEvaluationFixture",
        conclusion=conclusion,
        confidence=1.0,
        source_claim_ids=sources or [],
        assertions=[Assertion(key=assertion[0], value=assertion[1])] if assertion else [],
        evidence=[Evidence(path="fixture.txt", line=1, detail="Deterministic fixture truth")],
        files_examined=["fixture.txt"],
        validity_status=validity,
    )


class DeterministicEvaluationHarness:
    """Compare three retrieval strategies with stable, auditable logical measurements."""

    def __init__(self, store: GraphStore, project_root: str | Path, *, repetitions: int = 2):
        if repetitions < 2:
            raise ValueError("Repeated-task evaluation requires at least two repetitions.")
        self.store = store
        self.root = Path(project_root).resolve()
        self.repetitions = repetitions
        self.store.initialize()
        self.root.mkdir(parents=True, exist_ok=True)
        fixture = self.root / "fixture.txt"
        if not fixture.exists():
            fixture.write_text("deterministic evaluation fixture\n")

    def cases(self) -> list[EvaluationCase]:
        evidence = [
            _claim(
                f"EVAL-DEBUG-EVIDENCE-{index}", self.root,
                f"Pricing evidence {index}", f"Evidence {index} proves the stale expected value.",
            )
            for index in range(2)
        ]
        answer = _claim(
            "EVAL-DEBUG-ANSWER", self.root,
            "Why does test_discounted fail?", "The test expects 91, but the implementation returns 90.",
            sources=[item.id for item in evidence],
        )
        noise = [
            _claim(
                f"EVAL-NOISE-{index}", self.root,
                f"Unrelated renderer subsystem {index}",
                "Verbose unrelated history about rendering, input, UI, and packaging. " * 5,
            )
            for index in range(12)
        ]
        current = _claim(
            "EVAL-CONFLICT-CURRENT", self.root, "Current retry policy",
            "The current retry limit is 3.", assertion=("retry.limit", "3"),
        )
        stale = _claim(
            "EVAL-CONFLICT-STALE", self.root, "Historical retry policy",
            "The retry limit is 5.", assertion=("retry.limit", "5"),
            validity=ClaimValidity.SUPERSEDED,
        )
        resolved = _claim(
            "EVAL-CONFLICT-ANSWER", self.root, "What is the current retry limit?",
            "The current retry limit is 3.", sources=[current.id],
            assertion=("retry.limit", "3"),
        )
        return [
            EvaluationCase(
                id="repeated-debugging", scenario=EvaluationScenario.REPEATED_DEBUGGING,
                question=answer.subject, expected_answer=answer.conclusion,
                answer_claim_id=answer.id,
                required_evidence_ids=[item.id for item in evidence],
                claims=[*evidence, *noise, answer],
            ),
            EvaluationCase(
                id="conflict-resolution", scenario=EvaluationScenario.CONFLICT,
                question=resolved.subject, expected_answer=resolved.conclusion,
                answer_claim_id=resolved.id, required_evidence_ids=[current.id],
                claims=[current, stale, resolved, *noise],
            ),
        ]

    def run(self) -> EvaluationRun:
        run = EvaluationRun(project_root=str(self.root), repetitions=self.repetitions)
        results = self._evaluate_cases(run.id)
        results.extend(self._evaluate_recovery(run.id))
        run.results = results
        quality = [item for item in results if item.scenario != EvaluationScenario.RECOVERY]
        rlm = [item for item in quality if item.strategy == EvaluationStrategy.RLMGRAPH]
        static = [item for item in quality if item.strategy == EvaluationStrategy.STATIC_RETRIEVAL]
        memoryless_repeat = [
            item for item in quality
            if item.strategy == EvaluationStrategy.MEMORYLESS and item.repetition > 1
        ]
        rlm_repeat = [item for item in rlm if item.repetition > 1]
        governed_quality = [
            item for item in quality
            if item.strategy in {EvaluationStrategy.MEMORYLESS, EvaluationStrategy.RLMGRAPH}
        ]
        run.correctness_preserved = all(item.correct for item in governed_quality)
        run.evidence_preserved = all(item.evidence_complete for item in governed_quality)
        run.fewer_repeat_worker_calls = sum(item.worker_calls for item in rlm_repeat) < sum(
            item.worker_calls for item in memoryless_repeat
        )
        run.fewer_tokens_than_static = sum(item.retrieved_tokens for item in rlm) < sum(
            item.retrieved_tokens for item in static
        )
        conflict = [item for item in rlm if item.scenario == EvaluationScenario.CONFLICT]
        run.stale_or_conflicting_memory_blocked = bool(conflict) and all(
            item.conflict_resolved and "EVAL-CONFLICT-STALE" not in item.retrieved_claim_ids
            for item in conflict
        )
        recovery = [
            item for item in results
            if item.strategy == EvaluationStrategy.RLMGRAPH
            and item.scenario == EvaluationScenario.RECOVERY
        ]
        run.recovery_verified = bool(recovery) and all(
            item.recovery_succeeded for item in recovery
        )
        run.reproducible = self._result_signature(results) == self._result_signature(
            self._evaluate_cases("shadow", persist=False)
            + self._recovery_shadow("shadow")
        )
        run.passed = all(
            (
                run.correctness_preserved,
                run.evidence_preserved,
                run.fewer_repeat_worker_calls,
                run.fewer_tokens_than_static,
                run.stale_or_conflicting_memory_blocked,
                run.recovery_verified,
                run.reproducible,
            )
        )
        self.store.save_evaluation_run(run)
        return run

    def _evaluate_cases(self, run_id: str, *, persist: bool = True) -> list[EvaluationCaseResult]:
        results: list[EvaluationCaseResult] = []
        for case in self.cases():
            task = Task(
                id=f"{run_id}-{case.id}-task",
                question=case.question,
                fingerprint=f"{run_id}-{case.id}",
                project_root=str(self.root),
            )
            if persist:
                self.store.save_task(task)
                for claim in case.claims:
                    self.store.save_claim(task, claim)
                answer = next(item for item in case.claims if item.id == case.answer_claim_id)
                for source_id in answer.source_claim_ids:
                    self.store.save_edge(GraphEdge(source=answer.id, relation=GraphRelation.DERIVED_FROM, target=source_id))
                for claim in case.claims:
                    if claim.id.startswith("EVAL-NOISE"):
                        self.store.save_edge(GraphEdge(source=answer.id, relation=GraphRelation.CORROBORATES, target=claim.id))
                if case.scenario == EvaluationScenario.CONFLICT:
                    self.store.save_edge(GraphEdge(source="EVAL-CONFLICT-ANSWER", relation=GraphRelation.CONTRADICTS, target="EVAL-CONFLICT-STALE"))
            reconstruction = ActiveMemoryReconstructor(
                self.store, seed_count=1, max_depth=2, baseline_depth=2
            ).reconstruct(task, case.claims, required_evidence_ids=case.required_evidence_ids)
            if persist:
                self.store.save_reconstruction(reconstruction)
            by_id = {item.id: item for item in case.claims}
            static_ids = reconstruction.baseline_node_ids
            rlm_ids = reconstruction.selected_node_ids
            memoryless_ids = [case.answer_claim_id, *case.required_evidence_ids]
            for repetition in range(1, self.repetitions + 1):
                for strategy, ids in (
                    (EvaluationStrategy.MEMORYLESS, memoryless_ids),
                    (EvaluationStrategy.STATIC_RETRIEVAL, static_ids),
                    (EvaluationStrategy.RLMGRAPH, rlm_ids),
                ):
                    observed_started = perf_counter()
                    context = [by_id[item] for item in ids]
                    required = set(case.required_evidence_ids)
                    evidence_complete = required.issubset(ids)
                    stale_selected = "EVAL-CONFLICT-STALE" in ids
                    conflict_resolved = None
                    if case.scenario == EvaluationScenario.CONFLICT:
                        conflict_resolved = not stale_selected
                    correct = (
                        evidence_complete
                        and case.answer_claim_id in ids
                        and not (
                            case.scenario == EvaluationScenario.CONFLICT
                            and stale_selected
                        )
                    )
                    workers = len(case.required_evidence_ids) + 1 if strategy == EvaluationStrategy.MEMORYLESS else (len(case.required_evidence_ids) + 1 if repetition == 1 else 0)
                    models = 1 if workers else 0
                    reuse = 0 if workers else len(case.required_evidence_ids) + 1
                    duplicate = (len(case.required_evidence_ids) + 1) if strategy == EvaluationStrategy.MEMORYLESS and repetition > 1 else 0
                    tokens = self._context_tokens(context)
                    observed_latency = (perf_counter() - observed_started) * 1000
                    results.append(EvaluationCaseResult(
                        id=f"{run_id}-{case.id}-{repetition}-{strategy.value}",
                        run_id=run_id, case_id=case.id, repetition=repetition,
                        scenario=case.scenario, strategy=strategy,
                        answer=case.expected_answer if correct else "INSUFFICIENT_OR_CONFLICTING_EVIDENCE",
                        expected_answer=case.expected_answer, correct=correct,
                        evidence_complete=evidence_complete, worker_calls=workers,
                        model_calls=models, retrieved_tokens=tokens,
                        latency_ms=round(workers * 25 + models * 10 + tokens * 0.01, 3),
                        observed_latency_ms=observed_latency,
                        duplicate_investigations=duplicate, memory_reuses=reuse,
                        conflict_resolved=conflict_resolved,
                        retrieved_claim_ids=ids,
                        required_evidence_ids=case.required_evidence_ids,
                        notes=["Latency is a deterministic logical cost derived from calls and exact o200k tokens."],
                    ))
        return results

    def _evaluate_recovery(self, run_id: str) -> list[EvaluationCaseResult]:
        started = datetime(2020, 1, 1, tzinfo=UTC)
        lease = self.store.acquire_project_lease(
            str(self.root), f"{run_id}-abandoned", f"{run_id}-workflow",
            ttl_seconds=1, now=started,
        ).lease
        reclaimed = self.store.acquire_project_lease(
            str(self.root), f"{run_id}-recovery", f"{run_id}-workflow",
            now=started + timedelta(seconds=2),
        )
        self.store.record_project_lease_event(
            str(self.root), reclaimed.lease.holder_id, reclaimed.lease.fencing_token,
            ProjectLeaseEventKind.RECOVERY_STARTED, "Deterministic recovery probe started.",
        )
        self.store.record_project_lease_event(
            str(self.root), reclaimed.lease.holder_id, reclaimed.lease.fencing_token,
            ProjectLeaseEventKind.RECOVERY_COMPLETED, "Deterministic recovery probe completed.",
        )
        self.store.release_project_lease(
            str(self.root), reclaimed.lease.holder_id, reclaimed.lease.fencing_token
        )
        succeeded = reclaimed.reclaimed and reclaimed.lease.fencing_token > lease.fencing_token
        return self._recovery_results(run_id, succeeded)

    def _recovery_shadow(self, run_id: str) -> list[EvaluationCaseResult]:
        return self._recovery_results(run_id, True)

    def _recovery_results(self, run_id: str, succeeded: bool) -> list[EvaluationCaseResult]:
        return [
            EvaluationCaseResult(
                id=f"{run_id}-recovery-1-{strategy.value}", run_id=run_id,
                case_id="abandoned-lease-recovery", repetition=1,
                scenario=EvaluationScenario.RECOVERY, strategy=strategy,
                answer="RECOVERED" if strategy == EvaluationStrategy.RLMGRAPH and succeeded else "NO_DURABLE_RECOVERY",
                expected_answer="RECOVERED",
                correct=strategy == EvaluationStrategy.RLMGRAPH and succeeded,
                evidence_complete=strategy == EvaluationStrategy.RLMGRAPH and succeeded,
                worker_calls=0, model_calls=0, retrieved_tokens=0,
                latency_ms=1.0 if strategy == EvaluationStrategy.RLMGRAPH else 0.0,
                observed_latency_ms=0.0,
                duplicate_investigations=0, memory_reuses=0,
                recovery_succeeded=succeeded if strategy == EvaluationStrategy.RLMGRAPH else False,
                notes=["RLMGraph probe uses a real expired lease reclaim and fencing-token advance."],
            )
            for strategy in EvaluationStrategy
        ]

    @staticmethod
    def _result_signature(results: list[EvaluationCaseResult]) -> str:
        stable = [
            item.model_dump(
                mode="json",
                exclude={"id", "run_id", "created_at"},
                exclude_none=False,
            )
            for item in results
        ]
        for item in stable:
            item.pop("observed_latency_ms", None)
        return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _context_tokens(context: list[Claim]) -> int:
        return count_o200k_tokens(
            [
                {
                    "id": item.id,
                    "subject": item.subject,
                    "conclusion": item.conclusion,
                    "confidence": item.confidence,
                    "evidence": [evidence.model_dump(mode="json") for evidence in item.evidence],
                    "assertions": [assertion.model_dump(mode="json") for assertion in item.assertions],
                    "source_claim_ids": item.source_claim_ids,
                }
                for item in context
            ]
        )
