"""Authentication regression tests for protected API routes."""

import pytest
from fastapi.testclient import TestClient

from agenticos.api.main import create_app
from agenticos.config import Settings
from agenticos.security.auth import BearerTokenAuthenticator


def test_authenticator_rejects_missing_malformed_and_invalid_credentials() -> None:
    authenticator = BearerTokenAuthenticator("correct-secret")
    assert authenticator.authenticate(None) is None
    assert authenticator.authenticate("Basic abc") is None
    assert authenticator.authenticate("Bearer") is None
    assert authenticator.authenticate("Bearer wrong-secret") is None


def test_authenticator_returns_server_derived_principal() -> None:
    principal = BearerTokenAuthenticator("correct-secret").authenticate(
        "Bearer correct-secret"
    )
    assert principal is not None
    assert principal.principal_id == "local-operator"


def make_authenticated_client(fake_model, tmp_path) -> TestClient:
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="test-only-secret",
    )
    return TestClient(create_app(settings, model_client=fake_model))


def test_protected_endpoints_require_bearer_token(fake_model, tmp_path) -> None:
    client = make_authenticated_client(fake_model, tmp_path)
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/sessions/demo/messages").status_code == 401
    assert client.get("/v1/workspaces/demo/files").status_code == 401
    assert client.post(
        "/v1/runs", json={"task": "hello"}
    ).status_code == 401


def test_health_and_readiness_remain_public(fake_model, tmp_path) -> None:
    client = make_authenticated_client(fake_model, tmp_path)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_valid_token_exposes_server_derived_identity(fake_model, tmp_path) -> None:
    client = make_authenticated_client(fake_model, tmp_path)
    response = client.get(
        "/v1/me", headers={"Authorization": "Bearer test-only-secret"}
    )
    assert response.status_code == 200
    assert response.json() == {"principal_id": "local-operator"}


def test_production_requires_authentication_token(fake_model, tmp_path) -> None:
    settings = Settings(
        app_env="production",
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
    )
    with pytest.raises(ValueError, match="API_AUTH_TOKEN"):
        create_app(settings, model_client=fake_model)
