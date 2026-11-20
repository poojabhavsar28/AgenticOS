import pytest

from agenticos.runtime.graph import CodingWorkflow
from agenticos.runtime.progress import AgentStage, TokenChunk


class StreamingFakeModel:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return "fallback"

    async def generate_stream(self, prompt: str, *, system: str | None = None):
        yield "chunk-one"
        yield "chunk-two"


@pytest.mark.asyncio
async def test_workflow_streams_chunks_with_run_and_stage_scope() -> None:
    chunks: list[TokenChunk] = []
    result = await CodingWorkflow(StreamingFakeModel()).run_with_progress(
        "Write a tiny function",
        run_id="stream-run",
        progress_callback=lambda _: None,
        token_callback=chunks.append,
    )

    assert result["plan"] == "chunk-onechunk-two"
    assert [chunk.stage for chunk in chunks] == [
        stage for stage in AgentStage for _ in range(2)
    ]
    assert [chunk.content for chunk in chunks[:2]] == ["chunk-one", "chunk-two"]
    assert all(chunk.run_id == "stream-run" for chunk in chunks)


@pytest.mark.asyncio
async def test_workflow_splits_large_provider_chunks_to_event_limit() -> None:
    class LargeChunkModel(StreamingFakeModel):
        async def generate_stream(self, prompt: str, *, system: str | None = None):
            yield "x" * 2_500

    chunks: list[TokenChunk] = []
    await CodingWorkflow(LargeChunkModel()).run_with_progress(
        "task",
        run_id="bounded-run",
        progress_callback=lambda _: None,
        token_callback=chunks.append,
    )

    assert [len(chunk.content) for chunk in chunks[:3]] == [1_024, 1_024, 452]
    assert all(len(chunk.content) <= 1_024 for chunk in chunks)
