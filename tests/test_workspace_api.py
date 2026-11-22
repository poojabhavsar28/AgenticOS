"""HTTP tests for explicit workspace file operations."""

from pathlib import Path

from fastapi.testclient import TestClient

from agenticos.api.main import create_app
from agenticos.config import Settings


def make_workspace_client(fake_model, tmp_path: Path) -> TestClient:
    settings = Settings(
        workspace_root=tmp_path,
        memory_database_path=tmp_path / "memory.sqlite3",
    )
    return TestClient(create_app(settings, model_client=fake_model))


def test_workspace_api_lists_and_reads_files(fake_model, tmp_path: Path) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello", encoding="utf-8")
    client = make_workspace_client(fake_model, tmp_path)

    listing = client.get("/v1/workspaces/demo/files")
    assert listing.status_code == 200
    assert listing.json() == ["README.md"]

    read = client.get("/v1/workspaces/demo/files/README.md")
    assert read.status_code == 200
    assert read.json()["content"] == "hello"


def test_workspace_api_requires_approval_before_writing(fake_model, tmp_path: Path) -> None:
    client = make_workspace_client(fake_model, tmp_path)
    target = tmp_path / "demo" / "src" / "main.py"

    staged = client.post(
        "/v1/workspaces/demo/changes",
        json={"relative_path": "src/main.py", "content": "print('approved')"},
    )
    assert staged.status_code == 202
    change_id = staged.json()["change_id"]
    assert not target.exists()

    pending = client.get("/v1/workspaces/demo/changes")
    assert pending.status_code == 200
    assert pending.json()[0]["change_id"] == change_id

    approved = client.post(f"/v1/workspaces/demo/changes/{change_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert target.read_text(encoding="utf-8") == "print('approved')"


def test_workspace_api_can_reject_a_staged_change(fake_model, tmp_path: Path) -> None:
    client = make_workspace_client(fake_model, tmp_path)
    staged = client.post(
        "/v1/workspaces/demo/changes",
        json={"relative_path": "discard.py", "content": "unsafe = True"},
    )
    change_id = staged.json()["change_id"]

    rejected = client.delete(f"/v1/workspaces/demo/changes/{change_id}")
    assert rejected.status_code == 200
    assert not (tmp_path / "demo" / "discard.py").exists()


def test_workspace_api_rejects_path_escape_and_unknown_approval(
    fake_model, tmp_path: Path
) -> None:
    client = make_workspace_client(fake_model, tmp_path)
    staged = client.post(
        "/v1/workspaces/demo/changes",
        json={"relative_path": "../outside.py", "content": "bad"},
    )
    assert staged.status_code == 422

    missing = client.post(
        "/v1/workspaces/demo/changes/not-a-change/approve"
    )
    assert missing.status_code == 404


def test_workspace_api_cannot_read_sibling_workspace_through_encoded_traversal(
    fake_model, tmp_path: Path
) -> None:
    first = tmp_path / "project-a"
    second = tmp_path / "project-b"
    first.mkdir()
    second.mkdir()
    secret = second / "secret.txt"
    secret.write_text("private workspace data", encoding="utf-8")
    client = make_workspace_client(fake_model, tmp_path)

    response = client.get(
        "/v1/workspaces/project-a/files/%2E%2E%2Fproject-b%2Fsecret.txt"
    )

    assert response.status_code == 422
    assert "outside the selected workspace" in response.json()["detail"]
    assert secret.read_text(encoding="utf-8") == "private workspace data"
