"""Default-deny permission policy for agent capabilities."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    principal_id: str
    action: str
    resource: str

    def __post_init__(self) -> None:
        if not self.principal_id.strip() or not self.action.strip() or not self.resource.strip():
            raise ValueError("Permission fields must be non-empty")


class PermissionDenied(PermissionError):
    """Raised when a principal attempts an operation without an explicit grant."""


class PermissionPolicy:
    """Exact-match grants; absence of a grant always means deny."""

    def __init__(self, grants: set[Permission] | None = None) -> None:
        self._grants = set(grants or ())

    def grant(self, permission: Permission) -> None:
        self._grants.add(permission)

    def revoke(self, permission: Permission) -> None:
        self._grants.discard(permission)

    def is_allowed(self, principal_id: str, action: str, resource: str) -> bool:
        return Permission(principal_id, action, resource) in self._grants

    def authorize(self, principal_id: str, action: str, resource: str) -> None:
        permission = Permission(principal_id, action, resource)
        if permission not in self._grants:
            raise PermissionDenied(
                f"Permission denied: {principal_id} cannot {action} {resource}"
            )
