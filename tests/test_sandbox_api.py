"""HTTP tests for authenticated sandbox approval and execution routes."""

# ruff: noqa: I001

import pytest
from fastapi.testclient import TestClient

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
    assert response.json()["review_id"]
    assert response.json()["approval_token"]


def test_human_approval_requires_separate_credential(fake_model, tmp_path):
    client = make_sandbox_client(fake_model, tmp_path)
    created = client.post(
        "/v1/sandbox/approvals",
        headers={"Authorization": "Bearer requester-secret"},
        json={"request": {"source": "print('hello')"}},
    )
    review_id = created.json()["review_id"]

    denied = client.post(f"/v1/sandbox/approvals/{review_id}/approve")
    assert denied.status_code == 401

    approved = client.post(
        f"/v1/sandbox/approvals/{review_id}/approve",
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
    approval = created.json()
    payload = {
        "approval_token": approval["approval_token"],
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


def test_human_reviewer_can_inspect_exact_code_before_approval(fake_model, tmp_path):
    client = make_sandbox_client(fake_model, tmp_path)
    created = client.post(
        "/v1/sandbox/approvals",
        headers={"Authorization": "Bearer requester-secret"},
        json={"request": {"source": "print('review me')"}},
    )
    review_id = created.json()["review_id"]
    reviewer_headers = {"X-Sandbox-Approval-Token": "Bearer human-approval-secret"}

    unauthorized = client.get("/v1/sandbox/reviews")
    assert unauthorized.status_code == 401

    queue = client.get("/v1/sandbox/reviews", headers=reviewer_headers)
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    assert "request" not in queue.json()[0]

    review = client.get(
        f"/v1/sandbox/reviews/{review_id}", headers=reviewer_headers
    )
    assert review.status_code == 200
    assert review.json()["request"]["source"] == "print('review me')"
    assert review.json()["request_hash"]
    assert review.json()["request"]["limits"]["timeout_seconds"] == 5.0


def test_sandbox_review_page_is_served_only_when_enabled(fake_model, tmp_path):
    enabled = make_sandbox_client(fake_model, tmp_path)
    page = enabled.get("/sandbox/review")
    assert page.status_code == 200
    assert "Sandbox execution review" in page.text
    assert "I inspected the full source code" in page.text

    disabled_settings = Settings(
        workspace_root=tmp_path / "disabled",
        memory_database_path=tmp_path / "disabled-memory.sqlite3",
        operations_database_path=tmp_path / "disabled-operations.sqlite3",
    )
    disabled = TestClient(create_app(disabled_settings, model_client=fake_model))
    assert disabled.get("/sandbox/review").status_code == 404



def test_approval_api_returns_429_when_requester_queue_is_full(
    fake_model, tmp_path
):
    client = make_sandbox_client(fake_model, tmp_path)
    client.app.state.sandbox_approvals.store.MAX_PENDING_PER_REQUESTER = 1
    headers = {"Authorization": "Bearer requester-secret"}
    payload = {"request": {"source": "print('hello')"}}

    first = client.post("/v1/sandbox/approvals", headers=headers, json=payload)
    assert first.status_code == 201

    second = client.post("/v1/sandbox/approvals", headers=headers, json=payload)
    assert second.status_code == 429
    assert second.json()["detail"] == "Pending sandbox approval capacity reached"


def test_requester_credential_cannot_access_human_reviewer_routes(
    fake_model, tmp_path
):
    client = make_sandbox_client(fake_model, tmp_path)
    requester_headers = {"X-Sandbox-Approval-Token": "Bearer requester-secret"}

    queue = client.get("/v1/sandbox/reviews", headers=requester_headers)
    assert queue.status_code == 401

    created = client.post(
        "/v1/sandbox/approvals",
        headers={"Authorization": "Bearer requester-secret"},
        json={"request": {"source": "print('review me')"}},
    )
    assert created.status_code == 201
    review_id = created.json()["review_id"]

    inspect = client.get(
        f"/v1/sandbox/reviews/{review_id}", headers=requester_headers
    )
    assert inspect.status_code == 401

    approve = client.post(
        f"/v1/sandbox/approvals/{review_id}/approve",
        headers=requester_headers,
    )
    assert approve.status_code == 401
