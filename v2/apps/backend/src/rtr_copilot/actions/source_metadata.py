"""Strict Action-v2 metadata resolver; unsupported batches use the shared seam."""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.actions.authority import (
    LEAF_ACL,
    MEMBERSHIPS,
    UUID_PATTERN,
    clock_retry_allowed,
    leaf_attributes,
    projection,
)
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.context.models import (
    ContextError,
    ContextGap,
    ResolvedSOTSource,
    SOTReference,
    SourceResolution,
    utc_now,
)
from rtr_copilot.rag.use_class import USE_CLASSES, UseClass, blocks


class UnsupportedSourceTopology(RuntimeError):
    """No partial result or policy decision is usable; close and resolve fresh."""


class InitialClockDenied(RuntimeError):
    """Discard the owned initial transaction, never substitute permission."""


async def resolve_action_sources(
    subject: Subject, references: Sequence[SOTReference], *,
    factory: async_sessionmaker[AsyncSession], use_class: UseClass,
    request_id: str, now: datetime | None = None,
    initial_session: AsyncSession | None = None,
) -> SourceResolution:
    if len(references) > 20 or use_class not in USE_CLASSES:
        raise ContextError("context_reference_budget", 400)
    refs = sorted(set(references), key=lambda r: (
        r.source_key, r.record_key, str(r.record_version_id), r.evidence_key or ""))
    if initial_session is None:
        async with factory() as session:
            row = await _source_row(session, subject, refs)
    else:
        row = await _source_row(initial_session, subject, refs)
    return _resolve_source_row(row, subject, references, refs, use_class, request_id, now,
                               clock_retry=initial_session is not None)


async def _source_row(session: AsyncSession, subject: Subject,
                      refs: Sequence[SOTReference]) -> Any:
    return (await session.execute(text("WITH " + MEMBERSHIPS + """
          , refs AS (SELECT * FROM jsonb_to_recordset(CAST(:refs AS jsonb))
            AS q(source_key text,record_key text,record_version_id uuid,
                 content_sha256 text,evidence_key text)), joined AS (
            SELECT q.*,r.record_id,r.owner_subject_id,r.current_version_id,
              r.lifecycle record_lifecycle,rv.version_id,rv.content_sha256 actual_checksum,
              rv.package_revision,rv.provenance_level,rv.verification_state,rv.fact_state,
              rv.effective_from,rv.effective_to,rv.freshness_due_at,rv.freshness_state,
              rv.lifecycle version_lifecycle,p.lifecycle package_lifecycle,
              jsonb_build_object('use_class',rv.value_payload->'use_class',
                'sot_tier',rv.value_payload->'sot_tier') purpose,
              to_jsonb(res) resource,r.record_id resource_id,'view'::text action,
              ev.row_count evidence_count,ev.present evidence_present
            FROM refs q LEFT JOIN records r
              ON r.source_key=q.source_key AND r.record_key=q.record_key
            LEFT JOIN record_versions rv
              ON rv.record_id=r.record_id AND rv.version_id=q.record_version_id
            LEFT JOIN sot_packages p ON p.package_id=rv.package_id
            LEFT JOIN resources res ON res.resource_id=r.record_id
            LEFT JOIN LATERAL (
              SELECT count(*) row_count,COALESCE(bool_or(evidence_key=q.evidence_key),false) present
              FROM (SELECT evidence_key FROM evidence_spans
                WHERE record_version_id=rv.version_id AND lifecycle='active'
                  AND q.evidence_key IS NOT NULL LIMIT 1001) bounded
            ) ev ON true), leaves AS (SELECT q.*, """ + LEAF_ACL + """
            FROM joined q)
          SELECT (SELECT to_jsonb(i) FROM identity i) identity,
            ARRAY(SELECT id FROM pm) principal_ids,
            COALESCE((SELECT jsonb_agg(to_jsonb(l)) FROM leaves l),'[]'::jsonb) leaves
        """), {"actor": uuid.UUID(subject.user_id), "uuid_pattern": UUID_PATTERN,
                "refs": json.dumps([r.model_dump(mode="json") for r in refs])})).mappings().one()


