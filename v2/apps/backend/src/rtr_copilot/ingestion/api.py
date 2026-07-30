import uuid
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text

from rtr_copilot.auth.api import current_subject
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.errors import IngestionFailure, safe_message
from rtr_copilot.ingestion.models import (
    ErrorEnvelope,
    RetryResponse,
    UploadAccepted,
    UploadStatus,
    ViewerCapabilities,
    ViewerManifest,
    ViewerRendition,
)
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.ingestion.validators import VIEWER_KINDS
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository
from rtr_copilot.storage.s3 import S3ObjectStorage

router = APIRouter(prefix="/api/v1/files", tags=["files"])
policy = PolicyEngine(StructuredAuditSink())
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope},
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


async def file_subject(request: Request) -> Subject | None:
    settings = get_settings()
    return await current_subject(
        request,
        request.cookies.get(settings.session_cookie_name),
    )


def _error(
    request: Request,
    status: int,
    code: str,
    *,
    retryable: bool = False,
    job_id: uuid.UUID | None = None,
    failed_stage: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": safe_message(code),
                "retryable": retryable,
                "failed_stage": failed_stage,
            },
            "request_id": str(request.state.request_id),
            "job_id": str(job_id) if job_id else None,
        },
    )


async def _authorized_resource(
    subject: Subject,
    resource_id: uuid.UUID,
    *,
    action: str,
    request_id: str,
) -> tuple[ResourceRecord, bool] | None:
    uow = UnitOfWork()
    repository = ResourceRepository()
    async with uow.factory() as session:
        resource = await repository.get(session, resource_id)
        effective = await repository.effective_policy_attributes(
            session,
            resource_id,
            action=action,
            principal_ids={uuid.UUID(subject.user_id)},
        )
    if resource is None or effective is None:
        return None
    attributes = effective[0]
    decision = policy.decide(
        subject,
        action,
        attributes,
        PolicyContext(request_id=request_id),
    )
    return resource, decision.allow


async def _version_authorized(
    subject: Subject,
    version_id: uuid.UUID,
    *,
    action: str,
    request_id: str,
) -> tuple[dict[str, Any], bool] | None:
    uow = UnitOfWork()
    repository = ResourceRepository()
    async with uow.factory() as session:
        effective = await repository.effective_policy_attributes(
            session,
            version_id,
            action=action,
            principal_ids={uuid.UUID(subject.user_id)},
        )
        row = (await session.execute(text("""
            SELECT v.version_id,v.document_id,v.object_id,v.sha256,v.detected_mime,
              v.viewer_state,r.classification,r.lifecycle_state,d.source_id
            FROM document_versions v
            JOIN resources r ON r.resource_id=v.version_id
            JOIN documents d ON d.document_id=v.document_id
            WHERE v.version_id=:version_id
        """), {"version_id": version_id})).mappings().one_or_none()
        if effective is None or row is None:
            return None
        attributes = effective[0]
    decision = policy.decide(
        subject,
        action,
        attributes,
        PolicyContext(request_id=request_id),
    )
    return dict(row), decision.allow


async def _audit_access(
    *,
    subject: Subject,
    action: str,
    allow: bool,
    reason: str,
    request_id: str,
    resource_id: uuid.UUID | None,
    resource_type: str,
) -> None:
    async with UnitOfWork().transaction() as session:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=uuid.UUID(subject.user_id),
            action=action,
            result="allow" if allow else "deny",
            reason_code=reason,
            request_id=request_id,
            resource_id=resource_id,
            resource_type=resource_type,
        )


