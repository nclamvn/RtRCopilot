"""Live, policy-scoped governance dashboard (TIP-010 Task 7 backend, AC-12).

Every tile is computed server-side from live tables at request time under the
caller's policy scope; no stored snapshot serves any number (REQ-034,
D-010-05). Denied existence never enters a count, and every tile carries a
structural zone label so the UI can separate SOT surfaces from research
surfaces (D-010-08).
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.auth.models import PolicyContext, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.models import Gap, StrictModel
from rtr_copilot.governance.service import (
    GAP_BATCH_SIZE,
    GAP_SCAN_LIMIT,
    GovernanceService,
    policy,
)
from rtr_copilot.ingestion.api import _effective_principal_ids
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.governance import GovernanceRepository
from rtr_copilot.repositories.resources import ResourceRepository
from rtr_copilot.research.service import ResearchService

COVERAGE_SCAN_LIMIT = 1000

CLOSED_GAP_STATES = frozenset({"published", "declined", "resolved", "dismissed"})
AGE_BUCKETS = ("under_24h", "days_1_3", "days_3_7", "over_7_days")

COVERAGE_SQL = """
    SELECT r.record_id, r.record_key, r.source_key, r.owner_subject_id,
      rv.classification
    FROM records r
    JOIN record_versions rv ON rv.version_id = r.current_version_id
    WHERE r.lifecycle = 'active' AND rv.lifecycle = 'active'
    ORDER BY r.record_key, r.record_id
    LIMIT :scan_limit
"""
RESEARCH_TIER_SQL = """
    SELECT package_id, tier, count(*) AS total
    FROM research_records
    WHERE package_id = ANY(:package_ids)
    GROUP BY package_id, tier
"""


def aging_bucket(first_seen_at: datetime, *, now: datetime) -> str:
    """Bucket an open gap by age; boundaries are half-open at 24h/72h/168h."""
    hours = (now - first_seen_at).total_seconds() / 3600
    if hours < 24:
        return AGE_BUCKETS[0]
    if hours < 72:
        return AGE_BUCKETS[1]
    if hours < 168:
        return AGE_BUCKETS[2]
    return AGE_BUCKETS[3]


class CoverageTile(StrictModel):
    zone_label: Literal["sot"] = "sot"
    total_records: int
    by_source_key: dict[str, int]
    by_owner: dict[str, int]
    by_classification: dict[str, int]


class FreshnessTile(StrictModel):
    zone_label: Literal["sot"] = "sot"
    total: int
    expiring: int
    expired: int
    assigned: int
    unassigned: int


class ConflictTile(StrictModel):
    """Live conflict-queue aggregates under the caller's scope (TIP-011)."""

    zone_label: Literal["sot"] = "sot"
    total: int
    disputed: int
    superseded_ambiguous: int
    assigned: int
    unassigned: int


class OwnerReviewTile(StrictModel):
    """Live owner-review aggregates under the caller's scope (TIP-011)."""

    zone_label: Literal["sot"] = "sot"
    total: int
    due: int
    overdue: int
    assigned: int
    unassigned: int


class GapFlowTile(StrictModel):
    zone_label: Literal["sot"] = "sot"
    open_total: int
    closed_total: int
    overdue: int
    by_state: dict[str, int]
    aging: dict[str, int]


class ResearchIntakeTile(StrictModel):
    zone_label: Literal["research"] = "research"
    sources_total: int
    sources_active: int
    packages_by_state: dict[str, int]
    records_by_tier: dict[str, int]


class GraduationFunnelTile(StrictModel):
    zone_label: Literal["research"] = "research"
    proposed: int
    approved: int
    rejected: int
    submitted: int


class GovernanceDashboard(StrictModel):
    computed_at: datetime
    coverage: CoverageTile
    freshness: FreshnessTile
    conflict: ConflictTile
    owner_review: OwnerReviewTile
    gap_flow: GapFlowTile
    research_intake: ResearchIntakeTile
    graduation: GraduationFunnelTile


