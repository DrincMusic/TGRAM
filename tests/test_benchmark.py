from pathlib import Path

from rlmgraph.benchmark import BenchmarkCase, MemoryBenchmarkRunner
from rlmgraph.models import Claim, Evidence, GraphRelation
from rlmgraph.reconstruction import count_o200k_tokens
from rlmgraph.store import SQLiteGraphStore


def make_case(root: Path, index: int) -> BenchmarkCase:
    project = root / f"case-{index}"
    project.mkdir(parents=True)
    (project / "contract.txt").write_text(f"validated-answer-{index}\n")
    evidence = [
        Claim(
            id=f"CASE-{index}-EVIDENCE-{number}",
            fingerprint=f"evidence-{index}-{number}",
            project_root=str(project.resolve()),
            subject=f"Evidence {number} for benchmark case {index}",
            producer="BenchmarkFixture",
            conclusion=f"Evidence {number} validates case {index}.",
            confidence=1.0,
            evidence=[Evidence(path="contract.txt", line=1, detail="Fixture truth")],
            files_examined=["contract.txt"],
        )
        for number in range(2)
    ]
    noise = [
        Claim(
            id=f"CASE-{index}-NOISE-{number}",
            fingerprint=f"noise-{index}-{number}",
            project_root=str(project.resolve()),
            subject=f"Unrelated subsystem {number}",
            producer="BenchmarkFixture",
            conclusion=(
                f"Unrelated subsystem {number} contains deliberately verbose historical "
                "implementation context that is irrelevant to this benchmark question."
            ),
            confidence=0.9,
        )
        for number in range(15)
    ]
    question = f"What is the validated answer for benchmark case {index}?"
    answer = Claim(
        id=f"CASE-{index}-ANSWER",
        fingerprint=f"answer-{index}",
        project_root=str(project.resolve()),
        subject=question,
        producer="BenchmarkFixture",
        conclusion=f"validated-answer-{index}",
        confidence=1.0,
        source_claim_ids=[claim.id for claim in evidence],
        evidence=[Evidence(path="contract.txt", line=1, detail="Fixture truth")],
        files_examined=["contract.txt"],
    )
    return BenchmarkCase(
        id=f"case-{index}",
        question=question,
        project_root=project,
        claims=[*evidence, *noise, answer],
        expected_answer=answer.conclusion,
        answer_claim_id=answer.id,
        required_evidence_ids=[claim.id for claim in evidence],
    )


def test_three_repeatable_cases_reduce_tokens_without_quality_loss(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "benchmark.db")
    runner = MemoryBenchmarkRunner(store)
    runs = [runner.run(make_case(tmp_path, index)) for index in range(3)]

    assert len(store.benchmark_runs()) == 3
    assert all(run.passed for run in runs)
    assert all(run.token_reduction >= 0.5 for run in runs)
    assert all(run.fixed.correct and run.active.correct for run in runs)
    assert all(run.fixed.evidence_complete and run.active.evidence_complete for run in runs)
    assert all(run.active.input_tokens < run.fixed.input_tokens for run in runs)
    assert all(run.fixed.output_tokens == run.active.output_tokens for run in runs)
    assert all(run.fixed.wall_time_ms > 0 and run.active.wall_time_ms > 0 for run in runs)
    assert all(run.fixed.duplicate_retrievals == 0 for run in runs)
    assert all(run.active.duplicate_retrievals == 0 for run in runs)
    assert all(len(run.traversal_node_ids) == 3 for run in runs)
    assert all(len(run.traversal_edges) == 2 for run in runs)
    persisted_claims = {claim.id: claim for claim in store.claims()}
    assert all(
        run.fixed.input_tokens
        == count_o200k_tokens(
            MemoryBenchmarkRunner._input_payload(
                run.question,
                [persisted_claims[node_id] for node_id in run.fixed.context_node_ids],
            )
        )
        for run in runs
    )
    assert sum(
        edge.relation == GraphRelation.HAS_BENCHMARK for edge in store.edges()
    ) == 3
    assert sum(
        edge.relation == GraphRelation.MEASURED_RECONSTRUCTION for edge in store.edges()
    ) == 3


def test_benchmark_rejects_missing_evidence_and_insufficient_reduction(
    tmp_path: Path,
) -> None:
    missing = make_case(tmp_path / "missing", 0)
    missing.claims[-1].source_claim_ids = missing.required_evidence_ids[:1]
    missing_run = MemoryBenchmarkRunner(
        SQLiteGraphStore(tmp_path / "missing.db")
    ).run(missing)
    assert missing_run.fixed.correct is True
    assert missing_run.active.correct is False
    assert missing_run.active.evidence_complete is False
    assert missing_run.passed is False

    strict_case = make_case(tmp_path / "strict", 1)
    strict_case = BenchmarkCase(
        **{
            **strict_case.__dict__,
            "minimum_reduction": 0.99,
        }
    )
    strict_run = MemoryBenchmarkRunner(SQLiteGraphStore(tmp_path / "strict.db")).run(
        strict_case
    )
    assert strict_run.correctness_preserved is True
    assert strict_run.evidence_preserved is True
    assert strict_run.token_reduction < 0.99
    assert strict_run.passed is False
