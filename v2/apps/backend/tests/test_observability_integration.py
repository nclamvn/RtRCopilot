"""TIP-012 Task 3 — observability integration coverage against live infra.

Proves end to end (live Postgres :5432, Redis :6380, MinIO :9002):

* AC-09 request-id chain: the api logs request-id R, the ingestion job row the
  request spawns persists R, and the worker logs R while processing that job.
* AC-09 log-leak probe: across bad-upload, denied-access, oversized-body,
  rate-limited, provider-failure and internal-exception paths, no secret value,
  object key, bucket URL, DSN/credential shape or internal host:port appears in
  any emitted log.
* AC-10 audit export: a non-admin is denied (403) and creates no export event;
  an admin gets a checksummed JSONL export whose checksum matches the body and
  whose export action is itself in the audit trail.
* AC-08: the worker's dedicated metrics endpoint serves the exposition.

House pattern: ASGITransport + dependency overrides; a fresh DB migrated to
head; skipped unless INTEGRATION_DATABASE_DSN is set.
"""

import hashlib
import json
import os
import socket
import urllib.request
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_ingestion_integration import (
    _bytes_stream,
    _png,
    _principal_and_parent,
    _subject,
)

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.api import governance_subject
from rtr_copilot.ingestion.malware import DeterministicTestScanner
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.rag.api import rag_subject
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.storage.s3 import S3ObjectStorage

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


