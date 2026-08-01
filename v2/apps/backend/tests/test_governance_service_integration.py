import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.service import GapTransitionInput, GovernanceService
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
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
def service(factory: async_sessionmaker[Any]) -> GovernanceService:
    return GovernanceService(uow=UnitOfWork(factory))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def subject(role: Role, user_id: uuid.UUID) -> Subject:
    return Subject(
        user_id=str(user_id),
        issuer="governance-service-tests",
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
            VALUES (:id,'governance-service-tests',:sub,:email,'rtrobotics.com')
        """), {
            "id": actor_id,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
        })


async def insert_sot_version(
    factory: async_sessionmaker[Any],
    owner_id: uuid.UUID,
    *,
    lifecycle: str = "active",
    effective_to: datetime | None = None,
    freshness_due_at: datetime | None = None,
    record_id: uuid.UUID | None = None,
    version_ordinal: int = 1,
    package_revision: int = 1,
    set_current: bool = True,
    supersedes_version_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a SOT package/record/version fixture with live freshness metadata."""
    package_id = uuid.uuid4()
    version_id = uuid.uuid4()
    checksum = digest(uuid.uuid4().hex)
    new_record = record_id is None
    record_id = record_id or uuid.uuid4()
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO sot_packages(
              package_id,source_key,revision,schema_version,trust_zone,
              manifest_sha256,payload_sha256,producer,generated_at,
              staging_name,lifecycle
            ) VALUES (
              :package_id,:source_key,:revision,'1','sot',:checksum,:checksum,
              'governance-service-tests',now(),:staging,'active'
            )
        """), {
            "package_id": package_id,
            "source_key": f"govsvc.{uuid.uuid4().hex}",
            "revision": package_revision,
            "checksum": checksum,
            "staging": f"staging-{package_id.hex}",
        })
        if new_record:
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
                  :record_id,:record_key,'governance-service-tests',:owner_id,
                  'internal','active'
                )
            """), {
                "record_id": record_id,
                "record_key": f"GOVSVC.{uuid.uuid4().hex}",
                "owner_id": owner_id,
            })
        await session.execute(text("""
            INSERT INTO record_versions(
              version_id,record_id,package_id,package_revision,version_ordinal,
              owner_subject_id,classification,value_payload,searchable_text,
              provenance_level,confidence,verification_state,fact_state,
              effective_from,effective_to,freshness_policy,freshness_due_at,
              freshness_state,source_refs,acl_projection,content_sha256,
              supersedes_version_id,lifecycle
            ) VALUES (
              :version_id,:record_id,:package_id,:package_revision,
              :version_ordinal,:owner_id,'internal','{"value":"governed"}',
              'governed fact','verified_primary',1,'verified','verified',
              :effective_from,:effective_to,'{}',:freshness_due_at,'current',
              ARRAY['governance-service-tests'],'[]',:checksum,
              :supersedes_version_id,:lifecycle
            )
        """), {
            "version_id": version_id,
            "record_id": record_id,
            "package_id": package_id,
            "package_revision": package_revision,
            "version_ordinal": version_ordinal,
            "owner_id": owner_id,
            "effective_from": datetime.now(UTC) - timedelta(days=30),
            "effective_to": effective_to,
            "freshness_due_at": freshness_due_at,
            "supersedes_version_id": supersedes_version_id,
            "checksum": checksum,
            "lifecycle": lifecycle,
        })
        if set_current:
            await session.execute(text("""
                UPDATE records SET current_version_id=:version_id
                WHERE record_id=:record_id
            """), {"version_id": version_id, "record_id": record_id})
    return version_id, record_id


async def audit_actions(
    factory: async_sessionmaker[Any],
    resource_id: uuid.UUID,
) -> list[str]:
    async with factory() as session:
        rows = (await session.execute(text("""
            SELECT action FROM audit_events
            WHERE resource_id=:resource_id ORDER BY sequence
        """), {"resource_id": resource_id})).scalars()
        return list(rows)


