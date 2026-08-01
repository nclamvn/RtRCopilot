"""TIP-010 Task 6/7 integration: admin surfaces, AC-11 boundary, dashboard."""

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from research_fixtures import build_research_package, research_record_row
from sot_fixtures import SECRET
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.admin import AdminGovernanceService, JobFailureView
from rtr_copilot.governance.api import governance_subject
from rtr_copilot.governance.dashboard import DashboardService
from rtr_copilot.governance.service import GapTransitionInput, GovernanceService
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.research.service import ResearchService

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)

ISSUER = "governance-admin-tests"


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def admin_service(factory: async_sessionmaker[Any]) -> AdminGovernanceService:
    return AdminGovernanceService(uow=UnitOfWork(factory))


@pytest.fixture
def research_service(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> ResearchService:
    staging = tmp_path / "research-staging"
    staging.mkdir()
    settings = get_settings().model_copy(update={
        "research_staging_root": staging,
        "sot_staging_root": tmp_path / "sot-staging",
        "sot_signing_secret": SecretStr(SECRET),
        "rag_provider_mode": "local",
    })
    return ResearchService(settings, factory=factory)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def subject(role: Role, user_id: uuid.UUID) -> Subject:
    return Subject(
        user_id=str(user_id),
        issuer=ISSUER,
        sub=user_id.hex,
        email=f"{user_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


async def insert_actor(
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,:issuer,:sub,:email,'rtrobotics.com')
        """), {
            "id": actor_id,
            "issuer": ISSUER,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
        })


async def insert_sot_version(
    factory: async_sessionmaker[Any],
    owner_id: uuid.UUID,
    *,
    source_key: str | None = None,
    effective_to: datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """One active SOT package/record/version owned by ``owner_id``."""
    package_id, record_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    checksum = digest(uuid.uuid4().hex)
    source_key = source_key or f"admin.cov.{uuid.uuid4().hex[:8]}"
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO sot_packages(
              package_id,source_key,revision,schema_version,trust_zone,
              manifest_sha256,payload_sha256,producer,generated_at,
              staging_name,lifecycle
            ) VALUES (
              :package_id,:source_key,1,'1','sot',:checksum,:checksum,
              'governance-admin-tests',now(),:staging,'active'
            )
        """), {
            "package_id": package_id,
            "source_key": source_key,
            "checksum": checksum,
            "staging": f"staging-{package_id.hex}",
        })
        await session.execute(text("""
            INSERT INTO resources(
              resource_id,resource_type,owner_subject_id,classification,
              source_zone,lifecycle_state
            ) VALUES (:record_id,'record',:owner_id,'internal','sot','active')
        """), {"record_id": record_id, "owner_id": owner_id})
        await session.execute(text("""
            INSERT INTO records(
              record_id,record_key,source_key,owner_subject_id,
              classification,lifecycle
            ) VALUES (
              :record_id,:record_key,:source_key,:owner_id,'internal','active'
            )
        """), {
            "record_id": record_id,
            "record_key": f"ADMIN.{uuid.uuid4().hex}",
            "source_key": source_key,
            "owner_id": owner_id,
        })
        await session.execute(text("""
            INSERT INTO record_versions(
              version_id,record_id,package_id,package_revision,version_ordinal,
              owner_subject_id,classification,value_payload,searchable_text,
              provenance_level,confidence,verification_state,fact_state,
              effective_from,effective_to,freshness_policy,freshness_due_at,
              freshness_state,source_refs,acl_projection,content_sha256,
              lifecycle
            ) VALUES (
              :version_id,:record_id,:package_id,1,1,:owner_id,'internal',
              '{"value":"governed"}','governed fact','verified_primary',1,
              'verified','verified',:effective_from,:effective_to,'{}',NULL,
              'current',ARRAY['governance-admin-tests'],'[]',:checksum,'active'
            )
        """), {
            "version_id": version_id,
            "record_id": record_id,
            "package_id": package_id,
            "owner_id": owner_id,
            "effective_from": datetime.now(UTC) - timedelta(days=10),
            "effective_to": effective_to,
            "checksum": checksum,
        })
        await session.execute(text("""
            UPDATE records SET current_version_id=:version_id
            WHERE record_id=:record_id
        """), {"version_id": version_id, "record_id": record_id})
    return version_id, record_id


