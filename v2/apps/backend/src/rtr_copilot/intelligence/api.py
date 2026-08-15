"""Authenticated read-only API for the TIP-038 intelligence briefing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rtr_copilot.auth.models import Subject
from rtr_copilot.governance.api import governance_subject
from rtr_copilot.intelligence.models import IntelligenceBriefing
from rtr_copilot.intelligence.service import IntelligenceService


class IntelligenceErrorDetail(BaseModel):
    code: str
    message: str


class IntelligenceErrorEnvelope(BaseModel):
    error: IntelligenceErrorDetail
    request_id: str


router = APIRouter(
    prefix="/api/v1/intelligence",
    tags=["intelligence"],
    responses={
        status: {"model": IntelligenceErrorEnvelope}
        for status in (401, 403, 422, 503)
    },
)


def _error(request: Request, status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": "Intelligence briefing could not be completed",
            },
            "request_id": str(request.state.request_id),
        },
    )


@router.get("/briefing", response_model=IntelligenceBriefing)
async def briefing(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    limit: Annotated[int, Query(ge=1, le=20)] = 12,
) -> IntelligenceBriefing | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    try:
        return await IntelligenceService().briefing(
            subject,
            request_id=str(request.state.request_id),
            limit=limit,
        )
    except PermissionError:
        return _error(request, 403, "briefing_scope_denied")
