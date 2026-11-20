import pytest
from pydantic import ValidationError

from agenticos.config import Settings
from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxLimits,
    SandboxPolicy,
)


def test_sandbox_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    policy = SandboxPolicy()
    assert settings.sandbox_enabled is False
    assert settings.sandbox_image is None
    assert policy.enabled is False


def test_enabled_sandbox_requires_digest_pinned_approved_image() -> None:
    with pytest.raises(ValidationError, match="requires an approved"):
        SandboxPolicy(enabled=True)
    with pytest.raises(ValidationError, match="pinned by sha256"):
        SandboxPolicy(enabled=True, image_ref="python:3.11-slim")

    policy = SandboxPolicy(
        enabled=True,
        image_ref="registry.example/agenticos-python@sha256:" + "a" * 64,
    )
    assert policy.enabled is True


def test_isolation_guarantees_cannot_be_weakened() -> None:
    with pytest.raises(ValidationError):
        SandboxPolicy(network_enabled=True)
    with pytest.raises(ValidationError):
        SandboxPolicy(read_only_rootfs=False)
    with pytest.raises(ValidationError):
        SandboxPolicy(non_root=False)


def test_sandbox_limits_enforce_conservative_bounds() -> None:
    limits = SandboxLimits()
    assert limits.timeout_seconds == 5.0
    assert limits.memory_megabytes == 128
    with pytest.raises(ValidationError):
        SandboxLimits(timeout_seconds=120)
    with pytest.raises(ValidationError):
        SandboxLimits(memory_megabytes=4096)


def test_request_has_no_caller_controlled_runtime_options() -> None:
    request = SandboxExecutionRequest(source="print('hello')")
    assert request.language == "python"
    with pytest.raises(ValidationError):
        SandboxExecutionRequest(
            source="print('hello')",
            image="attacker/image",
        )


def test_blank_or_oversized_source_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SandboxExecutionRequest(source="  \n")
    with pytest.raises(ValidationError):
        SandboxExecutionRequest(source="x" * 1_000_001)


def test_result_is_bounded_and_immutable() -> None:
    result = SandboxExecutionResult(exit_code=0, stdout="ok", stderr="")
    assert result.output_truncated is False
    with pytest.raises(ValidationError):
        SandboxExecutionResult(exit_code=0, stdout="x" * 256_001, stderr="")
    with pytest.raises(ValidationError):
        result.exit_code = 1
