# Phase 13 — Local Model Token Streaming

## Goal

Expose incremental model output from the local Ollama provider to authenticated API clients, while preserving the existing sequential agent workflow, durable run lifecycle, stage progress, and cooperative cancellation behavior.

## Scope

- Extend the Ollama inference adapter with an asynchronous streaming response path using Ollama's local streaming API.
- Preserve the existing non-streaming inference contract and behavior for current callers.
- Define bounded, typed token/chunk events that identify the run and workflow stage without exposing prompts, credentials, or unrelated state.
- Forward chunks through the existing run-scoped event/SSE infrastructure with deterministic event IDs and replay support where the durable event store permits it.
- Keep token payloads bounded and avoid persisting full generated model output in the operational event log by default; document the replay semantics for transient token chunks.
- Propagate provider errors and cancellation distinctly; cooperative cancellation must still stop at safe boundaries when the provider cannot interrupt an in-flight request.
- Ensure disconnected SSE clients do not block inference or workflow execution.
- Add deterministic tests with a fake streaming transport; tests must not require Ollama or network access.
- Document client consumption, buffering, reconnect behavior, and limitations.

## Implemented

- Added an asynchronous Ollama newline-delimited JSON streaming adapter while preserving the existing non-streaming `generate` method.
- Added injectable HTTP transport support for deterministic tests without a live Ollama service.
- Added typed run/stage-scoped token chunks with a 1,024-character event bound.
- The workflow streams model chunks stage by stage, assembles each stage's final text, and falls back to ordinary generation for clients without streaming support.
- Token events are stored in the existing bounded SQLite event history and flow through the existing authenticated run SSE endpoint.
- Provider error details are not copied into operational token events.

## Client behavior

Connect to `GET /v1/runs/{run_id}/events/stream` after creating a run. Token events use the SSE event name `token`; the JSON data includes the stage and content. Use the event ID as `Last-Event-ID` when reconnecting. Token chunks are stored in the bounded event table, so replay is available only while the corresponding events remain retained. The stream endpoint is a bounded polling stream and clients should reconnect if they need to continue observing a longer-running workflow.

## Safety and reliability constraints

- Stream only output belonging to the authenticated run and current stage.
- Never emit prompts, bearer tokens, environment values, internal callbacks, or file contents as stream metadata.
- Enforce chunk and event size bounds; handle malformed or incomplete provider frames safely.
- Preserve non-streaming API compatibility and existing event retention limits.
- Do not introduce external model APIs, hosted brokers, or paid services; Ollama remains the only model provider.

## Acceptance checks

- Ollama adapter can consume streamed local responses and assemble the same final text expected by non-streaming callers.
- Chunks are emitted in order and tagged with the correct run and stage.
- Provider errors, normal completion, timeout, and cancellation remain distinguishable.
- Event/SSE framing remains valid under multiple concurrent runs and reconnects.
- Slow or disconnected clients do not stall the model workflow.
- Payload bounds and authentication/run isolation are covered by tests.
- Ruff, full pytest, and the evaluation regression gate pass.

## Deferred

- Forceful interruption of in-flight Ollama requests where the transport/provider cannot safely cancel.
- Persisting complete token streams for indefinite replay.
- Distributed streaming brokers, WebSockets, browser UI, hosted telemetry, and non-Ollama providers.
