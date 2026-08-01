"""Provider cost budgets (REQ-031): per-subject AND global daily ceilings.

Usage is metered in Redis counters that roll over at UTC midnight (the key
embeds the UTC date, and each debit refreshes a TTL to just past midnight).
Counters therefore survive a process restart as long as the Redis instance
persists (AOF/RDB) — see docs/limits.md. A breach raises :class:`BudgetExhausted`
which the ask surface renders as a typed 429 ``budget_exhausted`` with a
``Retry-After`` of the seconds remaining until reset.

The debited unit is the honest usage the local adapter exposes: provider
*calls* (``AnswerAdapter.calls``), which naturally counts a grounding-repair
retry as two. Swapping to a token estimate is a one-line change once a real
provider reports token usage (see SUGGESTIONS in the completion report).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any


class BudgetExhausted(Exception):
    """Raised before a provider call when a daily budget is already spent."""

    def __init__(self, scope: str, *, retry_after: int, limit: int, used: int) -> None:
        super().__init__("budget_exhausted")
        self.code = "budget_exhausted"
        self.scope = scope
        self.retry_after = retry_after
        self.limit = limit
        self.used = used


def utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%d")


def seconds_to_utc_midnight(now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1,
    )
    return max(1, int((midnight - moment).total_seconds()))


class CostBudget:
    def __init__(
        self,
        redis: Any,
        *,
        subject_daily: int,
        global_daily: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.redis = redis
        self.subject_daily = subject_daily
        self.global_daily = global_daily
        self._clock = clock

    def _keys(self, subject_id: str) -> tuple[str, str]:
        day = utc_day(self._clock())
        return (
            f"rtr:budget:subject:{day}:{subject_id}",
            f"rtr:budget:global:{day}",
        )

    async def usage(self, subject_id: str) -> tuple[int, int]:
        subject_key, global_key = self._keys(subject_id)
        subject_used = int(await self.redis.get(subject_key) or 0)
        global_used = int(await self.redis.get(global_key) or 0)
        return subject_used, global_used

    async def check(self, subject_id: str) -> None:
        """Refuse *before* debiting when either ceiling is already reached.

        Global is checked first so a system-wide cap protects every subject;
        the per-subject ceiling then bounds any single caller.
        """
        subject_used, global_used = await self.usage(subject_id)
        retry_after = seconds_to_utc_midnight(self._clock())
        if global_used >= self.global_daily:
            raise BudgetExhausted(
                "global",
                retry_after=retry_after,
                limit=self.global_daily,
                used=global_used,
            )
        if subject_used >= self.subject_daily:
            raise BudgetExhausted(
                "subject",
                retry_after=retry_after,
                limit=self.subject_daily,
                used=subject_used,
            )

    async def debit(self, subject_id: str, units: int) -> tuple[int, int]:
        """Record ``units`` of usage against both counters; returns new totals."""
        units = max(0, int(units))
        subject_key, global_key = self._keys(subject_id)
        ttl = seconds_to_utc_midnight(self._clock()) + 60
        subject_used = int(await self.redis.incrby(subject_key, units))
        await self.redis.expire(subject_key, ttl)
        global_used = int(await self.redis.incrby(global_key, units))
        await self.redis.expire(global_key, ttl)
        return subject_used, global_used
