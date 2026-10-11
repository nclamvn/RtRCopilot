import asyncio
import json
from typing import Any

import pytest
from fastapi import Request

from rtr_copilot.documents.api import call
from rtr_copilot.worker import main as worker


@pytest.mark.asyncio
async def test_retry_exhaustion_is_an_actionable_api_conflict() -> None:
    request = Request({"type": "http"})
    request.state.request_id = "synthetic-recovery"

    async def exhausted() -> None:
        raise ValueError("render_retry_exhausted")

    response = await call(request, exhausted())
    assert response.status_code == 409
    assert json.loads(response.body)["error"] == {
        "code": "render_retry_exhausted",
        "message": "Render attempt limit reached; contact an operator",
    }


@pytest.mark.asyncio
async def test_worker_db_poll_continues_across_blackholed_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polls = 0
    blocked_calls: list[str] = []
    closed = False

    class Blackhole:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            blocked_calls.append("heartbeat")
            await asyncio.Event().wait()

        async def brpop(self, *args: Any, **kwargs: Any) -> None:
            blocked_calls.append("brpop")
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    class Documents:
        async def process_next(self, **kwargs: Any) -> bool:
            nonlocal polls
            polls += 1
            if polls == 2:
                raise asyncio.CancelledError()
            return False

    class Jobs:
        async def dispatch_outbox(self, *args: Any) -> None:
            blocked_calls.append("outbox")
            await asyncio.Event().wait()

        async def refresh_metrics(self) -> None:
            pass

    class Reindex:
        async def process_next(self) -> None:
            pass

    async def noop(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(worker.Redis, "from_url", lambda *a, **k: Blackhole())
    monkeypatch.setattr(worker, "DocumentOSService", Documents)
    monkeypatch.setattr(worker, "JobRepository", Jobs)
    monkeypatch.setattr(worker, "ReindexService", Reindex)
    monkeypatch.setattr(worker, "start_worker_metrics_server", lambda _: None)
    monkeypatch.setattr(worker, "refresh_db_pool_metrics", lambda: None)
    monkeypatch.setattr(worker, "refresh_job_queue_depth", noop)
    monkeypatch.setattr(worker, "verify_audit_chain", noop)
    monkeypatch.setattr(worker, "audit_index_backpressure", noop)
    monkeypatch.setattr(worker, "QUEUE_MAINTENANCE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(worker, "QUEUE_POP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(worker.asyncio, "sleep", noop)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(worker.run(), 1)
    assert polls == 2
    assert blocked_calls == ["heartbeat", "brpop"]
    assert closed