async def audit_actions_by_detail(
    factory: async_sessionmaker[Any],
    key: str,
    value: str,
) -> list[str]:
    async with factory() as session:
        rows = (await session.execute(text(f"""
            SELECT action FROM audit_events
            WHERE details->>'{key}'=:value ORDER BY sequence
        """), {"value": value})).scalars()
        return list(rows)


async def create_manual_gap(
    factory: async_sessionmaker[Any],
    requester_id: uuid.UUID,
) -> uuid.UUID:
    async with factory() as session, session.begin():
        gap = await GovernanceRepository().create_or_increment_gap(
            session,
            question_digest=digest(f"admin question {uuid.uuid4().hex}"),
            sanitized_question="Which governed answer is missing?",
            sanitized_summary="governed answer",
            requester_id=requester_id,
            routing_key="curator:sot",
            origin="manual",
            reason_category="manual_entry",
        )
    return gap.gap_id


@pytest.mark.asyncio
async def test_source_crud_is_admin_gated_bounded_and_audited(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
) -> None:
    admin_id, owner_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, admin_id)
    await insert_actor(factory, owner_id)
    admin = subject(Role.ADMIN, admin_id)
    stable_key = f"refinery.admin.{uuid.uuid4().hex[:12]}"
    with pytest.raises(PermissionError, match="admin_required"):
        await admin_service.create_source(
            subject(Role.CURATOR, owner_id),
            stable_key=stable_key,
            display_name="curators cannot register sources",
            description="",
            origin="refinery",
            owner_subject_id=owner_id,
            classification="internal",
            lifecycle="active",
            request_id="src-0",
        )
    with pytest.raises(GovernanceError, match="owner_subject_unknown"):
        await admin_service.create_source(
            admin,
            stable_key=stable_key,
            display_name="unknown owner",
            description="",
            origin="refinery",
            owner_subject_id=uuid.uuid4(),
            classification="internal",
            lifecycle="active",
            request_id="src-1",
        )
    created = await admin_service.create_source(
        admin,
        stable_key=stable_key,
        display_name="Synthetic refinery corpus",
        description="admin-governed source",
        origin="refinery",
        owner_subject_id=owner_id,
        classification="internal",
        lifecycle="active",
        request_id="src-2",
    )
    with pytest.raises(GovernanceError, match="research_source_exists"):
        await admin_service.create_source(
            admin,
            stable_key=stable_key,
            display_name="duplicate key",
            description="",
            origin="manual",
            owner_subject_id=owner_id,
            classification="internal",
            lifecycle="active",
            request_id="src-3",
        )
    detail = await admin_service.source_detail(
        admin,
        created.source_id,
        request_id="src-4",
    )
    assert detail.stable_key == stable_key
    listed = await admin_service.list_sources(admin, request_id="src-5")
    assert created.source_id in {source.source_id for source in listed}
    with pytest.raises(GovernanceError, match="source_update_empty"):
        await admin_service.update_source(
            admin,
            created.source_id,
            reason="nothing to change",
            request_id="src-6",
        )
    with pytest.raises(GovernanceError, match="research_source_not_found"):
        await admin_service.update_source(
            admin,
            uuid.uuid4(),
            lifecycle="suspended",
            reason="unknown source",
            request_id="src-7",
        )
    updated = await admin_service.update_source(
        admin,
        created.source_id,
        display_name="Renamed refinery corpus",
        lifecycle="suspended",
        reason="operational pause",
        request_id="src-8",
    )
    assert updated.display_name == "Renamed refinery corpus"
    assert updated.lifecycle == "suspended"
    assert updated.stable_key == stable_key, "stable key is immutable"
    assert updated.updated_at > created.updated_at
    actions = await audit_actions_by_detail(
        factory,
        "source_id",
        str(created.source_id),
    )
    assert actions == ["governance.source.create", "governance.source.update"]


