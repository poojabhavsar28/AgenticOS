"""Typed contracts for local multi-agent collaboration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    name: str
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.agent_id.strip() or not self.name.strip():
            raise ValueError("Agent ID and name are required")
        if any(not item.strip() for item in self.capabilities):
            raise ValueError("Agent capabilities cannot contain empty values")


@dataclass
class CollaborationTask:
    title: str
    description: str
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    dependencies: tuple[str, ...] = ()
    task_id: str = field(default_factory=lambda: str(uuid4()))
    assigned_agent: str | None = None
    status: TaskStatus = TaskStatus.BACKLOG
    result: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.description.strip():
            raise ValueError("Task title and description are required")
        if not self.task_id.strip():
            raise ValueError("Task ID is required")
        if self.task_id in self.dependencies:
            raise ValueError("A task cannot depend on itself")


@dataclass(frozen=True)
class AgentMessage:
    sender_id: str
    recipient_id: str
    content: str
    topic: str = "task"
    message_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if not self.sender_id.strip() or not self.recipient_id.strip():
            raise ValueError("Message sender and recipient are required")
        if not self.content.strip():
            raise ValueError("Message content cannot be empty")
        if not self.topic.strip():
            raise ValueError("Message topic cannot be empty")
