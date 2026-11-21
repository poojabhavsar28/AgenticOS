import sqlite3

import pytest

from agenticos.security import AuditLog
from agenticos.security.audit import AuditIntegrityError, SQLiteAuditLog


KEY = b"test-audit-signing-key-material-32-bytes!!"


def test_audit_log_is_bounded_and_returns_immutable_snapshot() -> None:
    log = AuditLog(max_events=2)
    log.record("agent-a", "execute", "tool-a", "allowed")
    log.record("agent-a", "execute", "tool-b", "denied")
    log.record("agent-b", "execute", "tool-c", "allowed")
    events = log.events()
    assert len(events) == 2
    assert events[0].resource == "tool-b"
    assert isinstance(events, tuple)


def test_sqlite_audit_chain_verifies_and_persists(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    audit = SQLiteAuditLog(database, signing_key=KEY)
    audit.record("principal-a", "sandbox.execute", "sandbox:python", "allowed")
    audit.record("principal-b", "workspace.read", "workspace:one", "denied")
    checkpoint = audit.chain_head()

    reopened = SQLiteAuditLog(database, signing_key=KEY)
    assert reopened.verify_integrity(expected_head=checkpoint)
    assert [event.principal_id for event in reopened.events()] == [
        "principal-a",
        "principal-b",
    ]


def test_sqlite_audit_chain_rejects_event_mutation(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    audit = SQLiteAuditLog(database, signing_key=KEY)
    audit.record("principal-a", "execute", "tool-a", "allowed")
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER audit_chain_no_update")
        connection.execute(
            "UPDATE security_audit_chain_events SET outcome = 'denied' WHERE sequence = 1"
        )
    with pytest.raises(AuditIntegrityError, match="authentication"):
        audit.verify_integrity()


def test_sqlite_audit_chain_detects_reordering(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    audit = SQLiteAuditLog(database, signing_key=KEY)
    audit.record("principal-a", "execute", "tool-a", "allowed")
    audit.record("principal-b", "execute", "tool-b", "allowed")
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER audit_chain_no_update")
        connection.execute("UPDATE security_audit_chain_events SET sequence = 3 WHERE sequence = 1")
    with pytest.raises(AuditIntegrityError):
        audit.verify_integrity()


def test_sqlite_audit_chain_detects_deletion_and_truncation_checkpoint(tmp_path) -> None:
    database = tmp_path / "audit.sqlite3"
    audit = SQLiteAuditLog(database, signing_key=KEY)
    audit.record("principal-a", "execute", "tool-a", "allowed")
    audit.record("principal-b", "execute", "tool-b", "allowed")
    checkpoint = audit.chain_head()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER audit_chain_no_delete")
        connection.execute("DELETE FROM security_audit_chain_events WHERE sequence = 1")
    with pytest.raises(AuditIntegrityError):
        audit.verify_integrity(expected_head=checkpoint)


def test_sqlite_audit_chain_rejects_short_signing_key(tmp_path) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SQLiteAuditLog(tmp_path / "audit.sqlite3", signing_key=b"short")
