"""Research registry, research-scoped retrieval and the graduation gate.

Zone separation is enforced by construction: research content lives only in
``research_records`` (its own namespace; the SOT index tables are never read
or written here) and every response model carries the constant ``research``
zone label. Retrieval follows the TIP-007 order guarantees — policy runs on
metadata before any content fetch, and policy is rechecked on the selected
rows before content is returned.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.config import Settings, get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.models import (
    GraduationProposal,
    PackageImportState,
    ResearchEvidenceSpan,
    ResearchPackage,
    ResearchRecord,
    ResearchSource,
    ResearchTier,
)
from rtr_copilot.governance.service import (
    decode_signed_cursor,
    encode_signed_cursor,
    policy,
)
from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository
from rtr_copilot.repositories.resources import CLASSIFICATION_TO_POLICY
from rtr_copilot.research.candidate import GraduationEvidence, build_candidate_package
from rtr_copilot.research.models import (
    CandidateClaim,
    GraduationProposalInput,
    GraduationProposalPage,
    ResearchCitation,
    ResearchEvidenceView,
    ResearchHit,
    ResearchImportResult,
    ResearchPackagePage,
    ResearchPackageView,
    ResearchRecordPage,
    ResearchRecordView,
    ResearchSearchResponse,
)
from rtr_copilot.research.package import (
    ResearchPackageError,
    ResearchPackageParser,
)
from rtr_copilot.sot.package import PackageError, canonical_json, sha256_bytes
from rtr_copilot.sot.service import PublishError, SOTPublishService

RESEARCH_SCAN_LIMIT = 1000
RESEARCH_SNIPPET_MAX_CHARS = 700

ProposalDecisionInput = Literal["approved", "rejected"]

RESEARCH_METADATA_SQL = """
    SELECT r.research_record_id, r.record_key, r.version_ordinal, r.tier,
      r.corroboration_state, r.content_sha256, r.created_at, r.package_id,
      p.fingerprint, s.source_id, s.stable_key, s.classification,
      s.owner_subject_id, s.lifecycle
    FROM research_records r
    JOIN research_packages p ON p.package_id = r.package_id
      AND p.import_state = 'imported'
    JOIN research_sources s ON s.source_id = p.source_id
      AND s.lifecycle = 'active'
    WHERE (cardinality(CAST(:tiers AS text[])) = 0
           OR r.tier = ANY(CAST(:tiers AS text[])))
      AND (CAST(:ids AS uuid[]) IS NULL
           OR r.research_record_id = ANY(CAST(:ids AS uuid[])))
    ORDER BY r.created_at, r.research_record_id
    LIMIT :scan_limit
"""
RESEARCH_CONTENT_SQL = """
    SELECT research_record_id, searchable_text, evidence_spans,
      ts_rank_cd(
        to_tsvector('simple', searchable_text),
        plainto_tsquery('simple', :query)
      ) AS lexical_score
    FROM research_records
    WHERE research_record_id = ANY(CAST(:ids AS uuid[]))
