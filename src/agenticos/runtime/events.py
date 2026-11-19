"""Durable, bounded run lifecycle events stored locally in SQLite."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunEvent:
    event_id: int
    run_id: str
    event_type: str
    created_at: str
    data: dict[str, Any]


class SQLiteRunEventStore:
    """Append operational events and retain a bounded global event history."""

    def __init__(self, database_path: Path | str, *, max_events: int = 10_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.database_path = Path(database_path)
        self.max_events = max_events
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_run_id_event_id "
                "ON run_events(run_id, event_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def append(
        self, run_id: str, event_type: str, data: dict[str, Any] | None = None
    ) -> RunEvent:
        if not run_id.strip() or not event_type.strip():
            raise ValueError("run_id and event_type must be non-empty")
        payload = data or {}
        try:
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("event data must contain JSON-compatible values") from exc
        if len(serialized) > 4_096:
            raise ValueError("event data exceeds the 4096-character limit")
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO run_events(run_id, event_type, created_at, data_json) "
                "VALUES (?, ?, ?, ?)",
                (run_id, event_type, created_at, serialized),
            )
            connection.execute(
                """DELETE FROM run_events WHERE event_id NOT IN (
                    SELECT event_id FROM run_events ORDER BY event_id DESC LIMIT ?
                )""",
                (self.max_events,),
            )
            event_id = int(cursor.lastrowid)
        return RunEvent(event_id, run_id, event_type, created_at, payload)

    def list_events(
        self, run_id: str, *, after_event_id: int = 0, limit: int = 100
    ) -> list[RunEvent]:
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if after_event_id < 0:
            raise ValueError("after_event_id must be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT event_id, run_id, event_type, created_at, data_json
                FROM run_events WHERE run_id = ? AND event_id > ?
                ORDER BY event_id LIMIT ?""",
                (run_id, after_event_id, limit),
            ).fetchall()
        events = []
        for row in rows:
            data = json.loads(row["data_json"])
            if not isinstance(data, dict):
                raise ValueError("stored run event data must be an object")
            events.append(
                RunEvent(
                    int(row["event_id"]),
                    row["run_id"],
                    row["event_type"],
                    row["created_at"],
                    data,
                )
            )
        return events
