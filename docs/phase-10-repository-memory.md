# Phase 10 — Repository Indexing and Searchable Memory

## Goal

Upgrade explicit workspace notes into useful repository-aware context while preserving the local-first, SQLite-only architecture and safe workspace boundaries.

## Scope

- Add a bounded repository indexer for text files beneath the configured workspace root.
- Reuse workspace path resolution and reject traversal or symlink escapes.
- Skip hidden directories, virtual environments, VCS metadata, caches, dependency folders, binary files, and oversized files.
- Store indexed file metadata and content in SQLite FTS5 when available, with deterministic local keyword search.
- Support explicit index refresh and workspace-scoped search endpoints.
- Return source paths and bounded excerpts; never execute or modify indexed files.
- Add opt-in retrieval to run context, combining search results with explicit project notes and recent conversation history.
- Treat all retrieved repository text as untrusted reference material in prompts.
- Add tests for path isolation, ignore rules, binary/size limits, refresh behavior, ranking, workspace isolation, and prompt budget limits.
- Document index freshness, exclusions, local storage, and operational limits.

## Safety and reliability constraints

- No network calls, external embedding APIs, hosted vector stores, shell commands, or generated-code execution.
- Index only files within the selected workspace and enforce strict file-count, per-file, and total-content budgets.
- Use parameterized SQL and FTS query escaping; malformed search input must fail safely.
- Do not expose absolute filesystem paths through API responses.
- No automatic write-back or patch application.

## Acceptance checks

- Indexing and search stay within the selected workspace.
- Re-indexing updates changed/deleted files without duplicate rows.
- Search results are bounded, relevant, and include relative source paths.
- Existing conversation/project memory behavior remains intact.
- Retrieved context respects the configured prompt budget and is marked untrusted.
- Ruff, full pytest, and evaluation regression gate pass.

## Deferred

Semantic embeddings/vector databases, incremental filesystem watchers, language-aware AST chunking, cross-workspace search, automatic code execution, and background indexing jobs.
