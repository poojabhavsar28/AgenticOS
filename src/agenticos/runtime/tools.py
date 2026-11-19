"""Explicit tool contracts and registry for agent capabilities."""

from typing import Protocol


class AgentTool(Protocol):
    name: str

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        """Execute a validated tool operation."""


class ToolRegistry:
    """Registry that exposes only explicitly registered tools to the runtime."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        name = tool.name.strip()
        if not name:
            raise ValueError("Tool name cannot be empty")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
