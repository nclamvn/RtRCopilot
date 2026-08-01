"""TIP-012 Task 2 — integration coverage against live Postgres + Redis.

Proves, end to end through the real ASGI stack and real Redis: typed 429 rate
limiting per class with Retry-After + two-caller isolation, app-layer 413,
cost-budget breach on /ask (429 budget_exhausted) with subject isolation, the
provider circuit breaker opening under injected failures (timeout-bounded, then
immediate 503), and real DB-backed job-cap saturation.

House pattern: ASGITransport (not TestClient), dependency overrides for the
subject, a fresh DB migrated to head, Redis :6380. Skipped unless
INTEGRATION_DATABASE_DSN is set.
"""

import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_rag_integration import actor, publish_and_index, subject
from test_rag_integration import settings as rag_settings

from rtr_copilot.api.main import app
from rtr_copilot.config import get_settings
from rtr_copilot.ingestion.api import file_subject
from rtr_copilot.limits import middleware as limits_mw
from rtr_copilot.limits.backpressure import (
    QueueSaturated,
    check_capacity,
    outstanding_count,
)
from rtr_copilot.limits.breaker import ProviderUnavailable
from rtr_copilot.limits.budget import utc_day
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.api import rag_subject
from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence, SearchFilters
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.repositories.governance import GovernanceRepository

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def _redis() -> Any:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def _set_int_setting(
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
    key: str,
    value: int,
) -> None:
    """Set a governance limit setting. Governance settings are DB-global and
    persist across tests, so each budget-sensitive test sets what it needs."""
    async with factory() as session, session.begin():
        await GovernanceRepository().set_setting(
            session,
            setting_key=key,
            value_type="integer",
            value=value,
            updated_by=actor_id,
            reason="tip-012 integration test",
        )


