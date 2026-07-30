import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

audit_logger = logging.getLogger("rtr_copilot.audit")


class AuditEvent(BaseModel):
    actor_id: str | None
    action: str
    result: str
    reason: str
    request_id: str
    timestamp: datetime
    policy_ids: list[str] = []


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...


class StructuredAuditSink:
    def emit(self, event: AuditEvent) -> None:
        audit_logger.info(json.dumps(event.model_dump(mode="json"), sort_keys=True))


def event(
    *,
    actor_id: str | None,
    action: str,
    result: str,
    reason: str,
    request_id: str,
    policy_ids: list[str] | None = None,
) -> AuditEvent:
    return AuditEvent(
        actor_id=actor_id,
        action=action,
        result=result,
        reason=reason,
        request_id=request_id,
        timestamp=datetime.now(UTC),
        policy_ids=policy_ids or [],
    )
