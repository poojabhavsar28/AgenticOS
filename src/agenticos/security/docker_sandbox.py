"""Docker-backed isolated execution with fail-closed defaults.

The Docker daemon and host kernel remain trusted components. This backend is
defense in depth, not a guarantee against container-runtime or kernel escapes.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxPolicy,
)


class DockerSandboxError(RuntimeError):
    """Raised when the configured Docker sandbox cannot execute safely."""


class DockerSandboxBackend:
    """Run allowlisted Python source in a disposable hardened Docker container."""

    def __init__(
        self,
        policy: SandboxPolicy,
        *,
        docker_executable: str = "docker",
    ) -> None:
        self.policy = policy
        self.docker_executable = docker_executable

    async def _docker(
        self, *arguments: str, timeout: float = 15.0
    ) -> tuple[int, bytes, bytes]:
        try:
            process = await asyncio.create_subprocess_exec(
                self.docker_executable,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except FileNotFoundError as exc:
            raise DockerSandboxError("Docker CLI is unavailable") from exc
        except TimeoutError as exc:
            raise DockerSandboxError("Docker command timed out") from exc
        return process.returncode or 0, stdout, stderr

    async def execute(
        self, request: SandboxExecutionRequest
    ) -> SandboxExecutionResult:
        if not self.policy.enabled or not self.policy.image_ref:
            raise DockerSandboxError("Sandbox execution is disabled")
        if len(request.source.encode("utf-8")) > request.limits.max_source_bytes:
            raise ValueError("Source exceeds configured sandbox input limit")

        image_status, _, _ = await self._docker(
            "image", "inspect", self.policy.image_ref, timeout=10.0
        )
        if image_status != 0:
            raise DockerSandboxError(
                "Approved sandbox image is not available locally; image pulls are disabled"
            )

        with tempfile.TemporaryDirectory(prefix="agenticos-sandbox-") as temporary:
            source_dir = Path(temporary)
            source_file = source_dir / "main.py"
            source_file.write_text(request.source, encoding="utf-8")
            mount = f"type=bind,src={source_dir},dst=/workspace,readonly"
            limits = request.limits
            create_args = (
                "create",
                "--network",
                "none",
                "--read-only",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                str(limits.pid_limit),
                "--memory",
                f"{limits.memory_megabytes}m",
                "--cpus",
                str(limits.cpu_count),
                "--tmpfs",
                f"/tmp:rw,noexec,nosuid,size={limits.tmpfs_megabytes}m",
                "--mount",
                mount,
                "--workdir",
                "/tmp",
                "--log-driver",
                "none",
                self.policy.image_ref,
                "python",
                "-I",
                "-B",
                "/workspace/main.py",
            )
            create_status, create_out, _ = await self._docker(*create_args)
            if create_status != 0:
                raise DockerSandboxError("Docker refused to create the sandbox container")
            container_id = create_out.decode("utf-8", errors="replace").strip()
            if not container_id or len(container_id) > 128:
                raise DockerSandboxError("Docker returned an invalid container identifier")

            timed_out = False
            exit_code = 1
            try:
                start_status, _, _ = await self._docker("start", container_id)
                if start_status != 0:
                    raise DockerSandboxError("Docker failed to start the sandbox container")
                try:
                    wait_status, wait_out, _ = await self._docker(
                        "wait", container_id, timeout=limits.timeout_seconds
                    )
                    if wait_status != 0:
                        raise DockerSandboxError("Docker failed while waiting for execution")
                    exit_code = int(wait_out.decode("ascii").strip())
                except DockerSandboxError as exc:
                    if "timed out" not in str(exc):
                        raise
                    timed_out = True
                    await self._docker("kill", container_id, timeout=5.0)
                # The none logging driver prevents unbounded daemon log storage.
                # Output is intentionally empty until a separately bounded output
                # transport is implemented and verified.
                return SandboxExecutionResult(
                    exit_code=exit_code,
                    stdout="",
                    stderr="",
                    timed_out=timed_out,
                    output_truncated=False,
                )
            finally:
                await self._docker("rm", "--force", container_id, timeout=10.0)
