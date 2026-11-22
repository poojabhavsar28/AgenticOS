"""HTTP API tests using an in-memory fake model."""

import asyncio
import time

from fastapi.testclient import TestClient

from agenticos.api.main import create_app
from agenticos.config import Settings
from agenticos.runtime.checkpoints import SQLiteCheckpointStore
from agenticos.security.audit import SQLiteAuditLog


def make_client(fake_model, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
    )
    return TestClient(create_app(settings, model_client=fake_model))


def test_health_endpoint(fake_model, tmp_path) -> None:
    response = make_client(fake_model, tmp_path).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_endpoint(fake_model, tmp_path) -> None:
    response = make_client(fake_model, tmp_path).get("/ready")
    assert response.status_code == 200


def test_run_endpoint_returns_agent_outputs_and_status(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    response = client.post(
        "/v1/runs",
        json={"task": "Write a sum function", "session_id": "session-a"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["plan"] and body["code"] and body["review"] and body["test_plan"]

    status = client.get(f"/v1/runs/{body['run_id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    checkpoint = SQLiteCheckpointStore(tmp_path / "operations.sqlite3")
    snapshot = asyncio.run(checkpoint.load(body["run_id"]))
    assert snapshot is not None and snapshot["status"] == "completed"
    events = SQLiteAuditLog(tmp_path / "operations.sqlite3").events()
    assert any(event.resource == "/v1/runs" for event in events)

    history = client.get("/v1/sessions/session-a/messages")
    assert history.status_code == 200
    assert [item["role"] for item in history.json()] == ["user", "assistant"]


def test_run_endpoint_rejects_workspace_escape(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    response = client.post(
        "/v1/runs", json={"task": "Write a sum function", "workspace": "../outside"}
    )
    assert response.status_code == 422


def test_run_status_returns_404_for_unknown_run(fake_model, tmp_path) -> None:
    assert make_client(fake_model, tmp_path).get("/v1/runs/unknown").status_code == 404


def test_project_context_is_saved_and_used_in_session_scope(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    saved = client.put(
        "/v1/workspaces/default/context",
        json={
            "source_key": "architecture",
            "content": "Prefer async FastAPI routes",
            "metadata": {"type": "decision"},
        },
    )
    assert saved.status_code == 200

    run = client.post(
        "/v1/runs",
        json={"task": "Add a route", "session_id": "project-session"},
    )
    assert run.status_code == 200
    history = client.get("/v1/sessions/project-session/messages").json()
    assert len(history) == 2
    assert history[0]["content"] == "Add a route"


def test_invalid_session_identifier_is_rejected(fake_model, tmp_path) -> None:
    response = make_client(fake_model, tmp_path).post(
        "/v1/runs", json={"task": "hello", "session_id": "../other"}
    )
    assert response.status_code == 422



def test_repository_index_refresh_and_search_endpoints(fake_model, tmp_path) -> None:
    workspace = tmp_path / "default"
    workspace.mkdir()
    (workspace / "service.py").write_text(
        "def calculate_total(items): return sum(items)", encoding="utf-8"
    )
    client = make_client(fake_model, tmp_path)

    refreshed = client.post("/v1/workspaces/default/repository-index")
    assert refreshed.status_code == 200
    assert refreshed.json()["indexed_files"] == 1

    searched = client.get(
        "/v1/workspaces/default/repository-search",
        params={"q": "calculate total"},
    )
    assert searched.status_code == 200
    assert searched.json()[0]["path"] == "service.py"


def test_repository_index_endpoints_reject_workspace_escape(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    assert client.post("/v1/workspaces/../outside/repository-index").status_code in {404, 422}
    assert client.get(
        "/v1/workspaces/../outside/repository-search", params={"q": "needle"}
    ).status_code in {404, 422}



def test_run_event_history_and_sse_stream(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    created = client.post(
        "/v1/runs", json={"task": "Create a safe parser", "session_id": "events-session"}
    )
    run_id = created.json()["run_id"]

    response = client.get(f"/v1/runs/{run_id}/events")
    assert response.status_code == 200
    event_types = [event["event_type"] for event in response.json()]
    assert event_types[:2] == ["queued", "started"]
    assert event_types[-1] == "completed"
    stage_events = event_types[2:-1]
    assert stage_events == [
        "stage_started",
        "stage_completed",
        "stage_started",
        "stage_completed",
        "stage_started",
        "stage_completed",
        "stage_started",
        "stage_completed",
    ]

    resumed = client.get(
        f"/v1/runs/{run_id}/events",
        params={"after_event_id": response.json()[0]["event_id"]},
    )
    assert [event["event_type"] for event in resumed.json()] == event_types[1:]

    stream = client.get(f"/v1/runs/{run_id}/events/stream")
    resumed_stream = client.get(
        f"/v1/runs/{run_id}/events/stream",
        headers={"Last-Event-ID": str(response.json()[0]["event_id"])},
    )
    assert "event: queued" not in resumed_stream.text
    assert "event: started" in resumed_stream.text
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: queued" in stream.text
    assert "event: completed" in stream.text
    assert "id: " in stream.text


def test_run_event_endpoints_validate_unknown_runs_and_resume_ids(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    assert client.get("/v1/runs/missing/events").status_code == 404
    assert client.get(
        "/v1/runs/missing/events/stream", headers={"Last-Event-ID": "invalid"}
    ).status_code == 404


def test_async_run_can_be_cancelled_through_api(tmp_path) -> None:
    class SlowModel:
        async def generate(self, prompt: str, *, system: str | None = None) -> str:
            await asyncio.sleep(0.2)
            return "safe test output"

        async def health(self) -> bool:
            return True

    with make_client(SlowModel(), tmp_path) as client:
        started = client.post("/v1/runs/start", json={"task": "long running task"})
        assert started.status_code == 202
        run_id = started.json()["run_id"]

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = client.get(f"/v1/runs/{run_id}").json()["status"]
            if status == "running":
                break
            time.sleep(0.005)
        assert status == "running"

        cancelled = client.post(f"/v1/runs/{run_id}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "cancellation_requested"

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshot = client.get(f"/v1/runs/{run_id}").json()
            if snapshot["status"] == "cancelled":
                break
            time.sleep(0.005)
        assert snapshot["status"] == "cancelled"
        events = client.get(f"/v1/runs/{run_id}/events").json()
        assert events[-1]["event_type"] == "cancelled"


def test_session_messages_are_principal_scoped(fake_model, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="operator-secret",
        identity_admin_token="admin-secret",
    )
    with TestClient(create_app(settings, model_client=fake_model)) as client:
        store = client.app.state.identity_store
        memory = client.app.state.memory
        store.create_principal("alice")
        _, alice_token = store.issue_token("alice")
        alice = {"Authorization": f"Bearer {alice_token}"}
        store.create_principal("bob")
        _, bob_token = store.issue_token("bob")
        bob = {"Authorization": f"Bearer {bob_token}"}

        denied = client.get("/v1/sessions/session-a/messages", headers=alice)
        assert denied.status_code == 404
        memory.claim_session("session-a", "alice", "workspace-a")
        memory.append_message("session-a", "user", "alice private")
        assert client.get("/v1/sessions/session-a/messages", headers=alice).status_code == 200
        assert client.get("/v1/sessions/session-a/messages", headers=bob).status_code == 404


def test_authenticated_run_access_is_workspace_grant_and_owner_scoped(fake_model, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="operator-secret",
        identity_admin_token="admin-secret",
    )
    with TestClient(create_app(settings, model_client=fake_model)) as client:
        store = client.app.state.identity_store
        store.create_principal("alice")
        _, alice_token = store.issue_token("alice")
        alice = {"Authorization": f"Bearer {alice_token}"}
        denied = client.post(
            "/v1/runs",
            json={"task": "private", "workspace": "workspace-a"},
            headers=alice,
        )
        assert denied.status_code == 403

        store.grant("alice", "workspace-a", "execute", "workflow:run")
        created = client.post(
            "/v1/runs", json={"task": "private", "workspace": "workspace-a"}, headers=alice
        )
        assert created.status_code == 200
        run_id = created.json()["run_id"]
        assert client.get(f"/v1/runs/{run_id}", headers=alice).status_code == 200

        store.create_principal("bob")
        _, bob_token = store.issue_token("bob")
        bob = {"Authorization": f"Bearer {bob_token}"}
        assert client.get(f"/v1/runs/{run_id}", headers=bob).status_code == 404
        assert client.get(f"/v1/runs/{run_id}/events", headers=bob).status_code == 404

        admin = {"Authorization": "Bearer admin-secret"}
        assert client.get(f"/v1/runs/{run_id}", headers=admin).status_code == 200


def test_cancel_endpoint_rejects_unknown_and_terminal_runs(fake_model, tmp_path) -> None:
    client = make_client(fake_model, tmp_path)
    assert client.post("/v1/runs/missing/cancel").status_code == 404

    started = client.post("/v1/runs/start", json={"task": "quick task"})
    run_id = started.json()["run_id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = client.get(f"/v1/runs/{run_id}").json()
        if snapshot["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.005)
    assert client.post(f"/v1/runs/{run_id}/cancel").status_code == 409


def test_agent_tool_api_uses_authenticated_identity_and_human_approval(
    fake_model, tmp_path
) -> None:
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="requester-secret",
        sandbox_enabled=True,
        sandbox_image="python:3.12-slim@sha256:" + "a" * 64,
        sandbox_approval_token="human-secret",
        sandbox_approver_id="reviewer-1",
        sandbox_execution_principal="local-operator",
    )
    with TestClient(create_app(settings, model_client=fake_model)) as client:
        denied = client.post(
            "/v1/tools/request_code_execution/execute",
            json={"request": {"source": "print('hello')"}},
        )
        assert denied.status_code == 401

        requested = client.post(
            "/v1/tools/request_code_execution/execute",
            headers={"Authorization": "Bearer requester-secret"},
            json={
                "request": {"source": "print('hello')"},
                "principal_id": "attacker-controlled",
            },
        )
        assert requested.status_code == 200
        body = requested.json()
        assert body["status"] == "pending_human_review"

        reviews = client.get(
            "/v1/sandbox/reviews",
            headers={"X-Sandbox-Approval-Token": "Bearer human-secret"},
        )
        assert reviews.status_code == 200
        assert len(reviews.json()) == 1
        assert reviews.json()[0]["requester_id"] == "local-operator"

        review = client.get(
            f"/v1/sandbox/reviews/{body['review_id']}",
            headers={"X-Sandbox-Approval-Token": "Bearer human-secret"},
        )
        assert review.status_code == 200
        assert review.json()["request"]["source"] == "print('hello')"

        approved = client.post(
            f"/v1/sandbox/approvals/{body['review_id']}/approve",
            headers={"X-Sandbox-Approval-Token": "Bearer human-secret"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"


def test_agent_tool_api_rejects_unknown_tool(fake_model, tmp_path) -> None:
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="requester-secret",
        sandbox_enabled=True,
        sandbox_image="python:3.12-slim@sha256:" + "b" * 64,
        sandbox_approval_token="human-secret",
        sandbox_approver_id="reviewer-1",
        sandbox_execution_principal="local-operator",
    )
    client = TestClient(create_app(settings, model_client=fake_model))
    response = client.post(
        "/v1/tools/not-registered/execute",
        headers={"Authorization": "Bearer requester-secret"},
        json={},
    )
    assert response.status_code == 404
