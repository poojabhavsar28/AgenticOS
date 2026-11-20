import json

import httpx
import pytest

from agenticos.inference.ollama import OllamaClient


@pytest.mark.asyncio
async def test_generate_stream_yields_ordered_chunks_and_requests_streaming() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        body = (
            b'{"message":{"content":"Hello"},"done":false}\n'
            b'{"message":{"content":" world"},"done":false}\n'
            b'{"message":{"content":""},"done":true}\n'
        )
        return httpx.Response(200, content=body)

    client = OllamaClient(
        "http://ollama.test",
        "qwen2.5-coder:3b",
        transport=httpx.MockTransport(handler),
    )
    chunks = [chunk async for chunk in client.generate_stream("Say hello", system="Be brief")]

    assert chunks == ["Hello", " world"]
    assert requests == [
        {
            "model": "qwen2.5-coder:3b",
            "messages": [
                {"role": "system", "content": "Be brief"},
                {"role": "user", "content": "Say hello"},
            ],
            "stream": True,
        }
    ]


@pytest.mark.asyncio
async def test_generate_stream_rejects_malformed_frames() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json\n")

    client = OllamaClient(
        "http://ollama.test", "model", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(RuntimeError, match="malformed stream frame"):
        _ = [chunk async for chunk in client.generate_stream("task")]


@pytest.mark.asyncio
async def test_generate_stream_rejects_oversized_content_chunks() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        frame = json.dumps({"message": {"content": "x" * 9}, "done": False})
        return httpx.Response(200, content=f"{frame}\n".encode())

    client = OllamaClient(
        "http://ollama.test",
        "model",
        transport=httpx.MockTransport(handler),
        max_chunk_chars=8,
    )

    with pytest.raises(RuntimeError, match="chunk exceeds the size limit"):
        _ = [chunk async for chunk in client.generate_stream("task")]


@pytest.mark.asyncio
async def test_generate_stream_surfaces_provider_errors_without_echoing_payload() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"error":"private provider detail","done":false}\n',
        )

    client = OllamaClient(
        "http://ollama.test", "model", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(RuntimeError, match="Ollama stream failed") as error:
        _ = [chunk async for chunk in client.generate_stream("task")]
    assert "private provider detail" not in str(error.value)
