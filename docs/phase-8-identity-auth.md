# Phase 8 — Identity and API Authentication

## Goal

Replace trusted caller-supplied identities with an authenticated API principal before exposing AgenticOS beyond a private development environment.

## Scope

- Define an immutable authenticated-principal contract and an authentication provider interface.
- Add a local bearer-token provider for single-operator deployments. Compare token digests in constant time and never log or return credentials.
- Protect run, session, workspace, approval, and audit-sensitive endpoints. Keep only health/readiness endpoints public.
- Derive permission-policy principal IDs from the authenticated principal; never accept principal identity from request JSON.
- Add explicit development/test authentication fixtures. Production configuration must fail closed when authentication is not configured.
- Add tests for missing, malformed, invalid, and valid bearer tokens, endpoint coverage, and identity propagation.

## Security constraints

- No self-service registration, password storage, OAuth, or external identity service in this phase.
- Do not place bearer tokens in URLs, logs, exception messages, or audit event payloads.
- A single configured operator token is a bootstrap mechanism, not multi-user identity management.
- The existing workspace and permission layers remain defense-in-depth; authentication does not make workspace paths an OS sandbox.
- Shell and generated-code execution remain disabled.

## Acceptance checks

- Protected endpoints reject unauthenticated requests with HTTP 401.
- Health and readiness remain reachable without credentials.
- Authenticated requests receive a stable server-derived principal.
- No request body field can override the principal.
- Ruff, the complete pytest suite, and dedicated authentication regression tests pass.

## Deferred

Multi-user accounts, token rotation/revocation API, role administration UI, OAuth/OIDC, durable audit storage, and OS-enforced execution isolation.

## Initial implementation

The API now supports an optional single-operator bearer token. When configured, all `/v1/*` routes require it; `/health` and `/ready` remain public. Tokens are compared using SHA-256 digests and constant-time comparison. The token is not stored in plaintext by the authenticator.

In production mode, application startup fails if `API_AUTH_TOKEN` is absent. Development mode remains backward-compatible and unauthenticated unless a token is configured. The `/v1/me` endpoint reports the server-derived principal when authentication is enabled.

This is a bootstrap single-operator mechanism, not multi-user authentication. Deploy behind TLS, use a high-entropy secret, and never commit the token.
