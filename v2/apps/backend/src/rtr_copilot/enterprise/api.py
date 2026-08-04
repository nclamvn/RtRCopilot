"""Typed operator API for TIP-025 enterprise trust governance."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from rtr_copilot.auth.models import Subject
from rtr_copilot.enterprise.models import (
    CorpusManifestRecord,
    CorpusManifestSpec,
    DecisionInput,
    DomainCreate,
    DomainRecord,
    EnterpriseReadiness,
    EvaluationRunRecord,
    EvaluationRunRequest,
    EvaluationSuiteCreate,
    EvaluationSuiteRecord,
    OntologyActivationRequest,
    OntologyRevisionCreate,
    OntologyRevisionRecord,
    ReleaseAttestation,
    ValidationResult,
)
from rtr_copilot.enterprise.repository import EnterpriseError
from rtr_copilot.enterprise.service import EnterpriseService
from rtr_copilot.governance.api import governance_subject


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorpusManifestCreate(StrictRequest):
    version: int = Field(gt=0)
    manifest: CorpusManifestSpec


class EnterpriseErrorDetail(BaseModel):
    code: str
    message: str


class EnterpriseErrorEnvelope(BaseModel):
    error: EnterpriseErrorDetail
    request_id: str


router = APIRouter(
    prefix="/api/v1/enterprise",
    tags=["enterprise-governance"],
    responses={
        status: {"model": EnterpriseErrorEnvelope} for status in (400, 401, 403, 404, 409, 422)
    },
)

NOT_FOUND = {
    "enterprise_domain_not_found",
    "enterprise_manifest_not_found",
    "enterprise_ontology_not_found",
    "enterprise_suite_not_found",
    "enterprise_evaluation_run_not_found",
    "enterprise_active_ontology_not_found",
}
UNPROCESSABLE = {
    "enterprise_owner_unknown",
    "enterprise_source_unavailable",
    "enterprise_source_fingerprint_mismatch",
    "enterprise_suite_domain_coverage_invalid",
    "enterprise_suite_coverage_stale",
}


def _error(request: Request, status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": "Enterprise governance request failed"},
            "request_id": str(request.state.request_id),
        },
    )


async def _call(request: Request, operation: Any) -> Any:
    try:
        return await operation
    except PermissionError as error:
        return _error(request, 403, str(error) or "forbidden")
    except EnterpriseError as error:
        status = 404 if error.code in NOT_FOUND else 422 if error.code in UNPROCESSABLE else 409
        return _error(request, status, error.code)
    except IntegrityError:
        return _error(request, 409, "enterprise_ledger_conflict")


def _authenticated(request: Request, subject: Subject | None) -> JSONResponse | None:
    return None if subject is not None else _error(request, 401, "authentication_required")


@router.post("/domains", response_model=DomainRecord)
async def propose_domain(
    request: Request,
    payload: DomainCreate,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().propose_domain(
            subject,
            payload,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/domains/{domain_id}/decide", response_model=DomainRecord)
async def decide_domain(
    request: Request,
    domain_id: uuid.UUID,
    payload: DecisionInput,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().decide_domain(
            subject,
            domain_id,
            payload,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/corpus-manifests", response_model=CorpusManifestRecord)
async def propose_manifest(
    request: Request,
    payload: CorpusManifestCreate,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().propose_manifest(
            subject,
            payload.manifest,
            version=payload.version,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/corpus-manifests/{manifest_id}/validate", response_model=ValidationResult)
async def validate_manifest(
    request: Request,
    manifest_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().validate_manifest(
            subject,
            manifest_id,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/corpus-manifests/{manifest_id}/decide", response_model=CorpusManifestRecord)
async def decide_manifest(
    request: Request,
    manifest_id: uuid.UUID,
    payload: DecisionInput,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().decide_manifest(
            subject,
            manifest_id,
            payload,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/ontology-revisions", response_model=OntologyRevisionRecord)
async def propose_ontology(
    request: Request,
    payload: OntologyRevisionCreate,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().propose_ontology(
            subject,
            payload.ontology,
            version=payload.version,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/ontology-revisions/{revision_id}/decide", response_model=OntologyRevisionRecord)
async def decide_ontology(
    request: Request,
    revision_id: uuid.UUID,
    payload: DecisionInput,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().decide_ontology(
            subject,
            revision_id,
            payload,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/evaluation-suites", response_model=EvaluationSuiteRecord)
async def propose_suite(
    request: Request,
    payload: EvaluationSuiteCreate,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().propose_suite(
            subject,
            payload.suite,
            version=payload.version,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/evaluation-suites/{suite_id}/decide", response_model=EvaluationSuiteRecord)
async def decide_suite(
    request: Request,
    suite_id: uuid.UUID,
    payload: DecisionInput,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().decide_suite(
            subject,
            suite_id,
            payload,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/evaluation-suites/{suite_id}/run", response_model=EvaluationRunRecord)
async def run_suite(
    request: Request,
    suite_id: uuid.UUID,
    payload: EvaluationRunRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().run_suite(
            subject,
            suite_id,
            payload.ontology_revision_id,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/ontology-revisions/{revision_id}/activate", response_model=ReleaseAttestation)
async def activate_ontology(
    request: Request,
    revision_id: uuid.UUID,
    payload: OntologyActivationRequest,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().activate_ontology(
            subject,
            revision_id,
            payload.evaluation_run_id,
            reason=payload.reason,
            request_id=str(request.state.request_id),
        ),
    )


@router.get("/readiness", response_model=EnterpriseReadiness)
async def readiness(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().readiness(
            subject,
            request_id=str(request.state.request_id),
        ),
    )


@router.get("/active-ontology", response_model=OntologyRevisionRecord)
async def active_ontology(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
) -> Any:
    denied = _authenticated(request, subject)
    if denied:
        return denied
    assert subject is not None
    return await _call(
        request,
        EnterpriseService().active_ontology(
            subject,
            request_id=str(request.state.request_id),
        ),
    )
