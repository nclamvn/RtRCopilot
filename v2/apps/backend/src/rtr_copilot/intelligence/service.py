"""Live, evidence-bound briefing over SOT and the separate Research zone."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.models import ResearchSource
from rtr_copilot.ingestion.api import _effective_principal_ids
from rtr_copilot.intelligence.models import (
    IntelligenceBriefing,
    IntelligenceCounts,
    IntelligenceEvidence,
    IntelligenceItem,
)
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import ResourceRepository
from rtr_copilot.research.service import ResearchService

MAX_LIMIT = 20
METADATA_SCAN_LIMIT = 500
SOURCE_QUOTA = 3
SUMMARY_LIMIT = 520

SOT_METADATA_SQL = """
    SELECT r.record_id,r.record_key,r.source_key,rv.version_id,
      rv.package_revision,rv.provenance_level,rv.verification_state,
      rv.fact_state,rv.freshness_state,rv.freshness_due_at,
      rv.effective_from,rv.created_at,rv.content_sha256,rv.classification,
      sp.producer
    FROM records r
    JOIN record_versions rv ON rv.version_id=r.current_version_id
    JOIN sot_packages sp ON sp.package_id=rv.package_id
    JOIN resources rs ON rs.resource_id=r.record_id
    WHERE r.lifecycle='active' AND rv.lifecycle='active'
      AND rs.lifecycle_state='active'
      AND rv.fact_state IN ('approved','verified')
      AND rv.verification_state IN ('approved','verified')
      AND rv.provenance_level <> 'claim'
    ORDER BY
      CASE rv.freshness_state WHEN 'expired' THEN 0 WHEN 'stale' THEN 1
        WHEN 'unknown' THEN 2 ELSE 3 END,
      rv.created_at DESC,r.record_key
    LIMIT :scan_limit
"""

SOT_CONTENT_SQL = """
    SELECT rv.version_id,rv.value_payload,rv.searchable_text,
      COALESCE(e.source_label,r.source_key) AS source_label,
      COALESCE(e.locator,jsonb_build_object('record_key',r.record_key)) AS locator
    FROM record_versions rv
    JOIN records r ON r.record_id=rv.record_id
    LEFT JOIN LATERAL (
      SELECT source_label,locator FROM evidence_spans
      WHERE record_version_id=rv.version_id AND lifecycle='active'
      ORDER BY evidence_key LIMIT 1
    ) e ON true
    WHERE rv.version_id=ANY(CAST(:ids AS uuid[])) AND rv.lifecycle='active'
"""

RESEARCH_METADATA_SQL = """
    SELECT rr.research_record_id,rr.record_key,rr.version_ordinal,rr.tier,
      rr.corroboration_state,rr.content_sha256,rr.created_at,
      rp.package_id,rp.fingerprint,rs.source_id,rs.stable_key,
      rs.origin,rs.owner_subject_id,rs.classification,rs.lifecycle
    FROM research_records rr
    JOIN research_packages rp ON rp.package_id=rr.package_id
      AND rp.import_state='imported'
    JOIN research_sources rs ON rs.source_id=rp.source_id
      AND rs.lifecycle='active'
    WHERE rr.tier IN ('P','S','H')
      AND rr.corroboration_state <> 'disputed'
    ORDER BY
      CASE rr.corroboration_state WHEN 'corroborated' THEN 0 ELSE 1 END,
      CASE rr.tier WHEN 'P' THEN 0 WHEN 'S' THEN 1 ELSE 2 END,
      rr.created_at DESC,rr.record_key
    LIMIT :scan_limit
"""

RESEARCH_CONTENT_SQL = """
    SELECT rr.research_record_id,rr.record_key,rr.tier,rr.content,
      rr.corroboration_state,rr.content_sha256,rr.created_at,
      rr.searchable_text,rr.evidence_spans,rp.fingerprint,
      rs.source_id,rs.stable_key,rs.origin,rs.owner_subject_id,
      rs.classification,rs.lifecycle
    FROM research_records rr
    JOIN research_packages rp ON rp.package_id=rr.package_id
      AND rp.import_state='imported'
    JOIN research_sources rs ON rs.source_id=rp.source_id
      AND rs.lifecycle='active'
    WHERE rr.research_record_id=ANY(CAST(:ids AS uuid[]))
      AND rr.tier IN ('P','S','H')
      AND rr.corroboration_state <> 'disputed'
