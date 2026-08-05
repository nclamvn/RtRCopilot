import asyncio
import io
import os
import shutil
import subprocess
import sys
import uuid
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.ingestion.api import file_subject
from rtr_copilot.ingestion.errors import IngestionFailure
from rtr_copilot.ingestion.extractors import extract_required
from rtr_copilot.ingestion.malware import DeterministicTestScanner
from rtr_copilot.ingestion.private_engines import (
    LocalTesseractOCR,
    LocalVoskTranscript,
)
from rtr_copilot.ingestion.sandbox import ProcessSandbox
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.ingestion.validators import validate_content
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.repositories.resources import (
    ACLRecord,
    ResourceRecord,
    ResourceRepository,
)
from rtr_copilot.storage.s3 import S3ObjectStorage

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(not DATABASE_DSN, reason="integration database not configured")


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def _bytes_stream(payload: bytes) -> AsyncIterator[bytes]:
    midpoint = max(1, len(payload) // 2)
    yield payload[:midpoint]
    yield payload[midpoint:]


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 16), (22, 91, 143)).save(output, "PNG")
    return output.getvalue()


def _document_fixtures(tmp_path: Path) -> dict[str, tuple[str, bytes]]:
    fixtures: dict[str, tuple[str, bytes]] = {}
    for filename, format_name, mime in (
        ("fixture.png", "PNG", "image/png"),
        ("fixture.jpg", "JPEG", "image/jpeg"),
        ("fixture.webp", "WEBP", "image/webp"),
        ("fixture.tiff", "TIFF", "image/tiff"),
    ):
        path = tmp_path / filename
        Image.new("RGB", (64, 48), (22, 91, 143)).save(path, format_name)
        fixtures[filename] = (mime, path.read_bytes())
    pdf_path = tmp_path / "fixture.pdf"
    pdf = canvas.Canvas(str(pdf_path), invariant=1)
    pdf.drawString(50, 750, "persisted PDF")
    pdf.save()
    fixtures[pdf_path.name] = ("application/pdf", pdf_path.read_bytes())
    docx_path = tmp_path / "fixture.docx"
    document = Document()
    document.add_paragraph("persisted DOCX")
    document.save(docx_path)
    fixtures[docx_path.name] = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        docx_path.read_bytes(),
    )
    xlsx_path = tmp_path / "fixture.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "persisted XLSX"
    workbook.save(xlsx_path)
    fixtures[xlsx_path.name] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        xlsx_path.read_bytes(),
    )
    pptx_path = tmp_path / "fixture.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.add_textbox(1, 1, 100, 100).text = "persisted PPTX"
    presentation.save(pptx_path)
    fixtures[pptx_path.name] = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        pptx_path.read_bytes(),
    )
    return fixtures


@pytest.mark.skipif(
    shutil.which("soffice") is None,
    reason="LibreOffice runtime not installed",
)
def test_office_previews_preserve_vietnamese_and_presentation_geometry(
    tmp_path: Path,
) -> None:
    app_settings = get_settings()
    sandbox = ProcessSandbox(
        timeout_seconds=app_settings.ingestion_tool_timeout_seconds,
        temp_bytes=app_settings.ingestion_temp_bytes,
    )
    pptx_path = tmp_path / "fidelity.pptx"
    presentation = Presentation()
    for text_value in ("Đà Nẵng · lãnh đạo", "Khung năng lực UAV"):
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        shape = slide.shapes.add_textbox(914400, 914400, 7315200, 1828800)
        run = shape.text_frame.paragraphs[0].add_run()
        run.text = text_value
        run.font.name = "Be Vietnam Pro"
    presentation.save(pptx_path)

    first = extract_required(
        pptx_path,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        structural={},
        settings=app_settings,
        sandbox=sandbox,
    )
    second = extract_required(
        pptx_path,
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        structural={},
        settings=app_settings,
        sandbox=sandbox,
    )
    preview = next(item for item in first if item.kind == "preview_pdf")
    reader = PdfReader(io.BytesIO(preview.payload), strict=True)
    rendered_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) == 2
    assert "Đà Nẵng" in rendered_text
    assert "lãnh đạo" in rendered_text
    assert "năng lực" in rendered_text
    assert preview.quality["render_engine"] == "libreoffice"
    assert preview.quality["unicode_coverage"] == 1.0
    source_ratio = float(presentation.slide_width) / float(presentation.slide_height)
    rendered_ratio = float(reader.pages[0].mediabox.width) / float(
        reader.pages[0].mediabox.height,
    )
    assert abs(source_ratio - rendered_ratio) < 0.01
    assert preview.sha256 == next(
        item for item in second if item.kind == "preview_pdf"
    ).sha256


def _media_fixtures(tmp_path: Path) -> dict[str, tuple[str, bytes]]:
    speech = tmp_path / "fixture.wav"
    subprocess.run(
        ["espeak-ng", "-w", str(speech), "one two three four five"],
        check=True,
    )
    commands = {
        "fixture.mp3": ["-i", str(speech), "-c:a", "libmp3lame"],
        "fixture.m4a": ["-i", str(speech), "-c:a", "aac"],
        "fixture.ogg": ["-i", str(speech), "-c:a", "libopus"],
        "fixture.mp4": [
            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
            "-i", str(speech), "-shortest", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-c:a", "aac",
        ],
        "fixture.webm": [
            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
            "-i", str(speech), "-shortest", "-c:v", "libvpx",
            "-c:a", "libopus",
        ],
    }
    for filename, arguments in commands.items():
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", *arguments, "-y", filename],
            cwd=tmp_path,
            check=True,
        )
    return {
        "fixture.wav": ("audio/wav", speech.read_bytes()),
        "fixture.mp3": ("audio/mpeg", (tmp_path / "fixture.mp3").read_bytes()),
        "fixture.m4a": ("audio/mp4", (tmp_path / "fixture.m4a").read_bytes()),
        "fixture.ogg": ("audio/ogg", (tmp_path / "fixture.ogg").read_bytes()),
        "fixture.mp4": ("video/mp4", (tmp_path / "fixture.mp4").read_bytes()),
        "fixture.webm": ("video/webm", (tmp_path / "fixture.webm").read_bytes()),
    }


