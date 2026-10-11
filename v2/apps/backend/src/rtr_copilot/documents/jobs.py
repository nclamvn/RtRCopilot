"""Durable render admission and bounded ownership (Redis is only a hint)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.audit import AuditRepository


class RenderLeaseLost(Exception):
    """An obsolete attempt must neither publish nor clean up artifacts."""


@dataclass(frozen=True)
class RenderClaim:
    job_id: uuid.UUID
    token: uuid.UUID
    attempt: int


class RenderJobRepository:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def expire(self, job_id: uuid.UUID | None = None) -> int:
        # Unknown staged effects are not automatically replayed. Explicit retry
        # retains canonical job identity, but gets a fresh ownership token.
        async with self.uow.transaction() as session:
            rows = (await session.execute(text("""
                WITH expired AS (
                  SELECT render_job_id FROM render_jobs
                  WHERE state IN ('binding','rendering','validating')
                    AND (lease_expires_at IS NULL OR lease_expires_at<=now())
                    AND (CAST(:job AS uuid) IS NULL OR render_job_id=:job)
                  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 50
                )
                UPDATE render_jobs j SET state='failed',progress=100,
                  error_code='render_lease_expired',finished_at=now(),
                  lease_token=NULL,lease_expires_at=NULL
                FROM expired e WHERE j.render_job_id=e.render_job_id
                RETURNING j.render_job_id,j.request_id,j.template_version_id,j.attempt
            """), {"job": job_id})).mappings().all()
            for row in rows:
                await session.execute(text("""
                    UPDATE document_publication_outbox SET state='failed',
                      error_code='render_lease_expired',updated_at=now()
                    WHERE render_job_id=:job AND state<>'finalized'
                """), {"job": row["render_job_id"]})
                await AuditRepository().append(
                    session, actor_kind="service", actor_user_id=None,
                    action="document.render", result="failure",
                    reason_code="render_lease_expired", request_id=str(row["request_id"]),
                    resource_id=row["template_version_id"], resource_type="template_version",
                    details={"render_job_id": str(row["render_job_id"]),
                             "attempt": row["attempt"]},
                )
            return len(rows)

    async def claim(self, *, lease_seconds: int,
                    job_id: uuid.UUID | None = None) -> RenderClaim | None:
        await self.expire(job_id)
        async with self.uow.transaction() as session:
            row = (await session.execute(text("""
                SELECT render_job_id,attempt FROM render_jobs
                WHERE state='pending' AND attempt<max_attempts
                  AND (CAST(:job AS uuid) IS NULL OR render_job_id=:job)
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
            """), {"job": job_id})).mappings().one_or_none()
            if row is None:
                return None
            token = uuid.uuid4()
            await session.execute(text("""
                UPDATE render_jobs SET state='rendering',progress=35,started_at=now(),
                  attempt=attempt+1,lease_token=:token,
                  lease_expires_at=now()+make_interval(secs => :seconds)
                WHERE render_job_id=:job
            """), {"job": row["render_job_id"], "token": token, "seconds": lease_seconds})
            changed = await session.execute(text("""
                UPDATE document_publication_outbox SET state='preparing',
                  attempts=attempts+1,error_code=NULL,updated_at=now()
                WHERE render_job_id=:job AND state IN ('pending','failed')
            """), {"job": row["render_job_id"]})
            if getattr(changed, "rowcount", 0) != 1:
                raise ValueError("render_failed")
            return RenderClaim(row["render_job_id"], token, int(row["attempt"]) + 1)

    async def assert_owned(self, session: AsyncSession, claim: RenderClaim) -> None:
        owned = await session.scalar(text("""
            SELECT render_job_id FROM render_jobs
            WHERE render_job_id=:job AND state='rendering' AND lease_token=:token
              AND lease_expires_at>now()
            FOR UPDATE
        """), {"job": claim.job_id, "token": claim.token})
        if owned is None:
            raise RenderLeaseLost()
