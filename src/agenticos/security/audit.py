"""SQLite-backed append-only security audit events."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class AuditEvent:
    principal_id: str
    action: str
    resource: str
    outcome: str
    occurred_at: str


class AuditLog:
    """Bounded in-process audit event buffer."""

    def __init__(self, *, max_events: int = 10_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.max_events = max_events
        self._events: list[AuditEvent] = []

    def record(
        self, principal_id: str, action: str, resource: str, outcome: str
    ) -> AuditEvent:
        event = AuditEvent(
            principal_id=principal_id,
            action=action,
            resource=resource,
            outcome=outcome,
            occurred_at=datetime.now(UTC).isoformat(),
        )
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]
        return event

    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)


class SQLiteAuditLog:
    """Append-only SQLite audit event store with bounded ordered reads."""

    def __init__(self, database_path: Path | str, *, max_events: int = 10_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_events = max_events
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS security_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    principal_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10.0)

    def record(
        self, principal_id: str, action: str, resource: str, outcome: str
    ) -> AuditEvent:
        values = (principal_id, action, resource, outcome)
        if any(not value.strip() for value in values):
            raise ValueError("audit event fields must be non-empty")
        event = AuditEvent(
            principal_id=principal_id,
            action=action,
            resource=resource,
            outcome=outcome,
            occurred_at=datetime.now(UTC).isoformat(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO security_audit_events
                    (principal_id, action, resource, outcome, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.principal_id,
                    event.action,
                    event.resource,
                    event.outcome,
                    event.occurred_at,
                ),
            )
        return event

    def events(self, limit: int | None = None) -> tuple[AuditEvent, ...]:
        read_limit = self.max_events if limit is None else limit
        if read_limit < 1 or read_limit > self.max_events:
            raise ValueError(f"limit must be between 1 and {self.max_events}")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT principal_id, action, resource, outcome, occurred_at
                FROM security_audit_events
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (read_limit,),
            ).fetchall()
        return tuple(AuditEvent(*row) for row in reversed(rows))
