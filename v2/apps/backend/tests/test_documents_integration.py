import asyncio
import base64
import io
import os
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from docx import Document
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import (
    BindingDefinition,
    BindRequest,
    DecisionRequest,
    FieldRules,
    RenderRequest,
    TemplateImport,
    TemplateSchema,
)
from rtr_copilot.documents.renderers import render_docx
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.ingestion.api import file_subject
from rtr_copilot.ingestion.malware import DeterministicTestScanner
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.sot.service import SOTPublishService
from rtr_copilot.storage.s3 import S3ObjectStorage
from rtr_copilot.worker.main import execute

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


async def principal(
    factory: async_sessionmaker[Any],
    label: str,
    roles: set[Role],
) -> Subject:
    suffix = uuid.uuid4().hex
    persisted = await PostgresSubjectRepository(factory).upsert_from_claims(
        {
            "iss": "https://documents.integration",
            "sub": f"{label}-{suffix}",
            "email": f"{label}-{suffix}@rtrobotics.com",
            "email_verified": True,
            "name": label,
            "groups": [],
        },
        {},
    )
    return Subject(
        user_id=persisted.user_id,
        issuer="https://documents.integration",
        sub=f"{label}-{suffix}",
        email=f"{label}-{suffix}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        display_name=label,
        roles=roles,
    )


def docx_template() -> bytes:
    document = Document()
    document.add_heading("RtR governed output", level=1)
    document.add_paragraph("Customer: {{customer_name}}")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def locked_docx_template() -> bytes:
    document = Document()
    document.add_paragraph("Range: {{range}}")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


async def approved_locked_template(
    service: DocumentOSService,
    owner: Subject,
    *,
    document_class: Literal["internal", "official", "legal"],
    record_key: str,
) -> uuid.UUID:
    detail = await service.import_template(
        owner,
        TemplateImport(
            stable_key=f"integration.caveat.{document_class}.{uuid.uuid4().hex}",
            display_name=f"Caveat gate {document_class}",
            category="verification",
            classification="internal",
            document_class=document_class,
            format="docx",
            field_schema=TemplateSchema(bindings=[
                BindingDefinition(
                    field_path="range",
                    field_type="string",
                    source="locked_fact",
                    required=True,
                    rules=FieldRules(max_length=500),
                    record_key=record_key,
                    accepted_provenance=["approved_internal"],
                    require_fresh=True,
                    value_literal="15 km",
                ),
            ]),
            source_base64=base64.b64encode(locked_docx_template()).decode(),
        ),
        request_id=f"import-{uuid.uuid4()}",
    )
    await service.lifecycle(
        owner, detail.version_id, "submit", request_id=f"submit-{uuid.uuid4()}",
    )
    await service.lifecycle(
        owner, detail.version_id, "approve", request_id=f"approve-{uuid.uuid4()}",
    )
    return detail.version_id


async def approved_template(
    factory: async_sessionmaker[Any],
) -> tuple[DocumentOSService, Subject, uuid.UUID]:
    owner = await principal(factory, "document-owner", {Role.CURATOR, Role.STAFF})
    service = DocumentOSService(UnitOfWork(factory))
    detail = await service.import_template(
        owner,
        TemplateImport(
            stable_key=f"integration.{uuid.uuid4().hex}",
            display_name="Integration governed document",
            category="verification",
            classification="internal",
            document_class="internal",
            format="docx",
            field_schema=TemplateSchema(bindings=[
                BindingDefinition(
                    field_path="customer_name",
                    field_type="string",
                    source="user",
                    required=True,
                    rules=FieldRules(min_length=1, max_length=100),
                ),
            ]),
            source_base64=base64.b64encode(docx_template()).decode(),
        ),
        request_id=f"import-{uuid.uuid4()}",
    )
    await service.lifecycle(
        owner, detail.version_id, "submit", request_id=f"submit-{uuid.uuid4()}",
    )
    await service.lifecycle(
        owner, detail.version_id, "approve", request_id=f"approve-{uuid.uuid4()}",
    )
    return service, owner, detail.version_id


