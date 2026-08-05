import hashlib
import json
import random
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.config import Settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.metrics import LEASE_EXPIRY, QUEUE_DEPTH, RETRIES
from rtr_copilot.repositories.audit import AuditRepository

INGESTION_QUEUE = "rtr:ingestion:jobs"
PIPELINE_VERSION = "rtr-ingestion-v3"
RENDITION_GENERATOR_VERSION = "3"


@dataclass(frozen=True)
class JobClaim:
    job_id: uuid.UUID
    upload_id: uuid.UUID | None
    version_id: uuid.UUID | None
    resource_id: uuid.UUID
    job_type: str
    output_kind: str | None
    pipeline_version: str
    pipeline_fingerprint: str
    attempt: int
    max_attempts: int
    requested_by: uuid.UUID
    request_id: str
    input_sha256: str


def pipeline_fingerprint(kind: str, config_fingerprint: str) -> str:
    return hashlib.sha256(
        f"{PIPELINE_VERSION}:{kind}:{config_fingerprint}".encode(),
    ).hexdigest()


def config_fingerprint(settings: Settings) -> str:
    safe_config = {
        "max_image_pixels": settings.ingestion_max_image_pixels,
        "max_pdf_pages": settings.ingestion_max_pdf_pages,
        "max_pdf_objects": settings.ingestion_max_pdf_objects,
        "max_archive_entries": settings.ingestion_max_archive_entries,
        "max_archive_entry_bytes": settings.ingestion_max_archive_entry_bytes,
        "max_expanded_bytes": settings.ingestion_max_expanded_bytes,
        "max_compression_ratio": settings.ingestion_max_compression_ratio,
        "max_cells": settings.ingestion_max_cells,
        "max_slides": settings.ingestion_max_slides,
        "max_media_seconds": settings.ingestion_max_media_seconds,
        "max_media_width": settings.ingestion_max_media_width,
        "max_media_height": settings.ingestion_max_media_height,
        "max_sample_rate": settings.ingestion_max_sample_rate,
        "ocr_languages": settings.ingestion_ocr_languages,
        "ocr_enabled": settings.ingestion_ocr_enabled,
        "transcript_enabled": settings.ingestion_transcript_enabled,
        "vosk_model_sha256": settings.ingestion_vosk_model_sha256,
        "external_egress": settings.ingestion_external_egress,
    }
    return hashlib.sha256(
        json.dumps(safe_config, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


class JobRepository:
    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()

    async def create(
        self,
        session: AsyncSession,
        *,
        upload_id: uuid.UUID | None,
        version_id: uuid.UUID | None,
        resource_id: uuid.UUID,
        job_type: str,
        output_kind: str | None,
        idempotency_key: str,
        requested_by: uuid.UUID,
        request_id: str,
        input_sha256: str,
        settings: Settings,
    ) -> uuid.UUID:
        job_id = uuid.uuid4()
        fingerprint = pipeline_fingerprint(
            output_kind or job_type,
            config_fingerprint(settings),
        )
        row = (await session.execute(text("""
            INSERT INTO ingestion_jobs(
              job_id, upload_id, version_id, resource_id, job_type, output_kind,
              pipeline_version, pipeline_fingerprint, idempotency_key,
              status, max_attempts, requested_by, request_id, input_sha256
            ) VALUES (
              :job_id, :upload_id, :version_id, :resource_id, :job_type, :output_kind,
              :pipeline_version, :pipeline_fingerprint, :idempotency_key,
              'pending', :max_attempts, :requested_by, :request_id, :input_sha256
            )
            ON CONFLICT (idempotency_key) DO UPDATE
              SET updated_at=ingestion_jobs.updated_at
            RETURNING job_id
        """), {
            "job_id": job_id,
            "upload_id": upload_id,
            "version_id": version_id,
            "resource_id": resource_id,
            "job_type": job_type,
            "output_kind": output_kind,
            "pipeline_version": PIPELINE_VERSION,
            "pipeline_fingerprint": fingerprint,
            "idempotency_key": idempotency_key,
            "max_attempts": settings.ingestion_job_max_attempts,
            "requested_by": requested_by,
            "request_id": request_id,
            "input_sha256": input_sha256,
        })).scalar_one()
        durable_job_id = uuid.UUID(str(row))
        await session.execute(text("""
            INSERT INTO ingestion_outbox(outbox_id, job_id, payload)
            VALUES (:outbox_id, :job_id, CAST(:payload AS jsonb))
            ON CONFLICT (job_id) DO NOTHING
        """), {
            "outbox_id": uuid.uuid4(),
            "job_id": durable_job_id,
            "payload": json.dumps({
                "name": "ingestion.process",
                "job_id": str(durable_job_id),
            }),
        })
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=requested_by,
            action="ingestion.job.create",
            result="success",
            reason_code="durable_job_created",
            request_id=request_id,
            resource_id=resource_id,
            resource_type="ingestion_job",
            details={"job_id": str(durable_job_id), "job_type": job_type},
        )
        return durable_job_id

    async def dispatch_outbox(self, redis: Redis, *, batch_size: int = 50) -> int:
        dispatched = 0
        for _ in range(batch_size):
            async with self.uow.transaction() as session:
                row = (await session.execute(text("""
                    SELECT outbox_id, job_id, payload FROM ingestion_outbox
                    WHERE status IN ('pending','dispatching')
                      AND available_at <= now()
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1
                """))).mappings().one_or_none()
                if row is None:
                    break
                await session.execute(text("""
                    UPDATE ingestion_outbox SET status='dispatching',
                      attempts=attempts+1, updated_at=now()
                    WHERE outbox_id=:outbox_id
                """), {"outbox_id": row["outbox_id"]})
                await session.execute(text("""
                    UPDATE ingestion_jobs SET status='pending', updated_at=now()
                    WHERE job_id=:job_id AND status='retry_wait'
                """), {"job_id": row["job_id"]})
                await cast(
                    Awaitable[int],
                    redis.lpush(INGESTION_QUEUE, json.dumps(dict(row["payload"]))),
                )
                await session.execute(text("""
                    UPDATE ingestion_outbox SET status='dispatched',
                      dispatched_at=now(), updated_at=now()
                    WHERE outbox_id=:outbox_id
                """), {"outbox_id": row["outbox_id"]})
                dispatched += 1
        return dispatched

    async def claim(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        settings: Settings,
    ) -> JobClaim | None:
        async with self.uow.transaction() as session:
            row = (await session.execute(text("""
                SELECT * FROM ingestion_jobs WHERE job_id=:job_id FOR UPDATE
            """), {"job_id": job_id})).mappings().one_or_none()
            if row is None or row["status"] in {
                "succeeded",
                "failed",
                "quarantined",
                "cancelled",
            }:
                return None
            now = datetime.now(UTC)
            claimable = (
                row["status"] == "pending"
                or (
                    row["status"] == "retry_wait"
                    and (row["next_attempt_at"] is None or row["next_attempt_at"] <= now)
                )
                or (
                    row["status"] in {"leased", "running"}
                    and row["lease_expires_at"] is not None
                    and row["lease_expires_at"] <= now
                )
            )
            if not claimable:
                return None
            reclaimed = (
                row["status"] in {"leased", "running"}
                and row["lease_expires_at"] is not None
                and row["lease_expires_at"] <= now
            )
            attempt = int(row["attempt"]) + 1
            await session.execute(text("""
                UPDATE ingestion_jobs SET status='leased', attempt=:attempt,
                  lease_owner=:worker_id,
                  lease_expires_at=now() + make_interval(secs => :lease_seconds),
                  heartbeat_at=now(), started_at=COALESCE(started_at,now()),
                  updated_at=now()
                WHERE job_id=:job_id
            """), {
                "job_id": job_id,
                "attempt": attempt,
                "worker_id": worker_id,
                "lease_seconds": settings.ingestion_lease_seconds,
            })
            await AuditRepository().append(
                session,
                actor_kind="service",
                actor_user_id=None,
                action="ingestion.job.claim",
                result="success",
                reason_code="lease_acquired",
                request_id=str(row["request_id"]),
                resource_id=row["resource_id"],
                resource_type="ingestion_job",
                details={"job_id": str(job_id), "attempt": attempt},
            )
            if reclaimed:
                LEASE_EXPIRY.inc()
            return JobClaim(
                job_id=job_id,
                upload_id=row["upload_id"],
                version_id=row["version_id"],
                resource_id=row["resource_id"],
                job_type=str(row["job_type"]),
                output_kind=row["output_kind"],
                pipeline_version=str(row["pipeline_version"]),
                pipeline_fingerprint=str(row["pipeline_fingerprint"]),
                attempt=attempt,
                max_attempts=int(row["max_attempts"]),
                requested_by=row["requested_by"],
                request_id=str(row["request_id"]),
                input_sha256=str(row["input_sha256"]),
            )

    async def running(self, claim: JobClaim, *, progress: int = 1) -> None:
        async with self.uow.transaction() as session:
            result = await session.execute(text("""
                UPDATE ingestion_jobs SET status='running', progress=:progress,
                  heartbeat_at=now(), updated_at=now()
                WHERE job_id=:job_id AND status='leased' AND attempt=:attempt
            """), {
                "job_id": claim.job_id,
                "attempt": claim.attempt,
                "progress": progress,
            })
            if getattr(result, "rowcount", 0) != 1:
                raise RuntimeError("job_lease_lost")

    async def heartbeat(self, claim: JobClaim, *, settings: Settings) -> None:
        async with self.uow.transaction() as session:
            result = await session.execute(text("""
                UPDATE ingestion_jobs SET heartbeat_at=now(),
                  lease_expires_at=now() + make_interval(secs => :lease_seconds),
                  updated_at=now()
                WHERE job_id=:job_id AND status='running' AND attempt=:attempt
            """), {
                "job_id": claim.job_id,
                "attempt": claim.attempt,
                "lease_seconds": settings.ingestion_lease_seconds,
            })
            if getattr(result, "rowcount", 0) != 1:
                raise RuntimeError("job_lease_lost")

    async def succeeded(
        self,
        session: AsyncSession,
        claim: JobClaim,
        *,
        reason: str,
    ) -> None:
        result = await session.execute(text("""
            UPDATE ingestion_jobs SET status='succeeded', progress=100,
              lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=now(),
              finished_at=now(), updated_at=now(), error_code=NULL,
              error_fingerprint=NULL
            WHERE job_id=:job_id AND status='running' AND attempt=:attempt
        """), {"job_id": claim.job_id, "attempt": claim.attempt})
        if getattr(result, "rowcount", 0) != 1:
            raise RuntimeError("job_lease_lost")
        await AuditRepository().append(
            session,
            actor_kind="service",
            actor_user_id=None,
            action="ingestion.job.succeed",
            result="success",
            reason_code=reason,
            request_id=claim.request_id,
            resource_id=claim.resource_id,
            resource_type="ingestion_job",
            details={"job_id": str(claim.job_id), "attempt": claim.attempt},
        )

    async def failed(
        self,
        claim: JobClaim,
        *,
        code: str,
        fingerprint: str,
        retryable: bool,
        quarantined: bool = False,
    ) -> str:
        terminal = quarantined or not retryable or claim.attempt >= claim.max_attempts
        if quarantined:
            status = "quarantined"
        elif terminal:
            status = "failed"
        else:
            status = "retry_wait"
        jitter = random.SystemRandom().uniform(0.8, 1.2)
        delay = round(
            get_settings_retry_base() * (2 ** max(0, claim.attempt - 1)) * jitter,
        )
        async with self.uow.transaction() as session:
            result = await session.execute(text("""
                UPDATE ingestion_jobs SET status=:status, error_code=:code,
                  error_fingerprint=:fingerprint, lease_owner=NULL,
                  lease_expires_at=NULL, updated_at=now(),
                  next_attempt_at=CASE WHEN :status='retry_wait'
                    THEN now() + make_interval(secs => :delay) ELSE NULL END,
                  finished_at=CASE WHEN :terminal THEN now() ELSE NULL END
                WHERE job_id=:job_id AND status='running' AND attempt=:attempt
            """), {
                "status": status,
                "code": code,
                "fingerprint": fingerprint,
                "delay": delay,
                "terminal": terminal,
                "job_id": claim.job_id,
                "attempt": claim.attempt,
            })
            if getattr(result, "rowcount", 0) != 1:
                raise RuntimeError("job_lease_lost")
            if status == "retry_wait":
                await session.execute(text("""
                    UPDATE ingestion_outbox SET status='pending',
                      available_at=now() + make_interval(secs => :delay),
                      updated_at=now() WHERE job_id=:job_id
                """), {"delay": delay, "job_id": claim.job_id})
            await AuditRepository().append(
                session,
                actor_kind="service",
                actor_user_id=None,
                action=(
                    "ingestion.job.retry"
                    if status == "retry_wait"
                    else "ingestion.job.quarantine"
                    if status == "quarantined"
                    else "ingestion.job.fail"
                ),
                result="failure",
                reason_code=code,
                request_id=claim.request_id,
                resource_id=claim.resource_id,
                resource_type="ingestion_job",
                details={
                    "job_id": str(claim.job_id),
                    "attempt": claim.attempt,
                    "retryable": retryable,
                },
            )
            RETRIES.labels(
                "retry" if status == "retry_wait" else "terminal",
            ).inc()
        return status

    async def refresh_metrics(self) -> None:
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT status,count(*) AS total
                FROM ingestion_jobs GROUP BY status
            """))).mappings().all()
        counts = {str(row["status"]): int(row["total"]) for row in rows}
        for state in (
            "pending",
            "leased",
            "running",
            "retry_wait",
            "succeeded",
            "failed",
            "quarantined",
            "cancelled",
        ):
            QUEUE_DEPTH.labels(state).set(counts.get(state, 0))


def get_settings_retry_base() -> int:
    # Imported lazily so unit tests can isolate deterministic job math.
    from rtr_copilot.config import get_settings

    return get_settings().ingestion_retry_base_seconds
