import hashlib
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.governance.models import ResearchPackage, ResearchRecord, ResearchSource
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)

GOVERNANCE_TABLES = (
    "research_sources",
    "research_packages",
    "research_records",
    "gaps",
    "gap_transitions",
    "review_tasks",
    "graduation_proposals",
    "governance_settings",
    "enterprise_domains",
    "enterprise_corpus_manifests",
    "enterprise_ontology_revisions",
    "enterprise_evaluation_suites",
    "enterprise_evaluation_runs",
    "enterprise_release_attestations",
)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def actor() -> uuid.UUID:
    return uuid.uuid4()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def insert_actor(
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,'governance-integration',:sub,:email,'rtrobotics.com')
        """), {
            "id": actor_id,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
        })


def build_source(owner_id: uuid.UUID) -> ResearchSource:
    return ResearchSource(
        stable_key=f"refinery.{uuid.uuid4().hex}",
        display_name="Synthetic refinery corpus",
        origin="refinery",
        owner_subject_id=owner_id,
        classification="internal",
    )


def build_package(
    source_id: uuid.UUID,
    importer_id: uuid.UUID,
    *,
    fingerprint: str | None = None,
) -> ResearchPackage:
    return ResearchPackage(
        source_id=source_id,
        fingerprint=fingerprint or digest(uuid.uuid4().hex),
        payload_sha256=digest(uuid.uuid4().hex),
        snapshot_manifest={
            "captured_at": "2026-07-01T00:00:00+00:00",
            "scope": "industry",
            "adapter_version": "refinery-adapter-1",
        },
        captured_at=datetime(2026, 7, 1, tzinfo=UTC),
        snapshot_scope="industry",
        adapter_version="refinery-adapter-1",
        importer_subject_id=importer_id,
    )


def build_record(package_id: uuid.UUID, *, ordinal: int = 1) -> ResearchRecord:
    body = f"synthetic research fact {uuid.uuid4().hex}"
    return ResearchRecord(
        package_id=package_id,
        record_key=f"IND.{uuid.uuid4().hex}",
        version_ordinal=ordinal,
        tier="P",
        content={"claim": body},
        searchable_text=body,
        evidence_spans=[{
            "source_url": "https://example.org/source",
            "locator": {"page": 3},
            "quoted_text": body,
            "checksum": digest(body),
        }],
        content_sha256=digest(body),
    )


async def imported_package(
    repository: GovernanceRepository,
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
) -> tuple[ResearchPackage, ResearchRecord]:
    async with factory() as session, session.begin():
        source = await repository.create_source(session, build_source(actor_id))
        intake = await repository.register_package(
            session,
            build_package(source.source_id, actor_id),
        )
        record = await repository.insert_record(
            session,
            build_record(intake.package.package_id),
        )
        await repository.set_package_state(
            session,
            intake.package.package_id,
            from_state="received",
            to_state="validating",
        )
        package = await repository.set_package_state(
            session,
            intake.package.package_id,
            from_state="validating",
            to_state="imported",
            record_count=1,
            tier_composition={"P": 1},
        )
    return package, record


async def insert_sot_version(
    factory: async_sessionmaker[Any],
    owner_id: uuid.UUID,
    *,
    lifecycle: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal SOT package/record/version fixture directly.

    Keeps the TIP-006 integrity invariant the restore drill enforces: an
    active ``records`` row always points at its existing active current
    version; a non-active version leaves the record (and resource) staged.
    """
    package_id = uuid.uuid4()
    record_id = uuid.uuid4()
    version_id = uuid.uuid4()
    checksum = digest(uuid.uuid4().hex)
    record_state = "active" if lifecycle == "active" else "staged"
    resource_state = "active" if lifecycle == "active" else "draft"
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO sot_packages(
              package_id,source_key,revision,schema_version,trust_zone,
              manifest_sha256,payload_sha256,producer,generated_at,
              staging_name,lifecycle
            ) VALUES (
              :package_id,:source_key,1,'1','sot',:checksum,:checksum,
              'governance-tests',now(),:staging,'active'
            )
        """), {
            "package_id": package_id,
            "source_key": f"gov.{uuid.uuid4().hex}",
            "checksum": checksum,
            "staging": f"staging-{package_id.hex}",
        })
        await session.execute(text("""
            INSERT INTO resources(
              resource_id,resource_type,owner_subject_id,classification,
              source_zone,lifecycle_state
            ) VALUES (
              :record_id,'record',:owner_id,'internal','sot',:resource_state
            )
        """), {
            "record_id": record_id,
            "owner_id": owner_id,
            "resource_state": resource_state,
        })
        await session.execute(text("""
            INSERT INTO records(
              record_id,record_key,source_key,owner_subject_id,classification,
              lifecycle
            ) VALUES (
              :record_id,:record_key,'governance-tests',:owner_id,'internal',
              :record_state
            )
        """), {
            "record_id": record_id,
            "record_key": f"GOV.{uuid.uuid4().hex}",
            "owner_id": owner_id,
            "record_state": record_state,
        })
        await session.execute(text("""
            INSERT INTO record_versions(
              version_id,record_id,package_id,package_revision,version_ordinal,
              owner_subject_id,classification,value_payload,searchable_text,
              provenance_level,confidence,verification_state,fact_state,
              effective_from,freshness_policy,freshness_state,source_refs,
              acl_projection,content_sha256,lifecycle
            ) VALUES (
              :version_id,:record_id,:package_id,1,1,:owner_id,'internal',
              '{"value":"governed"}','governed fact','verified_primary',1,
              'verified','verified',now(),'{}','current',
              ARRAY['governance-tests'],'[]',:checksum,:lifecycle
            )
        """), {
            "version_id": version_id,
            "record_id": record_id,
            "package_id": package_id,
            "owner_id": owner_id,
            "checksum": checksum,
            "lifecycle": lifecycle,
        })
        if lifecycle == "active":
            await session.execute(text("""
                UPDATE records SET current_version_id=:version_id,
                  updated_at=now()
                WHERE record_id=:record_id
            """), {"version_id": version_id, "record_id": record_id})
    return version_id, package_id


@pytest.mark.asyncio
async def test_migration_head_provisions_governance_tables(
    factory: async_sessionmaker[Any],
) -> None:
    async with factory() as session:
        revision = await session.scalar(text(
            "SELECT version_num FROM alembic_version",
        ))
        missing = [
            table
            for table in GOVERNANCE_TABLES
            if await session.scalar(
                text("SELECT to_regclass(:name) IS NULL"),
                {"name": f"public.{table}"},
            )
        ]
        shared_indexes = (await session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'research_records'
              AND indexname IN (
                SELECT indexname FROM pg_indexes
                WHERE tablename IN ('records','record_versions')
              )
        """))).scalars().all()
    assert revision == "0014_document_outbox_repair"
    assert missing == []
    assert list(shared_indexes) == []


