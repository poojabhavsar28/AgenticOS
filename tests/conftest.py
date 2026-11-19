"""Shared test fixtures."""

import pytest


class FakeModel:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        role = (
            (system or "response").split(" ")[2]
            if system and len(system.split()) > 2
            else "response"
        )
        return f"[{role}] {prompt[:80]}"

    async def health(self) -> bool:
        return True


@pytest.fixture

def fake_model() -> FakeModel:
    return FakeModel()
