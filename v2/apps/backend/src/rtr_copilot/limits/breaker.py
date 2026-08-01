"""Per-provider circuit breaker with Redis-shared state (AC-06).

Consecutive failures (timeout or error) trip the breaker open; while open the
provider is *not called at all* — the caller raises :class:`ProviderUnavailable`
(typed 503) immediately, so a degraded provider can never tie up a request slot.
After a cooldown one half-open trial is admitted: success closes the breaker,
failure re-opens it and restarts the cooldown. State lives in Redis so every API
replica shares one view of a provider's health.

This wraps — it does not replace — the existing ``asyncio.timeout`` around the
provider call in ``rag/answering.py``: the timeout bounds a single call's wall
time; the breaker stops *making* calls once a provider is unhealthy.
"""

import time
from collections.abc import Callable
from typing import Any


class ProviderUnavailable(Exception):
    def __init__(self, provider: str, *, retry_after: int) -> None:
        super().__init__("provider_unavailable")
        self.code = "provider_unavailable"
        self.provider = provider
        self.retry_after = retry_after


class CircuitBreaker:
    def __init__(
        self,
        redis: Any,
        provider: str,
        *,
        threshold: int,
        cooldown_seconds: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.provider = provider
        self.threshold = max(1, threshold)
        self.cooldown = max(1, cooldown_seconds)
        self._now = now
        self._failure_key = f"rtr:cb:{provider}:failures"
        self._opened_key = f"rtr:cb:{provider}:opened_at"

    async def allow(self) -> tuple[bool, int]:
        """Return ``(admit_call, retry_after)``.

        ``admit_call`` is ``True`` when closed or when a half-open trial is due;
        ``retry_after`` is the seconds of cooldown left when refused.
        """
        failures = int(await self.redis.get(self._failure_key) or 0)
        if failures < self.threshold:
            return True, 0
        opened_at = float(await self.redis.get(self._opened_key) or 0.0)
        elapsed = self._now() - opened_at
        if elapsed >= self.cooldown:
            return True, 0
        return False, max(1, int(self.cooldown - elapsed))

    async def record_success(self) -> None:
        await self.redis.delete(self._failure_key)
        await self.redis.delete(self._opened_key)

    async def record_failure(self) -> int:
        failures = int(await self.redis.incr(self._failure_key))
        retention = max(self.cooldown * 4, 60)
        await self.redis.expire(self._failure_key, retention)
        if failures >= self.threshold:
            # (Re)start the cooldown: this both opens a closed breaker and
            # restarts the window when a half-open trial fails.
            await self.redis.set(self._opened_key, repr(self._now()))
            await self.redis.expire(self._opened_key, retention)
        return failures