def patch_ingestion(
    monkeypatch: pytest.MonkeyPatch,
    factory: async_sessionmaker[Any],
    *,
    after_render: Callable[[], Awaitable[None]] | None = None,
) -> None:
    settings = get_settings()

    def build() -> IngestionService:
        service = IngestionService(
            settings=settings,
            storage=S3ObjectStorage(settings),
            uow=UnitOfWork(factory),
            scanner=DeterministicTestScanner("clean"),
        )
        original = service.process_job

        async def process(job_id: uuid.UUID, *, worker_id: str) -> bool:
            result = await original(job_id, worker_id=worker_id)
            if after_render is not None:
                async with factory() as session:
                    job_type = await session.scalar(text("""
                        SELECT job_type FROM ingestion_jobs WHERE job_id=:job_id
                    """), {"job_id": job_id})
                if job_type == "render":
                    await after_render()
            return result

        service.process_job = process  # type: ignore[method-assign]
        return service

    monkeypatch.setattr("rtr_copilot.documents.service.IngestionService", build)


async def run_render(
    service: DocumentOSService,
    owner: Subject,
    version_id: uuid.UUID,
    value: str,
) -> Any:
    status = await service.create_render(
        owner,
        version_id,
        RenderRequest(
            idempotency_key=f"render-{uuid.uuid4()}",
            parameters={"customer_name": value},
        ),
        request_id=f"render-{uuid.uuid4()}",
    )
    await execute(
        cast(Redis, object()),
        {
            "name": "document.render",
            "job_id": str(status.render_job_id),
            "request_id": f"worker-{uuid.uuid4()}",
        },
        worker_id="production-worker-probe",
    )
    return await service.status(
        owner, status.render_job_id, request_id=f"status-{uuid.uuid4()}",
    )


