import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.config import Settings, get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository
from rtr_copilot.sot.models import (
    ActiveEvidence,
    ActiveRecord,
    ParsedPackage,
    PublishResult,
    ValidationReport,
)
from rtr_copilot.sot.package import (
    PackageError,
    PackageParser,
    freshness_state,
    validate_package,
    verify_attestation,
)


class PublishError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SOTPublishService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        clock: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.uow = UnitOfWork(factory)
        self.parser = PackageParser(Path(self.settings.sot_staging_root))
        self.clock = clock or (lambda: datetime.now(UTC))

    async def _audit(
        self,
        session: AsyncSession,
        *,
        actor_id: uuid.UUID,
        action: str,
        result: str,
        code: str,
        request_id: str,
        details: dict[str, Any],
    ) -> uuid.UUID:
        return await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=actor_id,
            action=action,
            result=result,
            reason_code=code,
            request_id=request_id,
            resource_type="sot_package",
            details=details,
        )

    async def stage(
        self,
        staging_name: str,
        *,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> PublishResult:
        package = self.parser.parse(staging_name)
        manifest = package.manifest
        async with self.uow.transaction() as session:
            existing = (await session.execute(text("""
                SELECT p.package_id,p.manifest_sha256,p.payload_sha256,p.lifecycle,
                  r.run_id FROM sot_packages p
                JOIN sot_publish_runs r ON r.package_id=p.package_id
                WHERE p.source_key=:source_key AND p.revision=:revision
            """), {
                "source_key": manifest.source_key,
                "revision": manifest.revision,
            })).mappings().one_or_none()
            if existing:
                if (
                    existing["manifest_sha256"] == package.manifest_sha256
                    and existing["payload_sha256"] == manifest.payload_sha256
                ):
                    return PublishResult(
                        package_id=existing["package_id"],
                        run_id=existing["run_id"],
                        source_key=manifest.source_key,
                        revision=manifest.revision,
                        state=existing["lifecycle"],
                        idempotent=True,
                    )
                raise PublishError("revision_checksum_conflict")
            run_id = uuid.uuid4()
            try:
                await session.execute(text("""
                    INSERT INTO sot_packages(
                      package_id,source_key,revision,schema_version,trust_zone,
                      manifest_sha256,payload_sha256,producer,generated_at,
                      staging_name,lifecycle
                    ) VALUES (
                      :package_id,:source_key,:revision,:schema_version,'sot',
                      :manifest_sha256,:payload_sha256,:producer,:generated_at,
                      :staging_name,'staged'
                    )
                """), {
                    "package_id": manifest.package_id,
                    "source_key": manifest.source_key,
                    "revision": manifest.revision,
                    "schema_version": manifest.schema_version,
                    "manifest_sha256": package.manifest_sha256,
                    "payload_sha256": manifest.payload_sha256,
                    "producer": manifest.producer,
                    "generated_at": manifest.generated_at,
                    "staging_name": staging_name,
                })
                await session.execute(text("""
                    INSERT INTO sot_publish_runs(
                      run_id,package_id,source_key,revision,actor_user_id,request_id,
                      state,candidate_checksum,deterministic_checksum
                    ) VALUES (
                      :run_id,:package_id,:source_key,:revision,:actor,:request_id,
                      'staged',:checksum,:checksum
                    )
                """), {
                    "run_id": run_id,
                    "package_id": manifest.package_id,
                    "source_key": manifest.source_key,
                    "revision": manifest.revision,
                    "actor": actor_id,
                    "request_id": request_id,
                    "checksum": manifest.payload_sha256,
                })
            except IntegrityError:
                raise PublishError("package_identity_conflict") from None
            await self._audit(
                session,
                actor_id=actor_id,
                action="sot.package.stage",
                result="success",
                code="package_staged",
                request_id=request_id,
                details={
                    "package_id": str(manifest.package_id),
                    "source_key": manifest.source_key,
                    "revision": manifest.revision,
                    "run_id": str(run_id),
                },
            )
        return PublishResult(
            package_id=manifest.package_id,
            run_id=run_id,
            source_key=manifest.source_key,
            revision=manifest.revision,
            state="staged",
        )

    async def _load(self, package_id: uuid.UUID) -> tuple[ParsedPackage, dict[str, Any]]:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT p.*,r.run_id,r.actor_user_id,r.request_id,
                  r.state AS run_state,r.deterministic_checksum
                FROM sot_packages p JOIN sot_publish_runs r USING(package_id)
                WHERE package_id=:package_id
            """), {"package_id": package_id})).mappings().one_or_none()
        if row is None:
            raise PublishError("package_not_found")
        package = self.parser.parse(str(row["staging_name"]))
        if (
            package.manifest_sha256 != row["manifest_sha256"]
            or package.manifest.payload_sha256 != row["payload_sha256"]
        ):
            raise PublishError("staged_package_changed")
        return package, dict(row)

    async def validate(
        self,
        package_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> ValidationReport:
        package, row = await self._load(package_id)
        report = validate_package(
            package,
            now=self.clock(),
            allow_claim_as_approved=self.settings.sot_allow_claim_as_approved,
        )
        state = "validated" if report.valid else "rejected"
        code = "validation_passed" if report.valid else (
            report.findings[0].code if report.findings else "validation_failed"
        )
        summary = report.model_dump(mode="json")
        async with self.uow.transaction() as session:
            await session.execute(text("""
                UPDATE sot_packages SET lifecycle=:state,
                  validation_summary=CAST(:report AS jsonb),rejection_code=:code,
                  record_count=:records,evidence_count=:evidence,source_count=:sources
                WHERE package_id=:package_id
                  AND lifecycle IN ('staged','validating','validated','rejected')
            """), {
                "state": state,
                "report": json.dumps(summary),
                "code": None if report.valid else code,
                "records": report.record_count,
                "evidence": report.evidence_count,
                "sources": report.source_count,
                "package_id": package_id,
            })
            await session.execute(text("""
                UPDATE sot_publish_runs SET state=:state,
                  validation_report=CAST(:report AS jsonb),
                  deterministic_checksum=:checksum,record_count=:records,
                  evidence_count=:evidence,failure_code=:failure,
                  finished_at=CASE WHEN :state='rejected' THEN now() ELSE NULL END
                WHERE package_id=:package_id
            """), {
                "state": state,
                "report": json.dumps(summary),
                "checksum": report.deterministic_checksum,
                "records": report.record_count,
                "evidence": report.evidence_count,
                "failure": None if report.valid else code,
                "package_id": package_id,
            })
            await self._audit(
                session,
                actor_id=actor_id,
                action="sot.package.validate",
                result="success" if report.valid else "deny",
                code=code,
                request_id=request_id,
                details={
                    "package_id": str(package_id),
                    "run_id": str(row["run_id"]),
                    "finding_codes": [item.code for item in report.findings],
                    "finding_count": len(report.findings),
                },
            )
        return report

    async def publish(
        self,
        package_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        request_id: str,
        inject_failure: str | None = None,
    ) -> PublishResult:
        package, row = await self._load(package_id)
        if row["lifecycle"] == "active":
            return PublishResult(
                package_id=package_id,
                run_id=row["run_id"],
                source_key=row["source_key"],
                revision=row["revision"],
                state="active",
                idempotent=True,
            )
        if row["lifecycle"] != "validated":
            raise PublishError("candidate_not_validated")
        report = validate_package(
            package,
            now=self.clock(),
            allow_claim_as_approved=self.settings.sot_allow_claim_as_approved,
        )
        if not report.valid or report.deterministic_checksum != row["deterministic_checksum"]:
            raise PublishError("validation_changed")
        try:
            verify_attestation(
                package,
                secret=self.settings.sot_signing_secret.get_secret_value(),
                curator_id=str(actor_id),
                now=self.clock(),
            )
        except PackageError as error:
            raise PublishError(error.code) from None
        if inject_failure == "before_transaction":
            await self._record_failure(
                package_id,
                row["run_id"],
                "injected_failure",
            )
            raise PublishError("injected_failure")
        try:
            async with self.uow.transaction() as session:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:source_key))"),
                    {"source_key": package.manifest.source_key},
                )
                current = (await session.execute(text("""
                    SELECT * FROM sot_active_revisions WHERE source_key=:source_key
                    FOR UPDATE
                """), {"source_key": package.manifest.source_key})).mappings().one_or_none()
                if current and current["package_id"] == package_id:
                    return PublishResult(
                        package_id=package_id,
                        run_id=row["run_id"],
                        source_key=row["source_key"],
                        revision=row["revision"],
                        state="active",
                        idempotent=True,
                    )
                if current and package.manifest.revision <= int(current["revision"]):
                    raise PublishError("revision_not_monotonic")
                await session.execute(text("""
                    UPDATE sot_packages SET lifecycle='publishing'
                    WHERE package_id=:package_id AND lifecycle='validated'
                """), {"package_id": package_id})
                await session.execute(text("""
                    UPDATE sot_publish_runs SET state='publishing',
                      previous_active_revision=:previous_revision,
                      previous_active_checksum=:previous_checksum
                    WHERE run_id=:run_id
                """), {
                    "run_id": row["run_id"],
                    "previous_revision": current["revision"] if current else None,
                    "previous_checksum": current["payload_sha256"] if current else None,
                })
                if inject_failure == "before_candidates":
                    raise PublishError("injected_failure")
                await self._insert_candidates(session, package)
                if inject_failure == "after_candidates":
                    raise PublishError("injected_failure")
                await session.execute(text("""
                    UPDATE record_versions rv SET lifecycle='superseded'
                    FROM records r
                    WHERE rv.record_id=r.record_id AND r.source_key=:source_key
                      AND rv.lifecycle='active'
                """), {"source_key": package.manifest.source_key})
                await session.execute(text("""
                    UPDATE evidence_spans e SET lifecycle='superseded'
                    FROM record_versions rv JOIN records r ON r.record_id=rv.record_id
                    WHERE e.record_version_id=rv.version_id AND r.source_key=:source_key
                      AND e.lifecycle='active'
                """), {"source_key": package.manifest.source_key})
                await session.execute(text("""
                    UPDATE records SET lifecycle='superseded',current_version_id=NULL,
                      updated_at=now() WHERE source_key=:source_key
                """), {"source_key": package.manifest.source_key})
                await session.execute(text("""
                    UPDATE resources rs SET lifecycle_state='superseded',updated_at=now()
                    FROM records r WHERE rs.resource_id=r.record_id
                      AND r.source_key=:source_key
                """), {"source_key": package.manifest.source_key})
                await session.execute(text("""
                    UPDATE record_versions SET lifecycle='active'
                    WHERE package_id=:package_id
                """), {"package_id": package_id})
                await session.execute(text("""
                    UPDATE evidence_spans SET lifecycle='active'
                    WHERE package_id=:package_id
                """), {"package_id": package_id})
                await session.execute(text("""
                    UPDATE records r SET lifecycle='active',
                      current_version_id=rv.version_id,updated_at=now()
                    FROM record_versions rv
                    WHERE rv.record_id=r.record_id AND rv.package_id=:package_id
                """), {"package_id": package_id})
                await session.execute(text("""
                    UPDATE resources rs SET lifecycle_state='active',updated_at=now()
                    FROM records r JOIN record_versions rv ON rv.record_id=r.record_id
                    WHERE rs.resource_id=r.record_id AND rv.package_id=:package_id
                """), {"package_id": package_id})
                if current:
                    await session.execute(text("""
                        UPDATE sot_packages SET lifecycle='superseded'
                        WHERE package_id=:package_id
                    """), {"package_id": current["package_id"]})
                await session.execute(text("""
                    INSERT INTO sot_active_revisions(
                      source_key,package_id,revision,payload_sha256,activated_run_id
                    ) VALUES (
                      :source_key,:package_id,:revision,:checksum,:run_id
                    ) ON CONFLICT(source_key) DO UPDATE SET
                      package_id=excluded.package_id,revision=excluded.revision,
                      payload_sha256=excluded.payload_sha256,
                      activated_run_id=excluded.activated_run_id,activated_at=now()
                """), {
                    "source_key": package.manifest.source_key,
                    "package_id": package_id,
                    "revision": package.manifest.revision,
                    "checksum": package.manifest.payload_sha256,
                    "run_id": row["run_id"],
                })
                if inject_failure == "after_swap":
                    raise PublishError("injected_failure")
                await session.execute(text("""
                    INSERT INTO sot_reindex_outbox(run_id,source_key,revision,payload)
                    VALUES (:run_id,:source_key,:revision,CAST(:payload AS jsonb))
                    ON CONFLICT(run_id) DO NOTHING
                """), {
                    "run_id": row["run_id"],
                    "source_key": package.manifest.source_key,
                    "revision": package.manifest.revision,
                    "payload": json.dumps({
                        "name": "sot.reindex",
                        "run_id": str(row["run_id"]),
                        "source_key": package.manifest.source_key,
                        "revision": package.manifest.revision,
                    }),
                })
                await self._publish_linked_gaps(
                    session,
                    package_id,
                    actor_id=actor_id,
                    request_id=request_id,
                )
                if inject_failure == "before_audit":
                    raise PublishError("injected_failure")
                event_id = await self._audit(
                    session,
                    actor_id=actor_id,
                    action="sot.package.publish",
                    result="success",
                    code="revision_activated",
                    request_id=request_id,
                    details={
                        "package_id": str(package_id),
                        "run_id": str(row["run_id"]),
                        "source_key": package.manifest.source_key,
                        "revision": package.manifest.revision,
                        "previous_checksum": (
                            str(current["payload_sha256"]) if current else None
                        ),
                        "new_checksum": package.manifest.payload_sha256,
                        "record_count": len(package.records),
                        "evidence_count": len(package.evidence),
                        "decision": "approved",
                    },
                )
                await session.execute(text("""
                    UPDATE sot_packages SET lifecycle='active' WHERE package_id=:package_id
                """), {
                    "package_id": package_id,
                })
                await session.execute(text("""
                    UPDATE sot_publish_runs SET state='active',finished_at=now(),
                      audit_event_id=:event_id WHERE run_id=:run_id
                """), {
                    "run_id": row["run_id"],
                    "event_id": event_id,
                })
        except PublishError as error:
            await self._record_failure(package_id, row["run_id"], error.code)
            raise
        except Exception as error:
            code = f"activation_{type(error).__name__.lower()}"
            await self._record_failure(package_id, row["run_id"], code)
            raise PublishError("activation_failed") from None
        return PublishResult(
            package_id=package_id,
            run_id=row["run_id"],
            source_key=package.manifest.source_key,
            revision=package.manifest.revision,
            state="active",
        )

    async def _publish_linked_gaps(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> None:
        """TIP-010: flip answered gaps to published when their record activates.

        The flip rides inside the activation transaction, so a failed publish
        never publishes a gap. A gap that concurrently left the ``answered``
        state is skipped fail-closed rather than aborting the activation.
        """
        governance = GovernanceRepository()
        for gap_id in await governance.answered_gap_ids_for_package(
            session,
            package_id,
        ):
            try:
                await governance.transition_gap(
                    session,
                    gap_id,
                    to_state="published",
                    actor_subject_id=actor_id,
                    reason="Linked record activated through the publish gate",
                )
            except GovernanceError:
                continue
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor_id,
                action="governance.gap.publish",
                result="success",
                reason_code="linked_record_activated",
                request_id=request_id,
                resource_type="gap",
                details={
                    "gap_id": str(gap_id),
                    "package_id": str(package_id),
                },
            )

    async def _record_failure(
        self,
        package_id: uuid.UUID,
        run_id: uuid.UUID,
        code: str,
    ) -> None:
        fingerprint = hashlib.sha256(code.encode()).hexdigest()
        async with self.uow.transaction() as session:
            await session.execute(text("""
                UPDATE sot_packages SET lifecycle='validated'
                WHERE package_id=:package_id AND lifecycle='publishing'
            """), {"package_id": package_id})
            await session.execute(text("""
                UPDATE sot_publish_runs SET state='failed',failure_code=:code,
                  failure_fingerprint=:fingerprint,finished_at=now()
                WHERE run_id=:run_id
            """), {
                "run_id": run_id,
                "code": code,
                "fingerprint": fingerprint,
            })

    async def _insert_candidates(
        self,
        session: AsyncSession,
        package: ParsedPackage,
    ) -> None:
        version_ids: dict[str, uuid.UUID] = {}
        for record in package.records:
            existing = (await session.execute(text("""
                SELECT r.record_id,r.source_key,r.owner_subject_id,r.current_version_id,
                  coalesce(max(rv.version_ordinal),0) AS max_ordinal,
                  bool_or(
                    rv.lifecycle='active'
                    AND tstzrange(rv.effective_from,rv.effective_to,'[)')
                      && tstzrange(:effective_from,:effective_to,'[)')
                  ) AS active_overlap
                FROM records r LEFT JOIN record_versions rv ON rv.record_id=r.record_id
                WHERE r.record_key=:record_key
                GROUP BY r.record_id,r.source_key,r.owner_subject_id,r.current_version_id
            """), {
                "record_key": record.record_key,
                "effective_from": record.effective_from,
                "effective_to": record.effective_to,
            })).mappings().one_or_none()
            if existing and (
                existing["source_key"] != package.manifest.source_key
                or existing["owner_subject_id"] != record.owner_id
            ):
                raise PublishError("stable_record_identity_conflict")
            if existing and record.version_ordinal <= int(existing["max_ordinal"]):
                raise PublishError("version_ordinal_not_monotonic")
            if (
                existing
                and existing["active_overlap"]
                and record.supersedes_record_key != record.record_key
            ):
                raise PublishError("validity_overlap_unresolved")
            record_id = existing["record_id"] if existing else uuid.uuid5(
                package.manifest.package_id,
                record.record_key,
            )
            if not existing:
                await session.execute(text("""
                    INSERT INTO resources(
                      resource_id,resource_type,owner_subject_id,classification,
                      source_zone,department_id,project_id,lifecycle_state
                    ) VALUES (
                      :id,'record',:owner,:classification,'sot',:department,:project,'draft'
                    )
                """), {
                    "id": record_id,
                    "owner": record.owner_id,
                    "classification": record.classification,
                    "department": record.department_id,
                    "project": record.project_id,
                })
                await session.execute(text("""
                    INSERT INTO records(
                      record_id,record_key,source_key,owner_subject_id,classification,
                      department_id,project_id,lifecycle
                    ) VALUES (
                      :id,:key,:source,:owner,:classification,:department,:project,'staged'
                    )
                """), {
                    "id": record_id,
                    "key": record.record_key,
                    "source": package.manifest.source_key,
                    "owner": record.owner_id,
                    "classification": record.classification,
                    "department": record.department_id,
                    "project": record.project_id,
                })
            else:
                await session.execute(text("""
                    UPDATE records SET classification=:classification,
                      department_id=:department,project_id=:project,updated_at=now()
                    WHERE record_id=:id
                """), {
                    "id": record_id,
                    "classification": record.classification,
                    "department": record.department_id,
                    "project": record.project_id,
                })
                await session.execute(text("""
                    UPDATE resources SET classification=:classification,
                      department_id=:department,project_id=:project,updated_at=now()
                    WHERE resource_id=:id
                """), {
                    "id": record_id,
                    "classification": record.classification,
                    "department": record.department_id,
                    "project": record.project_id,
                })
            version_id = uuid.uuid5(package.manifest.package_id, record.record_key)
            version_ids[record.record_key] = version_id
            if existing:
                await session.execute(text("""
                    DELETE FROM acl_entries WHERE resource_id=:resource_id
                """), {"resource_id": record_id})
            await session.execute(text("""
                INSERT INTO record_versions(
                  version_id,record_id,package_id,package_revision,version_ordinal,
                  owner_subject_id,classification,department_id,project_id,
                  value_payload,searchable_text,provenance_level,confidence,
                  verification_state,fact_state,effective_from,effective_to,freshness_policy,
                  freshness_due_at,freshness_state,evidence_refs,source_refs,
                  acl_projection,content_sha256,supersedes_version_id,lifecycle
                ) VALUES (
                  :version_id,:record_id,:package_id,:revision,:ordinal,
                  :owner,:classification,:department,:project,
                  CAST(:value AS jsonb),:searchable,:provenance,:confidence,
                  :verification,:fact_state,:effective_from,:effective_to,
                  CAST(:freshness AS jsonb),
                  :freshness_due,:freshness_state,:evidence_refs,:source_refs,
                  CAST(:acl AS jsonb),:checksum,:supersedes,'staged'
                )
            """), {
                "version_id": version_id,
                "record_id": record_id,
                "package_id": package.manifest.package_id,
                "revision": package.manifest.revision,
                "ordinal": record.version_ordinal,
                "owner": record.owner_id,
                "classification": record.classification,
                "department": record.department_id,
                "project": record.project_id,
                "value": json.dumps(record.value),
                "searchable": record.searchable_text,
                "provenance": record.provenance_level,
                "confidence": record.confidence,
                "verification": record.verification_state,
                "fact_state": record.fact_state,
                "effective_from": record.effective_from,
                "effective_to": record.effective_to,
                "freshness": json.dumps(record.freshness_policy),
                "freshness_due": record.freshness_due_at,
                "freshness_state": freshness_state(record, self.clock()),
                "evidence_refs": record.evidence_keys,
                "source_refs": record.source_refs,
                "acl": json.dumps([
                    item.model_dump(mode="json") for item in record.acl
                ]),
                "checksum": record.content_sha256,
                "supersedes": (
                    existing["current_version_id"]
                    if existing and record.supersedes_record_key == record.record_key
                    else None
                ),
            })
            for acl in record.acl:
                await session.execute(text("""
                    INSERT INTO acl_entries(
                      resource_id,principal_type,principal_id,action,effect,
                      valid_from,granted_by,reason
                    ) VALUES (
                      :resource,:principal_type,:principal,:action,:effect,
                      now(),:owner,'sot_package_projection'
                    ) ON CONFLICT DO NOTHING
                """), {
                    "resource": record_id,
                    "principal_type": acl.principal_type,
                    "principal": acl.principal_id,
                    "action": acl.action,
                    "effect": acl.effect,
                    "owner": record.owner_id,
                })
        for evidence in package.evidence:
            await session.execute(text("""
                INSERT INTO evidence_spans(
                  span_id,evidence_key,record_version_id,package_id,source_ref,
                  source_document_id,source_version_id,source_blob_sha256,locator,
                  quoted_text,normalized_text,evidence_sha256,source_label,
                  classification,lifecycle
                ) VALUES (
                  :span_id,:key,:version_id,:package_id,:source_ref,
                  :document_id,:source_version_id,:blob_sha,CAST(:locator AS jsonb),
                  :quoted,:normalized,:checksum,:label,:classification,'staged'
                )
            """), {
                "span_id": uuid.uuid5(package.manifest.package_id, evidence.evidence_key),
                "key": evidence.evidence_key,
                "version_id": version_ids[evidence.record_key],
                "package_id": package.manifest.package_id,
                "source_ref": evidence.source_ref,
                "document_id": evidence.source_document_id,
                "source_version_id": evidence.source_version_id,
                "blob_sha": evidence.source_blob_sha256,
                "locator": json.dumps(evidence.locator),
                "quoted": evidence.quoted_text,
                "normalized": evidence.normalized_text,
                "checksum": evidence.evidence_sha256,
                "label": evidence.source_label,
                "classification": evidence.classification,
            })

    async def active_records(self) -> list[dict[str, Any]]:
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT r.record_id,r.record_key,rv.value_payload,rv.searchable_text,
                  rv.provenance_level,rv.verification_state,rv.effective_from,
                  rv.effective_to,rv.freshness_state,rv.content_sha256
                FROM records r JOIN record_versions rv
                  ON rv.version_id=r.current_version_id
                JOIN sot_packages p ON p.package_id=rv.package_id
                WHERE r.lifecycle='active' AND rv.lifecycle='active'
                  AND p.lifecycle='active'
                ORDER BY r.record_key
            """))).mappings().all()
        return [dict(row) for row in rows]

    async def status(self, package_id: uuid.UUID) -> dict[str, Any] | None:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT p.package_id,p.source_key,p.revision,p.lifecycle,
                  p.payload_sha256,p.record_count,p.evidence_count,p.source_count,
                  p.rejection_code,p.validation_summary,r.run_id,
                  r.state AS run_state,r.failure_code,r.started_at,r.finished_at
                FROM sot_packages p JOIN sot_publish_runs r USING(package_id)
                WHERE p.package_id=:package_id
            """), {"package_id": package_id})).mappings().one_or_none()
        return dict(row) if row else None

    async def active_record(self, record_key: str) -> tuple[uuid.UUID, ActiveRecord] | None:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT r.record_id,r.record_key,rv.version_id,rv.value_payload,
                  rv.searchable_text,rv.provenance_level,rv.verification_state,
                  rv.effective_from,rv.effective_to,rv.freshness_state,rv.content_sha256
                FROM records r JOIN record_versions rv
                  ON rv.version_id=r.current_version_id
                JOIN sot_packages p ON p.package_id=rv.package_id
                WHERE r.record_key=:key AND r.lifecycle='active'
                  AND rv.lifecycle='active' AND p.lifecycle='active'
            """), {"key": record_key})).mappings().one_or_none()
            if row is None:
                return None
            evidence_rows = (await session.execute(text("""
                SELECT evidence_key,locator,quoted_text,source_label,evidence_sha256
                FROM evidence_spans WHERE record_version_id=:version_id
                  AND lifecycle='active' ORDER BY evidence_key
            """), {"version_id": row["version_id"]})).mappings().all()
        return row["record_id"], ActiveRecord(
            record_key=row["record_key"],
            value=row["value_payload"],
            searchable_text=row["searchable_text"],
            provenance_level=row["provenance_level"],
            verification_state=row["verification_state"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            freshness_state=row["freshness_state"],
            content_sha256=str(row["content_sha256"]),
            evidence=[ActiveEvidence(**item) for item in evidence_rows],
        )