@pytest.mark.asyncio
async def test_source_classification_change_immediately_revokes_research_reads(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
    research_service: ResearchService,
) -> None:
    """AC-14 / Builder 3 D3: research visibility binds at source level, so an
    admin classification UPDATE is the revocation lever and takes effect on
    the very next read with no refresh step in between."""
    admin_id, owner_id, curator_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for actor_id in (admin_id, owner_id, curator_id):
        await insert_actor(factory, actor_id)
    admin = subject(Role.ADMIN, admin_id)
    owner = subject(Role.STAFF, owner_id)
    curator = subject(Role.CURATOR, curator_id)
    source = await admin_service.create_source(
        admin,
        stable_key=f"refinery.revoke.{uuid.uuid4().hex[:12]}",
        display_name="Revocation lever source",
        description="",
        origin="refinery",
        owner_subject_id=owner_id,
        classification="internal",
        lifecycle="active",
        request_id="revoke-0",
    )
    token = f"revocation{uuid.uuid4().hex[:8]}"
    staging = build_research_package(
        Path(research_service.settings.research_staging_root),
        source_key=source.stable_key,
        records=[research_record_row(text=f"insight about {token}")],
    )
    imported = await research_service.import_package(
        curator,
        staging,
        request_id="revoke-1",
    )
    async with factory() as session:
        record_id = await session.scalar(text("""
            SELECT research_record_id FROM research_records
            WHERE package_id=:package_id
        """), {"package_id": imported.package.package_id})
    record = await research_service.record_detail(
        owner,
        record_id,
        request_id="revoke-2",
    )
    assert record.zone_label == "research"
    hits = await research_service.search(curator, token, request_id="revoke-3")
    assert {hit.research_record_id for hit in hits.results} == {record_id}
    escalated = await admin_service.update_source(
        admin,
        source.source_id,
        classification="highly_restricted",
        reason="containment escalation",
        request_id="revoke-4",
    )
    assert escalated.classification == "highly_restricted"
    with pytest.raises(GovernanceError, match="research_record_not_found"):
        await research_service.record_detail(owner, record_id, request_id="revoke-5")
    with pytest.raises(GovernanceError, match="research_record_not_found"):
        await research_service.record_detail(
            curator,
            record_id,
            request_id="revoke-6",
        )
    hits_after = await research_service.search(
        curator,
        token,
        request_id="revoke-7",
    )
    assert hits_after.results == []
    packages = await research_service.list_packages(owner, request_id="revoke-8")
    assert imported.package.package_id not in {
        package.package_id for package in packages.items
    }
    # The lifecycle column is the second live lever: suspension hides content
    # from search on the next read as well.
    downgraded = await admin_service.update_source(
        admin,
        source.source_id,
        classification="internal",
        lifecycle="suspended",
        reason="suspended pending review",
        request_id="revoke-9",
    )
    assert downgraded.lifecycle == "suspended"
    hits_suspended = await research_service.search(
        curator,
        token,
        request_id="revoke-10",
    )
    assert hits_suspended.results == []


