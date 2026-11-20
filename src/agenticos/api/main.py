"""FastAPI application factory and HTTP routes."""

import asyncio
import json
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agenticos.config import Settings, get_settings
from agenticos.contracts import (
    RunRequest,
    RunResponse,
    WorkspaceChangeResponse,
    WorkspaceReadResponse,
    WorkspaceStageRequest,
)
from agenticos.inference.ollama import OllamaClient
from agenticos.logging import configure_logging, get_logger
from agenticos.memory.context import build_memory_context
from agenticos.memory.repository import RepositoryIndex
from agenticos.memory.store import SQLiteMemoryStore
from agenticos.runtime.checkpoints import SQLiteCheckpointStore
from agenticos.runtime.events import SQLiteRunEventStore
from agenticos.runtime.execution import ExecutionManager, RunExecutionError
from agenticos.runtime.graph import CodingWorkflow
from agenticos.security.approval import (
    ApprovalError,
    HumanApprovalManager,
    SQLiteExecutionApprovalStore,
)
from agenticos.security.audit import SQLiteAuditLog
from agenticos.security.auth import BearerTokenAuthenticator
from agenticos.security.authorized_sandbox import AuthorizedSandboxExecutor
from agenticos.security.docker_sandbox import (
    DockerSandboxBackend,
    DockerSandboxError,
)
from agenticos.security.policy import (
    Permission,
    PermissionDenied,
    PermissionPolicy,
)
from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    sandbox_policy_from_settings,
)
from agenticos.security.workspace import WorkspaceBoundaryError, resolve_workspace_path
from agenticos.workspace import WorkspaceFileService


