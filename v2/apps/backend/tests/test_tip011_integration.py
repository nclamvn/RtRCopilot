"""TIP-011 Task 3 integration: pickers, tiles, conversation list, citation zone.

4a-style live-infrastructure proofs: two-subject scoping with zero existence
leak for both pickers (AC-06), live-computed conflict and owner-review
dashboard tiles under the caller's policy scope (AC-08), the owner-only
conversation list with HMAC cursors and stored-digest metadata, and the
literal SOT zone label on real grounded-answer citations (AC-07).
"""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.dashboard import DashboardService
from rtr_copilot.governance.service import GovernanceService, encode_signed_cursor
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.api import rag_subject
from rtr_copilot.rag.models import SearchFilters
from rtr_copilot.rag.reindex import ReindexService
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.repositories.governance import GovernanceError
from rtr_copilot.sot.service import SOTPublishService

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)

ISSUER = "tip011-integration"


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
        issuer=ISSUER,
        sub=user_id.hex,
        email=f"{user_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


async def insert_actor(
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
    *,
    display_name: str = "",
) -> None:
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(
              user_id,issuer,provider_sub,email,canonical_domain,display_name
            ) VALUES (:id,:issuer,:sub,:email,'rtrobotics.com',:display_name)
        """), {
            "id": actor_id,
            "issuer": ISSUER,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
            "display_name": display_name,
        })


async def insert_sot_version(
    factory: async_sessionmaker[Any],
    owner_id: uuid.UUID,
    *,
    record_key: str | None = None,
    title: str | None = None,
    effective_to: datetime | None = None,
    freshness_due_at: datetime | None = None,
    record_id: uuid.UUID | None = None,
    version_ordinal: int = 1,
    package_revision: int = 1,
    set_current: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    """One SOT package/record/version fixture (TIP-006 integrity preserved)."""
    package_id = uuid.uuid4()
    version_id = uuid.uuid4()
    checksum = digest(uuid.uuid4().hex)
    new_record = record_id is None
    record_id = record_id or uuid.uuid4()
    payload = {"value": "governed"}
    if title is not None:
        payload["title"] = title
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO sot_packages(
              package_id,source_key,revision,schema_version,trust_zone,
              manifest_sha256,payload_sha256,producer,generated_at,
              staging_name,lifecycle
            ) VALUES (
              :package_id,:source_key,:revision,'1','sot',:checksum,:checksum,
              'tip011-integration',now(),:staging,'active'
            )
        """), {
            "package_id": package_id,
            "source_key": f"tip011.{uuid.uuid4().hex}",
            "revision": package_revision,
            "checksum": checksum,
            "staging": f"staging-{package_id.hex}",
        })
        if new_record:
            await session.execute(text("""
                INSERT INTO resources(
                  resource_id,resource_type,owner_subject_id,classification,
                  source_zone,lifecycle_state
                ) VALUES (
                  :record_id,'record',:owner_id,'internal','sot','active'
                )
            """), {"record_id": record_id, "owner_id": owner_id})
            await session.execute(text("""
                INSERT INTO records(
                  record_id,record_key,source_key,owner_subject_id,
                  classification,lifecycle
                ) VALUES (
                  :record_id,:record_key,'tip011-integration',:owner_id,
                  'internal','active'
                )
            """), {
                "record_id": record_id,
                "record_key": record_key or f"TIP011.{uuid.uuid4().hex}",
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
              :version_id,:record_id,:package_id,:package_revision,
              :version_ordinal,:owner_id,'internal',CAST(:payload AS jsonb),
              'governed fact','verified_primary',1,'verified','verified',
              :effective_from,:effective_to,'{}',:freshness_due_at,'current',
              ARRAY['tip011-integration'],'[]',:checksum,'active'
            )
        """), {
            "version_id": version_id,
            "record_id": record_id,
            "package_id": package_id,
            "package_revision": package_revision,
            "version_ordinal": version_ordinal,
            "owner_id": owner_id,
            "payload": json.dumps(payload),
            "effective_from": datetime.now(UTC) - timedelta(days=30),
            "effective_to": effective_to,
            "freshness_due_at": freshness_due_at,
            "checksum": checksum,
        })
        if set_current:
            await session.execute(text("""
                UPDATE records SET current_version_id=:version_id
                WHERE record_id=:record_id
            """), {"version_id": version_id, "record_id": record_id})
    return version_id, record_id


@pytest.mark.asyncio
async def test_subject_picker_two_subject_scoping_cursor_and_audit(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    """AC-06: only assign-capable callers can read the directory; probing
    reveals nothing through results, counts, cursors or error shape."""
    marker = f"TIP011 Picker {uuid.uuid4().hex[:8]}"
    curator_id, staff_id, first_id, second_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
    )
    await insert_actor(factory, curator_id, display_name="TIP011 Curator")
    await insert_actor(factory, staff_id)
    await insert_actor(factory, first_id, display_name=f"{marker} An")
    await insert_actor(factory, second_id, display_name=f"{marker} Binh")
    curator = subject(Role.CURATOR, curator_id)

    with pytest.raises(PermissionError, match="curator_required"):
        await service.search_subjects(
            subject(Role.STAFF, staff_id),
            marker,
            request_id="pick-sub-denied",
        )

    page = await service.search_subjects(
        curator,
        marker,
        request_id="pick-sub-1",
    )
    assert {item.subject_id for item in page.items} == {first_id, second_id}
    assert page.next_cursor is None
    assert all(item.email for item in page.items)

    first_page = await service.search_subjects(
        curator,
        marker,
        request_id="pick-sub-2",
        limit=1,
    )
    assert len(first_page.items) == 1
    assert first_page.next_cursor
    second_page = await service.search_subjects(
        curator,
        marker,
        request_id="pick-sub-3",
        cursor=first_page.next_cursor,
        limit=1,
    )
    assert len(second_page.items) == 1
    assert (
        {first_page.items[0].subject_id, second_page.items[0].subject_id}
        == {first_id, second_id}
    )

    # Kind-bound cursors: a gap-family cursor never opens the picker.
    foreign = encode_signed_cursor(
        "gaps",
        datetime.now(UTC),
        uuid.uuid4(),
        service._secret(),
    )
    with pytest.raises(GovernanceError, match="invalid_cursor"):
        await service.search_subjects(
            curator,
            marker,
            request_id="pick-sub-4",
            cursor=foreign,
        )

    empty = await service.search_subjects(
        curator,
        f"TIP011 Nothing {uuid.uuid4().hex[:8]}",
        request_id="pick-sub-5",
    )
    assert empty.items == []
    assert empty.next_cursor is None

    async with factory() as session:
        rows = (await session.execute(text("""
            SELECT details->>'returned_count' AS returned
            FROM audit_events
            WHERE action='governance.picker.subjects'
              AND actor_user_id=:actor AND request_id='pick-sub-1'
        """), {"actor": curator_id})).mappings().all()
    assert [row["returned"] for row in rows] == ["2"]


@pytest.mark.asyncio
async def test_record_picker_policy_filtered_zero_leak_and_title_match(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    """AC-06: adversarial two-subject probe — the stranger's result for an
    existing key is byte-identical to a nonexistent key's result."""
    owner_id, stranger_id, curator_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for actor_id in (owner_id, stranger_id, curator_id):
        await insert_actor(factory, actor_id)
    marker = f"TIP011.PICK.{uuid.uuid4().hex[:8]}"
    title = f"TIP011 Title {uuid.uuid4().hex[:8]}"
    first_version, _ = await insert_sot_version(
        factory,
        owner_id,
        record_key=f"{marker}.WARRANTY",
    )
    second_version, _ = await insert_sot_version(
        factory,
        owner_id,
        record_key=f"TIP011.OTHER.{uuid.uuid4().hex[:8]}",
        title=title,
    )
    owner = subject(Role.STAFF, owner_id)
    stranger = subject(Role.STAFF, stranger_id)
    curator = subject(Role.CURATOR, curator_id)

    mine = await service.search_records(owner, marker, request_id="pick-rec-1")
    assert [item.record_version_id for item in mine.items] == [first_version]
    assert mine.items[0].zone_label == "sot"
    assert mine.items[0].record_key.startswith(marker)

    by_title = await service.search_records(owner, title, request_id="pick-rec-2")
    assert [item.record_version_id for item in by_title.items] == [second_version]
    assert by_title.items[0].title == title

    denied = await service.search_records(
        stranger,
        marker,
        request_id="pick-rec-3",
    )
    nothing = await service.search_records(
        stranger,
        f"TIP011.NOTHING.{uuid.uuid4().hex[:8]}",
        request_id="pick-rec-4",
    )
    assert denied.model_dump() == nothing.model_dump() == {
        "items": [],
        "next_cursor": None,
    }, "denied existence is indistinguishable from nonexistence"

    elevated = await service.search_records(
        curator,
        marker,
        request_id="pick-rec-5",
    )
    assert first_version in {item.record_version_id for item in elevated.items}

    # A percent wildcard is literal input, not a match-everything probe.
    wildcard = await service.search_records(owner, "%", request_id="pick-rec-6")
    assert wildcard.items == []

    async with factory() as session:
        audited = (await session.execute(text("""
            SELECT request_id FROM audit_events
            WHERE action='governance.picker.records'
              AND request_id IN ('pick-rec-1','pick-rec-3')
        """))).scalars().all()
    assert set(audited) == {"pick-rec-1", "pick-rec-3"}


@pytest.mark.asyncio
async def test_dashboard_conflict_and_owner_review_tiles_live_and_scoped(
    factory: async_sessionmaker[Any],
    service: GovernanceService,
) -> None:
    """AC-08: both new tiles compute live under the caller's policy scope
    with the same leak-safety as the existing tiles."""
    owner_id, stranger_id, curator_id, assignee_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
    )
    for actor_id in (owner_id, stranger_id, curator_id, assignee_id):
        await insert_actor(factory, actor_id)
    now = datetime.now(UTC)
    conflict_version, conflict_record = await insert_sot_version(
        factory,
        owner_id,
        record_key=f"TIP011.CONFLICT.{uuid.uuid4().hex[:8]}",
    )
    await insert_sot_version(
        factory,
        owner_id,
        record_id=conflict_record,
        version_ordinal=2,
        package_revision=2,
        set_current=False,
    )
    review_version, _ = await insert_sot_version(
        factory,
        owner_id,
        record_key=f"TIP011.REVIEW.{uuid.uuid4().hex[:8]}",
        freshness_due_at=now - timedelta(hours=2),
    )
    await insert_sot_version(
        factory,
        owner_id,
        record_key=f"TIP011.REVIEW.{uuid.uuid4().hex[:8]}",
        freshness_due_at=now + timedelta(hours=100),
    )
    dashboard_service = DashboardService(uow=UnitOfWork(factory))

    owner_request_id = f"tiles-owner-{uuid.uuid4().hex}"
    owner_view = await dashboard_service.dashboard(
        subject(Role.STAFF, owner_id),
        request_id=owner_request_id,
    )
    assert owner_view.conflict.zone_label == "sot"
    assert owner_view.conflict.total == 1
    assert owner_view.conflict.disputed == 1
    assert owner_view.conflict.superseded_ambiguous == 0
    assert owner_view.conflict.unassigned == 1
    assert owner_view.owner_review.zone_label == "sot"
    assert owner_view.owner_review.total == 2
    assert owner_view.owner_review.overdue == 1
    assert owner_view.owner_review.due == 1
    assert owner_view.owner_review.unassigned == 2

    stranger_view = await dashboard_service.dashboard(
        subject(Role.STAFF, stranger_id),
        request_id="tiles-stranger-1",
    )
    assert stranger_view.conflict.total == 0
    assert stranger_view.conflict.disputed == 0
    assert stranger_view.owner_review.total == 0
    assert stranger_view.owner_review.overdue == 0, (
        "denied existence never enters a tile"
    )

    # Queue payloads themselves carry the literal zone labels (AC-07).
    queue = await service.queue_page(
        subject(Role.STAFF, owner_id),
        "owner_review",
        request_id="tiles-queue-1",
    )
    assert queue.zone_label == "sot"
    assert queue.entries
    assert all(entry.zone_label == "sot" for entry in queue.entries)
    assert review_version in {entry.record_version_id for entry in queue.entries}

    # Live recomputation: an assignment reflects on the next dashboard read.
    task = await service.assign_queue_task(
        subject(Role.CURATOR, curator_id),
        "conflict",
        record_version_id=conflict_version,
        assignee_subject_id=assignee_id,
        request_id="tiles-assign-1",
    )
    assert task.zone_label == "sot"
    live_view = await dashboard_service.dashboard(
        subject(Role.STAFF, owner_id),
        request_id="tiles-owner-2",
    )
    assert live_view.conflict.assigned == 1
    assert live_view.conflict.unassigned == 0
    async with factory() as session:
        audited = (await session.execute(text("""
            SELECT details->>'conflict_total' AS conflict_total
            FROM audit_events
            WHERE action='governance.dashboard.view'
              AND request_id=:request_id
        """), {"request_id": owner_request_id})).scalars().all()
    assert audited == ["1"]


