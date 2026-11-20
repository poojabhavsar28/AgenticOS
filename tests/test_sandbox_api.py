"""HTTP tests for authenticated sandbox approval and execution routes."""

from fastapi.testclient import TestClient

import pytest

from agenticos.api.main import create_app
from agenticos.config import Settings


IMAGE_REF = "python:3.11-slim@sha256:" + "a" * 64


def make_sandbox_client(fake_model, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="requester-secret",
        sandbox_enabled=True,
        sandbox_image=IMAGE_REF,
        sandbox_approval_token="human-approval-secret",
        sandbox_approver_id="human-reviewer",
        sandbox_execution_principal="local-operator",
    )
    return TestClient(create_app(settings, model_client=fake_model))


def test_requester_can_create_pending_sandbox_approval(fake_model, tmp_path):
    client = make_sandbox_client(fake_model, tmp_path)
    response = client.post(
        "/v1/sandbox/approvals",
        headers={"Authorization": "Bearer requester-secret"},
        json={"request": {"source": "print('hello')"}},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["approval_id"]


def test_human_approval_requires_separate_credential(fake_model, tmp_path):
    client = make_sandbox_client(fake_model, tmp_path)
    created = client.post(
        "/v1/sandbox/approvals",
        headers={"Authorization": "Bearer requester-secret"},
        json={"request": {"source": "print('hello')"}},
    )
    approval_id = created.json()["approval_id"]

    denied = client.post(f"/v1/sandbox/approvals/{approval_id}/approve")
    assert denied.status_code == 401

    approved = client.post(
        f"/v1/sandbox/approvals/{approval_id}/approve",
        headers={"X-Sandbox-Approval-Token": "Bearer human-approval-secret"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_execution_requires_approval_and_requester_auth(fake_model, tmp_path):
    client = make_sandbox_client(fake_model, tmp_path)
    created = client.post(
        "/v1/sandbox/approvals",
        headers={"Authorization": "Bearer requester-secret"},
        json={"request": {"source": "print('hello')"}},
    )
    approval_id = created.json()["approval_id"]
    payload = {
        "approval_id": approval_id,
        "request": {"source": "print('hello')"},
    }

    unauthenticated = client.post("/v1/sandbox/execute", json=payload)
    assert unauthenticated.status_code == 401

    unapproved = client.post(
        "/v1/sandbox/execute",
        headers={"Authorization": "Bearer requester-secret"},
        json=payload,
    )
    assert unapproved.status_code == 403
    assert "human approval" in unapproved.json()["detail"]


def test_sandbox_rejects_reused_requester_and_approver_token(fake_model, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="same-secret",
        sandbox_enabled=True,
        sandbox_image=IMAGE_REF,
        sandbox_approval_token="same-secret",
        sandbox_execution_principal="local-operator",
    )
    with pytest.raises(ValueError, match="must differ"):
        create_app(settings, model_client=fake_model)


def test_sandbox_api_is_unavailable_when_disabled(fake_model, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
    )
    client = TestClient(create_app(settings, model_client=fake_model))
    response = client.post(
        "/v1/sandbox/approvals",
        json={"request": {"source": "print('hello')"}},
    )
    assert response.status_code == 503