@pytest.mark.asyncio
async def test_package_fingerprint_idempotency_and_round_trip(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    repository = GovernanceRepository()
    async with factory() as session, session.begin():
        source = await repository.create_source(session, build_source(actor))
        assert await repository.get_source_by_key(session, source.stable_key) == source
        package = build_package(source.source_id, actor)
        first = await repository.register_package(session, package)
        again = await repository.register_package(
            session,
            build_package(source.source_id, actor, fingerprint=package.fingerprint),
        )
        record = await repository.insert_record(
            session,
            build_record(first.package.package_id),
        )
    assert first.created
    assert not again.created
    assert again.package.package_id == first.package.package_id
    async with factory() as session:
        by_fingerprint = await repository.get_package_by_fingerprint(
            session,
            package.fingerprint,
        )
        stored_records = await repository.list_records(
            session,
            first.package.package_id,
        )
    assert by_fingerprint == first.package
    assert stored_records == [record]


@pytest.mark.asyncio
async def test_research_records_and_package_content_are_immutable(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    repository = GovernanceRepository()
    package, record = await imported_package(repository, factory, actor)
    tamper_statements = [
        "UPDATE research_records SET searchable_text='tampered' "
        "WHERE research_record_id=:id",
        "UPDATE research_records SET tier='X' WHERE research_record_id=:id",
        "DELETE FROM research_records WHERE research_record_id=:id",
        "UPDATE research_packages SET fingerprint=:sha "
        "WHERE package_id=:package_id",
        "DELETE FROM research_packages WHERE package_id=:package_id",
    ]
    for statement in tamper_statements:
        with pytest.raises(DBAPIError):
            async with factory() as session, session.begin():
                await session.execute(text(statement), {
                    "id": record.research_record_id,
                    "package_id": package.package_id,
                    "sha": digest("tampered"),
                })
    with pytest.raises(DBAPIError):
        async with factory() as session, session.begin():
            forged = build_record(package.package_id, ordinal=2)
            await session.execute(text("""
                INSERT INTO research_records(
                  research_record_id,package_id,record_key,version_ordinal,
                  tier,zone_label,content,searchable_text,evidence_spans,
                  content_sha256
                ) VALUES (
                  :id,:package_id,:record_key,2,'P','sot','{}','forged',
                  '[{"checksum":"deadbeef"}]',:sha
                )
            """), {
                "id": forged.research_record_id,
                "package_id": package.package_id,
                "record_key": forged.record_key,
                "sha": forged.content_sha256,
            })
    with pytest.raises(GovernanceError, match="package_transition_invalid"):
        async with factory() as session, session.begin():
            await repository.set_package_state(
                session,
                package.package_id,
                from_state="imported",
                to_state="rejected",
                rejection_code="late_rejection",
            )
    with pytest.raises(GovernanceError, match="package_state_conflict"):
        async with factory() as session, session.begin():
            await repository.set_package_state(
                session,
                package.package_id,
                from_state="received",
                to_state="validating",
            )


@pytest.mark.asyncio
async def test_gap_dedupe_lifecycle_and_append_only_history(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    curator = uuid.uuid4()
    await insert_actor(factory, curator)
    repository = GovernanceRepository()
    question_digest = digest(f"question {uuid.uuid4().hex}")
    async with factory() as session, session.begin():
        gap = await repository.create_or_increment_gap(
            session,
            question_digest=question_digest,
            sanitized_question="What is the governed answer?",
            sanitized_summary="governed answer",
            requester_id=actor,
            routing_key="curator:sot",
            origin="manual",
            reason_category="manual_entry",
        )
        repeated = await repository.create_or_increment_gap(
            session,
            question_digest=question_digest,
            sanitized_question="What is the governed answer?",
            sanitized_summary="governed answer",
            requester_id=actor,
            routing_key="curator:sot",
            origin="manual",
            reason_category="manual_entry",
        )
    assert repeated.gap_id == gap.gap_id
    assert repeated.occurrence_count == 2
    active_version, _ = await insert_sot_version(factory, actor, lifecycle="active")
    staged_version, _ = await insert_sot_version(factory, actor, lifecycle="staged")
    async with factory() as session, session.begin():
        with pytest.raises(GovernanceError, match="gap_transition_invalid"):
            await repository.transition_gap(
                session,
                gap.gap_id,
                to_state="answered",
                actor_subject_id=curator,
                reason="skip triage",
                resolving_version_id=active_version,
            )
        await repository.transition_gap(
            session,
            gap.gap_id,
            to_state="triaged",
            actor_subject_id=curator,
            reason="triaged for owner",
        )
        await repository.transition_gap(
            session,
            gap.gap_id,
            to_state="assigned",
            actor_subject_id=curator,
            reason="assigned to curator",
            owner_subject_id=curator,
            due_at=datetime.now(UTC),
        )
        with pytest.raises(GovernanceError, match="record_version_not_active"):
            await repository.transition_gap(
                session,
                gap.gap_id,
                to_state="answered",
                actor_subject_id=curator,
                reason="staged record must not close a gap",
                resolving_version_id=staged_version,
            )
        answered = await repository.transition_gap(
            session,
            gap.gap_id,
            to_state="answered",
            actor_subject_id=curator,
            reason="answered by activated record",
            resolving_version_id=active_version,
        )
        published = await repository.transition_gap(
            session,
            gap.gap_id,
            to_state="published",
            actor_subject_id=curator,
            reason="record activated through publish gate",
        )
        history = await repository.list_gap_transitions(session, gap.gap_id)
        page = await repository.list_gaps(session, state="published", limit=50)
    assert answered.resolving_version_id == active_version
    assert published.lifecycle == "published"
    assert published.closed_at is not None
    assert [(item.from_state, item.to_state) for item in history] == [
        ("open", "triaged"),
        ("triaged", "assigned"),
        ("assigned", "answered"),
        ("answered", "published"),
    ]
    assert any(item.gap_id == gap.gap_id for item in page.items)
    async with factory() as session, session.begin():
        with pytest.raises(GovernanceError, match="gap_transition_invalid"):
            await repository.transition_gap(
                session,
                gap.gap_id,
                to_state="declined",
                actor_subject_id=curator,
                reason="published gaps are closed",
                decline_reason="not applicable",
            )
    tamper_statements = [
        "UPDATE gap_transitions SET reason='tampered' WHERE gap_id=:gap_id",
        "DELETE FROM gap_transitions WHERE gap_id=:gap_id",
        "UPDATE gaps SET lifecycle='open' WHERE gap_id=:gap_id",
        "DELETE FROM gaps WHERE gap_id=:gap_id",
    ]
    for statement in tamper_statements:
        with pytest.raises(DBAPIError):
            async with factory() as session, session.begin():
                await session.execute(text(statement), {"gap_id": gap.gap_id})


@pytest.mark.asyncio
async def test_declined_gap_reason_is_immutable(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    repository = GovernanceRepository()
    async with factory() as session, session.begin():
        gap = await repository.create_or_increment_gap(
            session,
            question_digest=digest(f"declined {uuid.uuid4().hex}"),
            sanitized_question="Out of scope question",
            sanitized_summary="out of scope",
            requester_id=actor,
            routing_key="curator:sot",
            origin="manual",
            reason_category="manual_entry",
        )
        with pytest.raises(GovernanceError, match="gap_decline_reason_required"):
            await repository.transition_gap(
                session,
                gap.gap_id,
                to_state="declined",
                actor_subject_id=actor,
                reason="attempt without reason",
            )
        declined = await repository.transition_gap(
            session,
            gap.gap_id,
            to_state="declined",
            actor_subject_id=actor,
            reason="declined as out of scope",
            decline_reason="outside company knowledge scope",
        )
    assert declined.decline_reason == "outside company knowledge scope"
    with pytest.raises(DBAPIError):
        async with factory() as session, session.begin():
            await session.execute(text("""
                UPDATE gaps SET decline_reason='rewritten' WHERE gap_id=:gap_id
            """), {"gap_id": gap.gap_id})


@pytest.mark.asyncio
async def test_review_task_assignment_upsert_and_reopen(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    other = uuid.uuid4()
    await insert_actor(factory, other)
    repository = GovernanceRepository()
    version_id, _ = await insert_sot_version(factory, actor, lifecycle="active")
    async with factory() as session, session.begin():
        task = await repository.upsert_review_task(
            session,
            queue_kind="freshness",
            record_version_id=version_id,
            assignee_subject_id=actor,
            assigned_by=actor,
        )
        reassigned = await repository.upsert_review_task(
            session,
            queue_kind="freshness",
            record_version_id=version_id,
            assignee_subject_id=other,
            assigned_by=actor,
        )
        completed = await repository.complete_review_task(session, task.task_id)
        with pytest.raises(GovernanceError, match="review_task_state_conflict"):
            await repository.complete_review_task(session, task.task_id)
        reopened = await repository.upsert_review_task(
            session,
            queue_kind="freshness",
            record_version_id=version_id,
            assignee_subject_id=other,
            assigned_by=actor,
        )
        listed = await repository.list_review_tasks(
            session,
            queue_kind="freshness",
            assignee_subject_id=other,
        )
    assert reassigned.task_id == task.task_id
    assert reassigned.assignee_subject_id == other
    assert completed.state == "completed"
    assert reopened.state == "reopened"
    assert reopened.completed_at is None
    assert any(item.task_id == task.task_id for item in listed)


@pytest.mark.asyncio
async def test_graduation_separation_of_duties_and_immutable_decisions(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    decider = uuid.uuid4()
    await insert_actor(factory, decider)
    repository = GovernanceRepository()
    package, record = await imported_package(repository, factory, actor)
    async with factory() as session, session.begin():
        pending = await repository.register_package(
            session,
            build_package(package.source_id, actor),
        )
        unimported_record = await repository.insert_record(
            session,
            build_record(pending.package.package_id),
        )
        with pytest.raises(GovernanceError, match="research_record_not_graduatable"):
            await repository.create_proposal(
                session,
                research_record_ids=[unimported_record.research_record_id],
                claim_draft={"claim": "from unimported package"},
                target_record_key="COMPANY.CLAIM.1",
                proposer_subject_id=actor,
                rationale="must be rejected",
            )
        with pytest.raises(GovernanceError, match="research_record_not_graduatable"):
            await repository.create_proposal(
                session,
                research_record_ids=[uuid.uuid4()],
                claim_draft={"claim": "missing record"},
                target_record_key="COMPANY.CLAIM.1",
                proposer_subject_id=actor,
                rationale="must be rejected",
            )
        proposal = await repository.create_proposal(
            session,
            research_record_ids=[record.research_record_id],
            claim_draft={"claim": "graduated synthetic claim"},
            target_record_key="COMPANY.CLAIM.1",
            proposer_subject_id=actor,
            rationale="verbatim evidence supports the claim",
        )
        with pytest.raises(GovernanceError, match="proposer_cannot_decide"):
            await repository.decide_proposal(
                session,
                proposal.proposal_id,
                decider_subject_id=actor,
                decision="approved",
                decision_reason="self approval must fail",
                attestation_hash=digest("self"),
            )
        approved = await repository.decide_proposal(
            session,
            proposal.proposal_id,
            decider_subject_id=decider,
            decision="approved",
            decision_reason="evidence verified",
            attestation_hash=digest("decision"),
        )
        with pytest.raises(GovernanceError, match="proposal_already_decided"):
            await repository.decide_proposal(
                session,
                proposal.proposal_id,
                decider_subject_id=decider,
                decision="rejected",
                decision_reason="double decision must fail",
                attestation_hash=digest("again"),
            )
    assert approved.state == "approved"
    assert approved.decided_by == decider
    _, sot_package_id = await insert_sot_version(factory, actor, lifecycle="active")
    async with factory() as session, session.begin():
        submitted = await repository.attach_publish_submission(
            session,
            proposal.proposal_id,
            publish_package_id=sot_package_id,
        )
        with pytest.raises(GovernanceError, match="proposal_submission_conflict"):
            await repository.attach_publish_submission(
                session,
                proposal.proposal_id,
                publish_package_id=sot_package_id,
            )
    assert submitted.publish_package_id == sot_package_id
    tamper_statements = [
        "UPDATE graduation_proposals SET claim_draft='{}' "
        "WHERE proposal_id=:proposal_id",
        "UPDATE graduation_proposals SET attestation_hash=:sha "
        "WHERE proposal_id=:proposal_id",
        "UPDATE graduation_proposals SET state='rejected' "
        "WHERE proposal_id=:proposal_id",
        "DELETE FROM graduation_proposals WHERE proposal_id=:proposal_id",
    ]
    for statement in tamper_statements:
        with pytest.raises(DBAPIError):
            async with factory() as session, session.begin():
                await session.execute(text(statement), {
                    "proposal_id": proposal.proposal_id,
                    "sha": digest("forged"),
                })


@pytest.mark.asyncio
async def test_governance_settings_are_versioned_and_append_only(
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    repository = GovernanceRepository()
    setting_key = f"gap.sla.assign_hours.{uuid.uuid4().hex[:8]}"
    async with factory() as session, session.begin():
        with pytest.raises(GovernanceError, match="setting_value_type_mismatch"):
            await repository.set_setting(
                session,
                setting_key=setting_key,
                value_type="duration_hours",
                value="48",
                updated_by=actor,
                reason="typed values only",
            )
        first = await repository.set_setting(
            session,
            setting_key=setting_key,
            value_type="duration_hours",
            value=48,
            updated_by=actor,
            reason="initial SLA window",
        )
        second = await repository.set_setting(
            session,
            setting_key=setting_key,
            value_type="duration_hours",
            value=24,
            updated_by=actor,
            reason="tightened SLA window",
        )
        latest = await repository.get_setting(session, setting_key)
        versions = await repository.list_setting_versions(session, setting_key)
    assert (first.version, second.version) == (1, 2)
    assert latest == second
    assert latest is not None and latest.value == 24
    assert [item.version for item in versions] == [1, 2]
    tamper_statements = [
        "UPDATE governance_settings SET value='9999' WHERE setting_key=:key",
        "DELETE FROM governance_settings WHERE setting_key=:key",
    ]
    for statement in tamper_statements:
        with pytest.raises(DBAPIError):
            async with factory() as session, session.begin():
                await session.execute(text(statement), {"key": setting_key})
