"""Tests for capability-based agent delegation and task coordination."""

import pytest

from agenticos.collaboration import (
    AgentCoordinator,
    AgentProfile,
    CollaborationTask,
    TaskStatus,
)


def test_directory_assigns_deterministically_by_capability() -> None:
    coordinator = AgentCoordinator()
    coordinator.register_agent(AgentProfile("coder-b", "Coder B", frozenset({"python"})))
    coordinator.register_agent(AgentProfile("coder-a", "Coder A", frozenset({"python"})))

    task = CollaborationTask("Implement API", "Build a FastAPI endpoint", frozenset({"python"}))
    assigned = coordinator.delegate(task)

    assert assigned == "coder-a"
    assert task.status is TaskStatus.READY


def test_task_cannot_start_or_complete_under_wrong_agent() -> None:
    coordinator = AgentCoordinator()
    coordinator.register_agent(AgentProfile("coder", "Coder", frozenset({"python"})))
    task = CollaborationTask("Implement API", "Build endpoint", frozenset({"python"}))
    coordinator.delegate(task)

    with pytest.raises(PermissionError):
        coordinator.start_task(task.task_id, "other")

    coordinator.start_task(task.task_id, "coder")
    with pytest.raises(PermissionError):
        coordinator.complete_task(task.task_id, "other", "done")

    coordinator.complete_task(task.task_id, "coder", "Implemented endpoint")
    assert task.status is TaskStatus.COMPLETED
    assert task.result == "Implemented endpoint"


def test_task_waits_for_dependencies() -> None:
    coordinator = AgentCoordinator()
    coordinator.register_agent(AgentProfile("builder", "Builder", frozenset({"build"})))

    prerequisite = CollaborationTask("Prepare schema", "Create schema", frozenset({"build"}))
    dependent = CollaborationTask(
        "Build API", "Use schema to build API", frozenset({"build"}),
        dependencies=(prerequisite.task_id,),
    )
    coordinator.delegate(prerequisite)
    coordinator.tasks.add(dependent)

    with pytest.raises(ValueError, match="dependencies"):
        coordinator.tasks.mark_ready(dependent.task_id)

    coordinator.start_task(prerequisite.task_id, "builder")
    coordinator.complete_task(prerequisite.task_id, "builder", "Schema ready")
    coordinator.tasks.mark_ready(dependent.task_id)
    assert dependent.status is TaskStatus.READY


def test_directory_rejects_duplicate_agents_and_missing_capabilities() -> None:
    coordinator = AgentCoordinator()
    agent = AgentProfile("reviewer", "Reviewer", frozenset({"review"}))
    coordinator.register_agent(agent)

    with pytest.raises(ValueError, match="already registered"):
        coordinator.register_agent(agent)

    task = CollaborationTask("Write code", "Implement feature", frozenset({"python"}))
    with pytest.raises(LookupError, match="No registered agent"):
        coordinator.delegate(task)
    assert task.status is TaskStatus.BACKLOG


def test_invalid_task_and_agent_contracts_are_rejected() -> None:
    with pytest.raises(ValueError):
        AgentProfile("", "No ID")

    with pytest.raises(ValueError):
        CollaborationTask(" ", "Missing title")
