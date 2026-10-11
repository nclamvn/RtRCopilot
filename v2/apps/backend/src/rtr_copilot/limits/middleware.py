"""App-layer rate-limit + body-size middleware (D-012-03, AC-04).

Runs inside the request-context middleware (so ``request.state.request_id`` is
already set and every response — including a rejection — is logged and carries
``X-Request-ID``). For each request it: classifies the path into a budget class,
rejects an over-limit body with a typed 413, resolves the caller's subject id
(after identity, before any expensive work), and enforces the per-IP and
per-subject fixed windows for the class with a typed 429 + ``Retry-After``.

Redis-down policy (documented in DEVIATIONS): the rate-limit *decision* is
fail-closed in the normal sense — a reachable Redis reporting an over-limit
count rejects. When Redis is unreachable the limiter degrades to fail-open for
every class EXCEPT ``auth`` in production, which fails closed (503
``rate_limiter_unavailable``). In non-production the whole limiter fails open so
the unit suite (which runs without a live Redis) is unaffected.
"""

import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rtr_copilot.config import Settings, get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.limits.errors import limit_response
from rtr_copilot.limits.rate_limit import RateLimiter
from rtr_copilot.limits.redis_support import open_redis
from rtr_copilot.observability.http import meter_error
from rtr_copilot.observability.metrics import RATE_LIMIT_REJECTIONS
from rtr_copilot.repositories.audit import AuditRepository

logger = logging.getLogger("rtr_copilot.limits")

SKIP_PREFIXES: tuple[str, ...] = ("/health", "/metrics")
SKIP_EXACT: frozenset[str] = frozenset({
    "/",
    "/favicon.ico",
    "/openapi.json",
    "/docs",
    "/redoc",
})


def classify(method: str, path: str) -> str:
    """Map a request to its budget class (AC-04's distinct classes)."""
    if path == "/auth" or path.startswith("/auth/"):
        return "auth"
    if path == "/api/v1/ask":
        return "ask"
    if path.startswith("/api/v1/files/uploads") and method == "POST":
        return "upload"
    if (
        method == "POST"
        and path.startswith("/api/v1/templates/")
        and path.endswith("/render")
    ):
        return "render"
    if path.startswith("/api/v1/admin"):
        return "admin"
    # TIP-054.2/.3: context resolve/packet POSTs are bounded read-compute,
    # but scoped memory writes and action-domain mutations must not inherit
    # the more permissive read window. Reuse existing finite write classes;
    # these classifications do not authorize a capability or source effect.
    mutation = method in {"POST", "PUT", "PATCH", "DELETE"}
    memory_path = "/api/v1/context/memory"
    if mutation and (path == memory_path or path.startswith(f"{memory_path}/")):
        return "upload"
    action_path = "/api/v1/actions"
    capability_path = f"{action_path}/capabilities"
    if mutation and (
        path == capability_path or path.startswith(f"{capability_path}/")
    ):
        return "admin"
    if mutation and (path == action_path or path.startswith(f"{action_path}/")):
        return "render"
    return "default-read"


CLASS_MAX_ATTR: dict[str, str] = {
    "auth": "limits_rate_auth_max",
    "ask": "limits_rate_ask_max",
    "upload": "limits_rate_upload_max",
    "render": "limits_rate_render_max",
    "admin": "limits_rate_admin_max",
    "default-read": "limits_rate_default_read_max",
}


def class_limit(settings: Settings, cls: str) -> int:
    return int(getattr(settings, CLASS_MAX_ATTR[cls]))


def body_limit(settings: Settings, cls: str) -> int:
    if cls == "upload":
        return settings.ingestion_max_upload_bytes
    return settings.limits_max_body_bytes


