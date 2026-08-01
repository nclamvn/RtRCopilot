"""Job backpressure: settings-bounded concurrency caps per job family (AC-07).

An "outstanding" job is any that is not yet in a terminal state (still occupying
queue depth). When the outstanding count for a family is at/over its
admin-configured cap, a *new submission* is refused at the API layer with a
typed ``queue_saturated`` (429) carrying ``Retry-After`` — never a silent drop.

Cap keys (governance SETTING_REGISTRY):
  ingestion -> limits.jobs.ingestion_max_inflight
  render    -> limits.jobs.render_max_inflight
  index     -> limits.jobs.index_max_backlog

The worker is a single sequential consumer (one job per family per loop), so
runtime concurrency is already bounded to one; these caps bound *queue growth*
at the point where work is admitted.
"""

from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.limits.settings_access import effective_int_setting

JobFamily = Literal["ingestion", "render", "index"]

FAMILY_CAP_KEY: dict[JobFamily, str] = {
    "ingestion": "limits.jobs.ingestion_max_inflight",
    "render": "limits.jobs.render_max_inflight",
    "index": "limits.jobs.index_max_backlog",
}

_OUTSTANDING_SQL: dict[JobFamily, str] = {
    "ingestion": """
        SELECT count(*) FROM ingestion_jobs
        WHERE status NOT IN ('succeeded','failed','quarantined','cancelled')
    """,
    "render": """
        SELECT count(*) FROM render_jobs
        WHERE state NOT IN ('completed','failed','finalized')
    """,
    "index": """
        SELECT count(*) FROM sot_reindex_outbox
        WHERE status IN ('pending','dispatching')
    """,
}


class QueueSaturated(Exception):
    def __init__(
        self,
        family: JobFamily,
        *,
        retry_after: int,
        outstanding: int,
        cap: int,
    ) -> None:
        super().__init__("queue_saturated")
        self.code = "queue_saturated"
        self.family = family
        self.retry_after = retry_after
        self.outstanding = outstanding
        self.cap = cap


async def outstanding_count(session: AsyncSession, family: JobFamily) -> int:
    value = await session.scalar(text(_OUTSTANDING_SQL[family]))
    return int(value or 0)


async def check_capacity(
    session: AsyncSession,
    family: JobFamily,
    *,
    retry_after: int,
) -> int:
    """Raise :class:`QueueSaturated` when the family is at/over its cap.

    Returns the current outstanding count when admission is allowed.
    """
    cap = await effective_int_setting(session, FAMILY_CAP_KEY[family])
    outstanding = await outstanding_count(session, family)
    if outstanding >= cap:
        raise QueueSaturated(
            family,
            retry_after=retry_after,
            outstanding=outstanding,
            cap=cap,
        )
    return outstanding