def create_app(settings: Settings | None = None, model_client=None) -> FastAPI:
    config = settings or get_settings()
    if config.app_env.lower() == "production" and not config.api_auth_token:
        raise ValueError("API_AUTH_TOKEN is required when APP_ENV=production")
    if config.sandbox_enabled and not all(
        (
            config.api_auth_token,
            config.sandbox_approval_token,
            config.sandbox_execution_principal,
        )
    ):
        raise ValueError(
            "Sandbox requires API_AUTH_TOKEN, SANDBOX_APPROVAL_TOKEN, "
            "and SANDBOX_EXECUTION_PRINCIPAL"
        )
    if config.sandbox_enabled and config.api_auth_token == config.sandbox_approval_token:
        raise ValueError("Sandbox approval token must differ from API_AUTH_TOKEN")
    authenticator = (
        BearerTokenAuthenticator(config.api_auth_token) if config.api_auth_token else None
    )
    configure_logging(config.log_level)
    logger = get_logger(__name__)
    model = model_client or OllamaClient(
        config.ollama_base_url, config.ollama_model, config.ollama_timeout_seconds
    )
    workflow = CodingWorkflow(model)
    run_events = SQLiteRunEventStore(config.operations_database_path)
    execution = ExecutionManager(
        workflow,
        SQLiteCheckpointStore(config.operations_database_path),
        max_concurrent_runs=config.max_concurrent_runs,
        timeout_seconds=config.run_timeout_seconds,
        event_store=run_events,
    )
    memory = SQLiteMemoryStore(config.memory_database_path)
    repository_index = RepositoryIndex(config.workspace_root, config.memory_database_path)
    workspace_files = WorkspaceFileService(config.workspace_root)
    audit_log = SQLiteAuditLog(config.operations_database_path)
    sandbox_approvals = None
    sandbox_executor = None
    approval_authenticator = None
    if config.sandbox_enabled:
        approval_authenticator = BearerTokenAuthenticator(config.sandbox_approval_token)
        sandbox_approvals = HumanApprovalManager(
            SQLiteExecutionApprovalStore(config.operations_database_path),
            allowed_approvers={config.sandbox_approver_id},
        )
        permission_policy = PermissionPolicy(
            {
                Permission(
                    config.sandbox_execution_principal,
                    "sandbox.execute",
                    "sandbox:python",
                )
            }
        )
        sandbox_executor = AuthorizedSandboxExecutor(
            DockerSandboxBackend(sandbox_policy_from_settings(config)),
            permission_policy,
            audit_log,
            sandbox_approvals,
        )

    app = FastAPI(title=config.app_name, version="0.4.0")
    app.state.settings = config
    app.state.model = model
    app.state.workflow = workflow
    app.state.execution = execution
    app.state.run_events = run_events
    app.state.memory = memory
    app.state.repository_index = repository_index
    app.state.workspace_files = workspace_files
    app.state.authenticator = authenticator
    app.state.audit_log = audit_log
    app.state.sandbox_approvals = sandbox_approvals
    app.state.sandbox_executor = sandbox_executor
    app.state.sandbox_approval_authenticator = approval_authenticator

    @app.middleware("http")
    async def authenticate_api_requests(request: Request, call_next):
        principal_id = "anonymous"
        is_human_approval_route = (
            request.url.path.startswith("/v1/sandbox/approvals/")
            and request.url.path.endswith("/approve")
        )
        if (
            request.url.path.startswith("/v1/")
            and authenticator is not None
            and not is_human_approval_route
        ):
            principal = authenticator.authenticate(request.headers.get("authorization"))
            if principal is None:
                audit_log.record(
                    principal_id, request.method, request.url.path, "denied"
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "A valid bearer token is required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.principal = principal
            principal_id = principal.principal_id
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            audit_log.record(
                principal_id, request.method, request.url.path, str(response.status_code)
            )
        return response

    @app.post("/v1/sandbox/approvals", status_code=201)
    async def request_sandbox_approval(payload: dict[str, object], request: Request):
        manager = request.app.state.sandbox_approvals
        if manager is None:
            raise HTTPException(status_code=503, detail="Sandbox approval is not configured")
        try:
            execution_request = SandboxExecutionRequest.model_validate(payload.get("request"))
            principal = getattr(request.state, "principal", None)
            if principal is None:
                raise HTTPException(status_code=401, detail="Authenticated requester required")
            approval_id = manager.request(principal.principal_id, execution_request)
        except HTTPException:
            raise
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"approval_id": approval_id, "status": "pending", "expires_in_seconds": 300}

    @app.post("/v1/sandbox/approvals/{approval_id}/approve")
    async def approve_sandbox_execution(approval_id: str, request: Request):
        manager = request.app.state.sandbox_approvals
        approval_auth = request.app.state.sandbox_approval_authenticator
        if manager is None or approval_auth is None:
            raise HTTPException(status_code=503, detail="Sandbox approval is not configured")
        principal = approval_auth.authenticate(request.headers.get("x-sandbox-approval-token"))
        if principal is None:
            raise HTTPException(status_code=401, detail="Valid human approval credential required")
        try:
            manager.approve(approval_id, config.sandbox_approver_id)
        except ApprovalError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"approval_id": approval_id, "status": "approved"}

    @app.post("/v1/sandbox/execute")
    async def execute_approved_sandbox_request(payload: dict[str, object], request: Request):
        executor = request.app.state.sandbox_executor
        if executor is None:
            raise HTTPException(status_code=503, detail="Sandbox execution is not configured")
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(status_code=401, detail="Authenticated requester required")
        approval_id = payload.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            raise HTTPException(status_code=422, detail="approval_id is required")
        try:
            execution_request = SandboxExecutionRequest.model_validate(payload.get("request"))
            result = await executor.execute(
                principal.principal_id,
                execution_request,
                approval_id=approval_id,
            )
        except (ApprovalError, PermissionDenied) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DockerSandboxError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": config.app_name}

    @app.get("/ready")
    async def readiness(request: Request) -> dict[str, str]:
        healthy = await request.app.state.model.health()
        if not healthy:
            raise HTTPException(status_code=503, detail="Local Ollama service is unavailable")
        return {"status": "ready", "provider": "ollama"}

    @app.get("/v1/me")
    async def current_principal(request: Request) -> dict[str, str]:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return {"principal_id": "local-development"}
        return {"principal_id": principal.principal_id}

    @app.post("/v1/runs", response_model=RunResponse)
    async def create_run(payload: RunRequest, request: Request) -> RunResponse:
        try:
            resolve_workspace_path(config.workspace_root, payload.workspace)
            store = request.app.state.memory
            history = store.get_recent_messages(payload.session_id)
            project_items = store.get_project_context(payload.workspace)
            repository_items = (
                request.app.state.repository_index.search(payload.workspace, payload.task)
                if payload.include_repository_context
                else []
            )
            memory_context = build_memory_context(history, project_items, repository_items)
            store.append_message(payload.session_id, "user", payload.task)
            record = await request.app.state.execution.execute(
                payload.task, memory_context=memory_context
            )
        except WorkspaceBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            logger.exception("agent_run_validation_failed")
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RunExecutionError as exc:
            logger.exception("agent_run_failed", run_id=exc.record.run_id)
            raise HTTPException(
                status_code=502,
                detail={"run_id": exc.record.run_id, "error": exc.record.error},
            ) from exc

        result = record.result or {}
        assistant_summary = str(result.get("plan", ""))
        store.append_message(payload.session_id, "assistant", assistant_summary or "Run completed.")
        return RunResponse(
            run_id=record.run_id or str(uuid4()),
            status="completed",
            plan=str(result.get("plan", "")),
            code=str(result.get("code", "")),
            review=str(result.get("review", "")),
            test_plan=str(result.get("test_plan", "")),
        )

    @app.post("/v1/runs/start", status_code=202)
    async def start_run(payload: RunRequest, request: Request) -> dict[str, str]:
        try:
            resolve_workspace_path(config.workspace_root, payload.workspace)
            store = request.app.state.memory
            history = store.get_recent_messages(payload.session_id)
            project_items = store.get_project_context(payload.workspace)
            repository_items = (
                request.app.state.repository_index.search(payload.workspace, payload.task)
                if payload.include_repository_context
                else []
            )
            memory_context = build_memory_context(history, project_items, repository_items)
            store.append_message(payload.session_id, "user", payload.task)
            run_id = request.app.state.execution.start(
                payload.task, memory_context=memory_context
            )
        except WorkspaceBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"run_id": run_id, "status": "queued"}

    @app.post("/v1/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str, request: Request) -> dict[str, str]:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if snapshot.get("status") in {"completed", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Run is already terminal")
        accepted = await request.app.state.execution.cancel_run(run_id)
        if not accepted:
            raise HTTPException(status_code=409, detail="Run is not currently cancellable")
        return {"run_id": run_id, "status": "cancellation_requested"}

    @app.get("/v1/sessions/{session_id}/messages")
    async def get_session_messages(
        session_id: str, request: Request, limit: int = 12
    ) -> list[dict[str, str]]:
        try:
            messages = request.app.state.memory.get_recent_messages(session_id, limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [
            {"role": message.role, "content": message.content, "created_at": message.created_at}
            for message in messages
        ]

    @app.put("/v1/workspaces/{workspace}/context")
    async def save_project_context(
        workspace: str, payload: dict[str, object], request: Request
    ) -> dict[str, str]:
        try:
            resolve_workspace_path(config.workspace_root, workspace)
            source_key = str(payload.get("source_key", ""))
            content = str(payload.get("content", ""))
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            request.app.state.memory.upsert_project_context(
                workspace, source_key, content, metadata
            )
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "saved", "workspace": workspace}

    @app.post("/v1/workspaces/{workspace}/repository-index")
    async def refresh_repository_index(workspace: str, request: Request) -> dict[str, int | bool]:
        try:
            return request.app.state.repository_index.refresh(workspace)
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/workspaces/{workspace}/repository-search")
    async def search_repository_index(
        workspace: str, request: Request, q: str, limit: int = 10
    ) -> list[dict[str, str]]:
        try:
            return request.app.state.repository_index.search(workspace, q, limit)
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/workspaces/{workspace}/files", response_model=list[str])
    async def list_workspace_files(workspace: str, request: Request) -> list[str]:
        try:
            return list(request.app.state.workspace_files.list_files(workspace))
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/v1/workspaces/{workspace}/files/{relative_path:path}",
        response_model=WorkspaceReadResponse,
    )
    async def read_workspace_file(
        workspace: str, relative_path: str, request: Request
    ) -> WorkspaceReadResponse:
        try:
            content = request.app.state.workspace_files.read_text(workspace, relative_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return WorkspaceReadResponse(
            workspace=workspace, relative_path=relative_path, content=content
        )

    @app.post(
        "/v1/workspaces/{workspace}/changes",
        response_model=WorkspaceChangeResponse,
        status_code=202,
    )
    async def stage_workspace_change(
        workspace: str, payload: WorkspaceStageRequest, request: Request
    ) -> WorkspaceChangeResponse:
        try:
            change = request.app.state.workspace_files.stage_write(
                workspace, payload.relative_path, payload.content
            )
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return WorkspaceChangeResponse(
            change_id=change.change_id,
            workspace=change.workspace,
            relative_path=change.relative_path,
            size_bytes=change.size_bytes,
        )

    @app.get(
        "/v1/workspaces/{workspace}/changes",
        response_model=list[WorkspaceChangeResponse],
    )
    async def list_workspace_changes(
        workspace: str, request: Request
    ) -> list[WorkspaceChangeResponse]:
        try:
            changes = [
                change
                for change in request.app.state.workspace_files.pending_changes()
                if change.workspace == workspace
            ]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [
            WorkspaceChangeResponse(
                change_id=change.change_id,
                workspace=change.workspace,
                relative_path=change.relative_path,
                size_bytes=change.size_bytes,
            )
            for change in changes
        ]

    @app.post("/v1/workspaces/{workspace}/changes/{change_id}/approve")
    async def approve_workspace_change(
        workspace: str, change_id: str, request: Request
    ) -> dict[str, str]:
        service = request.app.state.workspace_files
        change = next(
            (
                item
                for item in service.pending_changes()
                if item.change_id == change_id and item.workspace == workspace
            ),
            None,
        )
        if change is None:
            raise HTTPException(status_code=404, detail="Staged change not found")
        try:
            written_path = service.approve(change_id)
        except (WorkspaceBoundaryError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        relative_path = written_path.relative_to(config.workspace_root.resolve()).as_posix()
        return {"status": "approved", "path": relative_path}

    @app.delete("/v1/workspaces/{workspace}/changes/{change_id}")
    async def reject_workspace_change(
        workspace: str, change_id: str, request: Request
    ) -> dict[str, str]:
        service = request.app.state.workspace_files
        change = next(
            (
                item
                for item in service.pending_changes()
                if item.change_id == change_id and item.workspace == workspace
            ),
            None,
        )
        if change is None:
            raise HTTPException(status_code=404, detail="Staged change not found")
        service.reject(change_id)
        return {"status": "rejected"}

    @app.get("/v1/runs/{run_id}/events")
    async def get_run_events(
        run_id: str, request: Request, after_event_id: int = 0, limit: int = 100
    ) -> list[dict[str, object]]:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            events = request.app.state.run_events.list_events(
                run_id, after_event_id=after_event_id, limit=limit
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [
            {
                "event_id": event.event_id,
                "run_id": event.run_id,
                "event_type": event.event_type,
                "created_at": event.created_at,
                "data": event.data,
            }
            for event in events
        ]

    @app.get("/v1/runs/{run_id}/events/stream")
    async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            after_id = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc

        async def event_stream():
            cursor = after_id
            for _ in range(60):
                events = request.app.state.run_events.list_events(
                    run_id, after_event_id=cursor, limit=100
                )
                for event in events:
                    payload = json.dumps(
                        {
                            "run_id": event.run_id,
                            "event_type": event.event_type,
                            "created_at": event.created_at,
                            "data": event.data,
                        },
                        separators=(",", ":"),
                    )
                    yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
                    cursor = event.event_id
                current = await request.app.state.execution.get_snapshot(run_id)
                if current and current.get("status") in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, object]:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return snapshot

    return app


app = create_app()