@pytest.mark.asyncio
async def test_settings_overview_and_versions_are_typed_and_admin_gated(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
) -> None:
    admin_id, curator_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, admin_id)
    await insert_actor(factory, curator_id)
    admin = subject(Role.ADMIN, admin_id)
    with pytest.raises(PermissionError, match="admin_required"):
        await admin_service.settings_overview(
            subject(Role.CURATOR, curator_id),
            request_id="set-0",
        )
    with pytest.raises(GovernanceError, match="setting_unknown"):
        await admin_service.setting_versions(
            admin,
            "gap.sla.unregistered",
            request_id="set-1",
        )
    governance = GovernanceService(uow=UnitOfWork(factory))
    first = await governance.update_setting(
        admin,
        setting_key="gap.sla.triage_hours",
        value=12,
        reason="tighter triage pilot",
        request_id="set-2",
    )
    second = await governance.update_setting(
        admin,
        setting_key="gap.sla.triage_hours",
        value=36,
        reason="relaxed after review",
        request_id="set-3",
    )
    assert second.version == first.version + 1
    overview = {view.setting_key: view for view in await admin_service.settings_overview(
        admin,
        request_id="set-4",
    )}
    assert set(overview) == {
        "gap.sla.triage_hours",
        "gap.sla.assign_hours",
        "queue.freshness.expiring_hours",
        "queue.owner_review.upcoming_hours",
        # TIP-012 Task 2 — cost budgets and job concurrency caps.
        "limits.budget.subject_daily_units",
        "limits.budget.global_daily_units",
        "limits.jobs.ingestion_max_inflight",
        "limits.jobs.render_max_inflight",
        "limits.jobs.index_max_backlog",
    }
    assert overview["limits.budget.subject_daily_units"].value_type == "integer"
    assert overview["limits.jobs.index_max_backlog"].value == 200
    triage = overview["gap.sla.triage_hours"]
    assert triage.value == 36
    assert triage.version == second.version
    assert triage.value_type == "duration_hours"
    assert triage.minimum == 1
    versions = await admin_service.setting_versions(
        admin,
        "gap.sla.triage_hours",
        request_id="set-5",
    )
    assert [item.version for item in versions][-2:] == [
        first.version,
        second.version,
    ]
    assert versions[-1].value == 36
    assert versions[-2].value == 12


