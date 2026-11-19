"""Tests for workspace file boundaries and explicit patch approval."""

from pathlib import Path

import pytest

from agenticos.workspace import WorkspaceFileService


def test_read_and_list_workspace_files(tmp_path: Path) -> None:
    service = WorkspaceFileService(tmp_path)
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "README.md").write_text("# AgenticOS", encoding="utf-8")
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print('ok')", encoding="utf-8")

    assert service.read_text("project", "README.md") == "# AgenticOS"
    assert service.list_files("project") == ("README.md", "src/app.py")


def test_staged_write_does_not_modify_file_before_approval(tmp_path: Path) -> None:
    service = WorkspaceFileService(tmp_path)
    workspace = tmp_path / "project"
    workspace.mkdir()
    target = workspace / "app.py"
    target.write_text("old = True", encoding="utf-8")

    change = service.stage_write("project", "app.py", "new = True")

    assert target.read_text(encoding="utf-8") == "old = True"
    assert service.pending_changes() == (change,)

    written_path = service.approve(change.change_id)
    assert written_path == target
    assert target.read_text(encoding="utf-8") == "new = True"
    assert service.pending_changes() == ()


def test_rejected_change_is_never_written(tmp_path: Path) -> None:
    service = WorkspaceFileService(tmp_path)
    change = service.stage_write("project", "new.py", "print('not approved')")

    service.reject(change.change_id)

    assert not (tmp_path / "project" / "new.py").exists()
    with pytest.raises(KeyError, match="not found"):
        service.approve(change.change_id)


@pytest.mark.parametrize(
    "relative_path",
    ["../outside.txt", "../../escape.py", "/absolute/path.py"],
)
def test_file_operations_reject_paths_outside_workspace(
    tmp_path: Path, relative_path: str
) -> None:
    service = WorkspaceFileService(tmp_path)

    with pytest.raises(ValueError):
        service.stage_write("project", relative_path, "unsafe")


def test_read_rejects_missing_and_oversized_files(tmp_path: Path) -> None:
    service = WorkspaceFileService(tmp_path, max_file_bytes=4)
    with pytest.raises(FileNotFoundError):
        service.read_text("project", "missing.txt")

    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "large.txt").write_text("12345", encoding="utf-8")
    with pytest.raises(ValueError, match="read limit"):
        service.read_text("project", "large.txt")


def test_stage_rejects_oversized_content_and_invalid_limits(tmp_path: Path) -> None:
    service = WorkspaceFileService(tmp_path, max_file_bytes=4)
    with pytest.raises(ValueError, match="write limit"):
        service.stage_write("project", "large.txt", "12345")

    with pytest.raises(ValueError, match="positive"):
        WorkspaceFileService(tmp_path, max_file_bytes=0)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    service = WorkspaceFileService(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        service.stage_write("project", "link/secret.txt", "overwrite")
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"
