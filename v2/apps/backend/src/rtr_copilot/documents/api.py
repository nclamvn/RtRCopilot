import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from rtr_copilot.auth.models import Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import (
    ArtifactPlanRequest,
    ArtifactPlanResponse,
    BindRequest,
    BindResult,
    DecisionRequest,
    GeneratedHistory,
    GeneratedVersionDetail,
    IssuanceResult,
    RenderRequest,
    RenderStatus,
    TemplateHistory,
    TemplateImport,
    TemplatePage,
    TemplateVersionDetail,
)
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.ingestion.api import file_subject
from rtr_copilot.limits.backpressure import QueueSaturated, check_capacity
from rtr_copilot.limits.errors import limit_response
from rtr_copilot.repositories.audit import AuditRepository

router = APIRouter(prefix="/api/v1", tags=["documents"])


def error(request: Request, status: int, code: str) -> JSONResponse:
    messages = {
        "authentication_required": "Authentication required",
        "not_found": "Resource not found",
        "invalid_request": "Request is invalid",
        "forbidden": "Action is not permitted",
        "conflict": "Resource state changed; refresh and retry",
    }
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": messages[code]},
            "request_id": str(request.state.request_id),
        },
    )


def subject_or_error(
    request: Request, subject: Subject | None,
) -> Subject | JSONResponse:
    return subject if subject else error(request, 401, "authentication_required")


async def call(
    request: Request,
    operation: Any,
) -> Any:
    try:
        return await operation
    except LookupError:
        return error(request, 404, "not_found")
    except PermissionError:
        return error(request, 403, "forbidden")
    except ValueError as failure:
        if str(failure) in {
            "stale_transition", "approval_required", "not_issued_or_revoked",
            "separation_or_state_denied",
        }:
            return error(request, 409, "conflict")
        return error(request, 422, "invalid_request")


@router.get("/templates", response_model=TemplatePage)
async def list_templates(
    request: Request,
    subject: Annotated[Subject | None, Depends(file_subject)],
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().list_templates(
        actor, request_id=str(request.state.request_id), limit=limit,
        cursor=cursor,
    ))


@router.post("/artifact-plans", response_model=ArtifactPlanResponse)
async def plan_artifact(
    request: Request,
    payload: ArtifactPlanRequest,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().plan_artifact(
        actor, payload, request_id=str(request.state.request_id),
    ))


@router.post("/templates/import", response_model=TemplateVersionDetail)
async def import_template(
    request: Request,
    payload: TemplateImport,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().import_template(
        actor, payload, request_id=str(request.state.request_id),
    ))


@router.get(
    "/templates/{template_id}/versions/{version_id}",
    response_model=TemplateVersionDetail,
)
async def template_detail(
    request: Request,
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    result = await call(request, DocumentOSService().detail(
        actor, version_id, request_id=str(request.state.request_id),
    ))
    if (
        isinstance(result, TemplateVersionDetail)
        and result.template_id != template_id
    ):
        return error(request, 404, "not_found")
    return result


@router.get("/templates/{template_id}/versions", response_model=TemplateHistory)
async def template_history(
    request: Request,
    template_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().template_history(
        actor, template_id, request_id=str(request.state.request_id),
    ))


@router.post("/templates/{version_id}/lifecycle/{operation}")
async def template_lifecycle(
    request: Request,
    version_id: uuid.UUID,
    operation: str,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    if operation not in {"submit", "approve", "retire"}:
        return error(request, 404, "not_found")
    result = await call(request, DocumentOSService().lifecycle(
        actor, version_id, operation, request_id=str(request.state.request_id),
    ))
    return {"ok": True} if result is None else result


@router.post("/templates/{version_id}/bind", response_model=BindResult)
async def bind(
    request: Request,
    version_id: uuid.UUID,
    payload: BindRequest,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().bind(
        actor, version_id, payload, request_id=str(request.state.request_id),
    ))


@router.post("/templates/{version_id}/render", response_model=RenderStatus)
async def create_render(
    request: Request,
    version_id: uuid.UUID,
    payload: RenderRequest,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    request_id = str(request.state.request_id)
    try:
        async with UnitOfWork().factory() as session:
            await check_capacity(
                session,
                "render",
                retry_after=get_settings().limits_queue_retry_after_seconds,
            )
    except QueueSaturated as saturated:
        async with UnitOfWork().transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=uuid.UUID(actor.user_id),
                action="document.render.shed",
                result="deny",
                reason_code="queue_saturated",
                request_id=request_id,
                resource_type="request_limit",
                details={
                    "family": "render",
                    "outstanding": saturated.outstanding,
                    "cap": saturated.cap,
                    "template_version_id": str(version_id),
                },
            )
        return limit_response(
            request_id, "queue_saturated", retry_after=saturated.retry_after,
        )
    return await call(request, DocumentOSService().create_render(
        actor, version_id, payload, request_id=request_id,
    ))


@router.get("/documents/render-jobs/{job_id}", response_model=RenderStatus)
async def render_status(
    request: Request,
    job_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().status(
        actor, job_id, request_id=str(request.state.request_id),
    ))


@router.get(
    "/documents/generated/{generated_id}",
    response_model=GeneratedVersionDetail,
)
async def generated_detail(
    request: Request,
    generated_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().generated_detail(
        actor, generated_id, request_id=str(request.state.request_id),
    ))


@router.get("/documents/history", response_model=GeneratedHistory)
async def generated_history(
    request: Request,
    template_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().generated_history(
        actor, template_id, request_id=str(request.state.request_id),
    ))


@router.post(
    "/documents/render-jobs/{job_id}/{action}",
    response_model=RenderStatus,
)
async def render_action(
    request: Request,
    job_id: uuid.UUID,
    action: str,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    if action not in {"retry", "cancel"}:
        return error(request, 404, "not_found")
    return await call(request, DocumentOSService().render_action(
        actor, job_id, action, request_id=str(request.state.request_id),
    ))


@router.post("/documents/generated/{generated_id}/submit")
async def submit_generated(
    request: Request,
    generated_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    result = await call(request, DocumentOSService().submit(
        actor, generated_id, request_id=str(request.state.request_id),
    ))
    return {"ok": True} if result is None else result


@router.post("/documents/generated/{generated_id}/decision/{decision}")
async def decide_generated(
    request: Request,
    generated_id: uuid.UUID,
    decision: str,
    payload: DecisionRequest,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    if decision not in {"approve", "reject"}:
        return error(request, 404, "not_found")
    result = await call(request, DocumentOSService().decide(
        actor, generated_id, "approved" if decision == "approve" else "rejected",
        payload, request_id=str(request.state.request_id),
    ))
    return {"ok": True} if result is None else result


@router.post(
    "/documents/generated/{generated_id}/issue",
    response_model=IssuanceResult,
)
async def issue_generated(
    request: Request,
    generated_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().issue(
        actor, generated_id, request_id=str(request.state.request_id),
    ))


@router.post(
    "/documents/generated/{generated_id}/revoke",
    response_model=IssuanceResult,
)
async def revoke_generated(
    request: Request,
    generated_id: uuid.UUID,
    payload: DecisionRequest,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> Any:
    actor = subject_or_error(request, subject)
    if isinstance(actor, JSONResponse):
        return actor
    return await call(request, DocumentOSService().revoke(
        actor, generated_id, payload, request_id=str(request.state.request_id),
    ))
