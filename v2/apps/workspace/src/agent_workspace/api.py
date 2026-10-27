"""Loopback-only standalone HTTP boundary. No legacy app/config import."""
import asyncio
from contextlib import asynccontextmanager
import json
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .store import Store, TERMINAL, WorkspaceError

COOKIE = "workspace_session"
PREFIX = "/api/workspace"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewWorkspace(StrictInput):
    name: str = Field(min_length=1, max_length=120)


class Upload(StrictInput):
    filename: str = Field(min_length=1, max_length=160)
    content: str = Field(max_length=256000)
    media_type: str = "text/plain"


class NewRun(StrictInput):
    workspace_id: str
    message: str = Field(min_length=1, max_length=16000)
    client_request_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")


def create_app(settings: Settings | None = None, *, runtime_factory=None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir / "catalogue.sqlite")

    @asynccontextmanager
    async def lifespan(app):
        from .runtime import Runtime
        runtime = (runtime_factory or Runtime)(settings, store)
        app.state.runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="Agent Workspace", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def local_boundary(request, call_next):
        # DNS rebinding and remote exposure are not an authentication mode.
        peer = request.client.host if request.client else ""
        if peer not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            return JSONResponse({"detail": "loopback_only"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") not in settings.origins:
                return JSONResponse({"detail": "origin_denied"}, status_code=403)
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 1600000):
                return JSONResponse({"detail": "request_too_large"}, status_code=413)
            # Also bound chunked/no-Content-Length requests before JSON decoding.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 1600000:
                    return JSONResponse({"detail": "request_too_large"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(WorkspaceError)
    async def workspace_error(request, exc):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    def owner(request: Request):
        return store.authenticate(request.cookies.get(COOKIE))

    Owner = Annotated[str, Depends(owner)]

    @app.post(PREFIX + "/session")
    def session(request: Request, response: Response):
        token, _ = store.session(request.cookies.get(COOKIE))
        # HTTP-only local development: Secure would prevent plain-loopback HTTP.
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path=PREFIX, max_age=30 * 86400)
        return {"authenticated": True}

    @app.get(PREFIX + "/status")
    def status(request: Request, actor: Owner):
        return request.app.state.runtime.status()

    @app.get(PREFIX + "/workspaces")
    def workspaces(actor: Owner):
        return {"items": store.workspaces(actor)}

    @app.post(PREFIX + "/workspaces")
    def new_workspace(body: NewWorkspace, actor: Owner):
        if not body.name.strip():
            raise WorkspaceError("empty_name")
        return store.workspaces(actor, body.name.strip())

    @app.get(PREFIX + "/workspaces/{workspace_id}/messages")
    def messages(workspace_id: str, actor: Owner):
        return {"items": store.items(actor, workspace_id, "messages")}

    @app.get(PREFIX + "/workspaces/{workspace_id}/files")
    def files(workspace_id: str, actor: Owner):
        return {"items": store.items(actor, workspace_id, "files")}

    @app.post(PREFIX + "/workspaces/{workspace_id}/files")
    def upload(workspace_id: str, body: Upload, actor: Owner):
        return store.upload(actor, workspace_id, body.filename, body.content, body.media_type)

    @app.get(PREFIX + "/workspaces/{workspace_id}/artifacts")
    def artifacts(workspace_id: str, actor: Owner):
        return {"items": store.items(actor, workspace_id, "artifacts")}

    @app.get(PREFIX + "/artifacts/{artifact_id}")
    def artifact(artifact_id: str, actor: Owner, version: int | None = None):
        return store.artifact(actor, artifact_id, version)

    @app.get(PREFIX + "/artifacts/{artifact_id}/download")
    def download(artifact_id: str, actor: Owner, version: int | None = None):
        from urllib.parse import quote
        item = store.artifact(actor, artifact_id, version)
        return Response(item["content"], media_type=item["media_type"], headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(item["filename"]),
        })

    @app.post(PREFIX + "/runs")
    async def start_run(body: NewRun, request: Request, actor: Owner):
        # Validate scope before availability to avoid resource probing.
        store.items(actor, body.workspace_id, "messages")
        runtime = request.app.state.runtime
        if not runtime.status()["available"]:
            raise WorkspaceError("model_unavailable", 503)
        if not body.message.strip():
            raise WorkspaceError("empty_message")
        limits = {key: getattr(settings, key) for key in (
            "deadline_seconds", "request_limit", "tool_limit", "token_limit", "output_bytes_limit")}
        run = store.create_run(actor, body.workspace_id, body.message, body.client_request_id, limits)
        await runtime.dispatch_pending()
        return {"run_id": run["id"], "state": run["state"]}

    @app.get(PREFIX + "/runs/{run_id}")
    def run(run_id: str, actor: Owner):
        return store.run(actor, run_id)

    @app.post(PREFIX + "/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request, actor: Owner):
        result = store.cancel(actor, run_id)
        await request.app.state.runtime.cancel(actor, run_id)
        return result

    @app.get(PREFIX + "/runs/{run_id}/events")
    async def events(run_id: str, request: Request, actor: Owner, after: int = 0):
        store.run(actor, run_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")), 0)
        except ValueError:
            raise WorkspaceError("invalid_event_cursor")

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                rows = store.events(actor, run_id, cursor)
                for item in rows:
                    cursor = item["seq"]
                    yield f"id: {cursor}\nevent: workspace\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                if not rows and store.run(actor, run_id)["state"] in TERMINAL:
                    break
                idle += 1
                if idle % 40 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.1)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    return app


app = create_app()
