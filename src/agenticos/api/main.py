"""FastAPI application factory and HTTP routes."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from agenticos.config import Settings, get_settings
from agenticos.contracts import RunRequest, RunResponse
from agenticos.inference.ollama import OllamaClient
from agenticos.logging import configure_logging, get_logger
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

    app = FastAPI(title=config.app_name, version="0.2.0")
    app.state.settings = config
    app.state.model = model
    app.state.workflow = workflow
    app.state.execution = execution

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
            record = await request.app.state.execution.execute(payload.task)
        except WorkspaceBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RunExecutionError as exc:
            logger.exception("agent_run_failed", run_id=exc.record.run_id)
            raise HTTPException(
                status_code=502,
                detail={"run_id": exc.record.run_id, "error": exc.record.error},
            ) from exc

        result = record.result or {}
        return RunResponse(
            run_id=record.run_id or str(uuid4()),
            status="completed",
            plan=str(result.get("plan", "")),
            code=str(result.get("code", "")),
            review=str(result.get("review", "")),
            test_plan=str(result.get("test_plan", "")),
        )

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, object]:
        snapshot = await request.app.state.execution.get_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return snapshot

    return app


app = create_app()
