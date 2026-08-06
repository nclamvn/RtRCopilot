"""TIP-012 Task 2 — unit coverage for the app-layer limiters (fakes only).

Every edge required by AC-04..07: fixed-window rollover, per-subject vs per-IP
independence, Retry-After math, budget debit/breach/rollover with subject vs
global isolation, breaker open/half-open/close, job-cap boundary, request
classification and the Redis-down fail policy.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import Request

from rtr_copilot.config import Settings
from rtr_copilot.limits.backpressure import QueueSaturated, check_capacity
from rtr_copilot.limits.breaker import CircuitBreaker, ProviderUnavailable
from rtr_copilot.limits.budget import (
    BudgetExhausted,
    CostBudget,
    seconds_to_utc_midnight,
    utc_day,
)
from rtr_copilot.limits.errors import LIMIT_STATUS_BY_CODE, limit_response
from rtr_copilot.limits.middleware import (
    apply_limits,
    classify,
    client_ip,
)
from rtr_copilot.limits.rate_limit import RATE_CLASSES, RateLimiter


class FakeRedis:
    """Minimal async Redis supporting the ops the limiters use."""

    def __init__(self) -> None:
        self.values: dict[str, int | str] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    async def incrby(self, key: str, amount: int) -> int:
        value = int(self.values.get(key, 0)) + int(amount)
        self.values[key] = value
        return value

    async def get(self, key: str) -> Any:
        value = self.values.get(key)
        return None if value is None else str(value)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                removed += 1
        return removed

    async def aclose(self) -> None:
        return None


class BrokenRedis(FakeRedis):
    async def incr(self, key: str) -> int:
        raise RuntimeError("redis-down")

    async def get(self, key: str) -> Any:
        raise RuntimeError("redis-down")


# --------------------------------------------------------------------------- #
# RateLimiter
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rate_limiter_boundary_and_retry_after() -> None:
    clock = [1000.0]
    redis = FakeRedis()
    limiter = RateLimiter(redis, window_seconds=60, now=lambda: clock[0])
    outcomes = [
        await limiter.hit(cls="ask", scope="ip", identity="1.1.1.1", limit=3)
        for _ in range(4)
    ]
    allowed = [item[0] for item in outcomes]
    assert allowed == [True, True, True, False]
    # Retry-After = seconds until this fixed window rolls over.
    assert outcomes[-1][1] == 60 - int(clock[0]) % 60


@pytest.mark.asyncio
async def test_rate_limiter_window_rollover_resets_count() -> None:
    clock = [100.0]
    redis = FakeRedis()
    limiter = RateLimiter(redis, window_seconds=60, now=lambda: clock[0])
    for _ in range(3):
        await limiter.hit(cls="ask", scope="ip", identity="ip", limit=3)
    blocked, _ = await limiter.hit(cls="ask", scope="ip", identity="ip", limit=3)
    assert blocked is False
    # Cross the 120s boundary -> a fresh window key -> count resets.
    clock[0] = 121.0
    allowed, _ = await limiter.hit(cls="ask", scope="ip", identity="ip", limit=3)
    assert allowed is True


@pytest.mark.asyncio
async def test_rate_limiter_subject_and_ip_scopes_are_independent() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis, window_seconds=60, now=lambda: 500.0)
    # Exhaust one subject.
    for _ in range(2):
        await limiter.hit(cls="ask", scope="subject", identity="u1", limit=2)
    blocked, _ = await limiter.hit(cls="ask", scope="subject", identity="u1", limit=2)
    assert blocked is False
    # A different subject and the IP scope keep full allowance.
    other, _ = await limiter.hit(cls="ask", scope="subject", identity="u2", limit=2)
    ip_scope, _ = await limiter.hit(cls="ask", scope="ip", identity="u1", limit=2)
    assert other is True and ip_scope is True


# --------------------------------------------------------------------------- #
# CostBudget
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_budget_debit_and_subject_breach() -> None:
    redis = FakeRedis()
    budget = CostBudget(redis, subject_daily=3, global_daily=100)
    await budget.check("subject-a")  # 0 used -> allowed
    subject_used, _ = await budget.debit("subject-a", 3)
    assert subject_used == 3
    with pytest.raises(BudgetExhausted) as breach:
        await budget.check("subject-a")
    assert breach.value.scope == "subject"
    assert breach.value.retry_after == seconds_to_utc_midnight()


@pytest.mark.asyncio
async def test_budget_global_breach_and_subject_isolation() -> None:
    redis = FakeRedis()
    budget = CostBudget(redis, subject_daily=100, global_daily=4)
    await budget.debit("subject-a", 2)
    await budget.debit("subject-b", 2)
    # Neither subject is over its own ceiling, but the shared global cap is.
    with pytest.raises(BudgetExhausted) as breach:
        await budget.check("subject-a")
    assert breach.value.scope == "global"
    # A fresh subject also sees the global breach (system-wide protection).
    with pytest.raises(BudgetExhausted):
        await budget.check("subject-c")


@pytest.mark.asyncio
async def test_budget_rolls_over_at_utc_midnight() -> None:
    day = [datetime(2026, 8, 1, 23, 59, 0, tzinfo=UTC)]
    redis = FakeRedis()
    budget = CostBudget(
        redis, subject_daily=1, global_daily=100, clock=lambda: day[0],
    )
    await budget.debit("subject-a", 1)
    with pytest.raises(BudgetExhausted):
        await budget.check("subject-a")
    # Next UTC day -> new date-scoped key -> allowance restored.
    day[0] = datetime(2026, 8, 2, 0, 1, 0, tzinfo=UTC)
    await budget.check("subject-a")
    assert utc_day(day[0]) == "20260802"


@pytest.mark.asyncio
async def test_token_budget_is_independent_from_call_budget() -> None:
    redis = FakeRedis()
    call_budget = CostBudget(redis, subject_daily=10, global_daily=100)
    token_budget = CostBudget(
        redis,
        subject_daily=1_000,
        global_daily=2_000,
        metric="tokens",
    )
    await call_budget.debit("subject-a", 1)
    await token_budget.debit("subject-a", 1_000)
    await call_budget.check("subject-a")
    with pytest.raises(BudgetExhausted) as breach:
        await token_budget.check("subject-a")
    assert breach.value.scope == "subject_tokens"


# --------------------------------------------------------------------------- #
# CircuitBreaker
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_breaker_opens_half_opens_and_closes() -> None:
    clock = [1000.0]
    redis = FakeRedis()
    breaker = CircuitBreaker(
        redis, "local", threshold=3, cooldown_seconds=30, now=lambda: clock[0],
    )
    admitted, _ = await breaker.allow()
    assert admitted is True
    for _ in range(3):
        await breaker.record_failure()
    admitted, retry_after = await breaker.allow()
    assert admitted is False
    assert retry_after == 30  # full cooldown remaining at t0
    # Part-way through the cooldown the breaker is still open.
    clock[0] = 1020.0
    admitted, retry_after = await breaker.allow()
    assert admitted is False and retry_after == 10
    # After the cooldown one half-open trial is admitted.
    clock[0] = 1031.0
    admitted, _ = await breaker.allow()
    assert admitted is True
    # A successful trial closes the breaker.
    await breaker.record_success()
    admitted, _ = await breaker.allow()
    assert admitted is True
    assert redis.values.get("rtr:cb:local:failures") is None


@pytest.mark.asyncio
async def test_breaker_half_open_failure_reopens() -> None:
    clock = [0.0]
    redis = FakeRedis()
    breaker = CircuitBreaker(
        redis, "p", threshold=2, cooldown_seconds=10, now=lambda: clock[0],
    )
    await breaker.record_failure()
    await breaker.record_failure()
    assert (await breaker.allow())[0] is False
    clock[0] = 11.0  # half-open trial admitted
    assert (await breaker.allow())[0] is True
    await breaker.record_failure()  # trial fails -> reopen, restart cooldown
    admitted, retry_after = await breaker.allow()
    assert admitted is False and retry_after == 10


# --------------------------------------------------------------------------- #
# Backpressure
# --------------------------------------------------------------------------- #
class _CountSession:
    def __init__(self, count: int) -> None:
        self._count = count

    async def scalar(self, *_args: Any, **_kwargs: Any) -> int:
        return self._count


@pytest.mark.asyncio
async def test_check_capacity_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    import rtr_copilot.limits.backpressure as bp

    async def fake_cap(_session: Any, _key: str) -> int:
        return 5

    monkeypatch.setattr(bp, "effective_int_setting", fake_cap)
    # At the cap -> shed; one below -> admitted.
    with pytest.raises(QueueSaturated) as saturated:
        await check_capacity(_CountSession(5), "ingestion", retry_after=15)
    assert saturated.value.outstanding == 5 and saturated.value.cap == 5
    assert saturated.value.retry_after == 15
    admitted = await check_capacity(_CountSession(4), "ingestion", retry_after=15)
    assert admitted == 4


# --------------------------------------------------------------------------- #
# Errors / status table
# --------------------------------------------------------------------------- #
def test_limit_status_table_and_response_headers() -> None:
    assert LIMIT_STATUS_BY_CODE["rate_limited"] == 429
    assert LIMIT_STATUS_BY_CODE["body_too_large"] == 413
    assert LIMIT_STATUS_BY_CODE["provider_unavailable"] == 503
    response = limit_response("req-1", "rate_limited", retry_after=12)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "12"


# --------------------------------------------------------------------------- #
# Classification / client IP
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/auth/login", "auth"),
        ("POST", "/auth/callback", "auth"),
        ("POST", "/api/v1/ask", "ask"),
        ("POST", "/api/v1/files/uploads", "upload"),
        ("POST", "/api/v1/files/uploads/abc/retry", "upload"),
        ("POST", "/api/v1/templates/xyz/render", "render"),
        ("PUT", "/api/v1/admin/settings/limits.budget.global_daily_units", "admin"),
        ("GET", "/api/v1/files", "default-read"),
        ("GET", "/api/v1/conversations", "default-read"),
    ],
)
def test_classify(method: str, path: str, expected: str) -> None:
    assert classify(method, path) == expected
    assert expected in RATE_CLASSES


def _request(
    path: str,
    *,
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    request = Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("9.9.9.9", 1),
        "scheme": "http",
    })
    request.state.request_id = "req-test"
    return request


def test_client_ip_prefers_last_forwarded_hop() -> None:
    request = _request(
        "/api/v1/files",
        headers=[(b"x-forwarded-for", b"1.2.3.4, 10.0.0.9")],
    )
    assert client_ip(request) == "10.0.0.9"
    assert client_ip(_request("/api/v1/files")) == "9.9.9.9"


# --------------------------------------------------------------------------- #
# apply_limits (middleware decision)
# --------------------------------------------------------------------------- #
def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "postgres_dsn": "postgresql://user:password@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "local",
        "s3_secret_key": "local-secret",
        "s3_bucket": "rtr-test",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_limits_skips_health_and_metrics() -> None:
    redis = BrokenRedis()
    settings = _settings()
    for path in ("/health/ready", "/metrics", "/"):
        assert await apply_limits(_request(path), redis, settings) is None


@pytest.mark.asyncio
async def test_apply_limits_body_too_large_is_413() -> None:
    redis = FakeRedis()
    settings = _settings(limits_max_body_bytes=1024)
    request = _request(
        "/api/v1/ask",
        method="POST",
        headers=[(b"content-length", b"9999")],
    )
    rejection = await apply_limits(request, redis, settings)
    assert rejection is not None
    assert rejection.response.status_code == 413
    assert rejection.reason == "body_too_large"


@pytest.mark.asyncio
async def test_apply_limits_rate_limits_after_threshold() -> None:
    redis = FakeRedis()
    settings = _settings(limits_rate_default_read_max=2, limits_rate_window_seconds=60)
    statuses = []
    for _ in range(3):
        rejection = await apply_limits(_request("/api/v1/files"), redis, settings)
        statuses.append(None if rejection is None else rejection.response.status_code)
    assert statuses == [None, None, 429]


@pytest.mark.asyncio
async def test_apply_limits_ip_isolation_between_callers() -> None:
    redis = FakeRedis()
    settings = _settings(limits_rate_default_read_max=1)
    hot = _request("/api/v1/files", headers=[(b"x-forwarded-for", b"5.5.5.5")])
    cool = _request("/api/v1/files", headers=[(b"x-forwarded-for", b"6.6.6.6")])
    assert await apply_limits(hot, redis, settings) is None
    assert (await apply_limits(hot, redis, settings)).response.status_code == 429  # type: ignore[union-attr]
    # A different client IP is unaffected by the first client's flood.
    assert await apply_limits(cool, redis, settings) is None


@pytest.mark.asyncio
async def test_apply_limits_fail_open_when_redis_down_non_auth() -> None:
    settings = _settings()
    assert await apply_limits(_request("/api/v1/files"), BrokenRedis(), settings) is None


@pytest.mark.asyncio
async def test_apply_limits_auth_fail_closed_in_production() -> None:
    settings = _settings()
    settings.app_env = "production"
    rejection = await apply_limits(
        _request("/auth/login"), BrokenRedis(), settings,
    )
    assert rejection is not None
    assert rejection.response.status_code == 503
    assert rejection.reason == "rate_limiter_unavailable"


def test_provider_unavailable_carries_retry_after() -> None:
    error = ProviderUnavailable("local", retry_after=17)
    assert error.retry_after == 17 and error.code == "provider_unavailable"
