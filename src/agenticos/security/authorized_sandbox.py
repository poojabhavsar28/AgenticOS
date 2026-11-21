"""Authorization, human approval, and audit boundary for sandbox execution."""

from typing import Protocol

from agenticos.security.approval import ApprovalError, HumanApprovalManager
from agenticos.security.docker_sandbox import DockerSandboxBackend
from agenticos.security.policy import PermissionDenied, PermissionPolicy
from agenticos.security.sandbox import SandboxExecutionRequest, SandboxExecutionResult

SANDBOX_EXECUTE_ACTION = "sandbox.execute"
SANDBOX_PYTHON_RESOURCE = "sandbox:python"


class AuditRecorder(Protocol):
    """Minimal audit interface; supports in-memory and persistent stores."""

    def record(
        self, principal_id: str, action: str, resource: str, outcome: str
    ) -> object:
        """Persist or buffer one metadata-only security event."""


class AuditCompletionError(RuntimeError):
    """Execution finished, but its terminal audit event could not be persisted."""

    def __init__(self, result: SandboxExecutionResult) -> None:
        self.result = result
        super().__init__(
            "Sandbox execution completed, but completion audit persistence failed; "
            "do not retry automatically. The execution result is attached."
        )


class AuthorizedSandboxExecutor:
    """Require permission and a one-time human approval before code execution."""

    def __init__(
        self,
        backend: DockerSandboxBackend,
        permissions: PermissionPolicy,
        audit_log: AuditRecorder,
        approvals: HumanApprovalManager,
    ) -> None:
        self.backend = backend
        self.permissions = permissions
        self.audit_log = audit_log
        self.approvals = approvals

    async def execute(
        self,
        principal_id: str,
        request: SandboxExecutionRequest,
        *,
        approval_id: str,
    ) -> SandboxExecutionResult:
        try:
            self.permissions.authorize(
                principal_id, SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE
            )
        except PermissionDenied:
            self.audit_log.record(
                principal_id, SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE, "denied"
            )
            raise

        try:
            self.approvals.consume(approval_id, principal_id, request)
        except ApprovalError:
            self.audit_log.record(
                principal_id,
                SANDBOX_EXECUTE_ACTION,
                SANDBOX_PYTHON_RESOURCE,
                "approval_denied",
            )
            raise

        # Fail closed if the audit store is unavailable before execution.
        self.audit_log.record(
            principal_id, SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE, "started"
        )
        try:
            result = await self.backend.execute(request)
        except BaseException:
            self.audit_log.record(
                principal_id, SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE, "failed"
            )
            raise

        try:
            self.audit_log.record(
                principal_id,
                SANDBOX_EXECUTE_ACTION,
                SANDBOX_PYTHON_RESOURCE,
                "timed_out" if result.timed_out else "completed",
            )
        except Exception as exc:
            # Execution already happened. Preserve the result and make the
            # ambiguous audit outcome explicit so callers do not blindly retry.
            raise AuditCompletionError(result) from exc
        return result
