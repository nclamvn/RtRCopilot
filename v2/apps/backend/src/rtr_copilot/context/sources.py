"""Shared SOT-ref authority seam. Actions uses metadata mode, never source text."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Subject, SubjectStatus
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.context.models import (
    ContextError,
    ContextGap,
    ResolvedSOTSource,
    SOTReference,
    SourceResolution,
    utc_now,
)
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.api import _effective_principal_ids
from rtr_copilot.rag.use_class import USE_CLASSES, UseClass, blocks
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.repositories.resources import ResourceRepository


async def current_context_subject(
    subject: Subject,
    factory: async_sessionmaker[AsyncSession],
) -> Subject:
    current = await PostgresSubjectRepository(factory).get_by_user_id(UUID(subject.user_id))
    if current is None or current.status != SubjectStatus.ACTIVE:
        raise ContextError("context_subject_unavailable", 403)
    return current


async def revalidate_sot_references(
    subject: Subject,
    references: Sequence[SOTReference],
    *,
    factory: async_sessionmaker[AsyncSession] | None = None,
    use_class: UseClass = "proposal",
    request_id: str,
    now: datetime | None = None,
    include_text: bool = False,
) -> SourceResolution:
    """Recheck exact current identities and purpose before any text load.

    There is no authorization cache. Missing/denied refs disclose no names or
    counts; stale/purpose gaps are emitted only after the record's view ACL.
    The caller must recheck immediately before disclosure/admission too.
    """
    if len(references) > 20 or use_class not in USE_CLASSES:
        raise ContextError("context_reference_budget", 400)
    uow = UnitOfWork(factory)
    if include_text:
        return await _resolve_text(
            subject,
            references,
            factory=uow.factory,
            use_class=use_class,
            request_id=request_id,
            now=now,
        )
    current = await current_context_subject(subject, uow.factory)
    instant = now or utc_now()
    sources: list[ResolvedSOTSource] = []
    gaps: set[str] = set()
    policy = PolicyEngine(StructuredAuditSink())
    async with uow.factory() as session:
        principals = await _effective_principal_ids(session, current)
        for ref in sorted(
            set(references),
            key=lambda item: (
                item.source_key,
                item.record_key,
                str(item.record_version_id),
                item.evidence_key or "",
            ),
        ):
            row = (
                (
                    await session.execute(
                        text("""
                SELECT r.record_id,r.owner_subject_id,r.classification,r.source_key,
                  r.current_version_id,r.lifecycle record_lifecycle,
                  rv.version_id,rv.content_sha256,rv.package_revision,rv.provenance_level,
                  rv.verification_state,rv.fact_state,rv.effective_from,rv.effective_to,
                  rv.freshness_due_at,rv.freshness_state,rv.lifecycle version_lifecycle,
                  p.lifecycle package_lifecycle
                FROM records r JOIN record_versions rv ON rv.record_id=r.record_id
                JOIN sot_packages p ON p.package_id=rv.package_id
                WHERE r.source_key=:source AND r.record_key=:key AND rv.version_id=:version
            """),
                        {
                            "source": ref.source_key,
                            "key": ref.record_key,
                            "version": ref.record_version_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                gaps.add("unavailable")
                continue
            effective = await ResourceRepository().effective_policy_attributes(
                session,
                row["record_id"],
                action="view",
                principal_ids=principals,
            )
            if (
                effective is None
                or effective[0].lifecycle_state != "active"
                or effective[0].source_zone != "sot"
                or not policy.decide(
                    current,
                    "view",
                    effective[0],
                    PolicyContext(request_id=request_id, now=instant),
                ).allow
            ):
                gaps.add("unavailable")
                continue
            if (
                row["record_lifecycle"] != "active"
                or row["version_lifecycle"] != "active"
                or row["package_lifecycle"] != "active"
                or row["current_version_id"] != ref.record_version_id
                or str(row["content_sha256"]) != ref.content_sha256
                or row["verification_state"] not in {"verified", "approved"}
                or row["fact_state"] not in {"verified", "approved"}
                or row["provenance_level"] == "claim"
            ):
                gaps.add("unavailable")
                continue
            if (
                row["freshness_state"] != "current"
                or row["effective_from"] > instant
                or (row["effective_to"] is not None and row["effective_to"] <= instant)
                or (row["freshness_due_at"] is not None and row["freshness_due_at"] <= instant)
            ):
                gaps.add("stale")
                continue
            # Project ONLY purpose keys; metadata mode never loads fact payloads.
            payload = await session.scalar(
                text("""
                SELECT jsonb_build_object('use_class',value_payload->'use_class',
                  'sot_tier',value_payload->'sot_tier')
                FROM record_versions WHERE version_id=:version
            """),
                {"version": ref.record_version_id},
            )
            if blocks(payload, requested=use_class, provenance_level=row["provenance_level"]):
                gaps.add("purpose_unavailable")
                continue
            evidence_keys = set(
                (
                    await session.execute(
                        text("""
                SELECT evidence_key FROM evidence_spans
                WHERE record_version_id=:version AND lifecycle='active' LIMIT 1000
            """),
                        {"version": ref.record_version_id},
                    )
                ).scalars()
            )
            if ref.evidence_key is not None and ref.evidence_key not in evidence_keys:
                gaps.add("unavailable")
                continue
            sources.append(
                ResolvedSOTSource(
                    reference=ref,
                    record_id=row["record_id"],
                    owner_subject_id=row["owner_subject_id"],
                    classification=effective[0].classification,
                    source_revision=row["package_revision"],
                    effective_from=row["effective_from"],
                    effective_to=row["effective_to"],
                    freshness_due_at=row["freshness_due_at"],
                    retrieved_at=instant,
                )
            )
    return SourceResolution(
        subject=current,
        sources=tuple(sources),
        gaps=tuple(ContextGap.model_validate({"code": code}) for code in sorted(gaps)),
    )


async def _resolve_text(
    subject: Subject,
    references: Sequence[SOTReference],
    *,
    factory: async_sessionmaker[AsyncSession],
    use_class: UseClass,
    request_id: str,
    now: datetime | None,
) -> SourceResolution:
    # Existing ACL SQL uses transaction-scoped now(). Close the metadata checkout
    # before checking newly effective revocations; never keep that old timestamp
    # across a content load, and never nest a checkout in the metadata phase.
    first = await revalidate_sot_references(
        subject,
        references,
        factory=factory,
        use_class=use_class,
        request_id=request_id,
        now=now,
    )
    current = first.subject
    gaps = {gap.code for gap in first.gaps}
    loaded: dict[SOTReference, str] = {}
    policy = PolicyEngine(StructuredAuditSink())
    for source in first.sources:
        ready = await revalidate_sot_references(
            current,
            [source.reference],
            factory=factory,
            use_class=use_class,
            request_id=request_id,
            now=now,
        )
        current = ready.subject
        gaps.update(gap.code for gap in ready.gaps)
        if not ready.sources:
            continue
        permitted = ready.sources[0]
        async with factory() as session:
            principals = await _effective_principal_ids(session, current)
            effective = await ResourceRepository().effective_policy_attributes(
                session,
                permitted.record_id,
                action="view",
                principal_ids=principals,
            )
            if (
                effective is None
                or effective[0].source_zone != "sot"
                or effective[0].lifecycle_state != "active"
                or not policy.decide(
                    current,
                    "view",
                    effective[0],
                    PolicyContext(request_id=request_id, now=now or utc_now()),
                ).allow
            ):
                gaps.add("unavailable")
                continue
            excerpt = (
                (
                    await session.execute(
                        text("""
                SELECT left(searchable_text,65536) AS excerpt,
                  length(searchable_text)>65536 AS clipped
                FROM record_versions WHERE version_id=:version
            """),
                        {"version": permitted.reference.record_version_id},
                    )
                )
                .mappings()
                .one()
            )
            loaded[permitted.reference] = excerpt["excerpt"]
            if excerpt["clipped"]:
                gaps.add("budget_limited")
    final = await revalidate_sot_references(
        current,
        tuple(loaded),
        factory=factory,
        use_class=use_class,
        request_id=request_id,
        now=now,
    )
    gaps.update(gap.code for gap in final.gaps)
    return SourceResolution(
        subject=final.subject,
        sources=tuple(
            source.model_copy(update={"text": loaded[source.reference]}) for source in final.sources
        ),
        gaps=tuple(ContextGap.model_validate({"code": code}) for code in sorted(gaps)),
    )
