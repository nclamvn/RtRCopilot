"""Synthetic render recovery faults; no Redis, S3 or provider calls."""

import asyncio
import base64
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO

import pytest
import test_documents_integration as document_fixtures
from pydantic import SecretStr
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_documents_unit import pdf_template

from rtr_copilot.auth.models import Role
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import (
    BindingDefinition,
    FieldRules,
    RenderRequest,
    TemplateImport,
    TemplateSchema,
)
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.ingestion.malware import DeterministicTestScanner
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.sot.service import SOTPublishService
from rtr_copilot.storage.s3 import StoredObject

pytestmark = document_fixtures.pytestmark


@pytest.fixture
def factory() -> Any:
    return document_fixtures.factory.__wrapped__()


async def approved_template(factory: Any, record_key: str | None = None,
                            owner: Any = None) -> Any:
    owner = owner or await document_fixtures.principal(
        factory, "recovery-owner", {Role.CURATOR, Role.STAFF},
    )
    service = DocumentOSService(UnitOfWork(factory))
    binding = (BindingDefinition(field_path="range", field_type="string", source="locked_fact",
                                 required=True, record_key=record_key, value_literal="15 km",
                                 rules=FieldRules(max_length=100),
                                 accepted_provenance=["approved_internal"])
               if record_key else BindingDefinition(field_path="customer_name", field_type="string",
                                                   source="user", required=True,
                                                   rules=FieldRules(max_length=100)))
    template = await service.import_template(owner, TemplateImport(
        stable_key=f"recovery.{uuid.uuid4().hex}", display_name="Synthetic recovery",
        category="verification", format="pdf", field_schema=TemplateSchema(bindings=[binding]),
        source_base64=base64.b64encode(pdf_template()).decode(),
    ), request_id="recovery-import")
    await service.lifecycle(owner, template.version_id, "submit", request_id="submit")
    await service.lifecycle(owner, template.version_id, "approve", request_id="approve")
    return service, owner, template.version_id


class MemoryStorage:
    bucket = "synthetic-recovery"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.pipeline_errors: list[str] = []

    async def upload_stream(
        self, *, key: str, stream: BinaryIO, **kwargs: Any,
    ) -> StoredObject:
        data = stream.read()
        self.objects[key] = data
        return StoredObject(self.bucket, key, hashlib.sha256(data).hexdigest(), len(data), None)

    async def download_to(self, key: str, target: BinaryIO) -> None:
        target.write(self.objects[key])
        target.seek(0)

    async def verify(self, *, key: str, expected_sha256: str, expected_size: int,
                     **kwargs: Any) -> dict[str, Any]:
        data = self.objects[key]
        assert len(data) == expected_size
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        return {"ContentLength": len(data)}

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


class LostRedis:
    async def lpush(self, *args: Any) -> int:
        raise ConnectionError("synthetic-notification-loss")

    async def aclose(self) -> None:
        pass


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> MemoryStorage:
    from rtr_copilot.config import get_settings

    storage = MemoryStorage()
    monkeypatch.setattr("rtr_copilot.documents.service.S3ObjectStorage", lambda _: storage)
    monkeypatch.setattr("rtr_copilot.documents.service.Redis.from_url", lambda *a, **k: LostRedis())
    def build() -> IngestionService:
        service = IngestionService(
            settings=get_settings().model_copy(update={"ingestion_ocr_enabled": False}),
            storage=storage, uow=UnitOfWork(factory),
            scanner=DeterministicTestScanner("clean"),
        )
        original = service._process_rendition

        async def diagnostic(claim: Any) -> None:
            try:
                await original(claim)
            except Exception as error:
                storage.pipeline_errors.append(repr(error))
                raise

        service._process_rendition = diagnostic  # type: ignore[method-assign]
        return service

    monkeypatch.setattr("rtr_copilot.documents.service.IngestionService", build)
    return storage


