# AgenticOS Testing and CI

## 1. Test strategy

The repository uses pytest for unit, API, integration, security-regression, and evaluation tests, with Ruff for linting. The CI workflow separates Docker-independent quality checks from optional real-container verification.

The Phase 15 branch's recorded successful run is GitHub Actions run [#45029592782](https://github.com/poojabhavsar28/AgenticOS/actions/runs/45029592782), on commit `8ed8dd7c4556b2300b7af40c3c6ea5832bbbdb4b`. Its quality and Docker sandbox integration jobs passed. The run recorded 219 passed and 3 skipped in the main suite, 8 evaluation tests passed, and 3 Docker integration tests passed. This is a branch-specific CI record, not a guarantee that a later commit or integrated branch passes.

## 2. Local commands

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Lint:

```bash
ruff check .
```

Full test suite:

```bash
pytest -q
```

Evaluation regression suite:

```bash
pytest -q tests/test_evaluation.py
```

The real Docker tests require an available Docker daemon, an approved local digest-pinned image, and the explicit integration environment flag. Do not assume they can run on every developer machine.

## 3. CI workflow

The current `.github/workflows/ci.yml` defines:

### Quality job
1. Checkout repository.
2. Set up Python 3.11.
3. Install `.[dev]`.
4. Run `ruff check .`.
5. Run `pytest -q`.
6. Run the evaluation regression gate separately.

### Docker sandbox integration job
Runs only when repository variable `AGENTICOS_TEST_SANDBOX_IMAGE` is non-empty:
1. Checkout repository and set up Python 3.11.
2. Install project and development dependencies.
3. Verify Docker daemon.
4. Preload the administrator-approved digest-pinned image.
5. Set `AGENTICOS_DOCKER_INTEGRATION=1`.
6. Run `pytest -q tests/test_docker_sandbox_integration.py`.

The sandbox backend itself does not pull images. The CI workflow preloads the approved image as an explicit test setup step.

## 4. Test coverage map

| Area | Representative test files |
|---|---|
| API routes and run lifecycle | `test_api.py`, `test_execution.py` |
| Authentication and identity | `test_auth.py`, `test_identity_store.py`, `test_identity_api.py` |
| Authorization and workspace isolation | `test_tool_permissions.py`, `test_workspace_api.py`, `test_workspace_security.py` |
| Agent graph and collaboration | `test_graph.py`, `test_collaboration.py`, `test_collaboration_bus.py` |
| Memory and repository index | `test_memory_store.py`, `test_memory_context.py`, `test_repository_memory.py` |
| Run persistence and observability | `test_checkpoints.py`, `test_run_events.py` |
| Streaming | `test_graph_streaming.py`, `test_execution_streaming.py`, `test_ollama_streaming.py` |
| Workspace operations | `test_workspace_files.py` |
| Sandbox policy and approval | `test_sandbox_contracts.py`, `test_sandbox_approval.py`, `test_sandbox_api.py`, `test_authorized_sandbox.py` |
| Docker isolation and lifecycle | `test_docker_sandbox.py`, `test_sandbox_lifecycle.py`, `test_docker_sandbox_integration.py` |
| Audit integrity | `test_security_audit.py` |
| Evaluation | `test_evaluation.py` |

## 5. Integration acceptance checklist

- [ ] Ruff passes on the exact candidate commit.
- [ ] Full pytest suite passes on the exact candidate commit.
- [ ] Evaluation regression gate passes.
- [ ] Docker integration job passes when sandbox is configured.
- [ ] Run create/start/status/cancel and event resume work together.
- [ ] Session and run ownership isolation work across principals.
- [ ] Workspace grants are enforced at API and tool boundaries.
- [ ] Token issue/rotate/revoke/expiry and disabled-principal behavior pass.
- [ ] Sandbox requester/reviewer separation and one-time exact-request approval pass.
- [ ] Docker cleanup works on success, error, timeout, and cancellation.
- [ ] Audit chain mutation/reordering and external checkpoint mismatch are detected.
- [ ] Clean-checkout setup and operator documentation are verified.

## 6. CI interpretation rules

- A skipped Docker job is not a passing Docker integration test.
- A passing phase branch does not prove the final integrated branch passes.
- A CI result must be tied to the exact commit SHA being accepted.
- Re-run or inspect both quality and Docker jobs after documentation/code changes if CI is expected to validate the changed commit.
- Do not describe a branch as release-ready until the final integrated candidate has its own green checks and required review.
