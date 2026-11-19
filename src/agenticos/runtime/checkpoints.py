"""Checkpoint storage contracts and an in-memory implementation."""

from copy import deepcopy
from typing import Protocol


class CheckpointStore(Protocol):
    async def save(self, run_id: str, snapshot: dict[str, object]) -> None:
        """Persist a serializable snapshot for a run."""

    async def load(self, run_id: str) -> dict[str, object] | None:
        """Return the latest snapshot for a run, if present."""


class InMemoryCheckpointStore:
    """Process-local checkpoint store; durable storage is added in a later phase."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, object]] = {}

    async def save(self, run_id: str, snapshot: dict[str, object]) -> None:
        self._snapshots[run_id] = deepcopy(snapshot)

    async def load(self, run_id: str) -> dict[str, object] | None:
        snapshot = self._snapshots.get(run_id)
        return deepcopy(snapshot) if snapshot is not None else None
