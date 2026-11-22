"""HTTP authentication integration tests for persistent identities."""

import pytest
from fastapi.testclient import TestClient

from agenticos.api.main import create_app
from agenticos.config import Settings
from agenticos.runtime.tools import ToolRegistry


def _settings(tmp_path):
    return Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
        operations_database_path=tmp_path / "operations.sqlite3",
        api_auth_token="configured-operator-secret",
        sandbox_execution_principal="operator",
        identity_admin_token="configured-admin-secret",
    )


def test_api_authentication_uses_persistent_identity_store(fake_model, tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings, model_client=fake_model)) as client:
        assert client.get("/v1/sessions/missing/messages").status_code == 401
        response = client.get(
            "/v1/sessions/missing/messages",
            headers={"Authorization": "Bearer configured-operator-secret"},
        )
        assert response.status_code == 200
        assert response.json() == []
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
        response = client.get("/v1/sessions/missing/messages", headers=headers)
        assert response.status_code == 200
        assert response.json() == []

        store.revoke_token(token_id)
        assert client.get("/v1/sessions/missing/messages", headers=headers).status_code == 401


def test_configured_identity_survives_application_restart(fake_model, tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings, model_client=fake_model)) as first:
        response = first.get(
            "/v1/sessions/missing/messages",
            headers={"Authorization": "Bearer configured-operator-secret"},
        )
        assert response.status_code == 200
        assert response.json() == []

    with TestClient(create_app(settings, model_client=fake_model)) as second:
        response = second.get(
            "/v1/sessions/missing/messages",
            headers={"Authorization": "Bearer configured-operator-secret"},
        )
        assert response.status_code == 200
        assert response.json() == []



def test_identity_admin_can_manage_principals_tokens_and_workspace_grants(
    fake_model, tmp_path
) -> None:
    with TestClient(create_app(_settings(tmp_path), model_client=fake_model)) as client:
        admin = {"Authorization": "Bearer configured-admin-secret"}
        ordinary = {"Authorization": "Bearer configured-operator-secret"}

        # Ordinary authenticated users cannot provision identities or grant access.
        assert client.post(
            "/v1/admin/principals", json={"principal_id": "alice"}, headers=ordinary
        ).status_code == 403
        denied_events = [
            event
            for event in client.app.state.audit_log.events()
            if event.action == "identity.admin_access_denied"
        ]
        assert denied_events
        assert denied_events[-1].principal_id == "operator"
        assert denied_events[-1].outcome == "denied"

        created = client.post(
            "/v1/admin/principals", json={"principal_id": "alice"}, headers=admin
        )
        assert created.status_code == 201
        assert created.json() == {"principal_id": "alice", "status": "created"}

        issued = client.post("/v1/admin/principals/alice/tokens", headers=admin)
        assert issued.status_code == 201
        token_data = issued.json()
        assert token_data["token"].startswith("agx_")
        authenticated = client.app.state.identity_store.authenticate(token_data["token"])
        assert authenticated is not None
        assert authenticated.principal_id == "alice"

        grant_path = "/v1/admin/principals/alice/workspaces/project-a/grants"
        grant = client.put(
            grant_path,
            json={"action": "execute", "resource": "echo"},
            headers=admin,
        )
        assert grant.status_code == 200
        store = client.app.state.identity_store
        assert store.is_allowed("alice", "project-a", "execute", "echo")
        assert not store.is_allowed("alice", "project-b", "execute", "echo")

        # A normal principal cannot manage its own privileges.
        assert client.put(
            grant_path,
            json={"action": "execute", "resource": "admin"},
            headers={"Authorization": f"Bearer {token_data['token']}"},
        ).status_code == 403

        revoked = client.request(
            "DELETE",
            grant_path,
            json={"action": "execute", "resource": "echo"},
            headers=admin,
        )
        assert revoked.status_code == 200
        assert not store.is_allowed("alice", "project-a", "execute", "echo")

        disabled = client.patch(
            "/v1/admin/principals/alice",
            json={"enabled": False},
            headers=admin,
        )
        assert disabled.status_code == 200
        assert store.authenticate(token_data["token"]) is None

        # Token revocation is separately supported for active credentials.
        client.patch(
            "/v1/admin/principals/alice",
            json={"enabled": True},
            headers=admin,
        )
        admin_disable = client.patch(
            "/v1/admin/principals/local-admin",
            json={"enabled": False},
            headers=admin,
        )
        assert admin_disable.status_code == 409
        connection = store._connect()
        try:
            admin_token_id = connection.execute(
                "SELECT token_id FROM identity_tokens WHERE principal_id = ?",
                ("local-admin",),
            ).fetchone()["token_id"]
        finally:
            connection.close()
        admin_revoke = client.delete(
            f"/v1/admin/tokens/{admin_token_id}", headers=admin
        )
        assert admin_revoke.status_code == 409
        admin_rotate = client.post(
            f"/v1/admin/tokens/{admin_token_id}/rotate", headers=admin
        )
        assert admin_rotate.status_code == 409
        assert store.authenticate(token_data["token"]) is not None
        rotated = client.post(
            f"/v1/admin/tokens/{token_data['token_id']}/rotate", headers=admin
        )
        assert rotated.status_code == 200
        rotated_data = rotated.json()
        assert rotated_data["status"] == "rotated"
        assert store.authenticate(token_data["token"]) is None
        assert store.authenticate(rotated_data["token"]).principal_id == "alice"

        revoked_token = client.delete(
            f"/v1/admin/tokens/{rotated_data['token_id']}", headers=admin
        )
        assert revoked_token.status_code == 200
        assert store.authenticate(rotated_data["token"]) is None


