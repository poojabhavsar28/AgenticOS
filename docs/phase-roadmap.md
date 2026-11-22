# AgenticOS Phase History and Release Plan

## 1. Phase history

This list summarizes the delivered scope at a capability level. Each phase's detailed implementation record is maintained in its corresponding `docs/phase-*.md` file where available.

| Phase | Capability area | Main result |
|---|---|---|
| 1 | Foundation | Local-first FastAPI application, configuration, Ollama adapter, four-role coding workflow, workspace boundary |
| 2 | Execution | Bounded workflow execution and run lifecycle foundation |
| 3 | Memory | Persistent conversation/project memory |
| 4 | Collaboration | Agent directory, task coordination, dependencies, bounded message bus |
| 5 | Workspace operations | Bounded file access and staged, approved changes |
| 6 | Evaluation | Deterministic evaluation cases, scoring, aggregate regression gate |
| 7 | Security | Explicit tool registration and security/policy foundations |
| 8 | Identity and authentication | Bearer authentication and identity foundations |
| 9 | Durable operations | Persistent checkpoints and API/run operational history |
| 10 | Repository memory | Bounded local repository indexing and opt-in retrieval context |
| 11 | Run observability | Durable lifecycle events and run status visibility |
| 12 | Agent progress | Stage-level progress reporting and cancellation integration |
| 13 | Token streaming | Bounded model token chunks and resumable run-scoped SSE events |
| 14 | Sandboxed execution | Opt-in hardened Docker execution, human approval, exact-request binding, fail-closed behavior |
| 15 | Identity and audit hardening | Persistent principals/tokens/grants, ownership isolation, audit HMAC chain, storage hardening, approval queue hardening |
| 16 | Integration and release readiness | Integrate Phases 1–15, validate the full system, finish docs, and prepare a reviewed release candidate |

Phase 16 is not another product-feature phase. It is the final integration and release-readiness phase.

## 2. Phase 16 objectives

1. Create/use an integration branch from the accepted Phase 15 snapshot.
2. Verify that the integrated branch contains the intended cumulative Phase 1–15 implementation.
3. Run full quality, evaluation, and Docker integration CI against the exact integration commit.
4. Fix integration regressions and documentation drift.
5. Verify clean-checkout setup, configuration, API OpenAPI output, and runbook procedures.
6. Review the security model and explicitly disposition residual risks.
7. Prepare a release candidate and a pull request for review.
8. Merge to `main` only after the owner explicitly approves.

## 3. Release gates

| Gate | Required evidence |
|---|---|
| Source integration | Compare and inspect integrated branch; no unreviewed history loss |
| Quality | Ruff and full pytest pass on exact SHA |
| Evaluation | Evaluation regression gate passes |
| Sandbox | Real Docker integration job passes when configured; skipped status is reported honestly |
| Security | Identity, grant, ownership, approval, audit, storage, and container checks reviewed |
| Documentation | Architecture, API, security, operations, testing, and README match final code |
| Release | Version/tag/changelog and deployment plan reviewed |
| Approval | Explicit owner approval before merging into `main` |

## 4. Current baseline

Phase 15 branch: `feature/phase-15-identity-audit-hardening`  
Phase 15 commit: `8ed8dd7c4556b2300b7af40c3c6ea5832bbbdb4b`  
Recorded CI run: [#45029592782](https://github.com/poojabhavsar28/AgenticOS/actions/runs/45029592782)

The documentation branch is based on that verified Phase 15 commit. The final integration branch and commit must be recorded here after Phase 16 integration. Do not copy Phase 15 CI status forward as if it validates the integration branch.
