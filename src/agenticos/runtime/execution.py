"""Bounded execution lifecycle for coding workflows."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from agenticos.runtime.checkpoints import CheckpointStore
from agenticos.runtime.events import SQLiteRunEventStore
from agenticos.runtime.progress import StageProgress


class Workflow(Protocol):
    async def run(self, task: str, memory_context: str = "") -> dict[str, Any]:
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
    """Controls concurrency, timeouts, and checkpoint updates."""

    def __init__(
        self,
        workflow: Workflow,
        checkpoints: CheckpointStore,
        *,
        max_concurrent_runs: int = 2,
        timeout_seconds: float = 300.0,
        event_store: SQLiteRunEventStore | None = None,
    ) -> None:
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.workflow = workflow
        self.checkpoints = checkpoints
        self.event_store = event_store
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)

    def _emit(self, record: RunRecord, event_type: str) -> None:
        if self.event_store is not None:
            self.event_store.append(record.run_id, event_type, {"status": record.status.value})

    def _emit_stage_progress(self, progress: StageProgress) -> None:
        if self.event_store is None:
            return
        data: dict[str, str | int] = {
            "stage": progress.stage.value,
            "occurred_at": progress.occurred_at,
        }
        if progress.duration_ms is not None:
            data["duration_ms"] = progress.duration_ms
        self.event_store.append(progress.run_id, progress.event_type.value, data)

    async def _run_workflow(self, record: RunRecord, memory_context: str) -> dict[str, Any]:
        run_with_progress = getattr(self.workflow, "run_with_progress", None)
        if run_with_progress is not None:
            return await run_with_progress(
                record.task,
                run_id=record.run_id,
                memory_context=memory_context,
                progress_callback=self._emit_stage_progress,
            )
        return await self.workflow.run(record.task, memory_context=memory_context)

    async def _checkpoint(self, record: RunRecord) -> None:
        record.updated_at = datetime.now(UTC).isoformat()
        await self.checkpoints.save(record.run_id, record.snapshot())

    async def get_snapshot(self, run_id: str) -> dict[str, object] | None:
        return await self.checkpoints.load(run_id)

    async def execute(self, task: str, memory_context: str = "") -> RunRecord:
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
            self._emit(record, "queued")
            async with self._semaphore:
                record.status = RunStatus.RUNNING
                await self._checkpoint(record)
                self._emit(record, "started")
                record.result = await asyncio.wait_for(
                    self._run_workflow(record, memory_context),
                    timeout=self.timeout_seconds,
                )
                record.status = RunStatus.COMPLETED
                await self._checkpoint(record)
                self._emit(record, "completed")
                return record
        except asyncio.CancelledError:
            record.status = RunStatus.CANCELLED
            record.error = "Run was cancelled"
            await self._checkpoint(record)
            self._emit(record, "cancelled")
            raise
        except Exception as exc:
            record.status = RunStatus.FAILED
            record.error = (
                "Execution timed out"
                if isinstance(exc, TimeoutError)
                else "Agent workflow failed"
            )
            await self._checkpoint(record)
            self._emit(record, "failed")
            raise RunExecutionError(record) from exc
