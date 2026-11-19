# Phase 9 — Durable Operations and Audit Trail

## Goal

Make run checkpoints and security audit events survive process restarts using the existing local SQLite approach, without introducing external services or changing the local-only Ollama inference boundary.

## Scope

- Add a SQLite-backed implementation of the existing `CheckpointStore` protocol.
- Preserve the in-memory checkpoint store for focused unit tests and ephemeral use.
- Persist complete run snapshots with safe serialization and deterministic upsert semantics.
- Add a SQLite-backed audit event store with append-only records and bounded, ordered reads.
- Wire durable stores into the application factory using explicit configuration paths.
- Keep audit records free of bearer tokens, request secrets, and generated source contents.
- Add restart/persistence, ordering, malformed-input, and API integration tests.
- Document backup, local file permissions, retention, and operational limitations.

## Security and reliability constraints

- Use parameterized SQL for all queries.
- Create parent directories safely and initialize schemas idempotently.
- Do not log or expose database contents or credentials on errors.
- Store only operational metadata in audit events; never store authorization headers.
- Do not claim SQLite provides multi-host coordination or tamper-proof audit storage.
- Existing authentication remains the boundary for protected API access.
- No external database, telemetry SaaS, shell execution, or model-provider fallback.

## Acceptance checks

- Run snapshots remain retrievable after reopening the SQLite store.
- Snapshot updates replace the previous snapshot for the same run ID.
- Audit events remain ordered and retrievable after reopening the store.
- Read limits are validated and bounded.
- Existing in-memory behavior and all prior phase tests remain green.
- Ruff, complete pytest suite, and evaluation regression gate pass.

## Deferred

Multi-process distributed locking, encrypted-at-rest storage, tamper-evident audit chains, automatic retention jobs, multi-user authorization, and production-grade backup orchestration.
