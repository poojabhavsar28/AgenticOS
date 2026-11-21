# Phase 14 — Security and Implementation Review

## Review target

- Branch: `feature/phase-14-sandboxed-execution`
- Reviewed implementation baseline: `d74d3b655bc0abb6fad8d45189a41b67bb161fd5`
- CI run: [#44914812543](https://github.com/poojabhavsar28/AgenticOS/actions/runs/44914812543)
- CI result: quality and real-Docker integration jobs passed.
- Scope inspected: sandbox contracts, Docker backend, approval store, authorization wrapper, audit stores, API/tool adapters, Phase 14 documentation, and focused unit/integration tests.

## Findings

### High — approval identifier is persisted in plaintext

`SQLiteExecutionApprovalStore.create` stores the SHA-256 digest in `approval_id`, but also stores the original value in `public_id`. The review/list API returns that `public_id`. Therefore the approval identifier is not actually secret-at-rest despite the digest column, and the documentation's statement that approval hashes remain for verification is incomplete.

**Required before production:** separate a non-secret opaque review-record identifier from any bearer-like approval secret; persist only a digest of secrets; ensure review/approve/execute APIs remain protected by the distinct reviewer/requester credentials. Add a database-inspection regression test proving raw approval secrets are absent.

### High — SQLite directory permissions are not hardened

The approval store attempts to chmod the database file to `0600`, but does not restrict the containing directory. On POSIX systems, a permissive parent directory can allow replacement, deletion, or access to SQLite sidecar files. The operations database may also contain other sensitive records.

**Required before production:** create/use a dedicated private data directory with restrictive permissions (and document equivalent Windows ACL requirements); apply safe permissions to newly created database files and account for SQLite WAL/journal sidecars. Verify effective permissions in tests where supported.

### Medium — malformed container ID after create can bypass cleanup

The Docker backend validates the returned container identifier before entering the `try/finally` cleanup block. If Docker successfully creates a container but returns an empty or malformed identifier, the function raises without attempting cleanup. The normal valid-ID success, failure, timeout, and cancellation paths do have forced removal coverage.

**Recommended fix:** make container creation and identifier validation part of a cleanup-safe lifecycle; where the ID cannot be trusted, use a safe, unique label assigned at create time and clean up only containers carrying that invocation label. Add a regression test for malformed create output.

### Medium — output streams are combined

The Docker CLI log path combines stdout and stderr into the result's `stdout`, leaving `stderr` empty. This is explicitly disclosed in the Phase 14 documentation and does not invalidate the current bounded-output behavior, but callers cannot distinguish program output from errors.

**Recommended follow-up:** preserve separate streams if the runtime interface supports it safely, or explicitly keep a combined-output contract and remove misleading expectations from clients.

### Medium — audit durability is not tamper-evident

The SQLite audit store persists events and provides ordered bounded reads, but the table is not cryptographically tamper-evident and does not enforce an immutable retention policy. A process or database owner can alter or delete records. The separate in-memory audit implementation is volatile.

**Required before production:** define the threat model and retention policy; use a tamper-evident chain/signature or externally protected append-only sink, restrict write/read access, and test integrity verification.

### Medium — container isolation is host/runtime dependent

The integration tests verify the configured Linux Docker daemon's non-root UID, read-only root filesystem and workspace mount, disabled network, resource limits, capability drop, no-new-privileges, tmpfs, timeout and output truncation. They do not prove protection against Docker/containerd/runc or kernel vulnerabilities, nor establish equivalent behavior on every Docker Desktop/rootless/Windows environment.

**Operational requirement:** keep the feature disabled by default; enable only on a supported, patched, dedicated runtime with reviewed image provenance. Consider a microVM or hardened sandbox runtime for hostile multi-tenant workloads.

## Controls verified in source/tests

- Sandbox disabled by default; enabled policy requires a full SHA-256 digest-pinned image.
- The backend checks the approved image is already local and does not pull it.
- Docker is invoked with an argument array, fixed Python entrypoint, no network, read-only rootfs, non-root UID/GID, all capabilities dropped, no-new-privileges, PID/CPU/memory limits, bounded tmpfs, read-only source mount, and local log rotation.
- Request limits cannot exceed administrator policy; source and returned output are bounded.
- Valid container IDs are removed in a `finally` block; timeout and cancellation paths have tests.
- Requester and approver credentials are distinct; requester cannot approve own execution; approver identity is allowlisted.
- Approval is bound to requester and canonical request fingerprint, has a maximum 15-minute lifetime, and is atomically single-use.
- Execution tool identities are server-bound; tool permissions are exact-match/default-deny; requesting approval does not execute code.
- Audit failure before execution prevents execution; completion-audit failure preserves the result and warns against automatic retry.
- API tests cover auth boundaries, review endpoints, disabled mode, and explicit approval requirements.

## Documentation and acceptance disposition

- Phase 14 quality and real-Docker CI acceptance checks passed on run #44914812543.
- Documentation now records that result and clarifies that CI verification is not a production security certification.
- **Phase 14 CI/functional acceptance: passed.**
- **Production security acceptance: pending** until the two High findings are resolved and the Medium findings are either fixed or explicitly accepted with an operational control.
- No merge to `dev` or `main` is authorized or performed by this review.