@pytest.mark.asyncio
async def test_binding_management_is_bounded_audited_and_effective(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
) -> None:
    admin_id, target_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, admin_id)
    await insert_actor(factory, target_id)
    admin = subject(Role.ADMIN, admin_id)
    with pytest.raises(PermissionError, match="admin_required"):
        await admin_service.mutate_binding(
            subject(Role.CURATOR, admin_id),
            target_id,
            binding="role",
            key="curator",
            operation="assign",
            reason="curators cannot manage bindings",
            request_id="bind-0",
        )
    with pytest.raises(GovernanceError, match="subject_not_found"):
        await admin_service.mutate_binding(
            admin,
            uuid.uuid4(),
            binding="role",
            key="curator",
            operation="assign",
            reason="unknown subject",
            request_id="bind-1",
        )
    with pytest.raises(GovernanceError, match="role_unknown"):
        await admin_service.mutate_binding(
            admin,
            target_id,
            binding="role",
            key="root",
            operation="assign",
            reason="no such policy primitive",
            request_id="bind-2",
        )
    with pytest.raises(GovernanceError, match="group_unknown"):
        await admin_service.mutate_binding(
            admin,
            target_id,
            binding="group",
            key="ops-team",
            operation="assign",
            reason="group does not exist yet",
            request_id="bind-3",
        )
    with pytest.raises(GovernanceError, match="binding_not_found"):
        await admin_service.mutate_binding(
            admin,
            target_id,
            binding="role",
            key="curator",
            operation="unassign",
            reason="nothing to remove",
            request_id="bind-4",
        )
    assigned = await admin_service.mutate_binding(
        admin,
        target_id,
        binding="role",
        key="curator",
        operation="assign",
        reason="promote to curator",
        request_id="bind-5",
    )
    assert "curator" in assigned.roles
    assert assigned.security_version == 2
    with pytest.raises(GovernanceError, match="binding_exists"):
        await admin_service.mutate_binding(
            admin,
            target_id,
            binding="role",
            key="curator",
            operation="assign",
            reason="duplicate assign",
            request_id="bind-6",
        )
    loaded = await PostgresSubjectRepository(factory).get_by_user_id(target_id)
    assert loaded is not None
    assert Role.CURATOR in loaded.roles, "policy identity honours the binding"
    group_key = f"ops-team-{uuid.uuid4().hex[:8]}"
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO groups(issuer, provider_group_key, name)
            VALUES (:issuer, :key, :key)
        """), {"issuer": ISSUER, "key": group_key})
    grouped = await admin_service.mutate_binding(
        admin,
        target_id,
        binding="group",
        key=group_key,
        operation="assign",
        reason="join operations team",
        request_id="bind-7",
    )
    assert group_key in grouped.groups
    removed = await admin_service.mutate_binding(
        admin,
        target_id,
        binding="role",
        key="curator",
        operation="unassign",
        reason="rotation ended",
        request_id="bind-8",
    )
    assert "curator" not in removed.roles
    assert removed.groups == [group_key]
    assert removed.security_version == 4
    subjects = await admin_service.list_subjects(
        admin,
        request_id="bind-9",
        limit=5,
    )
    assert 0 < len(subjects) <= 5
    assert all(
        item.roles == sorted(item.roles) and item.groups == sorted(item.groups)
        for item in subjects
    )
    assert await audit_actions_by_detail(factory, "subject_id", str(target_id)) == [
        "admin.binding.assign",
        "admin.binding.assign",
        "admin.binding.unassign",
    ]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        projected = await redis.get(f"rtr:subject-security-version:{target_id}")
    finally:
        await redis.aclose()
    assert projected is not None and int(projected) >= 3, (
        "session projection drops stale sessions immediately"
    )


@pytest.mark.asyncio
async def test_gap_priority_change_is_scoped_audited_and_state_bounded(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
) -> None:
    curator_id, requester_id, stranger_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for actor_id in (curator_id, requester_id, stranger_id):
        await insert_actor(factory, actor_id)
    curator = subject(Role.CURATOR, curator_id)
    gap_id = await create_manual_gap(factory, requester_id)
    with pytest.raises(GovernanceError, match="gap_not_found"):
        await admin_service.set_gap_priority(
            subject(Role.STAFF, stranger_id),
            gap_id,
            priority="urgent",
            reason="stranger probe",
            request_id="prio-0",
        )
    with pytest.raises(PermissionError, match="curator_required"):
        await admin_service.set_gap_priority(
            subject(Role.STAFF, requester_id),
            gap_id,
            priority="urgent",
            reason="requester cannot reprioritize",
            request_id="prio-1",
        )
    raised = await admin_service.set_gap_priority(
        curator,
        gap_id,
        priority="high",
        reason="pilot escalation",
        request_id="prio-2",
    )
    assert raised.priority == "high"
    assert await audit_actions_by_detail(factory, "gap_id", str(gap_id)) == [
        "governance.gap.priority",
    ]
    await GovernanceService(uow=UnitOfWork(factory)).transition_gap(
        curator,
        gap_id,
        "decline",
        GapTransitionInput(
            reason="closing for the priority freeze test",
            decline_reason="out of scope",
        ),
        request_id="prio-3",
    )
    with pytest.raises(GovernanceError, match="gap_state_unsupported"):
        await admin_service.set_gap_priority(
            curator,
            gap_id,
            priority="low",
            reason="closed gaps freeze",
            request_id="prio-4",
        )


@pytest.mark.asyncio
async def test_job_health_is_admin_gated_live_and_payload_free(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
) -> None:
    admin_id, staff_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, admin_id)
    await insert_actor(factory, staff_id)
    admin = subject(Role.ADMIN, admin_id)
    with pytest.raises(PermissionError, match="admin_required"):
        await admin_service.job_health(
            subject(Role.CURATOR, staff_id),
            request_id="jobs-0",
        )
    resource_id, job_id = uuid.uuid4(), uuid.uuid4()
    checksum = digest(uuid.uuid4().hex)
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO resources(resource_id,resource_type,owner_subject_id,
              classification,source_zone,lifecycle_state)
            VALUES (:id,'object',:owner,'internal','private_context','active')
        """), {"id": resource_id, "owner": staff_id})
        await session.execute(text("""
            INSERT INTO object_blobs(object_id,bucket,object_key,sha256,
              byte_size,mime_type,storage_state)
            VALUES (:id,'rtr-test',:key,:sha,10,'text/plain','available')
        """), {"id": resource_id, "key": f"jobs/{resource_id}", "sha": checksum})
        upload_id = uuid.uuid4()
        await session.execute(text("""
            INSERT INTO upload_sessions(upload_id,parent_resource_id,object_id,
              requested_by,request_id,state,logical_name,original_filename,
              sha256,byte_size)
            VALUES (:upload_id,:resource_id,:resource_id,:requested_by,
              'jobs-fixture','accepted','fixture.txt','fixture.txt',:sha,10)
        """), {
            "upload_id": upload_id,
            "resource_id": resource_id,
            "requested_by": staff_id,
            "sha": checksum,
        })
        await session.execute(text("""
            INSERT INTO ingestion_jobs(job_id,upload_id,resource_id,job_type,
              pipeline_version,pipeline_fingerprint,idempotency_key,status,
              attempt,max_attempts,requested_by,request_id,input_sha256,
              error_code,finished_at)
            VALUES (:job_id,:upload_id,:resource_id,'validate','rtr-ingestion-v1',
              :fingerprint,:idempotency,'failed',3,3,:requested_by,
              'jobs-fixture',:sha,'validator_failed',now())
        """), {
            "job_id": job_id,
            "upload_id": upload_id,
            "resource_id": resource_id,
            "fingerprint": checksum,
            "idempotency": f"jobs-fixture-{job_id.hex}",
            "requested_by": staff_id,
            "sha": checksum,
        })
    report = await admin_service.job_health(admin, request_id="jobs-1")
    families = {family.family: family for family in report.families}
    assert set(families) == {"ingestion", "render", "reindex"}
    ingestion = families["ingestion"]
    assert ingestion.job_counts.get("failed", 0) >= 1
    seeded = next(
        item for item in ingestion.recent_failures if item.job_id == job_id
    )
    assert seeded.error_code == "validator_failed"
    assert seeded.status == "failed"
    assert set(JobFailureView.model_fields) == {
        "job_id", "kind", "status", "error_code", "attempt", "occurred_at",
    }, "job health exposes states and codes only, never payload content"
    failed_before = ingestion.job_counts["failed"]
    async with factory() as session, session.begin():
        await session.execute(text("""
            UPDATE ingestion_jobs SET status='succeeded', error_code=NULL
            WHERE job_id=:job_id
        """), {"job_id": job_id})
    live = await admin_service.job_health(admin, request_id="jobs-2")
    ingestion_after = next(
        family for family in live.families if family.family == "ingestion"
    )
    assert ingestion_after.job_counts.get("failed", 0) == failed_before - 1
    assert job_id not in {
        item.job_id for item in ingestion_after.recent_failures
    }, "job health is computed live, not from any snapshot"


