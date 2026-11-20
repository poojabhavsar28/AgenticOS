"""Tests for the LangGraph coding workflow."""

import pytest

from agenticos.runtime.graph import CodingWorkflow
from agenticos.runtime.progress import AgentStage, StageEventType


@pytest.mark.asyncio
async def test_workflow_runs_all_roles(fake_model) -> None:
    result = await CodingWorkflow(fake_model).run("Create a hello world function")
    assert result["task"] == "Create a hello world function"
    assert result["plan"]
    assert result["code"]
    assert result["review"]
    assert result["test_plan"]


@pytest.mark.asyncio
async def test_workflow_emits_ordered_stage_progress(fake_model) -> None:
    progress = []
    result = await CodingWorkflow(fake_model).run_with_progress(
        "Create a hello world function",
        run_id="run-progress",
        progress_callback=progress.append,
    )

    assert result["test_plan"]
    assert [(item.stage, item.event_type) for item in progress] == [
        (stage, event_type)
        for stage in AgentStage
        for event_type in (StageEventType.STARTED, StageEventType.COMPLETED)
    ]
    assert all(item.run_id == "run-progress" for item in progress)
    assert all(item.duration_ms is None for item in progress if item.event_type is StageEventType.STARTED)
    assert all(item.duration_ms is not None for item in progress if item.event_type is StageEventType.COMPLETED)


@pytest.mark.asyncio
async def test_workflow_emits_failed_stage_without_model_output(fake_model) -> None:
    class FailingModel:
        async def generate(self, prompt: str, *, system: str) -> str:
            raise RuntimeError("private model response")

    progress = []
    with pytest.raises(RuntimeError, match="private model response"):
        await CodingWorkflow(FailingModel()).run_with_progress(
            "private task",
            run_id="run-failed",
            progress_callback=progress.append,
        )

    assert [(item.stage, item.event_type) for item in progress] == [
        (AgentStage.PLANNER, StageEventType.STARTED),
        (AgentStage.PLANNER, StageEventType.FAILED),
    ]
    assert all(not hasattr(item, "prompt") for item in progress)
