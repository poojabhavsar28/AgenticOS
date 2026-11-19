"""In-process, addressed agent messaging with bounded queues."""

from collections import defaultdict, deque

from agenticos.collaboration.directory import AgentDirectory
from agenticos.collaboration.models import AgentMessage


class AgentMessageBus:
    def __init__(self, directory: AgentDirectory, *, max_pending_per_agent: int = 100) -> None:
        if max_pending_per_agent < 1:
            raise ValueError("max_pending_per_agent must be at least 1")
        self.directory = directory
        self.max_pending_per_agent = max_pending_per_agent
        self._inboxes: dict[str, deque[AgentMessage]] = defaultdict(deque)

    def send(self, message: AgentMessage) -> None:
        self.directory.get(message.sender_id)
        self.directory.get(message.recipient_id)
        inbox = self._inboxes[message.recipient_id]
        if len(inbox) >= self.max_pending_per_agent:
            raise OverflowError("Recipient inbox is full")
        inbox.append(message)

    def receive(self, agent_id: str, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        self.directory.get(agent_id)
        if limit < 1:
            raise ValueError("Message limit must be at least 1")
        inbox = self._inboxes[agent_id]
        messages = tuple(inbox.popleft() for _ in range(min(limit, len(inbox))))
        return messages

    def pending_count(self, agent_id: str) -> int:
        self.directory.get(agent_id)
        return len(self._inboxes[agent_id])
