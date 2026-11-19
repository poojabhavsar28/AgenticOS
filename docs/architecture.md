# AgenticOS architecture

## Phase 1 boundaries

The first workload is coding. The runtime is local-first: model requests go to the configured Ollama HTTP endpoint. There is no hosted model-provider fallback.

## Request flow

1. FastAPI validates a coding task and workspace identifier.
2. The workspace helper resolves a path and rejects paths outside the configured workspace root.
3. LangGraph runs four sequential roles: planner, coder, reviewer, and test planner.
4. The API returns the role outputs with a generated run identifier.

## Safety boundaries

The initial implementation generates proposed code as text. It does not execute shell commands, apply patches, or write generated code into a workspace. Path validation is a boundary helper, not a complete operating-system sandbox. Production deployments should add authenticated users, per-user authorization, resource limits, audit storage, and isolated execution before enabling tools that mutate or execute code.

## Local inference

The Ollama adapter uses the configured local base URL and model. The default model is `qwen2.5-coder:3b`. Set `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in the environment to change them.