"""


class ResearchService:
    """Refinery import, research-only retrieval and the graduation gate."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.factory = factory
        self.uow = UnitOfWork(factory)
        self.repository = GovernanceRepository()
        self.parser = ResearchPackageParser(
            Path(self.settings.research_staging_root),
        )
        self.dlp = ProviderPolicy(mode="local")

    def _secret(self) -> str:
        return self.settings.sot_signing_secret.get_secret_value()

    def _source_attributes(self, source: ResearchSource) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=str(source.source_id),
            owner_id=str(source.owner_subject_id),
            classification=CLASSIFICATION_TO_POLICY[source.classification],
            source_zone="research",
            lifecycle_state=source.lifecycle,
        )

    def source_visible(
        self,
        subject: Subject,
        source: ResearchSource,
        request_id: str,
    ) -> bool:
        """Owner or curator, and always inside classification clearance."""
        attributes = self._source_attributes(source)
        context = PolicyContext(request_id=request_id)
        if not policy.decide(subject, "view", attributes, context).allow:
            return False
        if str(source.owner_subject_id) == subject.user_id:
            return True
        return policy.decide(subject, "curate", attributes, context).allow

    def source_searchable(
        self,
        subject: Subject,
        source: ResearchSource,
        request_id: str,
    ) -> bool:
        """Research queries are a separately authorized scope (AC-08)."""
        if not self.source_visible(subject, source, request_id):
            return False
        return policy.decide(
            subject,
            "search",
            self._source_attributes(source),
            PolicyContext(request_id=request_id),
        ).allow

    def _curator_gate(self, subject: Subject, request_id: str) -> None:
        attributes = ResourceAttributes(
            classification="internal",
            source_zone="research",
        )
        context = PolicyContext(request_id=request_id)
        allowed = (
            policy.decide(subject, "curate", attributes, context).allow
            or policy.decide(subject, "manage_policies", attributes, context).allow
        )
        if not allowed:
            raise PermissionError("curator_required")

    async def _audit(
        self,
        *,
        actor: uuid.UUID,
        action: str,
        result: str,
        code: str,
        request_id: str,
        resource_type: str,
        details: dict[str, Any],
    ) -> None:
        async with self.uow.transaction() as session:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action=action,
                result=result,
                reason_code=code,
                request_id=request_id,
                resource_type=resource_type,
                details=details,
            )

    def _package_view(
        self,
        package: ResearchPackage,
        source: ResearchSource,
    ) -> ResearchPackageView:
        return ResearchPackageView(
            package_id=package.package_id,
            source_key=source.stable_key,
            fingerprint=package.fingerprint,
            payload_sha256=package.payload_sha256,
            captured_at=package.captured_at,
            snapshot_scope=package.snapshot_scope,
            adapter_version=package.adapter_version,
            tier_composition=package.tier_composition,
            import_state=package.import_state,
            rejection_code=package.rejection_code,
            record_count=package.record_count,
            received_at=package.received_at,
            imported_at=package.imported_at,
        )

    def _record_view(
        self,
        record: ResearchRecord,
        package: ResearchPackage,
        source: ResearchSource,
    ) -> ResearchRecordView:
        return ResearchRecordView(
            research_record_id=record.research_record_id,
            package_id=record.package_id,
            package_fingerprint=package.fingerprint,
            source_key=source.stable_key,
            record_key=record.record_key,
            version_ordinal=record.version_ordinal,
            tier=record.tier,
            content=record.content,
            searchable_text=record.searchable_text,
            evidence=[
                ResearchEvidenceView(
                    source_url=span.source_url,
                    locator=span.locator,
                    quoted_text=span.quoted_text,
                    checksum=span.checksum,
                )
                for span in record.evidence_spans
            ],
            corroboration_state=record.corroboration_state,
            content_sha256=record.content_sha256,
            created_at=record.created_at,
        )

    async def _reject_registered(
        self,
        actor: uuid.UUID,
        request_id: str,
        package_id: uuid.UUID,
        *,
        code: str,
        details: dict[str, Any],
    ) -> None:
        async with self.uow.transaction() as session:
            await self.repository.set_package_state(
                session,
                package_id,
                from_state="validating",
                to_state="rejected",
                rejection_code=code,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="research.package.import",
                result="deny",
                reason_code=code,
                request_id=request_id,
                resource_type="research_package",
                details=details,
            )

    async def import_package(
        self,
        subject: Subject,
        staging_name: str,
        *,
        request_id: str,
    ) -> ResearchImportResult:
        """Quarantine-parse, validate and atomically import one package.

        Any contract violation rejects the whole package with a typed,
        audited error and leaves zero research record rows (AC-05).
        Identical fingerprints re-import idempotently.
        """
        actor = uuid.UUID(subject.user_id)
        self._curator_gate(subject, request_id)
        try:
            staged = self.parser.stage(staging_name, now=datetime.now(UTC))
        except ResearchPackageError as error:
            await self._audit(
                actor=actor,
                action="research.package.import",
                result="deny",
                code=error.code,
                request_id=request_id,
                resource_type="research_package",
                details={"staging_name": staging_name},
            )
            raise GovernanceError(error.code) from None
        manifest = staged.manifest
        async with self.uow.factory() as session:
            source = await self.repository.get_source_by_key(
                session,
                manifest.source_key,
            )
        if source is None or not self.source_visible(subject, source, request_id):
            await self._audit(
                actor=actor,
                action="research.package.import",
                result="deny",
                code="research_source_unknown",
                request_id=request_id,
                resource_type="research_package",
                details={
                    "staging_name": staging_name,
                    "source_key": manifest.source_key,
                },
            )
            raise GovernanceError("research_source_unknown")
        if source.lifecycle != "active":
            await self._audit(
                actor=actor,
                action="research.package.import",
                result="deny",
                code="research_source_inactive",
                request_id=request_id,
                resource_type="research_package",
                details={
                    "staging_name": staging_name,
                    "source_key": manifest.source_key,
                },
            )
            raise GovernanceError("research_source_inactive")
        async with self.uow.transaction() as session:
            intake = await self.repository.register_package(
                session,
                ResearchPackage(
                    source_id=source.source_id,
                    fingerprint=manifest.fingerprint,
                    payload_sha256=manifest.payload_sha256,
                    snapshot_manifest=manifest.model_dump(mode="json"),
                    captured_at=manifest.captured_at,
                    snapshot_scope=manifest.scope,
                    adapter_version=manifest.adapter_version,
                    importer_subject_id=actor,
                ),
            )
            package = intake.package
            if package.import_state == "imported":
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=actor,
                    action="research.package.import",
                    result="success",
                    reason_code="idempotent_reimport",
                    request_id=request_id,
                    resource_type="research_package",
                    details={
                        "package_id": str(package.package_id),
                        "fingerprint": package.fingerprint,
                    },
                )
            elif package.import_state == "received":
                package = await self.repository.set_package_state(
                    session,
                    package.package_id,
                    from_state="received",
                    to_state="validating",
                )
        if intake.package.import_state == "imported":
            return ResearchImportResult(
                package=self._package_view(intake.package, source),
                created=False,
                idempotent=True,
            )
        if intake.package.import_state == "rejected":
            code = intake.package.rejection_code or "package_rejected"
            await self._audit(
                actor=actor,
                action="research.package.import",
                result="deny",
                code=code,
                request_id=request_id,
                resource_type="research_package",
                details={
                    "package_id": str(intake.package.package_id),
                    "fingerprint": intake.package.fingerprint,
                    "idempotent": True,
                },
            )
            raise GovernanceError(code)
        reject_details = {
            "staging_name": staging_name,
            "package_id": str(package.package_id),
            "fingerprint": package.fingerprint,
        }
        try:
            parsed_records = staged.load_records()
        except ResearchPackageError as error:
            await self._reject_registered(
                actor,
                request_id,
                package.package_id,
                code=error.code,
                details=reject_details,
            )
            raise GovernanceError(error.code) from None
        composition: dict[str, int] = {}
        rows: list[ResearchRecord] = []
        for item in parsed_records:
            composition[item.tier] = composition.get(item.tier, 0) + 1
            rows.append(ResearchRecord(
                package_id=package.package_id,
                record_key=item.record_key,
                version_ordinal=item.version_ordinal,
                tier=item.tier,
                content=item.content,
                searchable_text=item.searchable_text,
                evidence_spans=[
                    ResearchEvidenceSpan(
                        source_url=span.source_url,
                        locator=span.locator,
                        quoted_text=span.quoted_text,
                        checksum=span.checksum,
                    )
                    for span in item.evidence
                ],
                content_sha256=item.content_sha256,
            ))
        try:
            async with self.uow.transaction() as session:
                for row in rows:
                    await self.repository.insert_record(session, row)
                package = await self.repository.set_package_state(
                    session,
                    package.package_id,
                    from_state="validating",
                    to_state="imported",
                    record_count=len(rows),
                    tier_composition=composition,
                )
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=actor,
                    action="research.package.import",
                    result="success",
                    reason_code="package_imported",
                    request_id=request_id,
                    resource_type="research_package",
                    details={
                        "package_id": str(package.package_id),
                        "fingerprint": package.fingerprint,
                        "source_key": source.stable_key,
                        "record_count": len(rows),
                        "tier_composition": composition,
                    },
                )
        except IntegrityError:
            await self._reject_registered(
                actor,
                request_id,
                package.package_id,
                code="record_version_conflict",
                details=reject_details,
            )
            raise GovernanceError("record_version_conflict") from None
        return ResearchImportResult(
            package=self._package_view(package, source),
            created=intake.created,
            idempotent=False,
        )

    async def list_packages(
        self,
        subject: Subject,
        *,
        request_id: str,
        import_state: PackageImportState | None = None,
        source_key: str | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> ResearchPackagePage:
        limit = max(1, min(limit, 100))
        boundary = (
            decode_signed_cursor("research:packages", cursor, self._secret())
            if cursor
            else None
        )
        async with self.uow.factory() as session:
            sources = {
                source.source_id: source
                for source in await self.repository.list_sources(session)
            }
            packages = await self.repository.list_packages(
                session,
                import_state=import_state,
            )
        visible = [
            package
            for package in packages
            if (source := sources.get(package.source_id)) is not None
            and (source_key is None or source.stable_key == source_key)
            and self.source_visible(subject, source, request_id)
        ]
        if boundary is not None:
            visible = [
                package
                for package in visible
                if (package.received_at, package.package_id) < boundary
            ]
        page = visible[:limit]
        next_cursor = (
            encode_signed_cursor(
                "research:packages",
                page[-1].received_at,
                page[-1].package_id,
                self._secret(),
            )
            if len(visible) > limit
            else None
        )
        return ResearchPackagePage(
            items=[
                self._package_view(package, sources[package.source_id])
                for package in page
            ],
            next_cursor=next_cursor,
        )

    async def _visible_package(
        self,
        session: AsyncSession,
        subject: Subject,
        package_id: uuid.UUID,
        request_id: str,
    ) -> tuple[ResearchPackage, ResearchSource]:
        """404-discipline lookup: missing and denied are indistinguishable."""
        package = await self.repository.get_package(session, package_id)
        source = (
            await self.repository.get_source(session, package.source_id)
            if package is not None
            else None
        )
        if (
            package is None
            or source is None
            or not self.source_visible(subject, source, request_id)
        ):
            raise GovernanceError("research_package_not_found")
        return package, source

    async def package_detail(
        self,
        subject: Subject,
        package_id: uuid.UUID,
        *,
        request_id: str,
    ) -> ResearchPackageView:
        async with self.uow.factory() as session:
            package, source = await self._visible_package(
                session,
                subject,
                package_id,
                request_id,
            )
        return self._package_view(package, source)

    async def list_records(
        self,
        subject: Subject,
        package_id: uuid.UUID,
        *,
        request_id: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> ResearchRecordPage:
        limit = max(1, min(limit, 100))
        boundary = (
            decode_signed_cursor("research:records", cursor, self._secret())
            if cursor
            else None
        )
        async with self.uow.factory() as session:
            package, source = await self._visible_package(
                session,
                subject,
                package_id,
                request_id,
            )
            records = await self.repository.list_records(session, package_id)
        records.sort(key=lambda item: (item.created_at, item.research_record_id))
        if boundary is not None:
            records = [
                record
                for record in records
                if (record.created_at, record.research_record_id) > boundary
            ]
        page = records[:limit]
        next_cursor = (
            encode_signed_cursor(
                "research:records",
                page[-1].created_at,
                page[-1].research_record_id,
                self._secret(),
            )
            if len(records) > limit
            else None
        )
        await self._audit(
            actor=uuid.UUID(subject.user_id),
            action="research.record.view",
            result="success",
            code="records_listed",
            request_id=request_id,
            resource_type="research_record",
            details={
                "package_id": str(package_id),
                "returned_count": len(page),
            },
        )
        return ResearchRecordPage(
            items=[self._record_view(record, package, source) for record in page],
            next_cursor=next_cursor,
        )

    async def record_detail(
        self,
        subject: Subject,
        research_record_id: uuid.UUID,
        *,
        request_id: str,
    ) -> ResearchRecordView:
        async with self.uow.factory() as session:
            record = await self.repository.get_record(session, research_record_id)
            package = (
                await self.repository.get_package(session, record.package_id)
                if record is not None
                else None
            )
            source = (
                await self.repository.get_source(session, package.source_id)
                if package is not None
                else None
            )
        if (
            record is None
            or package is None
            or source is None
            or not self.source_visible(subject, source, request_id)
        ):
            raise GovernanceError("research_record_not_found")
        await self._audit(
            actor=uuid.UUID(subject.user_id),
            action="research.record.view",
            result="success",
            code="record_disclosed",
            request_id=request_id,
            resource_type="research_record",
            details={
                "research_record_id": str(research_record_id),
                "package_id": str(package.package_id),
            },
        )
        return self._record_view(record, package, source)

    async def _search_metadata(
        self,
        session: AsyncSession,
        *,
        tiers: list[str],
        ids: list[uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        rows = (await session.execute(text(RESEARCH_METADATA_SQL), {
            "tiers": tiers,
            "ids": ids,
            "scan_limit": RESEARCH_SCAN_LIMIT,
        })).mappings().all()
        return [dict(row) for row in rows]

    def _search_allowed(
        self,
        subject: Subject,
        rows: list[dict[str, Any]],
        request_id: str,
    ) -> set[uuid.UUID]:
        allowed: set[uuid.UUID] = set()
        for row in rows:
            source = ResearchSource(
                source_id=row["source_id"],
                stable_key=row["stable_key"],
                display_name="research source",
                origin="refinery",
                owner_subject_id=row["owner_subject_id"],
                classification=row["classification"],
                lifecycle=row["lifecycle"],
            )
            if self.source_searchable(subject, source, request_id):
                allowed.add(row["research_record_id"])
        return allowed

    async def search(
        self,
        subject: Subject,
        query: str,
        *,
        request_id: str,
        tiers: list[ResearchTier] | None = None,
        limit: int = 10,
    ) -> ResearchSearchResponse:
        """Research-scoped retrieval: explicit scope, labeled results only.

        Order guarantees mirror TIP-007: policy over metadata first, content
        fetched only for allowed rows, policy rechecked on the selected rows
        before anything is returned, DLP on every disclosed snippet.
        """
        limit = max(1, min(limit, 50))
        tier_filter = [str(tier) for tier in tiers or []]
        if len(query.encode()) > self.settings.rag_query_max_bytes:
            raise GovernanceError("query_budget_exceeded")
        normalized = normalize_query(query)
        if not normalized:
            raise GovernanceError("query_empty_after_normalization")
        dlp_rule_ids: list[str] = []
        async with self.uow.factory() as session:
            metadata = await self._search_metadata(session, tiers=tier_filter)
            allowed = self._search_allowed(subject, metadata, request_id)
            hits: list[ResearchHit] = []
            if allowed:
                content_rows = (await session.execute(
                    text(RESEARCH_CONTENT_SQL),
                    {"ids": list(allowed), "query": normalized},
                )).mappings().all()
                metadata_by_id = {
                    row["research_record_id"]: row for row in metadata
                }
                scored = sorted(
                    (
                        dict(row)
                        for row in content_rows
                        if float(row["lexical_score"]) > 0
                    ),
                    key=lambda row: (
                        -float(row["lexical_score"]),
                        str(metadata_by_id[row["research_record_id"]]["record_key"]),
                    ),
                )[:limit]
                recheck_rows = await self._search_metadata(
                    session,
                    tiers=tier_filter,
                    ids=[row["research_record_id"] for row in scored],
                )
                still_allowed = self._search_allowed(
                    subject,
                    recheck_rows,
                    request_id,
                )
                for row in scored:
                    record_id = row["research_record_id"]
                    if record_id not in still_allowed:
                        continue
                    meta = metadata_by_id[record_id]
                    decision = self.dlp.inspect(
                        str(row["searchable_text"]),
                        classification=str(meta["classification"]),
                    )
                    if not decision.allow or decision.text is None:
                        dlp_rule_ids.extend(decision.rule_ids)
                        continue
                    snippet = decision.text[:RESEARCH_SNIPPET_MAX_CHARS]
                    spans = list(row["evidence_spans"])
                    hits.append(ResearchHit(
                        research_record_id=record_id,
                        record_key=meta["record_key"],
                        tier=meta["tier"],
                        snippet=snippet,
                        lexical_score=float(row["lexical_score"]),
                        citation=ResearchCitation(
                            research_record_id=record_id,
                            record_key=meta["record_key"],
                            version_ordinal=meta["version_ordinal"],
                            tier=meta["tier"],
                            source_key=meta["stable_key"],
                            package_fingerprint=meta["fingerprint"],
                            content_sha256=str(meta["content_sha256"]),
                            corroboration_state=meta["corroboration_state"],
                            evidence_checksums=[
                                str(span["checksum"]) for span in spans
                            ],
                        ),
                    ))
        await self._audit(
            actor=uuid.UUID(subject.user_id),
            action="research.search",
            result="success",
            code="research_scope_results",
            request_id=request_id,
            resource_type="research_search",
            details={
                "returned_count": len(hits),
                "query_fingerprint": sha256_bytes(normalized.encode()),
                "tier_filter": tier_filter,
                "dlp_rule_ids": sorted(set(dlp_rule_ids)),
            },
        )
        return ResearchSearchResponse(results=hits, request_id=request_id)

    async def _graduatable_records(
        self,
        session: AsyncSession,
        subject: Subject,
        record_ids: list[uuid.UUID],
        request_id: str,
    ) -> list[GraduationEvidence]:
        """Missing, unimported, inactive-source and policy-denied records all
        fail with the identical typed code, so probing leaks nothing."""
        evidence: list[GraduationEvidence] = []
        for record_id in dict.fromkeys(record_ids):
            record = await self.repository.get_record(session, record_id)
            package = (
                await self.repository.get_package(session, record.package_id)
                if record is not None
                else None
            )
            source = (
                await self.repository.get_source(session, package.source_id)
                if package is not None
                else None
            )
            if (
                record is None
                or package is None
                or package.import_state != "imported"
                or source is None
                or source.lifecycle != "active"
                or not self.source_visible(subject, source, request_id)
            ):
                raise GovernanceError("research_record_not_graduatable")
            evidence.append((record, package, source))
        return evidence

    def proposal_visible(
        self,
        subject: Subject,
        proposal: GraduationProposal,
        request_id: str,
    ) -> bool:
        caller = uuid.UUID(subject.user_id)
        if caller in {proposal.proposer_subject_id, proposal.decided_by}:
            return True
        return policy.decide(
            subject,
            "curate",
            ResourceAttributes(classification="internal", source_zone="research"),
            PolicyContext(request_id=request_id),
        ).allow

    async def propose(
        self,
        subject: Subject,
        payload: GraduationProposalInput,
        *,
        request_id: str,
    ) -> GraduationProposal:
        actor = uuid.UUID(subject.user_id)
        self._curator_gate(subject, request_id)
        async with self.uow.transaction() as session:
            await self._graduatable_records(
                session,
                subject,
                payload.research_record_ids,
                request_id,
            )
            proposal = await self.repository.create_proposal(
                session,
                research_record_ids=payload.research_record_ids,
                claim_draft=payload.claim.model_dump(mode="json"),
                target_record_key=payload.target_record_key,
                proposer_subject_id=actor,
                rationale=payload.rationale,
                supersedes_proposal_id=payload.supersedes_proposal_id,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.graduation.propose",
                result="success",
                reason_code="proposal_drafted",
                request_id=request_id,
                resource_type="graduation_proposal",
                details={
                    "proposal_id": str(proposal.proposal_id),
                    "target_record_key": payload.target_record_key,
                    "research_record_ids": [
                        str(item) for item in proposal.research_record_ids
                    ],
                    "supersedes_proposal_id": (
                        str(payload.supersedes_proposal_id)
                        if payload.supersedes_proposal_id
                        else None
                    ),
                },
            )
        return proposal

    async def list_proposals(
        self,
        subject: Subject,
        *,
        request_id: str,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> GraduationProposalPage:
        limit = max(1, min(limit, 100))
        boundary = (
            decode_signed_cursor("graduation:proposals", cursor, self._secret())
            if cursor
            else None
        )
        async with self.uow.factory() as session:
            proposals = await self.repository.list_proposals(session, state=state)
        visible = [
            proposal
            for proposal in proposals
            if self.proposal_visible(subject, proposal, request_id)
        ]
        if boundary is not None:
            visible = [
                proposal
                for proposal in visible
                if (proposal.proposed_at, proposal.proposal_id) < boundary
            ]
        page = visible[:limit]
        next_cursor = (
            encode_signed_cursor(
                "graduation:proposals",
                page[-1].proposed_at,
                page[-1].proposal_id,
                self._secret(),
            )
            if len(visible) > limit
            else None
        )
        return GraduationProposalPage(items=page, next_cursor=next_cursor)

    async def proposal_detail(
        self,
        subject: Subject,
        proposal_id: uuid.UUID,
        *,
        request_id: str,
    ) -> GraduationProposal:
        async with self.uow.factory() as session:
            proposal = await self.repository.get_proposal(session, proposal_id)
        if proposal is None or not self.proposal_visible(
            subject,
            proposal,
            request_id,
        ):
            raise GovernanceError("proposal_not_found")
        return proposal

    def _attestation_hash(
        self,
        proposal: GraduationProposal,
        *,
        decision: str,
        decider: uuid.UUID,
        reason: str,
    ) -> str:
        return sha256_bytes(canonical_json({
            "proposal_id": str(proposal.proposal_id),
            "decision": decision,
            "decider": str(decider),
            "reason": reason,
            "research_record_ids": sorted(
                str(item) for item in proposal.research_record_ids
            ),
            "claim_sha256": sha256_bytes(canonical_json(proposal.claim_draft)),
        }))

    async def decide(
        self,
        subject: Subject,
        proposal_id: uuid.UUID,
        *,
        decision: ProposalDecisionInput,
        reason: str,
        request_id: str,
    ) -> GraduationProposal:
        """Separation-of-duties decision; approval submits a draft candidate.

        The repository enforces proposer != decider and single-decision under
        row lock, so concurrent, duplicate and stale decisions fail closed;
        every denial is audited (AC-10). Approval stages a claim package into
        the TIP-006 pipeline — nothing activates here (AC-09).
        """
        actor = uuid.UUID(subject.user_id)
        async with self.uow.factory() as session:
            proposal = await self.repository.get_proposal(session, proposal_id)
        if proposal is None or not self.proposal_visible(
            subject,
            proposal,
            request_id,
        ):
            raise GovernanceError("proposal_not_found")
        self._curator_gate(subject, request_id)
        claim: CandidateClaim | None = None
        evidence: list[GraduationEvidence] = []
        try:
            async with self.uow.transaction() as session:
                if decision == "approved":
                    evidence = await self._graduatable_records(
                        session,
                        subject,
                        proposal.research_record_ids,
                        request_id,
                    )
                    try:
                        claim = CandidateClaim.model_validate(proposal.claim_draft)
                    except ValidationError:
                        raise GovernanceError("graduation_claim_invalid") from None
                decided = await self.repository.decide_proposal(
                    session,
                    proposal_id,
                    decider_subject_id=actor,
                    decision=decision,
                    decision_reason=reason,
                    attestation_hash=self._attestation_hash(
                        proposal,
                        decision=decision,
                        decider=actor,
                        reason=reason,
                    ),
                )
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=actor,
                    action="governance.graduation.decide",
                    result="success",
                    reason_code=f"proposal_{decision}",
                    request_id=request_id,
                    resource_type="graduation_proposal",
                    details={
                        "proposal_id": str(proposal_id),
                        "decision": decision,
                        "attestation_hash": decided.attestation_hash,
                    },
                )
        except GovernanceError as error:
            await self._audit(
                actor=actor,
                action="governance.graduation.decide",
                result="deny",
                code=error.code,
                request_id=request_id,
                resource_type="graduation_proposal",
                details={"proposal_id": str(proposal_id), "decision": decision},
            )
            raise
        if decision == "rejected" or claim is None:
            return decided
        return await self._submit_candidate(
            actor,
            decided,
            claim,
            evidence,
            request_id=request_id,
        )

    async def _submit_candidate(
        self,
        actor: uuid.UUID,
        proposal: GraduationProposal,
        claim: CandidateClaim,
        evidence: list[GraduationEvidence],
        *,
        request_id: str,
    ) -> GraduationProposal:
        """Stage the draft candidate into the SOT publish pipeline (no bypass)."""
        try:
            staging_name = build_candidate_package(
                Path(self.settings.sot_staging_root),
                proposal=proposal,
                claim=claim,
                evidence=evidence,
                decider_id=actor,
                signing_secret=self._secret(),
                now=datetime.now(UTC),
            )
            staged = await SOTPublishService(
                self.settings,
                factory=self.factory,
            ).stage(
                staging_name,
                actor_id=actor,
                request_id=request_id,
            )
        except (PackageError, PublishError, OSError) as error:
            await self._audit(
                actor=actor,
                action="governance.graduation.submit",
                result="deny",
                code=str(getattr(error, "code", "staging_failed")),
                request_id=request_id,
                resource_type="graduation_proposal",
                details={"proposal_id": str(proposal.proposal_id)},
            )
            raise GovernanceError("graduation_submission_failed") from None
        async with self.uow.transaction() as session:
            submitted = await self.repository.attach_publish_submission(
                session,
                proposal.proposal_id,
                publish_package_id=staged.package_id,
            )
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor,
                action="governance.graduation.submit",
                result="success",
                reason_code="draft_candidate_staged",
                request_id=request_id,
                resource_type="graduation_proposal",
                details={
                    "proposal_id": str(proposal.proposal_id),
                    "publish_package_id": str(staged.package_id),
                    "publish_run_id": str(staged.run_id),
                    "source_key": staged.source_key,
                    "state": staged.state,
                    "research_record_ids": [
                        str(item) for item in proposal.research_record_ids
                    ],
                    "package_fingerprints": sorted({
                        package.fingerprint for _, package, _ in evidence
                    }),
                },
            )
        return submitted
