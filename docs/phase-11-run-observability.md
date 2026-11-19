# Phase 11 — Run Observability and Progress Streaming

## Goal

Make long-running agent workflows observable to local clients without changing the execution model or introducing external services.

## Scope

- Define a typed run event contract with run ID, event type, timestamp, and bounded structured data.
- Emit lifecycle events for queued, started, completed, failed, and cancelled runs. Workflow stage-level model progress is deferred until the graph exposes a concurrency-safe progress callback.
- Persist a bounded event history in the existing local SQLite operations database.
- Expose a run-scoped event history endpoint and Server-Sent Events (SSE) stream.
- Ensure event reads are scoped to the requested run and authenticated consistently with existing API policy.
- Avoid logging prompts, model outputs, bearer tokens, or sensitive file contents in operational event metadata.
- Add deterministic tests for event ordering, persistence across app restarts, bounded reads, run isolation, and SSE framing.
- Document client reconnection using event IDs and the limits of the local single-process event stream.

## Safety and reliability constraints

- No external telemetry, hosted observability service, or network calls beyond the local API.
- Event payloads contain operational metadata only, with strict size bounds.
- SQLite remains the durable source of event history; live notifications are best-effort.
- A disconnected SSE client must not block or fail the agent run.
- Existing run status and evaluation behavior must remain backward compatible.

## Acceptance checks

- Run lifecycle and stage events are recorded in deterministic order.
- Event history survives application restart and is isolated by run ID.
- Event payloads contain status metadata only; prompts, model outputs, and file contents are excluded.
- SSE emits correctly framed events and supports reconnecting from a last event ID.
- Event retention and response limits are enforced.
- Ruff, full pytest, and evaluation regression gate pass.

## Deferred

Stage-level model progress, distributed event brokers, multi-process pub/sub, OpenTelemetry exporters, dashboards, metrics aggregation, and user-specific event subscriptions.
