from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from rlmgraph.models import ProjectLeaseEventKind, ProjectLeaseStatus
from rlmgraph.store import SQLiteGraphStore


def test_independent_sqlite_connections_atomically_contend_for_one_project(
    tmp_path: Path,
) -> None:
    database = tmp_path / "graph.db"
    SQLiteGraphStore(database).initialize()
    barrier = Barrier(2)

    def acquire(holder: str):
        store = SQLiteGraphStore(database)
        barrier.wait()
        return store.acquire_project_lease(str(tmp_path / "project"), holder, holder)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, ("runner-a", "runner-b")))

    assert sum(result.acquired for result in results) == 1
    lease = SQLiteGraphStore(database).project_leases()[0]
    assert lease.status == ProjectLeaseStatus.ACTIVE
    assert [event.kind for event in lease.events].count(ProjectLeaseEventKind.ACQUIRED) == 1
    assert [event.kind for event in lease.events].count(ProjectLeaseEventKind.CONTENDED) == 1


def test_expired_lease_is_reclaimed_with_a_new_fencing_token(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    started = datetime(2026, 1, 1, tzinfo=UTC)
    old = store.acquire_project_lease(
        str(tmp_path / "project"), "dead-runner", "workflow-old",
        ttl_seconds=5, now=started,
    ).lease

    reclaimed = SQLiteGraphStore(store.path).acquire_project_lease(
        str(tmp_path / "project"), "new-runner", "workflow-new",
        ttl_seconds=30, now=started + timedelta(seconds=6),
    )

    assert reclaimed.acquired is True
    assert reclaimed.reclaimed is True
    assert reclaimed.lease.fencing_token == old.fencing_token + 1
    assert ProjectLeaseEventKind.RECLAIMED in {
        event.kind for event in reclaimed.lease.events
    }
    with pytest.raises(RuntimeError, match="stale|another process"):
        store.release_project_lease(
            str(tmp_path / "project"), "dead-runner", old.fencing_token,
            now=started + timedelta(seconds=7),
        )


def test_renewal_and_release_are_durable_and_fenced(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    started = datetime(2026, 1, 1, tzinfo=UTC)
    lease = store.acquire_project_lease(
        str(tmp_path / "project"), "runner", "workflow", now=started,
    ).lease
    renewed = store.renew_project_lease(
        lease.project_root, "runner", lease.fencing_token,
        ttl_seconds=300, now=started + timedelta(seconds=1),
    )
    released = SQLiteGraphStore(store.path).release_project_lease(
        lease.project_root, "runner", lease.fencing_token,
        now=started + timedelta(seconds=2),
    )

    assert renewed.expires_at == started + timedelta(seconds=301)
    assert released.status == ProjectLeaseStatus.RELEASED
    assert [event.kind for event in released.events] == [
        ProjectLeaseEventKind.ACQUIRED,
        ProjectLeaseEventKind.RENEWED,
        ProjectLeaseEventKind.RELEASED,
    ]
