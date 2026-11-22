from pathlib import Path

import pytest

from agenticos.security.approval import (
    ApprovalCapacityError,
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
    approval = manager.request("agent-1", request)
    review_id, token = approval["review_id"], approval["approval_token"]

    manager.approve(review_id, "human-admin")
    manager.consume(token, "agent-1", request)

    with pytest.raises(ApprovalError, match="valid, matching"):
        manager.consume(token, "agent-1", request)


def test_approval_rejects_changed_source_or_limits(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="print('hello')")
    approval = manager.request("agent-1", request)
    review_id, token = approval["review_id"], approval["approval_token"]
    manager.approve(review_id, "human-admin")

    changed = SandboxExecutionRequest(
        source="print('changed')", limits=SandboxLimits(timeout_seconds=10)
    )
    with pytest.raises(ApprovalError):
        manager.consume(token, "agent-1", changed)


def test_requester_cannot_approve_own_execution(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    review_id = manager.request("human-admin", request)["review_id"]

    with pytest.raises(ApprovalError, match="cannot approve their own"):
        manager.approve(review_id, "human-admin")


def test_unapproved_principal_cannot_approve(tmp_path):
    manager = make_manager(tmp_path)
    review_id = manager.request("agent-1", SandboxExecutionRequest(source="pass"))["review_id"]

    with pytest.raises(ApprovalError, match="not authorized"):
        manager.approve(review_id, "agent-2")


def test_approval_expires(tmp_path, monkeypatch):
    import agenticos.security.approval as approval_module

    now = [1000.0]
    monkeypatch.setattr(approval_module.time, "time", lambda: now[0])
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    review_id = manager.request("agent-1", request, ttl_seconds=2)["review_id"]
    now[0] = 1003.0

    with pytest.raises(ApprovalError, match="expired"):
        manager.approve(review_id, "human-admin")


def test_approval_token_is_not_reusable_for_another_requester(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    approval = manager.request("agent-1", request)
    review_id, token = approval["review_id"], approval["approval_token"]
    manager.approve(review_id, "human-admin")

    with pytest.raises(ApprovalError):
        manager.consume(token, "agent-2", request)


def test_approval_lifetime_is_bounded(tmp_path):
    manager = make_manager(tmp_path)
    with pytest.raises(ValueError, match="between 1 and 900"):
        manager.request("agent-1", SandboxExecutionRequest(source="pass"), ttl_seconds=901)


def test_review_source_is_cleared_after_approval(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="print('sensitive review source')")
    review_id = manager.request("agent-1", request)["review_id"]

    pending = manager.get_review(review_id)
    assert pending is not None
    assert pending["request"]["source"] == "print('sensitive review source')"

    manager.approve(review_id, "human-admin")
    approved = manager.get_review(review_id)
    assert approved is not None
    assert approved["status"] == "approved"
    assert approved["request"] is None
    assert approved["request_hash"] == manager.store.fingerprint(request)



def test_raw_approval_token_is_never_persisted(tmp_path):
    import sqlite3

    database = tmp_path / "approvals.sqlite3"
    manager = HumanApprovalManager(
        SQLiteExecutionApprovalStore(database), allowed_approvers={"human-admin"}
    )
    approval = manager.request("agent-1", SandboxExecutionRequest(source="pass"))
    token = approval["approval_token"]
    review_id = approval["review_id"]

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT approval_id, public_id FROM sandbox_execution_approvals"
        ).fetchone()

    assert token not in row
    assert row[0] == manager.store._approval_digest(token)
    assert row[1] == review_id
    assert len(review_id) == 32


def test_approval_store_restricts_dedicated_directory_and_database(tmp_path):
    import os
    import stat

    from agenticos.security.sqlite_storage import harden_sqlite_files

    if os.name == "nt":
        pytest.skip("POSIX mode bits are not an authoritative Windows ACL check")

    data_dir = tmp_path / ".agenticos"
    data_dir.mkdir(mode=0o755)
    database = data_dir / "approvals.sqlite3"
    SQLiteExecutionApprovalStore(database)

    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600

    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        sidecar.write_text("test", encoding="utf-8")
        sidecar.chmod(0o644)

    harden_sqlite_files(database)

    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_approval_store_rejects_insecure_shared_directory(tmp_path):
    import os

    if os.name == "nt":
        pytest.skip("POSIX directory mode check is not applicable on Windows")

    shared_dir = tmp_path / "shared"
    shared_dir.mkdir(mode=0o755)
    shared_dir.chmod(0o755)

    with pytest.raises(PermissionError, match="dedicated private directory"):
        SQLiteExecutionApprovalStore(shared_dir / "approvals.sqlite3")



def test_pending_approval_queue_is_bounded_per_requester(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")

    for _ in range(manager.store.MAX_PENDING_PER_REQUESTER):
        manager.request("agent-1", request)

    with pytest.raises(ApprovalCapacityError, match="capacity"):
        manager.request("agent-1", request)

    # Capacity is scoped per requester, not a blanket lockout.
    manager.request("agent-2", request)


def test_pending_approval_queue_has_global_limit(tmp_path):
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")

    for index in range(manager.store.MAX_PENDING_APPROVALS):
        manager.request(f"agent-{index}", request)

    with pytest.raises(ApprovalCapacityError, match="capacity"):
        manager.request("another-agent", request)


def test_expired_pending_approvals_are_reclaimed_when_queue_is_full(tmp_path, monkeypatch):
    import agenticos.security.approval as approval_module

    now = [1000.0]
    monkeypatch.setattr(approval_module.time, "time", lambda: now[0])
    manager = make_manager(tmp_path)
    manager.store.MAX_PENDING_APPROVALS = 1
    manager.request("agent-1", SandboxExecutionRequest(source="pass"), ttl_seconds=1)

    now[0] = 1002.0
    manager.request("agent-2", SandboxExecutionRequest(source="pass"))

    assert [item["requester_id"] for item in manager.list_pending()] == ["agent-2"]



def test_approved_request_expires_and_releases_pending_source(tmp_path, monkeypatch):
    import agenticos.security.approval as approval_module

    now = [1000.0]
    monkeypatch.setattr(approval_module.time, "time", lambda: now[0])
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="print('sensitive')")
    review_id = manager.request("agent-1", request, ttl_seconds=2)["review_id"]
    manager.approve(review_id, "human-admin")

    now[0] = 1003.0
    manager.request("agent-2", SandboxExecutionRequest(source="pass"))
    expired = manager.get_review(review_id)

    assert expired is not None
    assert expired["status"] == "expired"
    assert expired["request"] is None


def test_terminal_approval_history_is_pruned_after_retention_window(
    tmp_path, monkeypatch
):
    import agenticos.security.approval as approval_module

    now = [1000.0]
    monkeypatch.setattr(approval_module.time, "time", lambda: now[0])
    manager = make_manager(tmp_path)
    request = SandboxExecutionRequest(source="pass")
    review_id = manager.request("agent-1", request, ttl_seconds=1)["review_id"]

    now[0] = 1002.0
    manager.request("agent-2", request)
    assert manager.get_review(review_id)["status"] == "expired"

    now[0] += manager.store.TERMINAL_RETENTION_SECONDS + 1
    manager.request("agent-3", request)
    assert manager.get_review(review_id) is None