async def _principal_and_parent(
    factory: async_sessionmaker[Any],
) -> tuple[uuid.UUID, ResourceRecord]:
    suffix = uuid.uuid4().hex
    subject = await PostgresSubjectRepository(factory).upsert_from_claims(
        {
            "iss": "https://integration.identity",
            "sub": f"ingestion-{suffix}",
            "email": f"ingestion-{suffix}@rtrobotics.com",
            "email_verified": True,
            "name": "Ingestion Integration",
            "groups": [],
        },
        {},
    )
    principal = uuid.UUID(subject.user_id)
    parent = ResourceRecord(
        resource_type="source",
        owner_subject_id=principal,
        classification="internal",
        source_zone="private_context",
        lifecycle_state="active",
    )
    async with factory() as session, session.begin():
        await ResourceRepository().create(session, parent)
        await session.execute(text("""
            INSERT INTO sources(source_id,kind,name,metadata)
            VALUES (:source_id,'internal','Integration source','{}')
        """), {"source_id": parent.resource_id})
    return principal, parent


async def _new_principal(
    factory: async_sessionmaker[Any],
    label: str,
) -> uuid.UUID:
    suffix = uuid.uuid4().hex
    subject = await PostgresSubjectRepository(factory).upsert_from_claims(
        {
            "iss": "https://integration.identity",
            "sub": f"{label}-{suffix}",
            "email": f"{label}-{suffix}@rtrobotics.com",
            "email_verified": True,
            "name": label,
            "groups": [],
        },
        {},
    )
    return uuid.UUID(subject.user_id)


