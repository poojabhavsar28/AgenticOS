# Phase 4 — Multi-Agent Collaboration

## Scope

- Agent profiles with stable IDs, names, and declared capabilities.
- Deterministic capability-based task assignment.
- Shared in-memory task board with explicit lifecycle transitions.
- Dependency-aware readiness: a task becomes ready only after all dependencies complete.
- Addressed agent-to-agent messages with FIFO delivery and bounded inboxes.
- Coordinator facade for registration, delegation, task transitions, and messaging.

## Boundaries

This phase provides collaboration primitives, not autonomous parallel model execution. Agents are registered by the application; there is no dynamic agent spawning or model-based routing. The task board and message inboxes are in-memory and are lost on process restart. Messages are local process objects, not a network protocol. Agent IDs identify participants but do not authenticate them. The coordinator does not execute tools, shell commands, or generated code.

The capability matcher is deterministic: when multiple agents qualify, the lexicographically first agent ID is selected. Task results remain plain text and must be reviewed by the caller.

## Acceptance checks

- Duplicate and invalid agent/task/message contracts are rejected.
- Assignment selects only agents whose capabilities cover all task requirements.
- Assignment is deterministic when multiple agents qualify.
- Only the assigned agent can start, complete, or fail its task.
- Tasks cannot become ready until every declared dependency is completed.
- Messages are delivered only to registered recipients and in FIFO order.
- Inbox capacity and receive limits are enforced.
