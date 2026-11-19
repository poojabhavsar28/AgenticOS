"""Agent directory with deterministic capability-based assignment."""

from agenticos.collaboration.models import AgentProfile, CollaborationTask


class AgentDirectory:
    def __init__(self) -> None:
        self._agents: dict[str, AgentProfile] = {}

    def register(self, agent: AgentProfile) -> None:
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent already registered: {agent.agent_id}")
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> AgentProfile:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {agent_id}") from exc

    def find_capable(self, required: frozenset[str]) -> tuple[AgentProfile, ...]:
        matches = [
            agent
            for agent in self._agents.values()
            if required.issubset(agent.capabilities)
        ]
        return tuple(sorted(matches, key=lambda agent: agent.agent_id))

    def assign(self, task: CollaborationTask) -> str:
        if task.assigned_agent is not None:
            raise ValueError("Task is already assigned")
        candidates = self.find_capable(task.required_capabilities)
        if not candidates:
            raise LookupError("No registered agent satisfies task capabilities")
        task.assigned_agent = candidates[0].agent_id
        return task.assigned_agent

    def list_agents(self) -> tuple[AgentProfile, ...]:
        return tuple(self._agents[key] for key in sorted(self._agents))