@pytest.mark.asyncio
async def test_caveated_fact_is_visible_internal_and_blocked_official(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await principal(factory, "named-caveat-owner", {Role.CURATOR, Role.STAFF})
    owner_id = uuid.UUID(owner.user_id)
    record_key = f"CAVEAT.{uuid.uuid4().hex.upper()}"
    package_root = build_package(
        tmp_path,
        curator_id=owner_id,
        owner_id=owner_id,
        source_key=f"caveat.{uuid.uuid4().hex}",
        record_key=record_key,
        text="15 km",
        confidence_signal={"tier": "soft", "needs_double_check": True},
    )
    sot_settings = get_settings().model_copy(update={
        "sot_staging_root": tmp_path,
        "sot_signing_secret": SecretStr(SECRET),
    })
    sot = SOTPublishService(sot_settings, factory=factory, clock=lambda: NOW)
    staged = await sot.stage(
        package_root.name, actor_id=owner_id, request_id=f"stage-{uuid.uuid4()}",
    )
    assert (await sot.validate(
        staged.package_id, actor_id=owner_id,
        request_id=f"validate-{uuid.uuid4()}",
    )).valid
    await sot.publish(
        staged.package_id, actor_id=owner_id,
        request_id=f"publish-{uuid.uuid4()}",
    )

    service = DocumentOSService(UnitOfWork(factory))
    internal_version = await approved_locked_template(
        service, owner, document_class="internal", record_key=record_key,
    )
    official_version = await approved_locked_template(
        service, owner, document_class="official", record_key=record_key,
    )

    internal = await service.bind(
        owner, internal_version, BindRequest(parameters={}),
        request_id=f"bind-{uuid.uuid4()}",
    )
    assert internal.valid
    assert internal.blocked == []
    value = str(internal.fields[0].value)
    assert value.startswith("15 km [CAVEAT: needs_double_check")
    assert "owner: named-caveat-owner" in value
    rendered = render_docx(locked_docx_template(), {"range": value})
    rendered_document = Document(io.BytesIO(rendered))
    assert "CAVEAT: needs_double_check" in "\n".join(
        paragraph.text for paragraph in rendered_document.paragraphs
    )

    official = await service.bind(
        owner, official_version, BindRequest(parameters={}),
        request_id=f"bind-{uuid.uuid4()}",
    )
    assert not official.valid
    assert official.fields == []
    assert official.blocked == [{"field": "range", "code": "fact_caveated"}]
    with pytest.raises(ValueError, match="fact_caveated"):
        await service.create_render(
            owner,
            official_version,
            RenderRequest(
                idempotency_key=f"blocked-{uuid.uuid4()}",
                parameters={},
            ),
            request_id=f"render-{uuid.uuid4()}",
        )


@asynccontextmanager
async def files_client(subject: Subject) -> Any:
    async def override(_: Request) -> Subject:
        return subject

    app.dependency_overrides[file_subject] = override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(file_subject, None)


@pytest.mark.asyncio
async def test_worker_render_e2e_and_concurrent_canonical_lifecycle(
    factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ingestion(monkeypatch, factory)
    service, owner, version_id = await approved_template(factory)
    rendered = await run_render(service, owner, version_id, "Factory A")
    assert rendered.state == "completed"
    assert rendered.generated_file_id and rendered.version_id

    async with factory() as session:
        publication = (await session.execute(text("""
            SELECT p.state,p.finalized_at,g.checksum,v.sha256,o.storage_state,
              vr.lifecycle_state version_state,dr.lifecycle_state document_state
            FROM document_publication_outbox p
            JOIN generated_files g USING(render_job_id)
            JOIN document_versions v ON v.version_id=g.version_id
            JOIN object_blobs o ON o.object_id=g.object_id
            JOIN resources vr ON vr.resource_id=g.version_id
            JOIN resources dr ON dr.resource_id=g.document_id
            WHERE p.render_job_id=:job_id
        """), {"job_id": rendered.render_job_id})).mappings().one()
    assert publication["state"] == "finalized"
    assert publication["finalized_at"] is not None
    assert publication["checksum"] == publication["sha256"]
    assert publication["storage_state"] == "available"
    assert publication["version_state"] == publication["document_state"] == "active"

    async with files_client(owner) as client:
        response = await client.get(
            f"/api/v1/files/versions/{rendered.version_id}/viewer-manifest",
        )
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["state"] in {"ready", "partial"}
    assert manifest["renditions"]

    leader_a = await principal(factory, "leader-a", {Role.LEADER})
    leader_b = await principal(factory, "leader-b", {Role.LEADER})
    generated_id = rendered.generated_file_id
    async with factory() as session, session.begin():
        for leader in (leader_a, leader_b):
            await session.execute(text("""
                INSERT INTO acl_entries(
                  resource_id,principal_type,principal_id,action,effect,reason
                ) VALUES (
                  :resource_id,'user',:principal_id,'approve','allow',
                  'integration approval grant'
                )
            """), {
                "resource_id": rendered.version_id,
                "principal_id": uuid.UUID(leader.user_id),
            })
    await service.submit(owner, generated_id, request_id=f"submit-{uuid.uuid4()}")
    approve_results = await asyncio.gather(
        service.decide(
            leader_a, generated_id, "approved", DecisionRequest(reason="approved A"),
            request_id=f"decision-{uuid.uuid4()}",
        ),
        service.decide(
            leader_b, generated_id, "approved", DecisionRequest(reason="approved B"),
            request_id=f"decision-{uuid.uuid4()}",
        ),
        return_exceptions=True,
    )
    assert sum(result is None for result in approve_results) == 1, approve_results

    issue_results = await asyncio.gather(
        service.issue(leader_a, generated_id, request_id=f"issue-{uuid.uuid4()}"),
        service.issue(leader_b, generated_id, request_id=f"issue-{uuid.uuid4()}"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in issue_results) == 1
    revoke_results = await asyncio.gather(
        service.revoke(
            leader_a, generated_id, DecisionRequest(reason="revoke A"),
            request_id=f"revoke-{uuid.uuid4()}",
        ),
        service.revoke(
            leader_b, generated_id, DecisionRequest(reason="revoke B"),
            request_id=f"revoke-{uuid.uuid4()}",
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in revoke_results) == 1

    rejected = await run_render(service, owner, version_id, "Factory B")
    assert rejected.generated_file_id
    async with factory() as session, session.begin():
        for leader in (leader_a, leader_b):
            await session.execute(text("""
                INSERT INTO acl_entries(
                  resource_id,principal_type,principal_id,action,effect,reason
                ) VALUES (
                  :resource_id,'user',:principal_id,'approve','allow',
                  'integration rejection grant'
                )
            """), {
                "resource_id": rejected.version_id,
                "principal_id": uuid.UUID(leader.user_id),
            })
    await service.submit(
        owner, rejected.generated_file_id, request_id=f"submit-{uuid.uuid4()}",
    )
    reject_results = await asyncio.gather(
        service.decide(
            leader_a, rejected.generated_file_id, "rejected",
            DecisionRequest(reason="reject A"),
            request_id=f"decision-{uuid.uuid4()}",
        ),
        service.decide(
            leader_b, rejected.generated_file_id, "rejected",
            DecisionRequest(reason="reject B"),
            request_id=f"decision-{uuid.uuid4()}",
        ),
        return_exceptions=True,
    )
    assert sum(result is None for result in reject_results) == 1

    async with factory() as session:
        canonical = (await session.execute(text("""
            SELECT
              (SELECT lifecycle FROM generated_files
               WHERE generated_file_id=:issued) issued_lifecycle,
              (SELECT count(*) FROM approvals
               WHERE generated_file_id=:issued) approval_count,
              (SELECT count(*) FROM document_issuances
               WHERE generated_file_id=:issued AND revoked_at IS NOT NULL) issuance_count,
              (SELECT lifecycle FROM generated_files
               WHERE generated_file_id=:rejected) rejected_lifecycle,
              (SELECT count(*) FROM approvals
               WHERE generated_file_id=:rejected AND decision='rejected') rejection_count,
              (SELECT count(*) FROM audit_events
               WHERE details->>'generated_file_id'=:issued_text
                 AND action='document.issue') issue_audits,
              (SELECT count(*) FROM audit_events
               WHERE details->>'generated_file_id'=:issued_text
                 AND action='document.revoke') revoke_audits
        """), {
            "issued": generated_id,
            "issued_text": str(generated_id),
            "rejected": rejected.generated_file_id,
        })).mappings().one()
    assert dict(canonical) == {
        "issued_lifecycle": "revoked",
        "approval_count": 1,
        "issuance_count": 1,
        "rejected_lifecycle": "rejected",
        "rejection_count": 1,
        "issue_audits": 1,
        "revoke_audits": 1,
    }
    async with factory() as session:
        with pytest.raises(DBAPIError):
            async with session.begin():
                await session.execute(text("""
                    UPDATE approvals SET reason='tamper'
                    WHERE generated_file_id=:generated_id
                """), {"generated_id": generated_id})


@pytest.mark.asyncio
async def test_policy_revocation_before_finalization_closes_visibility_and_bytes(
    factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, owner, version_id = await approved_template(factory)

    async def revoke_render_policy() -> None:
        async with factory() as session, session.begin():
            await session.execute(text("""
                INSERT INTO acl_entries(
                  resource_id,principal_type,principal_id,action,effect,reason
                ) VALUES (
                  :resource_id,'user',:principal_id,'render','deny',
                  'integration revocation before finalization'
                )
            """), {
                "resource_id": version_id,
                "principal_id": uuid.UUID(owner.user_id),
            })

    patch_ingestion(
        monkeypatch,
        factory,
        after_render=revoke_render_policy,
    )
    rendered = await run_render(service, owner, version_id, "Revoked Factory")
    assert rendered.state == "failed"
    assert rendered.error_code == "fact_policy_denied"
    async with factory() as session:
        closure = (await session.execute(text("""
            SELECT p.state,p.finalized_at,
              (SELECT count(*) FROM generated_files
               WHERE render_job_id=:job_id) generated_count,
              (SELECT count(*) FROM upload_sessions u
               JOIN resources r ON r.resource_id IN (
                 u.document_id,u.version_id,u.object_id
               )
               WHERE u.request_id=(SELECT request_id FROM render_jobs
                 WHERE render_job_id=:job_id)
                 AND r.lifecycle_state='active') active_count
            FROM document_publication_outbox p
            WHERE p.render_job_id=:job_id
        """), {"job_id": rendered.render_job_id})).mappings().one()
        object_keys = list((await session.execute(text("""
            SELECT o.object_key FROM upload_sessions u
            JOIN object_blobs o ON o.object_id=u.object_id
            WHERE u.request_id=(SELECT request_id FROM render_jobs
              WHERE render_job_id=:job_id)
        """), {"job_id": rendered.render_job_id})).scalars())
    assert closure["state"] == "failed"
    assert closure["finalized_at"] is None
    assert closure["generated_count"] == closure["active_count"] == 0
    inventory = {
        item["key"] for item in await S3ObjectStorage(get_settings()).inventory()
    }
    assert not (set(object_keys) & inventory)
