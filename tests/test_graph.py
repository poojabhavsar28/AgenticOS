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
    assert "run_id" not in result
    assert "progress_callback" not in result
    assert "cancellation_check" not in result
    assert not any(callable(value) for value in result.values())
    assert [(item.stage, item.event_type) for item in progress] == [
        (stage, event_type)
        for stage in AgentStage
        for event_type in (StageEventType.STARTED, StageEventType.COMPLETED)
    ]
    assert all(item.run_id == "run-progress" for item in progress)
    started = [item for item in progress if item.event_type is StageEventType.STARTED]
    completed = [item for item in progress if item.event_type is StageEventType.COMPLETED]
    assert all(item.duration_ms is None for item in started)
    assert all(item.duration_ms is not None for item in completed)


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


@pytest.mark.asyncio
async def test_workflow_dispatches_explicit_tools_through_registry(fake_model) -> None:
    from agenticos.runtime.tools import ToolRegistry
    from agenticos.security.policy import Permission, PermissionPolicy

    class EchoTool:
        name = "echo"

        async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
            return {"echo": arguments["value"]}

    registry = ToolRegistry(
        policy=PermissionPolicy({Permission("operator", "execute", "echo")})
    )
    registry.register(EchoTool())
    workflow = CodingWorkflow(fake_model, tool_registry=registry)

    result = await workflow.execute_tool(
        "echo", {"value": "explicit request"}, principal_id="operator"
    )

    assert result == {"echo": "explicit request"}


@pytest.mark.asyncio
async def test_workflow_tool_dispatch_is_default_deny(fake_model) -> None:
    from agenticos.runtime.tools import ToolRegistry

    class EchoTool:
        name = "echo"

        async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
            return arguments

    registry = ToolRegistry()
    registry.register(EchoTool())
    workflow = CodingWorkflow(fake_model, tool_registry=registry)

    with pytest.raises(PermissionError, match="Permission denied"):
        await workflow.execute_tool("echo", {}, principal_id="operator")
