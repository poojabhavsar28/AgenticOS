"""Backup and restore tests for SQLite-backed durable state."""

# ruff: noqa: I001

import sqlite3

import pytest

from agenticos.security.audit import SQLiteAuditLog
from agenticos.security.backup import (
    backup_sqlite_database,
    restore_sqlite_database,
)
from agenticos.security.identity import SQLiteIdentityStore


AUDIT_KEY = b"phase-17-backup-test-key-material-32-bytes"


def test_backup_restore_preserves_identity_tokens_and_workspace_grants(
    tmp_path,
) -> None:
    original = tmp_path / "operations.sqlite3"
    identities = SQLiteIdentityStore(original)
    identities.create_principal("operator")
    token_id, token = identities.issue_token("operator")
    identities.grant("operator", "workspace-a", "read", "files")

    backup = backup_sqlite_database(original, tmp_path / "backups" / "ops.bak")
    restored = restore_sqlite_database(backup, tmp_path / "recovered" / "ops.sqlite3")

    recovered = SQLiteIdentityStore(restored)
    principal = recovered.authenticate(token)
    assert principal is not None
    assert principal.principal_id == "operator"
    assert recovered.principal_for_token(token_id) == "operator"
    assert recovered.is_allowed("operator", "workspace-a", "read", "files")
    assert not recovered.is_allowed("operator", "workspace-b", "read", "files")


def test_backup_restore_preserves_audit_chain_and_checkpoint(tmp_path) -> None:
    original = tmp_path / "audit.sqlite3"
    audit = SQLiteAuditLog(original, signing_key=AUDIT_KEY)
    audit.record("operator", "workspace.read", "workspace-a", "allowed")
    audit.record("operator", "workspace.write", "workspace-a", "denied")
    expected_head = audit.chain_head()

    backup = backup_sqlite_database(original, tmp_path / "audit.bak")
    restored = restore_sqlite_database(backup, tmp_path / "restored-audit.sqlite3")
    recovered = SQLiteAuditLog(restored, signing_key=AUDIT_KEY)

    assert recovered.verify_integrity(expected_head=expected_head)
    assert len(recovered.events()) == 2


def test_backup_rejects_corrupt_source_without_replacing_destination(tmp_path) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    with sqlite3.connect(corrupt) as connection:
        connection.execute("CREATE TABLE example (value TEXT)")
    corrupt.write_bytes(b"not a sqlite database")
    destination = tmp_path / "existing.bak"
    destination.write_bytes(b"preserve existing backup")

    with pytest.raises(sqlite3.DatabaseError):
        backup_sqlite_database(corrupt, destination)

    assert destination.read_bytes() == b"preserve existing backup"


def test_backup_rejects_symlinked_source_and_destination(tmp_path) -> None:
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE example (value TEXT)")
    source_link = tmp_path / "source-link.sqlite3"
    destination_link = tmp_path / "destination-link.sqlite3"
    try:
        source_link.symlink_to(source)
        destination_link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")

    with pytest.raises(ValueError, match="source"):
        backup_sqlite_database(source_link, tmp_path / "backup.sqlite3")
    with pytest.raises(ValueError, match="destination"):
        backup_sqlite_database(source, destination_link)


def test_backup_output_is_private_on_posix(tmp_path) -> None:
    import os
    import stat

    if os.name == "nt":
        pytest.skip("POSIX mode bits are not an NTFS ACL check")
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE example (value TEXT)")
    backup = backup_sqlite_database(source, tmp_path / "backup.sqlite3")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_backup_restore_preserves_run_checkpoints(tmp_path) -> None:
    from agenticos.runtime.checkpoints import SQLiteCheckpointStore

    original = tmp_path / "operations.sqlite3"
    store = SQLiteCheckpointStore(original)
    await store.save(
        "run-42",
        {"run_id": "run-42", "status": "completed", "result": "verified"},
    )

    backup = backup_sqlite_database(original, tmp_path / "operations.bak")
    restored = restore_sqlite_database(backup, tmp_path / "recovered-operations.sqlite3")

    recovered = SQLiteCheckpointStore(restored)
    assert await recovered.load("run-42") == {
        "run_id": "run-42",
        "status": "completed",
        "result": "verified",
    }
