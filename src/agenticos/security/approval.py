"""Persistent, one-time human approvals for sandbox execution requests."""

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from agenticos.security.sandbox import SandboxExecutionRequest


class ApprovalError(PermissionError):
    """Raised when an execution approval is missing, invalid, or unusable."""


class SQLiteExecutionApprovalStore:
    """SQLite-backed approval records; source code is never stored, only its hash."""

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
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(sandbox_execution_approvals)").fetchall()}
            if "public_id" not in columns:
                connection.execute("ALTER TABLE sandbox_execution_approvals ADD COLUMN public_id TEXT")
            if "request_json" not in columns:
                connection.execute("ALTER TABLE sandbox_execution_approvals ADD COLUMN request_json TEXT")
        try:
            self.database_path.chmod(0o600)
        except OSError:
            # Windows ACLs are managed by the host; deployment docs require a private data dir.
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _approval_digest(approval_id: str) -> str:
        return hashlib.sha256(approval_id.encode("utf-8")).hexdigest()

    @staticmethod
    def fingerprint(request: SandboxExecutionRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def create(
        self, requester_id: str, request: SandboxExecutionRequest, *, ttl_seconds: int
    ) -> str:
        if not requester_id.strip():
            raise ValueError("Requester identity must be non-empty")
        if not 1 <= ttl_seconds <= 900:
            raise ValueError("Approval lifetime must be between 1 and 900 seconds")
        now = time.time()
        approval_id = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sandbox_execution_approvals
                    (approval_id, public_id, requester_id, request_hash, request_json,
                     created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    self._approval_digest(approval_id),
                    approval_id,
                    requester_id,
                    self.fingerprint(request),
                    json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                    now,
                    now + ttl_seconds,
                ),
            )
        return approval_id

    def list_pending(self) -> list[dict[str, object]]:
        """Return pending review records for the authenticated approver."""
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "UPDATE sandbox_execution_approvals SET status = 'expired', request_json = NULL WHERE status = 'pending' AND expires_at <= ?",
                (now,),
            )
            rows = connection.execute(
                "SELECT public_id, requester_id, request_hash, request_json, created_at, expires_at, status FROM sandbox_execution_approvals WHERE status = 'pending' AND expires_at > ? AND request_json IS NOT NULL ORDER BY created_at ASC LIMIT 100",
                (now,),
            ).fetchall()
        return [
            {key: value for key, value in self._review_record(row).items() if key != "request"}
            for row in rows
        ]

    def get_review(self, approval_id: str) -> dict[str, object] | None:
        """Return a review record and clear code if the approval has expired."""
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT public_id, requester_id, request_hash, request_json, created_at, expires_at, status FROM sandbox_execution_approvals WHERE approval_id = ?",
                (self._approval_digest(approval_id),),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now and row["request_json"] is not None:
                connection.execute(
                    "UPDATE sandbox_execution_approvals SET status = 'expired', request_json = NULL WHERE approval_id = ? AND status IN ('pending', 'approved')",
                    (self._approval_digest(approval_id),),
                )
                row = connection.execute(
                    "SELECT public_id, requester_id, request_hash, request_json, created_at, expires_at, status FROM sandbox_execution_approvals WHERE approval_id = ?",
                    (self._approval_digest(approval_id),),
                ).fetchone()
        return self._review_record(row)

    @staticmethod
    def _review_record(row: sqlite3.Row) -> dict[str, object]:
        return {
            "approval_id": row["public_id"],
            "requester_id": row["requester_id"],
            "request_hash": row["request_hash"],
            "request": json.loads(row["request_json"]) if row["request_json"] else None,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "status": row["status"],
        }

    def approve(
        self, approval_id: str, approver_id: str, *, allowed_approvers: frozenset[str]
    ) -> None:
        if not approver_id or approver_id not in allowed_approvers:
            raise ApprovalError("Principal is not authorized to approve sandbox execution")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT requester_id, status, expires_at
                   FROM sandbox_execution_approvals WHERE approval_id = ?""",
                (self._approval_digest(approval_id),),
            ).fetchone()
            if row is None or row["status"] != "pending" or row["expires_at"] <= now:
                raise ApprovalError("Approval is missing, expired, or no longer pending")
            if row["requester_id"] == approver_id:
                raise ApprovalError("Requester cannot approve their own execution")
            updated = connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET status = 'approved', approver_id = ?, request_json = NULL
                   WHERE approval_id = ? AND status = 'pending' AND expires_at > ?""",
                (approver_id, self._approval_digest(approval_id), now),
            )
            if updated.rowcount != 1:
                raise ApprovalError("Approval could not be applied")

    def consume(
        self, approval_id: str, requester_id: str, request: SandboxExecutionRequest
    ) -> None:
        now = time.time()
        request_hash = self.fingerprint(request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT requester_id, request_hash, status, expires_at
                   FROM sandbox_execution_approvals WHERE approval_id = ?""",
                (self._approval_digest(approval_id),),
            ).fetchone()
            if (
                row is None
                or row["requester_id"] != requester_id
                or row["request_hash"] != request_hash
                or row["status"] != "approved"
                or row["expires_at"] <= now
            ):
                raise ApprovalError("A valid, matching, unused human approval is required")
            updated = connection.execute(
                """UPDATE sandbox_execution_approvals
                   SET status = 'consumed', consumed_at = ?, request_json = NULL
                   WHERE approval_id = ? AND status = 'approved' AND expires_at > ?""",
                (now, self._approval_digest(approval_id), now),
            )
            if updated.rowcount != 1:
                raise ApprovalError("Approval has already been consumed")


class HumanApprovalManager:
    """Expose request/approve/consume operations around the persistent store."""

    def __init__(
        self, store: SQLiteExecutionApprovalStore, *, allowed_approvers: set[str]
    ) -> None:
        if not allowed_approvers or any(not item.strip() for item in allowed_approvers):
            raise ValueError("At least one valid human approver must be configured")
        self.store = store
        self.allowed_approvers = frozenset(allowed_approvers)

    def request(
        self, requester_id: str, request: SandboxExecutionRequest, *, ttl_seconds: int = 300
    ) -> str:
        """Create a pending approval bound to this exact request."""
        return self.store.create(requester_id, request, ttl_seconds=ttl_seconds)

    def list_pending(self) -> list[dict[str, object]]:
        """List pending code-review requests for the approval UI."""
        return self.store.list_pending()

    def get_review(self, approval_id: str) -> dict[str, object] | None:
        """Read one request for human inspection before approval."""
        return self.store.get_review(approval_id)

    def approve(self, approval_id: str, approver_id: str) -> None:
        """Approve only when called as an allowlisted, distinct human principal."""
        self.store.approve(
            approval_id, approver_id, allowed_approvers=self.allowed_approvers
        )

    def consume(
        self, approval_id: str, requester_id: str, request: SandboxExecutionRequest
    ) -> None:
        """Atomically consume approval once, only for the exact requester and request."""
        self.store.consume(approval_id, requester_id, request)
