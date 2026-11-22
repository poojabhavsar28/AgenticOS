"""Tests for workspace path validation and cross-workspace isolation."""

from pathlib import Path

import pytest

from agenticos.security.workspace import WorkspaceBoundaryError, resolve_workspace_path


def test_resolves_path_inside_workspace(tmp_path: Path) -> None:
    result = resolve_workspace_path(tmp_path, "project", "src/main.py")
    assert result == (tmp_path / "project" / "src" / "main.py").resolve()


def test_rejects_parent_traversal_outside_workspace(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBoundaryError):
        resolve_workspace_path(tmp_path, "project", "../../outside")


def test_rejects_traversal_into_sibling_workspace(tmp_path: Path) -> None:
    (tmp_path / "project-a").mkdir()
    (tmp_path / "project-b").mkdir()
    with pytest.raises(WorkspaceBoundaryError, match="selected workspace"):
        resolve_workspace_path(tmp_path, "project-a", "../project-b/secret.txt")


def test_rejects_workspace_separator(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBoundaryError):
        resolve_workspace_path(tmp_path, "../outside")


def test_rejects_workspace_symlink_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    try:
        with pytest.raises(WorkspaceBoundaryError, match="workspace is outside"):
            resolve_workspace_path(tmp_path, "linked", "secret.txt")
    finally:
        (tmp_path / "linked").unlink()
        outside.rmdir()


def test_rejects_symlinked_file_into_sibling_workspace(tmp_path: Path) -> None:
    first = tmp_path / "project-a"
    second = tmp_path / "project-b"
    first.mkdir()
    second.mkdir()
    secret = second / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    try:
        (first / "leak.txt").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    with pytest.raises(WorkspaceBoundaryError, match="selected workspace"):
        resolve_workspace_path(tmp_path, "project-a", "leak.txt")
