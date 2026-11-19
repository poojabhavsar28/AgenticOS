# AgenticOS

AgenticOS is a local-first, multi-agent coding platform. Model inference is routed to a locally hosted Ollama instance. The initial workflow uses four focused roles: Planner, Coder, Reviewer, and Test Planner.

## Principles

- **Local-first inference:** Ollama is the only model provider; there is no paid external model API fallback.
- **Explicit agent roles:** each workflow stage has a defined responsibility.
- **Bounded execution:** runs have IDs, lifecycle states, a concurrency limit, and a timeout.
- **Controlled tools:** agent capabilities must be explicitly registered. No shell tool is enabled.
- **Safe output boundary:** generated code is returned as text; this phase does not execute shell commands or apply generated patches.
- **Workspace awareness:** workspace identifiers and resolved paths are checked against a configured root.

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
git switch feature/phase-2-execution
python -m venv .venv
```

Activate the environment (PowerShell: `.venv\Scripts\Activate.ps1`; macOS/Linux: `source .venv/bin/activate`), then install:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and adjust settings. Defaults: Ollama at `http://localhost:11434`, 300-second run timeout, and two concurrent runs.

## Run

```bash
uvicorn agenticos.api.main:app --reload
```

Health and readiness: `GET /health`, `GET /ready`.

Submit a run:

```bash
curl -X POST http://127.0.0.1:8000/v1/runs -H "Content-Type: application/json" -d '{"task":"Write a Python function that validates an email address."}'
```

Inspect its checkpoint with `GET /v1/runs/{run_id}`. Checkpoints are process-local and are lost on restart.

## Tests

```bash
ruff check .
pytest -q
```

## Current limitations

This remains a development foundation, not a production-safe autonomous coding environment. Authentication, durable run history, per-user authorization, rate limits, isolated code execution, patch approval, and comprehensive audit logging are not implemented. Workspace path validation alone is not an operating-system sandbox. Review generated code before use.
