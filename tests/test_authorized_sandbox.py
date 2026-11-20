import pytest

from agenticos.security.audit import AuditLog
from agenticos.security.authorized_sandbox import (
    SANDBOX_EXECUTE_ACTION,
    SANDBOX_PYTHON_RESOURCE,
    AuthorizedSandboxExecutor,
)
from agenticos.security.docker_sandbox import DockerSandboxBackend
from agenticos.security.policy import Permission, PermissionDenied, PermissionPolicy
from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxPolicy,
)


class StubBackend(DockerSandboxBackend):
    def __init__(self, *, timed_out: bool = False, fail: bool = False) -> None:
        super().__init__(SandboxPolicy())
        self.calls = 0
        self.timed_out = timed_out
        self.fail = fail

    async def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("backend failed")
        return SandboxExecutionResult(
            exit_code=0, stdout="safe output", stderr="", timed_out=self.timed_out
        )


@pytest.mark.asyncio
async def test_authorized_execution_records_completion_without_source() -> None:
    backend = StubBackend()
    audit = AuditLog()
    permissions = PermissionPolicy({
        Permission("agent-1", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE)
    })
    executor = AuthorizedSandboxExecutor(backend, permissions, audit)

    result = await executor.execute(
        "agent-1", SandboxExecutionRequest(source="print('secret source')")
    )

    assert result.stdout == "safe output"
    assert backend.calls == 1
    events = audit.events()
    assert [event.outcome for event in events] == ["started", "completed"]
    assert all("secret source" not in event.resource for event in events)


@pytest.mark.asyncio
async def test_unauthorized_execution_is_denied_and_audited() -> None:
    backend = StubBackend()
    audit = AuditLog()
    executor = AuthorizedSandboxExecutor(backend, PermissionPolicy(), audit)

    with pytest.raises(PermissionDenied):
        await executor.execute("untrusted-agent", SandboxExecutionRequest(source="pass"))

    assert backend.calls == 0
    assert [event.outcome for event in audit.events()] == ["denied"]


@pytest.mark.asyncio
async def test_failed_execution_is_audited_and_reraised() -> None:
    backend = StubBackend(fail=True)
    audit = AuditLog()
    permissions = PermissionPolicy({
        Permission("agent-1", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE)
    })
    executor = AuthorizedSandboxExecutor(backend, permissions, audit)

    with pytest.raises(RuntimeError, match="backend failed"):
        await executor.execute("agent-1", SandboxExecutionRequest(source="pass"))

    assert [event.outcome for event in audit.events()] == ["started", "failed"]


@pytest.mark.asyncio
async def test_timed_out_execution_has_distinct_audit_outcome() -> None:
    backend = StubBackend(timed_out=True)
    audit = AuditLog()
    permissions = PermissionPolicy({
        Permission("agent-1", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE)
    })
    executor = AuthorizedSandboxExecutor(backend, permissions, audit)

    await executor.execute("agent-1", SandboxExecutionRequest(source="while True: pass"))

    assert [event.outcome for event in audit.events()] == ["started", "timed_out"]


@pytest.mark.asyncio
async def test_authorized_execution_supports_persistent_sqlite_audit(tmp_path) -> None:
    from agenticos.security.audit import SQLiteAuditLog

    backend = StubBackend()
    audit = SQLiteAuditLog(tmp_path / "security-audit.sqlite3")
    permissions = PermissionPolicy({
        Permission("agent-1", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE)
    })
    executor = AuthorizedSandboxExecutor(backend, permissions, audit)

    await executor.execute(
        "agent-1", SandboxExecutionRequest(source="print('not stored in audit')")
    )

    reopened = SQLiteAuditLog(tmp_path / "security-audit.sqlite3")
    events = reopened.events()
    assert [event.outcome for event in events] == ["started", "completed"]
    assert all("not stored in audit" not in event.resource for event in events)