def _small_limits(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    tuned = get_settings().model_copy(update=overrides)
    monkeypatch.setattr(limits_mw, "get_settings", lambda: tuned)


def _random_ip() -> str:
    quad = uuid.uuid4().int
    return f"10.{quad % 200 + 1}.{(quad >> 8) % 200 + 1}.{(quad >> 16) % 200 + 1}"


class FailingProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.model = "always-fails"
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: list[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        del question, evidence, system_policy
        self.calls += 1
        raise RuntimeError("provider_down")


class HangingProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.model = "never-returns"
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: list[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        del question, evidence, system_policy
        self.calls += 1
        import asyncio

        await asyncio.sleep(60)
        raise AssertionError("timeout failed")


# --------------------------------------------------------------------------- #
# Rate limiting through the ASGI stack
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rate_limit_429_with_retry_after_through_asgi(
    factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await actor(factory)
    _small_limits(monkeypatch, limits_rate_default_read_max=3)

    async def authenticated() -> Any:
        return subject(owner)

    app.dependency_overrides[file_subject] = authenticated
    ip = _random_ip()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            statuses = []
            for _ in range(4):
                response = await client.get(
                    "/api/v1/files", headers={"x-forwarded-for": ip},
                )
                statuses.append(response.status_code)
            assert statuses[:3] == [200, 200, 200]
            assert statuses[3] == 429
            blocked = await client.get(
                "/api/v1/files", headers={"x-forwarded-for": ip},
            )
            assert blocked.json()["error"]["code"] == "rate_limited"
            assert int(blocked.headers["Retry-After"]) >= 1
    finally:
        app.dependency_overrides.pop(file_subject, None)


@pytest.mark.asyncio
async def test_rate_limit_two_callers_isolated(
    factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await actor(factory)
    _small_limits(monkeypatch, limits_rate_default_read_max=2)

    async def authenticated() -> Any:
        return subject(owner)

    app.dependency_overrides[file_subject] = authenticated
    ip_a, ip_b = _random_ip(), _random_ip()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            for _ in range(3):
                await client.get("/api/v1/files", headers={"x-forwarded-for": ip_a})
            flooded = await client.get(
                "/api/v1/files", headers={"x-forwarded-for": ip_a},
            )
            other = await client.get(
                "/api/v1/files", headers={"x-forwarded-for": ip_b},
            )
            assert flooded.status_code == 429
            assert other.status_code == 200
    finally:
        app.dependency_overrides.pop(file_subject, None)


@pytest.mark.asyncio
async def test_body_too_large_413_through_asgi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _small_limits(monkeypatch, limits_max_body_bytes=64)

    async def anonymous() -> None:
        return None

    app.dependency_overrides[rag_subject] = anonymous
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            # Body-size guard fires in middleware, before auth.
            response = await client.post(
                "/api/v1/ask",
                content=b"x" * 512,
                headers={"content-type": "application/json"},
            )
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "body_too_large"
    finally:
        app.dependency_overrides.pop(rag_subject, None)


# --------------------------------------------------------------------------- #
# Cost budget breach on /ask
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_budget_breach_429_on_ask_with_subject_isolation(
    factory: async_sessionmaker[Any],
) -> None:
    spender = await actor(factory)
    bystander = await actor(factory)
    # Subject ceiling of 1; a generous global so only the per-subject cap binds.
    await _set_int_setting(factory, spender, "limits.budget.subject_daily_units", 1)
    await _set_int_setting(
        factory, spender, "limits.budget.global_daily_units", 100_000_000,
    )
    # Pre-seed the spender's daily counter to the ceiling; the bystander's stays
    # at zero, proving one subject's spend never blocks another.
    redis = _redis()
    try:
        await redis.set(
            f"rtr:budget:subject:{utc_day()}:{spender}", "1",
        )
    finally:
        await redis.aclose()

    transport = httpx.ASGITransport(app=app)

    async def as_spender() -> Any:
        return subject(spender)

    async def as_bystander() -> Any:
        return subject(bystander)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test",
    ) as client:
        app.dependency_overrides[rag_subject] = as_spender
        try:
            breached = await client.post("/api/v1/ask", json={
                "question": "Anything at all?",
                "filters": {},
            }, headers={"x-forwarded-for": _random_ip()})
        finally:
            app.dependency_overrides.pop(rag_subject, None)
        assert breached.status_code == 429
        assert breached.json()["error"]["code"] == "budget_exhausted"
        assert int(breached.headers["Retry-After"]) >= 1

        app.dependency_overrides[rag_subject] = as_bystander
        try:
            # Scope to a source that does not exist so the outcome is a
            # deterministic honest-null (no leftover evidence can match).
            allowed = await client.post("/api/v1/ask", json={
                "question": "A question with no evidence available.",
                "filters": {"source_key": f"absent.{uuid.uuid4().hex}"},
            }, headers={"x-forwarded-for": _random_ip()})
        finally:
            app.dependency_overrides.pop(rag_subject, None)
        # No budget seeded for the bystander -> not rejected (honest-null 200).
        assert allowed.status_code == 200
        assert allowed.json()["state"] == "honest_null"

    # The breach is audited (resource_id NULL, ids in details).
    async with factory() as session:
        reason = await session.scalar(text("""
            SELECT reason_code FROM audit_events
            WHERE action='limits.budget.exhausted' AND actor_user_id=:actor
            ORDER BY sequence DESC LIMIT 1
        """), {"actor": spender})
    assert reason == "budget_exhausted"


# --------------------------------------------------------------------------- #
# Circuit breaker + provider timeout
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_hanging_provider_is_timeout_bounded_then_breaker_opens_503(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    # Generous budgets so only the breaker (not the cost budget) can refuse.
    await _set_int_setting(factory, owner, "limits.budget.subject_daily_units", 100_000)
    await _set_int_setting(
        factory, owner, "limits.budget.global_daily_units", 100_000_000,
    )
    source_key = f"breaker.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"BRK.{uuid.uuid4().hex}",
        text_value="Breaker synthetic evidence is current and verified.",
    )
    tuned = rag_settings(tmp_path).model_copy(update={
        "rag_provider_timeout_seconds": 0.05,
        "limits_breaker_failure_threshold": 2,
        "limits_breaker_cooldown_seconds": 30,
    })
    provider = HangingProvider(f"hang-{uuid.uuid4().hex}")

    def build() -> AnswerService:
        return AnswerService(
            tuned,
            factory=factory,
            retrieval=RetrievalService(tuned, factory=factory),
            provider=provider,
        )

    # Call 1: two hung attempts, each cut at the timeout -> honest_null. The
    # timeout must bound wall time even with the breaker in the loop.
    started = time.perf_counter()
    first = await build().ask(
        subject(owner),
        "What breaker evidence is current?",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="breaker-1",
    )
    elapsed = time.perf_counter() - started
    assert first.state == "honest_null"
    assert elapsed < 1.0
    assert provider.calls == 2  # both attempts made before the breaker opened

    # Call 2: breaker is now open -> immediate typed 503, provider NOT called.
    with pytest.raises(ProviderUnavailable) as outage:
        await build().ask(
            subject(owner),
            "What breaker evidence is current?",
            filters=SearchFilters(source_key=source_key),
            require_verified=True,
            conversation_id=None,
            request_id="breaker-2",
        )
    assert provider.calls == 2  # unchanged: no call was made while open
    assert outage.value.retry_after >= 1


@pytest.mark.asyncio
async def test_failing_provider_opens_breaker_across_asks(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    await _set_int_setting(factory, owner, "limits.budget.subject_daily_units", 100_000)
    await _set_int_setting(
        factory, owner, "limits.budget.global_daily_units", 100_000_000,
    )
    source_key = f"fail.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"FAIL.{uuid.uuid4().hex}",
        text_value="Failing synthetic evidence is current and verified.",
    )
    tuned = rag_settings(tmp_path).model_copy(update={
        "limits_breaker_failure_threshold": 2,
        "limits_breaker_cooldown_seconds": 60,
    })
    provider = FailingProvider(f"fail-{uuid.uuid4().hex}")

    def build() -> AnswerService:
        return AnswerService(
            tuned,
            factory=factory,
            retrieval=RetrievalService(tuned, factory=factory),
            provider=provider,
        )

    result = await build().ask(
        subject(owner),
        "What failing evidence is current?",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="fail-1",
    )
    assert result.state == "honest_null"
    assert provider.calls == 2
    with pytest.raises(ProviderUnavailable):
        await build().ask(
            subject(owner),
            "What failing evidence is current?",
            filters=SearchFilters(source_key=source_key),
            require_verified=True,
            conversation_id=None,
            request_id="fail-2",
        )


# --------------------------------------------------------------------------- #
# Job backpressure against the real DB
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_job_capacity_admits_when_empty_and_sheds_over_cap(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    # A fresh source published-but-not-indexed leaves one 'pending' reindex
    # outbox row -> a real index-family backlog of 1.
    await _publish_pending(tmp_path, factory, owner)

    async with factory() as session, session.begin():
        await GovernanceRepository().set_setting(
            session,
            setting_key="limits.jobs.index_max_backlog",
            value_type="integer",
            value=1,
            updated_by=owner,
            reason="tip-012 integration index cap",
        )
    async with factory() as session:
        # Ingestion family is empty -> admitted (real counting SQL).
        admitted = await check_capacity(session, "ingestion", retry_after=15)
        assert admitted == 0
        index_outstanding = await outstanding_count(session, "index")
        assert index_outstanding >= 1
        # Index family is at/over its cap -> shed.
        with pytest.raises(QueueSaturated) as saturated:
            await check_capacity(session, "index", retry_after=15)
    assert saturated.value.family == "index"
    assert saturated.value.cap == 1
    assert saturated.value.retry_after == 15


async def _publish_pending(
    root: Path,
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
) -> None:
    """Publish a source without indexing it, leaving a pending reindex row."""
    from sot_fixtures import NOW, build_package
    from sqlalchemy import text as _text

    from rtr_copilot.sot.service import SOTPublishService

    source_key = f"idx.{uuid.uuid4().hex}"
    package_root = build_package(
        root,
        curator_id=actor_id,
        owner_id=actor_id,
        source_key=source_key,
        record_key=f"IDX.{uuid.uuid4().hex}",
        revision=1,
        ordinal=1,
        supersedes=False,
        classification="internal",
        text="Index backlog synthetic evidence.",
        additional_records=None,
    )
    sot = SOTPublishService(rag_settings(root), factory=factory, clock=lambda: NOW)
    staged = await sot.stage(
        package_root.name, actor_id=actor_id, request_id="idx-stage",
    )
    assert (await sot.validate(
        staged.package_id, actor_id=actor_id, request_id="idx-validate",
    )).valid
    published = await sot.publish(
        staged.package_id, actor_id=actor_id, request_id="idx-publish",
    )
    async with factory() as session:
        status = await session.scalar(_text("""
            SELECT status FROM sot_reindex_outbox WHERE run_id=:run_id
        """), {"run_id": published.run_id})
    assert status == "pending"
