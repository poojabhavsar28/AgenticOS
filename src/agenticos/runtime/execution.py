"""Bounded execution lifecycle for coding workflows."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from agenticos.runtime.checkpoints import CheckpointStore
from agenticos.runtime.events import SQLiteRunEventStore
from agenticos.runtime.progress import RunCancelledError, StageProgress, TokenChunk


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
    workspace_id: str | None = None
    principal_id: str | None = None
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
        self._cancellation_events: dict[str, asyncio.Event] = {}
        self._run_tasks: dict[str, asyncio.Task[RunRecord]] = {}

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

    def start(
        self, task: str, memory_context: str = "", *,
        workspace_id: str | None = None, principal_id: str | None = None,
    ) -> str:
        """Schedule a run and return its ID without waiting for completion."""
        run_id = str(uuid4())
        cancellation_event = asyncio.Event()
        self._cancellation_events[run_id] = cancellation_event
        task_handle = asyncio.create_task(
            self.execute(
                task,
                memory_context=memory_context,
                run_id=run_id,
                cancellation_event=cancellation_event,
                workspace_id=workspace_id,
                principal_id=principal_id,
            )
        )
        self._run_tasks[run_id] = task_handle
        task_handle.add_done_callback(lambda _: self._run_tasks.pop(run_id, None))
        return run_id

    async def cancel_run(self, run_id: str) -> bool:
        """Request cooperative cancellation for an active run."""
        cancellation_event = self._cancellation_events.get(run_id)
        if cancellation_event is None:
            return False
        cancellation_event.set()
        return True

    def _emit_token_chunk(self, chunk: TokenChunk) -> None:
        if self.event_store is None:
            return
        self.event_store.append(
            chunk.run_id,
            "token",
            {"stage": chunk.stage.value, "content": chunk.content},
        )

    async def _run_workflow(
        self, record: RunRecord, memory_context: str, cancellation_event: asyncio.Event
    ) -> dict[str, Any]:
        run_with_progress = getattr(self.workflow, "run_with_progress", None)
        if run_with_progress is not None:
            return await run_with_progress(
                record.task,
                run_id=record.run_id,
                memory_context=memory_context,
                progress_callback=self._emit_stage_progress,
                cancellation_event=cancellation_event,
                token_callback=self._emit_token_chunk,
            )
        result = await self.workflow.run(record.task, memory_context=memory_context)
        if cancellation_event.is_set():
            raise RunCancelledError("Run cancellation requested")
        return result

    async def _checkpoint(self, record: RunRecord) -> None:
        record.updated_at = datetime.now(UTC).isoformat()
        await self.checkpoints.save(record.run_id, record.snapshot())

    async def get_snapshot(self, run_id: str) -> dict[str, object] | None:
        return await self.checkpoints.load(run_id)

    async def execute(
        self,
        task: str,
        memory_context: str = "",
        *,
        run_id: str | None = None,
        cancellation_event: asyncio.Event | None = None,
        workspace_id: str | None = None,
        principal_id: str | None = None,
    ) -> RunRecord:
        now = datetime.now(UTC).isoformat()
        record = RunRecord(
            run_id=run_id or str(uuid4()),
            task=task,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
            workspace_id=workspace_id,
            principal_id=principal_id,
        )
        cancellation_event = cancellation_event or asyncio.Event()
        self._cancellation_events[record.run_id] = cancellation_event
        try:
            await self._checkpoint(record)
            self._emit(record, "queued")
            async with self._semaphore:
                record.status = RunStatus.RUNNING
                await self._checkpoint(record)
                self._emit(record, "started")
                record.result = await asyncio.wait_for(
                    self._run_workflow(record, memory_context, cancellation_event),
                    timeout=self.timeout_seconds,
                )
                record.status = RunStatus.COMPLETED
                await self._checkpoint(record)
                self._emit(record, "completed")
                return record
        except RunCancelledError:
            record.status = RunStatus.CANCELLED
            record.error = "Run was cancelled"
            await self._checkpoint(record)
            self._emit(record, "cancelled")
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
        finally:
            self._cancellation_events.pop(record.run_id, None)
