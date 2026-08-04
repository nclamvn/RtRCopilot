import asyncio
import hashlib
import io
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.auth.models import (
    PolicyContext,
    Role,
    SubjectStatus,
    TemporaryEntitlement,
)
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.infra.dependencies import DatabaseSchemaOutdated, _postgres
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.repositories.objects import ObjectRepository
from rtr_copilot.repositories.resources import ACLRecord, ResourceRecord, ResourceRepository
from rtr_copilot.storage.s3 import S3ObjectStorage, StoredObject

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
OWNER_DSN = os.getenv("MIGRATION_DSN")
pytestmark = pytest.mark.skipif(not DATABASE_DSN, reason="integration database not configured")


class MemoryAudit:
    def emit(self, _: Any) -> None:
        return None


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.bucket = "integration"
        self.delete_calls: list[str] = []

    async def upload_stream(
        self,
        *,
        key: str,
        stream: Any,
        mime_type: str,
        declared_sha256: str | None = None,
    ) -> StoredObject:
        data = stream.read()
        digest = hashlib.sha256(data).hexdigest()
        if declared_sha256 and declared_sha256 != digest:
            raise ValueError("checksum_mismatch")
        self.objects[key] = data
        return StoredObject(self.bucket, key, digest, len(data), "not-checksum")

    async def head(self, key: str) -> dict[str, int]:
        return {"ContentLength": len(self.objects[key])}

    async def verify(
        self,
        *,
        key: str,
        expected_sha256: str,
        expected_size: int,
        recompute: bool = True,
    ) -> dict[str, int]:
        data = self.objects[key]
        if (
            len(data) != expected_size
            or hashlib.sha256(data).hexdigest() != expected_sha256
        ):
            raise ValueError("object_content_integrity_mismatch")
        return {"ContentLength": len(data)}

    async def inventory(self) -> list[dict[str, Any]]:
        return [{"key": key, "byte_size": len(value)} for key, value in self.objects.items()]

    async def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        self.objects.pop(key)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(DATABASE_DSN.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    ))
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def owner_factory() -> async_sessionmaker[Any]:
    assert OWNER_DSN
    engine = create_async_engine(OWNER_DSN.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    ))
    return async_sessionmaker(engine, expire_on_commit=False)


def corporate_claims(sub: str, email: str, name: str = "Same Name") -> dict[str, Any]:
    return {
        "iss": "https://integration.identity",
        "sub": sub,
        "email": email,
        "email_verified": True,
        "name": name,
        "groups": [],
    }


@pytest.mark.asyncio
async def test_schema_extensions_revision_and_identity_adapter_parity(
    factory: async_sessionmaker[Any],
) -> None:
    async with factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        extensions = set((await session.execute(text(
            "SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','vector')",
        ))).scalars())
    assert revision == "0011_ingestion_pub_deferred"
    assert extensions == {"pgcrypto", "vector"}

    repository = PostgresSubjectRepository(factory)
    suffix = uuid.uuid4().hex
    first = await repository.upsert_from_claims(
        corporate_claims(f"one-{suffix}", f"one-{suffix}@rtrobotics.com"),
        {},
    )
    renamed = await repository.upsert_from_claims(
        corporate_claims(f"one-{suffix}", f"renamed-{suffix}@rtrobotics.com"),
        {},
    )
    second = await repository.upsert_from_claims(
        corporate_claims(f"two-{suffix}", f"two-{suffix}@rtrobotics.com"),
        {},
    )
    assert first.user_id == renamed.user_id
    assert first.user_id != second.user_id
    async with factory() as session, session.begin():
        await session.execute(text(
            "UPDATE subjects SET status='disabled' WHERE user_id=:user_id",
        ), {"user_id": uuid.UUID(first.user_id)})
    disabled = await repository.upsert_from_claims(
        corporate_claims(f"one-{suffix}", f"again-{suffix}@rtrobotics.com"),
        {},
    )
    assert disabled.user_id == first.user_id
    assert disabled.status.value == "disabled"

    settings = get_settings()
    await _postgres(settings)
    async with owner_factory_from_dsn() as session, session.begin():
        await session.execute(text(
            "UPDATE alembic_version SET version_num='0003_resource_object_foundation'",
        ))
    with pytest.raises(DatabaseSchemaOutdated):
        await _postgres(settings)
    async with owner_factory_from_dsn() as session, session.begin():
        await session.execute(text(
            "UPDATE alembic_version SET version_num='0011_ingestion_pub_deferred'",
        ))


