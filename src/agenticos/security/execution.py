"""Fail-closed execution boundary for generated code."""

from dataclasses import dataclass
from typing import Protocol


class SandboxUnavailable(RuntimeError):
    """Raised when no independently isolated execution backend is configured."""


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: float = 5.0
    memory_megabytes: int = 128
    max_output_bytes: int = 64_000

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.memory_megabytes < 16 or self.max_output_bytes < 1:
            raise ValueError("Execution limits are invalid")


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class IsolatedExecutionBackend(Protocol):
    async def execute(
        self, source: str, *, limits: ExecutionLimits
    ) -> ExecutionResult:
        """Execute source in an OS-enforced isolated environment."""


class SafeCodeExecutor:
    """Delegates only to an explicitly supplied isolation backend."""

    def __init__(
        self,
        backend: IsolatedExecutionBackend | None = None,
        *,
        limits: ExecutionLimits | None = None,
    ) -> None:
        self.backend = backend
        self.limits = limits or ExecutionLimits()

    async def execute(self, source: str) -> ExecutionResult:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Source code cannot be empty")
        if self.backend is None:
            raise SandboxUnavailable(
                "Code execution is disabled: no isolated execution backend is configured"
            )
        return await self.backend.execute(source, limits=self.limits)
