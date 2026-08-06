import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import MaintenanceActive, UnitOfWork
from rtr_copilot.governance.models import (
    Gap,
    GapPriority,
    GapState,
    GapTransition,
    GovernanceSetting,
    QueueKind,
    ReviewTask,
    SettingValue,
    SettingValueType,
    StrictModel,
)
from rtr_copilot.governance.queues import (
    QueueConflictSide,
    QueueEntry,
    QueuePage,
    aggregate_entries,
    conflict_status,
    freshness_status,
    review_status,
)
from rtr_copilot.ingestion.api import _effective_principal_ids
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.governance import (
    GovernanceError,
    GovernanceRepository,
    encode_gap_cursor,
    validate_setting_value,
)
from rtr_copilot.repositories.resources import (
    CLASSIFICATION_TO_POLICY,
    ResourceRepository,
)

policy = PolicyEngine(StructuredAuditSink())

GapOperation = Literal["triage", "assign", "answer", "decline"]
GAP_OPERATION_TARGET: dict[GapOperation, GapState] = {
    "triage": "triaged",
    "assign": "assigned",
    "answer": "answered",
    "decline": "declined",
}
GAP_SCAN_LIMIT = 1000
GAP_BATCH_SIZE = 200
QUEUE_SCAN_LIMIT = 1000
PICKER_SCAN_LIMIT = 500
PICKER_QUERY_MAX_CHARS = 100
PICKER_LIMIT_MAX = 50


class SettingSpec(StrictModel):
    value_type: SettingValueType
    default: SettingValue
    minimum: float | None = None
    maximum: float | None = None
    description: str


SETTING_REGISTRY: dict[str, SettingSpec] = {
    "gap.sla.triage_hours": SettingSpec(
        value_type="duration_hours", default=24, minimum=1, maximum=2160,
        description="Hours from gap intake to expected triage",
    ),
    "gap.sla.assign_hours": SettingSpec(
        value_type="duration_hours", default=72, minimum=1, maximum=2160,
        description="Hours granted to an assigned owner before the gap is due",
    ),
    "queue.freshness.expiring_hours": SettingSpec(
        value_type="duration_hours", default=336, minimum=1, maximum=8760,
        description="Look-ahead window for facts approaching expiry",
    ),
    "queue.owner_review.upcoming_hours": SettingSpec(
        value_type="duration_hours", default=336, minimum=1, maximum=8760,
        description="Look-ahead window for scheduled owner reviews",
    ),
    # TIP-012/TIP-027.5 — two independent provider budgets. Calls stop runaway
    # retry/fallback loops; actual response token totals stop a few very large
    # prompts from hiding behind a small call count. Both are admin-editable,
    # versioned and audited via the existing settings surface.
    "limits.budget.subject_daily_units": SettingSpec(
        value_type="integer", default=500, minimum=1, maximum=100_000_000,
        description="Per-subject daily AI provider usage budget (calls)",
    ),
    "limits.budget.global_daily_units": SettingSpec(
        value_type="integer", default=20_000, minimum=1, maximum=1_000_000_000,
        description="Global daily AI provider usage budget (calls)",
    ),
    "limits.budget.subject_daily_tokens": SettingSpec(
        value_type="integer", default=2_000_000, minimum=1, maximum=1_000_000_000,
        description="Per-subject daily AI provider usage budget (actual tokens)",
    ),
    "limits.budget.global_daily_tokens": SettingSpec(
        value_type="integer", default=50_000_000, minimum=1, maximum=10_000_000_000,
        description="Global daily AI provider usage budget (actual tokens)",
    ),
    # TIP-012 Task 2 (AC-07) — job backpressure caps (outstanding, non-terminal
    # jobs per family). Enforced at the submission API layer.
    "limits.jobs.ingestion_max_inflight": SettingSpec(
        value_type="integer", default=100, minimum=1, maximum=1_000_000,
        description="Max outstanding ingestion jobs before new uploads are shed",
    ),
    "limits.jobs.render_max_inflight": SettingSpec(
        value_type="integer", default=50, minimum=1, maximum=1_000_000,
        description="Max outstanding render jobs before new renders are shed",
    ),
    "limits.jobs.index_max_backlog": SettingSpec(
        value_type="integer", default=200, minimum=1, maximum=1_000_000,
        description="Max pending SOT reindex backlog before publishes are shed",
    ),
}

QUEUE_HORIZON_SETTING: dict[QueueKind, str] = {
    "freshness": "queue.freshness.expiring_hours",
    "owner_review": "queue.owner_review.upcoming_hours",
}


