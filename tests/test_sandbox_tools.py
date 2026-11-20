import pytest

from agenticos.runtime.sandbox_tools import (
    ExecuteApprovedCodeTool,
    RequestCodeExecutionApprovalTool,
)
from agenticos.security.approval import HumanApprovalManager, SQLiteExecutionApprovalStore
from agenticos.security.audit import AuditLog
from agenticos.security.authorized_sandbox import (
    SANDBOX_EXECUTE_ACTION,
    SANDBOX_PYTHON_RESOURCE,
    AuthorizedSandboxExecutor,
)
from agenticos.security.docker_sandbox import DockerSandboxBackend
from agenticos.security.policy import Permission, PermissionPolicy
from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxPolicy,
)


class StubBackend(DockerSandboxBackend):
    def __init__(self) -> None:
        super().__init__(SandboxPolicy())
        self.calls = 0

    async def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        self.calls += 1
        return SandboxExecutionResult(
            exit_code=0, stdout="sandbox result", stderr="", timed_out=False
        )


def make_approvals(tmp_path):
    return HumanApprovalManager(
        SQLiteExecutionApprovalStore(tmp_path / "approvals.sqlite3"),
        allowed_approvers={"human-reviewer"},
    )


@pytest.mark.asyncio
async def test_request_tool_only_creates_human_review_request(tmp_path) -> None:
    approvals = make_approvals(tmp_path)
    tool = RequestCodeExecutionApprovalTool(approvals, "trusted-agent")
    request = SandboxExecutionRequest(source="print('hello')")

    response = await tool.execute({"request": request.model_dump(mode="json")})

    review = approvals.get_review(response["approval_id"])
    assert response["status"] == "pending_human_review"
    assert review is not None
    assert review["requester_id"] == "trusted-agent"
    assert review["request"]["source"] == "print('hello')"


@pytest.mark.asyncio
async def test_execution_tool_requires_matching_human_approval(tmp_path) -> None:
    approvals = make_approvals(tmp_path)
    backend = StubBackend()
    permissions = PermissionPolicy(
        {
            Permission(
                "trusted-agent", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE
            )
        }
    )
    executor = AuthorizedSandboxExecutor(backend, permissions, AuditLog(), approvals)
    tool = ExecuteApprovedCodeTool(executor, "trusted-agent")
    request = SandboxExecutionRequest(source="print('hello')")
    approval_id = approvals.request("trusted-agent", request)

    with pytest.raises(PermissionError, match="human approval"):
        await tool.execute(
            {
                "approval_id": approval_id,
                "request": request.model_dump(mode="json"),
            }
        )
    assert backend.calls == 0


@pytest.mark.asyncio
async def test_execution_tool_runs_only_after_human_approval(tmp_path) -> None:
    approvals = make_approvals(tmp_path)
    backend = StubBackend()
    permissions = PermissionPolicy(
        {
            Permission(
                "trusted-agent", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE
            )
        }
    )
    executor = AuthorizedSandboxExecutor(backend, permissions, AuditLog(), approvals)
    tool = ExecuteApprovedCodeTool(executor, "trusted-agent")
    request = SandboxExecutionRequest(source="print('hello')")
    approval_id = approvals.request("trusted-agent", request)
    approvals.approve(approval_id, "human-reviewer")

    response = await tool.execute(
        {
            "approval_id": approval_id,
            "request": request.model_dump(mode="json"),
        }
    )

    assert response["stdout"] == "sandbox result"
    assert backend.calls == 1


@pytest.mark.asyncio
async def test_execution_tool_cannot_change_approved_source(tmp_path) -> None:
    approvals = make_approvals(tmp_path)
    backend = StubBackend()
    permissions = PermissionPolicy(
        {
            Permission(
                "trusted-agent", SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE
            )
        }
    )
    executor = AuthorizedSandboxExecutor(backend, permissions, AuditLog(), approvals)
    tool = ExecuteApprovedCodeTool(executor, "trusted-agent")
    approved = SandboxExecutionRequest(source="print('approved')")
    approval_id = approvals.request("trusted-agent", approved)
    approvals.approve(approval_id, "human-reviewer")

    with pytest.raises(PermissionError, match="human approval"):
        await tool.execute(
            {
                "approval_id": approval_id,
                "request": SandboxExecutionRequest(
                    source="print('changed')"
                ).model_dump(mode="json"),
            }
        )
    assert backend.calls == 0
