import pytest

from agenticos.security.approval import (
    ApprovalError,
    HumanApprovalManager,
    SQLiteExecutionApprovalStore,
)
from agenticos.security.audit import AuditLog
from agenticos.security.authorized_sandbox import (
    SANDBOX_EXECUTE_ACTION,
    SANDBOX_PYTHON_RESOURCE,
    AuditCompletionError,
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


def make_approval(tmp_path, request):
    approvals = HumanApprovalManager(
        SQLiteExecutionApprovalStore(tmp_path / "approvals.sqlite3"),
        allowed_approvers={"human-admin"},
    )
    approval = approvals.request("agent-1", request)
    approvals.approve(approval["review_id"], "human-admin")
    return approvals, approval["approval_token"]


def make_executor(backend, audit, approvals, *, allowed=True):
    grants = (
        {Permission("agent-1", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE)}
        if allowed
        else set()
    )
    return AuthorizedSandboxExecutor(backend, PermissionPolicy(grants), audit, approvals)


@pytest.mark.asyncio
async def test_authorized_execution_records_completion_without_source(tmp_path) -> None:
    backend = StubBackend()
    audit = AuditLog()
    request = SandboxExecutionRequest(source="print('secret source')")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, audit, approvals)

    result = await executor.execute("agent-1", request, approval_token=approval_id)

    assert result.stdout == "safe output"
    assert backend.calls == 1
    events = audit.events()
    assert [event.outcome for event in events] == ["started", "completed"]
    assert all("secret source" not in event.resource for event in events)


@pytest.mark.asyncio
async def test_unauthorized_execution_is_denied_and_audited(tmp_path) -> None:
    backend = StubBackend()
    audit = AuditLog()
    request = SandboxExecutionRequest(source="pass")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, audit, approvals, allowed=False)

    with pytest.raises(PermissionDenied):
        await executor.execute("agent-1", request, approval_token=approval_id)

    assert backend.calls == 0
    assert [event.outcome for event in audit.events()] == ["denied"]


@pytest.mark.asyncio
async def test_execution_without_human_approval_is_denied(tmp_path) -> None:
    backend = StubBackend()
    audit = AuditLog()
    approvals = HumanApprovalManager(
        SQLiteExecutionApprovalStore(tmp_path / "approvals.sqlite3"),
        allowed_approvers={"human-admin"},
    )
    executor = make_executor(backend, audit, approvals)

    with pytest.raises(ApprovalError, match="human approval"):
        await executor.execute(
            "agent-1", SandboxExecutionRequest(source="pass"), approval_id="missing"
        )
    assert backend.calls == 0
    assert [event.outcome for event in audit.events()] == ["approval_denied"]


@pytest.mark.asyncio
async def test_failed_execution_is_audited_and_reraised(tmp_path) -> None:
    backend = StubBackend(fail=True)
    audit = AuditLog()
    request = SandboxExecutionRequest(source="pass")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, audit, approvals)

    with pytest.raises(RuntimeError, match="backend failed"):
        await executor.execute("agent-1", request, approval_token=approval_id)

    assert [event.outcome for event in audit.events()] == ["started", "failed"]


@pytest.mark.asyncio
async def test_timed_out_execution_has_distinct_audit_outcome(tmp_path) -> None:
    backend = StubBackend(timed_out=True)
    audit = AuditLog()
    request = SandboxExecutionRequest(source="while True: pass")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, audit, approvals)

    await executor.execute("agent-1", request, approval_token=approval_id)

    assert [event.outcome for event in audit.events()] == ["started", "timed_out"]


@pytest.mark.asyncio
async def test_authorized_execution_supports_persistent_sqlite_audit(tmp_path) -> None:
    from agenticos.security.audit import SQLiteAuditLog

    backend = StubBackend()
    audit = SQLiteAuditLog(tmp_path / "security-audit.sqlite3")
    request = SandboxExecutionRequest(source="print('not stored in audit')")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, audit, approvals)

    await executor.execute("agent-1", request, approval_token=approval_id)

    reopened = SQLiteAuditLog(tmp_path / "security-audit.sqlite3")
    events = reopened.events()
    assert [event.outcome for event in events] == ["started", "completed"]
    assert all("not stored in audit" not in event.resource for event in events)

@pytest.mark.asyncio
async def test_audit_store_failure_fails_closed_before_execution(tmp_path) -> None:
    class UnavailableAudit:
        def record(self, principal_id, action, resource, outcome):
            raise OSError("audit database unavailable")

    backend = StubBackend()
    request = SandboxExecutionRequest(source="print('must not execute')")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, UnavailableAudit(), approvals)

    with pytest.raises(OSError, match="audit database unavailable"):
        await executor.execute("agent-1", request, approval_token=approval_id)

    assert backend.calls == 0



@pytest.mark.asyncio
async def test_completion_audit_failure_preserves_result_and_warns_against_retry(tmp_path) -> None:
    class CompletionAuditUnavailable:
        def __init__(self):
            self.calls = 0

        def record(self, principal_id, action, resource, outcome):
            self.calls += 1
            if outcome in {"completed", "timed_out"}:
                raise OSError("audit database unavailable after execution")

    backend = StubBackend()
    audit = CompletionAuditUnavailable()
    request = SandboxExecutionRequest(source="print('executed exactly once')")
    approvals, approval_id = make_approval(tmp_path, request)
    executor = make_executor(backend, audit, approvals)

    with pytest.raises(AuditCompletionError, match="do not retry automatically") as exc_info:
        await executor.execute("agent-1", request, approval_token=approval_id)

    assert backend.calls == 1
    assert exc_info.value.result.stdout == "safe output"
    assert audit.calls == 2
