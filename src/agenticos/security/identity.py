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

    DEFAULT_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
    MAX_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60

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
                    revoked_at INTEGER,
                    expires_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_identity_tokens_active
                    ON identity_tokens(revoked_at, principal_id);
                CREATE TABLE IF NOT EXISTS configured_identity_tokens (
                    principal_id TEXT PRIMARY KEY REFERENCES principals(principal_id),
                    token_id TEXT NOT NULL UNIQUE REFERENCES identity_tokens(token_id)
                );
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
            token_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(identity_tokens)")
            }
            if "expires_at" not in token_columns:
                connection.execute(
                    "ALTER TABLE identity_tokens ADD COLUMN expires_at INTEGER"
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
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError(f"{field} must be canonical and contain no control characters")
        maximum_lengths = {
            "principal_id": 256,
            "workspace_id": 256,
            "action": 128,
            "resource": 2048,
            "token_id": 256,
        }
        maximum = maximum_lengths.get(field)
        if maximum is not None and len(value) > maximum:
            raise ValueError(f"{field} must not exceed {maximum} characters")
        return value

    @staticmethod
    def _expiry_for_ttl(ttl_seconds: int, now: int) -> int:
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or ttl_seconds < 1
            or ttl_seconds > SQLiteIdentityStore.MAX_TOKEN_TTL_SECONDS
        ):
            raise ValueError(
                "ttl_seconds must be between 1 second and 90 days"
            )
        if ttl_seconds > (2**63 - 1) - now:
            raise ValueError("ttl_seconds exceeds SQLite's supported timestamp range")
        return now + ttl_seconds

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

    def issue_token(
        self, principal_id: str, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS
    ) -> tuple[str, str]:
        """Return (opaque token ID, bearer secret); the secret is returned only once."""
        principal_id = self._required(principal_id, "principal_id")
        token_id = uuid4().hex
        token = "agx_" + secrets.token_urlsafe(32)
        verifier = hashlib.sha256(token.encode("utf-8")).digest()
        now = int(time.time())
        expires_at = self._expiry_for_ttl(ttl_seconds, now)
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
                INSERT INTO identity_tokens(
                    token_id, principal_id, verifier, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (token_id, principal_id, verifier, now, expires_at),
            )
        return token_id, token

    def token_expiry(self, token_id: str) -> int | None:
        token_id = self._required(token_id, "token_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at FROM identity_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        return None if row is None or row["expires_at"] is None else int(row["expires_at"])

    def register_configured_token(self, principal_id: str, token: str) -> None:
        """Register the configured credential and revoke its previous configured value."""
        principal_id = self._required(principal_id, "principal_id")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > self.MAX_BEARER_TOKEN_LENGTH
            or any(character.isspace() for character in token)
        ):
            raise ValueError(
                "Configured token must be non-empty, contain no whitespace, "
                f"and not exceed {self.MAX_BEARER_TOKEN_LENGTH} characters"
            )
        verifier = hashlib.sha256(token.encode("utf-8")).digest()
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO principals(principal_id, enabled, created_at)
                VALUES (?, 1, ?)
                ON CONFLICT(principal_id) DO NOTHING
                """,
                (principal_id, now),
            )
            current = connection.execute(
                """
                SELECT token_id FROM identity_tokens
                WHERE principal_id = ? AND verifier = ? AND revoked_at IS NULL
                """,
                (principal_id, verifier),
            ).fetchone()
            previous = connection.execute(
                "SELECT token_id FROM configured_identity_tokens WHERE principal_id = ?",
                (principal_id,),
            ).fetchone()
            if previous is not None and (
                current is None or str(previous["token_id"]) != str(current["token_id"])
            ):
                connection.execute(
                    """
                    UPDATE identity_tokens SET revoked_at = ?
                    WHERE token_id = ? AND revoked_at IS NULL
                    """,
                    (now, previous["token_id"]),
                )
            if current is None:
                token_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO identity_tokens(token_id, principal_id, verifier, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (token_id, principal_id, verifier, now),
                )
            else:
                token_id = str(current["token_id"])
            connection.execute(
                """
                INSERT INTO configured_identity_tokens(principal_id, token_id)
                VALUES (?, ?)
                ON CONFLICT(principal_id) DO UPDATE SET token_id = excluded.token_id
                """,
                (principal_id, token_id),
            )

    MAX_BEARER_TOKEN_LENGTH = 4096

    def authenticate(self, token: str | None) -> AuthenticatedPrincipal | None:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > self.MAX_BEARER_TOKEN_LENGTH
        ):
            return None
        supplied = hashlib.sha256(token.encode("utf-8")).digest()
        match: str | None = None
        ambiguous = False
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.verifier, t.principal_id
                FROM identity_tokens AS t
                JOIN principals AS p ON p.principal_id = t.principal_id
                WHERE t.revoked_at IS NULL AND p.enabled = 1
                  AND (t.expires_at IS NULL OR t.expires_at > ?)
                """,
                (int(time.time()),),
            ).fetchall()
        for row in rows:
            if hmac.compare_digest(bytes(row["verifier"]), supplied):
                principal_id = str(row["principal_id"])
                if match is not None and principal_id != match:
                    ambiguous = True
                match = principal_id
        # Never resolve a duplicated bearer secret by database row order:
        # doing so could accidentally authenticate as a more privileged identity.
        if ambiguous:
            return None
        return AuthenticatedPrincipal(principal_id=match) if match else None

    def principal_for_token(self, token_id: str) -> str | None:
        """Return the owning principal for an opaque token ID, if it exists."""
        token_id = self._required(token_id, "token_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT principal_id FROM identity_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        return str(row["principal_id"]) if row is not None else None

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

    def rotate_token(
        self, token_id: str, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS
    ) -> tuple[str, str]:
        """Atomically revoke one token and issue its replacement for the same principal."""
        token_id = self._required(token_id, "token_id")
        new_token_id = uuid4().hex
        new_token = "agx_" + secrets.token_urlsafe(32)
        verifier = hashlib.sha256(new_token.encode("utf-8")).digest()
        now = int(time.time())
        expires_at = self._expiry_for_ttl(ttl_seconds, now)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.principal_id, p.enabled
                FROM identity_tokens AS t
                JOIN principals AS p ON p.principal_id = t.principal_id
                WHERE t.token_id = ? AND t.revoked_at IS NULL
                  AND (t.expires_at IS NULL OR t.expires_at > ?)
                """,
                (token_id, now),
            ).fetchone()
            if row is None or not row["enabled"]:
                raise PermissionDenied(
                    "Cannot rotate an unknown, revoked, or disabled credential"
                )
            revoked = connection.execute(
                """
                UPDATE identity_tokens
                SET revoked_at = ?
                WHERE token_id = ? AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (now, token_id, now),
            )
            # Another concurrent rotation/revocation may have consumed this
            # token after the initial read. Only the request that atomically
            # changes the active row may create a replacement credential.
            if revoked.rowcount != 1:
                raise PermissionDenied(
                    "Cannot rotate a credential that was concurrently revoked or rotated"
                )
            connection.execute(
                """
                INSERT INTO identity_tokens(
                    token_id, principal_id, verifier, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (new_token_id, row["principal_id"], verifier, now, expires_at),
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
