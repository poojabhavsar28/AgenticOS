# AgenticOS

AgenticOS is a local-first, multi-agent coding platform. Model inference is routed to a locally hosted Ollama instance. The initial workflow uses four focused roles: Planner, Coder, Reviewer, and Test Planner.

## Principles

- **Local-first inference:** Ollama is the only model provider; there is no paid external model API fallback.
- **Explicit agent roles:** each workflow stage has a defined responsibility.
- **Bounded execution:** runs have IDs, lifecycle states, a concurrency limit, a timeout, and durable lifecycle event history.
- **Persistent memory:** SQLite stores session history, workspace-scoped project notes, and a bounded local repository index. Repository retrieval is opt-in per run.
- **Controlled tools:** agent capabilities must be explicitly registered. No shell tool is enabled.
- **Safe output boundary:** generated code is returned as text; this phase does not execute shell commands or apply generated patches.
- **Workspace awareness:** workspace identifiers and resolved paths are checked against a configured root.
- **Agent collaboration:** capability-based delegation, dependency-aware task coordination, and bounded in-process agent messaging.
- **Workspace operations:** UTF-8 file reads, bounded listings, and staged writes that require explicit approval.
- **Evaluation gates:** deterministic checks for all four workflow stages, output bounds, required terms, and aggregate pass-rate thresholds.
- **Default-deny permissions:** registered tools require explicit principal/action/resource grants before invocation; allowed and denied calls are audited in a bounded in-memory log.
- **Fail-closed execution:** generated-code execution remains disabled unless an independently isolated backend is explicitly configured.
- **Durable operations:** SQLite stores run checkpoints and append-only API audit events across process restarts.
- **API authentication:** a configured single-operator bearer token protects `/v1/*`; `/health` and `/ready` remain public.

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
git switch feature/phase-3-memory
python -m venv .venv
```

Activate the environment (PowerShell: `.venv\Scripts\Activate.ps1`; macOS/Linux: `source .venv/bin/activate`), then install:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and adjust settings. Defaults: Ollama at `http://localhost:11434`, 300-second run timeout, two concurrent runs, and SQLite memory at `.agenticos/memory.sqlite3`.

## Run

```bash
uvicorn agenticos.api.main:app --reload
```

Health and readiness: `GET /health`, `GET /ready`.

Submit a run with an optional session identifier:

```bash
curl -X POST http://127.0.0.1:8000/v1/runs -H "Content-Type: application/json" -d '{"task":"Write a Python function that validates an email address.","session_id":"my-project"}'
```

- `GET /v1/sessions/{session_id}/messages` returns recent conversation history.
- `POST /v1/workspaces/{workspace}/repository-index` refreshes the local text-file index.
- `GET /v1/workspaces/{workspace}/repository-search?q=...` searches indexed files and returns relative paths with bounded excerpts.
- Set `include_repository_context: true` in a run request to include matching repository excerpts as untrusted context.
- `PUT /v1/workspaces/{workspace}/context` stores a project note. JSON body: `{"source_key":"architecture.md","content":"Use async FastAPI routes","metadata":{"kind":"decision"}}`.
- `GET /v1/runs/{run_id}` returns the run checkpoint.
- `GET /v1/runs/{run_id}/events` returns bounded durable lifecycle events; use `after_event_id` to resume.
- `GET /v1/runs/{run_id}/events/stream` streams Server-Sent Events and resumes from the `Last-Event-ID` header.

SQLite history, run checkpoints, API audit events, and bounded run lifecycle events persist across restarts in local database files. SSE is a best-effort local stream; clients should reconnect using the last received event ID. Configure `OPERATIONS_DATABASE_PATH` to change the checkpoint/audit database location.

## Tests

```bash
ruff check .
pytest -q
```

## Current limitations

This remains a development foundation, not a production-safe autonomous coding environment. Multi-user identity lifecycle, token rotation/revocation, tamper-evident audit storage, and a production sandbox backend are not implemented. The security policy still uses in-memory grants and does not yet bind fine-grained per-workspace permissions to multiple users. Execution limit settings are contracts for a future backend, not OS-enforced controls. Staged workspace changes require explicit approval, but approval is available only to the configured single operator when API authentication is enabled. Session identifiers are not authentication credentials. Repository indexing is explicit and bounded; hidden, binary, oversized, and dependency/cache files are skipped. Search is local keyword/SQLite FTS5, not semantic retrieval, and the index must be refreshed after file changes. Retrieved repository text and project notes are untrusted reference material. Workspace path validation alone is not an operating-system sandbox. Review generated code before use.