def validate_setting_bounds(setting_key: str, value: SettingValue) -> SettingSpec:
    """Reject unknown keys, wrong types and out-of-bounds admin values."""
    spec = SETTING_REGISTRY.get(setting_key)
    if spec is None:
        raise GovernanceError("setting_unknown")
    validate_setting_value(spec.value_type, value)
    if not isinstance(value, bool) and isinstance(value, int | float):
        numeric = float(value)
        below = spec.minimum is not None and numeric < spec.minimum
        above = spec.maximum is not None and numeric > spec.maximum
        if below or above:
            raise GovernanceError("setting_out_of_bounds")
    return spec


class GapListPage(StrictModel):
    items: list[Gap]
    next_cursor: str | None = None


class GapDetail(StrictModel):
    gap: Gap
    transitions: list[GapTransition]


class GapTransitionInput(StrictModel):
    reason: str
    owner_subject_id: uuid.UUID | None = None
    resolving_version_id: uuid.UUID | None = None
    decline_reason: str | None = None


class SubjectPickerItem(StrictModel):
    """Directory row disclosed to authorized assigners (TIP-011 AC-06)."""

    subject_id: uuid.UUID
    display_name: str
    email: str | None = None


class SubjectPickerPage(StrictModel):
    items: list[SubjectPickerItem]
    next_cursor: str | None = None


class RecordPickerItem(StrictModel):
    """Active SOT record row for the gap-answer picker (TIP-011 AC-06)."""

    zone_label: Literal["sot"] = "sot"
    record_key: str
    record_version_id: uuid.UUID
    title: str | None = None
    classification: str


class RecordPickerPage(StrictModel):
    items: list[RecordPickerItem]
    next_cursor: str | None = None


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so picker queries stay literal."""
    return (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def validate_picker_query(query: str) -> str:
    stripped = query.strip()
    if not stripped or len(stripped) > PICKER_QUERY_MAX_CHARS:
        raise GovernanceError("picker_query_invalid")
    return stripped


def _signature(payload: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode(), payload, hashlib.sha256).digest()


def encode_signed_cursor(
    kind: str,
    sort_at: datetime,
    item_id: uuid.UUID,
    secret: str,
) -> str:
    payload = json.dumps(
        {"k": kind, "at": sort_at.isoformat(), "id": str(item_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(
        payload + _signature(payload, secret),
    ).decode().rstrip("=")


def decode_signed_cursor(
    kind: str,
    cursor: str,
    secret: str,
) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
        canonical = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        if not hmac.compare_digest(canonical, cursor):
            raise ValueError("cursor_noncanonical_encoding")
        payload, signature = raw[:-32], raw[-32:]
        if not hmac.compare_digest(signature, _signature(payload, secret)):
            raise ValueError("cursor_signature_mismatch")
        value = json.loads(payload)
        if value["k"] != kind:
            raise ValueError("cursor_kind_mismatch")
        return datetime.fromisoformat(str(value["at"])), uuid.UUID(str(value["id"]))
    except (ValueError, KeyError, TypeError, binascii.Error) as error:
        raise GovernanceError("invalid_cursor") from error


FRESHNESS_MEMBERSHIP_SQL = """
    SELECT r.record_id, r.record_key, r.owner_subject_id,
      r.current_version_id AS version_id, rv.classification,
      rv.effective_from, rv.effective_to, rv.freshness_due_at, rv.created_at
    FROM records r JOIN record_versions rv ON rv.version_id = r.current_version_id
    WHERE r.lifecycle = 'active' AND rv.lifecycle = 'active'
      AND rv.effective_to IS NOT NULL AND rv.effective_to <= :horizon
    ORDER BY rv.effective_to, rv.version_id
    LIMIT :scan_limit
"""
OWNER_REVIEW_MEMBERSHIP_SQL = """
    SELECT r.record_id, r.record_key, r.owner_subject_id,
      r.current_version_id AS version_id, rv.classification,
      rv.effective_from, rv.effective_to, rv.freshness_due_at, rv.created_at
    FROM records r JOIN record_versions rv ON rv.version_id = r.current_version_id
    WHERE r.lifecycle = 'active' AND rv.lifecycle = 'active'
      AND rv.freshness_due_at IS NOT NULL AND rv.freshness_due_at <= :horizon
    ORDER BY rv.freshness_due_at, rv.version_id
    LIMIT :scan_limit
