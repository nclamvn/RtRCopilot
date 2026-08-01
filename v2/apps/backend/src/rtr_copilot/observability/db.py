"""Database connection-pool metrics (AC-08).

The SQLAlchemy async engine wraps a synchronous ``QueuePool`` whose occupancy
counters are cheap, non-blocking reads. Rather than register a scrape-time
custom collector (which would have to reach into the engine on the metrics
thread), we refresh a small set of gauges: the worker refreshes them once per
loop, and the api refreshes them inline when ``/metrics`` is scraped. Both are
cheap and side-effect free — reading the pool never opens a connection.
"""

import logging

from sqlalchemy.pool import QueuePool

from rtr_copilot.db.engine import runtime_engine
from rtr_copilot.observability.metrics import DB_POOL_CONNECTIONS

logger = logging.getLogger("rtr_copilot.observability")


def refresh_db_pool_metrics() -> None:
    """Sample the runtime engine's pool occupancy into the gauge set.

    Never raises: a metrics refresh must never break the request or worker loop
    it is attached to. If the pool type does not expose the occupancy counters
    (a non-queue pool, or an engine not yet created) the sample is skipped. The
    async engine's default pool is an ``AsyncAdaptedQueuePool`` (a ``QueuePool``
    subclass), so the counters resolve at runtime.
    """
    try:
        pool = runtime_engine().pool
        if not isinstance(pool, QueuePool):
            return
        DB_POOL_CONNECTIONS.labels(state="size").set(pool.size())
        DB_POOL_CONNECTIONS.labels(state="checked_in").set(pool.checkedin())
        DB_POOL_CONNECTIONS.labels(state="checked_out").set(pool.checkedout())
        DB_POOL_CONNECTIONS.labels(state="overflow").set(pool.overflow())
    except Exception:  # pragma: no cover - defensive; never break the caller
        logger.debug("db_pool_metric_refresh_skipped")
