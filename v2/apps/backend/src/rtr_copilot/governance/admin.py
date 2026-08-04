"""Admin governance surfaces for TIP-010 Task 6 (REQ-032, D-010-07).

Admins operate the system, never the truth: this module manages research
sources, governance settings, gap queue priority, identity bindings inside the
TIP-003 model and read-only job health. No code path here mutates SOT record
content, research record content, audit events or issued documents; the admin
API additionally refuses those families with typed, audited errors (AC-11).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.auth.storage import SessionStore
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.models import (
    Classification,
    Gap,
    GapPriority,
    GovernanceSetting,
    ResearchOrigin,
    ResearchSource,
    ResearchSourceLifecycle,
    SettingValue,
    SettingValueType,
    StrictModel,
)
from rtr_copilot.governance.service import (
    SETTING_REGISTRY,
    GovernanceService,
    policy,
)
from rtr_copilot.pilot.questions import load_pilot_questions
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository

logger = logging.getLogger("rtr_copilot.governance.admin")

BindingKind = Literal["role", "group"]
BindingOperation = Literal["assign", "unassign"]
JobFamily = Literal["ingestion", "render", "reindex"]
PilotGateState = Literal["met", "partial", "blocked"]

SUBJECT_LIST_LIMIT = 200
RECENT_FAILURE_LIMIT = 10

SUBJECT_VIEW_SQL = """
    SELECT s.user_id, s.issuer, s.email, s.display_name, s.status,
      s.security_version, s.last_seen_at,
      (SELECT COALESCE(array_agg(DISTINCT ro.key), CAST('{}' AS text[]))
         FROM subject_roles sr JOIN roles ro ON ro.role_id = sr.role_id
        WHERE sr.subject_id = s.user_id AND sr.valid_from <= now()
          AND (sr.expires_at IS NULL OR sr.expires_at > now())) AS roles,
      (SELECT COALESCE(array_agg(DISTINCT g.provider_group_key),
                       CAST('{}' AS text[]))
         FROM subject_groups sg JOIN groups g ON g.group_id = sg.group_id
        WHERE sg.subject_id = s.user_id AND sg.valid_from <= now()
          AND (sg.expires_at IS NULL OR sg.expires_at > now())) AS groups
    FROM subjects s
