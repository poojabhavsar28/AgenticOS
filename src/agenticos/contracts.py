"""Validated request and response contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    workspace: str = Field(
        default="default", min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    session_id: str = Field(
        default="default", min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    max_steps: int = Field(default=8, ge=1, le=32)
    include_repository_context: bool = False


class RunResponse(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    plan: str
    code: str
    review: str
    test_plan: str


class WorkspaceStageRequest(BaseModel):
    relative_path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1_000_000)


class WorkspaceReadResponse(BaseModel):
    workspace: str
    relative_path: str
    content: str


class WorkspaceChangeResponse(BaseModel):
    change_id: str
    workspace: str
    relative_path: str
    size_bytes: int
    status: Literal["pending"] = "pending"
