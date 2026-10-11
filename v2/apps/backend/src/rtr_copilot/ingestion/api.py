import base64
import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text

from rtr_copilot.auth.api import current_subject
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.errors import IngestionFailure, safe_message
from rtr_copilot.ingestion.jobs import RENDITION_GENERATOR_VERSION
from rtr_copilot.ingestion.models import (
    ErrorEnvelope,
    FileCatalogItem,
    FileCatalogPage,
    RetryResponse,
    UploadAccepted,
    UploadStatus,
    UploadTarget,
    UploadTargetList,
    ViewerCapabilities,
    ViewerManifest,
    ViewerRendition,
)
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.ingestion.validators import VIEWER_KINDS, normalize_display_name
from rtr_copilot.limits.backpressure import QueueSaturated, check_capacity
from rtr_copilot.limits.errors import limit_response
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
    416: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
VIEWER_FILTERS = frozenset(VIEWER_KINDS.values())
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
OFFICE_PREVIEW_MIMES = frozenset({
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
})
VISUAL_RENDITION_KINDS = frozenset({
    "preview_pdf",
    "safe_image_preview",
    "browser_audio",
    "browser_video",
    "workbook_manifest",
})


def _is_current_visual_rendition(
    *,
    mime: str,
    kind: str,
    generator_version: str,
) -> bool:
    return not (
        mime in OFFICE_PREVIEW_MIMES
        and kind == "preview_pdf"
        and generator_version != RENDITION_GENERATOR_VERSION
    )


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
        principal_ids = await _effective_principal_ids(session, subject)
        effective = await repository.effective_policy_attributes(
            session,
            resource_id,
            action=action,
            principal_ids=principal_ids,
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
        principal_ids = await _effective_principal_ids(session, subject)
        effective = await repository.effective_policy_attributes(
            session,
            version_id,
            action=action,
            principal_ids=principal_ids,
        )
        row = (await session.execute(text("""
            SELECT v.version_id,v.document_id,v.object_id,v.sha256,v.detected_mime,
              v.mime_type,v.byte_size,v.original_filename,v.viewer_state,
              r.classification,r.lifecycle_state,d.source_id
            FROM document_versions v
            JOIN resources r ON r.resource_id=v.version_id
            JOIN documents d ON d.document_id=v.document_id
            WHERE v.version_id=:version_id
        """), {"version_id": version_id})).mappings().one_or_none()
        if effective is None or row is None:
            return None
        from rtr_copilot.actions.execution import action_output_guard
        from rtr_copilot.actions.registry import ActionError

        try:
            await action_output_guard(session, uow, version_id, subject)
        except ActionError:
            return None
        attributes = effective[0]
    decision = policy.decide(
        subject,
        action,
        attributes,
        PolicyContext(request_id=request_id),
    )
    return dict(row), decision.allow


async def _effective_principal_ids(session: Any, subject: Subject) -> set[uuid.UUID]:
    """Resolve all persisted principal assignments at request time."""
    user_id = uuid.UUID(subject.user_id)
    rows = (await session.execute(text("""
        SELECT group_id AS principal_id FROM subject_groups
        WHERE subject_id=:subject_id AND valid_from <= now()
          AND (expires_at IS NULL OR expires_at > now())
        UNION
        SELECT role_id FROM subject_roles
        WHERE subject_id=:subject_id AND valid_from <= now()
          AND (expires_at IS NULL OR expires_at > now())
        UNION
        SELECT CAST(scope_key AS uuid) FROM subject_scopes
        WHERE subject_id=:subject_id AND valid_from <= now()
          AND (expires_at IS NULL OR expires_at > now())
          AND scope_key ~* :uuid_pattern
    """), {
        "subject_id": user_id,
        "uuid_pattern": (
            "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
    })).scalars().all()
    return {user_id, *(uuid.UUID(str(value)) for value in rows)}


def _normalized_query(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).split())


def _cursor_secret() -> bytes:
    return get_settings().sot_signing_secret.get_secret_value().encode()


def _encode_cursor(created_at: datetime, version_id: uuid.UUID) -> str:
    payload = json.dumps(
        {"at": created_at.isoformat(), "id": str(version_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(_cursor_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        canonical = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        if not hmac.compare_digest(canonical, value):
            raise ValueError
        payload, signature = raw[:-32], raw[-32:]
        expected = hmac.new(_cursor_secret(), payload, hashlib.sha256).digest()
        if len(payload) == 0 or not hmac.compare_digest(signature, expected):
            raise ValueError
        decoded = json.loads(payload)
        return datetime.fromisoformat(decoded["at"]), uuid.UUID(decoded["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("invalid_cursor") from error


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None:
        return None
    match = RANGE_PATTERN.fullmatch(value.strip())
    if match is None or "," in value or size <= 0:
        raise ValueError("invalid_range")
    start_raw, end_raw = match.groups()
    if not start_raw and not end_raw:
        raise ValueError("invalid_range")
    if not start_raw:
        suffix = int(end_raw)
        if suffix <= 0:
            raise ValueError("invalid_range")
        return max(0, size - suffix), size - 1
    start = int(start_raw)
    end = int(end_raw) if end_raw else size - 1
    if start >= size or end < start:
        raise ValueError("range_not_satisfiable")
    return start, min(end, size - 1)


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


@router.get("", response_model=FileCatalogPage, responses=ERROR_RESPONSES)
async def catalog(
    request: Request,
    subject: Annotated[Subject | None, Depends(file_subject)],
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: str | None = None,
    viewer_kind: str | None = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> FileCatalogPage | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    if viewer_kind is not None and viewer_kind not in VIEWER_FILTERS:
        return _error(request, 400, "invalid_filter")
    try:
        boundary = _decode_cursor(cursor) if cursor else None
    except ValueError:
        return _error(request, 400, "invalid_cursor")
    normalized_query = _normalized_query(query or "")
    items: list[FileCatalogItem] = []
    examined: tuple[datetime, uuid.UUID] | None = boundary
    exhausted = False
    repository = ResourceRepository()
    async with UnitOfWork().factory() as session:
        principal_ids = await _effective_principal_ids(session, subject)
        while len(items) < limit and not exhausted:
            rows = (await session.execute(text("""
                SELECT d.document_id,d.logical_name,v.version_id,v.original_filename,
                  v.object_id,v.detected_mime,v.viewer_state,v.byte_size,v.created_at,
                  r.classification,r.owner_subject_id,s.display_name AS owner_display_name,
                  COALESCE(q.ready_count,0) AS ready_count,
                  COALESCE(q.partial_count,0) AS partial_count
                FROM documents d
                JOIN document_versions v ON v.version_id=d.current_version_id
                JOIN resources r ON r.resource_id=v.version_id
                LEFT JOIN subjects s ON s.user_id=r.owner_subject_id
                LEFT JOIN LATERAL (
                  SELECT count(*) FILTER (WHERE rd.status='ready') AS ready_count,
                    count(*) FILTER (
                      WHERE rd.status='ready' AND rd.quality_state<>'complete'
                    ) AS partial_count
                  FROM renditions rd WHERE rd.version_id=v.version_id
                ) q ON true
                WHERE r.lifecycle_state='active'
                  AND (
                    CAST(:at AS timestamptz) IS NULL
                    OR (v.created_at,v.version_id)
                      < (CAST(:at AS timestamptz),CAST(:cursor_id AS uuid))
                  )
                ORDER BY v.created_at DESC,v.version_id DESC
                LIMIT 100
            """), {
                "at": examined[0] if examined else None,
                "cursor_id": examined[1] if examined else None,
            })).mappings().all()
            if not rows:
                exhausted = True
                break
            for row in rows:
                examined = (row["created_at"], row["version_id"])
                mime = str(row["detected_mime"])
                kind = VIEWER_KINDS.get(mime)
                if kind is None or (viewer_kind is not None and kind != viewer_kind):
                    continue
                if normalized_query and normalized_query not in _normalized_query(
                    f"{row['logical_name']} {row['original_filename']}",
                ):
                    continue
                effective = await repository.effective_policy_attributes(
                    session,
                    row["version_id"],
                    action="view",
                    principal_ids=principal_ids,
                )
                if effective is None or not policy.decide(
                    subject,
                    "view",
                    effective[0],
                    PolicyContext(request_id=str(request.state.request_id)),
                ).allow:
                    continue
                downloadable = await repository.effective_policy_attributes(
                    session,
                    row["version_id"],
                    action="download",
                    principal_ids=principal_ids,
                )
                downloadable_object = await repository.effective_policy_attributes(
                    session,
                    row["object_id"],
                    action="download",
                    principal_ids=principal_ids,
                )
                can_download = bool(
                    downloadable
                    and downloadable_object
                    and policy.decide(
                        subject,
                        "download",
                        downloadable[0],
                        PolicyContext(request_id=str(request.state.request_id)),
                    ).allow
                    and policy.decide(
                        subject,
                        "download",
                        downloadable_object[0],
                        PolicyContext(request_id=str(request.state.request_id)),
                    ).allow
                )
                warnings = []
                if row["partial_count"]:
                    warnings.append("partial_rendition")
                if kind in {"docx", "pptx"}:
                    warnings.append("semantic_preview_layout_may_differ")
                items.append(FileCatalogItem(
                    document_id=row["document_id"],
                    version_id=row["version_id"],
                    logical_name=row["logical_name"],
                    display_filename=row["original_filename"],
                    detected_mime=mime,
                    viewer_kind=kind,
                    viewer_state=row["viewer_state"],
                    byte_size=row["byte_size"],
                    classification=row["classification"],
                    owner_display_name=row["owner_display_name"] or None,
                    version_created_at=row["created_at"],
                    quality={
                        "ready_rendition_count": row["ready_count"],
                        "partial_rendition_count": row["partial_count"],
                    },
                    warnings=warnings,
                    can_download=can_download,
                ))
                if len(items) == limit:
                    break
            exhausted = len(rows) < 100
    next_cursor = (
        _encode_cursor(*examined)
        if examined is not None and not exhausted and len(items) == limit
        else None
    )
    return FileCatalogPage(items=items, next_cursor=next_cursor)


@router.get(
    "/upload-targets",
    response_model=UploadTargetList,
    responses=ERROR_RESPONSES,
)
async def upload_targets(
    request: Request,
    subject: Annotated[Subject | None, Depends(file_subject)],
) -> UploadTargetList | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    results: list[UploadTarget] = []
    repository = ResourceRepository()
    async with UnitOfWork().factory() as session:
        principal_ids = await _effective_principal_ids(session, subject)
        boundary: tuple[str, uuid.UUID] | None = None
        while True:
            rows = (await session.execute(text("""
                SELECT s.source_id,s.name,r.classification
                FROM sources s JOIN resources r ON r.resource_id=s.source_id
                WHERE r.lifecycle_state='active'
                  AND (
                    CAST(:after_name AS text) IS NULL
                    OR (lower(s.name),s.source_id)
                      > (CAST(:after_name AS text),CAST(:after_id AS uuid))
                  )
                ORDER BY lower(s.name),s.source_id
                LIMIT 200
            """), {
                "after_name": boundary[0] if boundary else None,
                "after_id": boundary[1] if boundary else None,
            })).mappings().all()
            if not rows:
                break
            for row in rows:
                effective = await repository.effective_policy_attributes(
                    session,
                    row["source_id"],
                    action="upload",
                    principal_ids=principal_ids,
                )
                if effective and policy.decide(
                    subject,
                    "upload",
                    effective[0],
                    PolicyContext(request_id=str(request.state.request_id)),
                ).allow:
                    results.append(UploadTarget(
                        target_id=row["source_id"],
                        label=row["name"],
                        classification=row["classification"],
                    ))
            last = rows[-1]
            boundary = (str(last["name"]).lower(), last["source_id"])
            if len(rows) < 200:
                break
    return UploadTargetList(items=results)


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
        async with UnitOfWork().factory() as session:
            await check_capacity(
                session,
                "ingestion",
                retry_after=get_settings().limits_queue_retry_after_seconds,
            )
    except QueueSaturated as saturated:
        async with UnitOfWork().transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action="ingestion.queue.shed",
                result="deny",
                reason_code="queue_saturated",
                request_id=request_id,
                resource_type="request_limit",
                details={
                    "family": "ingestion",
                    "outstanding": saturated.outstanding,
                    "cap": saturated.cap,
                    "parent_resource_id": str(parent_resource_id),
                },
            )
        return limit_response(
            request_id, "queue_saturated", retry_after=saturated.retry_after,
        )
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
    response: Response,
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
    object_download = await _authorized_resource(
        subject,
        version["object_id"],
        action="download",
        request_id=request_id,
    )
    async with UnitOfWork().factory() as session:
        rows = (await session.execute(text("""
            SELECT r.rendition_id,r.kind,r.mime_type,r.quality_state,
              r.generator_version,
              o.byte_size,o.sha256
            FROM renditions r JOIN object_blobs o ON o.object_id=r.object_id
            JOIN resources rr ON rr.resource_id=r.rendition_id
            WHERE r.version_id=:version_id AND r.status='ready'
              AND rr.lifecycle_state='active'
            ORDER BY r.kind,r.rendition_id
        """), {"version_id": version_id})).mappings().all()
    renditions = []
    mime = str(version["detected_mime"])
    stale_office_preview = False
    for row in rows:
        if not _is_current_visual_rendition(
            mime=mime,
            kind=str(row["kind"]),
            generator_version=str(row["generator_version"]),
        ):
            stale_office_preview = True
            continue
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
    warnings: list[str] = []
    if stale_office_preview:
        warnings.append("office_preview_stale")
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
    response.headers["Cache-Control"] = "private, no-store"
    return ViewerManifest(
        version_id=version_id,
        source_sha256=str(version["sha256"]),
        detected_mime=mime,
        viewer_kind=VIEWER_KINDS[mime],
        state=version["viewer_state"],
        capabilities=ViewerCapabilities(
            preview=any(item.kind in VISUAL_RENDITION_KINDS for item in renditions),
            text=text_ready,
            search_within_file=text_ready,
            deep_link=text_ready,
            download_original=bool(
                download and download[1] and object_download and object_download[1]
            ),
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
    "/versions/{version_id}/original",
    response_model=None,
    responses=ERROR_RESPONSES,
)
async def original_content(
    request: Request,
    version_id: uuid.UUID,
    subject: Annotated[Subject | None, Depends(file_subject)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    request_id = str(request.state.request_id)
    version_authorized = await _version_authorized(
        subject,
        version_id,
        action="download",
        request_id=request_id,
    )
    if version_authorized is None:
        return _error(request, 404, "not_found")
    version, version_allowed = version_authorized
    object_authorized = await _authorized_resource(
        subject,
        version["object_id"],
        action="download",
        request_id=request_id,
    )
    allowed = bool(version_allowed and object_authorized and object_authorized[1])
    if not allowed:
        await _audit_access(
            subject=subject,
            action="original.content",
            allow=False,
            reason="policy_denied",
            request_id=request_id,
            resource_id=version_id,
            resource_type="document_version",
        )
        return _error(request, 404, "not_found")
    async with UnitOfWork().factory() as session:
        row = (await session.execute(text("""
            SELECT o.object_key,o.byte_size,o.sha256
            FROM object_blobs o WHERE o.object_id=:object_id
              AND o.storage_state='available'
        """), {"object_id": version["object_id"]})).mappings().one_or_none()
    if row is None:
        return _error(request, 404, "not_found")
    size = int(row["byte_size"])
    try:
        byte_range = _parse_range(range_header, size)
    except ValueError:
        failure = _error(request, 416, "range_not_satisfiable")
        failure.headers["Content-Range"] = f"bytes */{size}"
        failure.headers["Accept-Ranges"] = "bytes"
        return failure
    body = await S3ObjectStorage(get_settings()).get_body(
        str(row["object_key"]),
        byte_range=byte_range,
    )

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := body.read(1024 * 1024):
                yield chunk
        finally:
            body.close()

    await _audit_access(
        subject=subject,
        action="original.content",
        allow=True,
        reason="request_time_authorization",
        request_id=request_id,
        resource_id=version_id,
        resource_type="document_version",
    )
    filename = normalize_display_name(str(version["original_filename"]))
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Content-Length": str(
            byte_range[1] - byte_range[0] + 1 if byte_range else size
        ),
        "ETag": f'"{row["sha256"]}"',
        "X-Content-Type-Options": "nosniff",
    }
    if byte_range:
        headers["Content-Range"] = f"bytes {byte_range[0]}-{byte_range[1]}/{size}"
    return StreamingResponse(
        chunks(),
        status_code=206 if byte_range else 200,
        media_type=str(version["mime_type"]),
        headers=headers,
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
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse | JSONResponse:
    if subject is None:
        return _error(request, 401, "authentication_required")
    async with UnitOfWork().factory() as session:
        row = (await session.execute(text("""
            SELECT r.version_id,r.mime_type,r.status,o.object_key,o.byte_size,o.sha256
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
    size = int(row["byte_size"])
    try:
        byte_range = _parse_range(range_header, size)
    except ValueError:
        failure = _error(request, 416, "range_not_satisfiable")
        failure.headers["Content-Range"] = f"bytes */{size}"
        failure.headers["Accept-Ranges"] = "bytes"
        return failure
    body = await S3ObjectStorage(get_settings()).get_body(
        str(row["object_key"]),
        byte_range=byte_range,
    )

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
        status_code=206 if byte_range else 200,
        media_type=str(row["mime_type"]),
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "Content-Length": str(
                byte_range[1] - byte_range[0] + 1 if byte_range else size
            ),
            **(
                {"Content-Range": f"bytes {byte_range[0]}-{byte_range[1]}/{size}"}
                if byte_range else {}
            ),
            "ETag": f'"{row["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