@pytest.mark.asyncio
async def test_admin_boundary_probes_fail_typed_and_audited(
    factory: async_sessionmaker[Any],
) -> None:
    """AC-11 hard boundary: every truth-family admin path refuses with a
    typed error and appends an audit entry; no underlying row changes."""
    admin_id = uuid.uuid4()
    await insert_actor(factory, admin_id)
    admin = subject(Role.ADMIN, admin_id)

    async def resolve() -> Subject:
        return admin

    async with factory() as session:
        versions_before = await session.scalar(
            text("SELECT count(*) FROM record_versions"),
        )
        research_before = await session.scalar(
            text("SELECT count(*) FROM research_records"),
        )
    app.dependency_overrides[governance_subject] = resolve
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            probes = [
                await client.post(
                    f"/api/v1/admin/sot/records/{uuid.uuid4()}",
                    json={"value_payload": {"value": "forged"}},
                ),
                await client.patch(
                    f"/api/v1/admin/research-records/{uuid.uuid4()}",
                    json={"searchable_text": "forged research"},
                ),
                await client.delete(
                    f"/api/v1/admin/research-packages/{uuid.uuid4()}",
                ),
                await client.put(
                    f"/api/v1/admin/audit/events/{uuid.uuid4()}",
                    json={"details": {}},
                ),
                await client.delete(f"/api/v1/admin/issuances/{uuid.uuid4()}"),
                await client.post(
                    f"/api/v1/admin/documents/{uuid.uuid4()}/content",
                    json={"content": "forged issuance"},
                ),
                await client.get(f"/api/v1/admin/records/{uuid.uuid4()}"),
            ]
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    for response in probes:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "admin_truth_immutable"
        assert response.json()["request_id"]
    async with factory() as session:
        rows = (await session.execute(text("""
            SELECT details->>'family' AS family, details->>'method' AS method
            FROM audit_events
            WHERE action='admin.boundary.refused'
              AND actor_user_id=:actor ORDER BY sequence
        """), {"actor": admin_id})).mappings().all()
        versions_after = await session.scalar(
            text("SELECT count(*) FROM record_versions"),
        )
        research_after = await session.scalar(
            text("SELECT count(*) FROM research_records"),
        )
    assert len(rows) == len(probes)
    assert {row["family"] for row in rows} == {
        "sot", "records", "research-records", "research-packages",
        "audit", "issuances", "documents",
    }
    assert {row["method"] for row in rows} == {"POST", "PATCH", "PUT", "DELETE", "GET"}
    assert versions_after == versions_before
    assert research_after == research_before


