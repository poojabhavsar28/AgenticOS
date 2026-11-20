# Phase 14 — Sandboxed Code Execution

## Goal

Introduce an opt-in execution backend for generated code that runs in a disposable, constrained container. The host application must remain fail-closed: if the sandbox runtime or approved image is unavailable, code execution is rejected rather than falling back to the host.

## Security boundary

The container is a defense-in-depth boundary, not a guarantee against every container-runtime or kernel escape. The Docker daemon and host kernel remain trusted components. This phase must not claim that arbitrary hostile code is perfectly safe.

### Required defaults

- Execution is disabled unless an explicit sandbox configuration enables it.
- Use only a locally available, administrator-approved and pinned execution image; never pull images automatically at run time.
- Run as a fixed non-root UID/GID with a read-only root filesystem.
- Disable networking and use no host network mode.
- Drop all Linux capabilities and enable no-new-privileges.
- Apply explicit CPU, memory, PID, wall-clock, output-size and input-size limits.
- Provide only a fresh temporary working directory; do not mount the repository, home directory, Docker socket, credentials, or broad host paths.
- Make temporary storage size-bounded and destroy the container and temporary files after every run.
- Do not allow privileged mode, host PID/IPC namespaces, device access, arbitrary mounts, image overrides from API callers, or caller-supplied Docker flags.
- Capture container logs with the Docker local logging driver's 1 MiB rotation cap, then truncate the returned combined output to the request limit. The current CLI log path combines stdout/stderr into the result's stdout field; separate stream preservation remains a follow-up. Terminate on timeout or cancellation.
- Return structured execution results without exposing host paths, environment variables, secrets, or runtime internals.

## Scope

1. Define typed execution request, policy and result models with conservative defaults.
2. Add a sandbox interface so the runtime is independent of Docker-specific details.
3. Implement a Docker-backed runner using an argument array (never shell interpolation) and the required hardening options.
4. Validate language/command selection against a server-side allowlist; do not accept arbitrary executable paths or runtime flags from callers.
5. Stage only explicitly approved source files into a fresh temporary context.
6. Enforce timeout, CPU, memory, PID, input and output bounds, and reliably clean up containers and temporary data.
7. Keep execution opt-in and integrate it with workspace approval and tool authorization; generated code must not execute automatically merely because an agent produced it.
8. Emit bounded, sanitized audit events for allowed, denied, timed-out and completed executions.
9. Add deterministic unit tests using a fake sandbox runtime, plus Docker integration tests that run only when an approved local image/runtime is available.
10. Document installation, image preparation, configuration, threat model and operational limitations.

## Explicit non-goals

- Running code directly on the host as a fallback.
- Automatically downloading or building arbitrary images from user input.
- Network access from executed code.
- Mounting the Docker socket or exposing host credentials.
- Running privileged containers or supporting arbitrary Docker options.
- Claiming protection against vulnerabilities in Docker, containerd, runc, or the host kernel.
- Multi-host distributed execution, Kubernetes, browser IDEs, or hosted execution services.

## Proposed implementation sequence

1. **Contracts and policy:** typed request/result models, configuration, disabled-by-default policy and sandbox protocol.
2. **Docker runner:** hardened container creation, bounded input/output, timeout and cleanup.
3. **Authorization integration:** explicit approval, principal/action/resource checks and sanitized audit events.
4. **API/workflow integration:** opt-in execution tool with strict allowlists and no automatic execution.
5. **Verification and docs:** unit tests, optional Docker integration tests, security regression tests and operator documentation.

Each step should be delivered as a small, focused commit. Do not merge this phase into `dev` or `main` until the phase-specific checks pass and the user explicitly approves the merge.

## Acceptance checks

- Execution remains disabled by default and fails closed when configuration, runtime, or approved image is missing.
- No test path can cause a host-shell fallback.
- Container configuration enforces non-root, read-only root filesystem, no network, no capabilities, no-new-privileges, PID/CPU/memory limits and bounded temporary storage.
- API callers cannot choose arbitrary images, executable paths, mounts, environment variables, or runtime flags.
- Timeout and cancellation terminate execution and trigger container cleanup; output is capped by Docker's local log rotation and the request's byte limit.
- Containers and temporary data are cleaned up on success, failure, cancellation and timeout.
- Authorization is checked before execution; denied attempts are audited without leaking secrets.
- Unit tests run without Docker; Docker integration tests are deterministic and explicitly gated on runtime/image availability.
- Ruff, full pytest and the evaluation regression gate pass.

## Deferred risks and review items

- Container isolation depends on host kernel and runtime security; deployments requiring stronger isolation should evaluate a dedicated microVM or hardened sandbox runtime.
- Resource enforcement differs across operating systems and Docker implementations; supported platforms and exact guarantees must be documented.
- Windows developer environments may require Docker Desktop/WSL2, while CI can use Linux containers. Tests must not assume Docker is installed.
- A security review must verify the final Docker API invocation and all mount, namespace, capability and resource settings before enabling execution outside development.
