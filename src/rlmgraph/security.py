from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


class RiskTier(IntEnum):
    READ_ONLY = 0
    CONTROLLED_EXECUTION = 1
    PROJECT_MUTATION = 2
    RECOVERY_OR_POLICY = 3


@dataclass(frozen=True)
class RiskDecision:
    tier: RiskTier
    authority: str
    consequence: str
    required_decision: str


def explain_risk(action: str) -> RiskDecision:
    action = action.upper()
    if action in {"VIEW", "SEARCH", "INDEX_READ_ONLY", "EXPORT"}:
        return RiskDecision(RiskTier.READ_ONLY, "registered-project read authority",
                            "No project bytes are changed", "No mutation approval")
    if action in {"RUN", "VALIDATE", "DEPENDENCY_EXECUTION"}:
        return RiskDecision(RiskTier.CONTROLLED_EXECUTION, "bounded worker policy",
                            "A confined subprocess may execute", "Approve execution if policy requires")
    if action == "PROMOTION":
        return RiskDecision(RiskTier.PROJECT_MUTATION, "bound promotion approval",
                            "Reviewed patch bytes may replace project files", "Separate promotion approval")
    return RiskDecision(RiskTier.RECOVERY_OR_POLICY, "authenticated administrator",
                        "Authority or durable state may change", "Explicit authenticated decision")


def confined_path(root: str | Path, candidate: str | Path, *, must_exist: bool = True) -> Path:
    """Reject escapes and every existing link/reparse component before returning a path."""
    base = Path(root).resolve(strict=True)
    raw = Path(candidate)
    target = raw if raw.is_absolute() else base / raw
    relative = target.absolute().relative_to(base)
    current = base
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            reparse = bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            if stat.S_ISLNK(info.st_mode) or reparse:
                raise ValueError(f"Path confinement rejected link or reparse component: {current}")
    resolved = target.resolve(strict=must_exist)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Path escapes the authorized project boundary.") from exc
    return resolved


def sanitized_environment(allowed: dict[str, str] | None = None) -> dict[str, str]:
    """Construct an allowlisted worker environment without inheriting credentials."""
    safe_names = {"PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in safe_names}
    for key, value in (allowed or {}).items():
        if any(marker in key.upper() for marker in ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL")):
            raise ValueError(f"Credential-like environment variable is not permitted: {key}")
        environment[key] = value
    return environment
