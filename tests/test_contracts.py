"""Tests for API contracts."""

import pytest
from pydantic import ValidationError

from agenticos.contracts import RunRequest


def test_run_request_defaults() -> None:
    request = RunRequest(task="Add a health endpoint")
    assert request.workspace == "default"
    assert request.max_steps == 8


def test_run_request_rejects_empty_task() -> None:
    with pytest.raises(ValidationError):
        RunRequest(task="")


def test_run_request_rejects_invalid_workspace() -> None:
    with pytest.raises(ValidationError):
        RunRequest(task="task", workspace="../outside")
