"""Explicit tool contracts and permission-checked registry."""

from typing import Protocol

from agenticos.security.audit import AuditLog
from agenticos.security.identity import SQLiteIdentityStore
from agenticos.security.policy import PermissionPolicy


class AgentTool(Protocol):
    name: str

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        """Execute a validated tool operation."""


class ToolRegistry:
    """Registry that requires explicit authorization before tool execution."""

    def __init__(
        self,
        policy: PermissionPolicy | None = None,
        audit_log: AuditLog | None = None,
        identity_store: SQLiteIdentityStore | None = None,
    ) -> None:
        self._tools: dict[str, AgentTool] = {}
        self.policy = policy or PermissionPolicy()
        self.audit_log = audit_log or AuditLog()
        self.identity_store = identity_store

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

    async def execute(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        principal_id: str,
        workspace_id: str = "default",
    ) -> dict[str, object]:
        tool = self.get(name)
        try:
            if self.identity_store is not None:
                self.identity_store.authorize(
                    principal_id, workspace_id, "execute", name
                )
            else:
                self.policy.authorize(principal_id, "execute", name)
        except PermissionError:
            self.audit_log.record(principal_id, "execute", name, "denied")
            raise
        self.audit_log.record(principal_id, "execute", name, "allowed")
        return await tool.execute(arguments)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
