import uuid
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rtr_copilot.auth.api import current_subject
from rtr_copilot.auth.models import Subject
from rtr_copilot.config import get_settings
from rtr_copilot.governance.models import GapPriority, GapState, QueueKind, ReviewTask
from rtr_copilot.governance.queues import QueuePage
from rtr_copilot.governance.service import (
    GapDetail,
    GapListPage,
    GapOperation,
    GapTransitionInput,
    GovernanceService,
)
from rtr_copilot.repositories.governance import GovernanceError


class GovernanceErrorDetail(BaseModel):
    code: str
    message: str


class GovernanceErrorEnvelope(BaseModel):
    error: GovernanceErrorDetail
    request_id: str


router = APIRouter(
    prefix="/api/v1",
    tags=["governance"],
    responses={
        status: {"model": GovernanceErrorEnvelope}
        for status in (400, 401, 403, 404, 409, 422)
    },
)

GAP_OPERATIONS: frozenset[str] = frozenset({"triage", "assign", "answer", "decline"})
QUEUE_PATHS: dict[str, QueueKind] = {
    "freshness": "freshness",
    "conflict": "conflict",
    "owner-review": "owner_review",
}
STATUS_BY_CODE: dict[str, int] = {
    "gap_not_found": 404,
    "queue_entry_not_found": 404,
    "review_task_not_found": 404,
    "invalid_cursor": 400,
    "gap_owner_required": 422,
    "gap_resolution_record_required": 422,
    "gap_decline_reason_required": 422,
    "record_version_not_found": 422,
    "setting_unknown": 422,
    "setting_out_of_bounds": 422,
    "setting_value_type_mismatch": 422,
}


async def governance_subject(request: Request) -> Subject | None:
    settings = get_settings()
    return await current_subject(
        request,
        request.cookies.get(settings.session_cookie_name),
    )


def _error(request: Request, status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": "Governance request could not be completed",
            },
            "request_id": str(request.state.request_id),
        },
    )


async def call(request: Request, operation: Any) -> Any:
    try:
        return await operation
    except LookupError:
        return _error(request, 404, "not_found")
    except PermissionError as failure:
        return _error(request, 403, str(failure) or "forbidden")
    except GovernanceError as failure:
        return _error(request, STATUS_BY_CODE.get(failure.code, 409), failure.code)


class GapTransitionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    owner_subject_id: uuid.UUID | None = None
    resolving_version_id: uuid.UUID | None = None
    decline_reason: str | None = Field(default=None, min_length=1, max_length=2000)


class QueueAssignRequest(BaseModel):
    record_version_id: uuid.UUID
    assignee_subject_id: uuid.UUID
    due_at: datetime | None = None
    note: str = Field(default="", max_length=2000)


@router.get("/gaps", response_model=GapListPage)
async def list_gaps(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    state: Annotated[GapState | None, Query()] = None,
    owner_subject_id: Annotated[uuid.UUID | None, Query()] = None,
    priority: Annotated[GapPriority | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, GovernanceService().list_gaps(
        subject,
        request_id=str(request.state.request_id),
        state=state,
        owner_subject_id=owner_subject_id,
        priority=priority,
        cursor=cursor,
        limit=limit,
    ))


@router.get("/gaps/{gap_id}", response_model=GapDetail)
async def gap_detail(
    request: Request,
    gap_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, GovernanceService().gap_detail(
        subject,
        gap_id,
        request_id=str(request.state.request_id),
    ))


@router.post("/gaps/{gap_id}/{operation}")
async def transition_gap(
    request: Request,
    gap_id: uuid.UUID,
    operation: str,
    payload: GapTransitionRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    if operation not in GAP_OPERATIONS:
        return _error(request, 404, "not_found")
    gap_operation = cast(GapOperation, operation)
    return await call(request, GovernanceService().transition_gap(
        subject,
        gap_id,
        gap_operation,
        GapTransitionInput(
            reason=payload.reason,
            owner_subject_id=payload.owner_subject_id,
            resolving_version_id=payload.resolving_version_id,
            decline_reason=payload.decline_reason,
        ),
        request_id=str(request.state.request_id),
    ))


@router.get("/governance/queues/{queue}", response_model=QueuePage)
async def queue_page(
    request: Request,
    queue: str,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    queue_kind = QUEUE_PATHS.get(queue)
    if queue_kind is None:
        return _error(request, 404, "not_found")
    return await call(request, GovernanceService().queue_page(
        subject,
        queue_kind,
        request_id=str(request.state.request_id),
        cursor=cursor,
        limit=limit,
    ))


@router.post("/governance/queues/{queue}/assign", response_model=ReviewTask)
async def assign_queue_task(
    request: Request,
    queue: str,
    payload: QueueAssignRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    queue_kind = QUEUE_PATHS.get(queue)
    if queue_kind is None:
        return _error(request, 404, "not_found")
    return await call(request, GovernanceService().assign_queue_task(
        subject,
        queue_kind,
        record_version_id=payload.record_version_id,
        assignee_subject_id=payload.assignee_subject_id,
        due_at=payload.due_at,
        note=payload.note,
        request_id=str(request.state.request_id),
    ))


@router.post(
    "/governance/review-tasks/{task_id}/complete",
    response_model=ReviewTask,
)
async def complete_review_task(
    request: Request,
    task_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, GovernanceService().complete_queue_task(
        subject,
        task_id,
        request_id=str(request.state.request_id),
    ))
