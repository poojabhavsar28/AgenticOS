# AgenticOS API Reference

This route reference is checked against the FastAPI-generated OpenAPI schema by `tests/test_api_contract.py`. Request/response fields and validation constraints are defined by the live schema and source contracts; clients should still fetch `/openapi.json` from the exact deployed version before integration.

## Authentication

When API authentication is configured, protected `/v1/*` routes require a bearer token in the `Authorization` header. The public health endpoints are `/health` and `/ready`. Identity administration routes additionally require a principal provisioned with the configured `IDENTITY_ADMIN_TOKEN`.

Sandbox reviewer operations are a deliberate exception to the ordinary API bearer middleware: `GET /v1/sandbox/reviews`, `GET /v1/sandbox/reviews/{review_id}`, and `POST /v1/sandbox/approvals/{review_id}/approve` require the separate `X-Sandbox-Approval-Token` header with a `Bearer <credential>` value. The reviewer page is `GET /sandbox/review`. Requesting an approval at `POST /v1/sandbox/approvals` remains an ordinary authenticated requester operation. Do not reuse credentials across roles.

## Health and identity

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness/health response |
| GET | `/ready` | Readiness check including required dependencies |
| GET | `/v1/me` | Return the authenticated principal identity |

## Runs and workflow execution

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/runs` | Execute a coding task and return its run result |
| POST | `/v1/runs/start` | Start a run asynchronously; returns an accepted run identifier |
| GET | `/v1/runs/{run_id}` | Read a run snapshot/checkpoint, subject to ownership |
| POST | `/v1/runs/{run_id}/cancel` | Request cancellation of a running workflow |
| GET | `/v1/runs/{run_id}/events` | Read bounded durable lifecycle events; supports event cursor |
| GET | `/v1/runs/{run_id}/events/stream` | Subscribe to run events through Server-Sent Events; reconnect with Last-Event-ID |

A run is bounded by configured timeout and concurrency limits. Streaming is best-effort; clients should persist the last received event ID and reconnect after interruptions.

## Sessions and project context

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/sessions/{session_id}/messages` | Read session conversation history after ownership checks |
| PUT | `/v1/workspaces/{workspace}/context` | Save workspace-scoped project context |

Session identifiers are not credentials. The authenticated principal and ownership rules determine access.

## Repository index

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/workspaces/{workspace}/repository-index` | Explicitly refresh the bounded local repository index |
| GET | `/v1/workspaces/{workspace}/repository-search?q=...` | Search indexed local text files and return bounded excerpts |

Repository indexing skips hidden, binary, oversized, dependency, and cache files. Search is local keyword/SQLite FTS5 search, not semantic search. Refresh the index after relevant repository changes. Treat returned excerpts as untrusted context.

## Workspace file operations

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/workspaces/{workspace}/files` | List bounded workspace files |
| GET | `/v1/workspaces/{workspace}/files/{relative_path}` | Read a UTF-8 text file |
| POST | `/v1/workspaces/{workspace}/changes` | Stage a proposed file change |
| GET | `/v1/workspaces/{workspace}/changes` | List pending staged changes |
| POST | `/v1/workspaces/{workspace}/changes/{change_id}/approve` | Approve and apply a staged change |
| DELETE | `/v1/workspaces/{workspace}/changes/{change_id}` | Reject/discard a staged change |

All paths are resolved under the configured workspace root. Staged changes are not applied until approved. Path validation is not a process sandbox.

## Tool execution

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/tools/{tool_name}/execute` | Execute a registered tool under the authenticated principal's permissions |
| POST | `/v1/workspaces/{workspace_id}/tools/{tool_name}/execute` | Execute a registered tool scoped to a workspace |

Only registered tools are available. Authorization is checked against exact principal/workspace/action/resource grants. No general shell tool is enabled.

## Identity administration

These endpoints require the identity administrator credential.

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/admin/principals` | Create a principal |
| POST | `/v1/admin/principals/{principal_id}/tokens` | Issue a managed token (secret returned once) |
| POST | `/v1/admin/tokens/{token_id}/rotate` | Atomically rotate a managed token |
| DELETE | `/v1/admin/tokens/{token_id}` | Revoke a managed token |
| PATCH | `/v1/admin/principals/{principal_id}` | Enable or disable a principal |
| PUT | `/v1/admin/principals/{principal_id}/workspaces/{workspace_id}/grants` | Add an exact workspace/action/resource grant |
| DELETE | `/v1/admin/principals/{principal_id}/workspaces/{workspace_id}/grants` | Revoke an exact grant |
| GET | `/v1/admin/audit/verify` | Verify audit-chain integrity; optional `expected_head` checkpoint |

Managed token lifetime defaults to 30 days and is bounded to 90 days. Bootstrap administrator credential changes are performed through deployment configuration, not these endpoints.

## Sandbox approval and execution

| Method | Path | Purpose |
|---|---|---|
| GET | `/sandbox/review` | Reviewer page |
| GET | `/v1/sandbox/reviews` | List pending review requests |
| GET | `/v1/sandbox/reviews/{review_id}` | Inspect a review request |
| POST | `/v1/sandbox/approvals` | Submit source and limits for human review |
| POST | `/v1/sandbox/approvals/{review_id}/approve` | Approve the exact pending request as an authorized reviewer |
| POST | `/v1/sandbox/execute` | Execute an approved request after re-authorization and one-time approval consumption |

The requester and approver are distinct. Approval is bound to the exact request fingerprint and is single-use. The sandbox must be explicitly enabled, and the approved image must already exist locally by digest. The sandbox API does not accept arbitrary Docker flags, host mounts, or caller-selected images.

## Client integration guidance

1. Fetch `/openapi.json` from the exact deployed version for field-level schemas.
2. Send bearer tokens only over a trusted local/private network or TLS-terminated deployment.
3. Treat model output, repository excerpts, file contents, and sandbox output as untrusted.
4. Use run IDs and event IDs only as identifiers; do not treat them as secrets.
5. Reconnect SSE with `Last-Event-ID` and tolerate duplicate delivery around reconnect boundaries.
6. Handle 401/403 separately from validation, conflict, capacity, and runtime errors.
7. Do not retry non-idempotent approval or execution calls without checking current review/run state.