@pytest.mark.asyncio
async def test_grounded_citation_zone_label_and_owner_only_conversation_list(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    """AC-07 + Task 4: a real grounded answer's citations carry the literal
    SOT zone label, and the conversation list is owner-only metadata with the
    already-stored first-question digest and HMAC cursors."""
    owner_id, stranger_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, owner_id)
    await insert_actor(factory, stranger_id)
    owner = subject(Role.STAFF, owner_id)
    stranger = subject(Role.STAFF, stranger_id)
    settings = get_settings().model_copy(update={
        "sot_staging_root": tmp_path,
        "sot_signing_secret": SecretStr(SECRET),
        "rag_provider_mode": "local",
    })
    source_key = f"tip011.rag.{uuid.uuid4().hex}"
    record_key = f"TIP011.HERA.{uuid.uuid4().hex}"
    package_root = build_package(
        tmp_path,
        curator_id=owner_id,
        owner_id=owner_id,
        source_key=source_key,
        record_key=record_key,
        revision=1,
        ordinal=1,
        supersedes=False,
        classification="internal",
        text="HERA autonomous drone supports synthetic inspection missions.",
    )
    sot = SOTPublishService(settings, factory=factory, clock=lambda: NOW)
    staged = await sot.stage(
        package_root.name,
        actor_id=owner_id,
        request_id="tip011-stage",
    )
    assert (await sot.validate(
        staged.package_id,
        actor_id=owner_id,
        request_id="tip011-validate",
    )).valid
    published = await sot.publish(
        staged.package_id,
        actor_id=owner_id,
        request_id="tip011-publish",
    )
    async with factory() as session:
        outbox_id = await session.scalar(text("""
            SELECT outbox_id FROM sot_reindex_outbox WHERE run_id=:run_id
        """), {"run_id": published.run_id})
    assert outbox_id
    await ReindexService(settings, factory=factory).process(outbox_id)

    answers = AnswerService(
        settings,
        factory=factory,
        retrieval=RetrievalService(settings, factory=factory),
        provider=OfflineExtractiveAnswer(),
    )
    first_question = "What inspection can the autonomous drone support?"
    first = await answers.ask(
        owner,
        first_question,
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="tip011-ask-1",
    )
    assert first.state == "grounded"
    assert first.citations
    assert all(item.zone_label == "sot" for item in first.citations)
    serialized = first.model_dump(mode="json")
    assert all(
        item["zone_label"] == "sot" for item in serialized["citations"]
    ), "the literal ships in the serialized payload"

    second = await answers.ask(
        owner,
        "What missions does the drone fly?",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="tip011-ask-2",
    )
    assert second.conversation_id != first.conversation_id

    async def as_owner() -> Subject:
        return owner

    async def as_stranger() -> Subject:
        return stranger

    transport = ASGITransport(app=app)
    try:
        app.dependency_overrides[rag_subject] = as_owner
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get("/api/v1/conversations")
            assert listed.status_code == 200
            body = listed.json()
            ids = [item["conversation_id"] for item in body["items"]]
            assert str(first.conversation_id) in ids
            assert str(second.conversation_id) in ids
            stamps = [item["last_activity_at"] for item in body["items"]]
            assert stamps == sorted(stamps, reverse=True), "newest activity first"
            mine = {
                item["conversation_id"]: item for item in body["items"]
            }
            assert (
                mine[str(first.conversation_id)]["first_question_digest"]
                == digest(first_question)
            ), "digest is the stored content_sha256, no new storage"

            page_one = await client.get(
                "/api/v1/conversations",
                params={"limit": 1},
            )
            assert page_one.status_code == 200
            assert len(page_one.json()["items"]) == 1
            cursor = page_one.json()["next_cursor"]
            assert cursor
            page_two = await client.get(
                "/api/v1/conversations",
                params={"limit": 1, "cursor": cursor},
            )
            assert page_two.status_code == 200
            assert (
                page_two.json()["items"][0]["conversation_id"]
                != page_one.json()["items"][0]["conversation_id"]
            )

        app.dependency_overrides[rag_subject] = as_stranger
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            foreign = await client.get("/api/v1/conversations")
            assert foreign.status_code == 200
            foreign_ids = {
                item["conversation_id"] for item in foreign.json()["items"]
            }
            assert str(first.conversation_id) not in foreign_ids
            assert str(second.conversation_id) not in foreign_ids
    finally:
        app.dependency_overrides.pop(rag_subject, None)

    async with factory() as session:
        audited = await session.scalar(text("""
            SELECT count(*) FROM audit_events
            WHERE action='rag.conversation.list' AND actor_user_id=:actor
        """), {"actor": owner_id})
    assert audited and int(audited) >= 2