def _subject(principal: uuid.UUID, *, role: Role = Role.STAFF) -> Subject:
    return Subject(
        user_id=str(principal),
        issuer="https://integration.identity",
        sub=str(principal),
        email=f"{principal}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


@asynccontextmanager
async def _http_client(
    subjects: dict[str, Subject],
) -> AsyncIterator[AsyncClient]:
    async def override(request: Request) -> Subject | None:
        return subjects.get(request.headers.get("X-Test-Subject", ""))

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
async def test_clean_upload_is_durable_idempotent_and_provenance_complete(
    factory: async_sessionmaker[Any],
) -> None:
    settings = get_settings()
    storage = S3ObjectStorage(settings)
    service = IngestionService(
        settings=settings,
        storage=storage,
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("clean"),
    )
    principal, parent = await _principal_and_parent(factory)
    payload = _png()
    upload_id, validation_job_id = await service.receive(
        _bytes_stream(payload),
        content_length=len(payload),
        parent=parent,
        logical_name="safe image",
        original_filename="safe.png",
        declared_mime="image/png",
        declared_sha256=None,
        requested_by=principal,
        request_id=f"req-{uuid.uuid4()}",
    )

    results = await asyncio.gather(
        service.process_job(validation_job_id, worker_id="worker-a"),
        service.process_job(validation_job_id, worker_id="worker-b"),
    )
    assert sorted(results) == [False, True]
    async with factory() as session:
        row = (await session.execute(text("""
            SELECT state,document_id,version_id FROM upload_sessions
            WHERE upload_id=:upload_id
        """), {"upload_id": upload_id})).mappings().one()
        render_job_id = await session.scalar(text("""
            SELECT job_id FROM ingestion_jobs
            WHERE version_id=:version_id AND job_type='render'
        """), {"version_id": row["version_id"]})
    assert row["state"] == "accepted"
    assert render_job_id is not None

    # Simulate a worker dying after it had acquired the job. The next worker
    # must reclaim the expired lease and publish exactly one logical bundle.
    async with factory() as session, session.begin():
        await session.execute(text("""
            UPDATE ingestion_jobs SET status='running', lease_owner='dead-worker',
              lease_expires_at=now() - interval '1 second'
            WHERE job_id=:job_id
        """), {"job_id": render_job_id})
    assert await service.process_job(render_job_id, worker_id="restart-worker")
    assert not await service.process_job(render_job_id, worker_id="duplicate-delivery")

    async with factory() as session:
        jobs = (await session.execute(text("""
            SELECT job_type,status,attempt FROM ingestion_jobs
            WHERE upload_id=:upload_id OR version_id=:version_id
            ORDER BY job_type
        """), {"upload_id": upload_id, "version_id": row["version_id"]})).mappings().all()
        renditions = (await session.execute(text("""
            SELECT r.kind,r.status,r.source_sha256,r.pipeline_fingerprint,
              r.quality_state,r.provenance,o.object_key,o.sha256,o.byte_size
            FROM renditions r JOIN object_blobs o ON o.object_id=r.object_id
            WHERE r.version_id=:version_id ORDER BY r.kind
        """), {"version_id": row["version_id"]})).mappings().all()
        outbox_count = await session.scalar(text("""
            SELECT count(*) FROM ingestion_outbox
            WHERE job_id IN (
              SELECT job_id FROM ingestion_jobs
              WHERE upload_id=:upload_id OR version_id=:version_id
            )
        """), {"upload_id": upload_id, "version_id": row["version_id"]})
        audit_actions = set((await session.execute(text("""
            SELECT action FROM audit_events
            WHERE request_id LIKE 'req-%'
              AND resource_id IN (:document_id,:version_id)
        """), {
            "document_id": row["document_id"],
            "version_id": row["version_id"],
        })).scalars())

    assert {(item["job_type"], item["status"]) for item in jobs} == {
        ("render", "succeeded"),
        ("validate", "succeeded"),
    }
    assert next(item["attempt"] for item in jobs if item["job_type"] == "render") == 1
    assert outbox_count == 2
    assert {item["kind"] for item in renditions} == {
        "ocr_json",
        "safe_image_preview",
        "thumbnail",
    }
    assert all(item["status"] == "ready" for item in renditions)
    assert all(item["source_sha256"] and item["pipeline_fingerprint"] for item in renditions)
    assert all(
        item["quality_state"] in {"complete", "low_confidence"}
        for item in renditions
    )
    assert all(item["provenance"]["source_sha256"] == item["source_sha256"] for item in renditions)
    assert {"upload.accepted", "malware.scan"} <= audit_actions
    for item in renditions:
        await storage.verify(
            key=item["object_key"],
            expected_sha256=item["sha256"],
            expected_size=item["byte_size"],
            recompute=True,
        )


@pytest.mark.asyncio
async def test_deferred_publication_stays_quarantined_until_atomic_finalization(
    factory: async_sessionmaker[Any],
) -> None:
    settings = get_settings()
    service = IngestionService(
        settings=settings,
        storage=S3ObjectStorage(settings),
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("clean"),
    )
    principal, parent = await _principal_and_parent(factory)
    payload = _png()
    upload_id, validation_job = await service.receive(
        _bytes_stream(payload), content_length=len(payload), parent=parent,
        logical_name="deferred output", original_filename="deferred.png",
        declared_mime="image/png", declared_sha256=None,
        requested_by=principal, request_id=f"deferred-{uuid.uuid4()}",
        defer_publication=True,
    )
    assert await service.process_job(validation_job, worker_id="deferred-validation")
    async with factory() as session:
        row = (await session.execute(text("""
            SELECT u.document_id,u.version_id,u.object_id,u.publication_deferred,
              array_agg(DISTINCT r.lifecycle_state) states
            FROM upload_sessions u
            JOIN resources r ON r.resource_id IN (
              u.document_id,u.version_id,u.object_id
            )
            WHERE u.upload_id=:upload_id
            GROUP BY u.document_id,u.version_id,u.object_id,u.publication_deferred
        """), {"upload_id": upload_id})).mappings().one()
        visible = await session.scalar(text("""
            SELECT count(*) FROM documents d
            JOIN resources r ON r.resource_id=d.document_id
            WHERE d.document_id=:document_id AND r.lifecycle_state='active'
        """), {"document_id": row["document_id"]})
    assert row["publication_deferred"] is True
    assert set(row["states"]) == {"quarantined"}
    assert visible == 0


@pytest.mark.asyncio
async def test_infected_upload_remains_quarantined_without_version(
    factory: async_sessionmaker[Any],
) -> None:
    settings = get_settings()
    service = IngestionService(
        settings=settings,
        storage=S3ObjectStorage(settings),
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("infected"),
    )
    principal, parent = await _principal_and_parent(factory)
    payload = _png()
    upload_id, job_id = await service.receive(
        _bytes_stream(payload),
        content_length=len(payload),
        parent=parent,
        logical_name="malware fixture",
        original_filename="fixture.png",
        declared_mime="image/png",
        declared_sha256=None,
        requested_by=principal,
        request_id=f"infected-{uuid.uuid4()}",
    )
    assert not await service.process_job(job_id, worker_id="scanner-worker")
    async with factory() as session:
        row = (await session.execute(text("""
            SELECT u.state,u.version_id,u.error_code,j.status,o.storage_state,
              r.lifecycle_state
            FROM upload_sessions u
            JOIN ingestion_jobs j ON j.job_id=u.validation_job_id
            JOIN object_blobs o ON o.object_id=u.object_id
            JOIN resources r ON r.resource_id=u.object_id
            WHERE u.upload_id=:upload_id
        """), {"upload_id": upload_id})).mappings().one()
        versions = await session.scalar(text("""
            SELECT count(*) FROM document_versions
            WHERE document_id=(SELECT document_id FROM upload_sessions
              WHERE upload_id=:upload_id)
        """), {"upload_id": upload_id})
    assert row["state"] == "rejected"
    assert row["version_id"] is None
    assert row["error_code"] == "malware_detected"
    assert row["status"] == "quarantined"
    assert row["storage_state"] == "staged"
    assert row["lifecycle_state"] == "quarantined"
    assert versions == 0


@pytest.mark.asyncio
async def test_scanner_unavailable_http_retry_twice_is_idempotent_and_recovers(
    factory: async_sessionmaker[Any],
) -> None:
    app_settings = get_settings()
    service = IngestionService(
        settings=app_settings,
        storage=S3ObjectStorage(app_settings),
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("unavailable"),
    )
    principal, parent = await _principal_and_parent(factory)
    payload = _png()
    upload_id, job_id = await service.receive(
        _bytes_stream(payload),
        content_length=len(payload),
        parent=parent,
        logical_name="retry image",
        original_filename="retry.png",
        declared_mime="image/png",
        declared_sha256=None,
        requested_by=principal,
        request_id=f"retry-{uuid.uuid4()}",
    )
    assert not await service.process_job(job_id, worker_id="scanner-unavailable")
    async with _http_client({"owner": _subject(principal)}) as client:
        first = await client.post(
            f"/api/v1/files/uploads/{upload_id}/retry",
            headers={"X-Test-Subject": "owner"},
        )
        second = await client.post(
            f"/api/v1/files/uploads/{upload_id}/retry",
            headers={"X-Test-Subject": "owner"},
        )
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"] == str(job_id)
    assert first.json()["state"] == second.json()["state"] == "pending"
    async with factory() as session:
        retry_audits = await session.scalar(text("""
            SELECT count(*) FROM audit_events
            WHERE action='ingestion.job.retry'
              AND details->>'job_id'=:job_id
        """), {"job_id": str(job_id)})
        job = (await session.execute(text("""
            SELECT status,resource_id FROM ingestion_jobs WHERE job_id=:job_id
        """), {"job_id": job_id})).mappings().one()
        resource_exists = await session.scalar(text("""
            SELECT EXISTS(SELECT 1 FROM resources WHERE resource_id=:resource_id)
        """), {"resource_id": job["resource_id"]})
    assert retry_audits == 1
    assert job["status"] == "pending"
    assert resource_exists
    service.scanner = DeterministicTestScanner("clean")
    assert await service.process_job(job_id, worker_id="scanner-restored")


@pytest.mark.asyncio
async def test_private_context_http_acl_is_owner_or_explicit_grant_only(
    factory: async_sessionmaker[Any],
) -> None:
    app_settings = get_settings()
    service = IngestionService(
        settings=app_settings,
        storage=S3ObjectStorage(app_settings),
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("clean"),
    )
    owner, parent = await _principal_and_parent(factory)
    admin = await _new_principal(factory, "admin")
    viewer = await _new_principal(factory, "viewer")
    unrelated = await _new_principal(factory, "unrelated")
    expired = await _new_principal(factory, "expired")
    denied = await _new_principal(factory, "denied")
    effective_cases = {
        principal_type: await _new_principal(factory, f"effective-{principal_type}")
        for principal_type in ("group", "role", "department", "project")
    }
    payload = _png()
    upload_id, job_id = await service.receive(
        _bytes_stream(payload),
        content_length=len(payload),
        parent=parent,
        logical_name="acl image",
        original_filename="acl.png",
        declared_mime="image/png",
        declared_sha256=None,
        requested_by=owner,
        request_id=f"acl-{uuid.uuid4()}",
    )
    assert await service.process_job(job_id, worker_id="acl-validation")
    async with factory() as session:
        version_id = await session.scalar(text("""
            SELECT version_id FROM upload_sessions WHERE upload_id=:upload_id
        """), {"upload_id": upload_id})
        source_id = await session.scalar(text("""
            SELECT d.source_id FROM documents d
            JOIN upload_sessions u ON u.document_id=d.document_id
            WHERE u.upload_id=:upload_id
        """), {"upload_id": upload_id})
        document_id = await session.scalar(text("""
            SELECT document_id FROM upload_sessions WHERE upload_id=:upload_id
        """), {"upload_id": upload_id})
        original_object_id = await session.scalar(text("""
            SELECT object_id FROM document_versions WHERE version_id=:version_id
        """), {"version_id": version_id})
        render_job_id = await session.scalar(text("""
            SELECT job_id FROM ingestion_jobs
            WHERE version_id=:version_id AND job_type='render'
        """), {"version_id": version_id})
    assert source_id == parent.resource_id
    assert document_id and version_id and original_object_id and render_job_id
    assert await service.process_job(render_job_id, worker_id="acl-render")
    async with factory() as session:
        rendition_ids = list((await session.execute(text("""
            SELECT rendition_id FROM renditions
            WHERE version_id=:version_id ORDER BY kind,rendition_id
        """), {"version_id": version_id})).scalars())
        effective = await ResourceRepository().effective_policy_attributes(
            session,
            version_id,
            action="view",
            principal_ids={unrelated},
        )
    assert rendition_ids
    assert effective is not None
    assert effective[0].source_zone == "private_context"
    assert effective[0].owner_id == str(owner)
    assert effective[0].explicit_deny

    subjects = {
        "owner": _subject(owner),
        "admin": _subject(admin, role=Role.ADMIN),
        "viewer": _subject(viewer),
        "unrelated": _subject(unrelated),
        "expired": _subject(expired),
        "denied": _subject(denied),
        **{
            f"effective-{principal_type}": _subject(principal)
            for principal_type, principal in effective_cases.items()
        },
    }
    manifest_url = f"/api/v1/files/versions/{version_id}/viewer-manifest"
    content_url = f"/api/v1/files/renditions/{rendition_ids[0]}/content"
    original_url = f"/api/v1/files/versions/{version_id}/original"
    status_url = f"/api/v1/files/uploads/{upload_id}"
    async with _http_client(subjects) as client:
        owner_catalog = await client.get(
            "/api/v1/files",
            headers={"X-Test-Subject": "owner"},
        )
        unrelated_catalog = await client.get(
            "/api/v1/files",
            headers={"X-Test-Subject": "unrelated"},
        )
        owner_targets = await client.get(
            "/api/v1/files/upload-targets",
            headers={"X-Test-Subject": "owner"},
        )
        owner_status = await client.get(
            status_url,
            headers={"X-Test-Subject": "owner"},
        )
        owner_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "owner"},
        )
        owner_content = await client.get(
            content_url,
            headers={"X-Test-Subject": "owner"},
        )
        owner_range = await client.get(
            content_url,
            headers={"X-Test-Subject": "owner", "Range": "bytes=0-9"},
        )
        owner_original = await client.get(
            original_url,
            headers={"X-Test-Subject": "owner"},
        )
        owner_original_suffix = await client.get(
            original_url,
            headers={"X-Test-Subject": "owner", "Range": "bytes=-10"},
        )
        owner_invalid_range = await client.get(
            original_url,
            headers={"X-Test-Subject": "owner", "Range": "bytes=999999-"},
        )
        unrelated_status = await client.get(
            status_url,
            headers={"X-Test-Subject": "unrelated"},
        )
        unrelated_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "unrelated"},
        )
        unrelated_content = await client.get(
            content_url,
            headers={"X-Test-Subject": "unrelated"},
        )
        admin_status = await client.get(
            status_url,
            headers={"X-Test-Subject": "admin"},
        )
        admin_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "admin"},
        )
        admin_content = await client.get(
            content_url,
            headers={"X-Test-Subject": "admin"},
        )
        unknown_status = await client.get(
            f"/api/v1/files/uploads/{uuid.uuid4()}",
            headers={"X-Test-Subject": "unrelated"},
        )
        unknown_manifest = await client.get(
            f"/api/v1/files/versions/{uuid.uuid4()}/viewer-manifest",
            headers={"X-Test-Subject": "unrelated"},
        )
        unknown_content = await client.get(
            f"/api/v1/files/renditions/{uuid.uuid4()}/content",
            headers={"X-Test-Subject": "unrelated"},
        )
    assert owner_status.status_code == 200
    assert owner_manifest.status_code == 200
    assert owner_content.status_code == 200
    assert owner_catalog.status_code == 200
    assert str(version_id) in {
        item["version_id"] for item in owner_catalog.json()["items"]
    }
    assert unrelated_catalog.status_code == 200
    assert str(version_id) not in {
        item["version_id"] for item in unrelated_catalog.json()["items"]
    }
    assert owner_targets.status_code == 200
    assert str(parent.resource_id) in {
        item["target_id"] for item in owner_targets.json()["items"]
    }
    assert owner_range.status_code == 206
    assert owner_range.content == owner_content.content[:10]
    assert owner_range.headers["content-range"].endswith(
        f"/{len(owner_content.content)}",
    )
    assert owner_original.status_code == 200
    assert owner_original.content == payload
    assert owner_original_suffix.status_code == 206
    assert owner_original_suffix.content == payload[-10:]
    assert owner_invalid_range.status_code == 416
    assert owner_invalid_range.content != payload
    assert owner_original.headers["content-disposition"].startswith("attachment;")
    assert owner_original.headers["cache-control"] == "private, no-store"
    assert owner_manifest.json()["capabilities"]["download_original"]
    for denied_response, unknown_response in (
        (unrelated_status, unknown_status),
        (unrelated_manifest, unknown_manifest),
        (unrelated_content, unknown_content),
        (admin_status, unknown_status),
        (admin_manifest, unknown_manifest),
        (admin_content, unknown_content),
    ):
        assert denied_response.status_code == unknown_response.status_code == 404
        assert denied_response.json()["error"] == unknown_response.json()["error"]
        assert denied_response.json()["job_id"] is None

    async with factory() as session, session.begin():
        repository = ResourceRepository()
        for record in (
            ACLRecord(
                resource_id=parent.resource_id,
                principal_type="user",
                principal_id=viewer,
                action="view",
                effect="allow",
            ),
            ACLRecord(
                resource_id=parent.resource_id,
                principal_type="user",
                principal_id=expired,
                action="view",
                effect="allow",
                valid_from=datetime.now(UTC) - timedelta(hours=2),
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            ),
            ACLRecord(
                resource_id=parent.resource_id,
                principal_type="user",
                principal_id=denied,
                action="view",
                effect="allow",
            ),
            ACLRecord(
                resource_id=document_id,
                principal_type="user",
                principal_id=denied,
                action="view",
                effect="deny",
            ),
            ACLRecord(
                resource_id=parent.resource_id,
                principal_type="user",
                principal_id=admin,
                action="view",
                effect="allow",
            ),
            ACLRecord(
                resource_id=document_id,
                principal_type="user",
                principal_id=admin,
                action="view",
                effect="deny",
            ),
            ACLRecord(
                resource_id=parent.resource_id,
                principal_type="user",
                principal_id=owner,
                action="view",
                effect="deny",
            ),
        ):
            await repository.add_acl(
                session,
                record,
                request_id=f"acl-grant-{uuid.uuid4()}",
            )
    async with _http_client(subjects) as client:
        viewer_status = await client.get(
            status_url,
            headers={"X-Test-Subject": "viewer"},
        )
        viewer_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "viewer"},
        )
        viewer_content = await client.get(
            content_url,
            headers={"X-Test-Subject": "viewer"},
        )
        expired_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "expired"},
        )
        expired_status = await client.get(
            status_url,
            headers={"X-Test-Subject": "expired"},
        )
        expired_content = await client.get(
            content_url,
            headers={"X-Test-Subject": "expired"},
        )
        denied_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "denied"},
        )
        denied_status = await client.get(
            status_url,
            headers={"X-Test-Subject": "denied"},
        )
        denied_content = await client.get(
            content_url,
            headers={"X-Test-Subject": "denied"},
        )
        admin_manifest = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "admin"},
        )
        admin_status_after_deny = await client.get(
            status_url,
            headers={"X-Test-Subject": "admin"},
        )
        admin_content_after_deny = await client.get(
            content_url,
            headers={"X-Test-Subject": "admin"},
        )
        owner_manifest_after_deny = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "owner"},
        )
        owner_status_after_deny = await client.get(
            status_url,
            headers={"X-Test-Subject": "owner"},
        )
        owner_content_after_deny = await client.get(
            content_url,
            headers={"X-Test-Subject": "owner"},
        )
    assert viewer_status.status_code == 200
    assert viewer_manifest.status_code == 200
    assert viewer_content.status_code == 200
    assert not viewer_manifest.json()["capabilities"]["download_original"]
    assert {
        expired_manifest.status_code,
        expired_status.status_code,
        expired_content.status_code,
        denied_manifest.status_code,
        denied_status.status_code,
        denied_content.status_code,
        admin_manifest.status_code,
        admin_status_after_deny.status_code,
        admin_content_after_deny.status_code,
        owner_manifest_after_deny.status_code,
        owner_status_after_deny.status_code,
        owner_content_after_deny.status_code,
    } == {404}

    async with factory() as session, session.begin():
        await ResourceRepository().add_acl(
            session,
            ACLRecord(
                resource_id=document_id,
                principal_type="user",
                principal_id=viewer,
                action="download",
                effect="allow",
            ),
            request_id=f"acl-grant-{uuid.uuid4()}",
        )
    async with _http_client(subjects) as client:
        viewer_manifest_with_download = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "viewer"},
        )
    assert viewer_manifest_with_download.status_code == 200
    assert viewer_manifest_with_download.json()["capabilities"]["download_original"]

    async with factory() as session, session.begin():
        await ResourceRepository().add_acl(
            session,
            ACLRecord(
                resource_id=original_object_id,
                principal_type="user",
                principal_id=viewer,
                action="download",
                effect="deny",
            ),
            request_id=f"object-download-deny-{uuid.uuid4()}",
        )
    async with _http_client(subjects) as client:
        viewer_catalog_after_object_deny = await client.get(
            "/api/v1/files",
            headers={"X-Test-Subject": "viewer"},
        )
        viewer_manifest_after_object_deny = await client.get(
            manifest_url,
            headers={"X-Test-Subject": "viewer"},
        )
        viewer_original_after_object_deny = await client.get(
            original_url,
            headers={"X-Test-Subject": "viewer"},
        )
    denied_catalog_item = next(
        item for item in viewer_catalog_after_object_deny.json()["items"]
        if item["version_id"] == str(version_id)
    )
    assert not denied_catalog_item["can_download"]
    assert not viewer_manifest_after_object_deny.json()["capabilities"][
        "download_original"
    ]
    assert viewer_original_after_object_deny.status_code == 404

    group_id = uuid.uuid4()
    department_id = uuid.uuid4()
    project_id = uuid.uuid4()
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO groups(group_id,issuer,provider_group_key,name)
            VALUES (:group_id,'https://integration.identity',:key,'Effective deny')
        """), {"group_id": group_id, "key": f"effective-{group_id}"})
        await session.execute(text("""
            INSERT INTO subject_groups(subject_id,group_id)
            VALUES (:subject_id,:group_id)
        """), {
            "subject_id": effective_cases["group"],
            "group_id": group_id,
        })
        role_id = await session.scalar(text("""
            SELECT role_id FROM roles WHERE key='staff'
        """))
        assert role_id
        await session.execute(text("""
            INSERT INTO subject_roles(subject_id,role_id)
            VALUES (:subject_id,:role_id)
        """), {
            "subject_id": effective_cases["role"],
            "role_id": role_id,
        })
        for scope_type, scope_id in (
            ("department", department_id),
            ("project", project_id),
        ):
            await session.execute(text("""
                INSERT INTO subject_scopes(subject_id,scope_type,scope_key)
                VALUES (:subject_id,:scope_type,:scope_key)
            """), {
                "subject_id": effective_cases[scope_type],
                "scope_type": scope_type,
                "scope_key": str(scope_id),
            })
        repository = ResourceRepository()
        for principal in effective_cases.values():
            await repository.add_acl(
                session,
                ACLRecord(
                    resource_id=parent.resource_id,
                    principal_type="user",
                    principal_id=principal,
                    action="view",
                    effect="allow",
                ),
                request_id=f"effective-allow-{uuid.uuid4()}",
            )
        for principal_type, principal_id in (
            ("group", group_id),
            ("role", role_id),
            ("department", department_id),
            ("project", project_id),
        ):
            await repository.add_acl(
                session,
                ACLRecord(
                    resource_id=document_id,
                    principal_type=principal_type,  # type: ignore[arg-type]
                    principal_id=principal_id,
                    action="view",
                    effect="deny",
                ),
                request_id=f"effective-deny-{uuid.uuid4()}",
            )
    async with _http_client(subjects) as client:
        effective_denials = [
            await client.get(
                manifest_url,
                headers={"X-Test-Subject": f"effective-{principal_type}"},
            )
            for principal_type in effective_cases
        ]
    assert [response.status_code for response in effective_denials] == [404] * 4


@pytest.mark.asyncio
async def test_upload_targets_scan_past_first_batch_without_authorization_starvation(
    factory: async_sessionmaker[Any],
) -> None:
    principal, _parent = await _principal_and_parent(factory)
    unrelated = await _new_principal(factory, "target-scan-unrelated")
    decoy_ids = [uuid.uuid4() for _ in range(200)]
    authorized_id = uuid.uuid4()
    resource_rows = [
        {
            "resource_id": resource_id,
            "owner_subject_id": unrelated,
        }
        for resource_id in decoy_ids
    ]
    resource_rows.append({
        "resource_id": authorized_id,
        "owner_subject_id": principal,
    })
    source_rows = [
        {
            "source_id": resource_id,
            "name": f"scan-target-{index:03d}",
        }
        for index, resource_id in enumerate(decoy_ids)
    ]
    source_rows.append({
        "source_id": authorized_id,
        "name": "zzzz-authorized-after-first-scan-batch",
    })
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO resources(
              resource_id,resource_type,owner_subject_id,classification,
              source_zone,lifecycle_state
            ) VALUES (
              :resource_id,'source',:owner_subject_id,'internal',
              'private_context','active'
            )
        """), resource_rows)
        await session.execute(text("""
            INSERT INTO sources(source_id,kind,name,metadata)
            VALUES (:source_id,'internal',:name,'{}')
        """), source_rows)
    async with _http_client({"scanner": _subject(principal)}) as client:
        response = await client.get(
            "/api/v1/files/upload-targets",
            headers={"X-Test-Subject": "scanner"},
        )
    assert response.status_code == 200
    assert str(authorized_id) in {
        item["target_id"] for item in response.json()["items"]
    }


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("espeak-ng") is None,
    reason="private media fixture runtime not installed",
)
async def test_all_14_formats_persist_31_required_outputs_and_viewer_manifests(
    factory: async_sessionmaker[Any],
    tmp_path: Path,
) -> None:
    app_settings = get_settings()
    service = IngestionService(
        settings=app_settings,
        storage=S3ObjectStorage(app_settings),
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("clean"),
    )
    principal, parent = await _principal_and_parent(factory)
    fixtures = {
        **_document_fixtures(tmp_path),
        **_media_fixtures(tmp_path),
    }
    assert len(fixtures) == 14
    version_ids: list[uuid.UUID] = []
    for filename, (mime, payload) in fixtures.items():
        upload_id, validation_job = await service.receive(
            _bytes_stream(payload),
            content_length=len(payload),
            parent=parent,
            logical_name=filename,
            original_filename=filename,
            declared_mime=mime,
            declared_sha256=None,
            requested_by=principal,
            request_id=f"all-formats-{uuid.uuid4()}",
        )
        assert await service.process_job(
            validation_job,
            worker_id=f"validate-{filename}",
        )
        async with factory() as session:
            version_id = await session.scalar(text("""
                SELECT version_id FROM upload_sessions WHERE upload_id=:upload_id
            """), {"upload_id": upload_id})
            render_job = await session.scalar(text("""
                SELECT job_id FROM ingestion_jobs
                WHERE version_id=:version_id AND job_type='render'
            """), {"version_id": version_id})
        assert version_id and render_job
        rendered = await service.process_job(
            render_job,
            worker_id=f"render-{filename}",
        )
        if not rendered:
            async with factory() as session:
                failure = (await session.execute(text("""
                    SELECT status,error_code,error_fingerprint,attempt
                    FROM ingestion_jobs
                    WHERE job_id=:job_id
                """), {"job_id": render_job})).mappings().one()
            pytest.fail(f"{filename}:{dict(failure)}")
        version_ids.append(version_id)
    async with factory() as session:
        versions = (await session.execute(text("""
            SELECT version_id,viewer_state,detected_mime
            FROM document_versions WHERE version_id=ANY(:version_ids)
        """), {"version_ids": version_ids})).mappings().all()
        renditions = (await session.execute(text("""
            SELECT r.version_id,r.kind,r.status,r.provenance,
              o.sha256,o.byte_size,o.storage_state
            FROM renditions r
            JOIN object_blobs o ON o.object_id=r.object_id
            WHERE r.version_id=ANY(:version_ids)
        """), {"version_ids": version_ids})).mappings().all()
    required = [
        item for item in renditions
        if item["provenance"]["origin"] in {"native", "render"}
    ]
    assert len(versions) == 14
    assert len({item["detected_mime"] for item in versions}) == 14
    assert all(item["viewer_state"] == "ready" for item in versions)
    assert len(required) == 31
    assert len(renditions) >= 31
    assert all(item["status"] == "ready" for item in renditions)
    assert all(item["storage_state"] == "available" for item in renditions)
    assert all(item["sha256"] and item["byte_size"] > 0 for item in renditions)
    subjects = {"owner": _subject(principal)}
    async with _http_client(subjects) as client:
        responses = [
            await client.get(
                f"/api/v1/files/versions/{version_id}/viewer-manifest",
                headers={"X-Test-Subject": "owner"},
            )
            for version_id in version_ids
        ]
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["capabilities"]["preview"] for response in responses)
    assert sum(
        len(response.json()["renditions"]) for response in responses
    ) == len(renditions)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg runtime not installed")
