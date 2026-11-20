import pytest

from agenticos.runtime.checkpoints import InMemoryCheckpointStore
from agenticos.runtime.events import SQLiteRunEventStore
from agenticos.runtime.execution import ExecutionManager
from agenticos.runtime.graph import CodingWorkflow
from agenticos.runtime.progress import AgentStage


class StreamModel:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return "fallback"

    async def generate_stream(self, prompt: str, *, system: str | None = None):
        yield "alpha"
        yield "beta"


@pytest.mark.asyncio
async def test_execution_persists_run_scoped_token_events(tmp_path) -> None:
    event_store = SQLiteRunEventStore(tmp_path / "events.sqlite3")
    manager = ExecutionManager(
        CodingWorkflow(StreamModel()),
        InMemoryCheckpointStore(),
        event_store=event_store,
    )

    record = await manager.execute("stream this task", run_id="stream-events")

    assert record.status.value == "completed"
    events = event_store.list_events("stream-events", limit=100)
    token_events = [event for event in events if event.event_type == "token"]
    assert len(token_events) == len(AgentStage) * 2
    assert token_events[0].data == {"stage": "planner", "content": "alpha"}
    assert token_events[1].data == {"stage": "planner", "content": "beta"}
    assert all(event.run_id == "stream-events" for event in token_events)
