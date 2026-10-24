from pathlib import Path

import pytest

from rlmgraph import codex_executable


def test_explicit_existing_path_is_authoritative(tmp_path: Path) -> None:
    executable = tmp_path / "codex.cmd"
    executable.write_text("@echo off\n", encoding="utf-8")

    assert codex_executable.resolve_codex_executable(executable, environment={}) == str(
        executable.resolve()
    )


def test_stale_explicit_path_fails_without_fallback(monkeypatch, tmp_path: Path) -> None:
    stale = tmp_path / "removed" / "codex.exe"
    monkeypatch.setattr(codex_executable.shutil, "which", lambda _: "other-codex")

    with pytest.raises(FileNotFoundError, match="stale override"):
        codex_executable.resolve_codex_executable(stale, environment={})


def test_environment_override_supports_cmd_shim(tmp_path: Path) -> None:
    executable = tmp_path / "codex.cmd"
    executable.write_text("@echo off\n", encoding="utf-8")

    assert codex_executable.resolve_codex_executable(
        "codex", environment={"RLMGRAPH_CODEX_EXECUTABLE": str(executable)}
    ) == str(executable.resolve())


def test_clean_install_discovers_path_command(monkeypatch) -> None:
    def which(command: str):
        return "C:/tools/codex.cmd" if command == "codex.cmd" else None

    monkeypatch.setattr(codex_executable.shutil, "which", which)

    assert codex_executable.resolve_codex_executable(
        "codex", environment={}, windows=False
    ) == "C:/tools/codex.cmd"


def test_explicit_named_wrapper_fails_without_fallback(monkeypatch) -> None:
    monkeypatch.setattr(codex_executable.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        codex_executable,
        "_windows_store_candidates",
        lambda: pytest.fail("explicit wrapper must not use Store fallback"),
    )

    with pytest.raises(FileNotFoundError, match="explicit executable argument"):
        codex_executable.resolve_codex_executable("company-codex-wrapper", environment={})


def test_windows_store_path_is_rediscovered_after_version_disappears(
    monkeypatch, tmp_path: Path
) -> None:
    old = tmp_path / "OpenAI.Codex_1" / "app" / "resources" / "codex.exe"
    current = tmp_path / "OpenAI.Codex_2" / "app" / "resources" / "codex.exe"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    current.parent.mkdir(parents=True)
    current.write_text("current", encoding="utf-8")
    old.unlink()
    monkeypatch.setattr(codex_executable.shutil, "which", lambda _: None)
    monkeypatch.setattr(codex_executable, "_windows_store_candidates", lambda: [current])

    assert codex_executable.resolve_codex_executable(
        "codex", environment={}, windows=True
    ) == str(current.resolve())


def test_missing_cli_error_explains_install_and_override(monkeypatch) -> None:
    monkeypatch.setattr(codex_executable.shutil, "which", lambda _: None)
    monkeypatch.setattr(codex_executable, "_windows_store_candidates", list)

    with pytest.raises(FileNotFoundError, match="ensure 'codex' is on PATH") as failure:
        codex_executable.resolve_codex_executable("codex", environment={}, windows=True)

    assert "RLMGRAPH_CODEX_EXECUTABLE" in str(failure.value)
    assert "official OpenAI.Codex package" in str(failure.value)
