# AgenticOS

AgenticOS is a local-first, multi-agent coding platform. Its initial foundation is designed around locally hosted models through Ollama, with a modular runtime, API layer, and workspace-aware tooling.

## Initial direction

- Coding is the first supported workload.
- Ollama is the inference provider; no paid external model API is required.
- Agent execution is structured around explicit roles and bounded workflows.
- Workspace access and tool execution are treated as security boundaries.

## Development status

The repository is being built incrementally. The initial phase focuses on the project foundation, local inference integration, agent workflow, API, tests, and CI.

## Planned local setup

Ollama must be installed and running locally, with a coding model pulled before starting the application. Detailed setup instructions will be added as the implementation lands.
