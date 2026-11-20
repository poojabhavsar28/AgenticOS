"""Authorization and audit boundary for sandbox execution."""

from agenticos.security.audit import AuditLog
from agenticos.security.docker_sandbox import DockerSandboxBackend
from agenticos.security.policy import PermissionDenied, PermissionPolicy
from agenticos.security.sandbox import SandboxExecutionRequest, SandboxExecutionResult

SANDBOX_EXECUTE_ACTION = "sandbox.execute"
SANDBOX_PYTHON_RESOURCE = "sandbox:python"


class AuthorizedSandboxExecutor:
    """Require an explicit grant and audit each sandbox execution attempt.

    Audit records contain only principal, fixed action/resource, and outcome;
    source code and process output are deliberately excluded.
    """

    def __init__(
        self,
        backend: DockerSandboxBackend,
        permissions: PermissionPolicy,
        audit_log: AuditLog,
    ) -> None:
        self.backend = backend
        self.permissions = permissions
        self.audit_log = audit_log

    async def execute(
        self, principal_id: str, request: SandboxExecutionRequest
    ) -> SandboxExecutionResult:
        try:
            self.permissions.authorize(
                principal_id, SANDBOX_EXECUTE_ACTION, SANDBOX_PYTHON_RESOURCE
            )
        except PermissionDenied:
            self.audit_log.record(
                principal_id,
                SANDBOX_EXECUTE_ACTION,
                SANDBOX_PYTHON_RESOURCE,
                "denied",
            )
            raise

        # If the audit store is unavailable, fail closed before running code.
        self.audit_log.record(
            principal_id,
            SANDBOX_EXECUTE_ACTION,
            SANDBOX_PYTHON_RESOURCE,
            "started",
        )
        try:
            result = await self.backend.execute(request)
        except BaseException:
            self.audit_log.record(
                principal_id,
                SANDBOX_EXECUTE_ACTION,
                SANDBOX_PYTHON_RESOURCE,
                "failed",
            )
            raise

        self.audit_log.record(
            principal_id,
            SANDBOX_EXECUTE_ACTION,
            SANDBOX_PYTHON_RESOURCE,
            "timed_out" if result.timed_out else "completed",
        )
        return result