def test_real_ffmpeg_required_media_matrix(tmp_path: Path) -> None:
    source_wav = tmp_path / "source.wav"
    with wave.open(str(source_wav), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 8_000)

    commands = {
        "fixture.mp3": [
            "-i", str(source_wav), "-c:a", "libmp3lame",
        ],
        "fixture.m4a": [
            "-i", str(source_wav), "-c:a", "aac",
        ],
        "fixture.ogg": [
            "-i", str(source_wav), "-c:a", "libopus",
        ],
        "fixture.mp4": [
            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
            "-t", "0.5", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        ],
        "fixture.webm": [
            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
            "-t", "0.5", "-c:v", "libvpx",
        ],
    }
    for filename, arguments in commands.items():
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", *arguments, "-y", filename],
            cwd=tmp_path,
            check=True,
        )

    fixtures = {
        "source.wav": ("audio/wav", {"browser_audio", "waveform"}),
        "fixture.mp3": ("audio/mpeg", {"browser_audio", "waveform"}),
        "fixture.m4a": ("audio/mp4", {"browser_audio", "waveform"}),
        "fixture.ogg": ("audio/ogg", {"browser_audio", "waveform"}),
        "fixture.mp4": ("video/mp4", {"browser_video", "poster"}),
        "fixture.webm": ("video/webm", {"browser_video", "poster"}),
    }
    app_settings = get_settings()
    sandbox = ProcessSandbox(
        timeout_seconds=app_settings.ingestion_tool_timeout_seconds,
        temp_bytes=app_settings.ingestion_temp_bytes,
    )
    output_count = 0
    for filename, (mime, required_kinds) in fixtures.items():
        path = tmp_path / filename
        detected = validate_content(
            path,
            filename=filename,
            declared_mime=mime,
            settings=app_settings,
            sandbox=sandbox,
        )
        try:
            artifacts = extract_required(
                path,
                mime=detected.detected_mime,
                structural=detected.structural,
                settings=app_settings,
                sandbox=sandbox,
            )
        except Exception as exc:
            raise AssertionError(f"required media output failed for {filename}") from exc
        assert {artifact.kind for artifact in artifacts} == required_kinds
        assert all(artifact.sha256 and artifact.payload for artifact in artifacts)
        output_count += len(artifacts)
    assert output_count == 12


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract runtime not installed",
)
def test_private_ocr_is_real_rotated_deterministic_and_geometric(
    tmp_path: Path,
) -> None:
    source = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(source)
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 64)
    draw.text((35, 70), "ROBOT SAFETY REPORT", fill="black", font=font)
    path = tmp_path / "rotated.png"
    source.rotate(90, expand=True).save(path)
    app_settings = get_settings()
    engine = LocalTesseractOCR(
        app_settings,
        ProcessSandbox(
            timeout_seconds=app_settings.ingestion_tool_timeout_seconds,
            temp_bytes=app_settings.ingestion_temp_bytes,
        ),
    )
    first = engine.artifact_for_input(path, mime="image/png")
    second = engine.artifact_for_input(path, mime="image/png")
    assert first.sha256 == second.sha256
    assert first.kind == "ocr_json"
    payload = __import__("json").loads(first.payload)
    assert payload["regions"]
    assert "ROBOT" in " ".join(
        region["text"] for region in payload["regions"]
    ).upper()
    assert all(region["origin"] == "ocr" for region in payload["regions"])
    assert all(
        region["bounding_box"][2] > region["bounding_box"][0]
        and region["bounding_box"][3] > region["bounding_box"][1]
        for region in payload["regions"]
    )
    assert payload["aggregate_confidence"] > 0


