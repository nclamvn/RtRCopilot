import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis

from rtr_copilot.config import get_settings
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.ingestion.jobs import INGESTION_QUEUE, JobRepository
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.limits.backpressure import JobFamily, outstanding_count
from rtr_copilot.limits.settings_access import effective_int_setting
from rtr_copilot.observability.db import refresh_db_pool_metrics
from rtr_copilot.observability.metrics import (
    AUDIT_CHAIN_LAST_VERIFIED,
    AUDIT_CHAIN_VALID,
    JOB_QUEUE_DEPTH,
    JOB_QUEUE_SATURATION,
)
from rtr_copilot.observability.worker import (
    log_job_request_id,
    observe_job,
    start_worker_metrics_server,
)
from rtr_copilot.rag.reindex import ReindexService
from rtr_copilot.repositories.audit import AuditRepository

QUEUE = "rtr:jobs"
HEARTBEAT = "rtr:worker:heartbeat"
#: How often the worker re-verifies the audit hash-chain and republishes the
#: integrity gauge (the verify scans the chain, so it runs on a slow cadence).
AUDIT_VERIFY_INTERVAL_SECONDS = 60.0
QUEUE_MAINTENANCE_TIMEOUT_SECONDS = 2.0
QUEUE_POP_TIMEOUT_SECONDS = 7.0
logger = logging.getLogger("rtr_copilot.worker")


def ping_result(job_id: str, request_id: str) -> dict[str, str]:
    return {"job_id": job_id, "request_id": request_id, "status": "pong"}


async def execute(
    client: Redis,
    job: dict[str, Any],
    *,
    worker_id: str = "worker-test",
) -> None:
    job_id = str(job["job_id"])
    if job.get("name") == "ingestion.process":
        # process_job claims the row and logs the originating request-id itself
        # (the id is on the DB row, not the queue payload); observe duration by
        # family here where the family is known.
        with observe_job("ingestion"):
            await IngestionService().process_job(uuid.UUID(job_id), worker_id=worker_id)
        return
    if job.get("name") == "document.render":
        with observe_job("render"):
            await DocumentOSService().process_render(uuid.UUID(job_id), worker_id=worker_id)
        return
    if job.get("name") != "system.ping":
        return
    with observe_job("ping"):
        # The ping payload carries the request-id inline, so the worker logs the
        # chain link directly (AC-09).
        log_job_request_id("ping", str(job["request_id"]), job_id=job_id)
        key = f"rtr:result:{job_id}"
        if await client.exists(key):
            return
        result = ping_result(job_id, str(job["request_id"]))
        await client.set(key, json.dumps(result), ex=60, nx=True)


async def audit_index_backpressure(
    jobs: JobRepository,
    worker_id: str,
    *,
    previously_saturated: bool,
) -> bool:
    """Worker-side index backpressure (AC-07).

    The worker is a single sequential consumer, so runtime concurrency is
    already bounded to one; this bounds *backlog growth* by surfacing it. When
    the pending SOT reindex backlog crosses its configured cap the episode is
    logged and audited once (rising edge only, so the globally-serialized audit
    chain is never flooded). The worker keeps draining — reindex work is never
    dropped.
    """
    async with jobs.uow.factory() as session:
        cap = await effective_int_setting(session, "limits.jobs.index_max_backlog")
        outstanding = await outstanding_count(session, "index")
    saturated = outstanding >= cap
    if saturated and not previously_saturated:
        JOB_QUEUE_SATURATION.labels(family="index").inc()
        logger.warning(json.dumps({
            "event": "index_backlog_saturated",
            "outstanding": outstanding,
            "cap": cap,
        }))
        try:
            async with jobs.uow.transaction() as session:
                await AuditRepository().append(
                    session,
                    actor_kind="service",
                    actor_user_id=None,
                    action="sot.reindex.backpressure",
                    result="deny",
                    reason_code="queue_saturated",
                    request_id=f"worker:{worker_id}",
                    resource_type="request_limit",
                    details={
                        "family": "index",
                        "outstanding": outstanding,
                        "cap": cap,
                    },
                )
        except Exception:
            logger.warning(json.dumps({"event": "index_backpressure_audit_failed"}))
    return saturated


