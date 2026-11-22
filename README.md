# AgenticOS

AgenticOS is a local-first, multi-agent coding platform. Model inference is routed to a locally hosted Ollama instance. The initial workflow uses four focused roles: Planner, Coder, Reviewer, and Test Planner.

## Principles

- **Local-first inference:** Ollama is the model provider; there is no paid external model API fallback.
- **Explicit agent roles:** each workflow stage has a defined responsibility.
- **Bounded execution:** runs have IDs, lifecycle states, a concurrency limit, a timeout, and durable lifecycle event history.
- **Persistent memory:** SQLite stores session history, workspace-scoped project notes, and a bounded local repository index. Repository retrieval is opt-in per run.
- **Controlled tools:** agent capabilities must be explicitly registered. No general shell tool is enabled.
- **Safe output boundary:** generated code is returned as text; it is not automatically executed or applied to a workspace.
- **Workspace awareness:** workspace identifiers and resolved paths are checked against a configured root.
- **Agent collaboration:** capability-based delegation, dependency-aware task coordination, and bounded in-process agent messaging.
- **Workspace operations:** UTF-8 file reads, bounded listings, and staged writes that require explicit approval.
- **Evaluation gates:** deterministic checks for all four workflow stages, output bounds, required terms, and aggregate pass-rate thresholds.
- **Default-deny permissions:** registered tools require persistent principal/workspace/action/resource grants before invocation; authorization decisions are audited.
- **Fail-closed execution:** generated-code execution remains disabled unless an independently isolated backend is explicitly configured.
- **Durable operations:** SQLite stores run checkpoints, lifecycle events, identity records, grants, and audit data.
- **Local token streaming:** Ollama model chunks can be observed as bounded, run-scoped SSE events; non-streaming inference remains supported.
- **Persistent identities:** bearer secrets are stored only as SHA-256 verifiers; credentials can be issued, rotated, revoked, and disabled.
- **Workspace authorization:** tool execution requires exact persistent grants scoped to a principal and workspace; unmatched requests are denied.
- **Identity administration:** a separately configured bootstrap administrator manages principals, credentials, and grants.
- **Sandbox approvals:** code execution requires a separate reviewer, exact-request approval, and one-time approval consumption.

## Documentation

Start with:
- [Architecture](docs/architecture.md)
- [API Reference](docs/api-reference.md)
- [Security Model](docs/security-model.md)
- [Operations Runbook](docs/operations-runbook.md)
- [Testing and CI](docs/testing-and-ci.md)
- [Phase History and Release Plan](docs/phase-roadmap.md)
- [All documentation](docs/README.md)

## Requirements

- Python 3.11+
- Ollama installed and running locally
- A coding model available in Ollama (default: `qwen2.5-coder:3b`)

Pull the default model:

```bash
ollama pull qwen2.5-coder:3b
```

## Setup

```bash
git clone https://github.com/poojabhavsar28/AgenticOS.git
cd AgenticOS
python -m venv .venv
```

Activate the environment (PowerShell: `.venv\\Scripts\\Activate.ps1`; macOS/Linux: `source .venv/bin/activate`), then install:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and adjust settings. Defaults include Ollama at `http://localhost:11434`, a 300-second run timeout, two concurrent runs, and SQLite memory at `.agenticos/memory.sqlite3`. Set `API_AUTH_TOKEN` to provision the ordinary operator identity. Set a separate high-entropy `IDENTITY_ADMIN_TOKEN` to enable `/v1/admin/*`. Keep both credentials outside source control and never reuse secrets.

## Run

```bash
uvicorn agenticos.api.main:app --reload
```

Health and readiness: `GET /health`, `GET /ready`. OpenAPI: `/openapi.json`.

Submit a run:

```bash
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H "Authorization: Bearer $API_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task":"Write a Python function that validates an email address.","session_id":"my-project"}'
```

Useful capabilities:
- `GET /v1/sessions/{session_id}/messages` returns recent conversation history, subject to ownership.
- `POST /v1/workspaces/{workspace}/repository-index` refreshes the local text-file index.
- `GET /v1/workspaces/{workspace}/repository-search?q=...` searches indexed files and returns bounded excerpts.
- Set `include_repository_context: true` in a run request to include matching repository excerpts as untrusted context.
- `PUT /v1/workspaces/{workspace}/context` stores a project note.
- `GET /v1/runs/{run_id}` returns the run checkpoint.
- `GET /v1/runs/{run_id}/events` returns bounded durable lifecycle events.
- `GET /v1/runs/{run_id}/events/stream` streams Server-Sent Events; reconnect with `Last-Event-ID`.

## Identity administration

When `IDENTITY_ADMIN_TOKEN` is configured, authenticate with its bearer value to use identity-management routes. These support principal creation, token issuance/rotation/revocation, principal enablement, and exact workspace grants. Token secrets are returned only at issue/rotation time. Bootstrap administrator credentials are rotated through deployment configuration.

## Tests

```bash
ruff check .
pytest -q
pytest -q tests/test_evaluation.py
```

The Docker integration job is conditional on the repository variable `AGENTICOS_TEST_SANDBOX_IMAGE` containing an approved full-digest image reference. A skipped Docker job is not evidence that real-container integration passed.

## Current limitations

AgenticOS is a development foundation, not a production-certified autonomous coding environment. The application is local-first and currently uses SQLite; it is not a distributed high-availability service. Repository retrieval is bounded keyword/SQLite FTS5 search, not semantic retrieval. Retrieved repository text and project notes are untrusted reference material. Workspace path validation is not an OS sandbox.

The opt-in Docker sandbox provides defense-in-depth controls but trusts the Docker daemon and host kernel and cannot guarantee protection from runtime or kernel escapes. Identity, token verifiers, grants, checkpoints, and audit records are stored locally. The audit chain requires an independently retained checkpoint to detect tail truncation; independent key management, automated key rotation, and automated external checkpoint retention remain follow-up work. Review generated code before use.

See the [Security Model](docs/security-model.md) and [Operations Runbook](docs/operations-runbook.md) before enabling sandbox execution or deploying beyond a trusted local environment.