@pytest.mark.skipif(
    shutil.which("espeak-ng") is None,
    reason="eSpeak runtime not installed",
)
def test_private_vosk_transcript_json_vtt_is_offline_and_deterministic(
    tmp_path: Path,
) -> None:
    speech = tmp_path / "speech.wav"
    subprocess.run(
        [
            "espeak-ng",
            "-s",
            "135",
            "-w",
            str(speech),
            "one two three four five",
        ],
        check=True,
    )
    app_settings = get_settings()
    sandbox = ProcessSandbox(
        timeout_seconds=app_settings.ingestion_tool_timeout_seconds,
        temp_bytes=app_settings.ingestion_temp_bytes,
    )
    detection = validate_content(
        speech,
        filename=speech.name,
        declared_mime="audio/wav",
        settings=app_settings,
        sandbox=sandbox,
    )
    duration_ms = int(detection.structural["duration_ms"])
    engine = LocalVoskTranscript(app_settings, sandbox)
    first = engine.transcribe(speech, duration_ms=duration_ms)
    second = engine.transcribe(speech, duration_ms=duration_ms)
    assert [(item.kind, item.sha256) for item in first] == [
        (item.kind, item.sha256) for item in second
    ]
    assert {item.kind for item in first} == {
        "transcript_json",
        "transcript_vtt",
    }
    transcript_json = next(
        item for item in first if item.kind == "transcript_json"
    )
    payload = __import__("json").loads(transcript_json.payload)
    assert payload["segments"]
    assert all(
        0 <= segment["start_ms"] < segment["end_ms"] <= duration_ms
        for segment in payload["segments"]
    )
    assert all(segment["origin"] == "transcript" for segment in payload["segments"])
    assert all(segment["speaker_label"] is None for segment in payload["segments"])
    transcript_vtt = next(
        item for item in first if item.kind == "transcript_vtt"
    )
    assert transcript_vtt.payload.startswith(b"WEBVTT\n")


