"""Tests for durable run event storage."""

import pytest

from agenticos.runtime.events import SQLiteRunEventStore


def test_events_persist_in_order_and_are_scoped_to_run(tmp_path) -> None:
    database = tmp_path / "operations.sqlite3"
    first = SQLiteRunEventStore(database)
    queued = first.append("run-a", "queued", {"status": "queued"})
    started = first.append("run-a", "started")
    first.append("run-b", "queued")

    reopened = SQLiteRunEventStore(database)
    events = reopened.list_events("run-a")
    assert [event.event_type for event in events] == ["queued", "started"]
    assert [event.event_id for event in events] == [queued.event_id, started.event_id]
    assert reopened.list_events("run-a", after_event_id=queued.event_id)[0].event_type == "started"
    assert reopened.list_events("run-b")[0].event_type == "queued"


def test_event_store_enforces_retention_and_read_limits(tmp_path) -> None:
    store = SQLiteRunEventStore(tmp_path / "events.sqlite3", max_events=2)
    store.append("run-a", "queued")
    store.append("run-a", "started")
    store.append("run-a", "completed")

    events = store.list_events("run-a")
    assert [event.event_type for event in events] == ["started", "completed"]
    with pytest.raises(ValueError, match="between 1 and 500"):
        store.list_events("run-a", limit=501)
    with pytest.raises(ValueError, match="non-negative"):
        store.list_events("run-a", after_event_id=-1)


def test_event_store_rejects_invalid_and_oversized_payloads(tmp_path) -> None:
    store = SQLiteRunEventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError, match="non-empty"):
        store.append("", "queued")
    with pytest.raises(ValueError, match="JSON-compatible"):
        store.append("run-a", "queued", {"invalid": object()})
    with pytest.raises(ValueError, match="4096"):
        store.append("run-a", "queued", {"detail": "x" * 4100})
