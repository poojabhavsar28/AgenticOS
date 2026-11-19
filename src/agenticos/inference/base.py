"""Provider-neutral interface for local language model clients."""

from typing import Protocol


class ModelClient(Protocol):
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Generate a text response for a prompt."""
