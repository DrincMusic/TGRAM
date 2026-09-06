from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def project_fingerprint(project_root: Path) -> str:
    """Fingerprint the project identity and relevant file state."""
    root = project_root.resolve()
    files: list[tuple[str, str]] = []
    ignored = {
        ".git",
        ".venv",
        ".rlmgraph",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
    }
    if root.exists():
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = sorted(name for name in names if name not in ignored)
            for name in sorted(filenames):
                candidate = Path(directory) / name
                try:
                    path = candidate.resolve(strict=True)
                    relative = path.relative_to(root)
                except (OSError, ValueError):
                    continue
                if not path.is_file() or path.name.startswith(".rlmgraph.db"):
                    continue
                files.append((relative.as_posix(), file_content_hash(path)))
    payload = {"root": str(root), "files": files}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def indexed_project_fingerprint(
    project_root: Path, files: list[tuple[str, str]]
) -> str:
    """Produce the canonical project state from an already-hashed project index."""
    payload = {"root": str(project_root.resolve()), "files": sorted(files)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def file_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_fingerprint(question: str, project_state: str) -> str:
    """Fingerprint a normalized question within one exact project state."""
    payload = {"question": " ".join(question.lower().split()), "project_state": project_state}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
