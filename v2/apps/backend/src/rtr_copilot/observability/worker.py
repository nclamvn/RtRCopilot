"""Worker-side observability: a dedicated metrics endpoint plus job telemetry.

The worker has no HTTP app of its own, so it publishes the shared default
registry on a separate port via ``prometheus_client.start_http_server`` (AC-08:
"prometheus-client exposition on api AND worker (separate port/endpoint)"). The
port is never published to the host in the hardened profile — Prometheus scrapes
``worker:<port>`` on the compose network, matching the api's internal-only
posture.

:func:`log_job_request_id` is the proven link in the request-id chain (AC-09):
when the worker begins processing a job it emits a structured log carrying the
originating request-id that the api persisted on the job row, under the worker
logger. :func:`observe_job` wraps execution to record duration + outcome by
family.
"""

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import start_http_server

from rtr_copilot.observability.metrics import JOB_DURATION, JOBS_PROCESSED

logger = logging.getLogger("rtr_copilot.worker")

_started = False


def start_worker_metrics_server(port: int) -> None:
    """Start the worker metrics HTTP server once (idempotent).

    Binds ``0.0.0.0:<port>`` inside the container; the port stays unpublished so
    it is reachable only on the compose network. Safe to call more than once —
    only the first call opens the socket.
    """
    global _started
    if _started:
        return
    start_http_server(port)
    _started = True
    logger.info(json.dumps({"event": "worker_metrics_server_started", "port": port}))


def log_job_request_id(family: str, request_id: str, *, job_id: str) -> None:
    """Emit the worker's request-id log line for a job it is processing.

    This is the third link the AC-09 chain test asserts on: the api logged
    request-id R, the job row persisted R, and the worker logs R here while
    handling the job. Only the id and coarse job identity are logged — never
    payload content.
    """
    logger.info(json.dumps({
        "event": "worker_job_processing",
        "family": family,
        "request_id": request_id,
        "job_id": job_id,
    }))


@contextmanager
def observe_job(family: str) -> Iterator[None]:
    """Record a worker job's duration and terminal result by family."""
    started = time.perf_counter()
    result = "success"
    try:
        yield
    except Exception:
        result = "error"
        raise
    finally:
        elapsed = time.perf_counter() - started
        JOB_DURATION.labels(family=family, result=result).observe(elapsed)
        JOBS_PROCESSED.labels(family=family, result=result).inc()
