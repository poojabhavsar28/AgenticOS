"""Small facade coordinating task delegation and agent communication."""

from agenticos.collaboration.board import TaskBoard
from agenticos.collaboration.bus import AgentMessageBus
from agenticos.collaboration.directory import AgentDirectory
from agenticos.collaboration.models import AgentMessage, AgentProfile, CollaborationTask


class AgentCoordinator:
    def __init__(self, *, max_pending_per_agent: int = 100) -> None:
        self.directory = AgentDirectory()
        self.tasks = TaskBoard()
        self.messages = AgentMessageBus(
            self.directory, max_pending_per_agent=max_pending_per_agent
        )

    def register_agent(self, agent: AgentProfile) -> None:
        self.directory.register(agent)

    def delegate(self, task: CollaborationTask) -> str:
        self.tasks.add(task)
        agent_id = self.directory.assign(task)
        if self.tasks.dependencies_complete(task.task_id):
            self.tasks.mark_ready(task.task_id)
        return agent_id

    def refresh_task_readiness(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task.status.value == "backlog" and self.tasks.dependencies_complete(task_id):
            self.tasks.mark_ready(task_id)

    def start_task(self, task_id: str, agent_id: str) -> None:
        self.tasks.start(task_id, agent_id)

    def complete_task(self, task_id: str, agent_id: str, result: str) -> None:
        self.tasks.complete(task_id, agent_id, result)

    def send_message(self, message: AgentMessage) -> None:
        self.messages.send(message)

    def receive_messages(self, agent_id: str, *, limit: int = 20) -> tuple[AgentMessage, ...]:
        return self.messages.receive(agent_id, limit=limit)
