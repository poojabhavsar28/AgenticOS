"""SQLite-backed durable run checkpoint stores."""

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Protocol


class CheckpointStore(Protocol):
    async def save(self, run_id: str, snapshot: dict[str, object]) -> None:
        """Persist a serializable snapshot for a run."""

    async def load(self, run_id: str) -> dict[str, object] | None:
        """Return the latest snapshot for a run, if present."""


class InMemoryCheckpointStore:
    """Process-local checkpoint store for tests and ephemeral use."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, object]] = {}

    async def save(self, run_id: str, snapshot: dict[str, object]) -> None:
        self._snapshots[run_id] = deepcopy(snapshot)

    async def load(self, run_id: str) -> dict[str, object] | None:
        snapshot = self._snapshots.get(run_id)
        return deepcopy(snapshot) if snapshot is not None else None


class SQLiteCheckpointStore:
    """Persist JSON run snapshots in a local SQLite database."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    async def save(self, run_id: str, snapshot: dict[str, object]) -> None:
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        try:
            serialized = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
            updated_at = str(snapshot.get("updated_at", ""))
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO run_checkpoints (run_id, snapshot_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        snapshot_json = excluded.snapshot_json,
                        updated_at = excluded.updated_at
                    """,
                    (run_id, serialized, updated_at),
                )
        except (TypeError, ValueError) as exc:
            raise ValueError("checkpoint snapshot must contain JSON-compatible values") from exc

    async def load(self, run_id: str) -> dict[str, object] | None:
        if not run_id.strip():
            raise ValueError("run_id must be non-empty")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM run_checkpoints WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            snapshot = json.loads(row["snapshot_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("stored checkpoint is invalid JSON") from exc
        if not isinstance(snapshot, dict):
            raise ValueError("stored checkpoint must be a JSON object")
        return snapshot
