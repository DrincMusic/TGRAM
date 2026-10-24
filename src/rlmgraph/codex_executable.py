from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

CODEX_EXECUTABLE_ENV_VARS = (
    "RLMGRAPH_CODEX_EXECUTABLE",
    "TGRAM_CODEX_EXECUTABLE",
)
_DEFAULT_COMMANDS = ("codex", "codex.exe", "codex.cmd")


def _resolve_required(value: str, source: str) -> str:
    candidate = Path(value).expanduser()
    looks_like_path = candidate.is_absolute() or any(sep in value for sep in ("/", "\\"))
    if looks_like_path:
        if candidate.is_file():
            return str(candidate.resolve())
        raise FileNotFoundError(
            f"Codex CLI executable configured by {source} does not exist: {candidate}. "
            "Update or remove the stale override; TGRAM will not silently replace an explicit path."
        )
    resolved = shutil.which(value)
    if resolved:
        return resolved
    raise FileNotFoundError(
        f"Codex CLI command configured by {source} was not found on PATH: {value!r}. "
        "Install Codex CLI or provide an existing executable path."
    )


def _windows_store_candidates() -> list[Path]:
    """Return official Store-package CLI paths without persisting a versioned path."""
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return []
    command = (
        "$ErrorActionPreference='Stop'; "
        "Get-AppxPackage -Name 'OpenAI.Codex' | "
        "Sort-Object Version -Descending | Select-Object -ExpandProperty InstallLocation"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [
        Path(line.strip()) / "app" / "resources" / "codex.exe"
        for line in completed.stdout.splitlines()
        if line.strip()
    ]


def resolve_codex_executable(
    executable: str | os.PathLike[str] | None = "codex",
    *,
    environment: Mapping[str, str] | None = None,
    windows: bool | None = None,
) -> str:
    """Resolve Codex CLI while keeping explicit user configuration fail-closed.

    Explicit non-default arguments and environment overrides are authoritative: a stale value
    produces an actionable error instead of silently selecting a different binary. Defaults are
    rediscovered on every call so a Store update cannot leave a cached versioned path behind.
    """
    env = os.environ if environment is None else environment
    requested = os.fspath(executable).strip() if executable is not None else ""
    if requested and requested.casefold() != "codex":
        return _resolve_required(requested, "the explicit executable argument")

    for variable in CODEX_EXECUTABLE_ENV_VARS:
        value = env.get(variable, "").strip()
        if value:
            return _resolve_required(value, variable)

    candidates = []
    if requested:
        candidates.append(requested)
    candidates.extend(item for item in _DEFAULT_COMMANDS if item.casefold() != requested.casefold())
    for command in candidates:
        resolved = shutil.which(command)
        if resolved:
            return resolved

    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        for candidate in _windows_store_candidates():
            if candidate.is_file():
                return str(candidate.resolve())

    overrides = ", ".join(CODEX_EXECUTABLE_ENV_VARS)
    raise FileNotFoundError(
        "Codex CLI executable was not found. Install Codex CLI and ensure 'codex' is on PATH, "
        f"or set one of these variables to an existing executable: {overrides}. "
        "On Windows, TGRAM also checks the currently installed official OpenAI.Codex package."
    )
