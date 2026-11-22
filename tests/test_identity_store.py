"""Persistence and security tests for multi-principal identity and grants."""

import pytest

from agenticos.security.identity import SQLiteIdentityStore
from agenticos.security.policy import PermissionDenied


def test_principals_and_tokens_survive_reopening(tmp_path) -> None:
    path = tmp_path / "identity.sqlite3"
    store = SQLiteIdentityStore(path)
    store.create_principal("alice")
    token_id, token = store.issue_token("alice")

    reopened = SQLiteIdentityStore(path)
    principal = reopened.authenticate(token)

    assert token_id
    assert principal is not None
    assert principal.principal_id == "alice"


def test_multiple_principals_have_independent_tokens(tmp_path) -> None:
    store = SQLiteIdentityStore(tmp_path / "identity.sqlite3")
    store.create_principal("alice")
    store.create_principal("bob")
    _, alice_token = store.issue_token("alice")
    _, bob_token = store.issue_token("bob")

    assert store.authenticate(alice_token).principal_id == "alice"
    assert store.authenticate(bob_token).principal_id == "bob"


def test_raw_bearer_token_is_not_stored(tmp_path) -> None:
    path = tmp_path / "identity.sqlite3"
    store = SQLiteIdentityStore(path)
    store.create_principal("alice")
    _, token = store.issue_token("alice")

    raw_database = path.read_bytes()
    assert token.encode() not in raw_database


def test_token_rotation_invalidates_old_token_immediately(tmp_path) -> None:
    store = SQLiteIdentityStore(tmp_path / "identity.sqlite3")
    store.create_principal("alice")
    old_id, old_token = store.issue_token("alice")

    new_id, new_token = store.rotate_token(old_id)

    assert store.authenticate(old_token) is None
    assert store.authenticate(new_token).principal_id == "alice"
    assert new_id != old_id


def test_revocation_and_principal_disable_invalidate_credentials(tmp_path) -> None:
    store = SQLiteIdentityStore(tmp_path / "identity.sqlite3")
    store.create_principal("alice")
    token_id, token = store.issue_token("alice")
    store.revoke_token(token_id)
    assert store.authenticate(token) is None

    _, second_token = store.issue_token("alice")
    store.set_principal_enabled("alice", False)
    assert store.authenticate(second_token) is None
    with pytest.raises(PermissionDenied):
        store.issue_token("alice")


def test_workspace_grants_are_persistent_exact_and_default_deny(tmp_path) -> None:
    path = tmp_path / "identity.sqlite3"
    store = SQLiteIdentityStore(path)
    store.create_principal("alice")
    store.create_principal("bob")
    store.grant("alice", "workspace-a", "read", "files")

    reopened = SQLiteIdentityStore(path)
    assert reopened.is_allowed("alice", "workspace-a", "read", "files")
    assert not reopened.is_allowed("alice", "workspace-b", "read", "files")
    assert not reopened.is_allowed("bob", "workspace-a", "read", "files")
    assert not reopened.is_allowed("alice", "workspace-a", "write", "files")


def test_workspace_grant_revocation_is_persistent(tmp_path) -> None:
    path = tmp_path / "identity.sqlite3"
    store = SQLiteIdentityStore(path)
    store.create_principal("alice")
    store.grant("alice", "workspace-a", "read", "files")
    store.revoke_grant("alice", "workspace-a", "read", "files")

    reopened = SQLiteIdentityStore(path)
    assert not reopened.is_allowed("alice", "workspace-a", "read", "files")


def test_unknown_or_disabled_principal_cannot_receive_grants_or_tokens(tmp_path) -> None:
    store = SQLiteIdentityStore(tmp_path / "identity.sqlite3")
    with pytest.raises(PermissionDenied):
        store.issue_token("missing")
    with pytest.raises(KeyError):
        store.grant("missing", "workspace-a", "read", "files")



def test_issued_token_expires_and_rotation_gets_a_fresh_lifetime(tmp_path):
    import time

    store = SQLiteIdentityStore(tmp_path / "identity.sqlite3")
    store.create_principal("alice")
    token_id, token = store.issue_token("alice", ttl_seconds=1)
    expiry = store.token_expiry(token_id)
    assert expiry is not None
    assert expiry <= int(time.time()) + 1
    time.sleep(1.05)
    assert store.authenticate(token) is None
    with pytest.raises(PermissionDenied):
        store.rotate_token(token_id)

    second_id, second_token = store.issue_token("alice", ttl_seconds=60)
    replacement_id, replacement = store.rotate_token(second_id, ttl_seconds=120)
    assert store.authenticate(second_token) is None
    assert store.authenticate(replacement).principal_id == "alice"
    assert store.token_expiry(replacement_id) >= int(time.time()) + 119


def test_token_ttl_must_be_a_positive_integer(tmp_path):
    store = SQLiteIdentityStore(tmp_path / "identity.sqlite3")
    store.create_principal("alice")
    for ttl in (0, -1, True, 1.5, 2**63):
        with pytest.raises(ValueError, match="ttl_seconds"):
            store.issue_token("alice", ttl_seconds=ttl)

    token_id, _ = store.issue_token("alice", ttl_seconds=60)
    with pytest.raises(ValueError, match="SQLite"):
        store.rotate_token(token_id, ttl_seconds=2**63)



def test_existing_identity_database_is_migrated_with_expiry_column(tmp_path):
    import sqlite3

    path = tmp_path / "legacy-identities.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE identity_tokens (
                token_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                verifier BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                revoked_at INTEGER
            )
            """
        )

    SQLiteIdentityStore(path)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(identity_tokens)")
        }
    assert "expires_at" in columns
