"""Redis-backed fixed-window rate limiter, keyed independently per scope.

A fixed-window counter (INCR + EXPIRE) is the smallest correct Redis primitive
here: one round trip, exact per-window counts, and a deterministic
``Retry-After`` (seconds until the current window rolls over). The middleware
calls :meth:`RateLimiter.hit` once for the client-IP scope and once for the
subject scope so one subject's traffic can never exhaust another's window and a
shared NAT egress IP can never borrow a subject's allowance.
"""

import time
from collections.abc import Callable
from typing import Any

#: The distinct budget classes required by AC-04. ``default-read`` is the
#: catch-all for authenticated reads.
RATE_CLASSES: tuple[str, ...] = (
    "auth",
    "ask",
    "upload",
    "render",
    "admin",
    "default-read",
)


class RateLimiter:
    def __init__(
        self,
        redis: Any,
        *,
        window_seconds: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.window = max(1, window_seconds)
        self._now = now

    def _window_start(self, now: float) -> int:
        return int(now) // self.window * self.window

    def retry_after(self, now: float) -> int:
        return max(1, self.window - int(now) % self.window)

    async def hit(
        self,
        *,
        cls: str,
        scope: str,
        identity: str,
        limit: int,
    ) -> tuple[bool, int]:
        """Count one request against ``(cls, scope, identity)``.

        Returns ``(allowed, retry_after_seconds)``. ``allowed`` is ``False``
        once the window count exceeds ``limit``; the counter still increments
        so a sustained flood keeps tripping until the window resets.
        """
        now = self._now()
        window_start = self._window_start(now)
        key = f"rtr:rl:{cls}:{scope}:{identity}:{window_start}"
        count = int(await self.redis.incr(key))
        if count == 1:
            # +1s guards against the counter outliving its window on a slow
            # EXPIRE without ever under-counting inside the window.
            await self.redis.expire(key, self.window + 1)
        return count <= limit, self.retry_after(now)
