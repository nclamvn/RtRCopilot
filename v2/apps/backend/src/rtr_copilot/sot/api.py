import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from rtr_copilot.auth.api import current_subject
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import ResourceRepository
from rtr_copilot.sot.models import ActiveRecord, PublishResult, ValidationReport
from rtr_copilot.sot.package import PackageError
from rtr_copilot.sot.service import PublishError, SOTPublishService


class StageRequest(BaseModel):
    staging_name: str = Field(min_length=1, max_length=128)


class SOTErrorDetail(BaseModel):
    code: str
    message: str


class SOTErrorEnvelope(BaseModel):
    error: SOTErrorDetail
    request_id: str


router = APIRouter(
    prefix="/api/v1/sot",
    tags=["sot"],
    responses={
        status: {"model": SOTErrorEnvelope}
        for status in (400, 401, 403, 404, 409, 422)
    },
)
policy = PolicyEngine(StructuredAuditSink())


async def sot_subject(request: Request) -> Subject | None:
    settings = get_settings()
    return await current_subject(
        request,
        request.cookies.get(settings.session_cookie_name),
    )


def _error(request: Request, status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": "SOT request could not be completed"},
            "request_id": str(request.state.request_id),
        },
    )


def _mutation_allowed(subject: Subject, request_id: str) -> bool:
    resource = ResourceAttributes(classification="internal", source_zone="sot")
    context = PolicyContext(request_id=request_id)
    return (
        policy.decide(subject, "curate", resource, context).allow
        or policy.decide(subject, "manage_policies", resource, context).allow
    )


def _actor(
    request: Request,
    subject: Subject | None,
    *,
    mutation: bool = False,
) -> uuid.UUID | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    if mutation and not _mutation_allowed(subject, str(request.state.request_id)):
        return _error(request, 403, "curator_role_required")
    return uuid.UUID(subject.user_id)


def _service_error(request: Request, error: Exception) -> JSONResponse:
    code = getattr(error, "code", "sot_request_failed")
    status = 404 if code == "package_not_found" else 409
    if code.endswith("_unsafe") or code.startswith("manifest_"):
        status = 400
    return _error(request, status, code)


@router.post("/packages/stage", response_model=PublishResult, status_code=201)
async def stage_package(
    request: Request,
    body: StageRequest,
    subject: Annotated[Subject | None, Depends(sot_subject)],
) -> PublishResult | JSONResponse:
    actor = _actor(request, subject, mutation=True)
    if isinstance(actor, JSONResponse):
        return actor
    try:
        return await SOTPublishService().stage(
            body.staging_name,
            actor_id=actor,
            request_id=str(request.state.request_id),
        )
    except (PackageError, PublishError) as error:
        return _service_error(request, error)


@router.post("/packages/{package_id}/validate", response_model=ValidationReport)
async def validate_package_endpoint(
    package_id: uuid.UUID,
    request: Request,
    subject: Annotated[Subject | None, Depends(sot_subject)],
) -> ValidationReport | JSONResponse:
    actor = _actor(request, subject, mutation=True)
    if isinstance(actor, JSONResponse):
        return actor
    try:
        return await SOTPublishService().validate(
            package_id,
            actor_id=actor,
            request_id=str(request.state.request_id),
        )
    except (PackageError, PublishError) as error:
        return _service_error(request, error)


@router.post("/packages/{package_id}/publish", response_model=PublishResult)
async def publish_package(
    package_id: uuid.UUID,
    request: Request,
    subject: Annotated[Subject | None, Depends(sot_subject)],
) -> PublishResult | JSONResponse:
    actor = _actor(request, subject, mutation=True)
    if isinstance(actor, JSONResponse):
        return actor
    try:
        return await SOTPublishService().publish(
            package_id,
            actor_id=actor,
            request_id=str(request.state.request_id),
        )
    except (PackageError, PublishError) as error:
        return _service_error(request, error)


@router.get("/packages/{package_id}", response_model=dict[str, Any])
async def package_status(
    package_id: uuid.UUID,
    request: Request,
    subject: Annotated[Subject | None, Depends(sot_subject)],
) -> dict[str, Any] | JSONResponse:
    actor = _actor(request, subject, mutation=True)
    if isinstance(actor, JSONResponse):
        return actor
    status = await SOTPublishService().status(package_id)
    return status if status is not None else _error(request, 404, "package_not_found")


async def _record_allowed(
    subject: Subject,
    record_id: uuid.UUID,
    request_id: str,
) -> bool:
    async with UnitOfWork().factory() as session:
        attributes = await ResourceRepository().policy_attributes(
            session,
            record_id,
            action="view",
            principal_ids={uuid.UUID(subject.user_id)},
        )
    return bool(
        attributes
        and policy.decide(
            subject,
            "view",
            attributes,
            PolicyContext(request_id=request_id),
        ).allow
    )


@router.get("/records", response_model=list[ActiveRecord])
async def list_records(
    request: Request,
    subject: Annotated[Subject | None, Depends(sot_subject)],
) -> list[ActiveRecord] | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    service = SOTPublishService()
    output: list[ActiveRecord] = []
    for row in await service.active_records():
        if await _record_allowed(
            subject,
            row["record_id"],
            str(request.state.request_id),
        ):
            detail = await service.active_record(row["record_key"])
            if detail:
                output.append(detail[1])
    return output


@router.get("/records/{record_key}", response_model=ActiveRecord)
async def get_record(
    record_key: str,
    request: Request,
    subject: Annotated[Subject | None, Depends(sot_subject)],
) -> ActiveRecord | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    detail = await SOTPublishService().active_record(record_key)
    allowed = bool(
        detail
        and await _record_allowed(
            subject,
            detail[0],
            str(request.state.request_id),
        )
    )
    async with UnitOfWork().transaction() as session:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action="sot.record.view",
            result="allow" if allowed else "deny",
            reason_code="record_visible" if allowed else "record_not_found",
            request_id=str(request.state.request_id),
            resource_id=detail[0] if detail else None,
            resource_type="record",
        )
    return detail[1] if allowed and detail else _error(request, 404, "record_not_found")
