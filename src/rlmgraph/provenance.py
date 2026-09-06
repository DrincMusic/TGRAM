from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .fingerprint import file_content_hash
from .models import (
    Claim,
    ClaimValidity,
    MemoryTier,
    ProjectFile,
    SourceFile,
    Task,
    TierTransition,
    ValidityEvent,
)


def repository_commit(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def supporting_paths(claim: Claim) -> list[str]:
    evidence_paths = [item.path for item in claim.evidence]
    paths = evidence_paths or claim.files_examined
    return list(dict.fromkeys(path.replace("\\", "/") for path in paths))


def capture_source_files(project_root: Path, claim: Claim) -> list[SourceFile]:
    lines_by_path: dict[str, list[int]] = {}
    for evidence in claim.evidence:
        normalized = evidence.path.replace("\\", "/")
        if evidence.line is not None:
            lines_by_path.setdefault(normalized, []).append(evidence.line)
    sources: list[SourceFile] = []
    root = project_root.resolve()
    for relative in supporting_paths(claim):
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            sources.append(
                SourceFile(
                    path=relative,
                    content_hash=file_content_hash(candidate),
                    evidence_lines=sorted(set(lines_by_path.get(relative, []))),
                )
            )
    return sources


def capture_indexed_source_files(claim: Claim, files: list[ProjectFile]) -> list[SourceFile]:
    """Ground a claim in hashes already captured by the read-only project index."""
    lines_by_path: dict[str, list[int]] = {}
    for evidence in claim.evidence:
        normalized = evidence.path.replace("\\", "/")
        if evidence.line is not None:
            lines_by_path.setdefault(normalized, []).append(evidence.line)
    indexed = {item.path: item for item in files}
    return [
        SourceFile(
            path=path,
            content_hash=indexed[path].content_hash,
            evidence_lines=sorted(set(lines_by_path.get(path, []))),
        )
        for path in supporting_paths(claim)
        if path in indexed
    ]


def assess_claim_from_index(
    claim: Claim, files: list[ProjectFile], project_state: str
) -> tuple[bool, str]:
    """Validate provenance without opening source files a second time."""
    if not claim.source_files:
        valid = claim.project_fingerprint == project_state
        return (
            valid,
            "Ungrounded claim is restricted to its exact indexed project state."
            if valid
            else "Ungrounded claim was learned in a different indexed project state.",
        )
    hashes = {item.path: item.content_hash for item in files}
    changed = [
        source.path
        for source in claim.source_files
        if hashes.get(source.path) != source.content_hash
    ]
    if changed:
        prefix = (
            f"Superseded by {claim.superseded_by_claim_id}; "
            if claim.superseded_by_claim_id
            else ""
        )
        return False, prefix + "indexed supporting evidence changed or disappeared: " + ", ".join(changed)
    return (
        True,
        "Historical indexed state restored; supporting evidence matches again."
        if claim.superseded_by_claim_id
        else "Every indexed supporting source still matches its learned content hash.",
    )


def initialize_provenance(task: Task, claim: Claim) -> Claim:
    root = Path(task.project_root)
    claim.project_root = claim.project_root or str(root.resolve())
    claim.source_task_id = claim.source_task_id or task.id
    claim.source_claim_ids = list(
        dict.fromkeys([*claim.source_claim_ids, *task.source_claim_ids, *claim.resolved_claim_ids])
    )
    claim.source_files = claim.source_files or capture_source_files(root, claim)
    claim.source_commit = claim.source_commit or repository_commit(root)
    claim.valid_from = claim.valid_from or task.project_fingerprint
    claim.validity_status = ClaimValidity.CURRENT
    claim.validity_reason = (
        "Every supporting source file still matches its learned content hash."
        if claim.source_files
        else "Ungrounded claim is restricted to its exact repository state."
    )
    if not claim.validity_history:
        claim.validity_history.append(
            ValidityEvent(
                status=ClaimValidity.CURRENT,
                project_fingerprint=task.project_fingerprint,
                reason=claim.validity_reason,
            )
        )
    if claim.memory_tier == MemoryTier.WORKING:
        if not claim.tier_history:
            claim.tier_history.append(
                TierTransition(
                    to_tier=MemoryTier.WORKING,
                    reason="Transient result produced while the task was executing.",
                )
            )
        claim.tier_history.append(
            TierTransition(
                from_tier=MemoryTier.WORKING,
                to_tier=MemoryTier.EPISODIC,
                reason="Completed task experience persisted as episodic memory.",
            )
        )
        claim.memory_tier = MemoryTier.EPISODIC
    return claim


def assess_claim(claim: Claim, project_root: Path, project_state: str) -> tuple[bool, str]:
    if not claim.source_files:
        valid = claim.project_fingerprint == project_state
        return (
            valid,
            "Ungrounded claim is restricted to its exact repository state."
            if valid
            else "Ungrounded claim was learned in a different repository state.",
        )
    root = project_root.resolve()
    changed: list[str] = []
    for source in claim.source_files:
        candidate = (root / source.path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            changed.append(source.path)
            continue
        if not candidate.is_file() or file_content_hash(candidate) != source.content_hash:
            changed.append(source.path)
    if changed:
        prefix = (
            f"Superseded by {claim.superseded_by_claim_id}; "
            if claim.superseded_by_claim_id
            else ""
        )
        return False, prefix + "supporting evidence changed or disappeared: " + ", ".join(changed)
    return (
        True,
        "Historical repository state restored; supporting evidence matches again."
        if claim.superseded_by_claim_id
        else "Every supporting source file still matches its learned content hash.",
    )


def record_validity(claim: Claim, valid: bool, project_state: str, reason: str) -> bool:
    target = (
        ClaimValidity.CURRENT
        if valid
        else (
            ClaimValidity.SUPERSEDED
            if claim.superseded_by_claim_id
            else ClaimValidity.INVALIDATED
        )
    )
    changed = claim.validity_status != target or claim.validity_reason != reason
    if not changed:
        return False
    claim.validity_status = target
    claim.validity_reason = reason
    claim.valid_until = None if valid else project_state
    claim.validity_history.append(
        ValidityEvent(status=target, project_fingerprint=project_state, reason=reason)
    )
    return True


def supersede(old: Claim, replacement: Claim, project_state: str) -> None:
    old.validity_status = ClaimValidity.SUPERSEDED
    old.superseded_by_claim_id = replacement.id
    old.valid_until = project_state
    old.validity_reason = f"Superseded by replacement claim {replacement.id}."
    old.validity_history.append(
        ValidityEvent(
            status=ClaimValidity.SUPERSEDED,
            project_fingerprint=project_state,
            reason=old.validity_reason,
            observed_at=datetime.now(UTC),
        )
    )
