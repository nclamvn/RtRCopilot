"""Shared Redis client factory for the app-layer limiters.

A fresh client per request/operation (closed in a ``finally``) matches the
existing app-wide pattern (auth ``clients``, ``system_ping``) and avoids
binding a pooled client to a stale event loop under the test transports. Short
socket timeouts keep a Redis outage from ever stalling a request slot — the
limiter fails fast and applies its documented fail-open / fail-closed policy.
"""

from typing import Any

from redis.asyncio import Redis

from rtr_copilot.config import Settings

CONNECT_TIMEOUT_SECONDS = 0.5


def open_redis(settings: Settings) -> Any:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=CONNECT_TIMEOUT_SECONDS,
    )