def test_identity_admin_routes_fail_closed_without_bootstrap_admin(fake_model, tmp_path):
    settings = _settings(tmp_path)
    settings.identity_admin_token = None
    with TestClient(create_app(settings, model_client=fake_model)) as client:
        response = client.post(
            "/v1/admin/principals",
            json={"principal_id": "attacker"},
            headers={"Authorization": "Bearer configured-operator-secret"},
        )
        assert response.status_code == 403



def test_admin_and_operator_principals_must_be_distinct(fake_model, tmp_path):
    settings = _settings(tmp_path)
    settings.identity_admin_principal = "operator"
    with pytest.raises(ValueError, match="must differ"):
        create_app(settings, model_client=fake_model)



def test_identity_admin_actions_are_written_to_tamper_evident_audit_log(
    fake_model, tmp_path
):
    with TestClient(create_app(_settings(tmp_path), model_client=fake_model)) as client:
        admin = {"Authorization": "Bearer configured-admin-secret"}
        created = client.post(
            "/v1/admin/principals",
            json={"principal_id": "audit-user"},
            headers=admin,
        )
        assert created.status_code == 201

        issued = client.post(
            "/v1/admin/principals/audit-user/tokens", headers=admin
        )
        assert issued.status_code == 201
        issued_token = issued.json()["token"]

        grant = client.put(
            "/v1/admin/principals/audit-user/workspaces/workspace-1/grants",
            json={"action": "execute", "resource": "run"},
            headers=admin,
        )
        assert grant.status_code == 200

        events = client.app.state.audit_log.events()
        semantic_events = [event for event in events if event.action.startswith("identity.")]
        actions = {event.action for event in semantic_events}
        assert {
            "identity.create_principal",
            "identity.issue_token",
            "identity.grant_workspace",
        }.issubset(actions)
        assert all(issued_token not in event.resource for event in semantic_events)
        assert client.app.state.audit_log.verify_integrity()



def test_failed_identity_admin_operation_is_recorded_with_http_status(
    fake_model, tmp_path
):
    with TestClient(create_app(_settings(tmp_path), model_client=fake_model)) as client:
        admin = {"Authorization": "Bearer configured-admin-secret"}
        response = client.delete(
            "/v1/admin/tokens/nonexistent-token", headers=admin
        )
        assert response.status_code == 404

        events = client.app.state.audit_log.events()
        failed_request = [
            event
            for event in events
            if event.resource == "/v1/admin/tokens/nonexistent-token"
            and event.action == "DELETE"
        ]
        assert failed_request
        assert failed_request[-1].principal_id == "local-admin"
        assert failed_request[-1].outcome == "404"
        assert client.app.state.audit_log.verify_integrity()



class _EchoTool:
    name = "echo"

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        return {"echo": arguments}


def test_concurrent_token_rotation_has_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agenticos.security.identity import SQLiteIdentityStore
    from agenticos.security.policy import PermissionDenied

    store = SQLiteIdentityStore(tmp_path / "identities.sqlite3")
    store.create_principal("rotation-user")
    token_id, original_token = store.issue_token("rotation-user")

    def rotate():
        try:
            return store.rotate_token(token_id)
        except PermissionDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: rotate(), range(2)))

    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    assert store.authenticate(original_token) is None
    assert store.authenticate(successful[0][1]).principal_id == "rotation-user"


def test_identity_store_rejects_noncanonical_security_identifiers(tmp_path):
    from agenticos.security.identity import SQLiteIdentityStore

    store = SQLiteIdentityStore(tmp_path / "identities.sqlite3")
    for value in (" alice", "alice ", "workspace\n-a", "tool\tname"):
        with pytest.raises(ValueError, match="canonical"):
            store.create_principal(value)
        with pytest.raises(ValueError, match="canonical"):
            store.is_allowed("alice", value, "execute", "echo")


def test_workspace_tool_api_enforces_exact_principal_and_workspace_grants(
    fake_model, tmp_path
):
    with TestClient(create_app(_settings(tmp_path), model_client=fake_model)) as client:
        store = client.app.state.identity_store
        store.create_principal("alice")
        _, alice_token = store.issue_token("alice")
        headers = {"Authorization": f"Bearer {alice_token}"}

        registry = ToolRegistry(identity_store=store)
        registry.register(_EchoTool())
        client.app.state.workflow.tool_registry = registry

        store.grant("alice", "workspace-a", "execute", "echo")
        store.create_principal("bob")
        _, bob_token = store.issue_token("bob")
        bob_headers = {"Authorization": f"Bearer {bob_token}"}

        bob_denied = client.post(
            "/v1/workspaces/workspace-a/tools/echo/execute",
            json={"message": "another principal must not execute"},
            headers=bob_headers,
        )
        assert bob_denied.status_code == 403

        allowed = client.post(
            "/v1/workspaces/workspace-a/tools/echo/execute",
            json={"message": "hello"},
            headers=headers,
        )
        assert allowed.status_code == 200
        assert allowed.json() == {"echo": {"message": "hello"}}

        denied_other_workspace = client.post(
            "/v1/workspaces/workspace-b/tools/echo/execute",
            json={"message": "must not execute"},
            headers=headers,
        )
        assert denied_other_workspace.status_code == 403

        denied_other_tool = client.post(
            "/v1/workspaces/workspace-a/tools/unknown/execute",
            json={},
            headers=headers,
        )
        assert denied_other_tool.status_code == 404

        assert store.is_allowed("alice", "workspace-a", "execute", "echo")
        assert not store.is_allowed("alice", "workspace-b", "execute", "echo")
