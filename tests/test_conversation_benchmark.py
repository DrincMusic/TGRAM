from rlmgraph.conversation_benchmark import (
    ConversationBenchmarkStore,
    PairedConversationBenchmark,
)
from rlmgraph.model_call_ledger import ModelCallLedger


class FakeAdapter:
    model = "fixture-model"

    def __init__(self, ledger: ModelCallLedger) -> None:
        self.ledger = ledger

    def _run_structured(self, prompt, root, result_type, timeout_seconds=900):
        del root, timeout_seconds
        self.ledger.record(
            role="conversation", operation=result_type.__name__, provider="fixture",
            model=self.model, status="SUCCEEDED", latency_ms=1,
            input_tokens=100, output_tokens=10, token_source="PROVIDER",
        )
        answer = (
            "Atlas has Boise as its final launch city and uses SQLite."
            if "What are the project codename" in prompt else "Remembered."
        )
        return result_type(answer=answer)


class FakeObserver:
    def __init__(self, ledger: ModelCallLedger) -> None:
        self.interpreter = FakeAdapter(ledger)
        self.ledger = ledger

    def safe_reply(self, message, history, *args):
        del history, args
        self.ledger.record(
            role="conversation", operation="RLMReply", provider="fixture",
            model="fixture-model", status="SUCCEEDED", latency_ms=1,
            input_tokens=20, output_tokens=5, token_source="PROVIDER",
        )
        answer = (
            "Atlas has Boise as its final launch city and uses SQLite."
            if message.startswith("What are") else "Remembered."
        )
        return {"answer": answer}


def test_paired_conversation_benchmark_measures_both_arms_and_persists(tmp_path) -> None:
    ledger = ModelCallLedger(tmp_path / "calls.db")
    store = ConversationBenchmarkStore(tmp_path / "benchmarks.db")
    benchmark = PairedConversationBenchmark(FakeObserver(ledger), ledger, store, tmp_path)

    result = benchmark.run()

    assert result["baseline_tokens"] == 330
    assert result["rlmgraph_tokens"] == 75
    assert result["tokens_saved"] == 255
    assert result["savings_percent"] == 77.3
    assert result["quality_preserved"] is True
    assert result["baseline"]["model_call_count"] == 3
    assert result["rlmgraph"]["model_call_count"] == 3
    assert store.latest()["id"] == result["id"]
