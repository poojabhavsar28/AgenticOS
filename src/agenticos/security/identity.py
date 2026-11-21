"""Persistent local principals, bearer credentials, and workspace grants."""

import hashlib
import hmac
import secrets
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from agenticos.security.auth import AuthenticatedPrincipal
from agenticos.security.policy import PermissionDenied
from agenticos.security.sqlite_storage import prepare_private_sqlite_database


class SQLiteIdentityStore:
    """Persist principal state, one-way token verifiers, and exact workspace grants."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = prepare_private_sqlite_database(database_path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS principals (
                    principal_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_tokens (
                    token_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
                    verifier BLOB NOT NULL,
                    created_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_identity_tokens_active
                    ON identity_tokens(revoked_at, principal_id);
                CREATE TABLE IF NOT EXISTS workspace_grants (
                    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
                    workspace_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (principal_id, workspace_id, action, resource)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _required(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    def create_principal(self, principal_id: str) -> None:
        principal_id = self._required(principal_id, "principal_id")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO principals(principal_id, enabled, created_at) VALUES (?, 1, ?)",
                (principal_id, int(time.time())),
            )

    def set_principal_enabled(self, principal_id: str, enabled: bool) -> None:
        principal_id = self._required(principal_id, "principal_id")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE principals SET enabled = ? WHERE principal_id = ?",
                (int(enabled), principal_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown principal: {principal_id}")

    def issue_token(self, principal_id: str) -> tuple[str, str]:
        """Return (opaque token ID, bearer secret); the secret is returned only once."""
        principal_id = self._required(principal_id, "principal_id")
        token_id = uuid4().hex
        token = "agx_" + secrets.token_urlsafe(32)
        verifier = hashlib.sha256(token.encode("utf-8")).digest()
        with self._connect() as connection:
            principal = connection.execute(
                "SELECT enabled FROM principals WHERE principal_id = ?",
                (principal_id,),
            ).fetchone()
            if principal is None or not principal["enabled"]:
                raise PermissionDenied(
                    "Cannot issue credentials for an unknown or disabled principal"
                )
            connection.execute(
                """
                INSERT INTO identity_tokens(token_id, principal_id, verifier, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_id, principal_id, verifier, int(time.time())),
            )
        return token_id, token

    def authenticate(self, token: str | None) -> AuthenticatedPrincipal | None:
        if not isinstance(token, str) or not token.startswith("agx_"):
            return None
        supplied = hashlib.sha256(token.encode("utf-8")).digest()
        match: str | None = None
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.verifier, t.principal_id
                FROM identity_tokens AS t
                JOIN principals AS p ON p.principal_id = t.principal_id
                WHERE t.revoked_at IS NULL AND p.enabled = 1
                """
            ).fetchall()
        for row in rows:
            if hmac.compare_digest(bytes(row["verifier"]), supplied):
                match = str(row["principal_id"])
        return AuthenticatedPrincipal(principal_id=match) if match else None

    def revoke_token(self, token_id: str) -> None:
        token_id = self._required(token_id, "token_id")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE identity_tokens
                SET revoked_at = ? WHERE token_id = ? AND revoked_at IS NULL
                """,
                (int(time.time()), token_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown or already revoked token: {token_id}")

    def rotate_token(self, token_id: str) -> tuple[str, str]:
        """Atomically revoke one token and issue its replacement for the same principal."""
        token_id = self._required(token_id, "token_id")
        new_token_id = uuid4().hex
        new_token = "agx_" + secrets.token_urlsafe(32)
        verifier = hashlib.sha256(new_token.encode("utf-8")).digest()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.principal_id, p.enabled
                FROM identity_tokens AS t
                JOIN principals AS p ON p.principal_id = t.principal_id
                WHERE t.token_id = ? AND t.revoked_at IS NULL
                """,
                (token_id,),
            ).fetchone()
            if row is None or not row["enabled"]:
                raise PermissionDenied(
                    "Cannot rotate an unknown, revoked, or disabled credential"
                )
            connection.execute(
                """
                UPDATE identity_tokens
                SET revoked_at = ? WHERE token_id = ? AND revoked_at IS NULL
                """,
                (int(time.time()), token_id),
            )
            connection.execute(
                """
                INSERT INTO identity_tokens(token_id, principal_id, verifier, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (new_token_id, row["principal_id"], verifier, int(time.time())),
            )
        return new_token_id, new_token

    def grant(
        self, principal_id: str, workspace_id: str, action: str, resource: str
    ) -> None:
        values = (
            self._required(principal_id, "principal_id"),
            self._required(workspace_id, "workspace_id"),
            self._required(action, "action"),
            self._required(resource, "resource"),
        )
        with self._connect() as connection:
            principal = connection.execute(
                "SELECT enabled FROM principals WHERE principal_id = ?", (values[0],)
            ).fetchone()
            if principal is None:
                raise KeyError(f"Unknown principal: {values[0]}")
            connection.execute(
                """
                INSERT INTO workspace_grants(
                    principal_id, workspace_id, action, resource, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(principal_id, workspace_id, action, resource) DO NOTHING
                """,
                (*values, int(time.time())),
            )

    def revoke_grant(
        self, principal_id: str, workspace_id: str, action: str, resource: str
    ) -> None:
        values = tuple(
            self._required(value, field)
            for value, field in zip(
                (principal_id, workspace_id, action, resource),
                ("principal_id", "workspace_id", "action", "resource"),
                strict=True,
            )
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM workspace_grants
                WHERE principal_id = ? AND workspace_id = ? AND action = ? AND resource = ?
                """,
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError("Workspace grant does not exist")

    def is_allowed(
        self, principal_id: str, workspace_id: str, action: str, resource: str
    ) -> bool:
        values = (
            self._required(principal_id, "principal_id"),
            self._required(workspace_id, "workspace_id"),
            self._required(action, "action"),
            self._required(resource, "resource"),
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM workspace_grants AS g
                JOIN principals AS p ON p.principal_id = g.principal_id
                WHERE g.principal_id = ? AND g.workspace_id = ?
                  AND g.action = ? AND g.resource = ? AND p.enabled = 1
                """,
                values,
            ).fetchone()
        return row is not None

    def authorize(
        self, principal_id: str, workspace_id: str, action: str, resource: str
    ) -> None:
        if not self.is_allowed(principal_id, workspace_id, action, resource):
            raise PermissionDenied(
                f"Permission denied for principal {principal_id} in workspace {workspace_id}"
            )
