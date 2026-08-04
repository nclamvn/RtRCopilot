"""Persistence and deterministic fingerprint checks for TIP-025."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.enterprise.models import (
    CorpusManifestRecord,
    CorpusManifestSpec,
    DomainCreate,
    DomainRecord,
    EvaluationRunRecord,
    EvaluationStatus,
    EvaluationSuiteRecord,
    EvaluationSuiteSpec,
    OntologyRevisionRecord,
    ReleaseAttestation,
    digest_of,
)
from rtr_copilot.rag.ontology import OntologySpec


class EnterpriseError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _domain(row: Any) -> DomainRecord:
    return DomainRecord.model_validate(dict(row))


def _manifest(row: Any) -> CorpusManifestRecord:
    return CorpusManifestRecord.model_validate(dict(row))


def _ontology(row: Any) -> OntologyRevisionRecord:
    return OntologyRevisionRecord.model_validate(dict(row))


def _suite(row: Any) -> EvaluationSuiteRecord:
    return EvaluationSuiteRecord.model_validate(dict(row))


def _run(row: Any) -> EvaluationRunRecord:
    return EvaluationRunRecord.model_validate(dict(row))


class EnterpriseRepository:
    async def subject_active(self, session: AsyncSession, subject_id: uuid.UUID) -> bool:
        return bool(
            await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM subjects WHERE user_id=:id AND status='active')",
                ),
                {"id": subject_id},
            )
        )

    async def create_domain(
        self,
        session: AsyncSession,
        payload: DomainCreate,
        proposer: uuid.UUID,
    ) -> DomainRecord:
        row = (
            (
                await session.execute(
                    text("""
            INSERT INTO enterprise_domains(
              domain_key,display_name,description,owner_subject_id,classification,
              minimum_eval_cases,proposed_by
            ) VALUES (
              :domain_key,:display_name,:description,:owner_subject_id,
              :classification,:minimum_eval_cases,:proposed_by
            ) RETURNING *
        """),
                    {**payload.model_dump(), "proposed_by": proposer},
                )
            )
            .mappings()
            .one()
        )
        return _domain(row)

    async def domain_by_id(
        self,
        session: AsyncSession,
        domain_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> DomainRecord | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM enterprise_domains WHERE domain_id=:id" + suffix,
                    ),
                    {"id": domain_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _domain(row) if row else None

    async def domain_by_key(
        self,
        session: AsyncSession,
        domain_key: str,
    ) -> DomainRecord | None:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM enterprise_domains WHERE domain_key=:key",
                    ),
                    {"key": domain_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _domain(row) if row else None

    async def active_domain_minimums(self, session: AsyncSession) -> dict[str, int]:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT domain_key,minimum_eval_cases FROM enterprise_domains
            WHERE state='active' ORDER BY domain_key
        """)
                )
            )
            .mappings()
            .all()
        )
        return {str(row["domain_key"]): int(row["minimum_eval_cases"]) for row in rows}

    async def decide_domain(
        self,
        session: AsyncSession,
        domain_id: uuid.UUID,
        *,
        approver: uuid.UUID,
        approved: bool,
        reason: str,
    ) -> DomainRecord:
        row = (
            (
                await session.execute(
                    text("""
            UPDATE enterprise_domains SET state=:state,approved_by=:approver,
              decision_reason=:reason,decided_at=now(),updated_at=now()
            WHERE domain_id=:id AND state='proposed' RETURNING *
        """),
                    {
                        "id": domain_id,
                        "state": "active" if approved else "rejected",
                        "approver": approver,
                        "reason": reason,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EnterpriseError("enterprise_domain_transition_invalid")
        return _domain(row)

    async def create_manifest(
        self,
        session: AsyncSession,
        *,
        domain_id: uuid.UUID,
        version: int,
        spec: CorpusManifestSpec,
        proposer: uuid.UUID,
    ) -> CorpusManifestRecord:
        canonical = spec.canonical()
        row = (
            (
                await session.execute(
                    text("""
            INSERT INTO enterprise_corpus_manifests(
              domain_id,version,manifest_digest,sources,source_count,proposed_by
            ) VALUES (
              :domain_id,:version,:digest,CAST(:sources AS jsonb),:count,:proposer
            ) RETURNING *
        """),
                    {
                        "domain_id": domain_id,
                        "version": version,
                        "digest": canonical.digest,
                        "sources": json.dumps(
                            [item.model_dump(mode="json") for item in canonical.sources]
                        ),
                        "count": len(canonical.sources),
                        "proposer": proposer,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _manifest(row)

    async def manifest_by_id(
        self,
        session: AsyncSession,
        manifest_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> CorpusManifestRecord | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM enterprise_corpus_manifests WHERE manifest_id=:id" + suffix,
                    ),
                    {"id": manifest_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _manifest(row) if row else None

    async def current_source_fingerprint(
        self,
        session: AsyncSession,
        kind: str,
        source_key: str,
    ) -> str | None:
        if kind == "sot":
            value = await session.scalar(
                text("""
                SELECT payload_sha256 FROM sot_active_revisions WHERE source_key=:key
            """),
                {"key": source_key},
            )
            return str(value) if value is not None else None
        if kind == "research":
            value = await session.scalar(
                text("""
                SELECT rp.fingerprint FROM research_sources rs
                JOIN research_packages rp ON rp.source_id=rs.source_id
                WHERE rs.stable_key=:key AND rs.lifecycle='active'
                  AND rp.import_state='imported'
                ORDER BY rp.imported_at DESC,rp.package_id DESC LIMIT 1
            """),
                {"key": source_key},
            )
            return str(value) if value is not None else None
        return None

    async def validate_sources(
        self,
        session: AsyncSession,
        sources: Sequence[Any],
    ) -> tuple[str, list[str]]:
        current: list[dict[str, str]] = []
        errors: list[str] = []
        for item in sources:
            actual = await self.current_source_fingerprint(
                session,
                str(item.kind),
                str(item.source_key),
            )
            identity = digest_of({"kind": item.kind, "source_key": item.source_key})[:16]
            if actual is None:
                errors.append(f"source_unavailable:{identity}")
                continue
            if actual != item.fingerprint:
                errors.append(f"source_drift:{identity}")
            current.append(
                {
                    "kind": str(item.kind),
                    "source_key": str(item.source_key),
                    "fingerprint": str(actual),
                }
            )
        return digest_of(
            sorted(current, key=lambda value: (value["kind"], value["source_key"]))
        ), errors

    async def mark_manifest_validated(
        self,
        session: AsyncSession,
        manifest_id: uuid.UUID,
        *,
        validator: uuid.UUID,
        snapshot_digest: str,
    ) -> CorpusManifestRecord:
        row = (
            (
                await session.execute(
                    text("""
            UPDATE enterprise_corpus_manifests SET state='validated',
              validated_snapshot_digest=:digest,validated_by=:validator,
              validated_at=now() WHERE manifest_id=:id AND state='proposed'
            RETURNING *
        """),
                    {"id": manifest_id, "digest": snapshot_digest, "validator": validator},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EnterpriseError("enterprise_manifest_transition_invalid")
        return _manifest(row)

    async def decide_manifest(
        self,
        session: AsyncSession,
        manifest_id: uuid.UUID,
        *,
        approver: uuid.UUID,
        approved: bool,
        reason: str,
    ) -> CorpusManifestRecord:
        manifest = await self.manifest_by_id(session, manifest_id, lock=True)
        if manifest is None:
            raise EnterpriseError("enterprise_manifest_not_found")
        expected = "validated" if approved else manifest.state
        if approved and expected != manifest.state:
            raise EnterpriseError("enterprise_manifest_not_validated")
        if not approved and manifest.state not in {"proposed", "validated"}:
            raise EnterpriseError("enterprise_manifest_transition_invalid")
        if approved:
            await session.execute(
                text("""
                UPDATE enterprise_corpus_manifests SET state='superseded'
                WHERE domain_id=:domain_id AND state='active'
            """),
                {"domain_id": manifest.domain_id},
            )
        row = (
            (
                await session.execute(
                    text("""
            UPDATE enterprise_corpus_manifests SET state=:state,decided_by=:approver,
              decision_reason=:reason,decided_at=now()
            WHERE manifest_id=:id RETURNING *
        """),
                    {
                        "id": manifest_id,
                        "state": "active" if approved else "rejected",
                        "approver": approver,
                        "reason": reason,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _manifest(row)

    async def current_corpus_snapshot(
        self,
        session: AsyncSession,
    ) -> tuple[str, int, int, list[str]]:
        domain_count = int(
            await session.scalar(
                text(
                    "SELECT count(*) FROM enterprise_domains WHERE state='active'",
                )
            )
            or 0
        )
        rows = (
            (
                await session.execute(
                    text("""
            SELECT m.* FROM enterprise_corpus_manifests m
            JOIN enterprise_domains d ON d.domain_id=m.domain_id
            WHERE d.state='active' AND m.state='active' ORDER BY d.domain_key
        """)
                )
            )
            .mappings()
            .all()
        )
        manifests = [_manifest(row) for row in rows]
        snapshots: list[dict[str, str]] = []
        errors: list[str] = []
        for manifest in manifests:
            digest, manifest_errors = await self.validate_sources(session, manifest.sources)
            errors.extend(manifest_errors)
            if digest != manifest.validated_snapshot_digest:
                errors.append(f"manifest_snapshot_drift:{manifest.manifest_digest[:16]}")
            snapshots.append(
                {
                    "manifest_digest": manifest.manifest_digest,
                    "snapshot_digest": digest,
                }
            )
        return digest_of(snapshots), domain_count, len(manifests), errors

    async def create_ontology(
        self,
        session: AsyncSession,
        *,
        version: int,
        ontology: OntologySpec,
        ontology_digest: str,
        proposer: uuid.UUID,
    ) -> OntologyRevisionRecord:
        row = (
            (
                await session.execute(
                    text("""
            INSERT INTO enterprise_ontology_revisions(
              registry_id,version,ontology_digest,payload,entity_count,proposed_by
            ) VALUES (
              :registry_id,:version,:digest,CAST(:payload AS jsonb),:count,:proposer
            ) RETURNING *
        """),
                    {
                        "registry_id": ontology.registry_id,
                        "version": version,
                        "digest": ontology_digest,
                        "payload": ontology.model_dump_json(),
                        "count": len(ontology.entities),
                        "proposer": proposer,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _ontology(row)

    async def ontology_by_id(
        self,
        session: AsyncSession,
        revision_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> OntologyRevisionRecord | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM enterprise_ontology_revisions WHERE revision_id=:id"
                        + suffix,
                    ),
                    {"id": revision_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _ontology(row) if row else None

    async def decide_ontology(
        self,
        session: AsyncSession,
        revision_id: uuid.UUID,
        *,
        approver: uuid.UUID,
        approved: bool,
        reason: str,
    ) -> OntologyRevisionRecord:
        row = (
            (
                await session.execute(
                    text("""
            UPDATE enterprise_ontology_revisions SET state=:state,decided_by=:approver,
              decision_reason=:reason,decided_at=now()
            WHERE revision_id=:id AND state='proposed' RETURNING *
        """),
                    {
                        "id": revision_id,
                        "state": "approved" if approved else "rejected",
                        "approver": approver,
                        "reason": reason,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EnterpriseError("enterprise_ontology_transition_invalid")
        return _ontology(row)

    async def active_ontology(self, session: AsyncSession) -> OntologyRevisionRecord | None:
        row = (
            (
                await session.execute(
                    text("""
            SELECT * FROM enterprise_ontology_revisions
            WHERE state='active' ORDER BY activated_at DESC LIMIT 1
        """)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _ontology(row) if row else None

    async def create_suite(
        self,
        session: AsyncSession,
        *,
        version: int,
        suite: EvaluationSuiteSpec,
        proposer: uuid.UUID,
    ) -> EvaluationSuiteRecord:
        domains = {item.domain_key for item in suite.cases}
        row = (
            (
                await session.execute(
                    text("""
            INSERT INTO enterprise_evaluation_suites(
              suite_key,version,suite_digest,definition,case_count,domain_count,proposed_by
            ) VALUES (
              :suite_key,:version,:digest,CAST(:definition AS jsonb),:cases,:domains,:proposer
            ) RETURNING *
        """),
                    {
                        "suite_key": suite.suite_key,
                        "version": version,
                        "digest": suite.digest,
                        "definition": suite.model_dump_json(),
                        "cases": len(suite.cases),
                        "domains": len(domains),
                        "proposer": proposer,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _suite(row)

    async def suite_by_id(
        self,
        session: AsyncSession,
        suite_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> EvaluationSuiteRecord | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM enterprise_evaluation_suites WHERE suite_id=:id" + suffix,
                    ),
                    {"id": suite_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _suite(row) if row else None

    async def decide_suite(
        self,
        session: AsyncSession,
        suite_id: uuid.UUID,
        *,
        approver: uuid.UUID,
        approved: bool,
        reason: str,
    ) -> EvaluationSuiteRecord:
        row = (
            (
                await session.execute(
                    text("""
            UPDATE enterprise_evaluation_suites SET state=:state,decided_by=:approver,
              decision_reason=:reason,decided_at=now()
            WHERE suite_id=:id AND state='proposed' RETURNING *
        """),
                    {
                        "id": suite_id,
                        "state": "approved" if approved else "rejected",
                        "approver": approver,
                        "reason": reason,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EnterpriseError("enterprise_suite_transition_invalid")
        return _suite(row)

    async def create_run(
        self,
        session: AsyncSession,
        *,
        suite_id: uuid.UUID,
        ontology_revision_id: uuid.UUID,
        ontology_digest: str,
        suite_digest: str,
        corpus_snapshot_digest: str,
        evaluation_subject_digest: str,
        status: EvaluationStatus,
        passed_count: int,
        failed_count: int,
        critical_failed_count: int,
        domain_metrics: dict[str, Any],
        result_payload: dict[str, Any],
        result_digest: str,
        executed_by: uuid.UUID,
        started_at: Any,
        finished_at: Any,
    ) -> EvaluationRunRecord:
        row = (
            (
                await session.execute(
                    text("""
            INSERT INTO enterprise_evaluation_runs(
              suite_id,ontology_revision_id,ontology_digest,suite_digest,
              corpus_snapshot_digest,evaluation_subject_digest,status,passed_count,
              failed_count,critical_failed_count,domain_metrics,result_payload,
              result_digest,executed_by,started_at,finished_at
            ) VALUES (
              :suite_id,:ontology_revision_id,:ontology_digest,:suite_digest,
              :corpus_snapshot_digest,:evaluation_subject_digest,:status,:passed_count,
              :failed_count,:critical_failed_count,CAST(:domain_metrics AS jsonb),
              CAST(:result_payload AS jsonb),:result_digest,:executed_by,:started_at,:finished_at
            ) RETURNING *
        """),
                    {
                        "suite_id": suite_id,
                        "ontology_revision_id": ontology_revision_id,
                        "ontology_digest": ontology_digest,
                        "suite_digest": suite_digest,
                        "corpus_snapshot_digest": corpus_snapshot_digest,
                        "evaluation_subject_digest": evaluation_subject_digest,
                        "status": status,
                        "passed_count": passed_count,
                        "failed_count": failed_count,
                        "critical_failed_count": critical_failed_count,
                        "domain_metrics": json.dumps(domain_metrics),
                        "result_payload": json.dumps(result_payload),
                        "result_digest": result_digest,
                        "executed_by": executed_by,
                        "started_at": started_at,
                        "finished_at": finished_at,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _run(row)

    async def run_by_id(
        self, session: AsyncSession, run_id: uuid.UUID
    ) -> EvaluationRunRecord | None:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM enterprise_evaluation_runs WHERE run_id=:id",
                    ),
                    {"id": run_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _run(row) if row else None

    async def activate(
        self,
        session: AsyncSession,
        *,
        revision: OntologyRevisionRecord,
        run: EvaluationRunRecord,
        approver: uuid.UUID,
        release_digest: str,
    ) -> ReleaseAttestation:
        await session.execute(
            text("""
            UPDATE enterprise_ontology_revisions SET state='superseded'
            WHERE state='active'
        """),
        )
        await session.execute(
            text("""
            UPDATE enterprise_release_attestations SET state='superseded'
            WHERE state='active'
        """),
        )
        await session.execute(
            text("""
            UPDATE enterprise_ontology_revisions SET state='active',activated_by=:approver,
              evaluation_run_id=:run_id,activated_at=now()
            WHERE revision_id=:revision_id AND state='approved'
        """),
            {
                "approver": approver,
                "run_id": run.run_id,
                "revision_id": revision.revision_id,
            },
        )
        row = (
            (
                await session.execute(
                    text("""
            INSERT INTO enterprise_release_attestations(
              registry_id,ontology_revision_id,evaluation_run_id,ontology_digest,
              corpus_snapshot_digest,suite_digest,result_digest,release_digest,approved_by
            ) VALUES (
              :registry_id,:revision_id,:run_id,:ontology_digest,:corpus_digest,
              :suite_digest,:result_digest,:release_digest,:approver
            ) RETURNING *
        """),
                    {
                        "registry_id": revision.registry_id,
                        "revision_id": revision.revision_id,
                        "run_id": run.run_id,
                        "ontology_digest": run.ontology_digest,
                        "corpus_digest": run.corpus_snapshot_digest,
                        "suite_digest": run.suite_digest,
                        "result_digest": run.result_digest,
                        "release_digest": release_digest,
                        "approver": approver,
                    },
                )
            )
            .mappings()
            .one()
        )
        return ReleaseAttestation.model_validate(dict(row))

    async def active_release(self, session: AsyncSession) -> ReleaseAttestation | None:
        row = (
            (
                await session.execute(
                    text("""
            SELECT * FROM enterprise_release_attestations WHERE state='active'
            ORDER BY activated_at DESC LIMIT 1
        """)
                )
            )
            .mappings()
            .one_or_none()
        )
        return ReleaseAttestation.model_validate(dict(row)) if row else None
