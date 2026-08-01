"""HTTP metrics middleware and typed-error metering for the api (AC-08).

The middleware is installed as the OUTERMOST layer so it observes the final
status of every response — including limit rejections (429/413) produced by the
Builder-2 limits middleware and 500s synthesized by the request-context
handler. It records latency into :data:`HTTP_REQUEST_DURATION` keyed by a
bounded route *class* (never the raw path) and the numeric status.

``meter_error`` is called from the api exception handlers and from the limits
layer to increment :data:`HTTP_ERRORS` by the machine-readable error code, so
"error counts by typed code" is a first-class series rather than something you
must reconstruct from status codes.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request

from rtr_copilot.observability.metrics import HTTP_ERRORS, HTTP_REQUEST_DURATION

# Ordered longest/most-specific prefix first. Every entry maps to a bounded
# class label; anything unmatched collapses to "other" so cardinality is fixed
# no matter what path is requested.
_PREFIX_CLASSES: tuple[tuple[str, str], ...] = (
    ("/api/v1/ask", "ask"),
    ("/api/v1/files/uploads", "upload"),
    ("/api/v1/files", "files"),
    ("/api/v1/templates", "documents"),
    ("/api/v1/document-os", "documents"),
    ("/api/v1/documents", "documents"),
    ("/api/v1/admin", "admin"),
    ("/api/v1/audit", "audit"),
    ("/api/v1/governance", "governance"),
    ("/api/v1/gaps", "governance"),
    ("/api/v1/sot", "sot"),
    ("/api/v1/research", "research"),
    ("/auth", "auth"),
    ("/health", "health"),
    ("/metrics", "metrics"),
    ("/system", "system"),
)


def route_class(path: str) -> str:
    """Map a request path to its bounded metric route class.

    A render submission (``/api/v1/templates/{v}/render``) is still the
    ``documents`` class; the finer ``render`` limit class lives in the limits
    layer. Uploads are split out because their latency/size profile differs
    sharply from other file reads. The table is ordered most-specific first, so
    the first prefix match wins; anything unmatched collapses to ``other``.
    """
    if path == "/":
        return "root"
    for prefix, label in _PREFIX_CLASSES:
        if path == prefix or path.startswith(prefix + "/"):
            return label
    return "other"


def meter_error(code: str, path: str) -> None:
    """Increment the typed-error counter for ``code`` on ``path``'s class."""
    HTTP_ERRORS.labels(code=code, route_class=route_class(path)).inc()


def install_metrics_middleware(app: FastAPI) -> None:
    """Register the HTTP latency middleware.

    Call AFTER every other ``@app.middleware`` so this is the outermost layer
    and sees the terminal status of limit rejections and 500s alike.
    """

    @app.middleware("http")
    async def _metrics(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        cls = route_class(request.url.path)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            HTTP_REQUEST_DURATION.labels(
                route_class=cls,
                method=request.method,
                status=str(status),
            ).observe(time.perf_counter() - started)
