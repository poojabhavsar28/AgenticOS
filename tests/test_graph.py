"""Tests for the LangGraph coding workflow."""

import pytest

from agenticos.runtime.graph import CodingWorkflow


@pytest.mark.asyncio
async def test_workflow_runs_all_roles(fake_model) -> None:
    result = await CodingWorkflow(fake_model).run("Create a hello world function")
    assert result["task"] == "Create a hello world function"
    assert result["plan"]
    assert result["code"]
    assert result["review"]
    assert result["test_plan"]