@router.post(
    "/uploads",
    status_code=202,
    response_model=UploadAccepted,
    responses=ERROR_RESPONSES,
)
async def upload(
    request: Request,
    subject: Annotated[Subject | None, Depends(file_subject)],
    parent_resource_id: Annotated[uuid.UUID, Header(alias="X-Parent-Resource-ID")],
    logical_name: Annotated[str, Header(alias="X-Logical-Name")],
    original_filename: Annotated[str, Header(alias="X-Original-Filename")],
    declared_sha256: Annotated[str | None, Header(alias="X-Content-SHA256")] = None,
    declared_mime: Annotated[str | None, Header(alias="X-Declared-MIME")] = None,
    content_length: Annotated[int | None, Header(alias="Content-Length")] = None,
) -> UploadAccepted | JSONResponse:
    request_id = str(request.state.request_id)
    if subject is None:
        return _error(request, 401, "authentication_required")
    authorization = await _authorized_resource(
        subject,
        parent_resource_id,
        action="upload",
        request_id=request_id,
    )
    if authorization is None or not authorization[1]:
        await _audit_access(
            subject=subject,
            action="upload.request",
            allow=False,
            reason="policy_denied",
            request_id=request_id,
            resource_id=(
                parent_resource_id if authorization is not None else None
            ),
            resource_type="upload_parent",
        )
        return _error(request, 403, "policy_denied")
    try:
        upload_id, job_id = await IngestionService().receive(
            request.stream(),
            content_length=content_length,
            parent=authorization[0],
            logical_name=logical_name,
            original_filename=original_filename,
            declared_mime=declared_mime,
            declared_sha256=declared_sha256,
            requested_by=uuid.UUID(subject.user_id),
            request_id=request_id,
        )
    except IngestionFailure as failure:
        await _audit_access(
            subject=subject,
            action="upload.rejected",
            allow=False,
            reason=failure.code,
            request_id=request_id,
            resource_id=parent_resource_id,
            resource_type="upload_parent",
        )
        return _error(
            request,
            413 if failure.code == "upload_too_large" else 422,
            failure.code,
            retryable=failure.retryable,
            failed_stage=failure.stage,
        )
    return UploadAccepted(
        upload_id=upload_id,
        job_id=job_id,
        state="quarantined",
        status_url=f"/api/v1/files/uploads/{upload_id}",
        request_id=request_id,
    )


async def _upload_status_row(upload_id: uuid.UUID) -> dict[str, Any] | None:
    async with UnitOfWork().factory() as session:
        row = (await session.execute(text("""
            SELECT upload_id,validation_job_id,state,progress,retryable,error_code,
              failed_stage,document_id,version_id,detected_mime,parent_resource_id,
              requested_by,request_id
            FROM upload_sessions WHERE upload_id=:upload_id
        """), {"upload_id": upload_id})).mappings().one_or_none()
        return dict(row) if row else None


