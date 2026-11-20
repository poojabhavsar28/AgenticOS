"""Typed contracts and immutable policy for isolated code execution."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agenticos.config import Settings


class SandboxLimits(BaseModel):
    """Hard upper bounds requested from the sandbox runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    cpu_count: float = Field(default=1.0, gt=0, le=2)
    memory_megabytes: int = Field(default=128, ge=32, le=1024)
    pid_limit: int = Field(default=64, ge=1, le=256)
    max_source_bytes: int = Field(default=128_000, ge=1, le=1_000_000)
    max_output_bytes: int = Field(default=64_000, ge=1, le=256_000)
    tmpfs_megabytes: int = Field(default=16, ge=1, le=128)


class SandboxPolicy(BaseModel):
    """Administrator-owned sandbox policy; callers cannot weaken isolation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    image_ref: str | None = None
    limits: SandboxLimits = Field(default_factory=SandboxLimits)
    network_enabled: Literal[False] = False
    read_only_rootfs: Literal[True] = True
    non_root: Literal[True] = True
    drop_all_capabilities: Literal[True] = True
    no_new_privileges: Literal[True] = True

    @field_validator("image_ref")
    @classmethod
    def image_must_be_digest_pinned(cls, value: str | None) -> str | None:
        if value is not None and not re.search(r"@sha256:[0-9a-f]{64}$", value):
            raise ValueError("Sandbox image must be pinned by a full sha256 digest")
        return value

    @model_validator(mode="after")
    def enabled_requires_image(self) -> "SandboxPolicy":
        if self.enabled and not self.image_ref:
            raise ValueError("Enabled sandbox requires an approved digest-pinned image")
        return self


class SandboxExecutionRequest(BaseModel):
    """Narrow execution input; no caller-controlled command, image, mounts or flags."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    language: Literal["python"] = "python"
    limits: SandboxLimits = Field(default_factory=SandboxLimits)

    @field_validator("source")
    @classmethod
    def source_must_fit_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 1_000_000:
            raise ValueError("Source exceeds the absolute input limit")
        if not value.strip():
            raise ValueError("Source code cannot be blank")
        return value


class SandboxExecutionResult(BaseModel):
    """Bounded, sanitized result returned by an isolated backend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exit_code: int
    stdout: str = Field(max_length=256_000)
    stderr: str = Field(max_length=256_000)
    timed_out: bool = False
    output_truncated: bool = False


def sandbox_policy_from_settings(settings: Settings) -> SandboxPolicy:
    """Build the immutable sandbox policy from administrator-owned settings."""
    return SandboxPolicy(
        enabled=settings.sandbox_enabled,
        image_ref=settings.sandbox_image,
    )
