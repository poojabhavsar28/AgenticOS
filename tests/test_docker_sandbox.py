import asyncio

import pytest

from agenticos.security.docker_sandbox import DockerSandboxBackend, DockerSandboxError
from agenticos.security.sandbox import SandboxExecutionRequest, SandboxPolicy


class FakeDockerBackend(DockerSandboxBackend):
    def __init__(self, policy: SandboxPolicy, *, timeout_wait: bool = False) -> None:
        super().__init__(policy)
        self.commands: list[tuple[str, ...]] = []
        self.timeout_wait = timeout_wait

    async def _docker(self, *arguments: str, timeout: float = 15.0):
        self.commands.append(arguments)
        if arguments[:2] == ("image", "inspect"):
            return 0, b"", b""
        if arguments[0] == "create":
            return 0, b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n", b""
        if arguments[:2] == ("ps", "--all"):
            return 0, b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\\n", b""
        if arguments[0] == "wait" and self.timeout_wait:
            raise DockerSandboxError("Docker command timed out")
        if arguments[0] == "wait":
            return 0, b"0\n", b""
        if arguments[0] == "logs":
            return 0, b"captured output", b""
        return 0, b"", b""


def approved_policy() -> SandboxPolicy:
    return SandboxPolicy(
        enabled=True,
        image_ref="registry.example/python@sha256:" + "b" * 64,
    )


@pytest.mark.asyncio
async def test_docker_backend_applies_hardening_and_cleans_container() -> None:
    backend = FakeDockerBackend(approved_policy())
    result = await backend.execute(SandboxExecutionRequest(source="print('safe')"))

    assert result.exit_code == 0
    assert result.stdout == "captured output"
    assert ("--network", "none") == tuple(
        backend.commands[1][backend.commands[1].index("--network"):
                            backend.commands[1].index("--network") + 2]
    )
    create = backend.commands[1]
    for flag in (
        "--read-only",
        "--user",
        "--cap-drop",
        "--security-opt",
        "--pids-limit",
        "--memory",
        "--memory-swap",
        "--cpus",
        "--entrypoint",
        "--tmpfs",
        "--mount",
        "--log-driver",
        "--log-opt",
    ):
        assert flag in create
    assert backend.commands[-1] == ("rm", "--force", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")


@pytest.mark.asyncio
async def test_docker_backend_fails_when_disabled() -> None:
    backend = FakeDockerBackend(SandboxPolicy())
    with pytest.raises(DockerSandboxError, match="disabled"):
        await backend.execute(SandboxExecutionRequest(source="print('no')"))
    assert backend.commands == []


@pytest.mark.asyncio
async def test_docker_backend_rejects_unavailable_local_image() -> None:
    class MissingImageBackend(FakeDockerBackend):
        async def _docker(self, *arguments: str, timeout: float = 15.0):
            self.commands.append(arguments)
            return 1, b"", b"missing"

    backend = MissingImageBackend(approved_policy())
    with pytest.raises(DockerSandboxError, match="image is not available locally"):
        await backend.execute(SandboxExecutionRequest(source="print('no')"))
    assert len(backend.commands) == 1


@pytest.mark.asyncio
async def test_docker_backend_kills_timed_out_container_and_cleans_up() -> None:
    backend = FakeDockerBackend(approved_policy(), timeout_wait=True)
    result = await backend.execute(SandboxExecutionRequest(source="while True: pass"))

    assert result.timed_out is True
    assert ("kill", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef") in backend.commands
    assert backend.commands[-1] == ("rm", "--force", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")


@pytest.mark.asyncio
async def test_docker_backend_cleans_up_when_execution_is_cancelled() -> None:
    class CancelledWaitBackend(FakeDockerBackend):
        async def _docker(self, *arguments: str, timeout: float = 15.0):
            self.commands.append(arguments)
            if arguments[:2] == ("image", "inspect"):
                return 0, b"", b""
            if arguments[0] == "create":
                return 0, b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n", b""
            if arguments[0] == "wait":
                raise asyncio.CancelledError
            return 0, b"", b""

    backend = CancelledWaitBackend(approved_policy())

    with pytest.raises(asyncio.CancelledError):
        await backend.execute(SandboxExecutionRequest(source="while True: pass"))

    assert backend.commands[-1] == ("rm", "--force", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")


@pytest.mark.asyncio
async def test_docker_backend_rejects_source_over_configured_limit() -> None:
    backend = FakeDockerBackend(approved_policy())
    request = SandboxExecutionRequest(
        source="x" * 200,
        limits={"max_source_bytes": 100},
    )
    with pytest.raises(ValueError, match="input limit"):
        await backend.execute(request)
    assert backend.commands == []


@pytest.mark.asyncio
async def test_docker_backend_rejects_limits_above_admin_policy() -> None:
    from agenticos.security.sandbox import SandboxLimits

    policy = SandboxPolicy(
        enabled=True,
        image_ref="registry.example/python@sha256:" + "b" * 64,
        limits=SandboxLimits(memory_megabytes=64),
    )
    backend = FakeDockerBackend(policy)
    request = SandboxExecutionRequest(source="print('no')")
    with pytest.raises(ValueError, match="administrator policy"):
        await backend.execute(request)
    assert backend.commands == []
