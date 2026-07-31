import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Role, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.repositories.resources import ResourceRepository
from rtr_copilot.sot.service import PublishError, SOTPublishService

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
def actor() -> uuid.UUID:
    return uuid.uuid4()


async def insert_actor(
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,'sot-integration',:sub,:email,'rtrobotics.com')
        """), {
            "id": actor_id,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
        })


def service(
    root: Path,
    factory: async_sessionmaker[Any],
) -> SOTPublishService:
    settings = get_settings().model_copy(update={
        "sot_staging_root": root,
        "sot_signing_secret": SecretStr(SECRET),
    })
    return SOTPublishService(settings, factory=factory, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_publish_projects_active_records_evidence_outbox_and_audit(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    source_key = f"success.{uuid.uuid4().hex}"
    record_key = f"SUCCESS.{uuid.uuid4().hex}"
    package_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=source_key,
        record_key=record_key,
    )
    publish = service(tmp_path, factory)
    staged = await publish.stage(
        package_root.name,
        actor_id=actor,
        request_id="stage-1",
    )
    report = await publish.validate(
        staged.package_id,
        actor_id=actor,
        request_id="validate-1",
    )
    assert report.valid
    result = await publish.publish(
        staged.package_id,
        actor_id=actor,
        request_id="publish-1",
    )
    assert result.state == "active"
    assert (await publish.active_record(record_key)) is not None
    async with factory() as session:
        state = (await session.execute(text("""
            SELECT p.lifecycle,r.state,
              (SELECT count(*) FROM evidence_spans e
               WHERE e.package_id=p.package_id AND e.lifecycle='active') evidence,
              (SELECT count(*) FROM sot_reindex_outbox o
               WHERE o.run_id=r.run_id) outbox,
              (SELECT count(*) FROM audit_events a
               WHERE a.action='sot.package.publish' AND a.request_id='publish-1'
                 AND a.details->>'package_id'=CAST(p.package_id AS text)) audit
            FROM sot_packages p JOIN sot_publish_runs r USING(package_id)
            WHERE p.package_id=:package_id
        """), {"package_id": staged.package_id})).mappings().one()
    assert dict(state) == {
        "lifecycle": "active",
        "state": "active",
        "evidence": 1,
        "outbox": 1,
        "audit": 1,
    }
    repeated = await publish.publish(
        staged.package_id,
        actor_id=actor,
        request_id="publish-idempotent",
    )
    assert repeated.idempotent


@pytest.mark.asyncio
async def test_failure_rolls_back_candidates_and_active_pointer(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    package_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=f"rollback.{uuid.uuid4().hex}",
        record_key=f"ROLLBACK.{uuid.uuid4().hex}",
    )
    publish = service(tmp_path, factory)
    staged = await publish.stage(
        package_root.name,
        actor_id=actor,
        request_id="rollback-stage",
    )
    await publish.validate(
        staged.package_id,
        actor_id=actor,
        request_id="rollback-validate",
    )
    with pytest.raises(PublishError, match="injected_failure"):
        await publish.publish(
            staged.package_id,
            actor_id=actor,
            request_id="rollback-publish",
            inject_failure="after_candidates",
        )
    async with factory() as session:
        candidates = await session.scalar(text(
            "SELECT count(*) FROM record_versions WHERE package_id=:package_id",
        ), {"package_id": staged.package_id})
        active = await session.scalar(text(
            "SELECT count(*) FROM sot_active_revisions WHERE package_id=:package_id",
        ), {"package_id": staged.package_id})
    assert candidates == 0
    assert active == 0


@pytest.mark.asyncio
async def test_revision_collision_and_publish_concurrency_are_safe(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    source_key = f"concurrent.{uuid.uuid4().hex}"
    record_key = f"CONCURRENT.{uuid.uuid4().hex}"
    package_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=source_key,
        record_key=record_key,
    )
    publish = service(tmp_path, factory)
    staged = await publish.stage(
        package_root.name,
        actor_id=actor,
        request_id="concurrent-stage",
    )
    await publish.validate(
        staged.package_id,
        actor_id=actor,
        request_id="concurrent-validate",
    )
    results = await asyncio.gather(
        publish.publish(
            staged.package_id,
            actor_id=actor,
            request_id="concurrent-a",
        ),
        publish.publish(
            staged.package_id,
            actor_id=actor,
            request_id="concurrent-b",
        ),
    )
    assert sum(not item.idempotent for item in results) == 1
    assert sum(item.idempotent for item in results) == 1
    duplicate = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=source_key,
        revision=1,
        record_key=record_key,
    )
    with pytest.raises(PublishError, match="revision_checksum_conflict"):
        await publish.stage(
            duplicate.name,
            actor_id=actor,
            request_id="collision",
        )


@pytest.mark.asyncio
async def test_failed_replacement_preserves_prior_and_rollback_is_rejected(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
    actor: uuid.UUID,
) -> None:
    await insert_actor(factory, actor)
    source_key = f"revision.{uuid.uuid4().hex}"
    record_key = f"REVISION.{uuid.uuid4().hex}"
    publish = service(tmp_path, factory)
    first_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=source_key,
        record_key=record_key,
        revision=1,
        classification="public_internal",
    )
    first = await publish.stage(
        first_root.name,
        actor_id=actor,
        request_id="first-stage",
    )
    await publish.validate(
        first.package_id,
        actor_id=actor,
        request_id="first-validate",
    )
    await publish.publish(
        first.package_id,
        actor_id=actor,
        request_id="first-publish",
    )
    second_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=source_key,
        record_key=record_key,
        revision=2,
        ordinal=2,
        supersedes=True,
        classification="restricted",
        acl_effect="deny",
    )
    second = await publish.stage(
        second_root.name,
        actor_id=actor,
        request_id="second-stage",
    )
    await publish.validate(
        second.package_id,
        actor_id=actor,
        request_id="second-validate",
    )
    with pytest.raises(PublishError, match="injected_failure"):
        await publish.publish(
            second.package_id,
            actor_id=actor,
            request_id="second-failed",
            inject_failure="after_swap",
        )
    async with factory() as session:
        active = (await session.execute(text("""
            SELECT package_id,revision FROM sot_active_revisions
            WHERE source_key=:source_key
        """), {"source_key": source_key})).mappings().one()
    assert active["package_id"] == first.package_id
    assert active["revision"] == 1
    await publish.publish(
        second.package_id,
        actor_id=actor,
        request_id="second-publish",
    )
    detail = await publish.active_record(record_key)
    assert detail is not None
    record_id = detail[0]
    async with factory() as session:
        projection = (await session.execute(text("""
            SELECT r.classification record_classification,
              rs.classification resource_classification,r.department_id,
              r.project_id,rs.department_id resource_department_id,
              rs.project_id resource_project_id
            FROM records r JOIN resources rs ON rs.resource_id=r.record_id
            WHERE r.record_id=:record_id
        """), {"record_id": record_id})).mappings().one()
        acl_rows = (await session.execute(text("""
            SELECT effect FROM acl_entries WHERE resource_id=:record_id
        """), {"record_id": record_id})).scalars().all()
        outsider_id = uuid.uuid4()
        attributes = await ResourceRepository().policy_attributes(
            session,
            record_id,
            action="view",
            principal_ids={outsider_id},
        )
    assert projection["record_classification"] == "restricted"
    assert projection["resource_classification"] == "restricted"
    assert projection["department_id"] == projection["resource_department_id"]
    assert projection["project_id"] == projection["resource_project_id"]
    assert list(acl_rows) == ["deny"]
    assert attributes is not None
    assert attributes.classification == "restricted"
    assert not attributes.explicit_deny
    staff = Subject(
        user_id=str(outsider_id),
        issuer="sot-integration",
        sub=outsider_id.hex,
        email=f"{outsider_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={Role.STAFF},
    )
    decision = PolicyEngine(StructuredAuditSink()).decide(
        staff,
        "view",
        attributes,
        PolicyContext(request_id="projection-regression"),
    )
    assert not decision.allow
    tamper_statements = [
        """
        UPDATE record_versions SET searchable_text='tampered'
        WHERE package_id=:package_id
        """,
        """
        UPDATE record_versions SET confidence=0
        WHERE package_id=:package_id
        """,
        """
        UPDATE evidence_spans SET normalized_text='tampered'
        WHERE package_id=:package_id
        """,
        """
        UPDATE evidence_spans SET source_label='tampered'
        WHERE package_id=:package_id
        """,
        "DELETE FROM evidence_spans WHERE package_id=:package_id",
        "DELETE FROM sot_reindex_outbox WHERE run_id=:run_id",
    ]
    for statement in tamper_statements:
        with pytest.raises(DBAPIError):
            async with factory() as session, session.begin():
                await session.execute(text(statement), {
                    "package_id": second.package_id,
                    "run_id": second.run_id,
                })
    rollback_source = f"rollback-order.{uuid.uuid4().hex}"
    rollback_record = f"ROLLBACK-ORDER.{uuid.uuid4().hex}"
    newer_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=rollback_source,
        record_key=rollback_record,
        revision=2,
        ordinal=2,
    )
    newer = await publish.stage(
        newer_root.name,
        actor_id=actor,
        request_id="newer-stage",
    )
    await publish.validate(
        newer.package_id,
        actor_id=actor,
        request_id="newer-validate",
    )
    await publish.publish(
        newer.package_id,
        actor_id=actor,
        request_id="newer-publish",
    )
    older_root = build_package(
        tmp_path,
        curator_id=actor,
        owner_id=actor,
        source_key=rollback_source,
        record_key=rollback_record,
        revision=1,
        ordinal=1,
    )
    older = await publish.stage(
        older_root.name,
        actor_id=actor,
        request_id="older-stage",
    )
    await publish.validate(
        older.package_id,
        actor_id=actor,
        request_id="older-validate",
    )
    with pytest.raises(PublishError, match="revision_not_monotonic"):
        await publish.publish(
            older.package_id,
            actor_id=actor,
            request_id="older-publish",
        )
