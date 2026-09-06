from rlmgraph.project_cold_archive import ProjectColdArchive


def test_archive_preserves_full_payload_by_reference(tmp_path) -> None:
    archive = ProjectColdArchive(tmp_path / "archive.db")
    payload = {"prompt": "a very large raw prompt", "result": {"full": [1, 2, 3]}}
    event_id = archive.append(kind="worker_exchange", payload=payload, task_id=4, attempt=2)

    event = archive.get(event_id)
    assert event["payload"] == payload
    assert event["task_id"] == 4
    assert archive.count() == 1
