# AgenticOS

AgenticOS is a local-first, multi-agent coding platform. Model inference is routed to a locally hosted Ollama instance. The initial workflow uses four focused roles: Planner, Coder, Reviewer, and Test Planner.

## Principles

- **Local-first inference:** Ollama is the only model provider; there is no paid external model API fallback.
- **Explicit agent roles:** each workflow stage has a defined responsibility.
- **Bounded execution:** runs have IDs, lifecycle states, a concurrency limit, and a timeout.
- **Persistent memory:** SQLite stores session history and workspace-scoped project notes locally.
- **Controlled tools:** agent capabilities must be explicitly registered. No shell tool is enabled.
- **Safe output boundary:** generated code is returned as text; this phase does not execute shell commands or apply generated patches.
- **Workspace awareness:** workspace identifiers and resolved paths are checked against a configured root.
- **Agent collaboration:** capability-based delegation, dependency-aware task coordination, and bounded in-process agent messaging.
- **Workspace operations:** UTF-8 file reads, bounded listings, and staged writes that require explicit approval.
- **Evaluation gates:** deterministic checks for all four workflow stages, output bounds, required terms, and aggregate pass-rate thresholds.

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
- `PUT /v1/workspaces/{workspace}/context` stores a project note. JSON body: `{"source_key":"architecture.md","content":"Use async FastAPI routes","metadata":{"kind":"decision"}}`.
- `GET /v1/runs/{run_id}` returns the run checkpoint.

SQLite history persists across restarts. Run checkpoints remain process-local.

## Tests

```bash
ruff check .
pytest -q
```

## Current limitations

This remains a development foundation, not a production-safe autonomous coding environment. Authentication, durable run history, per-user authorization, rate limits, isolated code execution, patch approval, and comprehensive audit logging are not implemented. Session identifiers are not authentication credentials. Project notes are explicit text entries, not automatic repository indexing or semantic retrieval. Treat retrieved project context as untrusted reference material. Workspace path validation alone is not an operating-system sandbox. Review generated code before use.
