"""Research registry, research-scoped search and graduation gate endpoints.

Reuses the governance error envelope, subject resolution and signed-cursor
conventions; research responses are structurally zone-labeled (AC-07).
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from rtr_copilot.auth.models import Subject
from rtr_copilot.governance.api import (
    GovernanceErrorEnvelope,
    _error,
    call,
    governance_subject,
)
from rtr_copilot.governance.models import PackageImportState, ResearchTier
from rtr_copilot.research.models import (
    CandidateClaim,
    GraduationProposalInput,
    GraduationProposalPage,
    ResearchImportResult,
    ResearchPackagePage,
    ResearchPackageView,
    ResearchRecordPage,
    ResearchRecordView,
    ResearchSearchResponse,
)
from rtr_copilot.research.service import ResearchService

router = APIRouter(
    prefix="/api/v1",
    tags=["research"],
    responses={
        status: {"model": GovernanceErrorEnvelope}
        for status in (400, 401, 403, 404, 409, 422)
    },
)

PROPOSAL_STATES = frozenset({"proposed", "approved", "rejected"})


class ResearchImportRequest(BaseModel):
    staging_name: str = Field(min_length=1, max_length=128)


class ResearchSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4096)
    tiers: list[ResearchTier] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=10, ge=1, le=50)


class ProposalCreateRequest(BaseModel):
    research_record_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    claim: CandidateClaim
    target_record_key: str = Field(min_length=1, max_length=256)
    rationale: str = Field(min_length=1, max_length=4000)
    supersedes_proposal_id: uuid.UUID | None = None


class ProposalDecideRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


@router.post(
    "/research/packages/import",
    response_model=ResearchImportResult,
    status_code=201,
)
async def import_package(
    request: Request,
    body: ResearchImportRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().import_package(
        subject,
        body.staging_name,
        request_id=str(request.state.request_id),
    ))


@router.get("/research/packages", response_model=ResearchPackagePage)
async def list_packages(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    import_state: Annotated[PackageImportState | None, Query()] = None,
    source_key: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().list_packages(
        subject,
        request_id=str(request.state.request_id),
        import_state=import_state,
        source_key=source_key,
        cursor=cursor,
        limit=limit,
    ))


@router.get("/research/packages/{package_id}", response_model=ResearchPackageView)
async def package_detail(
    request: Request,
    package_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().package_detail(
        subject,
        package_id,
        request_id=str(request.state.request_id),
    ))


@router.get(
    "/research/packages/{package_id}/records",
    response_model=ResearchRecordPage,
)
async def list_records(
    request: Request,
    package_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().list_records(
        subject,
        package_id,
        request_id=str(request.state.request_id),
        cursor=cursor,
        limit=limit,
    ))


@router.get(
    "/research/records/{research_record_id}",
    response_model=ResearchRecordView,
)
async def record_detail(
    request: Request,
    research_record_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().record_detail(
        subject,
        research_record_id,
        request_id=str(request.state.request_id),
    ))


class ResearchScopeResponse(BaseModel):
    allowed: bool


@router.get("/research/scope", response_model=ResearchScopeResponse)
async def research_scope(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    """Content-free research-scope capability for the Ask UI (TIP-011).

    Returns only a boolean computed from the same policy predicate the
    research search uses; nothing is disclosed and no row is read, so there
    is nothing to audit and no existence to leak — this replaces the Ask
    page's per-load audited search probe.
    """
    if subject is None:
        return _error(request, 401, "authentication_required")
    return ResearchScopeResponse(allowed=ResearchService().search_scope_allowed(
        subject,
        str(request.state.request_id),
    ))


@router.post("/research/search", response_model=ResearchSearchResponse)
async def search(
    request: Request,
    body: ResearchSearchRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().search(
        subject,
        body.query,
        request_id=str(request.state.request_id),
        tiers=body.tiers,
        limit=body.limit,
    ))


@router.post("/graduation/proposals", status_code=201)
async def create_proposal(
    request: Request,
    body: ProposalCreateRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().propose(
        subject,
        GraduationProposalInput(
            research_record_ids=body.research_record_ids,
            claim=body.claim,
            target_record_key=body.target_record_key,
            rationale=body.rationale,
            supersedes_proposal_id=body.supersedes_proposal_id,
        ),
        request_id=str(request.state.request_id),
    ))


@router.get("/graduation/proposals", response_model=GraduationProposalPage)
async def list_proposals(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    state: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    if state is not None and state not in PROPOSAL_STATES:
        return _error(request, 404, "not_found")
    return await call(request, ResearchService().list_proposals(
        subject,
        request_id=str(request.state.request_id),
        state=state,
        cursor=cursor,
        limit=limit,
    ))


@router.get("/graduation/proposals/{proposal_id}")
async def proposal_detail(
    request: Request,
    proposal_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().proposal_detail(
        subject,
        proposal_id,
        request_id=str(request.state.request_id),
    ))


@router.post("/graduation/proposals/{proposal_id}/decide")
async def decide_proposal(
    request: Request,
    proposal_id: uuid.UUID,
    body: ProposalDecideRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    if subject is None:
        return _error(request, 401, "authentication_required")
    return await call(request, ResearchService().decide(
        subject,
        proposal_id,
        decision=body.decision,
        reason=body.reason,
        request_id=str(request.state.request_id),
    ))
