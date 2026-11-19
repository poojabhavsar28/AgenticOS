"""Tests for bounded workflow execution."""

import asyncio

import pytest

from agenticos.runtime.checkpoints import InMemoryCheckpointStore
from agenticos.runtime.execution import ExecutionManager, RunExecutionError, RunStatus


class SuccessfulWorkflow:
    async def run(self, task: str) -> dict[str, str]:
        return {"task": task, "code": "pass"}


class FailingWorkflow:
    async def run(self, task: str) -> dict[str, str]:
        raise RuntimeError("private implementation detail")


class SlowWorkflow:
    async def run(self, task: str) -> dict[str, str]:
        await asyncio.sleep(0.05)
        return {"task": task}


@pytest.mark.asyncio
async def test_execution_persists_completed_lifecycle() -> None:
    checkpoints = InMemoryCheckpointStore()
    manager = ExecutionManager(SuccessfulWorkflow(), checkpoints)
    record = await manager.execute("write a function")

    assert record.status is RunStatus.COMPLETED
    assert record.result == {"task": "write a function", "code": "pass"}
    snapshot = await checkpoints.load(record.run_id)
    assert snapshot is not None
    assert snapshot["status"] == "completed"


@pytest.mark.asyncio
async def test_execution_records_failure_without_leaking_exception() -> None:
    checkpoints = InMemoryCheckpointStore()
    manager = ExecutionManager(FailingWorkflow(), checkpoints)

    with pytest.raises(RunExecutionError) as captured:
        await manager.execute("fail safely")

    record = captured.value.record
    assert record.status is RunStatus.FAILED
    assert record.error == "Agent workflow failed"
    assert "private implementation detail" not in record.error
    assert (await checkpoints.load(record.run_id))["status"] == "failed"


@pytest.mark.asyncio
async def test_execution_timeout_is_recorded() -> None:
    checkpoints = InMemoryCheckpointStore()
    manager = ExecutionManager(SlowWorkflow(), checkpoints, timeout_seconds=0.001)

    with pytest.raises(RunExecutionError) as captured:
        await manager.execute("slow task")

    assert captured.value.record.error == "Execution timed out"
    assert captured.value.record.status is RunStatus.FAILED


def test_execution_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        ExecutionManager(SuccessfulWorkflow(), InMemoryCheckpointStore(), max_concurrent_runs=0)