"""

_SPACE = re.compile(r"\s+")
_KEY_SEPARATOR = re.compile(r"[._-]+")
_NON_USER_PRODUCER = re.compile(
    r"(?:^test-fixture$|(?:^|[-_.])(?:tests?|integration)$)",
    re.IGNORECASE,
)
_VIETNAMESE = re.compile(
    r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩị"
    r"óòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    re.IGNORECASE,
)


def _clean(value: str, maximum: int) -> str:
    normalized = _SPACE.sub(" ", value).strip()
    if len(normalized) <= maximum:
        return normalized
    return normalized[: maximum - 1].rstrip() + "…"


def _humanize_key(record_key: str) -> str:
    label = _clean(_KEY_SEPARATOR.sub(" ", record_key), 180)
    return label or record_key[:180]


def _briefing_producer_allowed(producer: object) -> bool:
    """Keep synthetic and integration-fixture packages out of employee UX."""

    return not _NON_USER_PRODUCER.search(str(producer).strip())


def _payload_title(payload: object, record_key: str) -> str:
    if isinstance(payload, dict):
        for key in ("title", "display_name", "name", "label", "subject", "entity"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _clean(value, 180)
    return _humanize_key(record_key)


def _ask_query(title: str, record_key: str, sample: str) -> str:
    if _VIETNAMESE.search(sample):
        return _clean(
            f"Giải thích ý nghĩa, tác động và các việc cần lưu ý về {title} "
            f"theo hồ sơ {record_key}.",
            500,
        )
    return _clean(
        f"Explain the meaning, impact and next considerations for {title} "
        f"using record {record_key}.",
        500,
    )


def _item_id(zone: str, identity: object, kind: str) -> str:
    return hashlib.sha256(f"{zone}:{identity}:{kind}".encode()).hexdigest()


def _research_source(row: dict[str, Any]) -> ResearchSource:
    return ResearchSource(
        source_id=row["source_id"],
        stable_key=str(row["stable_key"]),
        display_name=str(row["stable_key"]),
        origin=row["origin"],
        owner_subject_id=row["owner_subject_id"],
        classification=row["classification"],
        lifecycle=row["lifecycle"],
    )


class IntelligenceService:
    """Create a bounded briefing without generating new factual claims."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        resources: ResourceRepository | None = None,
        research: ResearchService | None = None,
        dlp: ProviderPolicy | None = None,
    ) -> None:
        self.uow = UnitOfWork(factory)
        self.resources = resources or ResourceRepository()
        self.policy = PolicyEngine(StructuredAuditSink())
        self.research = research or ResearchService(factory=self.uow.factory)
        # This endpoint never sends content to a provider. Its DLP pass is a
        # local disclosure guard, independent of the configured LLM mode.
        self.dlp = dlp or ProviderPolicy(mode="local")

    async def _authorized_sot(
        self,
        session: AsyncSession,
        subject: Subject,
        rows: list[dict[str, Any]],
        request_id: str,
    ) -> list[dict[str, Any]]:
        principals = await _effective_principal_ids(session, subject)
        context = PolicyContext(request_id=request_id)
        allowed: list[dict[str, Any]] = []
        for row in rows:
            attributes = await self.resources.policy_attributes(
                session,
                row["record_id"],
                action="view",
                principal_ids=principals,
            )
            if attributes is not None and self.policy.decide(
                subject,
                "view",
                attributes,
                context,
            ).allow:
                allowed.append(row)
        return allowed

    async def _sot_items(
        self,
        subject: Subject,
        *,
        request_id: str,
        budget: int,
    ) -> tuple[list[IntelligenceItem], list[str]]:
        async with self.uow.factory() as session:
            metadata = [dict(row) for row in (await session.execute(
                text(SOT_METADATA_SQL),
                {"scan_limit": METADATA_SCAN_LIMIT},
            )).mappings().all() if _briefing_producer_allowed(row["producer"])]
            allowed = await self._authorized_sot(
                session,
                subject,
                metadata,
                request_id,
            )
            candidate_ids = [
                row["version_id"]
                for row in allowed[: budget * 6]
                if str(row["freshness_state"]) == "current"
            ]
            content_rows = (
                (await session.execute(text(SOT_CONTENT_SQL), {"ids": candidate_ids}))
                .mappings().all()
                if candidate_ids else []
            )
            content = {row["version_id"]: dict(row) for row in content_rows}
            # Re-evaluate authorization after content load. A revoked record is
            # removed rather than disclosed from the earlier snapshot.
            still_allowed = await self._authorized_sot(
                session,
                subject,
                allowed[: budget * 6],
                request_id,
            )

        rules: list[str] = []
        items: list[IntelligenceItem] = []
        source_counts: Counter[str] = Counter()
        for row in still_allowed:
            if len(items) >= budget:
                break
            source_key = str(row["source_key"])
            if source_counts[source_key] >= SOURCE_QUOTA:
                continue
            freshness = str(row["freshness_state"])
            kind: Literal["attention", "update"] = (
                "attention"
                if freshness in {"stale", "expired", "unknown"}
                else "update"
            )
            if kind == "attention":
                # Never load or disclose a stale value as a current company
                # fact. The immutable identity and freshness metadata are
                # enough to route a review.
                title = _humanize_key(str(row["record_key"]))
                summary = "This governed record requires freshness review before use."
                sample = title
                source_label = source_key
                locator: dict[str, object] = {"record_key": str(row["record_key"])}
            else:
                payload = content.get(row["version_id"])
                if payload is None:
                    continue
                title = _payload_title(payload["value_payload"], str(row["record_key"]))
                summary = _clean(str(payload["searchable_text"]), SUMMARY_LIMIT)
                sample = summary
                decision = self.dlp.inspect(
                    summary,
                    classification=str(row["classification"]),
                )
                if not decision.allow or decision.text is None:
                    rules.extend(decision.rule_ids)
                    continue
                summary = decision.text
                source_label = _clean(str(payload["source_label"]), 512)
                locator = dict(payload["locator"])
            title_decision = self.dlp.inspect(
                title,
                classification=str(row["classification"]),
            )
            if not title_decision.allow or title_decision.text is None:
                rules.extend(title_decision.rule_ids)
                continue
            title = title_decision.text
            evidence = IntelligenceEvidence(
                zone_label="sot",
                record_key=str(row["record_key"]),
                source_key=source_key,
                source_label=source_label,
                content_sha256=str(row["content_sha256"]),
                locator=locator,
                record_version_id=row["version_id"],
                source_revision=int(row["package_revision"]),
                provenance_level=str(row["provenance_level"]),
                verification_state=str(row["verification_state"]),
                freshness_state=freshness,
            )
            items.append(IntelligenceItem(
                item_id=_item_id("sot", row["version_id"], kind),
                zone_label="sot",
                kind=kind,
                priority="high" if kind == "attention" else "normal",
                title=title,
                summary=summary,
                observed_at=row["effective_from"] or row["created_at"],
                ask_query=_ask_query(title, str(row["record_key"]), sample),
                evidence=evidence,
            ))
            source_counts[source_key] += 1
        return items, sorted(set(rules))

    async def _research_items(
        self,
        subject: Subject,
        *,
        request_id: str,
        budget: int,
    ) -> tuple[list[IntelligenceItem], list[str]]:
        if budget <= 0 or not self.research.search_scope_allowed(subject, request_id):
            return [], []
        async with self.uow.factory() as session:
            metadata = [dict(row) for row in (await session.execute(
                text(RESEARCH_METADATA_SQL),
                {"scan_limit": METADATA_SCAN_LIMIT},
            )).mappings().all()]
            allowed = [
                row for row in metadata
                if self.research.source_searchable(
                    subject,
                    _research_source(row),
                    request_id,
                )
            ][: budget * 6]
            ids = [row["research_record_id"] for row in allowed]
            content_rows = (
                (await session.execute(text(RESEARCH_CONTENT_SQL), {"ids": ids}))
                .mappings().all()
                if ids else []
            )
            content = {row["research_record_id"]: dict(row) for row in content_rows}

        rules: list[str] = []
        items: list[IntelligenceItem] = []
        source_counts: Counter[str] = Counter()
        for row in allowed:
            if len(items) >= budget:
                break
            payload = content.get(row["research_record_id"])
            if payload is None:
                continue
            # The joined content query returns current source policy metadata.
            # Rechecking that object prevents a source revoked between the
            # metadata and content phases from being disclosed.
            source = _research_source(payload)
            if not self.research.source_searchable(subject, source, request_id):
                continue
            source_key = str(payload["stable_key"])
            if source_counts[source_key] >= SOURCE_QUOTA:
                continue
            summary = _clean(str(payload["searchable_text"]), SUMMARY_LIMIT)
            decision = self.dlp.inspect(
                summary,
                classification=str(payload["classification"]),
            )
            if not decision.allow or decision.text is None:
                rules.extend(decision.rule_ids)
                continue
            summary = decision.text
            title = _payload_title(
                payload["content"],
                str(payload["record_key"]),
            )
            title_decision = self.dlp.inspect(
                title,
                classification=str(payload["classification"]),
            )
            if not title_decision.allow or title_decision.text is None:
                rules.extend(title_decision.rule_ids)
                continue
            title = title_decision.text
            spans = list(payload["evidence_spans"] or [])
            if not spans:
                continue
            first = dict(spans[0])
            source_label = _clean(str(first.get("source_url") or source_key), 512)
            evidence = IntelligenceEvidence(
                zone_label="research",
                record_key=str(payload["record_key"]),
                source_key=source_key,
                source_label=source_label,
                content_sha256=str(payload["content_sha256"]),
                locator=dict(first.get("locator") or {}),
                research_record_id=row["research_record_id"],
                package_fingerprint=str(payload["fingerprint"]),
                tier=str(payload["tier"]),
                corroboration_state=str(payload["corroboration_state"]),
            )
            items.append(IntelligenceItem(
                item_id=_item_id("research", row["research_record_id"], "research"),
                zone_label="research",
                kind="research",
                priority="normal",
                title=title,
                summary=summary,
                observed_at=payload["created_at"],
                ask_query=_ask_query(title, str(payload["record_key"]), summary),
                evidence=evidence,
            ))
            source_counts[source_key] += 1
        return items, sorted(set(rules))

    async def briefing(
        self,
        subject: Subject,
        *,
        request_id: str,
        limit: int = 12,
    ) -> IntelligenceBriefing:
        limit = max(1, min(limit, MAX_LIMIT))
        # Keep Research useful but subordinate to the company SOT in a mixed
        # briefing. Empty SOT capacity is filled by Research below.
        research_budget = max(1, limit // 3)
        sot_items, sot_rules = await self._sot_items(
            subject,
            request_id=request_id,
            budget=limit - research_budget,
        )
        research_items, research_rules = await self._research_items(
            subject,
            request_id=request_id,
            budget=limit - len(sot_items),
        )
        items = sorted(
            [*sot_items, *research_items],
            key=lambda item: (
                0 if item.priority == "high" else 1,
                0 if item.zone_label == "sot" else 1,
                -item.observed_at.timestamp(),
                item.item_id,
            ),
        )[:limit]
        counts = Counter(item.kind for item in items)
        result = IntelligenceBriefing(
            generated_at=datetime.now(UTC),
            items=items,
            counts=IntelligenceCounts(
                updates=counts["update"],
                attention=counts["attention"],
                research=counts["research"],
            ),
            request_id=request_id,
        )
        async with self.uow.transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action="intelligence.briefing.view",
                result="success",
                reason_code="policy_scoped_live_briefing",
                request_id=request_id,
                resource_type="intelligence_briefing",
                details={
                    "returned_count": len(items),
                    "sot_count": sum(item.zone_label == "sot" for item in items),
                    "research_count": sum(
                        item.zone_label == "research" for item in items
                    ),
                    "dlp_rule_ids": sorted(set(sot_rules + research_rules)),
                },
            )
        return result