async def refresh_job_queue_depth(jobs: JobRepository) -> None:
    """Publish outstanding-job counts per family for the queue-depth gauge."""
    families: tuple[JobFamily, ...] = ("ingestion", "render", "index")
    async with jobs.uow.factory() as session:
        for family in families:
            JOB_QUEUE_DEPTH.labels(family=family).set(
                await outstanding_count(session, family),
            )


async def verify_audit_chain(jobs: JobRepository) -> None:
    """Re-verify the audit hash-chain and publish the integrity gauge (AC-08).

    Feeds the ``AuditChainVerifyFailure`` alert. Never raises: an infra hiccup
    during verification must not crash the worker; the gauge simply is not
    refreshed that cycle.
    """
    try:
        async with jobs.uow.factory() as session:
            valid, _count, _head = await AuditRepository().verify(session)
        AUDIT_CHAIN_VALID.set(1 if valid else 0)
        AUDIT_CHAIN_LAST_VERIFIED.set(time.time())
        if not valid:
            logger.error(json.dumps({
                "event": "audit_chain_verify_failed",
                "error_code": "audit_chain_invalid",
            }))
    except Exception as error:
        logger.warning(json.dumps({
            "event": "audit_chain_verify_error",
            "error_fingerprint": hashlib.sha256(
                type(error).__name__.encode(),
            ).hexdigest(),
        }))


async def run() -> None:
    settings = get_settings()
    start_worker_metrics_server(settings.worker_metrics_port)
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True,
                                   socket_connect_timeout=1, socket_timeout=6)
    worker_id = str(uuid.uuid4())
    index_saturated = False
    last_audit_verify = 0.0
    try:
        while True:
            # DB-backed render work is independent of Redis notification/uptime.
            try:
                with observe_job("render"):
                    await DocumentOSService().process_next(worker_id=worker_id)
            except Exception as error:
                logger.error(json.dumps({
                    "event": "document_poll_error",
                    "error_fingerprint": hashlib.sha256(type(error).__name__.encode()).hexdigest(),
                }))
            heartbeat = json.dumps({"worker_id": worker_id, "at": time.time()})
            jobs = JobRepository()
            try:
                async with asyncio.timeout(QUEUE_MAINTENANCE_TIMEOUT_SECONDS):
                    await client.set(HEARTBEAT, heartbeat, ex=15)
                    await jobs.dispatch_outbox(client)
            except Exception:
                logger.warning(json.dumps({"event": "worker_queue_unavailable"}))
            await jobs.refresh_metrics()
            await refresh_job_queue_depth(jobs)
            refresh_db_pool_metrics()
            if time.monotonic() - last_audit_verify >= AUDIT_VERIFY_INTERVAL_SECONDS:
                await verify_audit_chain(jobs)
                last_audit_verify = time.monotonic()
            index_saturated = await audit_index_backpressure(
                jobs, worker_id, previously_saturated=index_saturated,
            )
            try:
                await ReindexService().process_next()
            except Exception as error:
                logger.error(json.dumps({
                    "event": "reindex_job_error",
                    "error_code": "reindex_failed",
                    "error_fingerprint": hashlib.sha256(
                        type(error).__name__.encode(),
                    ).hexdigest(),
                }))
            try:
                async with asyncio.timeout(QUEUE_POP_TIMEOUT_SECONDS):
                    item = await cast(
                        Awaitable[list[str] | None],
                        client.brpop([INGESTION_QUEUE, QUEUE], timeout=5),
                    )
            except Exception:
                # Bound outage spin while continuing persisted render polling.
                await asyncio.sleep(1)
                item = None
            if item:
                try:
                    await execute(client, json.loads(item[1]), worker_id=worker_id)
                except Exception as error:
                    logger.error(json.dumps({
                        "event": "worker_job_error",
                        "error_code": "processing_failed",
                        "error_fingerprint": hashlib.sha256(
                            type(error).__name__.encode(),
                        ).hexdigest(),
                    }))
    finally:
        await client.aclose()


def main() -> None:
    try:
        asyncio.run(run())
    except Exception as error:
        logger.error(json.dumps({
            "event": "worker_runtime_error",
            "error_code": "worker_unavailable",
            "error_fingerprint": hashlib.sha256(
                type(error).__name__.encode(),
            ).hexdigest(),
        }))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
