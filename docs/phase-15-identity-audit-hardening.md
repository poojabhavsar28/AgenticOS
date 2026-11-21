# Phase 15 — Identity, Authorization, and Audit Hardening

## Goal

Move AgenticOS beyond its current single-operator authentication model toward explicit, revocable identities and workspace-scoped authorization. Close the high-severity Phase 14 security review findings before treating sandbox execution as suitable for untrusted users.

## Phase 14 carry-forward blockers

1. Stop persisting raw approval identifiers in SQLite. Separate public opaque review IDs from secrets; persist only a cryptographic digest for any secret-bearing token. Add a regression test that inspects stored rows and proves raw tokens are absent.
2. Harden the approval/operations data directory and SQLite database/sidecar permissions. Document and verify POSIX permissions and Windows ACL expectations.
3. Make Docker container lifecycle cleanup-safe even when create output is malformed; use a unique invocation label and only remove containers carrying that label.
4. Define whether sandbox output is combined or split; preserve a typed and documented contract.
5. Define a tamper-evident audit format and verification path, with retention and access controls.

## SQLite storage hardening implementation

The runtime now prepares the configured operations and memory database paths before opening their stores. The approval store also prepares its own path, and each connection reapplies restrictive modes to any existing database, rollback journal, WAL, and shared-memory sidecar.

### POSIX deployment

Use a dedicated directory owned by the service account. The default `.agenticos` directory is created/restricted to mode `0700`; database and existing sidecar files are restricted to `0600`. For a custom data directory, provision it with restrictive permissions before startup:

```sh
install -d -m 0700 -o agenticos -g agenticos /var/lib/agenticos
chmod 0700 /var/lib/agenticos
```

Custom parent directories that are group/other accessible or owned by another account are rejected rather than silently changing permissions on a potentially shared directory. Database paths must not be symlinks and must resolve to regular files.

### Windows deployment

Python's POSIX mode bits are not an NTFS ACL security boundary. Create a dedicated directory and grant access only to the Windows service identity and SYSTEM (replace the account with the actual service identity):

```powershell
New-Item -ItemType Directory -Force C:\ProgramData\AgenticOS
icacls C:\ProgramData\AgenticOS /inheritance:r
icacls C:\ProgramData\AgenticOS /grant:r "NT SERVICE\AgenticOS:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
```

The service identity must have modify access to create and update the SQLite database and sidecars. Do not grant access to interactive users or broad groups. The automated mode-bit tests are POSIX-only; Windows ACL correctness must be verified on the target host using `icacls` and the actual service account.

### Verification boundary

The POSIX tests verify directory mode `0700`, database/sidecar mode `0600`, and rejection of a permissive custom directory. These checks do not establish protection against root/Administrator, filesystem snapshots, backups, or a compromised service account. Backups must inherit equivalent access restrictions.

## Audit integrity implementation

The SQLite audit store now writes canonical, ordered events with sequence numbers, previous-event digests, and HMAC-SHA256 event authentication. The HMAC key must be at least 32 bytes. The API creates or loads a separate 32-byte key file beside the operations database, with owner-only permissions on POSIX, and rejects symlink/non-regular key paths. SQLite update/delete triggers provide an additional accidental-mutation guard; they are not treated as the cryptographic security boundary.

### Verification and truncation boundary

`SQLiteAuditLog.verify_integrity()` validates sequence continuity, previous-digest links, and every event HMAC. `chain_head()` returns the latest digest. To detect deletion of the newest events (tail truncation), operators must retain that chain head in an independent trusted location and pass it as `expected_head` to verification. A self-contained SQLite file cannot prove that its own newest rows were deleted.

The current key file is protected by the same private data-directory boundary as the database. This protects against other local users when filesystem permissions are correctly configured, but not against a compromised AgenticOS service account or host administrator. Production deployments should provision the HMAC key from an independent secret manager or protected key store and retain chain-head checkpoints outside the database. Key rotation, external checkpoint automation, and an operator-facing verification command/API remain follow-up work; this implementation does not claim protection against a fully compromised host.

## Scope

