"""FastAPI application factory and HTTP routes."""

# ruff: noqa: E501, I001  # Embedded HTML/CSS/JS is intentionally kept as one template.

import asyncio
import json
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

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
from agenticos.runtime.tools import ToolRegistry
from agenticos.runtime.sandbox_tools import (
    ExecuteApprovedCodeTool,
    RequestCodeExecutionApprovalTool,
)
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
from agenticos.security.sqlite_storage import prepare_private_sqlite_database
from agenticos.security.sandbox import (
    SandboxExecutionRequest,
    sandbox_policy_from_settings,
)
from agenticos.security.workspace import WorkspaceBoundaryError, resolve_workspace_path
from agenticos.workspace import WorkspaceFileService


SANDBOX_REVIEW_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgenticOS · Sandbox approvals</title><style>
:root{color-scheme:dark;--bg:#090b10;--panel:#11151e;--line:#283142;--muted:#9ba8bb;--text:#edf2fa;--accent:#9ac2ff;--danger:#ffb4a9}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#18243a 0,#090b10 52%);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:1120px;margin:auto;padding:36px 22px 70px}.eyebrow{color:var(--accent);font-size:12px;letter-spacing:.16em;text-transform:uppercase}
h1{font-size:30px;letter-spacing:-.04em;margin:8px 0 4px}.sub,.muted{color:var(--muted)}.layout{display:grid;grid-template-columns:330px minmax(0,1fr);gap:18px;margin-top:24px}
.panel{background:rgba(17,21,30,.94);border:1px solid var(--line);border-radius:16px;padding:18px;min-width:0}
label{display:block;color:var(--muted);font-size:12px;margin:12px 0 6px}input{width:100%;background:#090d14;border:1px solid var(--line);border-radius:9px;padding:11px;color:var(--text)}
button{border:1px solid #49658d;background:#1d3554;color:#f4f8ff;border-radius:9px;padding:10px 14px;font-weight:650;cursor:pointer}button:disabled{opacity:.4;cursor:not-allowed}
.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.queue{margin-top:16px;display:grid;gap:8px}
.item{width:100%;text-align:left;background:#0c111a;border:1px solid var(--line);padding:12px;border-radius:10px}.item.active{border-color:var(--accent)}
.item strong{display:block;overflow-wrap:anywhere}.item small{color:var(--muted)}.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:16px 0}
.meta div{background:#0b1018;border:1px solid var(--line);border-radius:9px;padding:10px;min-width:0}.meta small{display:block;color:var(--muted);font-size:11px}.meta span{overflow-wrap:anywhere}
pre{white-space:pre;overflow:auto;max-height:460px;background:#080c12;border:1px solid var(--line);border-radius:10px;padding:16px;font:13px/1.55 ui-monospace,monospace}
.notice{border-left:3px solid #d6a95c;background:#241d10;padding:11px 13px;color:#f4dba9;border-radius:5px;margin:14px 0}
.ack{display:flex;gap:10px;align-items:flex-start;color:var(--muted);margin:16px 0}.ack input{width:auto;margin-top:4px}
.status{min-height:24px;color:var(--muted);margin-top:10px}.status.error{color:var(--danger)}.hidden{display:none}
@media(max-width:760px){.layout{grid-template-columns:1fr}main{padding:24px 14px}}
</style></head><body><main>
<div class="eyebrow">AgenticOS · Security boundary</div><h1>Sandbox execution review</h1>
<p class="sub">Inspect the exact submitted Python code and resource limits before authorizing a one-time execution.</p>
<div class="layout"><section class="panel">
<h2 style="font-size:17px;margin:0">Reviewer access</h2><label for="token">Human approval bearer token</label>
<input id="token" type="password" autocomplete="off" placeholder="Paste reviewer credential">
<div class="row" style="margin-top:10px"><button id="connect">Load pending reviews</button><button id="refresh" disabled>Refresh</button></div>
<p class="muted" style="font-size:12px">Credential stays in this page's memory only. It is not saved to local storage.</p><div id="queue" class="queue"></div>
</section><section class="panel">
<div class="row" style="justify-content:space-between"><h2 style="font-size:17px;margin:0">Execution details</h2><span id="state" class="muted">Select a pending request</span></div>
<div id="empty" class="muted" style="padding:54px 8px;text-align:center">Choose a request from the review queue.</div>
<div id="details" class="hidden"><div class="meta">
<div><small>Requester</small><span id="requester"></span></div><div><small>Approval ID</small><span id="approval"></span></div>
<div><small>Expires</small><span id="expiry"></span></div><div><small>Request SHA-256</small><span id="hash"></span></div></div>
<div class="notice">Review the complete source and limits. Approval is tied to this exact request; any code or limit change invalidates it.</div>
<h3 style="font-size:14px">Requested Python source</h3><pre><code id="source"></code></pre>
<h3 style="font-size:14px">Resource limits</h3><div class="meta" id="limits"></div>
<label class="ack"><input id="inspected" type="checkbox"><span>I inspected the full source code and resource limits, and explicitly authorize this exact request for one execution.</span></label>
<button id="approve" disabled>Approve this execution</button></div><div id="status" class="status" role="status" aria-live="polite"></div>
</section></div></main><script>
const $=id=>document.getElementById(id);let credential="";let selected=null;
function authHeaders(){return {"X-Sandbox-Approval-Token":"Bearer "+credential,"Content-Type":"application/json"}}
function status(message,error=false){$("status").textContent=message;$("status").className="status"+(error?" error":"")}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{...authHeaders(),...(options.headers||{})}});const body=await response.json().catch(()=>({detail:"Unexpected server response"}));if(!response.ok)throw new Error(body.detail||"Request failed ("+response.status+")");return body}
function addMeta(container,key,value){const div=document.createElement("div");const small=document.createElement("small");small.textContent=key;const span=document.createElement("span");span.textContent=String(value);div.append(small,span);container.append(div)}
async function loadQueue(){const items=await api("/v1/sandbox/reviews");$("queue").replaceChildren();if(!items.length){const p=document.createElement("p");p.className="muted";p.textContent="No pending approvals.";$("queue").append(p);return}
for(const item of items){const b=document.createElement("button");b.className="item"+(selected===item.review_id?" active":"");const strong=document.createElement("strong");strong.textContent=item.review_id;const small=document.createElement("small");small.textContent="Requester: "+item.requester_id+" · Expires "+new Date(item.expires_at*1000).toLocaleTimeString();b.append(strong,small);b.addEventListener("click",()=>loadReview(item.review_id));$("queue").append(b)}}
async function loadReview(id){try{selected=id;status("Loading review…");const item=await api("/v1/sandbox/reviews/"+encodeURIComponent(id));$("empty").classList.add("hidden");$("details").classList.remove("hidden");$("requester").textContent=item.requester_id;$("approval").textContent=item.review_id;$("expiry").textContent=new Date(item.expires_at*1000).toLocaleString();$("hash").textContent=item.request_hash;$("source").textContent=item.request?.source??"Source unavailable or expired";$("limits").replaceChildren();for(const [key,value] of Object.entries(item.request?.limits??{}))addMeta($("limits"),key,value);$("inspected").checked=false;$("approve").disabled=item.status!=="pending"||!item.request?.source;$("state").textContent=item.status.toUpperCase();status(item.status==="pending"?"Read the complete code before acknowledging.":"This request is no longer pending.",item.status!=="pending");await loadQueue()}catch(e){status(e.message,true)}}
$("inspected").addEventListener("change",()=>{$("approve").disabled=!$("inspected").checked||!selected});
$("connect").addEventListener("click",async()=>{credential=$("token").value.trim();if(!credential){status("Enter the human approval credential.",true);return}try{await loadQueue();$("refresh").disabled=false;status("Reviewer authenticated. Select a request to inspect.")}catch(e){credential="";status(e.message,true)}});
$("refresh").addEventListener("click",async()=>{try{await loadQueue();status("Review queue refreshed.")}catch(e){status(e.message,true)}});
$("approve").addEventListener("click",async()=>{if(!selected||!$("inspected").checked)return;$("approve").disabled=true;try{await api("/v1/sandbox/approvals/"+encodeURIComponent(selected)+"/approve",{method:"POST"});$("state").textContent="APPROVED";status("Approved. This approval is one-time and retains its original expiry.");$("details").classList.add("hidden");$("empty").classList.remove("hidden");$("empty").textContent="Approval recorded. Select another request.";selected=null;await loadQueue()}catch(e){status(e.message,true);$("approve").disabled=false}});
$("token").addEventListener("keydown",event=>{if(event.key==="Enter")$("connect").click()});
</script></body></html>"""


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
        BearerTokenAuthenticator(
            config.api_auth_token,
            principal_id=config.sandbox_execution_principal or "local-operator",
        )
        if config.api_auth_token
        else None
    )
    # Runtime and security stores share dedicated SQLite paths. Prepare both
    # before any store opens them so directories, databases and sidecars inherit
    # restrictive permissions from the first write.
    prepare_private_sqlite_database(config.operations_database_path)
    prepare_private_sqlite_database(config.memory_database_path)
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
        approval_authenticator = BearerTokenAuthenticator(
            config.sandbox_approval_token, principal_id=config.sandbox_approver_id
        )
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
        tool_permissions = PermissionPolicy(
            {
                Permission(config.sandbox_execution_principal, "execute", "request_code_execution"),
                Permission(config.sandbox_execution_principal, "execute", "execute_approved_code"),
            }
        )
        tool_registry = ToolRegistry(policy=tool_permissions, audit_log=audit_log)
        tool_registry.register(
            RequestCodeExecutionApprovalTool(
                sandbox_approvals, config.sandbox_execution_principal
            )
        )
        tool_registry.register(
            ExecuteApprovedCodeTool(sandbox_executor, config.sandbox_execution_principal)
        )
        workflow.tool_registry = tool_registry

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
        ) or request.url.path.startswith("/v1/sandbox/reviews")
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

    @app.get("/sandbox/review", response_class=HTMLResponse)
    async def sandbox_review_page():
        if not config.sandbox_enabled:
            raise HTTPException(status_code=404, detail="Sandbox review is not enabled")
        return SANDBOX_REVIEW_HTML

    @app.get("/v1/sandbox/reviews")
    async def list_sandbox_reviews(request: Request):
        manager = request.app.state.sandbox_approvals
        approval_auth = request.app.state.sandbox_approval_authenticator
        principal = (
            approval_auth.authenticate(request.headers.get("x-sandbox-approval-token"))
            if approval_auth else None
        )
        if manager is None or principal is None:
            raise HTTPException(status_code=401, detail="Valid human approval credential required")
        return manager.list_pending()

    @app.get("/v1/sandbox/reviews/{review_id}")
    async def get_sandbox_review(review_id: str, request: Request):
        manager = request.app.state.sandbox_approvals
        approval_auth = request.app.state.sandbox_approval_authenticator
        principal = (
            approval_auth.authenticate(request.headers.get("x-sandbox-approval-token"))
            if approval_auth else None
        )
        if manager is None or principal is None:
            raise HTTPException(status_code=401, detail="Valid human approval credential required")
        review = manager.get_review(review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        return review

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
            approval = manager.request(principal.principal_id, execution_request)
        except HTTPException:
            raise
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"review_id": approval["review_id"], "approval_token": approval["approval_token"], "status": "pending", "expires_in_seconds": 300}

    @app.post("/v1/sandbox/approvals/{review_id}/approve")
    async def approve_sandbox_execution(review_id: str, request: Request):
        manager = request.app.state.sandbox_approvals
        approval_auth = request.app.state.sandbox_approval_authenticator
        if manager is None or approval_auth is None:
            raise HTTPException(status_code=503, detail="Sandbox approval is not configured")
        principal = approval_auth.authenticate(request.headers.get("x-sandbox-approval-token"))
        if principal is None:
            raise HTTPException(status_code=401, detail="Valid human approval credential required")
        try:
            manager.approve(review_id, principal.principal_id)
        except ApprovalError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"review_id": review_id, "status": "approved"}

    @app.post("/v1/sandbox/execute")
    async def execute_approved_sandbox_request(payload: dict[str, object], request: Request):
        executor = request.app.state.sandbox_executor
        if executor is None:
            raise HTTPException(status_code=503, detail="Sandbox execution is not configured")
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(status_code=401, detail="Authenticated requester required")
        approval_token = payload.get("approval_token")
        if not isinstance(approval_token, str) or not approval_token:
            raise HTTPException(status_code=422, detail="approval_token is required")
        try:
            execution_request = SandboxExecutionRequest.model_validate(payload.get("request"))
            result = await executor.execute(
                principal.principal_id,
                execution_request,
                approval_token=approval_token,
            )
        except (ApprovalError, PermissionDenied) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DockerSandboxError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/v1/tools/{tool_name}/execute")
    async def execute_agent_tool(
        tool_name: str, payload: dict[str, object], request: Request
    ) -> dict[str, object]:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(status_code=401, detail="Authenticated requester required")
        if request.app.state.workflow.tool_registry is None:
            raise HTTPException(status_code=503, detail="Agent tools are not configured")
        try:
            return await request.app.state.workflow.execute_tool(
                tool_name, payload, principal_id=principal.principal_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ApprovalError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except DockerSandboxError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

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