@pytest.mark.asyncio
async def test_committed_request_survives_notification_failure(factory: Any,
                                                              local_boundaries: Any) -> None:
    service, owner, version_id = await approved_template(factory)
    status = await service.create_render(owner, version_id, RenderRequest(
        idempotency_key=f"lost-{uuid.uuid4()}", parameters={"customer_name": "Lost hint"},
    ), request_id=f"recovery-{uuid.uuid4()}")
    assert status.state == "pending"
    # The isolated DB retains earlier fault evidence; a poller drains in order.
    for _ in range(10):
        assert await service.process_next(worker_id="durable-poller")
        final = await service.status(owner, status.render_job_id, request_id="status")
        if final.state != "pending":
            break
    assert final.state == "completed", local_boundaries.pipeline_errors
    duplicate = await service.create_render(owner, version_id, RenderRequest(
        idempotency_key=f"another-{uuid.uuid4()}", parameters={"customer_name": "Lost hint"},
    ), request_id="duplicate")
    assert duplicate.render_job_id == final.render_job_id
    await service.process_render(final.render_job_id)
    assert await generated_count(factory, final.render_job_id) == 1


@pytest.mark.asyncio
async def test_worker_loss_does_not_leave_indefinite_rendering(factory: Any,
                                                             local_boundaries: Any) -> None:
    service, owner, version_id = await approved_template(factory)
    # Use a successful but dropped notification for the stale-render proof.
    async def dropped(*args: Any) -> int:
        return 1

    LostRedis.lpush = dropped  # type: ignore[method-assign]
    try:
        status = await service.create_render(owner, version_id, RenderRequest(
            idempotency_key=f"crash-{uuid.uuid4()}", parameters={"customer_name": "Crash"},
        ), request_id=f"recovery-{uuid.uuid4()}")
    finally:
        async def lost(*args: Any) -> int:
            raise ConnectionError("synthetic-notification-loss")
        LostRedis.lpush = lost  # type: ignore[method-assign]
    async with factory() as session, session.begin():
        await session.execute(text("""
            UPDATE render_jobs SET state='rendering',started_at=now()-interval '2 hours'
            WHERE render_job_id=:job
        """), {"job": status.render_job_id})
        await session.execute(text("""
            UPDATE document_publication_outbox SET state='preparing'
            WHERE render_job_id=:job
        """), {"job": status.render_job_id})
    await service.process_render(status.render_job_id)
    final = await service.status(owner, status.render_job_id, request_id="status")
    assert final.state == "failed"
    assert final.error_code == "render_lease_expired"
    assert final.retryable
    await service.render_action(owner, status.render_job_id, "retry", request_id="retry")
    await service.process_render(status.render_job_id)
    recovered = await service.status(owner, status.render_job_id, request_id="status")
    assert recovered.state == "completed"
    assert recovered.render_job_id == status.render_job_id


async def submit(service: Any, owner: Any, version: uuid.UUID, label: str) -> Any:
    return await service.create_render(owner, version, RenderRequest(
        idempotency_key=f"{label}-{uuid.uuid4()}", parameters={"customer_name": label},
    ), request_id=f"recovery-{uuid.uuid4()}")


async def generated_count(factory: Any, job: uuid.UUID) -> int:
    async with factory() as session:
        return int(await session.scalar(text(
            "SELECT count(*) FROM generated_files WHERE render_job_id=:job",
        ), {"job": job}))


def pause_first_staged(monkeypatch: pytest.MonkeyPatch, factory: Any,
                       storage: MemoryStorage, *, obsolete_error: bool = False) -> Any:
    from rtr_copilot.config import get_settings

    entered, release = asyncio.Event(), asyncio.Event()
    first = True

    def build() -> IngestionService:
        service = IngestionService(
            settings=get_settings().model_copy(update={"ingestion_ocr_enabled": False}),
            storage=storage, uow=UnitOfWork(factory), scanner=DeterministicTestScanner("clean"),
        )
        original = service.process_job

        async def process(job_id: uuid.UUID, *, worker_id: str) -> bool:
            nonlocal first
            result = await original(job_id, worker_id=worker_id)
            async with factory() as session:
                kind = await session.scalar(text(
                    "SELECT job_type FROM ingestion_jobs WHERE job_id=:job",
                ), {"job": job_id})
            if kind == "render" and first:
                first = False
                entered.set()
                await release.wait()
                if obsolete_error:
                    raise ValueError("synthetic-obsolete-worker-error")
            return result

        service.process_job = process  # type: ignore[method-assign]
        return service

    monkeypatch.setattr("rtr_copilot.documents.service.IngestionService", build)
    return entered, release


