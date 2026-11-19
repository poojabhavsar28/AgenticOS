"""Persistence tests for SQLite checkpoint and audit stores."""

import pytest

from agenticos.runtime.checkpoints import SQLiteCheckpointStore
from agenticos.security.audit import SQLiteAuditLog


@pytest.mark.asyncio
async def test_checkpoint_survives_store_reopen_and_updates(tmp_path) -> None:
    database = tmp_path / "state" / "operations.sqlite3"
    first_store = SQLiteCheckpointStore(database)
    await first_store.save(
        "run-1",
        {"run_id": "run-1", "status": "running", "updated_at": "2026-11-20T10:00:00Z"},
    )

    reopened_store = SQLiteCheckpointStore(database)
    assert await reopened_store.load("run-1") == {
        "run_id": "run-1",
        "status": "running",
        "updated_at": "2026-11-20T10:00:00Z",
    }

    await reopened_store.save(
        "run-1",
        {"run_id": "run-1", "status": "completed", "updated_at": "2026-11-20T10:01:00Z"},
    )
    assert await SQLiteCheckpointStore(database).load("run-1") == {
        "run_id": "run-1",
        "status": "completed",
        "updated_at": "2026-11-20T10:01:00Z",
    }


@pytest.mark.asyncio
async def test_checkpoint_validates_ids_and_json_values(tmp_path) -> None:
    store = SQLiteCheckpointStore(tmp_path / "ops.sqlite3")
    with pytest.raises(ValueError, match="run_id"):
        await store.load(" ")
    with pytest.raises(ValueError, match="JSON-compatible"):
        await store.save("run-2", {"invalid": object()})


def test_audit_events_survive_reopen_and_preserve_order(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    first_store = SQLiteAuditLog(database, max_events=5)
    first_store.record("local-operator", "GET", "/v1/me", "200")
    first_store.record("anonymous", "GET", "/v1/runs", "denied")

    reopened_store = SQLiteAuditLog(database, max_events=5)
    events = reopened_store.events()
    assert [event.principal_id for event in events] == [
        "local-operator",
        "anonymous",
    ]
    assert [event.outcome for event in events] == ["200", "denied"]


def test_audit_reads_are_bounded_and_fields_required(tmp_path) -> None:
    store = SQLiteAuditLog(tmp_path / "audit.sqlite3", max_events=2)
    with pytest.raises(ValueError, match="between 1 and 2"):
        store.events(3)
    with pytest.raises(ValueError, match="between 1 and 2"):
        store.events(0)
    with pytest.raises(ValueError, match="non-empty"):
        store.record(" ", "GET", "/v1/me", "200")
    store.record("one", "GET", "/one", "200")
    store.record("two", "GET", "/two", "200")
    store.record("three", "GET", "/three", "200")
    assert [event.principal_id for event in store.events()] == [
        "two",
        "three",
    ]
