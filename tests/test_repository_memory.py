from pathlib import Path

import pytest

from agenticos.memory.repository import RepositoryIndex


def test_refresh_and_search_are_workspace_scoped(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir()
    (root / "alpha" / "app.py").write_text("def greet(): return 'hello agent'", encoding="utf-8")
    (root / "beta" / "secret.py").write_text("hello private tenant", encoding="utf-8")
    index = RepositoryIndex(root, tmp_path / "index.sqlite3")

    result = index.refresh("alpha")

    assert result["indexed_files"] == 1
    matches = index.search("alpha", "hello agent")
    assert [item["path"] for item in matches] == ["app.py"]
    assert index.search("beta", "private") == []


def test_refresh_replaces_stale_documents(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = root / "demo"
    workspace.mkdir(parents=True)
    source = workspace / "notes.md"
    source.write_text("old keyword", encoding="utf-8")
    index = RepositoryIndex(root, tmp_path / "index.sqlite3")
    index.refresh("demo")

    source.write_text("new phrase", encoding="utf-8")
    index.refresh("demo")

    assert index.search("demo", "old") == []
    assert index.search("demo", "new")[0]["path"] == "notes.md"


def test_refresh_ignores_hidden_binary_and_oversized_files(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = root / "demo"
    (workspace / ".git").mkdir(parents=True)
    (workspace / "node_modules").mkdir()
    workspace.mkdir(exist_ok=True)
    (workspace / ".secret").write_text("hidden needle", encoding="utf-8")
    (workspace / ".git" / "config").write_text("git needle", encoding="utf-8")
    (workspace / "node_modules" / "dep.js").write_text("dependency needle", encoding="utf-8")
    (workspace / "image.bin").write_bytes(b"\x00needle")
    (workspace / "large.txt").write_text("needle" * 20, encoding="utf-8")
    (workspace / "keep.txt").write_text("visible needle", encoding="utf-8")
    index = RepositoryIndex(root, tmp_path / "index.sqlite3", max_file_bytes=32)

    result = index.refresh("demo")

    assert result["indexed_files"] == 1
    assert [item["path"] for item in index.search("demo", "needle")] == ["keep.txt"]


def test_search_validates_query_and_limits(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    (root / "demo").mkdir(parents=True)
    index = RepositoryIndex(root, tmp_path / "index.sqlite3")

    with pytest.raises(ValueError):
        index.search("demo", "   ")
    with pytest.raises(ValueError):
        index.search("demo", "needle", limit=0)
    with pytest.raises(ValueError):
        index.search("../outside", "needle")


def test_refresh_rejects_too_many_files(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = root / "demo"
    workspace.mkdir(parents=True)
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "b.txt").write_text("b", encoding="utf-8")
    index = RepositoryIndex(root, tmp_path / "index.sqlite3", max_files=1)

    with pytest.raises(ValueError, match="file limit"):
        index.refresh("demo")



def test_refresh_enforces_total_repository_byte_budget(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = root / "demo"
    workspace.mkdir(parents=True)
    (workspace / "a.txt").write_text("123456", encoding="utf-8")
    (workspace / "b.txt").write_text("abcdef", encoding="utf-8")
    index = RepositoryIndex(
        root, tmp_path / "index.sqlite3", max_file_bytes=10, max_total_bytes=10
    )

    with pytest.raises(ValueError, match="byte limit"):
        index.refresh("demo")
