"""SQLite-backed conversation and project context storage."""

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_SESSION_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


@dataclass(frozen=True)
class MemoryMessage:
    role: str
    content: str
    created_at: str


class SQLiteMemoryStore:
    """Local persistent store for session messages and workspace context."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_id_id "
                "ON messages(session_id, id)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS session_owners (
                    session_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS project_context (
                    workspace TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(workspace, source_key)
                )
                """
            )

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ValueError("Invalid session identifier")

    def claim_session(self, session_id: str, principal_id: str, workspace_id: str) -> bool:
        """Bind an empty/new session to one principal and workspace; never transfer ownership."""
        self._validate_session_id(session_id)
        if not principal_id or len(principal_id) > 256 or not workspace_id or len(workspace_id) > 256:
            raise ValueError("Invalid session owner")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT principal_id, workspace_id FROM session_owners WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is not None:
                return row["principal_id"] == principal_id and row["workspace_id"] == workspace_id
            existing = connection.execute(
                "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,)
            ).fetchone()
            if existing is not None:
                return False
            connection.execute(
                "INSERT INTO session_owners(session_id, principal_id, workspace_id) VALUES (?, ?, ?)",
                (session_id, principal_id, workspace_id),
            )
        return True

    def owns_session(self, session_id: str, principal_id: str) -> bool:
        """Return whether the principal owns the session."""
        self._validate_session_id(session_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM session_owners WHERE session_id = ? AND principal_id = ?",
                (session_id, principal_id),
            ).fetchone()
        return row is not None

    def append_message(self, session_id: str, role: str, content: str) -> MemoryMessage:
        self._validate_session_id(session_id)
        if role not in {"user", "assistant"}:
            raise ValueError("Role must be user or assistant")
        if not content.strip() or len(content) > 100_000:
            raise ValueError("Message content must contain 1 to 100000 characters")
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            row = connection.execute(
                "SELECT role, content, created_at FROM messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return MemoryMessage(row["role"], row["content"], row["created_at"])

    def get_recent_messages(self, session_id: str, limit: int = 12) -> list[MemoryMessage]:
        self._validate_session_id(session_id)
        if not 1 <= limit <= 100:
            raise ValueError("Message limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at FROM (
                    SELECT id, role, content, created_at
                    FROM messages WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        return [MemoryMessage(row["role"], row["content"], row["created_at"]) for row in rows]

    def upsert_project_context(
        self,
        workspace: str,
        source_key: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if not workspace or len(workspace) > 80 or not source_key or len(source_key) > 240:
            raise ValueError("Workspace and source key must be non-empty and within limits")
        if len(content) > 200_000:
            raise ValueError("Project context exceeds 200000 characters")
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_context(workspace, source_key, content, metadata_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace, source_key) DO UPDATE SET
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (workspace, source_key, content, metadata_json),
            )

    def get_project_context(self, workspace: str, limit: int = 20) -> list[dict[str, object]]:
        if not workspace or not 1 <= limit <= 100:
            raise ValueError("Invalid workspace or context limit")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_key, content, metadata_json, updated_at
                FROM project_context WHERE workspace = ?
                ORDER BY source_key LIMIT ?
                """,
                (workspace, limit),
            ).fetchall()
        return [
            {
                "source_key": row["source_key"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
