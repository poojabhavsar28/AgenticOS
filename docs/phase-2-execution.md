# Phase 2 — Agent Execution Engine

## Scope

Phase 2 introduces a bounded execution lifecycle around the Phase 1 coding workflow:

- Run identifiers and explicit queued, running, completed, failed, and cancelled states.
- A configurable concurrency limit and per-run timeout.
- Checkpoint storage contract with a process-local implementation.
- Explicit tool interface and registry; tools are unavailable unless registered.
- Sanitized failure details at the execution boundary.

## Current boundaries

The in-memory checkpoint implementation is lost when the process exits. It is an interface seam for durable storage in a later phase, not a persistent run history. The tool registry does not execute shell commands and no tools are registered by default. Generated code remains text and is not applied or executed. Cancellation is recorded and then propagated to the caller.

## Acceptance checks

- Successful runs reach completed and persist a final snapshot.
- Workflow failures and timeouts reach failed with sanitized error messages.
- Concurrency is bounded by the manager semaphore.
- Checkpoint reads and writes do not leak mutable internal state.
- Unregistered tools cannot be resolved.