"""


class SettingView(StrictModel):
    """Registry-typed effective view of one governance setting."""

    setting_key: str
    value_type: SettingValueType
    description: str
    minimum: float | None = None
    maximum: float | None = None
    default: SettingValue
    value: SettingValue
    version: int
    updated_at: datetime | None = None


class SubjectAccountView(StrictModel):
    user_id: uuid.UUID
    issuer: str
    email: str | None = None
    display_name: str
    status: str
    security_version: int
    roles: list[str]
    groups: list[str]
    last_seen_at: datetime


class JobFailureView(StrictModel):
    """One recent job failure; state and code only, never payload content."""

    job_id: uuid.UUID
    kind: str
    status: str
    error_code: str | None = None
    attempt: int | None = None
    occurred_at: datetime


class JobFamilyHealth(StrictModel):
    family: JobFamily
    job_counts: dict[str, int]
    outbox_counts: dict[str, int]
    recent_failures: list[JobFailureView]


class JobHealthReport(StrictModel):
    computed_at: datetime
    families: list[JobFamilyHealth]


class PilotSotSummary(StrictModel):
    active_records: int
    strict_records: int
    caveated_records: int
    current_records: int
    stale_records: int
    named_owner_records: int
    placeholder_owner_records: int
    caveated_named_owner_records: int
    caveated_placeholder_owner_records: int
    high_risk_records: int
    high_risk_caveated_records: int
    zone_masquerade_findings: int


class PilotFileSummary(StrictModel):
    documents: int
    versions: int
    representative_versions: int
    ready_versions: int
    indexed_versions: int
    viewer_families: dict[str, int]
    original_checksum_mismatches: int
    rendition_lineage_mismatches: int


class PilotTemplateSummary(StrictModel):
    templates: int
    approved_templates: int
    locked_bindings: int
    official_or_legal_approved: int


class PilotResearchSummary(StrictModel):
    active_sources: int
    imported_packages: int
    records: int
    tiers: dict[str, int]
    corroboration: dict[str, int]


class PilotGate(StrictModel):
    gate_key: str
    target: int
    actual: int
    state: PilotGateState
    detail: str


class PilotReadinessReport(StrictModel):
    computed_at: datetime
    sot: PilotSotSummary
    files: PilotFileSummary
    templates: PilotTemplateSummary
    research: PilotResearchSummary
    question_count: int
    gates: list[PilotGate]
    production_boundary: str = "local_dev_only"


class AdminGovernanceService:
    """Governed admin mutations plus read-only operational inspection."""

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()
        self.settings = get_settings()
        self.repository = GovernanceRepository()
        self.governance = GovernanceService(uow=self.uow)

    def _admin_gate(self, subject: Subject, request_id: str, action: str) -> None:
        allowed = policy.decide(
            subject,
            action,
            ResourceAttributes(classification="internal"),
            PolicyContext(request_id=request_id),
        ).allow
        if not allowed:
            raise PermissionError("admin_required")

    async def _subject_exists(
        self,
        session: AsyncSession,
        subject_id: uuid.UUID,
    ) -> bool:
        found = await session.scalar(text(
            "SELECT 1 FROM subjects WHERE user_id = :subject_id",
        ), {"subject_id": subject_id})
        return found is not None

    async def create_source(
        self,
        subject: Subject,
        *,
        stable_key: str,
        display_name: str,
        description: str,
        origin: ResearchOrigin,
        owner_subject_id: uuid.UUID,
        classification: Classification,
        lifecycle: ResearchSourceLifecycle,
        request_id: str,
    ) -> ResearchSource:
        self._admin_gate(subject, request_id, "manage_policies")
        actor = uuid.UUID(subject.user_id)
        source = ResearchSource(
            stable_key=stable_key,
            display_name=display_name,
            description=description,
            origin=origin,
            owner_subject_id=owner_subject_id,
            classification=classification,
            lifecycle=lifecycle,
        )
        async with self.uow.transaction() as session:
            if not await self._subject_exists(session, owner_subject_id):
                raise GovernanceError("owner_subject_unknown")
            existing = await self.repository.get_source_by_key(session, stable_key)
            if existing is not None:
                raise GovernanceError("research_source_exists")
            created = await self.repository.create_source(session, source)
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.source.create",
                result="success",
                reason_code="research_source_registered",
                request_id=request_id,
                resource_type="research_source",
                details={
                    "source_id": str(created.source_id),
                    "stable_key": created.stable_key,
                    "origin": created.origin,
                    "classification": created.classification,
                    "lifecycle": created.lifecycle,
                    "owner_subject_id": str(created.owner_subject_id),
                },
            )
        return created

    async def list_sources(
        self,
        subject: Subject,
        *,
        request_id: str,
        lifecycle: ResearchSourceLifecycle | None = None,
    ) -> list[ResearchSource]:
        self._admin_gate(subject, request_id, "manage_policies")
        async with self.uow.factory() as session:
            return await self.repository.list_sources(session, lifecycle=lifecycle)

    async def source_detail(
        self,
        subject: Subject,
        source_id: uuid.UUID,
        *,
        request_id: str,
    ) -> ResearchSource:
        self._admin_gate(subject, request_id, "manage_policies")
        async with self.uow.factory() as session:
            source = await self.repository.get_source(session, source_id)
        if source is None:
            raise GovernanceError("research_source_not_found")
        return source

    async def update_source(
        self,
        subject: Subject,
        source_id: uuid.UUID,
        *,
        display_name: str | None = None,
        description: str | None = None,
        owner_subject_id: uuid.UUID | None = None,
        classification: Classification | None = None,
        lifecycle: ResearchSourceLifecycle | None = None,
        reason: str,
        request_id: str,
    ) -> ResearchSource:
        """Bounded, audited source update; classification is the AC-14 lever."""
        self._admin_gate(subject, request_id, "manage_policies")
        changes = {
            "display_name": display_name,
            "description": description,
            "owner_subject_id": owner_subject_id,
            "classification": classification,
            "lifecycle": lifecycle,
        }
        if all(value is None for value in changes.values()):
            raise GovernanceError("source_update_empty")
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            current = await self.repository.get_source(session, source_id)
            if current is None:
                raise GovernanceError("research_source_not_found")
            if owner_subject_id is not None and not await self._subject_exists(
                session,
                owner_subject_id,
            ):
                raise GovernanceError("owner_subject_unknown")
            updated = await self.repository.update_source(
                session,
                source_id,
                display_name=display_name,
                description=description,
                owner_subject_id=owner_subject_id,
                classification=classification,
                lifecycle=lifecycle,
            )
            before = current.model_dump(mode="json")
            after = updated.model_dump(mode="json")
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.source.update",
                result="success",
                reason_code="research_source_updated",
                request_id=request_id,
                resource_type="research_source",
                details={
                    "source_id": str(source_id),
                    "stable_key": updated.stable_key,
                    "reason": reason,
                    "changed": {
                        field: {"from": before[field], "to": after[field]}
                        for field, value in changes.items()
                        if value is not None and before[field] != after[field]
                    },
                },
            )
        return updated

    async def settings_overview(
        self,
        subject: Subject,
        *,
        request_id: str,
    ) -> list[SettingView]:
        """Effective registry-typed values; unset keys expose their default."""
        self._admin_gate(subject, request_id, "manage_policies")
        views: list[SettingView] = []
        async with self.uow.factory() as session:
            for setting_key in sorted(SETTING_REGISTRY):
                spec = SETTING_REGISTRY[setting_key]
                stored = await self.repository.get_setting(session, setting_key)
                views.append(SettingView(
                    setting_key=setting_key,
                    value_type=spec.value_type,
                    description=spec.description,
                    minimum=spec.minimum,
                    maximum=spec.maximum,
                    default=spec.default,
                    value=stored.value if stored is not None else spec.default,
                    version=stored.version if stored is not None else 0,
                    updated_at=stored.created_at if stored is not None else None,
                ))
        return views

    async def setting_versions(
        self,
        subject: Subject,
        setting_key: str,
        *,
        request_id: str,
    ) -> list[GovernanceSetting]:
        self._admin_gate(subject, request_id, "manage_policies")
        if setting_key not in SETTING_REGISTRY:
            raise GovernanceError("setting_unknown")
        async with self.uow.factory() as session:
            return await self.repository.list_setting_versions(session, setting_key)

    async def set_gap_priority(
        self,
        subject: Subject,
        gap_id: uuid.UUID,
        *,
        priority: GapPriority,
        reason: str,
        request_id: str,
    ) -> Gap:
        """Audited queue-priority change; the transition history stays intact."""
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            gap = await self.repository.get_gap(session, gap_id)
            if gap is None or not self.governance.gap_visible(
                subject,
                gap,
                request_id,
            ):
                raise GovernanceError("gap_not_found")
            if not self.governance.gap_mutation_allowed(subject, gap, request_id):
                raise PermissionError("curator_required")
            updated = await self.repository.set_gap_priority(
                session,
                gap_id,
                priority=priority,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.gap.priority",
                result="success",
                reason_code="gap_priority_changed",
                request_id=request_id,
                resource_type="gap",
                details={
                    "gap_id": str(gap_id),
                    "from_priority": gap.priority,
                    "to_priority": updated.priority,
                    "reason": reason,
                },
            )
        return updated

    def _subject_view(self, row: dict[str, Any]) -> SubjectAccountView:
        return SubjectAccountView(
            user_id=row["user_id"],
            issuer=str(row["issuer"]),
            email=str(row["email"]) if row["email"] is not None else None,
            display_name=str(row["display_name"]),
            status=str(row["status"]),
            security_version=int(row["security_version"]),
            roles=sorted(str(item) for item in row["roles"]),
            groups=sorted(str(item) for item in row["groups"]),
            last_seen_at=row["last_seen_at"],
        )

    async def list_subjects(
        self,
        subject: Subject,
        *,
        request_id: str,
        limit: int = 50,
    ) -> list[SubjectAccountView]:
        self._admin_gate(subject, request_id, "manage_users")
        limit = max(1, min(limit, SUBJECT_LIST_LIMIT))
        async with self.uow.factory() as session:
            rows = (await session.execute(text(
                SUBJECT_VIEW_SQL
                + " ORDER BY s.email NULLS LAST, s.user_id LIMIT :limit",
            ), {"limit": limit})).mappings().all()
        return [self._subject_view(dict(row)) for row in rows]

    async def _load_subject_view(
        self,
        session: AsyncSession,
        subject_id: uuid.UUID,
    ) -> SubjectAccountView | None:
        row = (await session.execute(text(
            SUBJECT_VIEW_SQL + " WHERE s.user_id = :subject_id",
        ), {"subject_id": subject_id})).mappings().one_or_none()
        return self._subject_view(dict(row)) if row else None

    async def _apply_binding(
        self,
        session: AsyncSession,
        *,
        subject_id: uuid.UUID,
        actor: uuid.UUID,
        binding: BindingKind,
        key: str,
        operation: BindingOperation,
    ) -> None:
        table = "subject_roles" if binding == "role" else "subject_groups"
        column = "role_id" if binding == "role" else "group_id"
        if binding == "role":
            principal = await session.scalar(text("""
                SELECT role_id FROM roles WHERE key = :key AND status = 'active'
            """), {"key": key})
            if principal is None:
                raise GovernanceError("role_unknown")
        else:
            issuer = await session.scalar(text(
                "SELECT issuer FROM subjects WHERE user_id = :subject_id",
            ), {"subject_id": subject_id})
            principal = await session.scalar(text("""
                SELECT group_id FROM groups
                WHERE issuer = :issuer AND provider_group_key = :key
                  AND status = 'active'
            """), {"issuer": issuer, "key": key})
            if principal is None:
                raise GovernanceError("group_unknown")
        bound = await session.scalar(text(f"""
            SELECT 1 FROM {table}
            WHERE subject_id = :subject_id AND {column} = :principal
              AND valid_from <= now()
              AND (expires_at IS NULL OR expires_at > now())
        """), {"subject_id": subject_id, "principal": principal})
        if operation == "assign":
            if bound is not None:
                raise GovernanceError("binding_exists")
            await session.execute(text(f"""
                INSERT INTO {table} (subject_id, {column}, assigned_by)
                VALUES (:subject_id, :principal, :actor)
            """), {"subject_id": subject_id, "principal": principal, "actor": actor})
        else:
            if bound is None:
                raise GovernanceError("binding_not_found")
            await session.execute(text(f"""
                DELETE FROM {table}
                WHERE subject_id = :subject_id AND {column} = :principal
            """), {"subject_id": subject_id, "principal": principal})

    async def mutate_binding(
        self,
        subject: Subject,
        subject_id: uuid.UUID,
        *,
        binding: BindingKind,
        key: str,
        operation: BindingOperation,
        reason: str,
        request_id: str,
    ) -> SubjectAccountView:
        """Assign or unassign one existing role/group binding (TIP-003 model).

        Only bindings to already-existing policy primitives are possible; the
        subject's security version is bumped so stale sessions cannot keep the
        old authority, and the change is audited in the same transaction.
        """
        self._admin_gate(subject, request_id, "manage_users")
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            if not await self._subject_exists(session, subject_id):
                raise GovernanceError("subject_not_found")
            await self._apply_binding(
                session,
                subject_id=subject_id,
                actor=actor,
                binding=binding,
                key=key,
                operation=operation,
            )
            version = await session.scalar(text("""
                UPDATE subjects SET security_version = security_version + 1,
                  updated_at = now()
                WHERE user_id = :subject_id
                RETURNING security_version
            """), {"subject_id": subject_id})
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action=f"admin.binding.{operation}",
                result="success",
                reason_code=f"{binding}_binding_{operation}ed",
                request_id=request_id,
                resource_type="subject_binding",
                details={
                    "subject_id": str(subject_id),
                    "binding": binding,
                    "key": key,
                    "reason": reason,
                    "security_version": int(version),
                },
            )
        await self._project_session_revocation(subject_id)
        async with self.uow.factory() as session:
            view = await self._load_subject_view(session, subject_id)
        if view is None:
            raise GovernanceError("subject_not_found")
        return view

    async def _project_session_revocation(self, subject_id: uuid.UUID) -> None:
        """Best-effort projection of the PostgreSQL authority bump into Redis.

        PostgreSQL remains canonical (login sync re-projects on next OIDC
        round-trip); a reachable Redis drops every live session immediately.
        """
        try:
            client = Redis.from_url(self.settings.redis_url, decode_responses=True)
            try:
                await SessionStore(
                    client,
                    self.settings.session_ttl_seconds,
                ).revoke_all(str(subject_id))
            finally:
                await client.aclose()
        except Exception:
            logger.exception("binding_session_projection_failed")

    async def _counts(
        self,
        session: AsyncSession,
        table: str,
        column: str,
    ) -> dict[str, int]:
        rows = (await session.execute(text(
            f"SELECT {column} AS state, count(*) AS total "
            f"FROM {table} GROUP BY {column}",
        ))).mappings().all()
        return {str(row["state"]): int(row["total"]) for row in rows}

    async def job_health(
        self,
        subject: Subject,
        *,
        request_id: str,
    ) -> JobHealthReport:
        """Live, read-only job state; identifiers and codes only, no payloads."""
        self._admin_gate(subject, request_id, "manage_policies")
        now = datetime.now(UTC)
        async with self.uow.factory() as session:
            ingestion_counts = await self._counts(session, "ingestion_jobs", "status")
            ingestion_outbox = await self._counts(session, "ingestion_outbox", "status")
            ingestion_failures = (await session.execute(text("""
                SELECT job_id, job_type, status, error_code, attempt, updated_at
                FROM ingestion_jobs
                WHERE status IN ('failed','quarantined','retry_wait')
                ORDER BY updated_at DESC LIMIT :limit
            """), {"limit": RECENT_FAILURE_LIMIT})).mappings().all()
            render_counts = await self._counts(session, "render_jobs", "state")
            render_outbox = await self._counts(
                session,
                "document_publication_outbox",
                "state",
            )
            render_failures = (await session.execute(text("""
                SELECT render_job_id, state, error_code,
                  COALESCE(finished_at, created_at) AS occurred_at
                FROM render_jobs
                WHERE state IN ('failed','cancelled')
                ORDER BY COALESCE(finished_at, created_at) DESC LIMIT :limit
            """), {"limit": RECENT_FAILURE_LIMIT})).mappings().all()
            index_counts = await self._counts(session, "index_jobs", "status")
            reindex_outbox = await self._counts(session, "sot_reindex_outbox", "status")
            index_failures = (await session.execute(text("""
                SELECT job_id, status, failure_code, attempt, updated_at
                FROM index_jobs
                WHERE status = 'failed'
                ORDER BY updated_at DESC LIMIT :limit
            """), {"limit": RECENT_FAILURE_LIMIT})).mappings().all()
        return JobHealthReport(
            computed_at=now,
            families=[
                JobFamilyHealth(
                    family="ingestion",
                    job_counts=ingestion_counts,
                    outbox_counts=ingestion_outbox,
                    recent_failures=[
                        JobFailureView(
                            job_id=row["job_id"],
                            kind=str(row["job_type"]),
                            status=str(row["status"]),
                            error_code=row["error_code"],
                            attempt=int(row["attempt"]),
                            occurred_at=row["updated_at"],
                        )
                        for row in ingestion_failures
                    ],
                ),
                JobFamilyHealth(
                    family="render",
                    job_counts=render_counts,
                    outbox_counts=render_outbox,
                    recent_failures=[
                        JobFailureView(
                            job_id=row["render_job_id"],
                            kind="render",
                            status=str(row["state"]),
                            error_code=row["error_code"],
                            occurred_at=row["occurred_at"],
                        )
                        for row in render_failures
                    ],
                ),
                JobFamilyHealth(
                    family="reindex",
                    job_counts=index_counts,
                    outbox_counts=reindex_outbox,
                    recent_failures=[
                        JobFailureView(
                            job_id=row["job_id"],
                            kind="index",
                            status=str(row["status"]),
                            error_code=row["failure_code"],
                            attempt=int(row["attempt"]),
                            occurred_at=row["updated_at"],
                        )
                        for row in index_failures
                    ],
                ),
            ],
        )

    @staticmethod
    def _pilot_gate(
        gate_key: str,
        *,
        target: int,
        actual: int,
        detail: str,
        blocked: bool = False,
    ) -> PilotGate:
        state: PilotGateState = (
            "blocked" if blocked else "met" if actual >= target else "partial"
        )
        return PilotGate(
            gate_key=gate_key,
            target=target,
            actual=actual,
            state=state,
            detail=detail,
        )

    async def pilot_readiness(
        self,
        subject: Subject,
        *,
        request_id: str,
    ) -> PilotReadinessReport:
        """Live, read-only reconciliation for the TIP-024 pilot campaign."""
        self._admin_gate(subject, request_id, "manage_policies")
        async with self.uow.factory() as session:
            sot_row = dict((await session.execute(text("""
                SELECT
                  count(*)::int AS active_records,
                  count(*) FILTER (
                    WHERE rv.provenance_level='verified_primary'
                      AND rv.verification_state='verified'
                      AND COALESCE(
                        rv.value_payload #>> '{confidence_signal,needs_double_check}',
                        'false'
                      ) <> 'true'
                  )::int AS strict_records,
                  count(*) FILTER (
                    WHERE rv.value_payload #>>
                      '{confidence_signal,needs_double_check}'='true'
                  )::int AS caveated_records,
                  count(*) FILTER (WHERE rv.freshness_state='current')::int
                    AS current_records,
                  count(*) FILTER (WHERE rv.freshness_state<>'current')::int
                    AS stale_records,
                  count(*) FILTER (
                    WHERE s.issuer <> 'tip013b-onboard'
                      AND COALESCE(s.email,'') NOT LIKE '%migration-owner%'
                  )::int AS named_owner_records,
                  count(*) FILTER (
                    WHERE s.issuer = 'tip013b-onboard'
                       OR COALESCE(s.email,'') LIKE '%migration-owner%'
                  )::int AS placeholder_owner_records,
                  count(*) FILTER (
                    WHERE rv.value_payload #>>
                      '{confidence_signal,needs_double_check}'='true'
                      AND s.issuer <> 'tip013b-onboard'
                      AND COALESCE(s.email,'') NOT LIKE '%migration-owner%'
                  )::int AS caveated_named_owner_records,
                  count(*) FILTER (
                    WHERE rv.value_payload #>>
                      '{confidence_signal,needs_double_check}'='true'
                      AND (
                        s.issuer = 'tip013b-onboard'
                        OR COALESCE(s.email,'') LIKE '%migration-owner%'
                      )
                  )::int AS caveated_placeholder_owner_records,
                  count(*) FILTER (
                    WHERE r.record_key LIKE 'SPEC.%'
                       OR r.record_key LIKE 'PRICE.%'
                       OR r.record_key LIKE 'REG.%'
                       OR r.record_key LIKE 'L3F.ENT.%'
                  )::int AS high_risk_records,
                  count(*) FILTER (
                    WHERE (
                      r.record_key LIKE 'SPEC.%'
                      OR r.record_key LIKE 'PRICE.%'
                      OR r.record_key LIKE 'REG.%'
                      OR r.record_key LIKE 'L3F.ENT.%'
                    ) AND rv.value_payload #>>
                      '{confidence_signal,needs_double_check}'='true'
                  )::int AS high_risk_caveated_records,
                  count(*) FILTER (WHERE rs.source_zone <> 'sot')::int
                    AS zone_masquerade_findings
                FROM records r
                JOIN record_versions rv ON rv.version_id=r.current_version_id
                JOIN resources rs ON rs.resource_id=r.record_id
                JOIN subjects s ON s.user_id=r.owner_subject_id
                WHERE r.lifecycle='active' AND rv.lifecycle='active'
            """))).mappings().one())
            file_row = dict((await session.execute(text("""
                SELECT
                  count(DISTINCT d.document_id)::int AS documents,
                  count(DISTINCT dv.version_id)::int AS versions,
                  count(DISTINCT dv.version_id) FILTER (
                    WHERE dv.byte_size >= 1024
                  )::int AS representative_versions,
                  count(DISTINCT dv.version_id) FILTER (
                    WHERE dv.viewer_state='ready'
                  )::int AS ready_versions,
                  count(DISTINCT fc.document_version_id)::int AS indexed_versions,
                  count(DISTINCT dv.version_id) FILTER (
                    WHERE ob.sha256 <> dv.sha256
                  )::int AS original_checksum_mismatches,
                  count(DISTINCT rd.version_id) FILTER (
                    WHERE rd.source_sha256 IS DISTINCT FROM dv.sha256
                  )::int AS rendition_lineage_mismatches
                FROM documents d
                JOIN document_versions dv ON dv.document_id=d.document_id
                JOIN object_blobs ob ON ob.object_id=dv.object_id
                LEFT JOIN file_chunks fc ON fc.document_version_id=dv.version_id
                LEFT JOIN renditions rd ON rd.version_id=dv.version_id
                  AND rd.status='ready'
            """))).mappings().one())
            family_rows = (await session.execute(text("""
                SELECT CASE
                  WHEN mime_type='application/pdf' THEN 'pdf'
                  WHEN mime_type LIKE 'image/%' THEN 'image'
                  WHEN mime_type LIKE 'video/%' THEN 'video'
                  WHEN mime_type LIKE 'audio/%' THEN 'audio'
                  WHEN mime_type LIKE '%wordprocessingml%' THEN 'docx'
                  WHEN mime_type LIKE '%spreadsheetml%' THEN 'xlsx'
                  WHEN mime_type LIKE '%presentationml%' THEN 'pptx'
                  ELSE 'other' END AS family,
                  count(*)::int AS total
                FROM document_versions
                WHERE byte_size >= 1024
                GROUP BY family ORDER BY family
            """))).mappings().all()
            template_row = dict((await session.execute(text("""
                SELECT
                  count(DISTINCT t.template_id)::int AS templates,
                  count(DISTINCT t.template_id) FILTER (
                    WHERE t.lifecycle='approved'
                  )::int AS approved_templates,
                  count(DISTINCT tb.binding_id) FILTER (
                    WHERE tb.source='locked_fact'
                  )::int AS locked_bindings,
                  count(DISTINCT t.template_id) FILTER (
                    WHERE t.lifecycle='approved'
                      AND t.document_class IN ('official','legal')
                  )::int AS official_or_legal_approved
                FROM templates t
                LEFT JOIN template_versions tv
                  ON tv.template_id=t.template_id
                LEFT JOIN template_bindings tb
                  ON tb.template_version_id=tv.version_id
            """))).mappings().one())
            research_row = dict((await session.execute(text("""
                SELECT
                  (SELECT count(*) FROM research_sources
                    WHERE lifecycle='active')::int AS active_sources,
                  (SELECT count(*) FROM research_packages
                    WHERE import_state='imported')::int AS imported_packages,
                  (SELECT count(*) FROM research_records)::int AS records
            """))).mappings().one())
            tier_rows = (await session.execute(text("""
                SELECT tier AS key,count(*)::int AS total
                FROM research_records GROUP BY tier ORDER BY tier
            """))).mappings().all()
            corroboration_rows = (await session.execute(text("""
                SELECT corroboration_state AS key,count(*)::int AS total
                FROM research_records
                GROUP BY corroboration_state ORDER BY corroboration_state
            """))).mappings().all()
        sot = PilotSotSummary.model_validate(sot_row)
        files = PilotFileSummary(
            **file_row,
            viewer_families={
                str(row["family"]): int(row["total"]) for row in family_rows
            },
        )
        templates = PilotTemplateSummary.model_validate(template_row)
        research = PilotResearchSummary(
            **research_row,
            tiers={str(row["key"]): int(row["total"]) for row in tier_rows},
            corroboration={
                str(row["key"]): int(row["total"])
                for row in corroboration_rows
            },
        )
        question_count = len(load_pilot_questions())
        gates = [
            self._pilot_gate(
                "sot_gold_baseline", target=8, actual=sot.strict_records,
                detail="Strict records retained without provenance promotion",
            ),
            self._pilot_gate(
                "caveated_named_owners", target=sot.caveated_records,
                actual=sot.caveated_named_owner_records,
                detail="Caveated records assigned to named human owners",
                blocked=sot.caveated_placeholder_owner_records > 0,
            ),
            self._pilot_gate(
                "representative_files", target=30,
                actual=files.representative_versions,
                detail="Ready real file versions of at least 1 KiB",
            ),
            self._pilot_gate(
                "viewer_families", target=4,
                actual=len(files.viewer_families),
                detail="Distinct representative viewer families",
            ),
            self._pilot_gate(
                "approved_templates", target=4,
                actual=templates.approved_templates,
                detail="Approved internal pilot templates",
            ),
            self._pilot_gate(
                "research_records", target=50, actual=research.records,
                detail="Imported Research-zone records",
            ),
            self._pilot_gate(
                "pilot_questions", target=25, actual=question_count,
                detail="Source-controlled role-labelled pilot questions",
            ),
            self._pilot_gate(
                "zone_integrity", target=0,
                actual=sot.zone_masquerade_findings,
                detail="SOT records outside the SOT source zone",
                blocked=sot.zone_masquerade_findings > 0,
            ),
            self._pilot_gate(
                "checksum_integrity", target=0,
                actual=(
                    files.original_checksum_mismatches
                    + files.rendition_lineage_mismatches
                ),
                detail="Unexplained original/rendition checksum findings",
                blocked=(
                    files.original_checksum_mismatches
                    + files.rendition_lineage_mismatches
                ) > 0,
            ),
        ]
        return PilotReadinessReport(
            computed_at=datetime.now(UTC),
            sot=sot,
            files=files,
            templates=templates,
            research=research,
            question_count=question_count,
            gates=gates,
        )
