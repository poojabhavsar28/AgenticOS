"""Workspace-scoped file access and explicit staged-write approval."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from agenticos.security.workspace import resolve_workspace_path


@dataclass(frozen=True)
class StagedChange:
    change_id: str
    workspace: str
    relative_path: str
    content: str
    size_bytes: int


class WorkspaceFileService:
    """Read workspace files and apply writes only after explicit approval."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        max_file_bytes: int = 1_000_000,
        max_list_entries: int = 500,
    ) -> None:
        if max_file_bytes < 1 or max_list_entries < 1:
            raise ValueError("Workspace limits must be positive")
        self.workspace_root = workspace_root.expanduser().resolve()
        self.max_file_bytes = max_file_bytes
        self.max_list_entries = max_list_entries
        self._staged: dict[str, StagedChange] = {}

    def _workspace(self, workspace: str) -> Path:
        return resolve_workspace_path(self.workspace_root, workspace)

    def _file_path(self, workspace: str, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise ValueError("A relative file path is required")
        if "\x00" in relative_path:
            raise ValueError("File path contains a null byte")
        base = self._workspace(workspace)
        target = resolve_workspace_path(self.workspace_root, workspace, relative_path)
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError("File path escapes its workspace") from exc
        return target

    def read_text(self, workspace: str, relative_path: str) -> str:
        path = self._file_path(workspace, relative_path)
        if not path.is_file():
            raise FileNotFoundError("Workspace file not found")
        if path.stat().st_size > self.max_file_bytes:
            raise ValueError("File exceeds configured read limit")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Only UTF-8 text files can be read") from exc

    def list_files(self, workspace: str) -> tuple[str, ...]:
        base = self._workspace(workspace)
        files: list[str] = []
        for path in base.rglob("*"):
            try:
                resolved = path.resolve()
                resolved.relative_to(base)
            except (OSError, ValueError):
                continue
            if path.is_file() and not path.is_symlink():
                files.append(path.relative_to(base).as_posix())
                if len(files) > self.max_list_entries:
                    raise ValueError("Workspace contains more files than the configured list limit")
        return tuple(sorted(files))

    def stage_write(self, workspace: str, relative_path: str, content: str) -> StagedChange:
        path = self._file_path(workspace, relative_path)
        if not isinstance(content, str):
            raise ValueError("File content must be text")
        size_bytes = len(content.encode("utf-8"))
        if size_bytes > self.max_file_bytes:
            raise ValueError("Proposed file exceeds configured write limit")
        if path.exists() and not path.is_file():
            raise ValueError("Target path is not a regular file")
        change = StagedChange(
            change_id=str(uuid4()),
            workspace=workspace,
            relative_path=relative_path,
            content=content,
            size_bytes=size_bytes,
        )
        self._staged[change.change_id] = change
        return change

    def pending_changes(self) -> tuple[StagedChange, ...]:
        return tuple(self._staged[key] for key in sorted(self._staged))

    def reject(self, change_id: str) -> None:
        if self._staged.pop(change_id, None) is None:
            raise KeyError("Staged change not found")

    def approve(self, change_id: str) -> Path:
        change = self._staged.get(change_id)
        if change is None:
            raise KeyError("Staged change not found")
        target = self._file_path(change.workspace, change.relative_path)
        if target.exists() and not target.is_file():
            raise ValueError("Target path is not a regular file")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after creating parents to reject symlink escapes.
        target = self._file_path(change.workspace, change.relative_path)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=".agenticos-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(change.content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = temporary.name
            os.replace(temporary_path, target)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        del self._staged[change_id]
        return target
