import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from rtr_copilot.api.health import router as health_router
from rtr_copilot.auth.api import dev_router as auth_dev_router
from rtr_copilot.auth.api import router as auth_router
from rtr_copilot.config import get_settings
from rtr_copilot.documents.api import router as documents_router
from rtr_copilot.governance.api import router as governance_router
from rtr_copilot.ingestion.api import router as files_router
from rtr_copilot.rag.api import router as rag_router
from rtr_copilot.research.api import router as research_router
from rtr_copilot.sot.api import router as sot_router
from rtr_copilot.worker.main import HEARTBEAT, QUEUE

logger = logging.getLogger("rtr_copilot")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")

@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    get_settings()
    yield


app = FastAPI(
    title="RtR Copilot V2 Foundation",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(files_router)
app.include_router(sot_router)
app.include_router(rag_router)
app.include_router(documents_router)
app.include_router(governance_router)
app.include_router(research_router)
if get_settings().app_env in {"development", "test"} and get_settings().dev_oidc_enabled:
    app.include_router(auth_dev_router)


@app.middleware("http")
async def request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Any]],
) -> Any:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as error:
        fingerprint = __import__("hashlib").sha256(
            type(error).__name__.encode(),
        ).hexdigest()
        logger.error(json.dumps({
            "event": "request_error",
            "request_id": request_id,
            "error_code": "internal_error",
            "error_fingerprint": fingerprint,
        }))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"},
                     "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    logger.info(json.dumps({"event": "request", "request_id": request_id,
                            "method": request.method, "path": request.url.path,
                            "status": response.status_code,
                            "duration_ms": round((time.monotonic() - started) * 1000, 2)}))
    return response


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message),
        request_id=request.state.request_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    if error.status_code == 404:
        return error_response(request, 404, "not_found", "Resource not found")
    return error_response(request, error.status_code, "http_error", "HTTP request failed")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
    return error_response(
        request,
        422,
        "validation_error",
        "Request validation failed",
    )


class ServiceInfo(BaseModel):
    service: str = "rtr-copilot-api"
    version: str = "0.1.0"
    state: str = "foundation-no-data"


class PingResponse(BaseModel):
    job_id: str
    request_id: str
    status: str


@app.get("/", response_model=ServiceInfo, tags=["system"])
async def info() -> ServiceInfo:
    return ServiceInfo()


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Any:
    from fastapi.responses import Response

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/system/ping", response_model=PingResponse, tags=["system"])
async def system_ping(request: Request) -> PingResponse:
    settings = get_settings()
    request_id = str(request.state.request_id)
    job_id = str(uuid.uuid4())
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        if not await client.exists(HEARTBEAT):
            return JSONResponse(  # type: ignore[return-value]
                status_code=503,
                content={"error": {"code": "worker_unavailable",
                                   "message": "Worker is not ready"},
                         "request_id": request_id},
            )
        job = json.dumps({"name": "system.ping", "job_id": job_id, "request_id": request_id})
        await cast(Awaitable[int], client.lpush(QUEUE, job))
        for _ in range(30):
            raw = await client.get(f"rtr:result:{job_id}")
            if raw:
                return PingResponse(**json.loads(raw))
            await __import__("asyncio").sleep(0.1)
        return JSONResponse(  # type: ignore[return-value]
            status_code=503,
            content={"error": {"code": "worker_timeout", "message": "Worker did not respond"},
                     "request_id": request_id},
        )
    finally:
        await client.aclose()