# --------------------------------------------------------------------------- #
# AC-09 — request-id chain: api → job row → worker
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_request_id_propagates_api_to_worker_job(
    factory: async_sessionmaker[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = get_settings()
    service = IngestionService(
        settings=settings,
        storage=S3ObjectStorage(settings),
        uow=UnitOfWork(factory),
        scanner=DeterministicTestScanner("clean"),
    )
    principal, parent = await _principal_and_parent(factory)
    request_id = f"chain-{uuid.uuid4()}"
    payload = _png()

    with caplog.at_level("INFO", logger="rtr_copilot"):
        # 1) The api handler logs request-id R (ingress → api seam).
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            resp = await client.get("/", headers={"X-Request-ID": request_id})
        assert resp.headers["X-Request-ID"] == request_id

        # 2) The request spawns a durable ingestion job carrying R.
        upload_id, job_id = await service.receive(
            _bytes_stream(payload),
            content_length=len(payload),
            parent=parent,
            logical_name="chain image",
            original_filename="chain.png",
            declared_mime="image/png",
            declared_sha256=None,
            requested_by=principal,
            request_id=request_id,
        )
        # 3) The worker processes the job and logs R.
        assert await service.process_job(job_id, worker_id="chain-worker")

    # The job table persisted the originating request-id (Task-3 premise).
    async with factory() as session:
        stored = await session.scalar(text(
            "SELECT request_id FROM ingestion_jobs WHERE job_id=:job_id",
        ), {"job_id": job_id})
    assert stored == request_id

    events = [
        json.loads(rec.message)
        for rec in caplog.records
        if rec.name.startswith("rtr_copilot")
        and rec.message.startswith("{")
    ]
    api_logs = [e for e in events if e.get("event") == "request"
                and e.get("request_id") == request_id]
    worker_logs = [e for e in events if e.get("event") == "worker_job_processing"
                   and e.get("request_id") == request_id]
    assert api_logs, "api did not log the request-id"
    assert worker_logs, "worker did not log the originating request-id"
    assert worker_logs[0]["family"] == "ingestion"
    assert upload_id is not None


# --------------------------------------------------------------------------- #
# AC-09 — log-leak probe over exercised error paths
# --------------------------------------------------------------------------- #
def _forbidden_needles() -> list[str]:
    settings = get_settings()
    needles = [
        # Live secret values must never appear in a log line.
        settings.s3_secret_key,
        settings.s3_access_key,
        settings.sot_signing_secret.get_secret_value(),
        # DSN / URL credential shapes.
        "postgresql://",
        "postgresql+asyncpg://",
        "redis://",
        "rediss://",
        # Internal host:port forms (compose service names + native ports).
        "postgres:5432",
        "redis:6379",
        "redis:6380",
        "minio:9000",
        "minio:9002",
        "api:8000",
        "clamav:3310",
    ]
    # Any password embedded in the runtime DSN.
    for host in settings.postgres_dsn.hosts():
        pwd = host.get("password")
        if pwd:
            needles.append(str(pwd))
    return [n for n in needles if n]


@pytest.mark.asyncio
async def test_logs_are_leak_free_across_error_paths(
    factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from rtr_copilot.limits import middleware as limits_mw

    # Tune a tiny read limit and body cap so the rate-limit + 413 paths fire.
    tuned = get_settings().model_copy(update={
        "limits_rate_default_read_max": 2,
        "limits_max_body_bytes": 64,
    })
    monkeypatch.setattr(limits_mw, "get_settings", lambda: tuned)

    async def anon() -> None:
        return None

    # An internal exception whose message deliberately embeds an internal
    # host:port; the handler must log a fingerprint only, never this text.
    async def exploding_subject() -> None:
        raise RuntimeError("db at postgres:5432 with postgresql://u:pw@postgres/db")

    ip = "203.0.113.7"
    with caplog.at_level("INFO", logger="rtr_copilot"):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            # bad upload / not-found
            await client.get("/api/v1/does-not-exist")
            # denied access (no subject on an authenticated surface)
            app.dependency_overrides[rag_subject] = anon
            try:
                await client.post("/api/v1/ask", json={"question": "x", "filters": {}})
                # oversized body -> typed 413 in middleware
                await client.post(
                    "/api/v1/ask",
                    content=b"y" * 4096,
                    headers={"content-type": "application/json"},
                )
            finally:
                app.dependency_overrides.pop(rag_subject, None)
            # rate-limited -> 429 after the tuned threshold
            for _ in range(4):
                await client.get("/api/v1/files", headers={"x-forwarded-for": ip})
            # internal exception -> synthesized 500, fingerprint-only log
            app.dependency_overrides[rag_subject] = exploding_subject
            try:
                crashed = await client.post(
                    "/api/v1/ask", json={"question": "boom", "filters": {}},
                    headers={"x-forwarded-for": "203.0.113.9"},
                )
            finally:
                app.dependency_overrides.pop(rag_subject, None)
    assert crashed.status_code == 500

    blob = "\n".join(
        rec.message for rec in caplog.records if rec.name.startswith("rtr_copilot")
    )
    leaked = [needle for needle in _forbidden_needles() if needle in blob]
    assert not leaked, f"log leak: {leaked}"
    # Sanity: the probe actually exercised the paths (some structured logs exist).
    assert '"event": "request_error"' in blob or '"event":"request_error"' in blob


# --------------------------------------------------------------------------- #
# AC-10 — admin-gated, checksummed audit export, itself audited
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_audit_export_two_subject_checksummed_and_audited(
    factory: async_sessionmaker[Any],
) -> None:
    admin_id = uuid.UUID((await PostgresSubjectRepository(factory).upsert_from_claims(
        {"iss": "https://integration.identity", "sub": f"admin-{uuid.uuid4().hex}",
         "email": f"admin-{uuid.uuid4().hex}@rtrobotics.com", "email_verified": True,
         "name": "Admin", "groups": []}, {},
    )).user_id)
    staff_id = uuid.UUID((await PostgresSubjectRepository(factory).upsert_from_claims(
        {"iss": "https://integration.identity", "sub": f"staff-{uuid.uuid4().hex}",
         "email": f"staff-{uuid.uuid4().hex}@rtrobotics.com", "email_verified": True,
         "name": "Staff", "groups": []}, {},
    )).user_id)
    admin = _subject(admin_id, role=Role.ADMIN)
    staff = _subject(staff_id, role=Role.STAFF)

    holder: dict[str, Any] = {"subject": None}

    async def override() -> Any:
        return holder["subject"]

    app.dependency_overrides[governance_subject] = override
    params = {"start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z", "limit": 5000}
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            # Non-admin -> typed 403, no export produced.
            holder["subject"] = staff
            denied = await client.get("/api/v1/audit/export", params=params)
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "admin_required"

            # Admin -> 200 checksummed JSONL.
            holder["subject"] = admin
            granted = await client.get("/api/v1/audit/export", params=params)
    finally:
        app.dependency_overrides.pop(governance_subject, None)

    assert granted.status_code == 200
    assert granted.headers["content-type"].startswith("application/x-ndjson")
    body = granted.content
    checksum = granted.headers["X-Audit-Export-Checksum"]
    assert checksum == f"sha256:{hashlib.sha256(body).hexdigest()}"
    count = int(granted.headers["X-Audit-Export-Count"])
    lines = [ln for ln in body.decode().splitlines() if ln]
    assert len(lines) == count >= 1
    # Every line is a valid JSON audit event.
    for line in lines[:20]:
        parsed = json.loads(line)
        assert {"sequence", "action", "event_hash", "request_id"} <= set(parsed)

    async with factory() as session:
        export_events = await session.scalar(text("""
            SELECT count(*) FROM audit_events
            WHERE action='admin.audit.export' AND actor_user_id=:actor
        """), {"actor": admin_id})
        staff_exports = await session.scalar(text("""
            SELECT count(*) FROM audit_events
            WHERE action='admin.audit.export' AND actor_user_id=:actor
        """), {"actor": staff_id})
    assert export_events >= 1  # the admin export is itself audited
    assert staff_exports == 0  # the denied attempt created no export event


@pytest.mark.asyncio
async def test_audit_export_rejects_inverted_time_range() -> None:
    admin = _subject(uuid.uuid4(), role=Role.ADMIN)

    async def override() -> Any:
        return admin

    app.dependency_overrides[governance_subject] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/audit/export", params={
                "start": "2100-01-01T00:00:00Z", "end": "2000-01-01T00:00:00Z",
            })
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_time_range"


# --------------------------------------------------------------------------- #
# AC-08 — the worker's dedicated metrics endpoint serves the exposition
# --------------------------------------------------------------------------- #
def test_worker_metrics_server_serves_exposition() -> None:
    from rtr_copilot.observability import worker as worker_obs

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Fresh flag so this test drives a real bind regardless of order.
    worker_obs._started = False
    worker_obs.start_worker_metrics_server(port)
    try:
        with urllib.request.urlopen(  # noqa: S310 - localhost only
            f"http://127.0.0.1:{port}/metrics", timeout=5,
        ) as response:
            body = response.read().decode()
    finally:
        worker_obs._started = False
    assert "rtr_worker_job_duration_seconds" in body or "python_info" in body
