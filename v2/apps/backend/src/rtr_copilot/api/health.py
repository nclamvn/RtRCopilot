from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from rtr_copilot.config import Settings, get_settings
from rtr_copilot.infra.dependencies import probe_dependencies

router = APIRouter(tags=["system"])


class LiveResponse(BaseModel):
    ok: Literal[True] = True
    status: Literal["live"] = "live"


class ReadyResponse(BaseModel):
    ok: bool
    status: Literal["ready", "unavailable"]
    dependencies: dict[str, str]


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