def client_ip(request: Request) -> str:
    """Client IP behind the single trusted ingress hop.

    Caddy appends the immediate peer to ``X-Forwarded-For``, so the last token
    is the real client (and cannot be spoofed by a client-supplied prefix).
    Falling back to the socket peer covers the dev profile with no proxy.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [item.strip() for item in forwarded.split(",") if item.strip()]
        if parts:
            return parts[-1]
    if request.client is not None:
        return request.client.host
    return "unknown"


async def resolve_subject_id(redis: Any, session_id: str | None) -> str | None:
    """One cheap GET of the session envelope for rate-limit keying only.

    This intentionally does not re-validate the session (the endpoint's own
    ``current_subject`` does that); an invalid/expired session simply yields no
    subject key and the request is limited per-IP.
    """
    if not session_id:
        return None
    raw = await redis.get(f"rtr:session:{session_id}")
    if not raw:
        return None
    try:
        return str(json.loads(raw)["user_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


@dataclass
class LimitRejection:
    response: JSONResponse
    action: str
    reason: str
    subject_id: str | None
    details: dict[str, Any] = field(default_factory=dict)


async def apply_limits(
    request: Request,
    redis: Any,
    settings: Settings,
) -> LimitRejection | None:
    """Pure decision: return a rejection to send, or ``None`` to proceed.

    Kept side-effect free (no DB audit) so it is directly unit-testable with a
    fake Redis; the caller performs the best-effort audit.
    """
    method = request.method
    path = request.url.path
    if path in SKIP_EXACT or any(path.startswith(p) for p in SKIP_PREFIXES):
        return None
    request_id = str(getattr(request.state, "request_id", ""))
    cls = classify(method, path)

    # 1) Body-size guard (typed 413) — header-only, never consumes the stream.
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            length = -1
        if length > body_limit(settings, cls):
            return LimitRejection(
                response=limit_response(request_id, "body_too_large"),
                action="limits.body.rejected",
                reason="body_too_large",
                subject_id=None,
                details={
                    "class": cls,
                    "declared_bytes": length,
                    "limit_bytes": body_limit(settings, cls),
                },
            )

    # 2) Resolve subject (after identity, before expensive work) and enforce the
    #    per-IP and per-subject windows. A Redis fault applies the fail policy.
    ip = client_ip(request)
    limiter = RateLimiter(redis, window_seconds=settings.limits_rate_window_seconds)
    limit = class_limit(settings, cls)
    try:
        session_id = request.cookies.get(settings.session_cookie_name)
        subject_id = await resolve_subject_id(redis, session_id)
        scopes: list[tuple[str, str]] = [("ip", ip)]
        if subject_id is not None:
            scopes.append(("subject", subject_id))
        worst_retry = 0
        breached_scope: str | None = None
        for scope, identity in scopes:
            allowed, retry_after = await limiter.hit(
                cls=cls,
                scope=scope,
                identity=identity,
                limit=limit,
            )
            if not allowed and breached_scope is None:
                breached_scope = scope
            worst_retry = max(worst_retry, retry_after)
        if breached_scope is not None:
            return LimitRejection(
                response=limit_response(
                    request_id,
                    "rate_limited",
                    retry_after=worst_retry,
                ),
                action="limits.rate.rejected",
                reason="rate_limited",
                subject_id=subject_id,
                details={
                    "class": cls,
                    "scope": breached_scope,
                    "limit": limit,
                    "window_seconds": settings.limits_rate_window_seconds,
                    "retry_after_seconds": worst_retry,
                },
            )
        return None
    except Exception as error:
        # A rate limiter must never turn a Redis fault (or any misbehaving
        # client) into a 500. Any failure of the limiter itself degrades per
        # the documented policy: fail-closed for auth in production, fail-open
        # (logged) for every other class and environment.
        if cls == "auth" and settings.app_env == "production":
            logger.error(json.dumps({
                "event": "rate_limiter_unavailable",
                "request_id": request_id,
                "class": cls,
                "policy": "fail_closed",
            }))
            return LimitRejection(
                response=limit_response(request_id, "rate_limiter_unavailable"),
                action="limits.rate.unavailable",
                reason="rate_limiter_unavailable",
                subject_id=None,
                details={"class": cls, "policy": "fail_closed"},
            )
        logger.warning(json.dumps({
            "event": "rate_limiter_degraded",
            "request_id": request_id,
            "class": cls,
            "policy": "fail_open",
            "error_type": type(error).__name__,
        }))
        return None


async def _audit_rejection(
    redis: Any,
    settings: Settings,
    rejection: LimitRejection,
    *,
    request_id: str,
) -> None:
    """Best-effort, de-duplicated audit of a limit event (never raises).

    A flood is collapsed to one audit event per identity per window via a Redis
    NX marker, so limit enforcement can never stall the globally-serialized
    audit chain. If the marker cannot be claimed (already audited, or Redis
    unreachable) the event is skipped.
    """
    marker = (
        f"rtr:limit-audited:{rejection.reason}:{rejection.subject_id or 'anon'}:"
        f"{request_id[:8]}"
    )
    try:
        claimed = await redis.set(
            marker,
            "1",
            nx=True,
            ex=settings.limits_rate_window_seconds,
        )
    except Exception:
        claimed = False
    if not claimed:
        return
    try:
        actor = (
            uuid.UUID(rejection.subject_id) if rejection.subject_id else None
        )
        async with UnitOfWork().transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user" if actor else "anonymous",
                actor_user_id=actor,
                action=rejection.action,
                result="deny",
                reason_code=rejection.reason,
                request_id=request_id,
                resource_type="request_limit",
                details=rejection.details,
            )
    except Exception:
        logger.warning(json.dumps({
            "event": "limit_audit_failed",
            "request_id": request_id,
            "reason": rejection.reason,
        }))


def install_limits_middleware(app: FastAPI) -> None:
    """Register the limits middleware. Call BEFORE the request-context
    middleware is defined so request-context stays the outermost layer."""

    @app.middleware("http")
    async def _limits(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        settings = get_settings()
        if not settings.limits_enabled:
            return await call_next(request)
        redis = open_redis(settings)
        try:
            rejection = await apply_limits(request, redis, settings)
            if rejection is not None:
                # Meter the limit hit (AC-08): bounded reason/class/scope labels
                # plus the typed-error counter. Metrics only; never affects the
                # decision Builder 2 already made.
                RATE_LIMIT_REJECTIONS.labels(
                    reason=rejection.reason,
                    route_class=str(rejection.details.get("class", "other")),
                    scope=str(rejection.details.get("scope", "-")),
                ).inc()
                meter_error(rejection.reason, request.url.path)
                await _audit_rejection(
                    redis,
                    settings,
                    rejection,
                    request_id=str(getattr(request.state, "request_id", "")),
                )
                return rejection.response
        finally:
            with contextlib.suppress(Exception):
                await redis.aclose()
        return await call_next(request)
