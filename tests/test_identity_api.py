"""HTTP authentication integration tests for persistent identities."""

from fastapi.testclient import TestClient

from agenticos.api.main import create_app
from agenticos.config import Settings


def _settings(tmp_path):
    return Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="configured-operator-secret",
        sandbox_execution_principal="operator",
    )


def test_api_authentication_uses_persistent_identity_store(fake_model, tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings, model_client=fake_model)) as client:
        assert client.get("/v1/sessions/missing/messages").status_code == 401
        response = client.get(
            "/v1/sessions/missing/messages",
            headers={"Authorization": "Bearer configured-operator-secret"},
        )
        assert response.status_code == 404
        principal = client.app.state.identity_store.authenticate(
            "configured-operator-secret"
        )
        assert principal is not None
        assert principal.principal_id == "operator"


def test_api_accepts_multiple_persistent_tokens_and_revocation(
    fake_model, tmp_path
) -> None:
    with TestClient(create_app(_settings(tmp_path), model_client=fake_model)) as client:
        store = client.app.state.identity_store
        token_id, token = store.issue_token("operator")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/v1/sessions/missing/messages", headers=headers).status_code == 404

        store.revoke_token(token_id)
        assert client.get("/v1/sessions/missing/messages", headers=headers).status_code == 401


def test_configured_identity_survives_application_restart(fake_model, tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings, model_client=fake_model)) as first:
        assert first.get(
            "/v1/sessions/missing/messages",
            headers={"Authorization": "Bearer configured-operator-secret"},
        ).status_code == 404

    with TestClient(create_app(settings, model_client=fake_model)) as second:
        assert second.get(
            "/v1/sessions/missing/messages",
            headers={"Authorization": "Bearer configured-operator-secret"},
        ).status_code == 404
