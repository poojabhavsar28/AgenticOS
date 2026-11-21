import pytest

from agenticos.runtime.tools import ToolRegistry
from agenticos.security import AuditLog, Permission, PermissionDenied, PermissionPolicy


class EchoTool:
    name = "echo"

    def __init__(self) -> None:
        self.called = False

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        self.called = True
        return arguments


@pytest.mark.asyncio
async def test_tool_invocation_is_denied_without_grant() -> None:
    tool = EchoTool()
    audit = AuditLog()
    registry = ToolRegistry(audit_log=audit)
    registry.register(tool)

    with pytest.raises(PermissionDenied):
        await registry.execute("echo", {"value": "x"}, principal_id="agent-a")

    assert not tool.called
    assert audit.events()[-1].outcome == "denied"


@pytest.mark.asyncio
async def test_tool_invocation_runs_after_explicit_grant() -> None:
    permission = Permission("agent-a", "execute", "echo")
    registry = ToolRegistry(policy=PermissionPolicy({permission}))
    tool = EchoTool()
    registry.register(tool)

    result = await registry.execute("echo", {"value": "safe"}, principal_id="agent-a")

    assert result == {"value": "safe"}
    assert tool.called
    assert registry.audit_log.events()[-1].outcome == "allowed"



@pytest.mark.asyncio
async def test_persistent_workspace_grant_is_required_for_tool_execution(tmp_path) -> None:
    from agenticos.security.identity import SQLiteIdentityStore

    store = SQLiteIdentityStore(tmp_path / "identities.sqlite3")
    store.create_principal("alice")
    store.create_principal("bob")
    tool = EchoTool()
    registry = ToolRegistry(identity_store=store)
    registry.register(tool)

    with pytest.raises(PermissionDenied):
        await registry.execute(
            "echo", {"value": "blocked"}, principal_id="alice",
            workspace_id="workspace-a",
        )
    assert not tool.called

    store.grant("alice", "workspace-a", "execute", "echo")
    assert await registry.execute(
        "echo", {"value": "allowed"}, principal_id="alice",
        workspace_id="workspace-a",
    ) == {"value": "allowed"}

    tool.called = False
    with pytest.raises(PermissionDenied):
        await registry.execute(
            "echo", {"value": "cross-workspace"}, principal_id="alice",
            workspace_id="workspace-b",
        )
    with pytest.raises(PermissionDenied):
        await registry.execute(
            "echo", {"value": "cross-user"}, principal_id="bob",
            workspace_id="workspace-a",
        )
    assert not tool.called
