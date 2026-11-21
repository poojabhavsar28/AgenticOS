"""Persistent, one-time human approvals for sandbox execution requests."""

# ruff: noqa: E501  # SQL query literals are clearer as contiguous statements.

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from agenticos.security.sandbox import SandboxExecutionRequest


class ApprovalError(PermissionError):
    """Raised when an execution approval is missing, invalid, or unusable."""


class SQLiteExecutionApprovalStore:
    """SQLite-backed approvals; only the one-time credential digest is persisted."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sandbox_execution_approvals (
                    approval_id TEXT PRIMARY KEY,
                    public_id TEXT UNIQUE,
                    requester_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    approver_id TEXT,
                    consumed_at REAL
                )
                """
            )
            columns = {row["name"] for row in connection.execute(
                "PRAGMA table_info(sandbox_execution_approvals)"
            ).fetchall()}
            if "public_id" not in columns:
                connection.execute(
                    "ALTER TABLE sandbox_execution_approvals ADD COLUMN public_id TEXT"
                )
            if "request_json" not in columns:
                connection.execute(
                    "ALTER TABLE sandbox_execution_approvals ADD COLUMN request_json TEXT"
                )
            # Revoke legacy records whose public_id contains the former bearer token.
            # New review IDs are 32-character UUID hex strings.
            connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET public_id = lower(hex(randomblob(16))),
                       status = 'revoked', request_json = NULL
                   WHERE public_id IS NOT NULL AND length(public_id) > 32"""
            )
            connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET public_id = lower(hex(randomblob(16))),
                       status = 'revoked', request_json = NULL
                   WHERE public_id IS NULL"""
            )
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _approval_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def fingerprint(request: SandboxExecutionRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def create(
        self, requester_id: str, request: SandboxExecutionRequest, *, ttl_seconds: int
    ) -> dict[str, str]:
        if not requester_id.strip():
            raise ValueError("Requester identity must be non-empty")
        if not 1 <= ttl_seconds <= 900:
            raise ValueError("Approval lifetime must be between 1 and 900 seconds")
        now = time.time()
        review_id = uuid4().hex
        approval_token = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sandbox_execution_approvals
                    (approval_id, public_id, requester_id, request_hash, request_json,
                     created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    self._approval_digest(approval_token),
                    review_id,
                    requester_id,
                    self.fingerprint(request),
                    json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                    now,
                    now + ttl_seconds,
                ),
            )
        return {"review_id": review_id, "approval_token": approval_token}

    def list_pending(self) -> list[dict[str, object]]:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET status = 'expired', request_json = NULL
                   WHERE status = 'pending' AND expires_at <= ?""",
                (now,),
            )
            rows = connection.execute(
                """SELECT public_id, requester_id, request_hash, request_json,
                          created_at, expires_at, status
                   FROM sandbox_execution_approvals
                   WHERE status = 'pending' AND expires_at > ?
                     AND request_json IS NOT NULL ORDER BY created_at ASC LIMIT 100""",
                (now,),
            ).fetchall()
        return [
            {key: value for key, value in self._review_record(row).items() if key != "request"}
            for row in rows
        ]

    def get_review(self, review_id: str) -> dict[str, object] | None:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT public_id, requester_id, request_hash, request_json,
                          created_at, expires_at, status
                   FROM sandbox_execution_approvals WHERE public_id = ?""",
                (review_id,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now and row["request_json"] is not None:
                connection.execute(
                    """UPDATE sandbox_execution_approvals
                       SET status = 'expired', request_json = NULL
                       WHERE public_id = ? AND status IN ('pending', 'approved')""",
                    (review_id,),
                )
                row = connection.execute(
                    """SELECT public_id, requester_id, request_hash, request_json,
                              created_at, expires_at, status
                       FROM sandbox_execution_approvals WHERE public_id = ?""",
                    (review_id,),
                ).fetchone()
        return self._review_record(row)

    @staticmethod
    def _review_record(row: sqlite3.Row) -> dict[str, object]:
        return {
            "review_id": row["public_id"],
            "requester_id": row["requester_id"],
            "request_hash": row["request_hash"],
            "request": json.loads(row["request_json"]) if row["request_json"] else None,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "status": row["status"],
        }

    def approve(
        self, review_id: str, approver_id: str, *, allowed_approvers: frozenset[str]
    ) -> None:
        if not approver_id or approver_id not in allowed_approvers:
            raise ApprovalError("Principal is not authorized to approve sandbox execution")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT requester_id, status, expires_at
                   FROM sandbox_execution_approvals WHERE public_id = ?""",
                (review_id,),
            ).fetchone()
            if row is None or row["status"] != "pending" or row["expires_at"] <= now:
                raise ApprovalError("Approval is missing, expired, or no longer pending")
            if row["requester_id"] == approver_id:
                raise ApprovalError("Requester cannot approve their own execution")
            updated = connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET status = 'approved', approver_id = ?, request_json = NULL
                   WHERE public_id = ? AND status = 'pending' AND expires_at > ?""",
                (approver_id, review_id, now),
            )
            if updated.rowcount != 1:
                raise ApprovalError("Approval could not be applied")

    def consume(
        self, approval_token: str, requester_id: str, request: SandboxExecutionRequest
    ) -> None:
        now = time.time()
        digest = self._approval_digest(approval_token)
        request_hash = self.fingerprint(request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT requester_id, request_hash, status, expires_at
                   FROM sandbox_execution_approvals WHERE approval_id = ?""",
                (digest,),
            ).fetchone()
            if (
                row is None or row["requester_id"] != requester_id
                or row["request_hash"] != request_hash
                or row["status"] != "approved" or row["expires_at"] <= now
            ):
                raise ApprovalError("A valid, matching, unused human approval is required")
            updated = connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET status = 'consumed', consumed_at = ?, request_json = NULL
                   WHERE approval_id = ? AND status = 'approved' AND expires_at > ?""",
                (now, digest, now),
            )
            if updated.rowcount != 1:
                raise ApprovalError("Approval has already been consumed")


class HumanApprovalManager:
    """Expose request/review/approve/consume operations around the persistent store."""

    def __init__(
        self, store: SQLiteExecutionApprovalStore, *, allowed_approvers: set[str]
    ) -> None:
        if not allowed_approvers or any(not item.strip() for item in allowed_approvers):
            raise ValueError("At least one valid human approver must be configured")
        self.store = store
        self.allowed_approvers = frozenset(allowed_approvers)

    def request(
        self, requester_id: str, request: SandboxExecutionRequest, *, ttl_seconds: int = 300
    ) -> dict[str, str]:
        return self.store.create(requester_id, request, ttl_seconds=ttl_seconds)

    def list_pending(self) -> list[dict[str, object]]:
        return self.store.list_pending()

    def get_review(self, review_id: str) -> dict[str, object] | None:
        return self.store.get_review(review_id)

    def approve(self, review_id: str, approver_id: str) -> None:
        self.store.approve(review_id, approver_id, allowed_approvers=self.allowed_approvers)

    def consume(
        self, approval_token: str, requester_id: str, request: SandboxExecutionRequest
    ) -> None:
        self.store.consume(approval_token, requester_id, request)
