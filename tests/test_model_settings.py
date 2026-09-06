from __future__ import annotations

import json

import pytest

from rlmgraph.model_settings import ModelSettingsManager


def _defaults() -> dict[str, dict[str, str]]:
    return {
        role: {
            "provider": "codex_cli",
            "model": "gpt-5.4",
            "base_url": "",
            "api_key_environment": "",
        }
        for role in ("conversation", "evidence", "ideas", "implementation")
    }


def test_local_conversation_selection_is_applied_and_persisted(tmp_path) -> None:
    applied: list[dict[str, str]] = []
    settings_path = tmp_path / "models.json"
    manager = ModelSettingsManager(
        settings_path,
        _defaults(),
        {"conversation": lambda selection: applied.append(selection)},
    )

    snapshot = manager.update(
        "conversation",
        "llama-3.3-local",
        "local_openai",
        "http://127.0.0.1:11434/v1/",
        "LOCAL_MODEL_KEY",
    )

    selected = next(role for role in snapshot["roles"] if role["role"] == "conversation")
    assert selected["provider"] == "local_openai"
    assert selected["model"] == "llama-3.3-local"
    assert selected["base_url"] == "http://127.0.0.1:11434/v1"
    assert selected["api_key_environment"] == "LOCAL_MODEL_KEY"
    assert snapshot["api_keys_are_persisted"] is False
    assert applied[-1] == {
        "provider": "local_openai",
        "model": "llama-3.3-local",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_environment": "LOCAL_MODEL_KEY",
    }
    assert "secret" not in settings_path.read_text(encoding="utf-8")

    reloaded = ModelSettingsManager(settings_path, _defaults(), {})
    assert reloaded.selections["conversation"] == applied[-1]


def test_tool_roles_reject_http_only_providers(tmp_path) -> None:
    manager = ModelSettingsManager(tmp_path / "models.json", _defaults(), {})

    with pytest.raises(ValueError, match="cannot perform the evidence role"):
        manager.update("evidence", "gpt-5.4", "openai_api")

    assert not (tmp_path / "models.json").exists()


def test_codex_rejects_known_unsupported_model_without_persisting(tmp_path):
    manager = ModelSettingsManager(tmp_path / "models.json", _defaults(), {})
    with pytest.raises(ValueError, match="unavailable"):
        manager.update("conversation", "gpt-5.4", "codex_cli")
    assert not (tmp_path / "models.json").exists()


def test_only_environment_variable_name_is_stored(tmp_path) -> None:
    settings_path = tmp_path / "models.json"
    manager = ModelSettingsManager(settings_path, _defaults(), {})
    manager.update(
        "conversation", "gpt-5.4", "openai_api", api_key_environment="RLMGRAPH_API_KEY"
    )

    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["conversation"]["api_key_environment"] == "RLMGRAPH_API_KEY"
    assert "api_key" not in stored["conversation"]
