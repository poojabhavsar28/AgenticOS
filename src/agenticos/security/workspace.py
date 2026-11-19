"""Path validation for workspace-scoped file operations."""

from pathlib import Path


class WorkspaceBoundaryError(ValueError):
    """Raised when a requested path escapes the workspace root."""


def resolve_workspace_path(root: Path, workspace: str, relative_path: str = ".") -> Path:
    if not workspace or workspace in {".", ".."} or any(ch in workspace for ch in "/\\"):
        raise WorkspaceBoundaryError("Invalid workspace name")
    root_path = root.expanduser().resolve()
    candidate = (root_path / workspace / relative_path).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise WorkspaceBoundaryError("Requested path is outside the workspace root") from exc
    return candidate
