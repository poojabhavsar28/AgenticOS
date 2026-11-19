"""Tests for checkpoint storage behavior."""

import pytest

from agenticos.runtime.checkpoints import InMemoryCheckpointStore


@pytest.mark.asyncio
async def test_checkpoint_store_copies_snapshots() -> None:
    store = InMemoryCheckpointStore()
    source = {"status": "running", "metadata": {"step": 1}}
    await store.save("run-1", source)
    source["metadata"]["step"] = 99

    loaded = await store.load("run-1")
    assert loaded == {"status": "running", "metadata": {"step": 1}}
    loaded["metadata"]["step"] = 42
    assert (await store.load("run-1"))["metadata"]["step"] == 1


@pytest.mark.asyncio
async def test_missing_checkpoint_returns_none() -> None:
    assert await InMemoryCheckpointStore().load("missing") is None
