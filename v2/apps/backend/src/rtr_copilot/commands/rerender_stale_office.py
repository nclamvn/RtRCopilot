"""Audit and repair stale active Office previews through the normal pipeline."""

import argparse
import asyncio
import json
import uuid
from typing import Any

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.jobs import (
    PIPELINE_VERSION,
    RENDITION_GENERATOR_VERSION,
    JobRepository,
)
from rtr_copilot.ingestion.service import IngestionService

OFFICE_MIMES = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)
OFFICE_BACKFILL_REVISION = "2"


async def backfill(*, apply: bool = False, limit: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    uow = UnitOfWork()
    jobs = JobRepository(uow)
    service = IngestionService(settings=settings, uow=uow)
    async with uow.factory() as session:
        rows = (await session.execute(text("""
            SELECT dv.version_id,dv.original_filename,dv.sha256,dv.created_by
            FROM document_versions dv
            JOIN resources vr ON vr.resource_id=dv.version_id
            WHERE dv.detected_mime=ANY(:office_mimes)
              AND vr.lifecycle_state='active'
              AND dv.created_by IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM renditions current_preview
                JOIN resources current_resource
                  ON current_resource.resource_id=current_preview.rendition_id
                WHERE current_preview.version_id=dv.version_id
                  AND current_preview.kind='preview_pdf'
                  AND current_preview.status='ready'
                  AND current_resource.lifecycle_state='active'
                  AND current_preview.generator_version=:generator_version
              )
            ORDER BY dv.created_at,dv.version_id
            LIMIT :limit
        """), {
            "office_mimes": list(OFFICE_MIMES),
            "generator_version": RENDITION_GENERATOR_VERSION,
            "limit": limit,
        })).mappings().all()
    result: dict[str, Any] = {
        "apply": apply,
        "pipeline_version": PIPELINE_VERSION,
        "generator_version": RENDITION_GENERATOR_VERSION,
        "backfill_revision": OFFICE_BACKFILL_REVISION,
        "eligible_versions": len(rows),
        "versions": [
            {
                "version_id": str(row["version_id"]),
                "filename": str(row["original_filename"]),
            }
            for row in rows
        ],
        "succeeded": 0,
        "failed": 0,
        "pending": 0,
    }
    if not apply:
        return result

    outcomes: list[dict[str, str | None]] = []
    for row in rows:
        version_id = uuid.UUID(str(row["version_id"]))
        async with uow.transaction() as session:
            job_id = await jobs.create(
                session,
                upload_id=None,
                version_id=version_id,
                resource_id=version_id,
                job_type="render",
                output_kind="required_bundle",
                idempotency_key=(
                    f"render:{version_id}:{PIPELINE_VERSION}:"
                    f"office-backfill-{OFFICE_BACKFILL_REVISION}"
                ),
                requested_by=uuid.UUID(str(row["created_by"])),
                request_id=f"office-backfill-{PIPELINE_VERSION}-{version_id}",
                input_sha256=str(row["sha256"]),
                settings=settings,
            )
        await service.process_job(job_id, worker_id=f"office-backfill-{version_id}")
        async with uow.factory() as session:
            job = (await session.execute(text("""
                SELECT status,error_code FROM ingestion_jobs WHERE job_id=:job_id
            """), {"job_id": job_id})).mappings().one()
        status = str(job["status"])
        if status == "succeeded":
            result["succeeded"] += 1
        elif status in {"failed", "quarantined"}:
            result["failed"] += 1
        else:
            result["pending"] += 1
        outcomes.append({
            "version_id": str(version_id),
            "job_id": str(job_id),
            "status": status,
            "error_code": str(job["error_code"]) if job["error_code"] else None,
        })
    result["outcomes"] = outcomes
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(
        asyncio.run(backfill(apply=args.apply, limit=args.limit)),
        ensure_ascii=False,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