@pytest.mark.asyncio
async def test_resource_acl_roundtrip_and_48_policy_parity_scenarios(
    factory: async_sessionmaker[Any],
) -> None:
    repository = ResourceRepository()
    principal = uuid.uuid4()
    resources: dict[str, uuid.UUID] = {}
    async with factory() as session, session.begin():
        for classification in (
            "public_internal",
            "internal",
            "restricted",
            "highly_restricted",
        ):
            record = ResourceRecord(
                resource_type="document",
                classification=classification,
                source_zone="sot",
                lifecycle_state="active",
            )
            await repository.create(session, record)
            resources[classification] = record.resource_id
        await repository.add_acl(
            session,
            ACLRecord(
                resource_id=resources["restricted"],
                principal_type="user",
                principal_id=principal,
                action="view",
                effect="deny",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            ),
            request_id="acl-active",
        )
        await repository.add_acl(
            session,
            ACLRecord(
                resource_id=resources["restricted"],
                principal_type="user",
                principal_id=principal,
                action="download",
                effect="allow",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
            request_id="acl-expired",
        )
    async with factory() as session:
        rows = await repository.active_acl(session, resources["restricted"])
        assert len(rows) == 1
        scenarios = 0
        for role, clearance in (
            (Role.STAFF, 1),
            (Role.LEADER, 2),
            (Role.CURATOR, 2),
            (Role.ADMIN, 1),
        ):
            subject_repository = PostgresSubjectRepository(factory)
            subject = await subject_repository.upsert_from_claims(
                corporate_claims(
                    f"policy-{role}-{uuid.uuid4().hex}",
                    f"{uuid.uuid4().hex}@rtrobotics.com",
                ),
                {},
            )
            subject.roles = {role}
            for classification, level in (
                ("public_internal", 0),
                ("internal", 1),
                ("restricted", 2),
                ("highly_restricted", 3),
            ):
                for action in ("view", "download", "render"):
                    attributes = await repository.policy_attributes(
                        session,
                        resources[classification],
                        action=action,
                        principal_ids=set(),
                    )
                    assert attributes is not None
                    decision = PolicyEngine(MemoryAudit()).decide(
                        subject,
                        action,
                        attributes,
                        PolicyContext(request_id="postgres-parity"),
                    )
                    assert decision.allow is (level <= clearance)
                    scenarios += 1
        assert scenarios == 48
        denied = await repository.policy_attributes(
            session,
            resources["restricted"],
            action="view",
            principal_ids={principal},
        )
        assert denied is not None and denied.explicit_deny
        deleted = ResourceRecord(
            resource_type="document",
            classification="internal",
            source_zone="sot",
            lifecycle_state="deleted",
        )
        quarantined = ResourceRecord(
            resource_type="document",
            classification="internal",
            source_zone="sot",
            lifecycle_state="quarantined",
        )
    async with factory() as session, session.begin():
        await repository.create(session, deleted)
        await repository.create(session, quarantined)
        held = ResourceRecord(
            resource_type="object",
            classification="restricted",
            source_zone="private_context",
            legal_hold=True,
        )
        retained = ResourceRecord(
            resource_type="object",
            classification="restricted",
            source_zone="private_context",
            retention_until=datetime.now(UTC) + timedelta(days=1),
        )
        conservative = ResourceRecord(
            resource_type="object",
            classification="internal",
            source_zone="private_context",
        )
        await repository.create(session, held)
        await repository.create(session, retained)
        await repository.create(session, conservative)
    async with factory() as session:
        assert await repository.policy_attributes(
            session, deleted.resource_id, action="view", principal_ids=set(),
        ) is None
        assert await repository.policy_attributes(
            session, quarantined.resource_id, action="view", principal_ids=set(),
        ) is None
        with pytest.raises(PermissionError, match="legal_hold"):
            await repository.assert_purge_allowed(
                session, held.resource_id, retention_configured=True,
            )
        with pytest.raises(PermissionError, match="retention_active"):
            await repository.assert_purge_allowed(
                session, retained.resource_id, retention_configured=True,
            )
        with pytest.raises(PermissionError, match="retention_policy_unconfigured"):
            await repository.assert_purge_allowed(
                session, conservative.resource_id, retention_configured=False,
            )

    rollback_principal = uuid.uuid4()
    with pytest.raises(RuntimeError, match="rollback"):
        async with factory() as session, session.begin():
            await repository.add_acl(
                session,
                ACLRecord(
                    resource_id=resources["internal"],
                    principal_type="user",
                    principal_id=rollback_principal,
                    action="download",
                    effect="allow",
                ),
                request_id="acl-must-rollback",
            )
            raise RuntimeError("rollback")
    async with factory() as session:
        assert await session.scalar(text("""
            SELECT count(*) FROM acl_entries WHERE principal_id=:principal_id
        """), {"principal_id": rollback_principal}) == 0
        assert await session.scalar(text("""
            SELECT count(*) FROM audit_events WHERE request_id='acl-must-rollback'
        """)) == 0


@pytest.mark.asyncio
async def test_streamed_objects_concurrent_versions_and_orphan_report(
    factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rtr_copilot.db.uow import UnitOfWork

    storage = FakeStorage()
    repository = ObjectRepository(storage, UnitOfWork(factory))  # type: ignore[arg-type]
    identity = PostgresSubjectRepository(factory)
    suffix = uuid.uuid4().hex
    actor = await identity.upsert_from_claims(
        corporate_claims(f"object-{suffix}", f"object-{suffix}@rtrobotics.com"),
        {},
    )
    actor_id = uuid.UUID(actor.user_id)
    document_id = await repository.create_document(
        owner_id=actor_id,
        logical_name="Object concurrency",
    )
    first, second = await asyncio.gather(
        repository.stage_upload(
            stream=io.BytesIO(b"first"),
            mime_type="text/plain",
            created_by=actor_id,
            request_id="upload-first",
        ),
        repository.stage_upload(
            stream=io.BytesIO(b"second"),
            mime_type="text/plain",
            created_by=actor_id,
            request_id="upload-second",
        ),
    )
    versions = await asyncio.gather(
        repository.activate_version(
            document_id=document_id,
            staged=first,
            original_filename="../../first.txt",
            created_by=actor_id,
            request_id="version-first",
        ),
        repository.activate_version(
            document_id=document_id,
            staged=second,
            original_filename="../../second.txt",
            created_by=actor_id,
            request_id="version-second",
        ),
    )
    assert {item.version_no for item in versions} == {1, 2}
    async with factory() as session:
        current = await session.scalar(text(
            "SELECT current_version_id FROM documents WHERE document_id=:id",
        ), {"id": document_id})
        assert current in {item.version_id for item in versions}
    storage.objects["staging/orphan"] = b"orphan"
    interrupted = await repository.stage_upload(
        stream=io.BytesIO(b"interrupted"),
        mime_type="text/plain",
        created_by=actor_id,
        request_id="upload-interrupted",
    )
    storage.objects[interrupted.stored.key] = b"tamper-data"
    with pytest.raises(ValueError, match="object_content_integrity_mismatch"):
        await repository.activate_version(
            document_id=document_id,
            staged=interrupted,
            original_filename="interrupted.txt",
            created_by=actor_id,
            request_id="version-interrupted",
        )
    report = await repository.reconcile()
    assert report["storage_orphans"] == ["staging/orphan"]
    assert interrupted.stored.key in report["staged"]

    storage.objects["staging/audit-must-commit-first"] = b"protected"

    async def reject_audit(*_: Any, **__: Any) -> uuid.UUID:
        raise RuntimeError("audit_unavailable")

    monkeypatch.setattr(AuditRepository, "append", reject_audit)
    with pytest.raises(RuntimeError, match="audit_unavailable"):
        await repository.reconcile_delete(
            "staging/audit-must-commit-first",
            actor_id=actor_id,
            request_id="reconcile-audit-failure",
            explicit=True,
        )
    assert "staging/audit-must-commit-first" in storage.objects
    assert storage.delete_calls == []


@pytest.mark.asyncio
async def test_audit_chain_redaction_transactionality_and_tamper_detection(
    factory: async_sessionmaker[Any],
    owner_factory: async_sessionmaker[Any],
) -> None:
    audit = AuditRepository()
    async with factory() as session, session.begin():
        await audit.append(
            session,
            actor_kind="service",
            actor_user_id=None,
            action="integration.success",
            result="success",
            reason_code="fixture",
            request_id="audit-fixture",
            details={"nested": {"password": "never-store"}, "safe": "value"},
        )
    async with factory() as session:
        valid, count, head = await audit.verify(session)
        details = await session.scalar(text(
            "SELECT details FROM audit_events WHERE request_id='audit-fixture'",
        ))
        assert valid and count > 0 and head
        assert "password" not in str(details).lower()

    async def append_concurrently(index: int) -> None:
        async with factory() as concurrent_session, concurrent_session.begin():
            await audit.append(
                concurrent_session,
                actor_kind="service",
                actor_user_id=None,
                action="integration.concurrent",
                result="success",
                reason_code="concurrent_fixture",
                request_id=f"audit-concurrent-{index}",
            )

    await asyncio.gather(*(append_concurrently(index) for index in range(5)))
    async with factory() as session:
        concurrent_valid, _, _ = await audit.verify(session)
        assert concurrent_valid

    with pytest.raises(RuntimeError):
        async with factory() as session, session.begin():
            await audit.append(
                session,
                actor_kind="service",
                actor_user_id=None,
                action="integration.rollback",
                result="failure",
                reason_code="injected",
                request_id="must-rollback",
            )
            raise RuntimeError("inject rollback")
    async with factory() as session:
        assert await session.scalar(text(
            "SELECT count(*) FROM audit_events WHERE request_id='must-rollback'",
        )) == 0

    for tamper_sql in (
        "DELETE FROM audit_events WHERE sequence=(SELECT max(sequence) FROM audit_events)",
        """DELETE FROM audit_events WHERE sequence=(
             SELECT sequence FROM audit_events ORDER BY sequence OFFSET 1 LIMIT 1
           )""",
        "UPDATE audit_events SET sequence = -sequence",
    ):
        async with owner_factory() as session:
            transaction = await session.begin()
            await session.execute(text(
                "ALTER TABLE audit_events DISABLE TRIGGER audit_no_update_delete",
            ))
            if tamper_sql.startswith("UPDATE audit_events SET sequence"):
                await session.execute(text("""
                    ALTER TABLE audit_events ALTER COLUMN sequence
                    SET GENERATED BY DEFAULT
                """))
            await session.execute(text(tamper_sql))
            tampered, _, _ = await audit.verify(session)
            assert not tampered
            await transaction.rollback()


@pytest.mark.asyncio
async def test_identity_mutation_rollback_and_maintenance_gate(
    factory: async_sessionmaker[Any],
    owner_factory: async_sessionmaker[Any],
) -> None:
    from rtr_copilot.db.uow import MaintenanceActive, UnitOfWork

    suffix = uuid.uuid4().hex
    repository = PostgresSubjectRepository(factory)
    current = await repository.upsert_from_claims(
        corporate_claims(f"authority-{suffix}", f"authority-{suffix}@rtrobotics.com"),
        {},
    )
    before = current.model_copy(deep=True)
    proposed = current.model_copy(deep=True)
    proposed.status = SubjectStatus.DISABLED
    proposed.roles = {Role.ADMIN, Role.CURATOR}
    proposed.groups = {"authority-admin"}
    proposed.departments = {"engineering"}
    proposed.projects = {"copilot-v2"}
    proposed.temporary_entitlements = [
        TemporaryEntitlement(
            action="download",
            classification="restricted",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        ),
    ]
    with pytest.raises(RuntimeError, match="injected_authority_failure"):
        await repository.mutate_authority(
            proposed,
            request_id="authority-must-rollback",
            actor_id=uuid.UUID(current.user_id),
            inject_failure=True,
        )
    rolled_back = await repository.get_by_identity(current.issuer, current.sub)
    assert rolled_back is not None
    assert rolled_back.status == before.status
    assert rolled_back.roles == before.roles
    assert rolled_back.groups == before.groups
    assert rolled_back.departments == before.departments
    assert rolled_back.projects == before.projects
    assert rolled_back.temporary_entitlements == before.temporary_entitlements
    async with factory() as session:
        assert await session.scalar(text("""
            SELECT count(*) FROM audit_events
            WHERE request_id='authority-must-rollback'
        """)) == 0

    await repository.mutate_authority(
        proposed,
        request_id="authority-committed",
        actor_id=uuid.UUID(current.user_id),
    )
    committed = await repository.get_by_identity(current.issuer, current.sub)
    assert committed is not None
    assert committed.status == SubjectStatus.DISABLED
    assert committed.roles == {Role.ADMIN, Role.CURATOR}
    assert committed.groups == {"authority-admin"}
    assert committed.departments == {"engineering"}
    assert committed.projects == {"copilot-v2"}
    assert len(committed.temporary_entitlements) == 1

    try:
        async with owner_factory() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(827005)"))
            await session.execute(text("""
                UPDATE maintenance_state SET enabled=true, reason='integration-test'
                WHERE singleton
            """))
        blocked_document = uuid.uuid4().hex
        storage = FakeStorage()
        objects = ObjectRepository(storage, UnitOfWork(factory))  # type: ignore[arg-type]
        with pytest.raises(MaintenanceActive):
            await objects.create_document(
                owner_id=uuid.UUID(current.user_id),
                logical_name=blocked_document,
            )
        async with factory() as session:
            assert await session.scalar(text("""
                SELECT count(*) FROM documents WHERE logical_name=:name
            """), {"name": blocked_document}) == 0
    finally:
        async with owner_factory() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(827005)"))
            await session.execute(text("""
                UPDATE maintenance_state SET enabled=false, reason=NULL
                WHERE singleton
            """))


def owner_factory_from_dsn() -> Any:
    assert OWNER_DSN
    engine = create_async_engine(OWNER_DSN.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    ))
    return async_sessionmaker(engine, expire_on_commit=False)()


@pytest.mark.asyncio
async def test_real_minio_object_persists_with_database_metadata(
    factory: async_sessionmaker[Any],
) -> None:
    from rtr_copilot.db.uow import UnitOfWork

    settings = get_settings()
    storage = S3ObjectStorage(settings)
    repository = ObjectRepository(storage, UnitOfWork(factory))
    identity = PostgresSubjectRepository(factory)
    suffix = uuid.uuid4().hex
    actor = await identity.upsert_from_claims(
        corporate_claims(f"drill-{suffix}", f"drill-{suffix}@rtrobotics.com"),
        {},
    )
    actor_id = uuid.UUID(actor.user_id)
    document_id = await repository.create_document(
        owner_id=actor_id,
        logical_name="Backup restore drill fixture",
    )
    payload = b"durable-object-for-backup-restore"
    staged = await repository.stage_upload(
        stream=io.BytesIO(payload),
        mime_type="application/octet-stream",
        created_by=actor_id,
        request_id="backup-drill-upload",
    )
    await repository.activate_version(
        document_id=document_id,
        staged=staged,
        original_filename="drill.bin",
        created_by=actor_id,
        request_id="backup-drill-version",
    )
    head = await storage.head(staged.stored.key)
    assert int(head["ContentLength"]) == len(payload)
    assert staged.stored.sha256 == hashlib.sha256(payload).hexdigest()

    tamper_payload = b"durable-object-for-backup-restorE"
    assert len(tamper_payload) == len(payload)
    trusted_head = await storage.head(staged.stored.key)
    await asyncio.to_thread(
        storage.client.put_object,
        Bucket=storage.bucket,
        Key=staged.stored.key,
        Body=tamper_payload,
        ContentType="application/octet-stream",
        Metadata=trusted_head["Metadata"],
    )
    with pytest.raises(ValueError, match="object_content_integrity_mismatch"):
        await storage.verify(
            key=staged.stored.key,
            expected_sha256=staged.stored.sha256,
            expected_size=staged.stored.byte_size,
        )
    await storage.upload_stream(
        key=staged.stored.key,
        stream=io.BytesIO(payload),
        mime_type="application/octet-stream",
        declared_sha256=staged.stored.sha256,
    )
