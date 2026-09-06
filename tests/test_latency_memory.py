import pytest

from rlmgraph.latency_memory import ChatTiming, latency_observations, record_latency
from rlmgraph.model_call_ledger import ModelCallLedger, scoped_model_call_ledger
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore


def test_stage_timing_accounts_for_total_without_sleep():
    ticks = iter([0, 1, 4, 5])
    timing = ChatTiming(clock=lambda: next(ticks))
    timing.mark("MEMORY_RECALL")
    timing.mark("ANSWER_REVIEW")
    result = timing.finish()
    assert result["total_ms"] == 5000
    assert result["stages_ms"] == {"REQUEST_SETUP": 1000, "MEMORY_RECALL": 3000, "ANSWER_REVIEW": 1000}


def test_bounded_profile_scoped_latency_report_and_chat_route(tmp_path):
    ledger = ModelCallLedger(tmp_path / "ledger.db")
    with scoped_model_call_ledger(ledger):
        for _ in range(205):
            record_latency(ledger, "owner", "session", "RLM_CONVERSATION", {"total_ms": 1000, "stages_ms": {"MEMORY_RECALL": 900, "ANSWER_REVIEW": 100}})
        record_latency(ledger, "foreign", "secret", "RLM_CONVERSATION", {"total_ms": 99000, "stages_ms": {"PRIVATE_STAGE": 99000}})
        observations = latency_observations("owner")
        assert observations["sample_count"] == 30
        assert observations["mean_ms"] == 1000
        assert observations["stages"][0]["stage"] == "MEMORY_RECALL"
        assert "PRIVATE_STAGE" not in str(observations)
        with ledger._connect() as connection:
            assert connection.execute("SELECT count(*) FROM chat_latency").fetchone()[0] == 200
        store = SQLiteGraphStore(tmp_path / "chat.db")
        store.initialize()
        chat = ObserverChat(store, interpreter=object())
        result = chat.safe_reply("Why are you so slow?", [], None, None, profile_id="owner")
        assert result["route"] == "RLM_LATENCY_OBSERVATION"
        assert "memory recall" in result["answer"]
        assert "not a proven root cause" in result["answer"]
        assert len(latency_observations("owner")["stages"]) == 2


def test_safe_reply_records_completed_measurement(tmp_path, monkeypatch):
    ledger = ModelCallLedger(tmp_path / "ledger.db")
    store = SQLiteGraphStore(tmp_path / "chat.db")
    store.initialize()
    chat = ObserverChat(store, interpreter=object())
    def response(*args, **kwargs):
        kwargs["progress"]("ANSWER_REVIEW", "Checking")
        return {"route": "RLM_CONVERSATION", "session_id": "s", "answer": "Checked"}
    monkeypatch.setattr(chat, "reply", response)
    with scoped_model_call_ledger(ledger):
        result = chat.safe_reply("Hello", [], None, None, profile_id="owner")
        assert "ANSWER_REVIEW" in result["latency_measurement"]["stages_ms"]
        assert latency_observations("owner")["sample_count"] == 1


pytestmark = pytest.mark.usefixtures("offline_chat_adapter")
