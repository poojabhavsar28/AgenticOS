"""Bounded, workspace-isolated repository indexing and keyword search."""

import os
import re
import sqlite3
from pathlib import Path

from agenticos.security.workspace import resolve_workspace_path

_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "node_modules", "dist", "build", ".tox",
}
_MAX_QUERY_TOKENS = 12


class RepositoryIndex:
    """Index UTF-8 text files into a local SQLite FTS5 index when available."""

    def __init__(
        self,
        workspace_root: Path,
        database_path: Path,
        *,
        max_file_bytes: int = 256_000,
        max_files: int = 2_000,
        excerpt_characters: int = 500,
    ) -> None:
        if min(max_file_bytes, max_files, excerpt_characters) < 1:
            raise ValueError("Repository index limits must be positive")
        self.workspace_root = workspace_root.expanduser().resolve()
        self.database_path = database_path
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.excerpt_characters = excerpt_characters
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_enabled = self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> bool:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS repository_documents (
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY(workspace, path)
                )"""
            )
            try:
                connection.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS repository_fts
                    USING fts5(workspace UNINDEXED, path UNINDEXED, content)"""
                )
                return True
            except sqlite3.OperationalError:
                return False

    def _workspace_path(self, workspace: str) -> Path:
        return resolve_workspace_path(self.workspace_root, workspace)

    def _iter_text_files(self, base: Path):
        count = 0
        for directory, dirnames, filenames in os.walk(base, followlinks=False):
            current = Path(directory)
            dirnames[:] = sorted(
                name for name in dirnames
                if name not in _IGNORED_DIRS and not name.startswith(".")
                and not (current / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = current / filename
                if filename.startswith(".") or path.is_symlink():
                    continue
                try:
                    resolved = path.resolve()
                    resolved.relative_to(base)
                    if not path.is_file() or path.stat().st_size > self.max_file_bytes:
                        continue
                    raw = path.read_bytes()
                    if b"\x00" in raw:
                        continue
                    content = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                count += 1
                if count > self.max_files:
                    raise ValueError("Workspace exceeds the configured repository file limit")
                yield path.relative_to(base).as_posix(), content

    def refresh(self, workspace: str) -> dict[str, int | bool]:
        """Replace one workspace's index with a fresh bounded file scan."""
        base = self._workspace_path(workspace)
        documents = list(self._iter_text_files(base))
        with self._connect() as connection:
            connection.execute("DELETE FROM repository_documents WHERE workspace = ?", (workspace,))
            if self._fts_enabled:
                connection.execute("DELETE FROM repository_fts WHERE workspace = ?", (workspace,))
            for path, content in documents:
                connection.execute(
                    "INSERT INTO repository_documents(workspace, path, content) VALUES (?, ?, ?)",
                    (workspace, path, content),
                )
                if self._fts_enabled:
                    connection.execute(
                        "INSERT INTO repository_fts(workspace, path, content) VALUES (?, ?, ?)",
                        (workspace, path, content),
                    )
        return {"indexed_files": len(documents), "fts_enabled": self._fts_enabled}

    def search(self, workspace: str, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Search only the requested workspace and return bounded source excerpts."""
        self._workspace_path(workspace)
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError("Search query must contain 1 to 500 characters")
        if not 1 <= limit <= 50:
            raise ValueError("Search limit must be between 1 and 50")
        tokens = re.findall(r"[A-Za-z0-9_]+", query)[:_MAX_QUERY_TOKENS]
        if not tokens:
            raise ValueError("Search query must include searchable terms")
        with self._connect() as connection:
            rows = []
            if self._fts_enabled:
                expression = " AND ".join(f'"{token}"' for token in tokens)
                try:
                    rows = connection.execute(
                        """SELECT path, content, bm25(repository_fts) AS rank
                        FROM repository_fts WHERE repository_fts MATCH ? AND workspace = ?
                        ORDER BY rank LIMIT ?""",
                        (expression, workspace, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                clauses = " AND ".join("lower(content) LIKE ?" for _ in tokens)
                parameters = [f"%{token.lower()}%" for token in tokens]
                rows = connection.execute(
                    f"""SELECT path, content FROM repository_documents
                    WHERE workspace = ? AND {clauses} ORDER BY path LIMIT ?""",
                    [workspace, *parameters, limit],
                ).fetchall()
        results = []
        for row in rows:
            content = row["content"]
            lowered = content.lower()
            positions = [lowered.find(token.lower()) for token in tokens]
            first = min((position for position in positions if position >= 0), default=0)
            positions = [lowered.find(token.lower()) for token in tokens]
            first = min((position for position in positions if position >= 0), default=0)
            start = max(0, first - self.excerpt_characters // 4)
            excerpt = content[start : start + self.excerpt_characters]
            if start:
                excerpt = "…" + excerpt
            if start + self.excerpt_characters < len(content):
                excerpt += "…"
            results.append({"path": row["path"], "excerpt": excerpt})
        return results
