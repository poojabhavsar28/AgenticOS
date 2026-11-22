# AgenticOS Security Model

## 1. Scope and security posture

This document describes the implemented controls in the Phase 15 development snapshot. It is an engineering security model, not a penetration-test report, compliance attestation, or production certification.

The design uses layered controls: authenticated principals, exact grants, ownership checks, bounded inputs and outputs, explicit human approval, fail-closed sandbox configuration, restrictive local storage permissions, and tamper-evident audit records.

## 2. Assets to protect

- Operator, administrator, and reviewer bearer credentials.
- Principal, token-verifier, and workspace-grant records.
- Workspace files and staged changes.
- Session messages, project notes, and repository-index contents.
- Run snapshots, events, and execution outputs.
- Pending sandbox source and one-time approval state.
- Audit records, HMAC key, and external chain-head checkpoints.
- Host filesystem, Docker daemon, and local Ollama service configuration.

## 3. Trust boundaries

| Boundary | Trust assumption | Control |
|---|---|---|
| Client → API | Client input is untrusted | Bearer authentication, typed validation, bounds |
| Principal → resource | Caller may request another user's data | Server-derived identity, ownership checks, exact grants |
| Agent → tool | Model output is untrusted | Explicit tool registry and authorization before dispatch |
| Agent → workspace | Paths and content may be malicious | Workspace-root resolution, bounded reads/listings, staged writes |
| Agent → code execution | Generated code is untrusted | Disabled-by-default sandbox, human review, one-time approval |
| Container → host | Container runtime is a boundary but not invulnerable | No network, read-only root, non-root, dropped caps, resource limits |
| Local DB → operator | Local files can be modified by privileged host actors | Private directory, file modes/ACLs, HMAC chain, external checkpoint |
| Repository text → model | Indexed content can contain malicious instructions | Treat retrieved text as untrusted context |

## 4. Authentication and identity

- API bearer authentication protects `/v1/*`; health and readiness endpoints remain public.
- Configured operator token and identity-admin token must be unique, high entropy, and never committed.
- The identity administrator is separately configured with `IDENTITY_ADMIN_TOKEN`.
- Managed token secrets are shown only at issuance/rotation; storage contains SHA-256 verifiers, not plaintext bearer tokens.
- Managed credentials can be revoked, rotated, and expire (30-day default, 90-day maximum).
- Disabled principals cannot authenticate.
- Strict bearer parsing, bounded token length, and duplicate Authorization-header rejection reduce ambiguous credential handling.
- Bootstrap administrator credential rotation is performed through deployment configuration, not through the admin API.

## 5. Authorization

Authorization is default-deny for protected operations. Grants bind:
- Principal
- Workspace
- Exact action
- Exact resource

The authenticated principal is derived from the credential, not trusted from model/tool arguments. The application checks relevant grants at API and tool boundaries. Run and session ownership is checked separately from workspace authorization. Access should be re-evaluated for long-lived operations and event streams so revoked grants do not silently remain effective.

Never use a session ID, run ID, workspace name, or review ID as a substitute for authentication.

## 6. Workspace and repository protections

- Workspace paths are resolved beneath a configured root.
- File operations are bounded and UTF-8-oriented.
- Writes are staged and require explicit approval before application.
- Repository indexing is explicit, bounded, and excludes hidden, binary, oversized, dependency, and cache content.
- Repository search is local keyword/SQLite FTS5 search.
- Repository excerpts and project notes are untrusted reference content, never trusted policy or instructions.

Path checks reduce accidental and unauthorized path traversal but do not isolate arbitrary processes. Use OS permissions and the sandbox for execution boundaries.

## 7. Sandbox execution controls

Execution is disabled unless explicitly configured. The backend requires a locally available administrator-approved image pinned by full SHA-256 digest. It never pulls an image at runtime and never falls back to host execution.

Implemented controls include:
- Separate request, policy, and result contracts.
- Allowlisted language/interpreter path and server-controlled runtime flags.
- Resource ceilings controlled by administrator policy.
- Non-root UID/GID, read-only root filesystem, no network, dropped Linux capabilities, and no-new-privileges.
- PID, CPU, memory, tmpfs, source-size, output-size, and wall-clock limits.
- Read-only mount of only the approved source payload.
- Disposable container and temporary directory with cleanup on success, failure, cancellation, and timeout.
- Human approval bound to the exact request fingerprint, distinct requester/reviewer credentials, no self-approval, bounded queue, expiry, and one-time consumption.
- Re-authorization before execution and sanitized audit outcomes.

Residual risk: Docker, containerd/runc, host kernel, Docker daemon configuration, and the host administrator remain trusted. Container escapes and denial-of-service against the host are not ruled out. Consider microVM isolation for untrusted public workloads.

## 8. Audit integrity

Audit events use canonical serialization and HMAC-SHA256 with:
- Monotonic sequence number
- Principal, action, resource, outcome, timestamp
- Previous-event digest
- Current event digest

SQLite triggers block ordinary updates and deletes. The administrator-only verification endpoint validates event sequence, links, and HMACs. The optional `expected_head` must come from a trusted independent location to detect tail truncation.

The current key file is stored beside the operations database under the private local data-directory boundary. This does not protect against a compromised AgenticOS service account or host administrator. Production hardening should move the key to an independent secret manager/KMS or protected OS key store, automate key rotation, and automate external checkpoint retention.

## 9. Local data protection

On POSIX, the expected private data directory is mode `0700`, and SQLite databases and sidecars are mode `0600`. Symlink and permissive custom-directory checks are enforced in the storage preparation path.

On Windows, POSIX mode bits are not an NTFS ACL boundary. Provision a dedicated directory and restrict access to the AgenticOS service identity and SYSTEM. Validate the actual ACL with `icacls` on the target host.

Backups, snapshots, crash dumps, logs, and copied databases must receive equivalent protections.

## 10. Operational security checklist

- [ ] Use separate high-entropy operator and administrator secrets.
- [ ] Keep secrets out of source control, logs, screenshots, and support bundles.
- [ ] Run under a dedicated least-privilege service account.
- [ ] Restrict the application data directory and backup access.
- [ ] Keep Ollama and Docker daemon access limited to the service/operator.
- [ ] Leave sandbox disabled unless there is an explicit operational need.
- [ ] Pin and review sandbox images by digest.
- [ ] Store audit chain-head checkpoints outside the host/database trust boundary.
- [ ] Monitor audit verification failures, authorization denials, and sandbox failures.
- [ ] Apply OS, Docker, Python, and dependency security updates.
- [ ] Re-run full CI and real-Docker integration tests after security-sensitive changes.

## 11. Explicit non-claims

AgenticOS does not currently claim:
- Protection from a compromised host administrator or service account.
- Perfect isolation from Docker/container runtime/kernel vulnerabilities.
- Distributed high availability or multi-region durability.
- Enterprise SSO, external IAM, or centralized authorization.
- Automated cryptographic key rotation or automated external audit checkpointing.
- Formal compliance certification or independent penetration-test clearance.
