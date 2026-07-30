import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.auth.audit import AuditEvent, AuditSink, StructuredAuditSink
from rtr_copilot.db.uow import UnitOfWork

FORBIDDEN = {
    "token",
    "cookie",
    "authorization",
    "password",
    "secret",
    "code_verifier",
    "raw_oidc",
    "access_token",
    "id_token",
}
logger = logging.getLogger("rtr_copilot.audit.persistence")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): redact(item)
            for key, item in value.items()
            if not any(word in str(key).lower() for word in FORBIDDEN)
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str) and any(word in value.lower() for word in FORBIDDEN):
        return "[REDACTED]"
    return value


def policy_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"rtr-policy:{value}")


def canonical_payload(
    *,
    event_id: uuid.UUID,
    occurred_at: datetime,
    actor_kind: str,
    actor_user_id: uuid.UUID | None,
    action: str,
    result: str,
    reason_code: str,
    request_id: str,
    session_fingerprint: str | None,
    resource_id: uuid.UUID | None,
    resource_type: str | None,
    matched_policy_ids: list[uuid.UUID],
    details: dict[str, Any],
    previous_hash: str | None,
    serialization_version: int,
) -> str:
    payload = {
        "event_id": str(event_id),
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "actor_kind": actor_kind,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "action": action,
        "result": result,
        "reason_code": reason_code,
        "request_id": request_id,
        "session_fingerprint": session_fingerprint,
        "resource_id": str(resource_id) if resource_id else None,
        "resource_type": resource_type,
        "matched_policy_ids": [str(item) for item in matched_policy_ids],
        "details": redact(details),
        "previous_hash": previous_hash,
        "serialization_version": serialization_version,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AuditRepository:
    async def append(
        self,
        session: AsyncSession,
        *,
        actor_kind: str,
        actor_user_id: uuid.UUID | None,
        action: str,
        result: str,
        reason_code: str,
        request_id: str,
        resource_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        matched_policy_ids: list[str] | None = None,
        details: dict[str, Any] | None = None,
        session_fingerprint: str | None = None,
    ) -> uuid.UUID:
        await session.execute(text("SELECT pg_advisory_xact_lock(827004)"))
        previous_hash = await session.scalar(text(
            "SELECT head_hash FROM audit_chain_anchor WHERE singleton",
        ))
        event_id = uuid.uuid4()
        occurred_at = datetime.now(UTC)
        policy_ids = [policy_uuid(item) for item in matched_policy_ids or []]
        safe_details = redact(details or {})
        serialized = canonical_payload(
            event_id=event_id,
            occurred_at=occurred_at,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            action=action,
            result=result,
            reason_code=reason_code,
            request_id=request_id,
            session_fingerprint=session_fingerprint,
            resource_id=resource_id,
            resource_type=resource_type,
            matched_policy_ids=policy_ids,
            details=safe_details,
            previous_hash=previous_hash,
            serialization_version=1,
        )
        event_hash = hashlib.sha256(serialized.encode()).hexdigest()
        await session.execute(text("""
            SELECT append_audit_event(
              :event_id, :occurred_at, :actor_kind, :actor_user_id, :action,
              :result, :reason_code, :request_id, :session_fingerprint,
              :resource_id, :resource_type, :matched_policy_ids,
              CAST(:details AS jsonb), :previous_hash, :event_hash, 1
            )
        """), {
            "event_id": event_id,
            "occurred_at": occurred_at,
            "actor_kind": actor_kind,
            "actor_user_id": actor_user_id,
            "action": action,
            "result": result,
            "reason_code": reason_code,
            "request_id": request_id,
            "session_fingerprint": session_fingerprint,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "matched_policy_ids": policy_ids,
            "details": json.dumps(safe_details),
            "previous_hash": previous_hash,
            "event_hash": event_hash,
        })
        return event_id

    async def verify(self, session: AsyncSession) -> tuple[bool, int, str | None]:
        anchor = (await session.execute(text("""
            SELECT expected_count, head_sequence, head_hash
            FROM audit_chain_anchor WHERE singleton
        """))).mappings().one_or_none()
        if anchor is None:
            return False, 0, None
        rows = (await session.execute(text("""
            SELECT sequence, event_id, occurred_at, actor_kind, actor_user_id, action, result,
              reason_code, request_id, session_fingerprint, resource_id,
              resource_type, matched_policy_ids, details, previous_hash,
              event_hash, serialization_version
            FROM audit_events ORDER BY sequence
        """))).mappings()
        expected_previous: str | None = None
        count = 0
        last_sequence: int | None = None
        for row in rows:
            if row["previous_hash"] != expected_previous:
                return False, count, expected_previous
            serialized = canonical_payload(
                event_id=row["event_id"],
                occurred_at=row["occurred_at"],
                actor_kind=row["actor_kind"],
                actor_user_id=row["actor_user_id"],
                action=row["action"],
                result=row["result"],
                reason_code=row["reason_code"],
                request_id=row["request_id"],
                session_fingerprint=row["session_fingerprint"],
                resource_id=row["resource_id"],
                resource_type=row["resource_type"],
                matched_policy_ids=list(row["matched_policy_ids"]),
                details=dict(row["details"]),
                previous_hash=row["previous_hash"],
                serialization_version=row["serialization_version"],
            )
            candidate = hashlib.sha256(serialized.encode()).hexdigest()
            if candidate != row["event_hash"]:
                return False, count, expected_previous
            expected_previous = candidate
            last_sequence = int(row["sequence"])
            count += 1
        valid_anchor = (
            count == int(anchor["expected_count"])
            and last_sequence == anchor["head_sequence"]
            and expected_previous == anchor["head_hash"]
        )
        return valid_anchor, count, expected_previous


class DatabaseAuditSink(AuditSink):
    """TIP-003 synchronous sink bridged to durable append-only storage."""

    def __init__(self) -> None:
        self.log_sink = StructuredAuditSink()

    def emit(self, audit_event: AuditEvent) -> None:
        self.log_sink.emit(audit_event)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._persist(audit_event))

    async def _persist(self, audit_event: AuditEvent) -> None:
        try:
            async with UnitOfWork().transaction() as session:
                await AuditRepository().append(
                    session,
                    actor_kind="user" if audit_event.actor_id else "anonymous",
                    actor_user_id=(
                        uuid.UUID(audit_event.actor_id)
                        if audit_event.actor_id
                        else None
                    ),
                    action=audit_event.action,
                    result=audit_event.result,
                    reason_code=audit_event.reason,
                    request_id=audit_event.request_id,
                    matched_policy_ids=audit_event.policy_ids,
                )
        except Exception:
            logger.exception("audit_persistence_failed")
