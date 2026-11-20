# Phase 12 — Agent Workflow Progress and Cooperative Cancellation

## Goal

Expose meaningful progress for each agent stage and allow a caller to request safe cancellation of a running workflow, while preserving the local-first execution model.

## Scope

- Add a typed, bounded progress event contract for the existing Planner, Coder, Reviewer, and Test Planner stages.
- Emit stage-started, stage-completed, and stage-failed events with run ID, stage name, timestamp, and safe operational metadata.
- Reuse the durable run-event store and existing run-scoped history/SSE endpoints.
- Add cooperative cancellation through the existing run lifecycle; cancellation requests must be observable and must not be reported as completed before the workflow actually stops.
- Ensure cancellation is checked at safe workflow boundaries and does not interrupt SQLite writes or leave run state inconsistent.
- Preserve timeout behavior and distinguish user-requested cancellation from timeout and execution failure.
- Keep event ordering deterministic for concurrent runs and prevent one run's cancellation from affecting another.
- Add deterministic tests using fake workflows; tests must not require Ollama or network access.
- Document supported cancellation boundaries, progress event schema, and SSE client behavior.

## Implemented so far

- Added typed `AgentStage`, `StageEventType`, and `StageProgress` contracts.
- Added per-invocation progress callbacks to the LangGraph workflow, avoiding shared mutable callback state across concurrent runs.
- Emits start, completion, and failure events for Planner, Coder, Reviewer, and Test Planner.
- Persists stage events through the existing SQLite run-event store. Payloads contain stage, timestamp, and duration only; they exclude prompts and model output.
- Added deterministic tests for ordered stage events and failure metadata.

## Safety and reliability constraints

- Do not log prompts, model outputs, bearer tokens, secrets, or file contents in progress metadata.
- Progress payloads and event retention remain bounded.
- A disconnected SSE client must not block workflow execution.
- Cancellation is cooperative; do not claim immediate interruption of a model request that cannot be safely interrupted.
- Preserve existing API authentication policy and default-deny tool permissions.
- No external telemetry, hosted services, distributed brokers, or paid model APIs.

## Acceptance checks

- Every workflow stage emits the expected start and terminal progress events.
- Event history remains durable and run-scoped; SSE can replay events after a supplied event ID.
- Cancellation requests are isolated by run ID and reach a terminal cancelled state only after execution has stopped.
- Timeout, cancellation, and failure remain distinguishable.
- Concurrent runs do not leak progress or cancellation state.
- Event payload bounds and existing retention limits are enforced.
- Ruff, full pytest, and the evaluation regression gate pass.

## Deferred

- Token-level streaming and partial model output.
- Forcefully interrupting in-flight Ollama generation when the provider cannot safely cancel it.
- Distributed cancellation, multi-process pub/sub, dashboards, OpenTelemetry, and user-specific subscriptions.
