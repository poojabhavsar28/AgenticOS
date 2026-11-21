"""SQLite-backed audit events and tamper-evident chained audit storage."""

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agenticos.security.sqlite_storage import (
    harden_sqlite_files,
    prepare_private_sqlite_database,
)


@dataclass(frozen=True)
class AuditEvent:
    principal_id: str
    action: str
    resource: str
    outcome: str
    occurred_at: str


class AuditIntegrityError(RuntimeError):
    """Raised when the persisted audit chain cannot be verified."""


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


def load_or_create_audit_key(key_path: Path | str) -> bytes:
    """Load a private HMAC key or atomically create it with owner-only access."""
    import os
    import secrets
    import stat

    path = Path(key_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise PermissionError("Audit signing key must not be a symbolic link")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        key = secrets.token_bytes(32)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return key
    file_stat = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(file_stat.st_mode):
        raise PermissionError("Audit signing key must be a regular file")
    if os.name != "nt":
        if file_stat.st_uid != os.getuid() or stat.S_IMODE(file_stat.st_mode) & 0o077:
            raise PermissionError("Audit signing key must be owner-only and service-owned")
    key = path.read_bytes()
    if len(key) < 32:
        raise ValueError("Audit signing key file is invalid")
    return key


class SQLiteAuditLog:
    """Append-only HMAC-chained audit store.

    The HMAC key must be supplied by the operator and stored outside this database.
    To detect deletion of the newest rows, callers must retain the returned chain
    head in an independent trusted location and pass it to verify_integrity().
    """

    _GENESIS = "0" * 64

    def __init__(
        self,
        database_path: Path | str,
        *,
        signing_key: bytes | None = None,
        max_events: int = 10_000,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.database_path = prepare_private_sqlite_database(database_path)
        if signing_key is None:
            key_path = self.database_path.with_name(
                self.database_path.name + ".audit.key"
            )
            signing_key = load_or_create_audit_key(key_path)
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("Audit signing key must contain at least 32 bytes")
        self._signing_key = signing_key
        self.max_events = max_events
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS security_audit_chain_events (
                    sequence INTEGER PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    previous_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS audit_chain_no_update
                BEFORE UPDATE ON security_audit_chain_events
                BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS audit_chain_no_delete
                BEFORE DELETE ON security_audit_chain_events
                BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        try:
            harden_sqlite_files(self.database_path)
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def _canonical_payload(
        sequence: int,
        principal_id: str,
        action: str,
        resource: str,
        outcome: str,
        occurred_at: str,
        previous_digest: str,
    ) -> bytes:
        return json.dumps(
            {
                "sequence": sequence,
                "principal_id": principal_id,
                "action": action,
                "resource": resource,
                "outcome": outcome,
                "occurred_at": occurred_at,
                "previous_digest": previous_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def _digest(self, payload: bytes) -> str:
        return hmac.new(self._signing_key, payload, hashlib.sha256).hexdigest()

    def record(
        self, principal_id: str, action: str, resource: str, outcome: str
    ) -> AuditEvent:
        values = (principal_id, action, resource, outcome)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("audit event fields must be non-empty strings")
        event = AuditEvent(
            principal_id=principal_id,
            action=action,
            resource=resource,
            outcome=outcome,
            occurred_at=datetime.now(UTC).isoformat(),
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT sequence, event_digest
                FROM security_audit_chain_events ORDER BY sequence DESC LIMIT 1
                """
            ).fetchone()
            sequence = 1 if previous is None else previous[0] + 1
            previous_digest = self._GENESIS if previous is None else previous[1]
            payload = self._canonical_payload(
                sequence,
                event.principal_id,
                event.action,
                event.resource,
                event.outcome,
                event.occurred_at,
                previous_digest,
            )
            event_digest = self._digest(payload)
            connection.execute(
                """
                INSERT INTO security_audit_chain_events
                    (sequence, principal_id, action, resource, outcome, occurred_at,
                     previous_digest, event_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    event.principal_id,
                    event.action,
                    event.resource,
                    event.outcome,
                    event.occurred_at,
                    previous_digest,
                    event_digest,
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
                FROM (
                    SELECT sequence, principal_id, action, resource, outcome, occurred_at
                    FROM security_audit_chain_events ORDER BY sequence DESC LIMIT ?
                ) ORDER BY sequence ASC
                """,
                (read_limit,),
            ).fetchall()
        return tuple(AuditEvent(*row) for row in rows)

    def chain_head(self) -> str:
        """Return the current chain head for storage in an independent trusted system."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT event_digest FROM security_audit_chain_events
                ORDER BY sequence DESC LIMIT 1
                """
            ).fetchone()
        return self._GENESIS if row is None else str(row[0])

    def verify_integrity(self, *, expected_head: str | None = None) -> bool:
        """Verify every link and optionally compare against an external checkpoint."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, principal_id, action, resource, outcome, occurred_at,
                       previous_digest, event_digest
                FROM security_audit_chain_events ORDER BY sequence ASC
                """
            ).fetchall()
        previous_digest = self._GENESIS
        for expected_sequence, row in enumerate(rows, start=1):
            (
                sequence,
                principal_id,
                action,
                resource,
                outcome,
                occurred_at,
                stored_previous,
                stored_digest,
            ) = row
            if sequence != expected_sequence or stored_previous != previous_digest:
                raise AuditIntegrityError("Audit sequence or previous-event link is invalid")
            payload = self._canonical_payload(
                sequence,
                principal_id,
                action,
                resource,
                outcome,
                occurred_at,
                stored_previous,
            )
            calculated = self._digest(payload)
            if not hmac.compare_digest(calculated, stored_digest):
                raise AuditIntegrityError("Audit event authentication failed")
            previous_digest = stored_digest
        if expected_head is not None and not hmac.compare_digest(
            previous_digest, expected_head
        ):
            raise AuditIntegrityError("Audit chain head differs from trusted checkpoint")
        return True
