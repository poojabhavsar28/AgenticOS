"""FastAPI application factory and HTTP routes."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from agenticos.config import Settings, get_settings
from agenticos.contracts import RunRequest, RunResponse
from agenticos.inference.ollama import OllamaClient
from agenticos.logging import configure_logging, get_logger
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

    app = FastAPI(title=config.app_name, version="0.1.0")
    app.state.settings = config
    app.state.model = model
    app.state.workflow = workflow

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
            result = await request.app.state.workflow.run(payload.task)
        except WorkspaceBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("agent_run_failed", workspace=payload.workspace)
            raise HTTPException(status_code=502, detail="Agent workflow failed") from exc

        return RunResponse(
            run_id=str(uuid4()),
            status="completed",
            plan=result.get("plan", ""),
            code=result.get("code", ""),
            review=result.get("review", ""),
            test_plan=result.get("test_plan", ""),
        )

    return app


app = create_app()
