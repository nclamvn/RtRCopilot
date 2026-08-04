from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis

from rtr_copilot.config import Settings, get_settings
from rtr_copilot.infra.dependencies import probe_dependencies
from rtr_copilot.rag.answer_llm import answer_quality_readiness

router = APIRouter(tags=["system"])
WORKER_HEARTBEAT = "rtr:worker:heartbeat"


class LiveResponse(BaseModel):
    ok: Literal[True] = True
    status: Literal["live"] = "live"


class ReadyResponse(BaseModel):
    ok: bool
    status: Literal["ready", "unavailable"]
    dependencies: dict[str, str]


class OperationalResponse(BaseModel):
    ok: bool
    status: Literal["operational", "unavailable"]
    build_sha: str
    dependencies: dict[str, str]
    capabilities: dict[str, str]


@router.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get("/health/ready", response_model=ReadyResponse)
async def ready(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadyResponse:
    dependencies = await probe_dependencies(settings)
    ok = all(value == "ready" for value in dependencies.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(ok=ok, status="ready" if ok else "unavailable", dependencies=dependencies)


async def probe_worker(settings: Settings) -> str:
    client: Redis = Redis.from_url(settings.redis_url, socket_timeout=2)
    try:
        return "ready" if await client.exists(WORKER_HEARTBEAT) else "unavailable"
    except Exception:
        return "unavailable"
    finally:
        await client.aclose()


@router.get("/health/operational", response_model=OperationalResponse)
async def operational(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> OperationalResponse:
    dependencies = await probe_dependencies(settings)
    dependencies["worker"] = await probe_worker(settings)
    ok = all(value == "ready" for value in dependencies.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return OperationalResponse(
        ok=ok,
        status="operational" if ok else "unavailable",
        build_sha=settings.rtr_build_sha,
        dependencies=dependencies,
        capabilities={
            "grounded_answering": answer_quality_readiness(settings),
        },
    )
