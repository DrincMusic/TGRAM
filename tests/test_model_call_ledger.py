from rlmgraph.model_call_ledger import ModelCallLedger, estimate_tokens, exact_tokens


def test_model_call_ledger_separates_provider_usage_from_estimates(tmp_path) -> None:
    ledger = ModelCallLedger(tmp_path / "calls.db")
    ledger.record(
        role="conversation", operation="Interpret", provider="openai_api",
        model="gpt-test", status="SUCCEEDED", latency_ms=12.5,
        input_tokens=80, output_tokens=20, token_source="PROVIDER",
    )
    ledger.record(
        role="implementation", operation="Implement", provider="codex_cli",
        model="gpt-test", status="FAILED", latency_ms=30,
        input_tokens=40, output_tokens=5, token_source="ESTIMATE", error="failed",
    )

    assert ledger.summary() == {
        "model_call_count": 2,
        "metered_total_tokens": 145,
        "provider_measured_tokens": 100,
        "estimated_tokens": 45,
        "provider_measured_calls": 1,
        "estimated_call_count": 1,
        "failed_model_calls": 1,
        "local_observed_input_tokens": 0,
        "provider_unexplained_input_tokens": 0,
        "provider_cached_input_tokens": 0,
        "provider_uncached_input_tokens": 0,
        "provider_unexplained_uncached_input_tokens": 0,
        "provider_measurement_coverage_percent": 50.0,
        "measurement_started_at": ledger.measurement_started_at,
        "excluded_historical_calls": 0,
        "excluded_historical_tokens": 0,
    }
    assert estimate_tokens("12345") == 2
    assert exact_tokens("hello") == 1
