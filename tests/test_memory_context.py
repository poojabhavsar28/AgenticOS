"""Tests for prompt context assembly."""

import pytest

from agenticos.memory.context import build_memory_context
from agenticos.memory.store import MemoryMessage


def test_context_contains_project_and_conversation_memory() -> None:
    context = build_memory_context(
        [MemoryMessage("user", "Use FastAPI", "now")],
        [{"source_key": "architecture.md", "content": "Local-first design"}],
    )
    assert "Local-first design" in context
    assert "Use FastAPI" in context


def test_context_respects_character_budget() -> None:
    context = build_memory_context(
        [MemoryMessage("user", "x" * 100, "now")],
        [],
        max_characters=20,
    )
    assert context == ""


def test_context_requires_positive_budget() -> None:
    with pytest.raises(ValueError):
        build_memory_context([], [], max_characters=0)
