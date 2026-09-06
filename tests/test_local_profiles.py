from __future__ import annotations

import json

import pytest

from rlmgraph.local_profiles import LocalProfileStore


def test_local_profiles_hash_passwords_and_issue_revocable_tokens(tmp_path):
    path = tmp_path / "profiles.json"
    store = LocalProfileStore(path)

    created = store.create("A profile chosen by the user", "correct horse battery")
    persisted = path.read_text(encoding="utf-8")

    assert "correct horse battery" not in persisted
    assert store.authenticate(created["token"])["name"] == "A profile chosen by the user"
    assert created["profile"]["owns_legacy_memory"] is True
    with pytest.raises(ValueError, match="incorrect"):
        store.login(created["profile"]["id"], "wrong password")

    store.logout(created["token"])
    with pytest.raises(PermissionError):
        store.authenticate(created["token"])


def test_only_first_profile_inherits_legacy_memory(tmp_path):
    store = LocalProfileStore(tmp_path / "profiles.json")
    first = store.create("First", "eight characters")
    second = store.create("Second", "another password")

    assert first["profile"]["owns_legacy_memory"] is True
    assert second["profile"]["owns_legacy_memory"] is False
    payload = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert all("password_hash" in profile for profile in payload["profiles"])