"""
CONFLICT_MEMBERSHIP_SQL = """
    WITH active_counts AS (
      SELECT record_id, count(*) AS active_count
      FROM record_versions WHERE lifecycle = 'active' GROUP BY record_id
    ), external_supersede AS (
      SELECT DISTINCT mine.record_id
      FROM record_versions mine
      JOIN record_versions other ON other.supersedes_version_id = mine.version_id
      WHERE mine.lifecycle = 'active' AND other.lifecycle = 'active'
        AND other.record_id <> mine.record_id
    )
    SELECT r.record_id, r.record_key, r.owner_subject_id,
      r.current_version_id AS version_id, rv.classification, rv.created_at,
      ac.active_count, (es.record_id IS NOT NULL) AS superseded_by_other
    FROM records r
    JOIN record_versions rv ON rv.version_id = r.current_version_id
    JOIN active_counts ac ON ac.record_id = r.record_id
    LEFT JOIN external_supersede es ON es.record_id = r.record_id
    WHERE r.lifecycle = 'active' AND rv.lifecycle = 'active'
      AND (ac.active_count > 1 OR es.record_id IS NOT NULL)
    ORDER BY rv.created_at, rv.version_id
    LIMIT :scan_limit
"""
SUBJECT_PICKER_SQL = """
    SELECT user_id, display_name, email, created_at
    FROM subjects
    WHERE status = 'active'
      AND (display_name ILIKE :prefix OR email ILIKE :prefix)
    ORDER BY created_at, user_id
    LIMIT :scan_limit
"""
RECORD_PICKER_SQL = """
    SELECT r.record_id, r.record_key, r.owner_subject_id,
      r.current_version_id AS version_id, rv.classification, rv.created_at,
      rv.value_payload->>'title' AS title
    FROM records r JOIN record_versions rv ON rv.version_id = r.current_version_id
    WHERE r.lifecycle = 'active' AND rv.lifecycle = 'active'
      AND (r.record_key ILIKE :pattern
           OR rv.value_payload->>'title' ILIKE :pattern)
    ORDER BY rv.created_at, rv.version_id
    LIMIT :scan_limit
"""
CONFLICT_SIDES_SQL = """
    SELECT rv.record_id AS conflict_record_id, rv.version_id,
      rv.record_id, rv.package_revision, rv.provenance_level,
      rv.verification_state, rv.content_sha256, rv.evidence_refs,
      rv.effective_from, false AS external
    FROM record_versions rv
    WHERE rv.lifecycle = 'active' AND rv.record_id = ANY(:record_ids)
    UNION ALL
    SELECT mine.record_id AS conflict_record_id, other.version_id,
      other.record_id, other.package_revision, other.provenance_level,
      other.verification_state, other.content_sha256, other.evidence_refs,
      other.effective_from, true AS external
    FROM record_versions mine
    JOIN record_versions other ON other.supersedes_version_id = mine.version_id
    WHERE mine.lifecycle = 'active' AND other.lifecycle = 'active'
      AND mine.record_id = ANY(:record_ids)
      AND other.record_id <> mine.record_id
    ORDER BY package_revision, version_id