@router.get(
    "/uploads/{upload_id}",
    response_model=UploadStatus,
    responses=ERROR_RESPONSES,
)
async def upload_status(
    request: Request,
    upload_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> UploadStatus | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    row = await _upload_status_row(upload_id)
    if row is None:
        return _error(request, 404, "not_found")
    authorization = await _authorized_resource(
        subject,
        row["document_id"] or row["parent_resource_id"],
        action="view",
        request_id=str(request.state.request_id),
    )
    if authorization is None or not authorization[1]:
        return _error(request, 404, "not_found")
    return UploadStatus(
        upload_id=upload_id,
        job_id=row["validation_job_id"],
        state=row["state"],
        progress=row["progress"],
        retryable=row["retryable"],
        error_code=row["error_code"],
        failed_stage=row["failed_stage"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        detected_mime=row["detected_mime"],
        request_id=str(request.state.request_id),
    )


@router.post(
    "/uploads/{upload_id}/retry",
    response_model=RetryResponse,
    responses=ERROR_RESPONSES,
)
async def retry_upload(
    request: Request,
    upload_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> RetryResponse | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    row = await _upload_status_row(upload_id)
    if row is None:
        return _error(request, 404, "not_found")
    authorization = await _authorized_resource(
        subject,
        row["document_id"] or row["parent_resource_id"],
        action="upload",
        request_id=str(request.state.request_id),
    )
    if authorization is None or not authorization[1]:
        return _error(request, 404, "not_found")
    if not row["retryable"] or row["state"] not in {"failed"}:
        return _error(request, 409, "retry_not_allowed", job_id=row["validation_job_id"])
    async with UnitOfWork().transaction() as session:
        job = (await session.execute(text("""
            SELECT status,resource_id,attempt FROM ingestion_jobs
            WHERE job_id=:job_id FOR UPDATE
        """), {"job_id": row["validation_job_id"]})).mappings().one_or_none()
        if job is None:
            return _error(request, 404, "not_found")
        if job["status"] in {"failed", "retry_wait"}:
            result = await session.execute(text("""
                UPDATE ingestion_jobs SET status='pending', next_attempt_at=now(),
                  error_code=NULL,error_fingerprint=NULL,updated_at=now()
                WHERE job_id=:job_id AND status IN ('failed','retry_wait')
            """), {"job_id": row["validation_job_id"]})
            if getattr(result, "rowcount", 0) != 1:
                return _error(request, 409, "retry_not_allowed")
            await session.execute(text("""
                UPDATE ingestion_outbox SET status='pending',available_at=now(),
                  updated_at=now() WHERE job_id=:job_id
            """), {"job_id": row["validation_job_id"]})
            already_audited = await session.scalar(text("""
                SELECT EXISTS(
                  SELECT 1 FROM audit_events
                  WHERE action='ingestion.job.retry'
                    AND details->>'job_id'=:job_id
                    AND details->>'attempt'=:attempt
                )
            """), {
                "job_id": str(row["validation_job_id"]),
                "attempt": str(job["attempt"]),
            })
            if not already_audited:
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=uuid.UUID(subject.user_id),
                    action="ingestion.job.retry",
                    result="success",
                    reason_code="manual_retry_requested",
                    request_id=str(request.state.request_id),
                    resource_id=job["resource_id"],
                    resource_type="document",
                    details={
                        "job_id": str(row["validation_job_id"]),
                        "attempt": job["attempt"],
                    },
                )
        elif job["status"] not in {"pending", "leased", "running"}:
            return _error(request, 409, "retry_not_allowed")
    return RetryResponse(
        upload_id=upload_id,
        job_id=row["validation_job_id"],
        state="pending",
        request_id=str(request.state.request_id),
    )


@router.get(
    "/versions/{version_id}/viewer-manifest",
    response_model=ViewerManifest,
    responses=ERROR_RESPONSES,
)
async def viewer_manifest(
    request: Request,
    version_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> ViewerManifest | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    request_id = str(request.state.request_id)
    authorized = await _version_authorized(
        subject,
        version_id,
        action="view",
        request_id=request_id,
    )
    if authorized is None or not authorized[1]:
        await _audit_access(
            subject=subject,
            action="viewer.manifest",
            allow=False,
            reason="policy_denied_or_not_visible",
            request_id=request_id,
            resource_id=version_id if authorized is not None else None,
            resource_type="document_version",
        )
        return _error(request, 404, "not_found")
    version = authorized[0]
    if version["viewer_state"] not in {"ready", "partial"}:
        return _error(request, 409, "viewer_not_ready")
    download = await _version_authorized(
        subject,
        version_id,
        action="download",
        request_id=request_id,
    )
    async with UnitOfWork().factory() as session:
        rows = (await session.execute(text("""
            SELECT r.rendition_id,r.kind,r.mime_type,r.quality_state,
              o.byte_size,o.sha256
            FROM renditions r JOIN object_blobs o ON o.object_id=r.object_id
            JOIN resources rr ON rr.resource_id=r.rendition_id
            WHERE r.version_id=:version_id AND r.status='ready'
              AND rr.lifecycle_state='active'
            ORDER BY r.kind,r.rendition_id
        """), {"version_id": version_id})).mappings().all()
    renditions = []
    for row in rows:
        rendition_authorization = await _authorized_resource(
            subject,
            row["rendition_id"],
            action="view",
            request_id=request_id,
        )
        if rendition_authorization is None or not rendition_authorization[1]:
            continue
        renditions.append(ViewerRendition(
            rendition_id=row["rendition_id"],
            kind=row["kind"],
            mime_type=row["mime_type"],
            byte_size=row["byte_size"],
            sha256=str(row["sha256"]),
            quality_state=row["quality_state"],
            content_url=f"/api/v1/files/renditions/{row['rendition_id']}/content",
        ))
    text_ready = any(
        item.kind in {
            "page_text_json",
            "structured_text_json",
            "workbook_manifest",
            "sheet_preview_json",
            "ocr_json",
            "transcript_json",
        }
        for item in renditions
    )
    mime = str(version["detected_mime"])
    warnings: list[str] = []
    if (
        (mime.startswith("image/") or mime == "application/pdf")
        and not any(item.kind == "ocr_json" for item in renditions)
    ):
        warnings.append("ocr_unavailable")
    if (
        (mime.startswith("audio/") or mime.startswith("video/"))
        and not any(item.kind == "transcript_json" for item in renditions)
    ):
        warnings.append("transcript_unavailable")
    await _audit_access(
        subject=subject,
        action="viewer.manifest",
        allow=True,
        reason="ready_renditions_filtered",
        request_id=request_id,
        resource_id=version_id,
        resource_type="document_version",
    )
    return ViewerManifest(
        version_id=version_id,
        source_sha256=str(version["sha256"]),
        detected_mime=mime,
        viewer_kind=VIEWER_KINDS[mime],
        state=version["viewer_state"],
        capabilities=ViewerCapabilities(
            preview=bool(renditions),
            text=text_ready,
            search_within_file=text_ready,
            deep_link=text_ready,
            download_original=bool(download and download[1]),
        ),
        renditions=renditions,
        quality={
            "ready_rendition_count": len(renditions),
            "partial_rendition_count": sum(
                item.quality_state != "complete" for item in renditions
            ),
        },
        warnings=warnings,
    )


@router.get(
    "/renditions/{rendition_id}/content",
    response_model=None,
    responses=ERROR_RESPONSES,
)
async def rendition_content(
    request: Request,
    rendition_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> StreamingResponse | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    async with UnitOfWork().factory() as session:
        row = (await session.execute(text("""
            SELECT r.version_id,r.mime_type,r.status,o.object_key
            FROM renditions r JOIN object_blobs o ON o.object_id=r.object_id
            JOIN resources rr ON rr.resource_id=r.rendition_id
            WHERE r.rendition_id=:rendition_id
              AND r.status='ready' AND rr.lifecycle_state='active'
        """), {"rendition_id": rendition_id})).mappings().one_or_none()
    if row is None:
        return _error(request, 404, "not_found")
    request_id = str(request.state.request_id)
    authorized = await _version_authorized(
        subject,
        row["version_id"],
        action="view",
        request_id=request_id,
    )
    rendition_authorized = await _authorized_resource(
        subject,
        rendition_id,
        action="view",
        request_id=request_id,
    )
    if (
        authorized is None
        or not authorized[1]
        or rendition_authorized is None
        or not rendition_authorized[1]
    ):
        await _audit_access(
            subject=subject,
            action="rendition.content",
            allow=False,
            reason="policy_denied",
            request_id=request_id,
            resource_id=rendition_id,
            resource_type="rendition",
        )
        return _error(request, 404, "not_found")
    body = await S3ObjectStorage(get_settings()).get_body(str(row["object_key"]))

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := body.read(1024 * 1024):
                yield chunk
        finally:
            body.close()

    await _audit_access(
        subject=subject,
        action="rendition.content",
        allow=True,
        reason="request_time_authorization",
        request_id=request_id,
        resource_id=rendition_id,
        resource_type="rendition",
    )
    return StreamingResponse(
        chunks(),
        media_type=str(row["mime_type"]),
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
