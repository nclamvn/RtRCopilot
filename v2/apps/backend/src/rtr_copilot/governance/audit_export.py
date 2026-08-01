"""Admin-gated, checksummed audit export (TIP-012 Task 3, AC-10).

A bounded, deterministic JSONL export of audit events over a time range, gated
by the same admin policy decision the rest of the admin surface uses
(``manage_policies`` → ``Role.ADMIN``). The export action is itself appended to
the audit trail (the checksum is recorded, never the payload), so "who exported
what, when" is auditable. Details carried on each event are re-run through the
existing :func:`redact` rules before they leave the system, so no secret,
token, cookie or credential shape can ride out in an export.

Deliberately NOT mounted under ``/api/v1/admin``: that surface is a closed,
enumerated set whose ``audit`` sub-path is an immutability boundary (admins
never mutate truth). A read-only export lives on its own ``/api/v1/audit``
prefix, admin-gated by policy rather than by URL.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import text

from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.api import (
    GovernanceErrorEnvelope,
    _error,
    call,
    governance_subject,
)
from rtr_copilot.governance.service import policy
from rtr_copilot.repositories.audit import AuditRepository, redact

#: Hard ceiling on rows returned in a single export so an unbounded range can
#: never stream the whole table into memory. The response signals truncation.
MAX_EXPORT_ROWS = 50_000

router = APIRouter(
    prefix="/api/v1/audit",
    tags=["audit-export"],
    responses={
        status: {"model": GovernanceErrorEnvelope}
        for status in (400, 401, 403, 422)
    },
)


def _serialize_event(row: Any) -> str:
    """One deterministic JSONL line for an audit event (secrets redacted)."""
    payload = {
        "sequence": int(row["sequence"]),
        "event_id": str(row["event_id"]),
        "occurred_at": row["occurred_at"].astimezone(UTC).isoformat(),
        "actor_kind": row["actor_kind"],
        "actor_user_id": (
            str(row["actor_user_id"]) if row["actor_user_id"] else None
        ),
        "action": row["action"],
        "result": row["result"],
        "reason_code": row["reason_code"],
        "request_id": row["request_id"],
        "session_fingerprint": row["session_fingerprint"],
        "resource_id": str(row["resource_id"]) if row["resource_id"] else None,
        "resource_type": row["resource_type"],
        "matched_policy_ids": [str(item) for item in row["matched_policy_ids"]],
        "details": redact(dict(row["details"])),
        "event_hash": row["event_hash"],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AuditExportService:
    """Reads existing audit rows; performs no schema change (constraint)."""

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()

    def _admin_gate(self, subject: Subject, request_id: str) -> None:
        allowed = policy.decide(
            subject,
            "manage_policies",
            ResourceAttributes(classification="internal"),
            PolicyContext(request_id=request_id),
        ).allow
        if not allowed:
            raise PermissionError("admin_required")

    async def export(
        self,
        subject: Subject,
        *,
        start: datetime,
        end: datetime,
        limit: int,
        request_id: str,
    ) -> tuple[bytes, str, int, bool]:
        """Return ``(jsonl_bytes, checksum_hex, count, truncated)``.

        Reads ``[start, end)`` ordered by the append sequence, up to ``limit``
        rows (never above :data:`MAX_EXPORT_ROWS`), then audits the export with
        the checksum recorded. Non-admins never reach the read: the gate raises
        :class:`PermissionError`, mapped to a typed 403 by ``call``.
        """
        self._admin_gate(subject, request_id)
        bounded = max(1, min(limit, MAX_EXPORT_ROWS))
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT sequence, event_id, occurred_at, actor_kind, actor_user_id,
                  action, result, reason_code, request_id, session_fingerprint,
                  resource_id, resource_type, matched_policy_ids, details, event_hash
                FROM audit_events
                WHERE occurred_at >= :start AND occurred_at < :end
                ORDER BY sequence
                LIMIT :limit
            """), {
                "start": start,
                "end": end,
                # Fetch one extra to detect truncation without a second query.
                "limit": bounded + 1,
            })).mappings().all()
        truncated = len(rows) > bounded
        emitted = rows[:bounded]
        body = "".join(f"{_serialize_event(row)}\n" for row in emitted).encode("utf-8")
        checksum = hashlib.sha256(body).hexdigest()
        async with self.uow.transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action="admin.audit.export",
                result="success",
                reason_code="audit_export",
                request_id=request_id,
                resource_type="audit_export",
                details={
                    "from": start.astimezone(UTC).isoformat(),
                    "to": end.astimezone(UTC).isoformat(),
                    "count": len(emitted),
                    "truncated": truncated,
                    "checksum_sha256": checksum,
                },
            )
        return body, checksum, len(emitted), truncated


@router.get("/export", include_in_schema=True)
async def export_audit(
    request: Request,
    subject: Annotated[Subject | None, Depends(governance_subject)],
    start: Annotated[datetime, Query(description="Inclusive lower bound (ISO 8601).")],
    end: Annotated[datetime, Query(description="Exclusive upper bound (ISO 8601).")],
    limit: Annotated[int, Query(ge=1, le=MAX_EXPORT_ROWS)] = 10_000,
) -> Any:
    """Admin-gated checksummed JSONL export of audit events by time range."""
    if subject is None:
        return _error(request, 401, "authentication_required")
    if end <= start:
        return _error(request, 400, "invalid_time_range")
    result = await call(request, AuditExportService().export(
        subject,
        start=start,
        end=end,
        limit=limit,
        request_id=str(request.state.request_id),
    ))
    if isinstance(result, Response):  # a typed error envelope (401/403/…)
        return result
    body, checksum, count, truncated = result
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={
            "X-Request-ID": str(request.state.request_id),
            "X-Audit-Export-Checksum": f"sha256:{checksum}",
            "X-Audit-Export-Count": str(count),
            "X-Audit-Export-Truncated": "true" if truncated else "false",
            "Content-Disposition": 'attachment; filename="audit-export.jsonl"',
        },
    )