async def audit_actions_by_detail(
    factory: async_sessionmaker[Any],
    key: str,
    value: uuid.UUID,
) -> list[str]:
    async with factory() as session:
        rows = (await session.execute(text(f"""
            SELECT action FROM audit_events
            WHERE details->>'{key}'=:value ORDER BY sequence
        """), {"value": str(value)})).scalars()
        return list(rows)


async def create_manual_gap(
    factory: async_sessionmaker[Any],
    requester_id: uuid.UUID,
) -> uuid.UUID:
    repository = GovernanceRepository()
    async with factory() as session, session.begin():
        gap = await repository.create_or_increment_gap(
            session,
            question_digest=digest(f"question {uuid.uuid4().hex}"),
            sanitized_question="Which governed answer is missing?",
            sanitized_summary="governed answer",
            requester_id=requester_id,
            routing_key="curator:sot",
            origin="manual",
            reason_category="manual_entry",
        )
    return gap.gap_id


@pytest.mark.asyncio
async def test_settings_are_admin_gated_bounded_versioned_and_audited(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    admin_id = uuid.uuid4()
    staff_id = uuid.uuid4()
    await insert_actor(factory, admin_id)
    await insert_actor(factory, staff_id)
    admin = subject(Role.ADMIN, admin_id)
    with pytest.raises(PermissionError, match="admin_required"):
        await service.update_setting(
            subject(Role.CURATOR, staff_id),
            setting_key="gap.sla.assign_hours",
            value=48,
            reason="curators must not change SLA",
            request_id="settings-1",
        )
    with pytest.raises(GovernanceError, match="setting_out_of_bounds"):
        await service.update_setting(
            admin,
            setting_key="gap.sla.assign_hours",
            value=0,
            reason="below minimum",
            request_id="settings-2",
        )
    with pytest.raises(GovernanceError, match="setting_unknown"):
        await service.update_setting(
            admin,
            setting_key="gap.sla.unregistered",
            value=10,
            reason="unknown key",
            request_id="settings-3",
        )
    first = await service.update_setting(
        admin,
        setting_key="gap.sla.assign_hours",
        value=48,
        reason="pilot SLA window",
        request_id="settings-4",
    )
    second = await service.update_setting(
        admin,
        setting_key="gap.sla.assign_hours",
        value=24,
        reason="tightened SLA window",
        request_id="settings-5",
    )
    assert second.version == first.version + 1
    assert await service.setting_value("gap.sla.assign_hours") == 24
    assert await service.setting_value("queue.freshness.expiring_hours") == 336
    assert await audit_actions_by_detail(factory, "setting_id", second.setting_id) == [
        "governance.setting.update",
    ]


@pytest.mark.asyncio
async def test_gap_lifecycle_applies_sla_from_settings_and_audits_every_step(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    admin_id, curator_id, requester_id, owner_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
    )
    for actor_id in (admin_id, curator_id, requester_id, owner_id):
        await insert_actor(factory, actor_id)
    curator = subject(Role.CURATOR, curator_id)
    await service.update_setting(
        subject(Role.ADMIN, admin_id),
        setting_key="gap.sla.assign_hours",
        value=48,
        reason="SLA fixture for lifecycle test",
        request_id="gap-sla-0",
    )
    gap_id = await create_manual_gap(factory, requester_id)
    active_version, _ = await insert_sot_version(factory, owner_id)
    with pytest.raises(GovernanceError, match="gap_transition_invalid"):
        await service.transition_gap(
            curator, gap_id, "answer",
            GapTransitionInput(
                reason="cannot answer before triage",
                resolving_version_id=active_version,
            ),
            request_id="gap-1",
        )
    triaged = await service.transition_gap(
        curator, gap_id, "triage",
        GapTransitionInput(reason="triaged for assignment"),
        request_id="gap-2",
    )
    assert triaged.lifecycle == "triaged"
    with pytest.raises(GovernanceError, match="gap_owner_required"):
        await service.transition_gap(
            curator, gap_id, "assign",
            GapTransitionInput(reason="assign without owner"),
            request_id="gap-3",
        )
    before = datetime.now(UTC)
    assigned = await service.transition_gap(
        curator, gap_id, "assign",
        GapTransitionInput(reason="assigned to owner", owner_subject_id=owner_id),
        request_id="gap-4",
    )
    assert assigned.owner_subject_id == owner_id
    assert assigned.due_at is not None
    offset = assigned.due_at - before
    assert timedelta(hours=47, minutes=55) < offset < timedelta(hours=48, minutes=5)
    staged_version, _ = await insert_sot_version(
        factory, owner_id, lifecycle="staged", set_current=False,
    )
    with pytest.raises(GovernanceError, match="record_version_not_active"):
        await service.transition_gap(
            curator, gap_id, "answer",
            GapTransitionInput(
                reason="staged version cannot close",
                resolving_version_id=staged_version,
            ),
            request_id="gap-5",
        )
    with pytest.raises(GovernanceError, match="record_version_not_found"):
        await service.transition_gap(
            curator, gap_id, "answer",
            GapTransitionInput(
                reason="unknown version cannot close",
                resolving_version_id=uuid.uuid4(),
            ),
            request_id="gap-6",
        )
    answered = await service.transition_gap(
        curator, gap_id, "answer",
        GapTransitionInput(
            reason="closed by activated record",
            resolving_version_id=active_version,
        ),
        request_id="gap-7",
    )
    assert answered.lifecycle == "answered"
    assert answered.resolving_version_id == active_version
    assert await audit_actions_by_detail(factory, "gap_id", gap_id) == [
        "governance.gap.triage",
        "governance.gap.assign",
        "governance.gap.answer",
    ]
    detail = await service.gap_detail(curator, gap_id, request_id="gap-8")
    assert [
        (item.from_state, item.to_state) for item in detail.transitions
    ] == [("open", "triaged"), ("triaged", "assigned"), ("assigned", "answered")]


@pytest.mark.asyncio
async def test_declined_gap_records_immutable_reason_through_service(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    curator_id, requester_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, curator_id)
    await insert_actor(factory, requester_id)
    curator = subject(Role.CURATOR, curator_id)
    gap_id = await create_manual_gap(factory, requester_id)
    with pytest.raises(GovernanceError, match="gap_decline_reason_required"):
        await service.transition_gap(
            curator, gap_id, "decline",
            GapTransitionInput(reason="attempt without decline reason"),
            request_id="decline-1",
        )
    declined = await service.transition_gap(
        curator, gap_id, "decline",
        GapTransitionInput(
            reason="declined as out of scope",
            decline_reason="outside company knowledge scope",
        ),
        request_id="decline-2",
    )
    assert declined.lifecycle == "declined"
    assert declined.decline_reason == "outside company knowledge scope"
    with pytest.raises(GovernanceError, match="gap_state_unsupported|gap_transition_invalid"):
        await service.transition_gap(
            curator, gap_id, "triage",
            GapTransitionInput(reason="closed gaps stay closed"),
            request_id="decline-3",
        )
    assert await audit_actions_by_detail(factory, "gap_id", gap_id) == [
        "governance.gap.decline",
    ]


@pytest.mark.asyncio
async def test_gap_scoping_blocks_cross_owner_probes_and_lists_only_caller_scope(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    requester_a, requester_b, stranger, curator_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
    )
    for actor_id in (requester_a, requester_b, stranger, curator_id):
        await insert_actor(factory, actor_id)
    gap_a = await create_manual_gap(factory, requester_a)
    gap_b = await create_manual_gap(factory, requester_b)
    page_a = await service.list_gaps(
        subject(Role.STAFF, requester_a), request_id="scope-1", limit=100,
    )
    ids_a = {item.gap_id for item in page_a.items}
    assert gap_a in ids_a
    assert gap_b not in ids_a
    assert all(
        item.requester_id == requester_a or item.owner_subject_id == requester_a
        for item in page_a.items
    )
    page_stranger = await service.list_gaps(
        subject(Role.STAFF, stranger), request_id="scope-2", limit=100,
    )
    assert page_stranger.items == []
    with pytest.raises(GovernanceError, match="gap_not_found"):
        await service.gap_detail(
            subject(Role.STAFF, requester_a), gap_b, request_id="scope-3",
        )
    with pytest.raises(GovernanceError, match="gap_not_found"):
        await service.transition_gap(
            subject(Role.STAFF, stranger), gap_a, "triage",
            GapTransitionInput(reason="cross-owner mutation probe"),
            request_id="scope-4",
        )
    with pytest.raises(PermissionError, match="curator_required"):
        await service.transition_gap(
            subject(Role.STAFF, requester_a), gap_a, "triage",
            GapTransitionInput(reason="requester cannot transition"),
            request_id="scope-5",
        )
    curator_page = await service.list_gaps(
        subject(Role.CURATOR, curator_id), request_id="scope-6", limit=100,
    )
    curator_ids = {item.gap_id for item in curator_page.items}
    assert {gap_a, gap_b} <= curator_ids


@pytest.mark.asyncio
async def test_gap_listing_cursor_is_stable_under_policy_filtering(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    requester_id = uuid.uuid4()
    await insert_actor(factory, requester_id)
    created = [await create_manual_gap(factory, requester_id) for _ in range(3)]
    viewer = subject(Role.STAFF, requester_id)
    collected: list[uuid.UUID] = []
    cursor: str | None = None
    for _ in range(5):
        page = await service.list_gaps(
            viewer, request_id="cursor-1", limit=1, cursor=cursor,
        )
        collected.extend(item.gap_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert set(created) <= set(collected)
    assert len(collected) == len(set(collected))


@pytest.mark.asyncio
async def test_queues_compute_live_membership_with_thresholds_and_scoping(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    owner_id, curator_id, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for actor_id in (owner_id, curator_id, stranger):
        await insert_actor(factory, actor_id)
    now = datetime.now(UTC)
    expired_version, _ = await insert_sot_version(
        factory, owner_id, effective_to=now - timedelta(hours=1),
    )
    expiring_version, _ = await insert_sot_version(
        factory, owner_id, effective_to=now + timedelta(hours=100),
    )
    far_version, _ = await insert_sot_version(
        factory, owner_id, effective_to=now + timedelta(hours=9000),
    )
    overdue_version, _ = await insert_sot_version(
        factory, owner_id, freshness_due_at=now - timedelta(hours=2),
    )
    conflict_a, conflict_record = await insert_sot_version(factory, owner_id)
    conflict_b, _ = await insert_sot_version(
        factory, owner_id,
        record_id=conflict_record,
        version_ordinal=2,
        package_revision=2,
        set_current=True,
    )
    owner = subject(Role.STAFF, owner_id)
    freshness = await service.queue_page(owner, "freshness", request_id="queue-1")
    statuses = {
        entry.record_version_id: entry.status for entry in freshness.entries
    }
    assert statuses[expired_version] == "expired"
    assert statuses[expiring_version] == "expiring"
    assert far_version not in statuses
    assert freshness.aggregates.total == len(freshness.entries) == 2
    assert freshness.aggregates.by_status == {"expired": 1, "expiring": 1}
    review = await service.queue_page(owner, "owner_review", request_id="queue-2")
    review_statuses = {
        entry.record_version_id: entry.status for entry in review.entries
    }
    assert review_statuses[overdue_version] == "overdue"
    conflict = await service.queue_page(owner, "conflict", request_id="queue-3")
    conflicted = {
        entry.record_id: entry for entry in conflict.entries
    }
    assert conflict_record in conflicted
    disputed = conflicted[conflict_record]
    assert disputed.status == "disputed"
    assert {side.version_id for side in disputed.sides} == {conflict_a, conflict_b}
    assert all(side.evidence_refs is not None for side in disputed.sides)
    stranger_view = await service.queue_page(
        subject(Role.STAFF, stranger), "freshness", request_id="queue-4",
    )
    stranger_ids = {entry.record_version_id for entry in stranger_view.entries}
    assert not {expired_version, expiring_version} & stranger_ids
    assert stranger_view.aggregates.total == len(stranger_view.entries) == 0
    curator_view = await service.queue_page(
        subject(Role.CURATOR, curator_id), "freshness", request_id="queue-5",
    )
    curator_ids = {entry.record_version_id for entry in curator_view.entries}
    assert {expired_version, expiring_version} <= curator_ids


@pytest.mark.asyncio
async def test_completed_task_reopens_while_live_metadata_is_unchanged(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    owner_id, curator_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, owner_id)
    await insert_actor(factory, curator_id)
    curator = subject(Role.CURATOR, curator_id)
    owner = subject(Role.STAFF, owner_id)
    now = datetime.now(UTC)
    expired_version, expired_record = await insert_sot_version(
        factory, owner_id, effective_to=now - timedelta(hours=3),
    )
    task = await service.assign_queue_task(
        curator, "freshness",
        record_version_id=expired_version,
        assignee_subject_id=owner_id,
        request_id="reopen-1",
    )
    assert task.state == "assigned"
    completed = await service.complete_queue_task(
        owner, task.task_id, request_id="reopen-2",
    )
    assert completed.state == "completed"
    recomputed = await service.queue_page(owner, "freshness", request_id="reopen-3")
    by_version = {
        entry.record_version_id: entry for entry in recomputed.entries
    }
    assert expired_version in by_version, "stale completion must not mask live expiry"
    reopened = by_version[expired_version].task
    assert reopened is not None
    assert reopened.state == "reopened"
    assert reopened.completed_at is None
    assert "governance.queue.reopen" in await audit_actions(factory, expired_record)
    await service.complete_queue_task(owner, task.task_id, request_id="reopen-4")
    async with factory() as session, session.begin():
        await session.execute(text("""
            UPDATE record_versions SET lifecycle='superseded'
            WHERE version_id=:version_id
        """), {"version_id": expired_version})
    replacement, _ = await insert_sot_version(
        factory, owner_id,
        record_id=expired_record,
        version_ordinal=2,
        package_revision=2,
        effective_to=now + timedelta(hours=9000),
        supersedes_version_id=expired_version,
    )
    resolved = await service.queue_page(owner, "freshness", request_id="reopen-5")
    resolved_versions = {entry.record_version_id for entry in resolved.entries}
    assert expired_version not in resolved_versions
    assert replacement not in resolved_versions
    async with factory() as session:
        final = await GovernanceRepository().get_review_task(session, task.task_id)
    assert final is not None
    assert final.state == "completed", "resolved work must stay completed"


@pytest.mark.asyncio
async def test_queue_assignment_requires_curator_and_live_membership(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    owner_id, curator_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, owner_id)
    await insert_actor(factory, curator_id)
    curator = subject(Role.CURATOR, curator_id)
    now = datetime.now(UTC)
    live_version, live_record = await insert_sot_version(
        factory, owner_id, effective_to=now - timedelta(hours=1),
    )
    fresh_version, _ = await insert_sot_version(
        factory, owner_id, effective_to=now + timedelta(hours=9000),
    )
    with pytest.raises(PermissionError, match="curator_required"):
        await service.assign_queue_task(
            subject(Role.STAFF, owner_id), "freshness",
            record_version_id=live_version,
            assignee_subject_id=owner_id,
            request_id="assign-1",
        )
    with pytest.raises(GovernanceError, match="queue_entry_not_found"):
        await service.assign_queue_task(
            subject(Role.STAFF, uuid.uuid4()), "freshness",
            record_version_id=live_version,
            assignee_subject_id=owner_id,
            request_id="assign-1b",
        )
    with pytest.raises(GovernanceError, match="queue_membership_stale"):
        await service.assign_queue_task(
            curator, "freshness",
            record_version_id=fresh_version,
            assignee_subject_id=owner_id,
            request_id="assign-2",
        )
    with pytest.raises(GovernanceError, match="queue_entry_not_found"):
        await service.assign_queue_task(
            curator, "freshness",
            record_version_id=uuid.uuid4(),
            assignee_subject_id=owner_id,
            request_id="assign-3",
        )
    task = await service.assign_queue_task(
        curator, "freshness",
        record_version_id=live_version,
        assignee_subject_id=owner_id,
        request_id="assign-4",
    )
    assert task.assignee_subject_id == owner_id
    actions = await audit_actions(factory, live_record)
    assert "governance.queue.assign" in actions
    with pytest.raises(GovernanceError, match="review_task_not_found"):
        await service.complete_queue_task(
            subject(Role.STAFF, uuid.uuid4()), task.task_id, request_id="assign-5",
        )
