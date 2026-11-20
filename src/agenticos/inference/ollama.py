"""Ollama HTTP adapter; requests remain on the configured local endpoint."""

import json
from collections.abc import AsyncIterator

import httpx


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_chunk_chars: int = 4_096,
    ) -> None:
        if max_chunk_chars < 1:
            raise ValueError("max_chunk_chars must be positive")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.max_chunk_chars = max_chunk_chars

    def _messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        ) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": self._messages(prompt, system),
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return str(payload["message"]["content"]).strip()
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Ollama returned an unexpected chat response") from exc

    async def generate_stream(
        self, prompt: str, *, system: str | None = None
    ) -> AsyncIterator[str]:
        """Yield bounded content chunks from Ollama's newline-delimited JSON stream."""
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": self._messages(prompt, system),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if len(line) > max(4_096, self.max_chunk_chars * 2):
                        raise RuntimeError("Ollama stream frame exceeds the size limit")
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("Ollama returned a malformed stream frame") from exc
                    if not isinstance(frame, dict):
                        raise RuntimeError("Ollama returned an unexpected stream frame")
                    if frame.get("error"):
                        raise RuntimeError("Ollama stream failed")
                    if frame.get("done") is True:
                        return
                    message = frame.get("message")
                    if not isinstance(message, dict):
                        raise RuntimeError("Ollama returned an unexpected stream message")
                    chunk = message.get("content", "")
                    if not isinstance(chunk, str):
                        raise RuntimeError("Ollama returned a non-text stream chunk")
                    if len(chunk) > self.max_chunk_chars:
                        raise RuntimeError("Ollama stream chunk exceeds the size limit")
                    if chunk:
                        yield chunk

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
