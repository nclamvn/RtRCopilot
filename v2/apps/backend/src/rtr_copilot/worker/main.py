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
from rtr_copilot.rag.reindex import ReindexService

QUEUE = "rtr:jobs"
HEARTBEAT = "rtr:worker:heartbeat"
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
        await IngestionService().process_job(uuid.UUID(job_id), worker_id=worker_id)
        return
    if job.get("name") == "document.render":
        await DocumentOSService().process_render(uuid.UUID(job_id))
        return
    if job.get("name") != "system.ping":
        return
    key = f"rtr:result:{job_id}"
    if await client.exists(key):
        return
    result = ping_result(job_id, str(job["request_id"]))
    await client.set(key, json.dumps(result), ex=60, nx=True)


async def run() -> None:
    settings = get_settings()
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    worker_id = str(uuid.uuid4())
    try:
        while True:
            heartbeat = json.dumps({"worker_id": worker_id, "at": time.time()})
            await client.set(HEARTBEAT, heartbeat, ex=15)
            jobs = JobRepository()
            await jobs.dispatch_outbox(client)
            await jobs.refresh_metrics()
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
            item = await cast(
                Awaitable[list[str] | None],
                client.brpop([INGESTION_QUEUE, QUEUE], timeout=5),
            )
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