### 1. Identity lifecycle
- Introduce a persistent identity/principal model with stable IDs and enabled/disabled state.
- Support multiple independently authenticated principals without trusting caller-supplied principal IDs.
- Store only secure token verifiers; use high-entropy token generation, constant-time verification, and a documented rotation path.
- Support token rotation and revocation, including immediate invalidation of revoked credentials.
- Keep requester and human-approver roles distinct; preserve the prohibition on self-approval.
- Provide explicit bootstrap/admin setup without shipping default credentials.

### 2. Authorization
- Persist grants instead of relying only on process-local in-memory grants.
- Define exact actions and resource scopes, including workspace-level permissions.
- Enforce default-deny behavior at every API and tool boundary.
- Bind workspace identity from validated server-side context; never accept an arbitrary principal identity from agent tool arguments.
- Add tests for cross-user and cross-workspace access attempts, revocation, and privilege escalation.

### 3. Audit integrity
- Replace mutable-only audit history with a tamper-evident append-only design (for example, canonical event serialization plus a chained HMAC/signature).
- Include sequence number, timestamp, principal, action, resource, outcome, and previous-event digest; do not record source code, bearer tokens, or secrets.
- Add an integrity-verification command/API and tests for mutation, deletion, reordering, and truncation detection.
- Define retention, rotation, backup, and restricted storage-directory permissions.
- Ensure audit write failures continue to fail closed before irreversible operations.

### 4. Sandbox hardening carry-forward
- Fix the plaintext approval identifier finding and add database-at-rest regression coverage.
- Restrict the dedicated data directory and SQLite files/sidecars.
- Cover malformed Docker create output and cleanup by per-invocation label.
- Keep output bounds and clarify stream semantics.
- Keep execution disabled by default and preserve explicit human approval.

### 5. API and operator experience
- Add authenticated identity/grant management endpoints only for an administrator principal.
- Provide clear unauthorized/forbidden responses without leaking credential or policy details.
- Document initial admin bootstrap, token rotation/revocation, backup, audit verification, and recovery.
- Do not add a public self-registration endpoint in this phase.

## Non-goals

- External identity providers, SSO/OIDC/SAML, organization billing, hosted control planes, or multi-region identity replication.
- Kubernetes or distributed sandbox orchestration.
- Enabling arbitrary network access for sandboxed code.
- Automatic execution of generated code without explicit human approval.

## Proposed implementation sequence

1. **Threat model and contracts:** identity, token, grant, workspace scope, audit event and verifier models.
2. **Credential storage:** persistent token verifier store, rotation, revocation, expiry, and bootstrap.
3. **Persistent authorization:** role/grant store and workspace-scoped enforcement at API/tool boundaries.
4. **Audit integrity:** append-only tamper-evident event chain, verification, retention, and permission hardening.
5. **Phase 14 blockers:** approval-token at-rest fix, data-directory permissions, Docker malformed-ID cleanup, and output contract.
6. **API integration:** administrator-only identity/grant lifecycle endpoints and tests.
7. **Documentation and acceptance:** threat model, operator guide, security regression suite, full Ruff/pytest/evaluation gates.

Deliver each step in small commits. Keep this phase on its own feature branch. Do not merge Phase 14 or Phase 15 into `dev` or `main` without explicit user approval.

## Acceptance checks

- No raw bearer/approval secrets are persisted.
- Tokens can be rotated and revoked; revoked tokens fail immediately.
- Principal identity is always derived from authenticated server-side credentials.
- Workspace grants are exact-match, persistent, and default-deny.
- Cross-principal and cross-workspace access tests pass.
- Audit tampering, deletion, reordering, and truncation are detected.
- Audit data and SQLite sidecars are protected by documented directory/file permissions.
- Docker create failure/malformed output cannot leak a created container; cleanup is scoped to a unique invocation label.
- Sandbox remains disabled by default and human approval remains exact-request, one-time, and separate from requester credentials.
- Ruff, full pytest, evaluation regression gate, and opt-in real-Docker tests pass.

## Starting point

This branch is based on the Phase 14 review snapshot, including the CI verification record and security findings. Phase 14 remains unmerged; this plan does not imply production approval.
