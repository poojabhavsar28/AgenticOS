"""FastAPI application factory and HTTP routes."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
from agenticos.memory.store import SQLiteMemoryStore
from agenticos.runtime.checkpoints import InMemoryCheckpointStore
from agenticos.runtime.execution import ExecutionManager, RunExecutionError
from agenticos.runtime.graph import CodingWorkflow
from agenticos.security.auth import BearerTokenAuthenticator
from agenticos.security.workspace import WorkspaceBoundaryError, resolve_workspace_path
from agenticos.workspace import WorkspaceFileService


def create_app(settings: Settings | None = None, model_client=None) -> FastAPI:
    config = settings or get_settings()
    if config.app_env.lower() == "production" and not config.api_auth_token:
        raise ValueError("API_AUTH_TOKEN is required when APP_ENV=production")
    authenticator = (
        BearerTokenAuthenticator(config.api_auth_token) if config.api_auth_token else None
    )
    configure_logging(config.log_level)
    logger = get_logger(__name__)
    model = model_client or OllamaClient(
        config.ollama_base_url, config.ollama_model, config.ollama_timeout_seconds
    )
    workflow = CodingWorkflow(model)
    execution = ExecutionManager(
        workflow,
        InMemoryCheckpointStore(),
        max_concurrent_runs=config.max_concurrent_runs,
        timeout_seconds=config.run_timeout_seconds,
    )
    memory = SQLiteMemoryStore(config.memory_database_path)
    workspace_files = WorkspaceFileService(config.workspace_root)

    app = FastAPI(title=config.app_name, version="0.4.0")
    app.state.settings = config
    app.state.model = model
    app.state.workflow = workflow
    app.state.execution = execution
    app.state.memory = memory
    app.state.workspace_files = workspace_files
    app.state.authenticator = authenticator

    @app.middleware("http")
    async def authenticate_api_requests(request: Request, call_next):
        if request.url.path.startswith("/v1/") and authenticator is not None:
            principal = authenticator.authenticate(request.headers.get("authorization"))
            if principal is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "A valid bearer token is required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.principal = principal
        response = await call_next(request)
        return response

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
            memory_context = build_memory_context(history, project_items)
            store.append_message(payload.session_id, "user", payload.task)
            record = await request.app.state.execution.execute(
                payload.task, memory_context=memory_context
            )
        except WorkspaceBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
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

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, object]:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return snapshot

    return app


app = create_app()
