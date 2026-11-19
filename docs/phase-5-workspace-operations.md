# Phase 5 — Workspace Operations and Patch Approval

## Scope

- Read UTF-8 text files from a named workspace.
- List workspace files with a configurable result limit.
- Stage proposed file content without modifying the target.
- Inspect pending changes and explicitly approve or reject them.
- Apply approved content with a temporary file and atomic replacement.
- Enforce workspace-relative paths, symlink boundary checks, and file-size limits.
- Expose read, list, stage, approve, and reject operations through FastAPI.

## API

- `GET /v1/workspaces/{workspace}/files`
- `GET /v1/workspaces/{workspace}/files/{relative_path}`
- `POST /v1/workspaces/{workspace}/changes`
- `GET /v1/workspaces/{workspace}/changes`
- `POST /v1/workspaces/{workspace}/changes/{change_id}/approve`
- `DELETE /v1/workspaces/{workspace}/changes/{change_id}`

A staged change does not touch the target file. Only the explicit approve operation writes it. Rejection discards the staged proposal.

## Boundaries and limitations

The staged-change queue is in-memory and is lost on process restart. This phase does not provide authenticated user identity, per-user approval authorization, version-control integration, diff generation, rollback, or an operating-system sandbox. The API currently has no authentication layer, so approval routes must not be exposed to untrusted networks. The file service rejects path traversal and resolved symlink escapes, but it is not a hardened defense against every possible local filesystem race or hostile concurrent process. Shell execution remains disabled. Only UTF-8 text files are supported.

## Acceptance checks

- Reads and listings stay inside the selected workspace.
- Traversal and symlink escapes are rejected.
- Read and write size limits are enforced.
- Staging never modifies a target file.
- Approval writes the staged content and clears the pending change.
- Rejection never writes the staged content.
- API tests verify explicit approval and rejection behavior.
