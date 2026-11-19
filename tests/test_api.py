"""HTTP API tests using an in-memory fake model."""

from fastapi.testclient import TestClient

from agenticos.api.main import create_app
from agenticos.config import Settings


def test_health_endpoint(fake_model, tmp_path) -> None:
    app = create_app(Settings(workspace_root=tmp_path), model_client=fake_model)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_endpoint(fake_model, tmp_path) -> None:
    app = create_app(Settings(workspace_root=tmp_path), model_client=fake_model)
    response = TestClient(app).get("/ready")
    assert response.status_code == 200


def test_run_endpoint_returns_agent_outputs(fake_model, tmp_path) -> None:
    app = create_app(Settings(workspace_root=tmp_path), model_client=fake_model)
    response = TestClient(app).post("/v1/runs", json={"task": "Write a sum function"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["plan"] and body["code"] and body["review"] and body["test_plan"]


def test_run_endpoint_rejects_workspace_escape(fake_model, tmp_path) -> None:
    app = create_app(Settings(workspace_root=tmp_path), model_client=fake_model)
    response = TestClient(app).post(
        "/v1/runs", json={"task": "Write a sum function", "workspace": "../outside"}
    )
    assert response.status_code == 422
