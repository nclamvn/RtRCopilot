"""Loopback-only standalone HTTP boundary. No legacy app/config import."""
import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
import json
from typing import Annotated, Literal

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


class BatchUpload(StrictInput):
    files: list[dict] = Field(min_length=1, max_length=10)


class Revision(StrictInput):
    expected_version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=256000)
    request_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")


class Search(StrictInput):
    query: str = Field(min_length=1, max_length=500)


class ResearchSource(StrictInput):
    source_id: str = Field(min_length=1, max_length=160)


class CreateArtifact(StrictInput):
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["document", "table"]
    content: str = Field(min_length=1, max_length=256000)
    request_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")


class CommandKey(StrictInput):
    request_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")


class ConnectionChange(CommandKey):
    enabled: bool
    expected_revision: int = Field(ge=0)


class ApprovalDecision(CommandKey):
    decision: Literal["approve", "reject"]


class NewMemory(CommandKey):
    content: str = Field(min_length=1, max_length=4000)


class VersionCommand(CommandKey):
    expected_version: int = Field(ge=1)


class EditMemory(VersionCommand):
    content: str = Field(min_length=1, max_length=4000)


class NewSchedule(CommandKey):
    message: str = Field(min_length=1, max_length=16000)
    due_at: float = Field(ge=0, le=31536000)


class ScheduleAction(VersionCommand):
    action: Literal["pause", "resume", "cancel"]


class ClockTick(CommandKey):
    target: float = Field(ge=0, le=31536000)


class DeleteWorkspace(CommandKey):
    confirmation_token: str = Field(min_length=20, max_length=160)
    confirm_name: str = Field(min_length=1, max_length=120)


