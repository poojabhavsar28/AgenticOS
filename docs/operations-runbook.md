# AgenticOS Operations Runbook

## 1. Supported operating model

The current implementation is a local-first Python application with:
- FastAPI/Uvicorn application process
- Local Ollama inference service
- SQLite persistence files
- Optional Docker daemon and digest-pinned image for sandbox execution

This is not a multi-node or high-availability deployment guide. Use a dedicated service account and private application data directory.

## 2. Prerequisites

- Python 3.11 or newer
- Ollama installed and running
- The configured coding model pulled into Ollama (default: `qwen2.5-coder:3b`)
- Docker only if sandbox execution is explicitly enabled
- A private data directory with appropriate POSIX permissions or Windows ACLs

## 3. First-time setup

```bash
git clone https://github.com/poojabhavsar28/AgenticOS.git
cd AgenticOS
python -m venv .venv
```

Activate the environment:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install the project and development tools:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
ollama pull qwen2.5-coder:3b
```

Copy `.env.example` to `.env` and set secrets before starting. Never commit `.env`.

## 4. Configuration reference

| Variable | Purpose | Example/default |
|---|---|---|
| `APP_NAME` | Application name | `AgenticOS` |
| `APP_ENV` | Environment mode | `development` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `OLLAMA_BASE_URL` | Local Ollama endpoint | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model name | `qwen2.5-coder:3b` |
| `OLLAMA_TIMEOUT_SECONDS` | Model request timeout | `120` |
| `RUN_TIMEOUT_SECONDS` | Maximum workflow run duration | `300` |
| `MAX_CONCURRENT_RUNS` | In-process concurrency limit | `2` |
| `WORKSPACE_ROOT` | Allowed workspace root | `./workspace` |
| `MEMORY_DATABASE_PATH` | Conversation/project memory DB | `./.agenticos/memory.sqlite3` |
| `OPERATIONS_DATABASE_PATH` | Operations/identity/audit DB | `./.agenticos/operations.sqlite3` |
| `API_AUTH_TOKEN` | Operator bootstrap bearer token | Must be a unique secret |
| `IDENTITY_ADMIN_TOKEN` | Identity administrator bearer token | Empty disables admin routes |
| `IDENTITY_ADMIN_PRINCIPAL` | Bootstrap admin principal ID | `local-admin` |

The sandbox policy has additional settings in the typed configuration model. Inspect the deployed version's `.env.example` and settings class before enabling it; do not guess image references or resource limits.

## 5. Start and verify

Start the API:

```bash
uvicorn agenticos.api.main:app --host 127.0.0.1 --port 8000
```

For local development with reload:

```bash
uvicorn agenticos.api.main:app --reload
```

Verify:
- `GET /health` responds.
- `GET /ready` reports readiness.
- Ollama is reachable and the configured model is available.
- The configured workspace root exists and is accessible.
- SQLite files are created under the expected private data directory.

The application exposes OpenAPI at `/openapi.json` and interactive docs at `/docs` unless disabled by the deployment configuration.

## 6. POSIX data-directory permissions

Use a dedicated directory owned by the service account:

```bash
sudo install -d -m 0700 -o agenticos -g agenticos /var/lib/agenticos
sudo chmod 0700 /var/lib/agenticos
```

The application hardens SQLite database and sidecar files to mode `0600` where supported. Custom parent directories that are too permissive or owned by an unexpected account are rejected. Do not put the database in a shared temporary directory.

## 7. Windows data-directory ACLs

Run PowerShell as an administrator and replace the service identity with the actual account:

```powershell
New-Item -ItemType Directory -Force C:\ProgramData\AgenticOS
icacls C:\ProgramData\AgenticOS /inheritance:r
icacls C:\ProgramData\AgenticOS /grant:r "NT SERVICE\AgenticOS:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
icacls C:\ProgramData\AgenticOS
```

Python POSIX mode bits do not establish an NTFS security boundary. Confirm the resulting ACL and service-account access on the actual host.

## 8. Sandbox enablement procedure

Do not enable sandbox execution by default. Before enabling:
1. Complete a security review of the Docker daemon and host.
2. Build or obtain a minimal approved image and review its provenance.
3. Pin the image using a full SHA-256 digest.
4. Preload the image on the host; the runtime intentionally does not pull.
5. Configure administrator-owned resource ceilings.
6. Configure separate requester/operator and human reviewer credentials.
7. Verify the sandbox approval workflow end-to-end.
8. Confirm that execution remains unavailable when the image, daemon, policy, or authorization is missing.
9. Run the real Docker integration suite against the exact image digest.
10. Document the supported host OS/runtime combination.

The Docker daemon and host kernel remain trusted. Do not expose the Docker socket to untrusted users or mount host credentials/workspaces into the sandbox.

## 9. Routine operations

### Rotate a managed principal token
Use the identity-admin token to call the token rotation endpoint. The replacement secret is returned once; store it in a secret manager and update the consuming client immediately. Verify the old token is rejected.

### Disable a principal
Use the admin principal endpoint to disable it. Confirm that authentication fails and existing run/session/workspace access is denied.

### Grant or revoke workspace access
Use the exact workspace/action/resource grant endpoints. Test both allowed and denied requests. Avoid broad wildcard grants unless the policy explicitly supports and reviews them.

### Verify audit integrity
Call `GET /v1/admin/audit/verify`. Retain the returned chain head in a trusted system outside the AgenticOS host/database. On the next verification, provide that value as `expected_head`. A chain mismatch returns a conflict and should trigger incident investigation.

### Backups and restore drills

AgenticOS provides `backup_sqlite_database(source, destination)` and `restore_sqlite_database(backup, destination)` in `agenticos.security.backup`. These helpers use SQLite's online backup API, run `PRAGMA integrity_check`, write to a temporary file, and atomically replace the destination. On POSIX, backup files are created with owner-only permissions.

Example for one configured SQLite database:

```python
from agenticos.security.backup import backup_sqlite_database, restore_sqlite_database