def _resolve_source_row(row: Any, subject: Subject, references: Sequence[SOTReference],
                        refs: Sequence[SOTReference], use_class: UseClass, request_id: str,
                        now: datetime | None, *, clock_retry: bool) -> SourceResolution:
    # Borrowed callers propagate the whole-attempt signal to their owner, which
    # CLOSES before a fresh fallback. Default callers already closed above.
    # Check the whole batch first; no subset result can leak across fallback.
    if any((leaf["resource"] is not None
            and leaf["resource"]["resource_type"] != "record")
           or (leaf["evidence_key"] is not None and leaf["evidence_count"] > 1000)
           for leaf in row["leaves"]):
        raise UnsupportedSourceTopology()
    try:
        current = projection(row)
    except ActionError as error:
        raise ContextError("context_subject_unavailable", 403) from error
    instant = now or utc_now()
    if clock_retry and current.subject.security_version != subject.security_version:
        raise ActionError("authority_changed", 403)
    policy = PolicyEngine(StructuredAuditSink())
    sources: list[ResolvedSOTSource] = []
    gaps: set[str] = set()
    hard_failure = len(references) != len(refs)
    clock_denied = False
    by_ref = {(r.source_key, r.record_key, str(r.record_version_id),
               r.content_sha256, r.evidence_key): r
              for r in refs}
    for leaf in row["leaves"]:
        ref = by_ref[(leaf["source_key"], leaf["record_key"],
                      leaf["record_version_id"], leaf["content_sha256"], leaf["evidence_key"])]
        if leaf["version_id"] is None:
            gaps.add("unavailable")
            hard_failure = True
            continue
        attributes = leaf_attributes(leaf, current.principal_ids)
        if (attributes is None or attributes.lifecycle_state != "active"
                or attributes.source_zone != "sot"
                or not policy.decide(current.subject, "view", attributes,
                                     PolicyContext(request_id=request_id, now=instant)).allow):
            gaps.add("unavailable")
            if (clock_retry and clock_retry_allowed(leaf, current)
                    and _source_gap(leaf, ref, instant, use_class) is None):
                clock_denied = True
            else:
                hard_failure = True
            continue
        gap = _source_gap(leaf, ref, instant, use_class)
        if gap is not None:
            gaps.add(gap)
            hard_failure = True
            continue
        effective_from = datetime.fromisoformat(leaf["effective_from"])
        effective_to = (datetime.fromisoformat(leaf["effective_to"])
                        if leaf["effective_to"] is not None else None)
        freshness_due_at = (datetime.fromisoformat(leaf["freshness_due_at"])
                            if leaf["freshness_due_at"] is not None else None)
        sources.append(ResolvedSOTSource(
            reference=ref, record_id=leaf["record_id"], owner_subject_id=leaf["owner_subject_id"],
            classification=attributes.classification, source_revision=leaf["package_revision"],
            effective_from=effective_from, effective_to=effective_to,
            freshness_due_at=freshness_due_at, retrieved_at=instant,
        ))
    if clock_denied and not hard_failure:
        raise InitialClockDenied()
    # SQL row order is not authority; preserve the shared stable reference order.
    sources.sort(key=lambda s: (s.reference.source_key, s.reference.record_key,
                               str(s.reference.record_version_id), s.reference.evidence_key or ""))
    return SourceResolution(
        subject=current.subject, sources=tuple(sources),
        gaps=tuple(ContextGap.model_validate({"code": c}) for c in sorted(gaps)),
    )


def _source_gap(leaf: Any, ref: SOTReference, instant: datetime,
                use_class: UseClass) -> str | None:
    """Full metadata validity before any clock retry; original gap ordering."""
    if (any(leaf[key] != "active" for key in
            ("record_lifecycle", "version_lifecycle", "package_lifecycle"))
            or leaf["current_version_id"] != str(ref.record_version_id)
            or leaf["actual_checksum"] != ref.content_sha256
            or leaf["verification_state"] not in {"verified", "approved"}
            or leaf["fact_state"] not in {"verified", "approved"}
            or leaf["provenance_level"] == "claim"):
        return "unavailable"
    if (leaf["freshness_state"] != "current"
            or datetime.fromisoformat(leaf["effective_from"]) > instant
            or any(leaf[key] is not None and datetime.fromisoformat(leaf[key]) <= instant
                   for key in ("effective_to", "freshness_due_at"))):
        return "stale"
    if blocks(leaf["purpose"], requested=use_class, provenance_level=leaf["provenance_level"]):
        return "purpose_unavailable"
    if ref.evidence_key is not None and not leaf["evidence_present"]:
        return "unavailable"
    return None
