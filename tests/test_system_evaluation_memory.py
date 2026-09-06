from rlmgraph.system_evaluation_memory import SystemEvaluationMemoryStore


def suite_result(*, suite_id="suite-valid", valid=True):
    return {
        "id": suite_id,
        "quality_threshold": 0.8,
        "project_count": 3,
        "repetitions": 3,
        "trial_count": 9,
        "summary": {
            "verdict": (
                "VALID_SAVINGS_COMPARISON"
                if valid else "INCONCLUSIVE_BASELINE_BELOW_QUALITY_THRESHOLD"
            ),
            "quality_gate_passed": valid,
            "baseline_pass_rate": 0.8667,
            "rlmgraph_pass_rate": 0.9111,
            "baseline_median_tokens": 423220,
            "rlmgraph_median_tokens": 68353,
            "quality_gated_median_savings_percent": 83.8 if valid else None,
        },
    }


def test_valid_suite_is_durable_bounded_evidence(tmp_path):
    store = SystemEvaluationMemoryStore(tmp_path / "evaluations.jsonl")
    report = tmp_path / "suite.json"
    report.write_text("{}", encoding="utf-8")

    first = store.remember_credible_suite(
        suite_result(), report, models=["gpt-5.4"]
    )
    second = store.remember_credible_suite(
        suite_result(), report, models=["gpt-5.4"]
    )

    assert first.id == second.id
    assert len(store.records()) == 1
    assert first.evidence_eligible is True
    assert first.metrics["median_token_savings_percent"] == 83.8
    assert first.metrics["tgram_pass_rate"] == 0.9111
    assert first.models == ["gpt-5.4"]
    assert store.retrieve("Do you remember the test you took in nine trials?") == [first]


def test_invalid_suite_is_only_retrieved_when_history_is_requested(tmp_path):
    store = SystemEvaluationMemoryStore(tmp_path / "evaluations.jsonl")
    report = tmp_path / "invalid.json"
    report.write_text("{}", encoding="utf-8")
    invalid = store.remember_credible_suite(
        suite_result(suite_id="suite-invalid", valid=False), report
    )

    assert store.retrieve("What did your benchmark establish?") == []
    assert store.retrieve("What happened in the earlier invalid benchmark?") == [invalid]
