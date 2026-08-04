"""Admin governance endpoints (TIP-010 Task 6, REQ-032, AC-11).

Reuses the governance error envelope, subject resolution and typed error
mapping. The surface is deliberately closed: research sources, settings, gap
priority, identity bindings and read-only job health. The truth families —
SOT records, research records/packages, audit events and issued documents —
are refused with a typed, audited error on every method (AC-11); the database
immutability triggers remain the final backstop.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from rtr_copilot.auth.models import Subject
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.admin import (
    AdminGovernanceService,
    BindingKind,
    BindingOperation,
    JobHealthReport,
    PilotReadinessReport,
    SettingView,
    SubjectAccountView,
)
from rtr_copilot.governance.api import (
    GovernanceErrorEnvelope,
    _error,
    call,
    governance_subject,
)
from rtr_copilot.governance.models import (
    Classification,
    Gap,
    GapPriority,
    GovernanceSetting,
    ResearchOrigin,
    ResearchSource,
    ResearchSourceLifecycle,
)
from rtr_copilot.governance.service import GovernanceService
from rtr_copilot.repositories.audit import AuditRepository

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["governance-admin"],
    responses={
        status: {"model": GovernanceErrorEnvelope}
        for status in (400, 401, 403, 404, 409, 422)
    },
)

TRUTH_FAMILIES = (
    "sot",
    "records",
    "research-records",
    "research-packages",
    "audit",
    "issuances",
    "documents",
)
BOUNDARY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


class BoundedRequest(BaseModel):
    """Admin write payloads refuse unknown fields (AC-11 bounded surface)."""

    model_config = ConfigDict(extra="forbid")


class SourceCreateRequest(BoundedRequest):
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    origin: ResearchOrigin
    owner_subject_id: uuid.UUID
    classification: Classification
    lifecycle: ResearchSourceLifecycle = "active"


class SourceUpdateRequest(BoundedRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner_subject_id: uuid.UUID | None = None
    classification: Classification | None = None
    lifecycle: ResearchSourceLifecycle | None = None
    reason: str = Field(min_length=1, max_length=2000)


class SettingUpdateRequest(BoundedRequest):
    value: int | float | bool | str
    reason: str = Field(min_length=1, max_length=2000)


class GapPriorityRequest(BoundedRequest):
    priority: GapPriority
    reason: str = Field(min_length=1, max_length=2000)


class BindingRequest(BoundedRequest):
    binding: BindingKind
    key: str = Field(min_length=1, max_length=128)
    operation: BindingOperation
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/research-sources", response_model=ResearchSource, status_code=201)
async def create_source(
    request: Request,
    body: SourceCreateRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().create_source(
        subject,
        stable_key=body.stable_key,
        display_name=body.display_name,
        description=body.description,
        origin=body.origin,
        owner_subject_id=body.owner_subject_id,
        classification=body.classification,
        lifecycle=body.lifecycle,
        request_id=str(request.state.request_id),
    ))


@router.get("/research-sources", response_model=list[ResearchSource])
async def list_sources(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    lifecycle: Annotated[ResearchSourceLifecycle | None, Query()] = None,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().list_sources(
        subject,
        request_id=str(request.state.request_id),
        lifecycle=lifecycle,
    ))


@router.get("/research-sources/{source_id}", response_model=ResearchSource)
async def source_detail(
    request: Request,
    source_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().source_detail(
        subject,
        source_id,
        request_id=str(request.state.request_id),
    ))


@router.patch("/research-sources/{source_id}", response_model=ResearchSource)
async def update_source(
    request: Request,
    source_id: uuid.UUID,
    body: SourceUpdateRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().update_source(
        subject,
        source_id,
        display_name=body.display_name,
        description=body.description,
        owner_subject_id=body.owner_subject_id,
        classification=body.classification,
        lifecycle=body.lifecycle,
        reason=body.reason,
        request_id=str(request.state.request_id),
    ))


@router.get("/settings", response_model=list[SettingView])
async def settings_overview(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().settings_overview(
        subject,
        request_id=str(request.state.request_id),
    ))


@router.put("/settings/{setting_key}", response_model=GovernanceSetting)
async def update_setting(
    request: Request,
    setting_key: str,
    body: SettingUpdateRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, GovernanceService().update_setting(
        subject,
        setting_key=setting_key,
        value=body.value,
        reason=body.reason,
        request_id=str(request.state.request_id),
    ))


@router.get(
    "/settings/{setting_key}/versions",
    response_model=list[GovernanceSetting],
)
async def setting_versions(
    request: Request,
    setting_key: str,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().setting_versions(
        subject,
        setting_key,
        request_id=str(request.state.request_id),
    ))


@router.post("/gaps/{gap_id}/priority", response_model=Gap)
async def set_gap_priority(
    request: Request,
    gap_id: uuid.UUID,
    body: GapPriorityRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().set_gap_priority(
        subject,
        gap_id,
        priority=body.priority,
        reason=body.reason,
        request_id=str(request.state.request_id),
    ))


@router.get("/subjects", response_model=list[SubjectAccountView])
async def list_subjects(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().list_subjects(
        subject,
        request_id=str(request.state.request_id),
        limit=limit,
    ))


@router.post(
    "/subjects/{subject_id}/bindings",
    response_model=SubjectAccountView,
)
async def mutate_binding(
    request: Request,
    subject_id: uuid.UUID,
    body: BindingRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().mutate_binding(
        subject,
        subject_id,
        binding=body.binding,
        key=body.key,
        operation=body.operation,
        reason=body.reason,
        request_id=str(request.state.request_id),
    ))


@router.get("/jobs/health", response_model=JobHealthReport)
async def job_health(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().job_health(
        subject,
        request_id=str(request.state.request_id),
    ))


@router.get("/pilot-readiness", response_model=PilotReadinessReport)
async def pilot_readiness(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, AdminGovernanceService().pilot_readiness(
        subject,
        request_id=str(request.state.request_id),
    ))


async def _refuse_truth_mutation(
    request: Request,
    family: str,
    rest: str,
    subject: Subject | None,
) -> Any:
    """AC-11 hard boundary: typed refusal plus an audit entry for the attempt."""
    if subject is None:
        return _error(request, 401, "authentication_required")
    async with UnitOfWork().transaction() as session:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action="admin.boundary.refused",
            result="deny",
            reason_code="admin_truth_immutable",
            request_id=str(request.state.request_id),
            resource_type="admin_boundary",
            details={
                "family": family,
                "path": rest,
                "method": request.method,
            },
        )
    return _error(request, 403, "admin_truth_immutable")


def _register_boundary(family: str) -> None:
    async def refuse(
        request: Request,
        rest: str,
        subject: Annotated[Subject | None, Depends(governance_subject)],
    ) -> Any:
        return await _refuse_truth_mutation(request, family, rest, subject)

    router.add_api_route(
        f"/{family}/{{rest:path}}",
        refuse,
        methods=BOUNDARY_METHODS,
        include_in_schema=False,
        name=f"admin_boundary_{family.replace('-', '_')}",
    )


for _family in TRUTH_FAMILIES:
    _register_boundary(_family)