@pytest.mark.asyncio
async def test_dashboard_is_policy_scoped_live_and_leak_safe(
    factory: async_sessionmaker[Any],
    admin_service: AdminGovernanceService,
    research_service: ResearchService,
) -> None:
    """AC-12: two subjects see different counts, a denied subject sees no
    restricted existence, and every tile recomputes live with no snapshot."""
    owner_id, stranger_id, curator_id, decider_id, admin_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
    )
    for actor_id in (owner_id, stranger_id, curator_id, decider_id, admin_id):
        await insert_actor(factory, actor_id)
    owner = subject(Role.STAFF, owner_id)
    stranger = subject(Role.STAFF, stranger_id)
    curator = subject(Role.CURATOR, curator_id)
    admin = subject(Role.ADMIN, admin_id)
    now = datetime.now(UTC)
    source_key_a = f"admin.dash.{uuid.uuid4().hex[:8]}"
    source_key_b = f"admin.dash.{uuid.uuid4().hex[:8]}"
    await insert_sot_version(
        factory, owner_id,
        source_key=source_key_a,
        effective_to=now + timedelta(hours=100),
    )
    await insert_sot_version(factory, owner_id, source_key=source_key_b)
    await create_manual_gap(factory, owner_id)
    source = await admin_service.create_source(
        admin,
        stable_key=f"refinery.dash.{uuid.uuid4().hex[:12]}",
        display_name="Dashboard research source",
        description="",
        origin="refinery",
        owner_subject_id=owner_id,
        classification="internal",
        lifecycle="active",
        request_id="dash-0",
    )
    staging = build_research_package(
        Path(research_service.settings.research_staging_root),
        source_key=source.stable_key,
        records=[
            research_record_row(tier="P"),
            research_record_row(tier="S"),
        ],
    )
    imported = await research_service.import_package(
        curator,
        staging,
        request_id="dash-1",
    )
    async with factory() as session:
        record_ids = list((await session.execute(text("""
            SELECT research_record_id FROM research_records
            WHERE package_id=:package_id
        """), {"package_id": imported.package.package_id})).scalars())
    async with factory() as session, session.begin():
        proposal = await GovernanceRepository().create_proposal(
            session,
            research_record_ids=record_ids,
            claim_draft={"claim_text": "dashboard claim"},
            target_record_key=f"company.claims.{uuid.uuid4().hex[:8]}",
            proposer_subject_id=curator_id,
            rationale="dashboard funnel fixture",
        )
    async with factory() as session, session.begin():
        await GovernanceRepository().decide_proposal(
            session,
            proposal.proposal_id,
            decider_subject_id=decider_id,
            decision="rejected",
            decision_reason="fixture rejection",
            attestation_hash=digest("dashboard attestation"),
        )
    dashboard_service = DashboardService(uow=UnitOfWork(factory))

    owner_view = await dashboard_service.dashboard(owner, request_id="dash-owner-1")
    assert owner_view.coverage.zone_label == "sot"
    assert owner_view.coverage.total_records == 2
    assert owner_view.coverage.by_owner == {str(owner_id): 2}
    assert owner_view.coverage.by_classification == {"internal": 2}
    assert owner_view.coverage.by_source_key == {source_key_a: 1, source_key_b: 1}
    assert owner_view.freshness.total == 1
    assert owner_view.freshness.expiring == 1
    assert owner_view.freshness.expired == 0
    assert owner_view.gap_flow.open_total == 1
    assert owner_view.gap_flow.closed_total == 0
    assert owner_view.gap_flow.by_state == {"open": 1}
    assert owner_view.gap_flow.aging["under_24h"] == 1
    assert owner_view.research_intake.zone_label == "research"
    assert owner_view.research_intake.sources_total == 1
    assert owner_view.research_intake.packages_by_state == {"imported": 1}
    assert owner_view.research_intake.records_by_tier == {"P": 1, "S": 1}
    assert owner_view.graduation.proposed == 0
    assert owner_view.graduation.rejected == 0

    stranger_view = await dashboard_service.dashboard(
        stranger,
        request_id="dash-stranger-1",
    )
    assert stranger_view.coverage.total_records == 0
    assert stranger_view.coverage.by_source_key == {}
    assert stranger_view.coverage.by_owner == {}
    assert stranger_view.freshness.total == 0
    assert stranger_view.gap_flow.open_total == 0
    assert stranger_view.gap_flow.closed_total == 0
    assert stranger_view.gap_flow.by_state == {}
    assert stranger_view.research_intake.sources_total == 0
    assert stranger_view.research_intake.packages_by_state == {}
    assert stranger_view.research_intake.records_by_tier == {}
    assert stranger_view.graduation.proposed == 0
    assert stranger_view.graduation.approved == 0
    assert stranger_view.graduation.rejected == 0
    assert stranger_view.graduation.submitted == 0

    curator_view = await dashboard_service.dashboard(
        curator,
        request_id="dash-curator-1",
    )
    assert curator_view.coverage.total_records >= 2
    assert curator_view.coverage.by_source_key.get(source_key_a) == 1
    assert curator_view.research_intake.sources_total >= 1
    assert curator_view.research_intake.packages_by_state.get("imported", 0) >= 1
    assert curator_view.graduation.rejected >= 1
    assert curator_view.gap_flow.open_total >= 1

    # A newly activated, already-expired version (as the publish gate would
    # produce) must surface on the very next computation with no refresh step.
    await insert_sot_version(
        factory, owner_id,
        source_key=f"admin.dash.{uuid.uuid4().hex[:8]}",
        effective_to=now - timedelta(hours=1),
    )
    live_view = await dashboard_service.dashboard(owner, request_id="dash-owner-2")
    assert live_view.coverage.total_records == 3
    assert live_view.freshness.total == 2
    assert live_view.freshness.expired == 1
    assert live_view.freshness.expiring == 1, (
        "a live metadata change reflects without any refresh step"
    )
    await admin_service.update_source(
        admin,
        source.source_id,
        classification="highly_restricted",
        reason="dashboard revocation probe",
        request_id="dash-2",
    )
    revoked_view = await dashboard_service.dashboard(
        owner,
        request_id="dash-owner-3",
    )
    assert revoked_view.research_intake.sources_total == 0
    assert revoked_view.research_intake.packages_by_state == {}
    assert revoked_view.research_intake.records_by_tier == {}, (
        "denied existence does not leak through aggregates"
    )
    async with factory() as session:
        audits = (await session.execute(text("""
            SELECT request_id FROM audit_events
            WHERE action='governance.dashboard.view'
              AND request_id IN ('dash-owner-1','dash-stranger-1','dash-owner-3')
        """))).scalars().all()
    assert set(audits) == {"dash-owner-1", "dash-stranger-1", "dash-owner-3"}