def test_private_vosk_missing_and_corrupt_models_fail_with_stable_codes(
    tmp_path: Path,
) -> None:
    app_settings = get_settings()
    sandbox = ProcessSandbox(
        timeout_seconds=app_settings.ingestion_tool_timeout_seconds,
        temp_bytes=app_settings.ingestion_temp_bytes,
    )
    missing = app_settings.model_copy(update={
        "ingestion_vosk_model_path": str(tmp_path / "missing-model"),
    })
    with pytest.raises(IngestionFailure) as missing_failure:
        LocalVoskTranscript(missing, sandbox).transcribe(
            tmp_path / "unused.wav",
            duration_ms=1000,
        )
    assert missing_failure.value.code == "transcript_model_unavailable"
    corrupt_path = tmp_path / "corrupt-model"
    corrupt_path.mkdir()
    (corrupt_path / ".archive-sha256").write_text("0" * 64, encoding="ascii")
    corrupt = app_settings.model_copy(update={
        "ingestion_vosk_model_path": str(corrupt_path),
    })
    with pytest.raises(IngestionFailure) as corrupt_failure:
        LocalVoskTranscript(corrupt, sandbox).transcribe(
            tmp_path / "unused.wav",
            duration_ms=1000,
        )
    assert corrupt_failure.value.code == "transcript_model_invalid"


def test_sandbox_os_enforces_no_socket_dns_or_tcp(tmp_path: Path) -> None:
    app_settings = get_settings()
    sandbox = ProcessSandbox(
        timeout_seconds=app_settings.ingestion_tool_timeout_seconds,
        temp_bytes=app_settings.ingestion_temp_bytes,
    )
    script = (
        "import errno,json,socket\n"
        "result={}\n"
        "for name,call in ["
        "('socket',lambda:socket.socket()),"
        "('dns',lambda:socket.getaddrinfo('no-such-host.invalid',80)),"
        "('tcp',lambda:socket.create_connection(('127.0.0.1',9),0.1))]:\n"
        " try: call(); result[name]='unexpected'\n"
        " except OSError as exc: result[name]=exc.errno\n"
        "print(json.dumps(result,sort_keys=True))\n"
    )
    result = sandbox.run(
        [sys.executable, "-c", script],
        temp_root=tmp_path,
    )
    blocked = __import__("json").loads(result.stdout)
    assert blocked["socket"] == 1
    assert blocked["tcp"] == 1
    assert blocked["dns"] in {None, 1, -3}
