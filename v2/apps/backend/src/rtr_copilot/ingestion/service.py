import asyncio
import hashlib
import io
import json
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.config import Settings, get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.errors import IngestionFailure
from rtr_copilot.ingestion.extractors import Artifact, canonical_json, extract_required
from rtr_copilot.ingestion.jobs import JobClaim, JobRepository
from rtr_copilot.ingestion.malware import ClamAVAdapter, MalwareAdapter
from rtr_copilot.ingestion.metrics import (
    QUARANTINE_DEPTH,
    RENDITION_BYTES,
    RENDITIONS,
    STAGE_DURATION,
    UPLOAD_BYTES,
    UPLOADS,
)
from rtr_copilot.ingestion.models import DetectionResult, RenditionProvenance
from rtr_copilot.ingestion.private_engines import (
    LocalTesseractOCR,
    LocalVoskTranscript,
)
from rtr_copilot.ingestion.sandbox import ProcessSandbox
from rtr_copilot.ingestion.validators import (
    MIME_EXTENSIONS,
    normalize_display_name,
    validate_content,
)
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository
from rtr_copilot.storage.s3 import S3ObjectStorage, StoredObject


def _state_result(code: str) -> str:
    return "rejected" if code in {
        "unknown_format",
        "declared_mime_mismatch",
        "extension_mismatch",
        "suspicious_polyglot",
        "malformed_content",
        "archive_path_unsafe",
        "archive_budget_exceeded",
        "archive_entry_unsupported",
        "ooxml_active_content",
        "pdf_active_content",
        "image_budget_exceeded",
        "media_budget_exceeded",
        "malware_detected",
    } else "failed"


class IngestionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage: S3ObjectStorage | None = None,
        uow: UnitOfWork | None = None,
        scanner: MalwareAdapter | None = None,
        sandbox: ProcessSandbox | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or S3ObjectStorage(self.settings)
        self.uow = uow or UnitOfWork()
        self.jobs = JobRepository(self.uow)
        self.scanner = scanner or ClamAVAdapter(self.settings)
        self.sandbox = sandbox or ProcessSandbox(
            timeout_seconds=self.settings.ingestion_tool_timeout_seconds,
            temp_bytes=self.settings.ingestion_temp_bytes,
        )

    async def _maintain_lease(
        self,
        claim: JobClaim,
        stop: asyncio.Event,
    ) -> None:
        interval = max(1, self.settings.ingestion_lease_seconds // 3)
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                try:
                    await self.jobs.heartbeat(claim, settings=self.settings)
                except RuntimeError:
                    return

    async def receive(
        self,
        stream: AsyncIterator[bytes],
        *,
        content_length: int | None,
        parent: ResourceRecord,
        logical_name: str,
        original_filename: str,
        declared_mime: str | None,
        declared_sha256: str | None,
        requested_by: uuid.UUID,
        request_id: str,
        defer_publication: bool = False,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        if (
            content_length is not None
            and content_length > self.settings.ingestion_max_upload_bytes
        ):
            raise IngestionFailure("upload_too_large", stage="receive")
        safe_name = normalize_display_name(original_filename)
        safe_logical_name = normalize_display_name(logical_name)
        upload_id = uuid.uuid4()
        object_id = uuid.uuid4()
        document_id = uuid.uuid4()
        key = f"quarantine/{upload_id}/{object_id}"
        digest = hashlib.sha256()
        received = 0
        with tempfile.TemporaryDirectory(prefix="rtr-receive-") as directory:
            path = Path(directory) / "upload.bin"
            try:
                with path.open("w+b") as target:
                    async for chunk in stream:
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > self.settings.ingestion_max_upload_bytes:
                            raise IngestionFailure("upload_too_large", stage="receive")
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    target.seek(0)
                    if content_length is not None and received != content_length:
                        raise IngestionFailure(
                            "content_length_mismatch",
                            stage="receive",
                        )
                    actual_sha = digest.hexdigest()
                    if (
                        declared_sha256
                        and actual_sha != declared_sha256.strip().lower()
                    ):
                        raise IngestionFailure("checksum_mismatch", stage="receive")
                    stored = await self.storage.upload_stream(
                        key=key,
                        stream=target,
                        mime_type="application/octet-stream",
                        declared_sha256=actual_sha,
                        upload_state="quarantine",
                        extra_metadata={"upload-id": str(upload_id)},
                    )
            except BaseException:
                await self.storage.delete(key)
                raise
        async with self.uow.transaction() as session:
            document_resource = ResourceRecord(
                resource_id=document_id,
                resource_type="document",
                owner_subject_id=requested_by,
                classification=parent.classification,
                source_zone=parent.source_zone,
                department_id=parent.department_id,
                project_id=parent.project_id,
                lifecycle_state="draft",
            )
            object_resource = ResourceRecord(
                resource_id=object_id,
                resource_type="object",
                owner_subject_id=requested_by,
                classification=parent.classification,
                source_zone=parent.source_zone,
                department_id=parent.department_id,
                project_id=parent.project_id,
                lifecycle_state="quarantined",
            )
            await ResourceRepository().create(session, document_resource)
            await ResourceRepository().create(session, object_resource)
            await session.execute(text("""
                INSERT INTO documents(document_id, source_id, logical_name)
                VALUES (
                  :document_id,
                  (SELECT source_id FROM sources WHERE source_id=:parent_id),
                  :logical_name
                )
            """), {
                "document_id": document_id,
                "parent_id": parent.resource_id,
                "logical_name": safe_logical_name,
            })
            await session.execute(text("""
                INSERT INTO object_blobs(
                  object_id,bucket,object_key,sha256,byte_size,mime_type,etag,
                  storage_state,created_by
                ) VALUES (
                  :object_id,:bucket,:object_key,:sha256,:byte_size,
                  'application/octet-stream',:etag,'staged',:created_by
                )
            """), {
                "object_id": object_id,
                "bucket": stored.bucket,
                "object_key": stored.key,
                "sha256": stored.sha256,
                "byte_size": stored.byte_size,
                "etag": stored.etag,
                "created_by": requested_by,
            })
            await session.execute(text("""
                INSERT INTO upload_sessions(
                  upload_id,parent_resource_id,document_id,object_id,requested_by,
                  request_id,state,progress,logical_name,original_filename,
                  declared_mime,sha256,byte_size
                ) VALUES (
                  :upload_id,:parent_id,:document_id,:object_id,:requested_by,
                  :request_id,'quarantined',10,:logical_name,:original_filename,
                  :declared_mime,:sha256,:byte_size
                )
            """), {
                "upload_id": upload_id,
                "parent_id": parent.resource_id,
                "document_id": document_id,
                "object_id": object_id,
                "requested_by": requested_by,
                "request_id": request_id,
                "logical_name": safe_logical_name,
                "original_filename": safe_name,
                "declared_mime": declared_mime,
                "sha256": stored.sha256,
                "byte_size": stored.byte_size,
            })
            if defer_publication:
                await session.execute(text("""
                    UPDATE upload_sessions SET publication_deferred=true
                    WHERE upload_id=:upload_id
                """), {"upload_id": upload_id})
            job_id = await self.jobs.create(
                session,
                upload_id=upload_id,
                version_id=None,
                resource_id=document_id,
                job_type="validate",
                output_kind=None,
                idempotency_key=f"validate:{upload_id}:{stored.sha256}",
                requested_by=requested_by,
                request_id=request_id,
                input_sha256=stored.sha256,
                settings=self.settings,
            )
            await session.execute(text("""
                UPDATE upload_sessions SET validation_job_id=:job_id
                WHERE upload_id=:upload_id
            """), {"job_id": job_id, "upload_id": upload_id})
            for action, reason in (
                ("upload.requested", "authorized_upload"),
                ("upload.completed", "quarantine_stream_complete"),
            ):
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=requested_by,
                    action=action,
                    result="success",
                    reason_code=reason,
                    request_id=request_id,
                    resource_id=document_id,
                    resource_type="upload",
                    details={"upload_id": str(upload_id), "byte_size": received},
                )
        QUARANTINE_DEPTH.inc()
        return upload_id, job_id

    async def _source_to_temp(
        self,
        *,
        key: str,
        sha256: str,
        byte_size: int,
        directory: str,
    ) -> Path:
        await self.storage.verify(
            key=key,
            expected_sha256=sha256,
            expected_size=byte_size,
            recompute=True,
        )
        path = Path(directory) / "source.bin"
        with path.open("w+b") as target:
            await self.storage.download_to(key, target)
        return path

    async def _transition_upload(
        self,
        upload_id: uuid.UUID,
        *,
        expected: set[str],
        state: str,
        progress: int,
        request_id: str,
        actor_id: uuid.UUID,
        reason: str,
    ) -> None:
        async with self.uow.transaction() as session:
            result = await session.execute(text("""
                UPDATE upload_sessions SET state=:state, progress=:progress,
                  updated_at=now() WHERE upload_id=:upload_id
                  AND state=ANY(:expected)
                RETURNING document_id
            """), {
                "state": state,
                "progress": progress,
                "upload_id": upload_id,
                "expected": sorted(expected),
            })
            if getattr(result, "rowcount", 0) != 1:
                raise RuntimeError("upload_state_conflict")
            document_id = result.scalar_one()
            await AuditRepository().append(
                session,
                actor_kind="service",
                actor_user_id=None,
                action=f"upload.{state}",
                result="success",
                reason_code=reason,
                request_id=request_id,
                resource_id=document_id,
                resource_type="upload",
                details={"requested_by": str(actor_id), "progress": progress},
            )

    async def _upload_row(self, upload_id: uuid.UUID) -> dict[str, Any]:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT u.*, o.bucket, o.object_key, o.mime_type, o.etag,
                  r.classification, r.source_zone, r.department_id, r.project_id
                FROM upload_sessions u
                JOIN object_blobs o ON o.object_id=u.object_id
                JOIN resources r ON r.resource_id=u.document_id
                WHERE u.upload_id=:upload_id
            """), {"upload_id": upload_id})).mappings().one()
            return dict(row)

    async def _finalize_upload(
        self,
        session: AsyncSession,
        claim: JobClaim,
        row: dict[str, Any],
        detection: DetectionResult,
    ) -> uuid.UUID:
        version_id = uuid.uuid4()
        await ResourceRepository().create(
            session,
            ResourceRecord(
                resource_id=version_id,
                resource_type="document_version",
                owner_subject_id=claim.requested_by,
                classification=row["classification"],
                source_zone=row["source_zone"],
                department_id=row["department_id"],
                project_id=row["project_id"],
                lifecycle_state=(
                    "quarantined" if row["publication_deferred"] else "active"
                ),
            ),
        )
        await session.execute(text("""
            INSERT INTO document_versions(
              version_id,document_id,version_no,object_id,original_filename,
              mime_type,sha256,byte_size,created_by,detected_mime,viewer_state
            ) VALUES (
              :version_id,:document_id,1,:object_id,:filename,:mime,
              :sha256,:byte_size,:created_by,:mime,'processing'
            )
        """), {
            "version_id": version_id,
            "document_id": row["document_id"],
            "object_id": row["object_id"],
            "filename": row["original_filename"],
            "mime": detection.detected_mime,
            "sha256": row["sha256"],
            "byte_size": row["byte_size"],
            "created_by": claim.requested_by,
        })
        await session.execute(text("""
            UPDATE documents SET current_version_id=:version_id, updated_at=now()
            WHERE document_id=:document_id;
        """), {"version_id": version_id, "document_id": row["document_id"]})
        await session.execute(text("""
            UPDATE resources SET lifecycle_state=:lifecycle, updated_at=now()
            WHERE resource_id IN (:document_id,:object_id)
        """), {
            "document_id": row["document_id"],
            "object_id": row["object_id"],
            "lifecycle": (
                "quarantined" if row["publication_deferred"] else "active"
            ),
        })
        await session.execute(text("""
            UPDATE object_blobs SET storage_state=:storage_state,
              mime_type=:mime, verified_at=now() WHERE object_id=:object_id
        """), {
            "mime": detection.detected_mime, "object_id": row["object_id"],
            "storage_state": (
                "staged" if row["publication_deferred"] else "available"
            ),
        })
        render_job = await self.jobs.create(
            session,
            upload_id=None,
            version_id=version_id,
            resource_id=version_id,
            job_type="render",
            output_kind="required_bundle",
            idempotency_key=f"render:{version_id}:{claim.pipeline_version}",
            requested_by=claim.requested_by,
            request_id=claim.request_id,
            input_sha256=claim.input_sha256,
            settings=self.settings,
        )
        await session.execute(text("""
            UPDATE upload_sessions SET state='accepted', progress=70,
              detected_mime=:mime, version_id=:version_id, retryable=false,
              error_code=NULL, error_fingerprint=NULL, failed_stage=NULL,
              updated_at=now(), finished_at=now()
            WHERE upload_id=:upload_id AND state='scanning'
        """), {
            "mime": detection.detected_mime,
            "version_id": version_id,
            "upload_id": claim.upload_id,
        })
        await AuditRepository().append(
            session,
            actor_kind="service",
            actor_user_id=None,
            action="upload.accepted",
            result="success",
            reason_code="validation_and_scan_clean",
            request_id=claim.request_id,
            resource_id=version_id,
            resource_type="document_version",
            details={
                "upload_id": str(claim.upload_id),
                "render_job_id": str(render_job),
                "detected_mime": detection.detected_mime,
                "source_sha256": claim.input_sha256,
            },
        )
        await self.jobs.succeeded(session, claim, reason="accepted_version_created")
        return version_id

    async def _record_upload_failure(
        self,
        claim: JobClaim,
        failure: IngestionFailure,
    ) -> None:
        state = _state_result(failure.code)
        async with self.uow.transaction() as session:
            await session.execute(text("""
                UPDATE upload_sessions SET state=:state, progress=100,
                  error_code=:code, error_fingerprint=:fingerprint,
                  retryable=:retryable, failed_stage=:stage, updated_at=now(),
                  finished_at=CASE WHEN NOT :retryable THEN now() ELSE NULL END
                WHERE upload_id=:upload_id
            """), {
                "state": state,
                "code": failure.code,
                "fingerprint": failure.fingerprint,
                "retryable": failure.retryable,
                "stage": failure.stage,
                "upload_id": claim.upload_id,
            })
            await AuditRepository().append(
                session,
                actor_kind="service",
                actor_user_id=None,
                action=f"upload.{state}",
                result="failure",
                reason_code=failure.code,
                request_id=claim.request_id,
                resource_id=claim.resource_id,
                resource_type="upload",
                details={
                    "job_id": str(claim.job_id),
                    "retryable": failure.retryable,
                    "failed_stage": failure.stage,
                },
            )
        await self.jobs.failed(
            claim,
            code=failure.code,
            fingerprint=failure.fingerprint,
            retryable=failure.retryable,
            quarantined=failure.code == "malware_detected",
        )
        UPLOADS.labels("failure", failure.code, "unknown").inc()

    async def _process_validation(self, claim: JobClaim) -> None:
        if claim.upload_id is None:
            raise RuntimeError("validation_job_missing_upload")
        row = await self._upload_row(claim.upload_id)
        await self._transition_upload(
            claim.upload_id,
            expected={"quarantined", "failed"},
            state="validating",
            progress=25,
            request_id=claim.request_id,
            actor_id=claim.requested_by,
            reason="validation_started",
        )
        with tempfile.TemporaryDirectory(prefix="rtr-validate-") as directory:
            path = await self._source_to_temp(
                key=str(row["object_key"]),
                sha256=claim.input_sha256,
                byte_size=int(row["byte_size"]),
                directory=directory,
            )
            detection = await asyncio.to_thread(
                validate_content,
                path,
                filename=str(row["original_filename"]),
                declared_mime=row["declared_mime"],
                settings=self.settings,
                sandbox=self.sandbox,
            )
            await self._transition_upload(
                claim.upload_id,
                expected={"validating"},
                state="scanning",
                progress=45,
                request_id=claim.request_id,
                actor_id=claim.requested_by,
                reason="structural_validation_passed",
            )
            scan = await self.scanner.scan(path)
            if scan.result != "clean":
                raise IngestionFailure("malware_detected", stage="scan")
        async with self.uow.transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="service",
                actor_user_id=None,
                action="malware.scan",
                result="success",
                reason_code="clean",
                request_id=claim.request_id,
                resource_id=claim.resource_id,
                resource_type="upload",
                details={"engine": scan.engine, "signature_version": scan.signature_version},
            )
        async with self.uow.transaction() as session:
            await self._finalize_upload(session, claim, row, detection)
        QUARANTINE_DEPTH.dec()
        UPLOAD_BYTES.labels(detection.detected_mime).inc(int(row["byte_size"]))
        UPLOADS.labels("accepted", "clean", detection.detected_mime).inc()

    async def _version_row(self, version_id: uuid.UUID) -> dict[str, Any]:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT v.version_id,v.document_id,v.object_id,v.sha256,v.byte_size,
                  v.detected_mime,o.object_key,o.bucket,r.owner_subject_id,
                  r.classification,r.source_zone,r.department_id,r.project_id
                  ,COALESCE(u.publication_deferred,false) publication_deferred
                FROM document_versions v
                JOIN object_blobs o ON o.object_id=v.object_id
                JOIN resources r ON r.resource_id=v.version_id
                LEFT JOIN upload_sessions u ON u.version_id=v.version_id
                WHERE v.version_id=:version_id
            """), {"version_id": version_id})).mappings().one()
            return dict(row)

    async def _upload_artifact(
        self,
        artifact: Artifact,
        *,
        object_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> StoredObject:
        return await self.storage.upload_stream(
            key=f"renditions/{object_id}",
            stream=io.BytesIO(artifact.payload),
            mime_type=artifact.mime_type,
            declared_sha256=artifact.sha256,
            upload_state="rendition-staged",
            extra_metadata={"job-id": str(job_id)},
        )

    async def _process_rendition(self, claim: JobClaim) -> None:
        if claim.version_id is None:
            raise RuntimeError("rendition_job_missing_version")
        row = await self._version_row(claim.version_id)
        with tempfile.TemporaryDirectory(prefix="rtr-render-") as directory:
            path = await self._source_to_temp(
                key=str(row["object_key"]),
                sha256=claim.input_sha256,
                byte_size=int(row["byte_size"]),
                directory=directory,
            )
            detection = await asyncio.to_thread(
                validate_content,
                path,
                filename="source" + sorted(
                    MIME_EXTENSIONS[str(row["detected_mime"])],
                )[0],
                declared_mime=str(row["detected_mime"]),
                settings=self.settings,
                sandbox=self.sandbox,
            )
            source_extension = sorted(
                MIME_EXTENSIONS[detection.detected_mime],
            )[0]
            typed_path = path.with_name(f"source{source_extension}")
            path.replace(typed_path)
            path = typed_path
            artifacts = await asyncio.to_thread(
                extract_required,
                path,
                mime=detection.detected_mime,
                structural=detection.structural,
                settings=self.settings,
                sandbox=self.sandbox,
            )
            optional_failures: list[IngestionFailure] = []
            if detection.detected_mime.startswith("image/") or (
                detection.detected_mime == "application/pdf"
            ):
                try:
                    artifacts.append(await asyncio.to_thread(
                        LocalTesseractOCR(
                            self.settings,
                            self.sandbox,
                        ).artifact_for_input,
                        path,
                        mime=detection.detected_mime,
                    ))
                except IngestionFailure as failure:
                    if failure.code != "ocr_not_applicable":
                        optional_failures.append(failure)
            if detection.detected_mime.startswith(("audio/", "video/")):
                try:
                    artifacts.extend(await asyncio.to_thread(
                        LocalVoskTranscript(
                            self.settings,
                            self.sandbox,
                        ).transcribe,
                        path,
                        duration_ms=int(detection.structural["duration_ms"]),
                    ))
                except IngestionFailure as failure:
                    optional_failures.append(failure)
            published: list[dict[str, Any]] = []
            for artifact in artifacts:
                rendition_id = uuid.uuid4()
                output_object_id = uuid.uuid4()
                manifest_object_id = uuid.uuid4()
                stored = await self._upload_artifact(
                    artifact,
                    object_id=output_object_id,
                    job_id=claim.job_id,
                )
                provenance = RenditionProvenance(
                    source_version_id=claim.version_id,
                    source_object_id=row["object_id"],
                    source_sha256=claim.input_sha256,
                    detected_mime=detection.detected_mime,
                    output_rendition_id=rendition_id,
                    output_object_id=output_object_id,
                    output_sha256=stored.sha256,
                    output_byte_size=stored.byte_size,
                    output_mime=artifact.mime_type,
                    generator="rtr-safe-pipeline",
                    generator_version="1",
                    pipeline_version=claim.pipeline_version,
                    config_fingerprint=claim.pipeline_fingerprint,
                    created_at=datetime.now(UTC),
                    job_id=claim.job_id,
                    attempt=claim.attempt,
                    origin=artifact.origin,
                    quality=artifact.quality,
                    warnings=list(artifact.warnings),
                    truncated=artifact.truncated,
                    partial=artifact.quality_state != "complete",
                )
                manifest_bytes = canonical_json(provenance.model_dump(mode="json"))
                manifest_stored = await self.storage.upload_stream(
                    key=f"rendition-manifests/{manifest_object_id}",
                    stream=io.BytesIO(manifest_bytes),
                    mime_type="application/json",
                    declared_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                    upload_state="rendition-manifest-staged",
                    extra_metadata={"job-id": str(claim.job_id)},
                )
                published.append({
                    "artifact": artifact,
                    "rendition_id": rendition_id,
                    "output_object_id": output_object_id,
                    "manifest_object_id": manifest_object_id,
                    "stored": stored,
                    "manifest_stored": manifest_stored,
                    "provenance": provenance,
                })
        async with self.uow.transaction() as session:
            for optional_failure in optional_failures:
                await AuditRepository().append(
                    session,
                    actor_kind="service",
                    actor_user_id=None,
                    action=f"{optional_failure.stage}.unavailable",
                    result="failure",
                    reason_code=optional_failure.code,
                    request_id=claim.request_id,
                    resource_id=claim.version_id,
                    resource_type="document_version",
                    details={
                        "job_id": str(claim.job_id),
                        "error_fingerprint": optional_failure.fingerprint,
                    },
                )
            for item in published:
                artifact = item["artifact"]
                for object_id, stored, mime in (
                    (
                        item["output_object_id"],
                        item["stored"],
                        artifact.mime_type,
                    ),
                    (
                        item["manifest_object_id"],
                        item["manifest_stored"],
                        "application/json",
                    ),
                ):
                    await ResourceRepository().create(
                        session,
                        ResourceRecord(
                            resource_id=object_id,
                            resource_type="object",
                            owner_subject_id=row["owner_subject_id"],
                            classification=row["classification"],
                            source_zone=row["source_zone"],
                            department_id=row["department_id"],
                            project_id=row["project_id"],
                            lifecycle_state=(
                                "quarantined"
                                if row["publication_deferred"] else "active"
                            ),
                        ),
                    )
                    await session.execute(text("""
                        INSERT INTO object_blobs(
                          object_id,bucket,object_key,sha256,byte_size,mime_type,
                          etag,storage_state,created_by,verified_at
                        ) VALUES (
                          :object_id,:bucket,:key,:sha256,:byte_size,:mime,
                          :etag,:storage_state,:created_by,now()
                        )
                    """), {
                        "object_id": object_id,
                        "bucket": stored.bucket,
                        "key": stored.key,
                        "sha256": stored.sha256,
                        "byte_size": stored.byte_size,
                        "mime": mime,
                        "etag": stored.etag,
                        "created_by": claim.requested_by,
                        "storage_state": (
                            "staged" if row["publication_deferred"] else "available"
                        ),
                    })
                await ResourceRepository().create(
                    session,
                    ResourceRecord(
                        resource_id=item["rendition_id"],
                        resource_type="rendition",
                        owner_subject_id=row["owner_subject_id"],
                        classification=row["classification"],
                        source_zone=row["source_zone"],
                        department_id=row["department_id"],
                        project_id=row["project_id"],
                        lifecycle_state=(
                            "quarantined"
                            if row["publication_deferred"] else "active"
                        ),
                    ),
                )
                await session.execute(text("""
                    INSERT INTO renditions(
                      rendition_id,version_id,kind,object_id,mime_type,status,
                      generator,generator_version,pipeline_fingerprint,
                      source_sha256,manifest_object_id,quality_state,
                      quality_summary,provenance,job_id,attempt
                    ) VALUES (
                      :rendition_id,:version_id,:kind,:object_id,:mime,'ready',
                      'rtr-safe-pipeline','1',:fingerprint,:source_sha,
                      :manifest_object_id,:quality_state,
                      CAST(:quality AS jsonb),CAST(:provenance AS jsonb),:job_id,:attempt
                    )
                """), {
                    "rendition_id": item["rendition_id"],
                    "version_id": claim.version_id,
                    "kind": item["artifact"].kind,
                    "object_id": item["output_object_id"],
                    "mime": item["artifact"].mime_type,
                    "fingerprint": claim.pipeline_fingerprint,
                    "source_sha": claim.input_sha256,
                    "manifest_object_id": item["manifest_object_id"],
                    "quality_state": item["artifact"].quality_state,
                    "quality": json.dumps(item["artifact"].quality),
                    "provenance": item["provenance"].model_dump_json(),
                    "job_id": claim.job_id,
                    "attempt": claim.attempt,
                })
                await AuditRepository().append(
                    session,
                    actor_kind="service",
                    actor_user_id=None,
                    action="rendition.ready",
                    result="success",
                    reason_code="artifact_verified_and_published",
                    request_id=claim.request_id,
                    resource_id=item["rendition_id"],
                    resource_type="rendition",
                    details={
                        "job_id": str(claim.job_id),
                        "kind": item["artifact"].kind,
                        "quality_state": item["artifact"].quality_state,
                    },
                )
                RENDITION_BYTES.labels(item["artifact"].kind).inc(
                    item["stored"].byte_size,
                )
                RENDITIONS.labels(item["artifact"].kind, "ready").inc()
            await session.execute(text("""
                UPDATE document_versions SET viewer_state='ready'
                WHERE version_id=:version_id AND viewer_state='processing'
            """), {"version_id": claim.version_id})
            await session.execute(text("""
                UPDATE upload_sessions SET progress=100
                WHERE version_id=:version_id
            """), {"version_id": claim.version_id})
            await self.jobs.succeeded(session, claim, reason="required_renditions_ready")

    async def process_job(self, job_id: uuid.UUID, *, worker_id: str) -> bool:
        claim = await self.jobs.claim(
            job_id,
            worker_id=worker_id,
            settings=self.settings,
        )
        if claim is None:
            return False
        await self.jobs.running(claim)
        started = time.monotonic()
        lease_stop = asyncio.Event()
        lease_task = asyncio.create_task(self._maintain_lease(claim, lease_stop))
        try:
            if claim.job_type == "validate":
                await self._process_validation(claim)
            else:
                await self._process_rendition(claim)
        except IngestionFailure as failure:
            STAGE_DURATION.labels(claim.job_type, failure.code).observe(
                time.monotonic() - started,
            )
            if claim.upload_id:
                await self._record_upload_failure(claim, failure)
            else:
                await self.jobs.failed(
                    claim,
                    code=failure.code,
                    fingerprint=failure.fingerprint,
                    retryable=failure.retryable,
                )
            return False
        except Exception as exc:
            STAGE_DURATION.labels(claim.job_type, "processing_failed").observe(
                time.monotonic() - started,
            )
            generic_failure = IngestionFailure(
                "processing_failed",
                retryable=claim.attempt < claim.max_attempts,
                stage="pipeline",
            )
            if claim.version_id and claim.attempt >= claim.max_attempts:
                async with self.uow.transaction() as session:
                    await session.execute(text("""
                        UPDATE document_versions SET viewer_state='processing_failed'
                        WHERE version_id=:version_id
                    """), {"version_id": claim.version_id})
                    await AuditRepository().append(
                        session,
                        actor_kind="service",
                        actor_user_id=None,
                        action="viewer.processing_failed",
                        result="failure",
                        reason_code="processing_failed",
                        request_id=claim.request_id,
                        resource_id=claim.version_id,
                        resource_type="document_version",
                        details={"job_id": str(claim.job_id), "attempt": claim.attempt},
                    )
            await self.jobs.failed(
                claim,
                code=generic_failure.code,
                fingerprint=hashlib.sha256(
                    f"{type(exc).__name__}:{generic_failure.fingerprint}".encode(),
                ).hexdigest(),
                retryable=generic_failure.retryable,
            )
            return False
        finally:
            lease_stop.set()
            await lease_task
        STAGE_DURATION.labels(claim.job_type, "succeeded").observe(
            time.monotonic() - started,
        )
        return True
