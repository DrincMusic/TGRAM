from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rlmgraph.project_continuity_memory import ProjectContinuityMemory


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _remember(
    store: ProjectContinuityMemory,
    *,
    memory_id: str,
    scope: str = "project-a",
    status: str = "VERIFIED",
    canary: str = "A1B2C3D4E5F6",
):
    return store.remember(
        memory_id=memory_id,
        project_scope=scope,
        origin_task_id="task-1",
        claim_type="validated_project_convention",
        semantic_rule=(
            "Serialize continuity receipt fields in semantic_digest, lease_id, "
            "validation_digest order with the namespace tag first."
        ),
        field_order=("semantic_digest", "lease_id", "validation_digest"),
        run_canary=canary,
        verification_status=status,
        worker_model="gpt-5.6-sol",
        worker_output_digest=_digest("worker"),
        semantic_validator_digest=_digest("validator"),
        test_result_digest=_digest("test"),
        candidate_patch_digest=_digest("patch"),
        candidate_promoted=False,
        created_after_validation=status == "VERIFIED",
    )


def test_verified_exact_scope_memory_survives_reopen_and_is_retrieved(
    tmp_path: Path,
) -> None:
    path = tmp_path / "continuity.jsonl"
    stored = _remember(ProjectContinuityMemory(path), memory_id="VERIFIED-1")

    restarted = ProjectContinuityMemory(path)
    retrieval = restarted.retrieve(
        "construct continuity receipt using field order and namespace tag",
        project_scope="project-a",
    )

    assert retrieval.selected_memory is not None
    assert retrieval.selected_memory["memory_id"] == stored.memory_id
    assert retrieval.selected_memory["run_canary"] == "A1B2C3D4E5F6"
    assert restarted.verify_integrity() == (True, ())


def test_verified_memory_outranks_newer_unverified_conflict(tmp_path: Path) -> None:
    store = ProjectContinuityMemory(tmp_path / "continuity.jsonl")
    _remember(store, memory_id="VERIFIED-1")
    _remember(
        store,
        memory_id="PROPOSED-NEWER",
        status="PROPOSED",
        canary="FFFFFFFFFFFF",
    )

    retrieval = store.retrieve(
        "continuity receipt field order namespace tag", project_scope="project-a"
    )

    assert retrieval.selected_memory is not None
    assert retrieval.selected_memory["memory_id"] == "VERIFIED-1"
    conflict = next(
        item
        for item in retrieval.candidate_memories
        if item["memory_id"] == "PROPOSED-NEWER"
    )
    assert conflict["eligible"] is False
    assert "NOT_VERIFIED" in conflict["rejection_reasons"]


def test_wrong_scope_is_traced_but_not_selected(tmp_path: Path) -> None:
    store = ProjectContinuityMemory(tmp_path / "continuity.jsonl")
    _remember(store, memory_id="OTHER-SCOPE", scope="project-b")

    retrieval = store.retrieve(
        "continuity receipt field order namespace tag", project_scope="project-a"
    )

    assert retrieval.selected_memory is None
    assert retrieval.candidate_memories[0]["rejection_reasons"] == ["WRONG_SCOPE"]


def test_verified_memory_requires_post_validation_discarded_candidate(
    tmp_path: Path,
) -> None:
    store = ProjectContinuityMemory(tmp_path / "continuity.jsonl")

    with pytest.raises(ValueError, match="discarded candidate"):
        store.remember(
            project_scope="project-a",
            origin_task_id="task-1",
            claim_type="validated_project_convention",
            semantic_rule="continuity receipt field order namespace tag",
            field_order=("semantic_digest", "lease_id", "validation_digest"),
            run_canary="A1B2C3D4E5F6",
            verification_status="VERIFIED",
            worker_model="gpt-5.6-sol",
            worker_output_digest=_digest("worker"),
            semantic_validator_digest=_digest("validator"),
            test_result_digest=_digest("test"),
            candidate_patch_digest=_digest("patch"),
            candidate_promoted=True,
            created_after_validation=False,
        )


def test_hash_tampering_fails_integrity(tmp_path: Path) -> None:
    path = tmp_path / "continuity.jsonl"
    _remember(ProjectContinuityMemory(path), memory_id="VERIFIED-1")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["run_canary"] = "FFFFFFFFFFFF"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    ok, errors = ProjectContinuityMemory(path).verify_integrity()

    assert ok is False
    assert "hash mismatch" in " ".join(errors)

    with pytest.raises(ValueError, match="integrity failed"):
        ProjectContinuityMemory(path).retrieve(
            "continuity receipt field order namespace tag", project_scope="project-a"
        )


def test_hash_consistent_malformed_verified_record_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "continuity.jsonl"
    _remember(ProjectContinuityMemory(path), memory_id="VERIFIED-1")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(
        {
            "run_canary": "not-a-canary",
            "worker_output_digest": "bad",
            "semantic_validator_digest": "bad",
            "test_result_digest": "bad",
            "candidate_patch_digest": "bad",
            "candidate_promoted": "",
            "created_after_validation": "yes",
        }
    )
    body = dict(raw)
    body.pop("content_sha256")
    raw["content_sha256"] = hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    store = ProjectContinuityMemory(path)
    ok, errors = store.verify_integrity()

    assert ok is False
    assert "canary" in " ".join(errors)
    assert "provenance flags" in " ".join(errors)
    with pytest.raises(ValueError, match="integrity failed"):
        store.retrieve(
            "continuity receipt field order namespace tag", project_scope="project-a"
        )


def test_token_sidecar_tampering_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "continuity.jsonl"
    _remember(ProjectContinuityMemory(path), memory_id="VERIFIED-1")
    token_path = Path(f"{path}.tokens.json")
    token_payload = json.loads(token_path.read_text(encoding="utf-8"))
    token_payload["entries"]["VERIFIED-1"]["concepts"] = ["attacker-selected"]
    token_path.write_text(json.dumps(token_payload), encoding="utf-8")

    store = ProjectContinuityMemory(path)
    ok, errors = store.verify_integrity()

    assert ok is False
    assert "token entry mismatch" in " ".join(errors)
    with pytest.raises(ValueError, match="integrity failed"):
        store.retrieve(
            "continuity receipt field order namespace tag", project_scope="project-a"
        )
