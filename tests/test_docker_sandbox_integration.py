"""Opt-in tests against a real local Docker daemon and approved image.

Set AGENTICOS_DOCKER_INTEGRATION=1 and
AGENTICOS_TEST_SANDBOX_IMAGE to a locally available digest-pinned Python image.
These tests never pull images and are skipped in ordinary CI/developer runs.
"""

import json
import os
import shutil
import subprocess

import pytest

from agenticos.security.docker_sandbox import DockerSandboxBackend
from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    SandboxLimits,
    SandboxPolicy,
)

_ENABLED = os.getenv("AGENTICOS_DOCKER_INTEGRATION") == "1"
_IMAGE = os.getenv("AGENTICOS_TEST_SANDBOX_IMAGE")
pytestmark = pytest.mark.skipif(
    not _ENABLED or not _IMAGE,
    reason="Set AGENTICOS_DOCKER_INTEGRATION=1 and AGENTICOS_TEST_SANDBOX_IMAGE",
)


def _policy() -> SandboxPolicy:
    if not _IMAGE:
        pytest.skip("No approved integration image configured")
    if not shutil.which("docker"):
        pytest.fail("Docker integration was enabled, but Docker CLI is unavailable")
    inspected = subprocess.run(
        ["docker", "image", "inspect", _IMAGE],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if inspected.returncode:
        pytest.fail("Approved image is not present locally; tests never pull images")
    return SandboxPolicy(enabled=True, image_ref=_IMAGE)


class InspectingDockerBackend(DockerSandboxBackend):
    """Capture effective container settings before the backend removes the container."""

    def __init__(self, policy: SandboxPolicy) -> None:
        super().__init__(policy)
        self.container_inspect: dict | None = None

    async def _docker(self, *arguments: str, timeout: float = 15.0):
        result = await super()._docker(*arguments, timeout=timeout)
        if arguments and arguments[0] == "logs":
            container_id = arguments[1]
            status, output, _ = await super()._docker("inspect", container_id)
            if status == 0:
                self.container_inspect = json.loads(output)[0]
        return result


@pytest.mark.asyncio
async def test_real_container_enforces_isolation_and_runs_as_non_root() -> None:
    backend = InspectingDockerBackend(_policy())
    source = """
import json
import os
import socket

checks = {}
checks["uid"] = os.getuid()
try:
    with open("/workspace/should-not-write", "w", encoding="utf-8") as handle:
        handle.write("bad")
    checks["workspace_read_only"] = False
except OSError:
    checks["workspace_read_only"] = True
try:
    with open("/rootfs-should-not-write", "w", encoding="utf-8") as handle:
        handle.write("bad")
    checks["rootfs_read_only"] = False
except OSError:
    checks["rootfs_read_only"] = True
with open("/tmp/sandbox-write-test", "w", encoding="utf-8") as handle:
    handle.write("ok")
try:
    socket.setdefaulttimeout(0.5)
    socket.create_connection(("1.1.1.1", 443))
    checks["network_blocked"] = False
except OSError:
    checks["network_blocked"] = True
print(json.dumps(checks))
"""
    result = await backend.execute(SandboxExecutionRequest(source=source))

    assert result.exit_code == 0, result.stdout
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "uid": 65534,
        "workspace_read_only": True,
        "rootfs_read_only": True,
        "network_blocked": True,
    }

    assert backend.container_inspect is not None
    host = backend.container_inspect["HostConfig"]
    assert host["NetworkMode"] == "none"
    assert host["ReadonlyRootfs"] is True
    assert host["UsernsMode"] in ("", None)
    assert host["PidsLimit"] == 64
    assert host["Memory"] == 128 * 1024 * 1024
    assert "ALL" in host["CapDrop"]
    assert any("no-new-privileges" in item for item in host["SecurityOpt"])
    assert any(mount["Destination"] == "/workspace" and not mount["RW"]
               for mount in backend.container_inspect["Mounts"])


@pytest.mark.asyncio
async def test_real_container_timeout_is_enforced_and_reported() -> None:
    policy = _policy()
    limits = SandboxLimits(timeout_seconds=1)
    backend = DockerSandboxBackend(policy)
    result = await backend.execute(
        SandboxExecutionRequest(source="while True:\n    pass\n", limits=limits)
    )
    assert result.timed_out is True


@pytest.mark.asyncio
async def test_real_container_output_is_truncated_to_request_limit() -> None:
    policy = _policy()
    limits = SandboxLimits(max_output_bytes=32)
    backend = DockerSandboxBackend(policy)
    result = await backend.execute(
        SandboxExecutionRequest(
            source="print('x' * 500)\n",
            limits=limits,
        )
    )
    assert result.output_truncated is True
    assert len(result.stdout.encode("utf-8")) <= limits.max_output_bytes