backup_sqlite_database(
    ".agenticos/operations.sqlite3",
    "/secure-backups/operations-2026-11-22.sqlite3",
)
restore_sqlite_database(
    "/secure-backups/operations-2026-11-22.sqlite3",
    "/recovery/operations.sqlite3",
)
```

Repeat for every configured database, including memory and operations/checkpoint state. Coordinate the backup window with a quiesced application or a documented snapshot procedure when consistency across multiple databases matters: each SQLite backup is consistent individually, but separate database files are not captured as one cross-database transaction.

Back up the audit signing key separately using encrypted storage and stricter access controls. Preserve the external audit chain-head checkpoint alongside the backup metadata, but outside the application host and database. A database-only restore without the matching audit key and trusted checkpoint cannot provide full audit-integrity verification. Do not overwrite the live database during recovery; restore to a new path, validate it, then switch configuration during a controlled maintenance window.

Run scheduled restore drills. Record backup age, restore duration, integrity-check results, and recovery-point/recovery-time objectives. These helpers do not implement scheduling, encryption, off-site replication, or automated key/checkpoint backup.

## 10. Troubleshooting

| Symptom | Checks |
|---|---|
| API cannot start | Validate Python environment, settings, filesystem permissions, and port availability |
| `/ready` fails | Check Ollama endpoint/model and required local stores |
| Model request times out | Check Ollama process, model availability, machine resources, and configured timeout |
| Run remains active | Inspect run status/events, concurrency limit, timeout, and cancellation behavior |
| 401 response | Check Authorization header, token validity, token rotation, principal enabled state |
| 403 response | Check principal/workspace/action/resource grant and run/session ownership |
| Workspace path rejected | Confirm resolved path remains under configured workspace root |
| Sandbox disabled | Check explicit enablement, approved digest, local image availability, and policy settings |
| Sandbox request denied | Check requester grant, reviewer separation, request expiry, and one-time approval state |
| Audit verification fails | Preserve DB/key/checkpoint; do not rewrite the chain; investigate sequence, digest, key, and external head mismatch |
| Docker cleanup fails | Inspect daemon health and invocation-labelled containers; do not manually delete unrelated containers |

## 11. Shutdown and recovery

Stop the Uvicorn process gracefully. Do not delete SQLite files while the application is running. On restart, run snapshots, event history, identity data, grants, and audit records are loaded from configured stores. SSE clients should reconnect with their last event ID. Confirm readiness and inspect recent run outcomes after recovery.

## 12. Production-readiness follow-ups

- Independent secret-manager/KMS storage for the audit key.
- Automated key rotation and documented re-signing/versioning strategy.
- Automated external audit chain-head checkpointing and alerting.
- Scheduled, tested encrypted backups and restore drills.
- Operator-facing audit verification tooling.
- Deployment-specific TLS/reverse-proxy and rate-limiting guidance.
- Host-level monitoring and resource isolation.
- Independent security assessment before accepting hostile public workloads.


## 13. API load probe

An opt-in bounded HTTP probe is available at `scripts/benchmark_api.py`. It reports request throughput, success/failure counts, and mean/p50/p95/p99/max latency. It does not measure host CPU or memory, and it does not establish a production capacity guarantee.

Start AgenticOS locally, then run a low-impact health probe:

```bash
python scripts/benchmark_api.py --mode health --requests 30 --concurrency 5
```

For an authorized local run-workflow probe:

```bash
python scripts/benchmark_api.py --mode run --requests 10 --concurrency 2
```

Set `AGENTICOS_BENCHMARK_TOKEN` when the target requires a bearer token. The script defaults to loopback targets, limits concurrency to 100 and requests to 10,000, and requires `--allow-remote` for non-local hosts. Run progressively (for example 10, 25, 50, then 100 concurrent requests) only after reviewing host capacity. Use representative tasks and a dedicated test workspace; avoid production workloads. Record hardware, model, configuration, dataset, warm-up, and exact commit alongside results. Capture CPU and memory with host monitoring separately.

The script has been added as a measurement harness; no throughput or latency numbers should be claimed until it has been run against a real, configured AgenticOS instance.
