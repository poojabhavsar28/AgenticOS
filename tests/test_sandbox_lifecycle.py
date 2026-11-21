"""End-to-end API lifecycle tests for human-gated agent sandbox execution."""

from fastapi.testclient import TestClient

import agenticos.api.main as api_main
from agenticos.config import Settings
from agenticos.security.sandbox import SandboxExecutionResult


class StubDockerSandboxBackend:
    """Deterministic backend: records dispatch without executing source code."""

    calls = 0

    def __init__(self, policy) -> None:
        self.policy = policy

    async def execute(self, request):
        type(self).calls += 1
        return SandboxExecutionResult(
            exit_code=0,
            stdout="stubbed sandbox output",
            stderr="",
            timed_out=False,
        )


def test_agent_to_human_approval_to_sandbox_execution_lifecycle(
    fake_model, tmp_path, monkeypatch
) -> None:
    StubDockerSandboxBackend.calls = 0
    monkeypatch.setattr(api_main, "DockerSandboxBackend", StubDockerSandboxBackend)
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="requester-secret",
        sandbox_enabled=True,
        sandbox_image="python:3.12-slim@sha256:" + "c" * 64,
        sandbox_approval_token="human-secret",
        sandbox_approver_id="reviewer-1",
        sandbox_execution_principal="local-operator",
    )
    source = "print('lifecycle verified')"
    request = {"source": source}

    with TestClient(api_main.create_app(settings, model_client=fake_model)) as client:
        requester_headers = {"Authorization": "Bearer requester-secret"}
        reviewer_headers = {
            "X-Sandbox-Approval-Token": "Bearer human-secret"
        }

        # The agent tool can submit code, but this only creates a pending review.
        submitted = client.post(
            "/v1/tools/request_code_execution/execute",
            headers=requester_headers,
            json={"request": request},
        )
        assert submitted.status_code == 200
        approval_id = submitted.json()["approval_id"]
        assert submitted.json()["status"] == "pending_human_review"
        assert StubDockerSandboxBackend.calls == 0

        # Only the separately authenticated reviewer can inspect the submitted source.
        queue = client.get("/v1/sandbox/reviews", headers=reviewer_headers)
        assert queue.status_code == 200
        assert [item["approval_id"] for item in queue.json()] == [approval_id]
        review = client.get(
            f"/v1/sandbox/reviews/{approval_id}", headers=reviewer_headers
        )
        assert review.status_code == 200
        assert review.json()["request"]["source"] == source
        assert review.json()["status"] == "pending"

        # The human approval is a distinct action from requesting execution.
        approved = client.post(
            f"/v1/sandbox/approvals/{approval_id}/approve",
            headers=reviewer_headers,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        # A modified request cannot reuse the approval; rejection does not consume it.
        tampered = client.post(
            "/v1/tools/execute_approved_code/execute",
            headers=requester_headers,
            json={
                "approval_id": approval_id,
                "request": {"source": "print('tampered source')"},
            },
        )
        assert tampered.status_code == 403
        assert StubDockerSandboxBackend.calls == 0

        # The agent must explicitly dispatch the exact approved request.
        executed = client.post(
            "/v1/tools/execute_approved_code/execute",
            headers=requester_headers,
            json={"approval_id": approval_id, "request": request},
        )
        assert executed.status_code == 200
        assert executed.json()["stdout"] == "stubbed sandbox output"
        assert StubDockerSandboxBackend.calls == 1

        # Approval is one-time: replaying the same tool call is denied.
        replay = client.post(
            "/v1/tools/execute_approved_code/execute",
            headers=requester_headers,
            json={"approval_id": approval_id, "request": request},
        )
        assert replay.status_code == 403
        assert StubDockerSandboxBackend.calls == 1