"""


class GovernanceService:
    """Gap lifecycle, live governance queues and typed governance settings."""

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()
        self.settings = get_settings()
        self.repository = GovernanceRepository()

    def _secret(self) -> str:
        return self.settings.sot_signing_secret.get_secret_value()

    def _gap_attributes(self, gap: Gap) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=str(gap.gap_id),
            owner_id=str(gap.owner_subject_id or gap.requester_id),
            classification=CLASSIFICATION_TO_POLICY[gap.classification],
            source_zone="sot",
            lifecycle_state="active",
        )

    def gap_visible(self, subject: Subject, gap: Gap, request_id: str) -> bool:
        """Requester and assigned owner see their gap; others need curator scope.

        The classification clearance check applies to everyone, so restricted
        question content never reaches a caller without clearance.
        """
        attributes = self._gap_attributes(gap)
        context = PolicyContext(request_id=request_id)
        if not policy.decide(subject, "view", attributes, context).allow:
            return False
        caller = uuid.UUID(subject.user_id)
        if caller in {gap.requester_id, gap.owner_subject_id}:
            return True
        return policy.decide(subject, "curate", attributes, context).allow

    def gap_mutation_allowed(
        self,
        subject: Subject,
        gap: Gap,
        request_id: str,
    ) -> bool:
        attributes = self._gap_attributes(gap)
        context = PolicyContext(request_id=request_id)
        return (
            policy.decide(subject, "curate", attributes, context).allow
            or policy.decide(subject, "manage_policies", attributes, context).allow
        )

    async def list_gaps(
        self,
        subject: Subject,
        *,
        request_id: str,
        state: str | None = None,
        owner_subject_id: uuid.UUID | None = None,
        priority: GapPriority | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> GapListPage:
        limit = max(1, min(limit, 100))
        boundary = (
            decode_signed_cursor("gaps", cursor, self._secret()) if cursor else None
        )
        repository_cursor = encode_gap_cursor(*boundary) if boundary else None
        visible: list[Gap] = []
        scanned = 0
        exhausted = False
        last_scanned: tuple[datetime, uuid.UUID] | None = None
        async with self.uow.factory() as session:
            while scanned < GAP_SCAN_LIMIT and len(visible) <= limit:
                page = await self.repository.list_gaps(
                    session,
                    state=state,
                    owner_subject_id=owner_subject_id,
                    priority=priority,
                    cursor=repository_cursor,
                    limit=GAP_BATCH_SIZE,
                )
                if not page.items:
                    exhausted = True
                    break
                for gap in page.items:
                    scanned += 1
                    last_scanned = (gap.first_seen_at, gap.gap_id)
                    if self.gap_visible(subject, gap, request_id):
                        visible.append(gap)
                        if len(visible) > limit:
                            break
                if len(visible) > limit:
                    break
                if page.next_cursor is None:
                    exhausted = True
                    break
                repository_cursor = page.next_cursor
        items = visible[:limit]
        if len(visible) > limit:
            resume: tuple[datetime, uuid.UUID] | None = (
                items[-1].first_seen_at,
                items[-1].gap_id,
            )
        elif not exhausted and last_scanned is not None:
            resume = last_scanned
        else:
            resume = None
        next_cursor = (
            encode_signed_cursor("gaps", resume[0], resume[1], self._secret())
            if resume
            else None
        )
        return GapListPage(items=items, next_cursor=next_cursor)

    async def gap_detail(
        self,
        subject: Subject,
        gap_id: uuid.UUID,
        *,
        request_id: str,
    ) -> GapDetail:
        async with self.uow.factory() as session:
            gap = await self.repository.get_gap(session, gap_id)
            if gap is None or not self.gap_visible(subject, gap, request_id):
                raise GovernanceError("gap_not_found")
            transitions = await self.repository.list_gap_transitions(session, gap_id)
        return GapDetail(gap=gap, transitions=transitions)

    async def _setting_hours(self, session: AsyncSession, setting_key: str) -> int:
        spec = SETTING_REGISTRY[setting_key]
        stored = await self.repository.get_setting(session, setting_key)
        value = stored.value if stored is not None else spec.default
        if isinstance(value, bool) or not isinstance(value, int | float):
            value = spec.default
        return int(value)

    async def _viewable_record_version(
        self,
        session: AsyncSession,
        subject: Subject,
        version_id: uuid.UUID,
        request_id: str,
    ) -> None:
        """Answering may only reference record versions inside caller scope.

        A version that does not exist and a version the caller must not know
        about produce the same typed failure, so probing leaks nothing.
        """
        record_id = await session.scalar(text("""
            SELECT record_id FROM record_versions WHERE version_id = :version_id
        """), {"version_id": version_id})
        if record_id is None:
            raise GovernanceError("record_version_not_found")
        principals = await _effective_principal_ids(session, subject)
        attributes = await ResourceRepository().policy_attributes(
            session,
            record_id,
            action="view",
            principal_ids=principals,
        )
        if attributes is None or not policy.decide(
            subject,
            "view",
            attributes,
            PolicyContext(request_id=request_id),
        ).allow:
            raise GovernanceError("record_version_not_found")

    async def transition_gap(
        self,
        subject: Subject,
        gap_id: uuid.UUID,
        operation: GapOperation,
        payload: GapTransitionInput,
        *,
        request_id: str,
    ) -> Gap:
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            gap = await self.repository.get_gap(session, gap_id)
            if gap is None or not self.gap_visible(subject, gap, request_id):
                raise GovernanceError("gap_not_found")
            if not self.gap_mutation_allowed(subject, gap, request_id):
                raise PermissionError("curator_required")
            due_at: datetime | None = None
            if operation == "assign":
                if payload.owner_subject_id is None:
                    raise GovernanceError("gap_owner_required")
                hours = await self._setting_hours(session, "gap.sla.assign_hours")
                due_at = datetime.now(UTC) + timedelta(hours=hours)
            if operation == "answer":
                if payload.resolving_version_id is None:
                    raise GovernanceError("gap_resolution_record_required")
                await self._viewable_record_version(
                    session,
                    subject,
                    payload.resolving_version_id,
                    request_id,
                )
            updated = await self.repository.transition_gap(
                session,
                gap_id,
                to_state=GAP_OPERATION_TARGET[operation],
                actor_subject_id=actor,
                reason=payload.reason,
                owner_subject_id=payload.owner_subject_id,
                due_at=due_at,
                resolving_version_id=payload.resolving_version_id,
                decline_reason=payload.decline_reason,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action=f"governance.gap.{operation}",
                result="success",
                reason_code=f"gap_{updated.lifecycle}",
                request_id=request_id,
                resource_type="gap",
                details={
                    "gap_id": str(gap_id),
                    "from_state": gap.lifecycle,
                    "to_state": updated.lifecycle,
                    "owner_subject_id": (
                        str(updated.owner_subject_id)
                        if updated.owner_subject_id
                        else None
                    ),
                    "due_at": due_at.isoformat() if due_at else None,
                    "resolving_version_id": (
                        str(payload.resolving_version_id)
                        if payload.resolving_version_id
                        else None
                    ),
                },
            )
        return updated

    async def _queue_rows(
        self,
        session: AsyncSession,
        queue_kind: QueueKind,
        *,
        horizon: datetime,
        now: datetime,
    ) -> list[QueueEntry]:
        if queue_kind == "freshness":
            rows = (await session.execute(
                text(FRESHNESS_MEMBERSHIP_SQL),
                {"horizon": horizon, "scan_limit": QUEUE_SCAN_LIMIT},
            )).mappings().all()
            return [
                QueueEntry(
                    queue_kind="freshness",
                    record_id=row["record_id"],
                    record_key=row["record_key"],
                    record_version_id=row["version_id"],
                    owner_subject_id=row["owner_subject_id"],
                    classification=row["classification"],
                    status=freshness_status(row["effective_to"], now=now),
                    sort_at=row["effective_to"],
                    effective_to=row["effective_to"],
                    review_due_at=row["freshness_due_at"],
                )
                for row in rows
            ]
        if queue_kind == "owner_review":
            rows = (await session.execute(
                text(OWNER_REVIEW_MEMBERSHIP_SQL),
                {"horizon": horizon, "scan_limit": QUEUE_SCAN_LIMIT},
            )).mappings().all()
            return [
                QueueEntry(
                    queue_kind="owner_review",
                    record_id=row["record_id"],
                    record_key=row["record_key"],
                    record_version_id=row["version_id"],
                    owner_subject_id=row["owner_subject_id"],
                    classification=row["classification"],
                    status=review_status(row["freshness_due_at"], now=now),
                    sort_at=row["freshness_due_at"],
                    effective_to=row["effective_to"],
                    review_due_at=row["freshness_due_at"],
                )
                for row in rows
            ]
        rows = (await session.execute(
            text(CONFLICT_MEMBERSHIP_SQL),
            {"scan_limit": QUEUE_SCAN_LIMIT},
        )).mappings().all()
        sides_by_record: dict[uuid.UUID, list[QueueConflictSide]] = {}
        if rows:
            side_rows = (await session.execute(
                text(CONFLICT_SIDES_SQL),
                {"record_ids": [row["record_id"] for row in rows]},
            )).mappings().all()
            for side in side_rows:
                sides_by_record.setdefault(side["conflict_record_id"], []).append(
                    QueueConflictSide(
                        version_id=side["version_id"],
                        record_id=side["record_id"],
                        package_revision=side["package_revision"],
                        provenance_level=side["provenance_level"],
                        verification_state=side["verification_state"],
                        content_sha256=str(side["content_sha256"]),
                        evidence_refs=list(side["evidence_refs"]),
                        effective_from=side["effective_from"],
                        external=side["external"],
                    ),
                )
        return [
            QueueEntry(
                queue_kind="conflict",
                record_id=row["record_id"],
                record_key=row["record_key"],
                record_version_id=row["version_id"],
                owner_subject_id=row["owner_subject_id"],
                classification=row["classification"],
                status=conflict_status(
                    int(row["active_count"]),
                    bool(row["superseded_by_other"]),
                ),
                sort_at=row["created_at"],
                sides=sides_by_record.get(row["record_id"], []),
            )
            for row in rows
        ]

    async def _reopen_stale_completions(
        self,
        queue_kind: QueueKind,
        tasks: dict[uuid.UUID, ReviewTask],
        member_version_ids: list[uuid.UUID],
        request_id: str,
    ) -> None:
        """A completed task whose record is still live queue membership reopens.

        The materialized row can therefore never mask a live expiry, conflict
        or review obligation.
        """
        stale = [
            version_id
            for version_id in member_version_ids
            if version_id in tasks and tasks[version_id].state == "completed"
        ]
        if not stale:
            return
        with contextlib.suppress(MaintenanceActive):
            async with self.uow.transaction() as session:
                reopened = await self.repository.reopen_completed_tasks(
                    session,
                    queue_kind=queue_kind,
                    record_version_ids=stale,
                )
                record_rows = (await session.execute(text("""
                    SELECT version_id, record_id FROM record_versions
                    WHERE version_id = ANY(:version_ids)
                """), {
                    "version_ids": [task.record_version_id for task in reopened],
                })).mappings().all()
                record_by_version = {
                    row["version_id"]: row["record_id"] for row in record_rows
                }
                for task in reopened:
                    await AuditRepository().append(
                        session,
                        actor_kind="service",
                        actor_user_id=None,
                        action="governance.queue.reopen",
                        result="success",
                        reason_code="live_membership_persists",
                        request_id=request_id,
                        resource_id=record_by_version.get(task.record_version_id),
                        resource_type="record",
                        details={
                            "task_id": str(task.task_id),
                            "record_version_id": str(task.record_version_id),
                            "queue_kind": queue_kind,
                        },
                    )
                for task in reopened:
                    tasks[task.record_version_id] = task

    async def _visible_queue_entries(
        self,
        session: AsyncSession,
        subject: Subject,
        entries: list[QueueEntry],
        request_id: str,
    ) -> list[QueueEntry]:
        principals = await _effective_principal_ids(session, subject)
        context = PolicyContext(request_id=request_id)
        caller = uuid.UUID(subject.user_id)
        visible: list[QueueEntry] = []
        for entry in entries:
            attributes = await ResourceRepository().policy_attributes(
                session,
                entry.record_id,
                action="view",
                principal_ids=principals,
            )
            if attributes is None:
                continue
            if not policy.decide(subject, "view", attributes, context).allow:
                continue
            if entry.owner_subject_id != caller and not policy.decide(
                subject,
                "curate",
                attributes,
                context,
            ).allow:
                continue
            visible.append(entry)
        return visible

    async def queue_page(
        self,
        subject: Subject,
        queue_kind: QueueKind,
        *,
        request_id: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> QueuePage:
        limit = max(1, min(limit, 100))
        boundary = (
            decode_signed_cursor(f"queue:{queue_kind}", cursor, self._secret())
            if cursor
            else None
        )
        now = datetime.now(UTC)
        async with self.uow.factory() as session:
            horizon = now
            setting_key = QUEUE_HORIZON_SETTING.get(queue_kind)
            if setting_key is not None:
                hours = await self._setting_hours(session, setting_key)
                horizon = now + timedelta(hours=hours)
            entries = await self._queue_rows(
                session,
                queue_kind,
                horizon=horizon,
                now=now,
            )
            member_version_ids = [entry.record_version_id for entry in entries]
            tasks = {
                task.record_version_id: task
                for task in await self.repository.list_review_tasks_for_versions(
                    session,
                    queue_kind=queue_kind,
                    record_version_ids=member_version_ids,
                )
            }
        await self._reopen_stale_completions(
            queue_kind,
            tasks,
            member_version_ids,
            request_id,
        )
        async with self.uow.factory() as session:
            visible = await self._visible_queue_entries(
                session,
                subject,
                entries,
                request_id,
            )
        visible = [
            entry.model_copy(update={"task": tasks.get(entry.record_version_id)})
            for entry in visible
        ]
        aggregates = aggregate_entries(visible)
        if boundary is not None:
            visible = [
                entry
                for entry in visible
                if (entry.sort_at, entry.record_version_id) > boundary
            ]
        page = visible[:limit]
        next_cursor = (
            encode_signed_cursor(
                f"queue:{queue_kind}",
                page[-1].sort_at,
                page[-1].record_version_id,
                self._secret(),
            )
            if len(visible) > limit
            else None
        )
        return QueuePage(
            queue_kind=queue_kind,
            computed_at=now,
            entries=page,
            aggregates=aggregates,
            next_cursor=next_cursor,
        )

    async def _version_in_live_queue(
        self,
        session: AsyncSession,
        queue_kind: QueueKind,
        version_id: uuid.UUID,
        *,
        now: datetime,
    ) -> bool:
        setting_key = QUEUE_HORIZON_SETTING.get(queue_kind)
        horizon = now
        if setting_key is not None:
            hours = await self._setting_hours(session, setting_key)
            horizon = now + timedelta(hours=hours)
        entries = await self._queue_rows(
            session,
            queue_kind,
            horizon=horizon,
            now=now,
        )
        return any(entry.record_version_id == version_id for entry in entries)

    async def _queue_record_attributes(
        self,
        session: AsyncSession,
        subject: Subject,
        version_id: uuid.UUID,
    ) -> tuple[ResourceAttributes, uuid.UUID] | None:
        row = (await session.execute(text("""
            SELECT rv.record_id, r.owner_subject_id
            FROM record_versions rv JOIN records r ON r.record_id = rv.record_id
            WHERE rv.version_id = :version_id
        """), {"version_id": version_id})).mappings().one_or_none()
        if row is None:
            return None
        principals = await _effective_principal_ids(session, subject)
        attributes = await ResourceRepository().policy_attributes(
            session,
            row["record_id"],
            action="view",
            principal_ids=principals,
        )
        if attributes is None:
            return None
        return attributes, row["record_id"]

    async def assign_queue_task(
        self,
        subject: Subject,
        queue_kind: QueueKind,
        *,
        record_version_id: uuid.UUID,
        assignee_subject_id: uuid.UUID,
        due_at: datetime | None = None,
        note: str = "",
        request_id: str,
    ) -> ReviewTask:
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            located = await self._queue_record_attributes(
                session,
                subject,
                record_version_id,
            )
            context = PolicyContext(request_id=request_id)
            curate_allowed = located is not None and policy.decide(
                subject,
                "curate",
                located[0],
                context,
            ).allow
            entry_visible = (
                located is not None
                and policy.decide(subject, "view", located[0], context).allow
                and (located[0].owner_id == subject.user_id or curate_allowed)
            )
            if located is None or not entry_visible:
                raise GovernanceError("queue_entry_not_found")
            if not curate_allowed:
                raise PermissionError("curator_required")
            if not await self._version_in_live_queue(
                session,
                queue_kind,
                record_version_id,
                now=datetime.now(UTC),
            ):
                raise GovernanceError("queue_membership_stale")
            task = await self.repository.upsert_review_task(
                session,
                queue_kind=queue_kind,
                record_version_id=record_version_id,
                assignee_subject_id=assignee_subject_id,
                assigned_by=actor,
                due_at=due_at,
                note=note,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.queue.assign",
                result="success",
                reason_code="review_task_assigned",
                request_id=request_id,
                resource_id=located[1],
                resource_type="record",
                details={
                    "task_id": str(task.task_id),
                    "record_version_id": str(record_version_id),
                    "queue_kind": queue_kind,
                    "assignee_subject_id": str(assignee_subject_id),
                    "state": task.state,
                },
            )
        return task

    async def complete_queue_task(
        self,
        subject: Subject,
        task_id: uuid.UUID,
        *,
        request_id: str,
    ) -> ReviewTask:
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            task = await self.repository.get_review_task(session, task_id)
            if task is None:
                raise GovernanceError("review_task_not_found")
            context = PolicyContext(request_id=request_id)
            if task.assignee_subject_id != actor:
                located = await self._queue_record_attributes(
                    session,
                    subject,
                    task.record_version_id,
                )
                curate_allowed = located is not None and policy.decide(
                    subject,
                    "curate",
                    located[0],
                    context,
                ).allow
                entry_visible = (
                    located is not None
                    and policy.decide(subject, "view", located[0], context).allow
                    and (located[0].owner_id == subject.user_id or curate_allowed)
                )
                if not entry_visible:
                    raise GovernanceError("review_task_not_found")
                if not curate_allowed:
                    raise PermissionError("curator_required")
            completed = await self.repository.complete_review_task(session, task_id)
            record_id = await session.scalar(text("""
                SELECT record_id FROM record_versions WHERE version_id = :version_id
            """), {"version_id": completed.record_version_id})
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.queue.complete",
                result="success",
                reason_code="review_task_completed",
                request_id=request_id,
                resource_id=record_id,
                resource_type="record",
                details={
                    "task_id": str(task_id),
                    "record_version_id": str(completed.record_version_id),
                    "queue_kind": completed.queue_kind,
                },
            )
        return completed

    async def search_subjects(
        self,
        subject: Subject,
        query: str,
        *,
        request_id: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> SubjectPickerPage:
        """Policy-gated subject picker for queue/gap assignment (AC-06).

        The subject directory is only visible to callers who can assign work
        (curators) or manage users (admins); everyone else receives the same
        typed 403 regardless of what exists, so probing discloses nothing.
        """
        limit = max(1, min(limit, PICKER_LIMIT_MAX))
        normalized = validate_picker_query(query)
        boundary = (
            decode_signed_cursor("picker:subjects", cursor, self._secret())
            if cursor
            else None
        )
        attributes = ResourceAttributes(classification="internal", source_zone="sot")
        context = PolicyContext(request_id=request_id)
        allowed = (
            policy.decide(subject, "curate", attributes, context).allow
            or policy.decide(subject, "manage_users", attributes, context).allow
        )
        if not allowed:
            raise PermissionError("curator_required")
        async with self.uow.factory() as session:
            rows = (await session.execute(text(SUBJECT_PICKER_SQL), {
                "prefix": f"{escape_like(normalized)}%",
                "scan_limit": PICKER_SCAN_LIMIT,
            })).mappings().all()
        matches = [
            row for row in rows
            if boundary is None or (row["created_at"], row["user_id"]) > boundary
        ]
        page = matches[:limit]
        next_cursor = (
            encode_signed_cursor(
                "picker:subjects",
                page[-1]["created_at"],
                page[-1]["user_id"],
                self._secret(),
            )
            if len(matches) > limit
            else None
        )
        await self._audit_picker(
            subject,
            action="governance.picker.subjects",
            request_id=request_id,
            resource_type="subject_directory",
            returned_count=len(page),
            normalized_query=normalized,
        )
        return SubjectPickerPage(
            items=[
                SubjectPickerItem(
                    subject_id=row["user_id"],
                    display_name=str(row["display_name"]),
                    email=str(row["email"]) if row["email"] is not None else None,
                )
                for row in page
            ],
            next_cursor=next_cursor,
        )

    async def search_records(
        self,
        subject: Subject,
        query: str,
        *,
        request_id: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> RecordPickerPage:
        """Policy-filtered active-record picker for gap answering (AC-06).

        Only records the caller can view — and owns or curates, mirroring the
        queue visibility rule — ever appear; denied existence is invisible
        through results, counts and cursors alike.
        """
        limit = max(1, min(limit, PICKER_LIMIT_MAX))
        normalized = validate_picker_query(query)
        boundary = (
            decode_signed_cursor("picker:records", cursor, self._secret())
            if cursor
            else None
        )
        context = PolicyContext(request_id=request_id)
        caller = uuid.UUID(subject.user_id)
        visible: list[dict[str, Any]] = []
        async with self.uow.factory() as session:
            rows = (await session.execute(text(RECORD_PICKER_SQL), {
                "pattern": f"%{escape_like(normalized)}%",
                "scan_limit": PICKER_SCAN_LIMIT,
            })).mappings().all()
            principals = await _effective_principal_ids(session, subject)
            for row in rows:
                attributes = await ResourceRepository().policy_attributes(
                    session,
                    row["record_id"],
                    action="view",
                    principal_ids=principals,
                )
                if attributes is None:
                    continue
                if not policy.decide(subject, "view", attributes, context).allow:
                    continue
                if row["owner_subject_id"] != caller and not policy.decide(
                    subject,
                    "curate",
                    attributes,
                    context,
                ).allow:
                    continue
                visible.append(dict(row))
        matches = [
            row for row in visible
            if boundary is None or (row["created_at"], row["version_id"]) > boundary
        ]
        page = matches[:limit]
        next_cursor = (
            encode_signed_cursor(
                "picker:records",
                page[-1]["created_at"],
                page[-1]["version_id"],
                self._secret(),
            )
            if len(matches) > limit
            else None
        )
        await self._audit_picker(
            subject,
            action="governance.picker.records",
            request_id=request_id,
            resource_type="record_picker",
            returned_count=len(page),
            normalized_query=normalized,
        )
        return RecordPickerPage(
            items=[
                RecordPickerItem(
                    record_key=str(row["record_key"]),
                    record_version_id=row["version_id"],
                    title=str(row["title"]) if row["title"] is not None else None,
                    classification=str(row["classification"]),
                )
                for row in page
            ],
            next_cursor=next_cursor,
        )

    async def _audit_picker(
        self,
        subject: Subject,
        *,
        action: str,
        request_id: str,
        resource_type: str,
        returned_count: int,
        normalized_query: str,
    ) -> None:
        """Audited disclosure per house rule: counts + query digest only."""
        async with self.uow.transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action=action,
                result="success",
                reason_code="picker_results_disclosed",
                request_id=request_id,
                resource_type=resource_type,
                details={
                    "returned_count": returned_count,
                    "query_fingerprint": hashlib.sha256(
                        normalized_query.casefold().encode(),
                    ).hexdigest(),
                },
            )

    async def setting_value(self, setting_key: str) -> SettingValue:
        """Effective typed value for one registered governance setting."""
        spec = SETTING_REGISTRY.get(setting_key)
        if spec is None:
            raise GovernanceError("setting_unknown")
        async with self.uow.factory() as session:
            stored = await self.repository.get_setting(session, setting_key)
        return stored.value if stored is not None else spec.default

    async def update_setting(
        self,
        subject: Subject,
        *,
        setting_key: str,
        value: SettingValue,
        reason: str,
        request_id: str,
    ) -> GovernanceSetting:
        spec = validate_setting_bounds(setting_key, value)
        attributes = ResourceAttributes(classification="internal", source_zone="sot")
        if not policy.decide(
            subject,
            "manage_policies",
            attributes,
            PolicyContext(request_id=request_id),
        ).allow:
            raise PermissionError("admin_required")
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            setting = await self.repository.set_setting(
                session,
                setting_key=setting_key,
                value_type=spec.value_type,
                value=value,
                updated_by=actor,
                reason=reason,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.setting.update",
                result="success",
                reason_code="setting_version_appended",
                request_id=request_id,
                resource_type="governance_setting",
                details={
                    "setting_id": str(setting.setting_id),
                    "setting_key": setting_key,
                    "version": setting.version,
                    "value": value,
                },
            )
        return setting
