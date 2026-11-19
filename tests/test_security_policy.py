import pytest

from agenticos.security import Permission, PermissionDenied, PermissionPolicy


def test_policy_denies_by_default() -> None:
    policy = PermissionPolicy()
    assert not policy.is_allowed("planner", "execute", "read_file")
    with pytest.raises(PermissionDenied):
        policy.authorize("planner", "execute", "read_file")


def test_policy_requires_exact_principal_action_and_resource() -> None:
    policy = PermissionPolicy({Permission("planner", "execute", "read_file")})
    policy.authorize("planner", "execute", "read_file")
    with pytest.raises(PermissionDenied):
        policy.authorize("coder", "execute", "read_file")
    with pytest.raises(PermissionDenied):
        policy.authorize("planner", "execute", "write_file")


def test_permission_can_be_revoked() -> None:
    permission = Permission("planner", "execute", "read_file")
    policy = PermissionPolicy({permission})
    policy.revoke(permission)
    assert not policy.is_allowed("planner", "execute", "read_file")
