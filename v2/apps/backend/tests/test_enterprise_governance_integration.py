import hashlib
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.enterprise.models import (
    CorpusManifestSpec,
    CorpusSourceRef,
    DecisionInput,
    DomainCreate,
    EvaluationCase,
    EvaluationExpectation,
    EvaluationSuiteSpec,
    digest_of,
)
from rtr_copilot.enterprise.repository import EnterpriseError, EnterpriseRepository
from rtr_copilot.enterprise.service import EnterpriseService
from rtr_copilot.rag.ontology import OntologyEntity, OntologySpec, load_runtime_ontology

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
OWNER_DSN = os.getenv("MIGRATION_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def owner_factory() -> async_sessionmaker[Any]:
    assert OWNER_DSN
    engine = create_async_engine(
        OWNER_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def subject(actor_id: uuid.UUID, roles: set[Role]) -> Subject:
    return Subject(
        user_id=str(actor_id),
        issuer="enterprise-integration",
        sub=actor_id.hex,
        email=f"{actor_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles=roles,
    )


async def seed_subjects_and_research(
    factory: async_sessionmaker[Any],
    subject_ids: tuple[uuid.UUID, ...],
) -> tuple[str, str]:
    source_key = f"enterprise.policy.{uuid.uuid4().hex}"
    fingerprint = sha(source_key)
    source_id = uuid.uuid4()
    package_id = uuid.uuid4()
    async with factory() as session, session.begin():
        for actor_id in subject_ids:
            await session.execute(
                text("""
                INSERT INTO subjects(
                  user_id,issuer,provider_sub,email,canonical_domain,status
                ) VALUES (
                  :id,'enterprise-integration',:sub,:email,'rtrobotics.com','active'
                )
            """),
                {
                    "id": actor_id,
                    "sub": actor_id.hex,
                    "email": f"{actor_id.hex}@rtrobotics.com",
                },
            )
        await session.execute(
            text("""
            INSERT INTO research_sources(
              source_id,stable_key,display_name,origin,owner_subject_id,
              classification,lifecycle
            ) VALUES (
              :source_id,:key,'Enterprise policy corpus','manual',:owner,
              'internal','active'
            )
        """),
            {"source_id": source_id, "key": source_key, "owner": subject_ids[2]},
        )
        await session.execute(
            text("""
            INSERT INTO research_packages(
              package_id,source_id,fingerprint,payload_sha256,snapshot_manifest,
              captured_at,snapshot_scope,adapter_version,tier_composition,
              import_state,record_count,importer_subject_id,imported_at
            ) VALUES (
              :package_id,:source_id,:fingerprint,:fingerprint,
              CAST(:manifest AS jsonb),now(),'enterprise-policy','manual-1','{}',
              'imported',0,:importer,now()
            )
        """),
            {
                "package_id": package_id,
                "source_id": source_id,
                "fingerprint": fingerprint,
                "manifest": ('{"adapter_version":"manual-1","scope":"enterprise-policy"}'),
                "importer": subject_ids[0],
            },
        )
    return source_key, fingerprint


def ontology_spec(suffix: str) -> OntologySpec:
    return OntologySpec(
        schema_version=1,
        registry_id=f"enterprise.integration.{suffix}",
        owner="Enterprise Architecture",
        entities=(
            OntologyEntity(
                entity_id="policy.integration",
                canonical_name="Integration Policy",
                entity_type="policy",
                domain="policy",
                aliases=("integration rule",),
                owner="Policy Owner",
                provenance_level="approved_internal",
            ),
        ),
    )


def evaluation_suite(domain_key: str, suffix: str) -> EvaluationSuiteSpec:
    return EvaluationSuiteSpec(
        suite_key=f"enterprise.integration.{suffix}",
        cases=(
            EvaluationCase(
                case_id="policy.query.open",
                domain_key=domain_key,
                risk_class="critical",
                kind="query",
                question="What policy evidence applies?",
                expectation=EvaluationExpectation(resolution_state="open"),
            ),
            EvaluationCase(
                case_id="policy.retrieval.required",
                domain_key=domain_key,
                risk_class="high",
                kind="retrieval",
                question="Find policy evidence",
                expectation=EvaluationExpectation(
                    required_record_keys=("POLICY.INTEGRATION",),
                ),
            ),
            EvaluationCase(
                case_id="policy.answer.grounded",
                domain_key=domain_key,
                risk_class="standard",
                kind="answer",
                question="Summarize the integration policy",
                expectation=EvaluationExpectation(
                    answer_state="grounded",
                    required_record_keys=("POLICY.INTEGRATION",),
                ),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_enterprise_onboarding_release_and_drift_gate(
    factory: async_sessionmaker[Any],
    owner_factory: async_sessionmaker[Any],
) -> None:
    curator_id, leader_id, owner_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    source_key, fingerprint = await seed_subjects_and_research(
        factory,
        (curator_id, leader_id, owner_id),
    )
    curator = subject(curator_id, {Role.CURATOR, Role.LEADER})
    leader = subject(leader_id, {Role.LEADER})
    service = EnterpriseService(factory)
    suffix = uuid.uuid4().hex[:12]
    domain_key = f"policy.{suffix}"

    domain = await service.propose_domain(
        curator,
        DomainCreate(
            domain_key=domain_key,
            display_name="Enterprise Policy",
            owner_subject_id=owner_id,
            minimum_eval_cases=3,
        ),
        request_id=f"tip025-domain-{suffix}",
    )
    with pytest.raises(PermissionError, match="separation_of_duties"):
        await service.decide_domain(
            curator,
            domain.domain_id,
            DecisionInput(decision="approved", reason="self"),
            request_id=f"tip025-domain-self-{suffix}",
        )
    domain = await service.decide_domain(
        leader,
        domain.domain_id,
        DecisionInput(decision="approved", reason="independent review"),
        request_id=f"tip025-domain-approve-{suffix}",
    )
    assert domain.state == "active"

    manifest = await service.propose_manifest(
        curator,
        CorpusManifestSpec(
            domain_key=domain_key,
            sources=(
                CorpusSourceRef(
                    kind="research",
                    source_key=source_key,
                    fingerprint=fingerprint,
                ),
            ),
        ),
        version=1,
        request_id=f"tip025-manifest-{suffix}",
    )
    validation = await service.validate_manifest(
        curator,
        manifest.manifest_id,
        request_id=f"tip025-validate-{suffix}",
    )
    manifest = await service.decide_manifest(
        leader,
        manifest.manifest_id,
        DecisionInput(decision="approved", reason="fingerprints reviewed"),
        request_id=f"tip025-manifest-approve-{suffix}",
    )
    assert manifest.state == "active"
    assert manifest.validated_snapshot_digest == validation.snapshot_digest

    revision = await service.propose_ontology(
        curator,
        ontology_spec(suffix),
        version=1,
        request_id=f"tip025-ontology-{suffix}",
    )
    revision = await service.decide_ontology(
        leader,
        revision.revision_id,
        DecisionInput(decision="approved", reason="ontology reviewed"),
        request_id=f"tip025-ontology-approve-{suffix}",
    )
    suite = await service.propose_suite(
        curator,
        evaluation_suite(domain_key, suffix),
        version=1,
        request_id=f"tip025-suite-{suffix}",
    )
    suite = await service.decide_suite(
        leader,
        suite.suite_id,
        DecisionInput(decision="approved", reason="matrix reviewed"),
        request_id=f"tip025-suite-approve-{suffix}",
    )

    incomplete = await service.run_suite(
        curator,
        suite.suite_id,
        revision.revision_id,
        request_id=f"tip025-eval-{suffix}",
    )
    assert incomplete.status == "incomplete"
    assert incomplete.result_payload["answer_quality_configured"] is False
    with pytest.raises(EnterpriseError, match="enterprise_release_gate_failed"):
        await service.activate_ontology(
            leader,
            revision.revision_id,
            incomplete.run_id,
            reason="must not activate incomplete",
            request_id=f"tip025-activate-denied-{suffix}",
        )

    repository = EnterpriseRepository()
    async with factory() as session:
        corpus_digest, _, _, errors = await repository.current_corpus_snapshot(session)
    assert errors == []
    now = datetime.now(UTC)
    synthetic_result = digest_of({"suite": suite.suite_digest, "result": "passed"})
    async with UnitOfWork(factory).transaction() as session:
        passed = await repository.create_run(
            session,
            suite_id=suite.suite_id,
            ontology_revision_id=revision.revision_id,
            ontology_digest=revision.ontology_digest,
            suite_digest=suite.suite_digest,
            corpus_snapshot_digest=corpus_digest,
            evaluation_subject_digest=digest_of(curator.user_id),
            status="passed",
            passed_count=3,
            failed_count=0,
            critical_failed_count=0,
            domain_metrics={domain_key: {"total": 3, "passed": 3, "failed": 0}},
            result_payload={"schema_version": 1, "case_results": []},
            result_digest=synthetic_result,
            executed_by=curator_id,
            started_at=now,
            finished_at=now,
        )
    attestation = await service.activate_ontology(
        leader,
        revision.revision_id,
        passed.run_id,
        reason="independent quality attestation",
        request_id=f"tip025-activate-{suffix}",
    )
    assert attestation.state == "active"
    assert (await service.readiness(leader, request_id=f"tip025-ready-{suffix}")).ready
    runtime = await load_runtime_ontology(factory)
    assert runtime.digest == revision.ontology_digest
    assert runtime.by_id["policy.integration"].canonical_name == "Integration Policy"

    async with factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE research_sources SET lifecycle='suspended' WHERE stable_key=:key",
            ),
            {"key": source_key},
        )
    readiness = await service.readiness(leader, request_id=f"tip025-drift-{suffix}")
    assert not readiness.ready
    assert readiness.code == "corpus_drift_detected"

    with pytest.raises(DBAPIError, match="permission denied"):
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                UPDATE enterprise_evaluation_runs SET passed_count=2 WHERE run_id=:run_id
            """),
                {"run_id": passed.run_id},
            )
    with pytest.raises(DBAPIError, match="enterprise evaluation history is immutable"):
        async with owner_factory() as session, session.begin():
            await session.execute(
                text("""
                UPDATE enterprise_evaluation_runs SET passed_count=2 WHERE run_id=:run_id
            """),
                {"run_id": passed.run_id},
            )