class DashboardService:
    """Computes every dashboard tile live under the caller's policy scope."""

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()
        self.settings = get_settings()
        self.repository = GovernanceRepository()
        self.governance = GovernanceService(uow=self.uow)
        self.research = ResearchService(self.settings, factory=self.uow.factory)

    async def _coverage(
        self,
        session: AsyncSession,
        subject: Subject,
        request_id: str,
    ) -> CoverageTile:
        rows = (await session.execute(
            text(COVERAGE_SQL),
            {"scan_limit": COVERAGE_SCAN_LIMIT},
        )).mappings().all()
        principals = await _effective_principal_ids(session, subject)
        context = PolicyContext(request_id=request_id)
        caller = uuid.UUID(subject.user_id)
        by_source: dict[str, int] = {}
        by_owner: dict[str, int] = {}
        by_classification: dict[str, int] = {}
        total = 0
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
            total += 1
            source_key = str(row["source_key"])
            owner_key = str(row["owner_subject_id"])
            classification = str(row["classification"])
            by_source[source_key] = by_source.get(source_key, 0) + 1
            by_owner[owner_key] = by_owner.get(owner_key, 0) + 1
            by_classification[classification] = (
                by_classification.get(classification, 0) + 1
            )
        return CoverageTile(
            total_records=total,
            by_source_key=by_source,
            by_owner=by_owner,
            by_classification=by_classification,
        )

    async def _freshness(self, subject: Subject, request_id: str) -> FreshnessTile:
        page = await self.governance.queue_page(
            subject,
            "freshness",
            request_id=request_id,
            limit=1,
        )
        return FreshnessTile(
            total=page.aggregates.total,
            expiring=page.aggregates.by_status.get("expiring", 0),
            expired=page.aggregates.by_status.get("expired", 0),
            assigned=page.aggregates.assigned,
            unassigned=page.aggregates.unassigned,
        )

    async def _conflict(self, subject: Subject, request_id: str) -> ConflictTile:
        """Live conflict aggregates via Builder 2's queue computation; the
        aggregates only count caller-visible entries, so hidden rows never
        enter any number (same leak-safety as the freshness tile)."""
        page = await self.governance.queue_page(
            subject,
            "conflict",
            request_id=request_id,
            limit=1,
        )
        return ConflictTile(
            total=page.aggregates.total,
            disputed=page.aggregates.by_status.get("disputed", 0),
            superseded_ambiguous=page.aggregates.by_status.get(
                "superseded_ambiguous",
                0,
            ),
            assigned=page.aggregates.assigned,
            unassigned=page.aggregates.unassigned,
        )

    async def _owner_review(
        self,
        subject: Subject,
        request_id: str,
    ) -> OwnerReviewTile:
        page = await self.governance.queue_page(
            subject,
            "owner_review",
            request_id=request_id,
            limit=1,
        )
        return OwnerReviewTile(
            total=page.aggregates.total,
            due=page.aggregates.by_status.get("due", 0),
            overdue=page.aggregates.by_status.get("overdue", 0),
            assigned=page.aggregates.assigned,
            unassigned=page.aggregates.unassigned,
        )

    async def _visible_gaps(
        self,
        session: AsyncSession,
        subject: Subject,
        request_id: str,
    ) -> list[Gap]:
        visible: list[Gap] = []
        cursor: str | None = None
        scanned = 0
        while scanned < GAP_SCAN_LIMIT:
            page = await self.repository.list_gaps(
                session,
                cursor=cursor,
                limit=GAP_BATCH_SIZE,
            )
            if not page.items:
                break
            for gap in page.items:
                scanned += 1
                if self.governance.gap_visible(subject, gap, request_id):
                    visible.append(gap)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return visible

    async def _gap_flow(
        self,
        session: AsyncSession,
        subject: Subject,
        request_id: str,
        *,
        now: datetime,
    ) -> GapFlowTile:
        gaps = await self._visible_gaps(session, subject, request_id)
        by_state: dict[str, int] = {}
        aging = dict.fromkeys(AGE_BUCKETS, 0)
        open_total = 0
        closed_total = 0
        overdue = 0
        for gap in gaps:
            state = str(gap.lifecycle)
            by_state[state] = by_state.get(state, 0) + 1
            if state in CLOSED_GAP_STATES:
                closed_total += 1
                continue
            open_total += 1
            aging[aging_bucket(gap.first_seen_at, now=now)] += 1
            if gap.due_at is not None and gap.due_at <= now:
                overdue += 1
        return GapFlowTile(
            open_total=open_total,
            closed_total=closed_total,
            overdue=overdue,
            by_state=by_state,
            aging=aging,
        )

    async def _research_intake(
        self,
        session: AsyncSession,
        subject: Subject,
        request_id: str,
    ) -> ResearchIntakeTile:
        sources = await self.repository.list_sources(session)
        visible_sources = [
            source
            for source in sources
            if self.research.source_visible(subject, source, request_id)
        ]
        visible_ids = {source.source_id for source in visible_sources}
        packages = await self.repository.list_packages(session)
        visible_packages = [
            package for package in packages if package.source_id in visible_ids
        ]
        packages_by_state: dict[str, int] = {}
        for package in visible_packages:
            state = str(package.import_state)
            packages_by_state[state] = packages_by_state.get(state, 0) + 1
        imported_ids = [
            package.package_id
            for package in visible_packages
            if package.import_state == "imported"
        ]
        records_by_tier: dict[str, int] = {}
        if imported_ids:
            rows = (await session.execute(
                text(RESEARCH_TIER_SQL),
                {"package_ids": imported_ids},
            )).mappings().all()
            for row in rows:
                tier = str(row["tier"])
                records_by_tier[tier] = records_by_tier.get(tier, 0) + int(row["total"])
        return ResearchIntakeTile(
            sources_total=len(visible_sources),
            sources_active=sum(
                1 for source in visible_sources if source.lifecycle == "active"
            ),
            packages_by_state=packages_by_state,
            records_by_tier=records_by_tier,
        )

    async def _graduation(
        self,
        session: AsyncSession,
        subject: Subject,
        request_id: str,
    ) -> GraduationFunnelTile:
        proposals = await self.repository.list_proposals(session)
        visible = [
            proposal
            for proposal in proposals
            if self.research.proposal_visible(subject, proposal, request_id)
        ]
        return GraduationFunnelTile(
            proposed=sum(1 for item in visible if item.state == "proposed"),
            approved=sum(1 for item in visible if item.state == "approved"),
            rejected=sum(1 for item in visible if item.state == "rejected"),
            submitted=sum(
                1
                for item in visible
                if item.state == "approved" and item.publish_package_id is not None
            ),
        )

    async def dashboard(
        self,
        subject: Subject,
        *,
        request_id: str,
    ) -> GovernanceDashboard:
        """One live computation pass; the export is audited (no content)."""
        now = datetime.now(UTC)
        freshness = await self._freshness(subject, request_id)
        conflict = await self._conflict(subject, request_id)
        owner_review = await self._owner_review(subject, request_id)
        async with self.uow.factory() as session:
            coverage = await self._coverage(session, subject, request_id)
            gap_flow = await self._gap_flow(session, subject, request_id, now=now)
            research_intake = await self._research_intake(
                session,
                subject,
                request_id,
            )
            graduation = await self._graduation(session, subject, request_id)
        report = GovernanceDashboard(
            computed_at=now,
            coverage=coverage,
            freshness=freshness,
            conflict=conflict,
            owner_review=owner_review,
            gap_flow=gap_flow,
            research_intake=research_intake,
            graduation=graduation,
        )
        await self._audit_export(subject, request_id, report)
        return report

    async def _audit_export(
        self,
        subject: Subject,
        request_id: str,
        report: GovernanceDashboard,
    ) -> None:
        details: dict[str, Any] = {
            "coverage_total": report.coverage.total_records,
            "freshness_total": report.freshness.total,
            "conflict_total": report.conflict.total,
            "owner_review_total": report.owner_review.total,
            "gaps_open": report.gap_flow.open_total,
            "gaps_closed": report.gap_flow.closed_total,
            "research_sources": report.research_intake.sources_total,
            "proposals": (
                report.graduation.proposed
                + report.graduation.approved
                + report.graduation.rejected
            ),
        }
        async with self.uow.transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action="governance.dashboard.view",
                result="success",
                reason_code="live_aggregates_disclosed",
                request_id=request_id,
                resource_type="governance_dashboard",
                details=details,
            )
