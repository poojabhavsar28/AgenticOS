"""Explicit agent-tool adapters for human-gated sandbox execution."""

from agenticos.security.approval import HumanApprovalManager
from agenticos.security.authorized_sandbox import AuthorizedSandboxExecutor
from agenticos.security.sandbox import SandboxExecutionRequest


class RequestCodeExecutionApprovalTool:
    """Submit generated Python code for human review; never executes code."""

    name = "request_code_execution"

    def __init__(self, approvals: HumanApprovalManager, requester_id: str) -> None:
        if not requester_id.strip():
            raise ValueError("Requester identity must be non-empty")
        self.approvals = approvals
        self.requester_id = requester_id

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        request = SandboxExecutionRequest.model_validate(arguments.get("request"))
        approval = self.approvals.request(self.requester_id, request)
        return {
            "review_id": approval["review_id"],
            "approval_token": approval["approval_token"],
            "status": "pending_human_review",
            "message": "Execution is not permitted until a human approves this exact request.",
        }


class ExecuteApprovedCodeTool:
    """Execute code only through the permission- and approval-enforcing executor."""

    name = "execute_approved_code"

    def __init__(self, executor: AuthorizedSandboxExecutor, principal_id: str) -> None:
        if not principal_id.strip():
            raise ValueError("Principal identity must be non-empty")
        self.executor = executor
        self.principal_id = principal_id

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        request = SandboxExecutionRequest.model_validate(arguments.get("request"))
        approval_token = arguments.get("approval_token")
        if not isinstance(approval_token, str) or not approval_token.strip():
            raise ValueError("approval_token is required")
        result = await self.executor.execute(
            self.principal_id, request, approval_token=approval_token
        )
        return result.model_dump(mode="json")
