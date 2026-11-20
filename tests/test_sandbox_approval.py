import pytest

from agenticos.security.approval import (
    ApprovalError,
    HumanApprovalManager,
    SQLiteExecutionApprovalStore,
)
from agenticos.security.sandbox import SandboxExecutionRequest, SandboxLimits


def make_manager(tmp_path):
    store = SQLiteExecutionApprovalStore(tmp_path / "approvals.sqlite3")
    return HumanApprovalManager(store, allowed_approvers={"human-admin"})


def test_approval_is_bound_to_exact_request_and_consumed_once(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="print('hello')")
    approval_id = manager.request("agent-1", request)

    manager.approve(approval_id, "human-admin")
    manager.consume(approval_id, "agent-1", request)

    with pytest.raises(ApprovalError, match="valid, matching"):
        manager.consume(approval_id, "agent-1", request)


def test_approval_rejects_changed_source_or_limits(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="print('hello')")
    approval_id = manager.request("agent-1", request)
    manager.approve(approval_id, "human-admin")

    changed = SandboxExecutionRequest(
        source="print('changed')", limits=SandboxLimits(timeout_seconds=10)
    )
    with pytest.raises(ApprovalError):
        manager.consume(approval_id, "agent-1", changed)


def test_requester_cannot_approve_own_execution(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    approval_id = manager.request("human-admin", request)

    with pytest.raises(ApprovalError, match="cannot approve their own"):
        manager.approve(approval_id, "human-admin")


def test_unapproved_principal_cannot_approve(tmp_path):
    manager = make_manager(tmp_path)
    approval_id = manager.request("agent-1", SandboxExecutionRequest(source="pass"))

    with pytest.raises(ApprovalError, match="not authorized"):
        manager.approve(approval_id, "agent-2")


def test_approval_expires(tmp_path, monkeypatch):
    import agenticos.security.approval as approval_module

    now = [1000.0]
    monkeypatch.setattr(approval_module.time, "time", lambda: now[0])
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    approval_id = manager.request("agent-1", request, ttl_seconds=2)
    now[0] = 1003.0

    with pytest.raises(ApprovalError, match="expired"):
        manager.approve(approval_id, "human-admin")


def test_approval_token_is_not_reusable_for_another_requester(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    approval_id = manager.request("agent-1", request)
    manager.approve(approval_id, "human-admin")

    with pytest.raises(ApprovalError):
        manager.consume(approval_id, "agent-2", request)


def test_approval_lifetime_is_bounded(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(ValueError, match="between 1 and 900"):
        manager.request("agent-1", SandboxExecutionRequest(source="pass"), ttl_seconds=901)


def test_review_source_is_cleared_after_approval(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="print('sensitive review source')")
    approval_id = manager.request("agent-1", request)

    pending = manager.get_review(approval_id)
    assert pending is not None
    assert pending["request"]["source"] == "print('sensitive review source')"

    manager.approve(approval_id, "human-admin")
    approved = manager.get_review(approval_id)
    assert approved is not None
    assert approved["status"] == "approved"
    assert approved["request"] is None
    assert approved["request_hash"] == manager.store.fingerprint(request)
