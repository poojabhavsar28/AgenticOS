"""Validated request and response contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    workspace: str = Field(default="default", min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    max_steps: int = Field(default=8, ge=1, le=32)


class RunResponse(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    plan: str
    code: str
    review: str
    test_plan: str