def create_app(settings: Settings | None = None, *, runtime_factory=None) -> FastAPI:
    settings = settings or Settings.from_env()
    # Import/app construction must not mutate a live catalogue. Startup owns
    # migrations after the operator has stopped any incompatible old worker.
    store = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal store
        from .runtime import Runtime
        store = Store(settings.data_dir / "catalogue.sqlite")
        app.state.store = store
        runtime = (runtime_factory or Runtime)(settings, store)
        app.state.runtime = runtime
        from .data_lifecycle import DataLifecycle
        app.state.lifecycle = DataLifecycle(store, active_runs=getattr(runtime, "active_runs", None))
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

    @app.get(PREFIX + "/readiness")
    def readiness(request: Request, actor: Owner):
        from .provider_config import readiness as provider_readiness
        value = request.app.state.runtime.status()
        provider, reason = provider_readiness(settings)
        return {**value, "provider": provider,
                "reason": value["reason"] if value["test_mode"] else (reason or value["reason"]),
                "setup_command": ".venv/bin/workspace configure --config .workspace-data/provider.json --allow-external-processing",
                "setup_directory": "v2/apps/workspace"}

    @app.get(PREFIX + "/workspaces")
    def workspaces(actor: Owner):
        return {"items": store.workspaces(actor)}

    @app.post(PREFIX + "/workspaces")
    def new_workspace(body: NewWorkspace, actor: Owner):
        if not body.name.strip():
            raise WorkspaceError("empty_name")
        return store.workspaces(actor, body.name.strip())

    @app.get(PREFIX + "/workspaces/{workspace_id}/export")
    def export_workspace(workspace_id: str, request: Request, actor: Owner):
        output = request.app.state.lifecycle.export(actor, workspace_id)
        return Response(output, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="workspace-export.zip"'})

    @app.get(PREFIX + "/workspaces/{workspace_id}/delete-preview")
    def delete_preview(workspace_id: str, request: Request, actor: Owner):
        return request.app.state.lifecycle.preview(actor, workspace_id)

    @app.post(PREFIX + "/workspaces/{workspace_id}/delete")
    def delete_workspace(workspace_id: str, body: DeleteWorkspace, request: Request, actor: Owner):
        return request.app.state.lifecycle.delete(actor, workspace_id, body.confirmation_token,
                                                  body.confirm_name, body.request_id)

    @app.get(PREFIX + "/workspaces/{workspace_id}/messages")
    def messages(workspace_id: str, actor: Owner):
        return {"items": store.items(actor, workspace_id, "messages")}

    @app.get(PREFIX + "/workspaces/{workspace_id}/files")
    def files(workspace_id: str, actor: Owner):
        return {"items": store.items(actor, workspace_id, "files")}

    @app.post(PREFIX + "/workspaces/{workspace_id}/files")
    def upload(workspace_id: str, body: Upload, actor: Owner):
        return store.upload(actor, workspace_id, body.filename, body.content, body.media_type)

    @app.post(PREFIX + "/workspaces/{workspace_id}/files/batch")
    def upload_batch(workspace_id: str, body: BatchUpload, actor: Owner):
        store.items(actor, workspace_id, "files")
        accepted, errors = [], []
        for index, value in enumerate(body.files):
            filename = value.get("filename", "")
            try:
                if set(value) - {"filename", "content", "content_base64", "media_type"} or not isinstance(filename, str):
                    raise WorkspaceError("invalid_upload")
                if ("content" in value) == ("content_base64" in value):
                    raise WorkspaceError("invalid_upload_encoding")
                if "content" in value:
                    if not isinstance(value["content"], str):
                        raise WorkspaceError("invalid_upload_encoding")
                    raw = value["content"].encode()
                else:
                    if not isinstance(value["content_base64"], str) or len(value["content_base64"]) > 350000:
                        raise WorkspaceError("file_too_large_or_binary", 413)
                    try:
                        raw = base64.b64decode(value["content_base64"], validate=True)
                    except (ValueError, binascii.Error):
                        raise WorkspaceError("invalid_upload_encoding") from None
                accepted.append(store.upload_bytes(actor, workspace_id, filename, raw))
            except WorkspaceError as exc:
                errors.append(dict(index=index, filename=filename if isinstance(filename, str) else "", error=exc.code))
        return dict(accepted=accepted, errors=errors)

    @app.get(PREFIX + "/files/{file_id}")
    def source(file_id: str, actor: Owner, offset: int = 0, limit: int = 16000):
        return store.source(actor, file_id, offset, limit)

    @app.get(PREFIX + "/files/{file_id}/download")
    def source_download(file_id: str, actor: Owner):
        from urllib.parse import quote
        item = store.source(actor, file_id, raw=True)
        return Response(item["raw_content"], media_type=item["media_type"], headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(item["filename"])})

    @app.post(PREFIX + "/workspaces/{workspace_id}/research/search")
    def research_search(workspace_id: str, body: Search, request: Request, actor: Owner):
        store.items(actor, workspace_id, "files")
        return request.app.state.runtime.research.search(body.query)

    @app.post(PREFIX + "/workspaces/{workspace_id}/research/read")
    def research_read(workspace_id: str, body: ResearchSource, request: Request, actor: Owner):
        store.items(actor, workspace_id, "files")
        return request.app.state.runtime.research.read(body.source_id)

    @app.post(PREFIX + "/workspaces/{workspace_id}/research/import")
    def research_import(workspace_id: str, body: ResearchSource, request: Request, actor: Owner):
        return request.app.state.runtime.research.import_source(store, actor, workspace_id, body.source_id)

    @app.get(PREFIX + "/workspaces/{workspace_id}/artifacts")
    def artifacts(workspace_id: str, actor: Owner):
        return {"items": store.items(actor, workspace_id, "artifacts")}

    @app.post(PREFIX + "/workspaces/{workspace_id}/artifacts")
    def create_artifact(workspace_id: str, body: CreateArtifact, actor: Owner):
        return store.create_artifact(actor, workspace_id, body.title, body.kind, body.content, body.request_id)

    @app.get(PREFIX + "/artifacts/{artifact_id}")
    def artifact(artifact_id: str, actor: Owner, version: int | None = None):
        return store.artifact(actor, artifact_id, version)

    @app.get(PREFIX + "/artifacts/{artifact_id}/download")
    def download(artifact_id: str, actor: Owner, version: int | None = None, format: str | None = None):
        from urllib.parse import quote
        item = store.artifact(actor, artifact_id, version)
        from .formats import render_artifact
        try:
            output = render_artifact(item["kind"], item["content"], format or ("csv" if item["kind"] == "table" else "md"), title=item["title"])
        except Exception:
            raise WorkspaceError("artifact_export_failed", 422) from None
        filename = item["filename"].rsplit(".", 1)[0] + "." + output.extension.lstrip(".")
        return Response(output.data, media_type=output.media_type, headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
            "X-Workspace-Export-Warnings": json.dumps(output.warnings, ensure_ascii=True),
        })

    @app.get(PREFIX + "/artifacts/{artifact_id}/versions")
    def versions(artifact_id: str, actor: Owner):
        return {"items": store.versions(actor, artifact_id)}

    @app.get(PREFIX + "/artifacts/{artifact_id}/diff")
    def artifact_diff(artifact_id: str, actor: Owner, from_version: int, to_version: int):
        return store.diff(actor, artifact_id, from_version, to_version)

    @app.post(PREFIX + "/artifacts/{artifact_id}/revisions")
    def revise(artifact_id: str, body: Revision, actor: Owner):
        return store.revise(actor, artifact_id, body.expected_version, body.content, body.request_id)

    @app.get(PREFIX + "/workspaces/{wid}/connection")
    def connection(wid: str, request: Request, actor: Owner):
        return request.app.state.runtime.connections.connection(actor, wid)

    @app.post(PREFIX + "/workspaces/{wid}/connection")
    def connection_change(wid: str, body: ConnectionChange, request: Request, actor: Owner):
        return request.app.state.runtime.connections.set_connection(actor, wid, body.enabled, body.expected_revision, body.request_id)

    @app.get(PREFIX + "/workspaces/{wid}/approvals")
    def approvals(wid: str, request: Request, actor: Owner):
        return request.app.state.runtime.connections.approvals(actor, wid)

    @app.post(PREFIX + "/approvals/{aid}/resolve")
    def resolve_approval(aid: str, body: ApprovalDecision, request: Request, actor: Owner):
        return request.app.state.runtime.connections.resolve(actor, aid, body.decision, body.request_id)

    @app.get(PREFIX + "/workspaces/{wid}/effects")
    def effects(wid: str, request: Request, actor: Owner):
        return request.app.state.runtime.connections.effects(actor, wid)

    @app.post(PREFIX + "/effects/{eid}/reconcile")
    async def reconcile_effect(eid: str, body: CommandKey, request: Request, actor: Owner):
        return await request.app.state.runtime.connections.reconcile(actor, eid)

    @app.get(PREFIX + "/workspaces/{wid}/memory")
    def memories(wid: str, request: Request, actor: Owner):
        return request.app.state.runtime.workspace_state.memories(actor, wid)

    @app.post(PREFIX + "/workspaces/{wid}/memory")
    def new_memory(wid: str, body: NewMemory, request: Request, actor: Owner):
        return request.app.state.runtime.workspace_state.save_memory(actor, wid, body.content, body.request_id)

    @app.post(PREFIX + "/workspaces/{wid}/memory/{mid}/edit")
    def edit_memory(wid: str, mid: str, body: EditMemory, request: Request, actor: Owner):
        return request.app.state.runtime.workspace_state.save_memory(actor, wid, body.content, body.request_id, memory_id=mid, expected_version=body.expected_version)

    @app.post(PREFIX + "/workspaces/{wid}/memory/{mid}/delete")
    def delete_memory(wid: str, mid: str, body: VersionCommand, request: Request, actor: Owner):
        return request.app.state.runtime.workspace_state.delete_memory(actor, wid, mid, body.expected_version, body.request_id)

    @app.get(PREFIX + "/workspaces/{wid}/schedules")
    def schedules(wid: str, request: Request, actor: Owner):
        return request.app.state.runtime.workspace_state.schedules(actor, wid)

    @app.post(PREFIX + "/workspaces/{wid}/schedules")
    def new_schedule(wid: str, body: NewSchedule, request: Request, actor: Owner):
        if not settings.test_mode:
            raise WorkspaceError("schedule_simulation_disabled", 403)
        return request.app.state.runtime.workspace_state.create_schedule(actor, wid, body.message, body.due_at, body.request_id)

    @app.post(PREFIX + "/workspaces/{wid}/schedules/{sid}/action")
    def schedule_action(wid: str, sid: str, body: ScheduleAction, request: Request, actor: Owner):
        return request.app.state.runtime.workspace_state.change_schedule(actor, wid, sid, body.action, body.expected_version, body.request_id)

    @app.post(PREFIX + "/workspaces/{wid}/clock/tick")
    async def clock_tick(wid: str, body: ClockTick, request: Request, actor: Owner):
        if not settings.test_mode:
            raise WorkspaceError("schedule_simulation_disabled", 403)
        runtime = request.app.state.runtime
        if not runtime.status()["available"]:
            raise WorkspaceError("model_unavailable", 503)
        limits = {key: getattr(settings, key) for key in ("deadline_seconds", "request_limit", "tool_limit", "token_limit", "output_bytes_limit")}
        value = runtime.workspace_state.tick(actor, wid, body.target, body.request_id, limits)
        await runtime.dispatch_pending()
        return value

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
