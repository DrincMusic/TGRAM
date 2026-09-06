"""Explicit offline fixtures for tests of chat orchestration."""
import pytest


@pytest.fixture
def offline_chat_adapter(monkeypatch):
    class OfflineAdapter:
        def investigate(self, *args, **kwargs):
            pytest.fail("This orchestration test must not invoke a live model.")

    monkeypatch.setattr(
        "rlmgraph.observer_chat.CodexCliInvestigator",
        lambda *args, **kwargs: OfflineAdapter(),
    )
