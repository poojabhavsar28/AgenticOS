"""Tests for workspace path validation."""

from pathlib import Path

import pytest

from agenticos.security.workspace import WorkspaceBoundaryError, resolve_workspace_path


def test_resolves_path_inside_workspace(tmp_path: Path) -> None:
    result = resolve_workspace_path(tmp_path, "project", "src/main.py")
    assert result == (tmp_path / "project" / "src" / "main.py").resolve()


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBoundaryError):
        resolve_workspace_path(tmp_path, "project", "../../outside")


def test_rejects_workspace_separator(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBoundaryError):
        resolve_workspace_path(tmp_path, "../outside")
