"""HTTP API tests using an in-memory fake model."""

import asyncio

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
