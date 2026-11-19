"""Tests for explicit tool registration."""

import pytest

from agenticos.runtime.tools import ToolRegistry


class EchoTool:
    name = "echo"

    async def execute(self, arguments: dict[str, object]) -> dict[str, object]:
        return arguments


def test_registry_exposes_only_registered_tools() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.names() == ("echo",)
    assert registry.get("echo") is not None
    with pytest.raises(KeyError, match="Unknown agent tool"):
        registry.get("shell")


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(EchoTool())
