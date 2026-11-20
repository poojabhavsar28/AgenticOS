"""Explicit agent-tool adapters for human-gated sandbox execution."""

from agenticos.security.approval import HumanApprovalManager
from agenticos.security.authorized_sandbox import AuthorizedSandboxExecutor
from agenticos.security.sandbox import SandboxExecutionRequest


class RequestCodeExecutionApprovalTool:
    """Submit generated Python code for human review; never executes code."""

    name = "request_code_execution"

    def __init__(self, approvals: HumanApprovalManager) -> None:
        self.approvals = approvals

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        request = SandboxExecutionRequest.model_validate(arguments.get("request"))
        requester_id = arguments.get("principal_id")
        if not isinstance(requester_id, str) or not requester_id.strip():
            raise ValueError("Authenticated principal_id is required")
        approval_id = self.approvals.request(requester_id, request)
        return {
            "approval_id": approval_id,
            "status": "pending_human_review",
            "message": "Execution is not permitted until a human approves this exact request.",
        }


class ExecuteApprovedCodeTool:
    """Execute code only through the permission- and approval-enforcing executor."""

    name = "execute_approved_code"

    def __init__(self, executor: AuthorizedSandboxExecutor) -> None:
        self.executor = executor

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        request = SandboxExecutionRequest.model_validate(arguments.get("request"))
        principal_id = arguments.get("principal_id")
        approval_id = arguments.get("approval_id")
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("Authenticated principal_id is required")
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise ValueError("approval_id is required")
        result = await self.executor.execute(
            principal_id, request, approval_id=approval_id
        )
        return result.model_dump(mode="json")