@pytest.mark.asyncio
@pytest.mark.parametrize("obsolete_error", [False, True])
async def test_obsolete_worker_cannot_publish_fail_or_delete_new_success(
    factory: Any, local_boundaries: MemoryStorage, monkeypatch: pytest.MonkeyPatch,
    obsolete_error: bool,
) -> None:
    service, owner, version = await approved_template(factory)
    status = await submit(service, owner, version, "obsolete")
    entered, release = pause_first_staged(monkeypatch, factory, local_boundaries,
                                         obsolete_error=obsolete_error)
    old_worker = asyncio.create_task(service.process_render(status.render_job_id, worker_id="old"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with factory() as session, session.begin():
            await session.execute(text("""
                UPDATE render_jobs SET lease_expires_at=now()-interval '1 second'
                WHERE render_job_id=:job
            """), {"job": status.render_job_id})
        assert await service.jobs.expire(status.render_job_id) == 1
        await service.render_action(owner, status.render_job_id, "retry", request_id="retry")
        await service.process_render(status.render_job_id, worker_id="new")
        newer = await service.status(owner, status.render_job_id, request_id="status")
        assert newer.state == "completed"
    finally:
        release.set()
        await old_worker
    final = await service.status(owner, status.render_job_id, request_id="status")
    assert final == newer
    assert final.attempt == 2
    assert await generated_count(factory, final.render_job_id) == 1
    assert local_boundaries.deleted == []
    async with factory() as session:
        versions = (await session.execute(text("""
            SELECT u.version_id,r.lifecycle_state FROM upload_sessions u
            JOIN resources r ON r.resource_id=u.version_id
            WHERE u.logical_name IN (:old,:new) ORDER BY u.logical_name
        """), {"old": f"generated-{final.render_job_id}-attempt-1",
               "new": f"generated-{final.render_job_id}-attempt-2"})).all()
    assert len(versions) == 2
    assert versions[0][1] == "quarantined"
    assert versions[1] == (final.version_id, "active")


@pytest.mark.asyncio
async def test_duplicate_delivery_and_concurrent_submission_have_one_job_and_artifact(
    factory: Any, local_boundaries: MemoryStorage,
) -> None:
    service, owner, version = await approved_template(factory)
    statuses = await asyncio.gather(*(
        submit(service, owner, version, "duplicate") for _ in range(4)
    ))
    assert len({status.render_job_id for status in statuses}) == 1
    job = statuses[0].render_job_id
    await asyncio.gather(*(service.process_render(job, worker_id=f"worker-{i}") for i in range(4)))
    final = await service.status(owner, job, request_id="status")
    assert final.state == "completed"
    assert final.attempt == 1
    assert await generated_count(factory, job) == 1


@pytest.mark.asyncio
async def test_duplicate_submission_does_not_require_nested_pool_checkout(
    factory: Any, local_boundaries: MemoryStorage,
) -> None:
    service, owner, version = await approved_template(factory)
    assert document_fixtures.DATABASE_DSN
    engine = create_async_engine(
        document_fixtures.DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_size=2, max_overflow=0, pool_timeout=1,
    )
    small = DocumentOSService(UnitOfWork(async_sessionmaker(engine, expire_on_commit=False)))
    try:
        first = await submit(small, owner, version, "small-pool")
        repeated = await asyncio.wait_for(asyncio.gather(*(
            submit(small, owner, version, "small-pool") for _ in range(6)
        )), 3)
        assert {row.render_job_id for row in repeated} == {first.render_job_id}
        await service.process_render(first.render_job_id)
        assert await generated_count(factory, first.render_job_id) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,code", [
    ("fact_acl", "fact_policy_denied"), ("fact_superseded", "fact_stale"),
])
async def test_locked_fact_rechecked_before_recovered_publication(
    factory: Any, local_boundaries: MemoryStorage, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, mutation: str, code: str,
) -> None:
    from rtr_copilot.config import get_settings

    owner = await document_fixtures.principal(factory, "fact-owner", {Role.CURATOR, Role.STAFF})
    actor = uuid.UUID(owner.user_id)
    key = f"RECOVERY.{uuid.uuid4().hex.upper()}"
    package = build_package(tmp_path, curator_id=actor, owner_id=actor,
                            source_key=f"recovery.{uuid.uuid4().hex}", record_key=key, text="15 km")
    settings = get_settings().model_copy(update={
        "sot_staging_root": tmp_path, "sot_signing_secret": SecretStr(SECRET),
    })
    sot = SOTPublishService(settings, factory=factory, clock=lambda: NOW)
    staged = await sot.stage(package.name, actor_id=actor, request_id="stage")
    assert (await sot.validate(staged.package_id, actor_id=actor, request_id="validate")).valid
    await sot.publish(staged.package_id, actor_id=actor, request_id="publish")
    service, owner, version = await approved_template(factory, key, owner)
    status = await service.create_render(owner, version, RenderRequest(
        idempotency_key=f"fact-{uuid.uuid4()}", parameters={},
    ), request_id=f"fact-{uuid.uuid4()}")
    entered, release = pause_first_staged(monkeypatch, factory, local_boundaries)
    worker_task = asyncio.create_task(service.process_render(status.render_job_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with factory() as session, session.begin():
            record = (await session.execute(text("""
                SELECT record_id,current_version_id FROM records WHERE record_key=:key
            """), {"key": key})).mappings().one()
            if mutation == "fact_acl":
                await session.execute(text("""
                    INSERT INTO acl_entries(
                      resource_id,principal_type,principal_id,action,effect,reason
                    ) VALUES (:id,'user',:actor,'view','deny','synthetic-fact-revocation')
                """), {"id": record["record_id"], "actor": actor})
            else:
                await session.execute(text("""
                    UPDATE record_versions SET lifecycle='superseded' WHERE version_id=:id
                """), {"id": record["current_version_id"]})
    finally:
        release.set()
        await worker_task
    final = await service.status(owner, status.render_job_id, request_id="status")
    assert final.state == "failed" and final.error_code == code
    assert await generated_count(factory, status.render_job_id) == 0


@pytest.mark.asyncio
async def test_cancel_fences_staged_worker_and_explicit_retry_keeps_identity(
    factory: Any, local_boundaries: MemoryStorage, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, owner, version = await approved_template(factory)
    status = await submit(service, owner, version, "cancelled")
    entered, release = pause_first_staged(monkeypatch, factory, local_boundaries)
    old_worker = asyncio.create_task(service.process_render(status.render_job_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        cancelled = await service.render_action(owner, status.render_job_id, "cancel",
                                                request_id="cancel")
        assert cancelled.state == "cancelled" and cancelled.retryable
        await service.process_render(status.render_job_id)
        assert await generated_count(factory, status.render_job_id) == 0
    finally:
        release.set()
        await old_worker
    stopped = await service.status(owner, status.render_job_id, request_id="status")
    assert stopped.state == "cancelled"
    await service.render_action(owner, status.render_job_id, "retry", request_id="retry")
    await service.process_render(status.render_job_id)
    final = await service.status(owner, status.render_job_id, request_id="status")
    assert final.state == "completed" and final.render_job_id == status.render_job_id
    assert final.attempt == 2 and not final.retryable
    with pytest.raises(ValueError, match="stale_transition"):
        await service.render_action(owner, status.render_job_id, "retry", request_id="retry")
    assert await generated_count(factory, status.render_job_id) == 1


@pytest.mark.asyncio
async def test_retries_are_bounded_and_status_reports_exhaustion(factory: Any,
                                                               local_boundaries: Any) -> None:
    service, owner, version = await approved_template(factory)
    service.settings = service.settings.model_copy(update={"document_render_max_attempts": 2})
    status = await submit(service, owner, version, "bounded")
    async with factory() as session, session.begin():
        await session.execute(text("""
            UPDATE template_versions SET status='retired' WHERE version_id=:id
        """), {"id": version})
    await service.process_render(status.render_job_id)
    first = await service.status(owner, status.render_job_id, request_id="status")
    assert first.state == "failed" and first.retryable and first.attempt == 1
    await service.render_action(owner, status.render_job_id, "retry", request_id="retry")
    await service.process_render(status.render_job_id)
    last = await service.status(owner, status.render_job_id, request_id="status")
    assert last.state == "failed" and not last.retryable and last.attempt == last.max_attempts == 2
    with pytest.raises(ValueError, match="render_retry_exhausted"):
        await service.render_action(owner, status.render_job_id, "retry", request_id="retry")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,code", [
    ("disabled", "fact_policy_denied"), ("template", "template_not_approved"),
    ("acl", "fact_policy_denied"),
])
async def test_publication_rechecks_current_authority_and_template(
    factory: Any, local_boundaries: MemoryStorage, monkeypatch: pytest.MonkeyPatch,
    mutation: str, code: str,
) -> None:
    service, owner, version = await approved_template(factory)
    status = await submit(service, owner, version, "drift")
    entered, release = pause_first_staged(monkeypatch, factory, local_boundaries)
    worker = asyncio.create_task(service.process_render(status.render_job_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with factory() as session, session.begin():
            if mutation == "disabled":
                await session.execute(text("""
                    UPDATE subjects SET status='disabled' WHERE user_id=:id
                """), {"id": uuid.UUID(owner.user_id)})
            elif mutation == "template":
                await session.execute(text("""
                    UPDATE template_versions SET status='retired' WHERE version_id=:id
                """), {"id": version})
            else:
                await session.execute(text("""
                    INSERT INTO acl_entries(
                      resource_id,principal_type,principal_id,action,effect,reason
                    )
                    VALUES (:id,'user',:actor,'render','deny','synthetic-revocation')
                """), {"id": version, "actor": uuid.UUID(owner.user_id)})
    finally:
        release.set()
        await worker
    final = await service.status(owner, status.render_job_id, request_id="status")
    assert final.state == "failed" and final.error_code == code
    assert await generated_count(factory, status.render_job_id) == 0
    assert local_boundaries.deleted


@pytest.mark.asyncio
async def test_blackholed_notification_is_bounded_and_work_remains_durable(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def blocked(*args: Any) -> int:
        await asyncio.Event().wait()
        return 0

    monkeypatch.setattr(LostRedis, "lpush", blocked)
    service, owner, version = await approved_template(factory)
    service.settings = service.settings.model_copy(update={
        "document_render_notification_timeout_seconds": 0.05,
    })
    started = time.monotonic()
    status = await asyncio.wait_for(submit(service, owner, version, "blackhole"), 1.0)
    assert time.monotonic() - started < 1.0
    assert status.state == "pending"
    for _ in range(10):
        assert await service.process_next(worker_id="durable-poller")
        final = await service.status(owner, status.render_job_id, request_id="status")
        if final.state != "pending":
            break
    assert final.state == "completed"


@pytest.mark.asyncio
async def test_absolute_render_budget_expires_without_unbounded_lease_renewal(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, owner, version = await approved_template(factory)
    status = await submit(service, owner, version, "budget")
    service.settings = service.settings.model_copy(update={"document_render_lease_seconds": 0.05})

    async def hung(*args: Any) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_process_render", hung)
    await asyncio.wait_for(service.process_render(status.render_job_id), 1)
    final = await service.status(owner, status.render_job_id, request_id="status")
    assert final.state == "failed" and final.error_code == "render_lease_expired"
    assert final.retryable and final.attempt == 1


@pytest.mark.asyncio
async def test_request_cancellation_during_hint_keeps_committed_work(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    async def blocked(*args: Any) -> int:
        entered.set()
        await asyncio.Event().wait()
        return 0

    monkeypatch.setattr(LostRedis, "lpush", blocked)
    service, owner, version = await approved_template(factory)
    request_task = asyncio.create_task(submit(service, owner, version, "cancel-hint"))
    await asyncio.wait_for(entered.wait(), 1)
    request_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request_task
    async with factory() as session:
        job = await session.scalar(text("""
            SELECT render_job_id FROM render_jobs WHERE template_version_id=:version
        """), {"version": version})
    assert job
    assert (await service.status(owner, job, request_id="status")).state == "pending"
    await service.process_render(job)
    assert (await service.status(owner, job, request_id="status")).state == "completed"
