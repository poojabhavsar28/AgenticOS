"""FastAPI application factory and HTTP routes."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from agenticos.config import Settings, get_settings
from agenticos.contracts import RunRequest, RunResponse
from agenticos.inference.ollama import OllamaClient
from agenticos.logging import configure_logging, get_logger
from agenticos.memory.context import build_memory_context
from agenticos.memory.store import SQLiteMemoryStore
from agenticos.runtime.checkpoints import InMemoryCheckpointStore
from agenticos.runtime.execution import ExecutionManager, RunExecutionError
from agenticos.runtime.graph import CodingWorkflow
from agenticos.security.workspace import WorkspaceBoundaryError, resolve_workspace_path


def create_app(settings: Settings | None = None, model_client=None) -> FastAPI:
    config = settings or get_settings()
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

    app = FastAPI(title=config.app_name, version="0.3.0")
    app.state.settings = config
    app.state.model = model
    app.state.workflow = workflow
    app.state.execution = execution
    app.state.memory = memory

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": config.app_name}

    @app.get("/ready")
    async def readiness(request: Request) -> dict[str, str]:
        healthy = await request.app.state.model.health()
        if not healthy:
            raise HTTPException(status_code=503, detail="Local Ollama service is unavailable")
        return {"status": "ready", "provider": "ollama"}

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

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, object]:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return snapshot

    return app


app = create_app()
