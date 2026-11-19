"""Tests for persistent memory storage."""

import pytest

from agenticos.memory.store import SQLiteMemoryStore


def test_messages_persist_and_remain_session_scoped(tmp_path) -> None:
    database = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(database)
    store.append_message("session-a", "user", "Build an API")
    store.append_message("session-a", "assistant", "I will plan it")
    store.append_message("session-b", "user", "Different project")

    reopened = SQLiteMemoryStore(database)
    history = reopened.get_recent_messages("session-a")

    assert [message.role for message in history] == ["user", "assistant"]
    assert history[0].content == "Build an API"
    assert len(reopened.get_recent_messages("session-b")) == 1


def test_recent_messages_are_bounded_and_ordered(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    for index in range(5):
        store.append_message("session-a", "user", f"message-{index}")

    history = store.get_recent_messages("session-a", limit=2)
    assert [message.content for message in history] == ["message-3", "message-4"]


def test_invalid_session_and_role_are_rejected(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    with pytest.raises(ValueError, match="session"):
        store.append_message("../other", "user", "hello")
    with pytest.raises(ValueError, match="Role"):
        store.append_message("valid", "system", "hello")


def test_project_context_is_upserted_and_workspace_scoped(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_project_context("alpha", "README.md", "first", {"kind": "doc"})
    store.upsert_project_context("alpha", "README.md", "updated", {"kind": "guide"})
    store.upsert_project_context("beta", "README.md", "other")

    alpha = store.get_project_context("alpha")
    assert len(alpha) == 1
    assert alpha[0]["content"] == "updated"
    assert alpha[0]["metadata"] == {"kind": "guide"}
    assert store.get_project_context("beta")[0]["content"] == "other"
