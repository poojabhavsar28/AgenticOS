"""Path validation for workspace-scoped file operations."""

from pathlib import Path


class WorkspaceBoundaryError(ValueError):
    """Raised when a requested path escapes its workspace."""


def resolve_workspace_path(root: Path, workspace: str, relative_path: str = ".") -> Path:
    if (
        not workspace
        or workspace in {".", ".."}
        or any(ch in workspace for ch in "/\\")
    ):
        raise WorkspaceBoundaryError("Invalid workspace name")

    root_path = root.expanduser().resolve()
    workspace_path = (root_path / workspace).resolve()
    try:
        workspace_path.relative_to(root_path)
    except ValueError as exc:
        raise WorkspaceBoundaryError(
            "Requested workspace is outside the workspace root"
        ) from exc

    candidate = (workspace_path / relative_path).resolve()
    try:
        candidate.relative_to(workspace_path)
    except ValueError as exc:
        raise WorkspaceBoundaryError(
            "Requested path is outside the selected workspace"
        ) from exc
    return candidate
