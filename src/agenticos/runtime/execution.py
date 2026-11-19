"""Bounded execution lifecycle for coding workflows."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from agenticos.runtime.checkpoints import CheckpointStore


class Workflow(Protocol):
    async def run(self, task: str) -> dict[str, Any]:
        """Run the configured multi-agent workflow."""


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunRecord:
    run_id: str
    task: str
    status: RunStatus
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None

    def snapshot(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class RunExecutionError(RuntimeError):
    def __init__(self, record: RunRecord) -> None:
        super().__init__(record.error or "Agent workflow failed")
        self.record = record


class ExecutionManager:
    """Controls concurrency, timeouts, run states, and checkpoint updates."""

    def __init__(
        self,
        workflow: Workflow,
        checkpoints: CheckpointStore,
        *,
        max_concurrent_runs: int = 2,
        timeout_seconds: float = 300.0,
    ) -> None:
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.workflow = workflow
        self.checkpoints = checkpoints
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)

    async def _checkpoint(self, record: RunRecord) -> None:
        record.updated_at = datetime.now(UTC).isoformat()
        await self.checkpoints.save(record.run_id, record.snapshot())

    async def execute(self, task: str) -> RunRecord:
        now = datetime.now(UTC).isoformat()
        record = RunRecord(
            run_id=str(uuid4()),
            task=task,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        try:
            await self._checkpoint(record)
            async with self._semaphore:
                record.status = RunStatus.RUNNING
                await self._checkpoint(record)
                record.result = await asyncio.wait_for(
                    self.workflow.run(task),
                    timeout=self.timeout_seconds,
                )
                record.status = RunStatus.COMPLETED
                await self._checkpoint(record)
                return record
        except asyncio.CancelledError:
            record.status = RunStatus.CANCELLED
            record.error = "Run was cancelled"
            await self._checkpoint(record)
            raise
        except Exception as exc:
            record.status = RunStatus.FAILED
            record.error = (
                "Execution timed out"
                if isinstance(exc, TimeoutError)
                else "Agent workflow failed"
            )
            await self._checkpoint(record)
            raise RunExecutionError(record) from exc
