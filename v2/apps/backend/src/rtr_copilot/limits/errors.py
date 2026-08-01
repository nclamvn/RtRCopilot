"""Typed limit errors and their HTTP status mapping (extends STATUS_BY_CODE).

Every limit event surfaces one of these machine-readable codes with the same
envelope shape the rest of the API uses (`{"error": {code, message}, request_id}`)
plus a `Retry-After` header where a retry is meaningful.
"""

from typing import Any

from fastapi.responses import JSONResponse

#: Canonical status for every TIP-012 Task 2 limit code. Mirrored into the
#: governance ``STATUS_BY_CODE`` table so codes that transit that layer map too.
LIMIT_STATUS_BY_CODE: dict[str, int] = {
    "rate_limited": 429,
    "budget_exhausted": 429,
    "queue_saturated": 429,
    "body_too_large": 413,
    "provider_unavailable": 503,
    "rate_limiter_unavailable": 503,
}

LIMIT_MESSAGES: dict[str, str] = {
    "rate_limited": "Too many requests; retry after the window resets",
    "budget_exhausted": "Daily AI usage budget exhausted; retry after reset",
    "queue_saturated": "Processing queue is saturated; retry shortly",
    "body_too_large": "Request body exceeds the configured size limit",
    "provider_unavailable": "AI provider is temporarily unavailable",
    "rate_limiter_unavailable": "Rate limiter is unavailable; request refused",
}


def limit_response(
    request_id: str,
    code: str,
    *,
    retry_after: int | None = None,
) -> JSONResponse:
    """Build the typed limit envelope with an optional ``Retry-After`` header."""
    headers: dict[str, str] = {"X-Request-ID": request_id}
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, int(retry_after)))
    payload: dict[str, Any] = {
        "error": {"code": code, "message": LIMIT_MESSAGES[code]},
        "request_id": request_id,
    }
    return JSONResponse(
        status_code=LIMIT_STATUS_BY_CODE[code],
        content=payload,
        headers=headers,
    )
