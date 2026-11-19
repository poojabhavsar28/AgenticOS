# AgenticOS

AgenticOS is a local-first, multi-agent coding platform. The first workload is coding, and model inference is routed to a locally hosted Ollama instance. The initial workflow uses four focused roles: Planner, Coder, Reviewer, and Test Planner.

## Principles

- **Local-first inference:** Ollama is the only model provider in this phase; there is no paid external model API fallback.
- **Explicit agent roles:** each workflow stage has a defined responsibility.
- **Bounded behavior:** generated code is returned as text; this phase does not execute shell commands or apply generated patches.
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

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/poojabhavsar28/AgenticOS.git
cd AgenticOS
python -m venv .venv
```

Activate it:

- Windows PowerShell: `.venv\\Scripts\\Activate.ps1`
- macOS/Linux: `source .venv/bin/activate`

Install the project:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and adjust the local settings if required. The default Ollama endpoint is `http://localhost:11434`.

## Run the API

```bash
uvicorn agenticos.api.main:app --reload
```

Check service health:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

Submit a coding task:

```bash
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"task":"Write a Python function that validates an email address."}'
```

The response contains the plan, proposed code, review, and test plan. The API does not claim that generated code has been applied or executed.

## Tests and lint

```bash
pytest -q
ruff check .
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the initial request flow and security boundaries.

## Current limitations

This is an initial foundation, not a production-safe autonomous coding environment. Authentication, durable run history, per-user authorization, rate limits, isolated code execution, patch approval, and comprehensive audit logging are not implemented yet. Workspace path validation alone is not an operating-system sandbox. Review generated code before using it.
