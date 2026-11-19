import pytest

from agenticos.security import (
    ExecutionLimits,
    SafeCodeExecutor,
    SandboxUnavailable,
)


def test_execution_fails_closed_without_isolation_backend() -> None:
    executor = SafeCodeExecutor()
    with pytest.raises(SandboxUnavailable, match="execution is disabled"):
        import asyncio

        asyncio.run(executor.execute("print('unsafe')"))


def test_empty_source_is_rejected_before_backend_use() -> None:
    executor = SafeCodeExecutor()
    with pytest.raises(ValueError, match="cannot be empty"):
        import asyncio

        asyncio.run(executor.execute("  "))


def test_execution_limits_are_validated() -> None:
    with pytest.raises(ValueError, match="invalid"):
        ExecutionLimits(timeout_seconds=0)
