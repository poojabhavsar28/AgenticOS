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


def test_run_endpoint_returns_agent_outputs_and_status(fake_model, tmp_path) -> None:
    client = TestClient(create_app(Settings(workspace_root=tmp_path), model_client=fake_model))
    response = client.post("/v1/runs", json={"task": "Write a sum function"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["plan"] and body["code"] and body["review"] and body["test_plan"]

    status = client.get(f"/v1/runs/{body['run_id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"


def test_run_endpoint_rejects_workspace_escape(fake_model, tmp_path) -> None:
    client = TestClient(create_app(Settings(workspace_root=tmp_path), model_client=fake_model))
    response = client.post(
        "/v1/runs", json={"task": "Write a sum function", "workspace": "../outside"}
    )
    assert response.status_code == 422


def test_run_status_returns_404_for_unknown_run(fake_model, tmp_path) -> None:
    client = TestClient(create_app(Settings(workspace_root=tmp_path), model_client=fake_model))
    assert client.get("/v1/runs/unknown").status_code == 404
