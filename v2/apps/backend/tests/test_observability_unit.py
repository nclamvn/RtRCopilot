"""TIP-012 Task 3 — observability unit coverage (no live infra).

Proves, with fakes only: the route classifier is bounded, the HTTP middleware
records latency by class/status, the typed-error and limit metrics increment,
the worker job telemetry + request-id log fire, the DB-pool refresh is
crash-safe, the audit-export gate denies non-admins and its serializer redacts
secrets, and every metric's label set is free of unbounded/PII dimensions.
"""

import json
from typing import Any

import httpx
import pytest
from prometheus_client import REGISTRY

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.governance.audit_export import AuditExportService, _serialize_event
from rtr_copilot.observability import metrics as m
from rtr_copilot.observability.db import refresh_db_pool_metrics
from rtr_copilot.observability.http import meter_error, route_class
from rtr_copilot.observability.worker import log_job_request_id, observe_job


def _subject(role: Role) -> Subject:
    return Subject(
        user_id="00000000-0000-0000-0000-000000000001",
        issuer="test",
        sub="s",
        email="p@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --------------------------------------------------------------------------- #
# Route classifier — bounded, id-free
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "root"),
        ("/api/v1/ask", "ask"),
        ("/api/v1/files/uploads", "upload"),
        ("/api/v1/files/uploads/abc123", "upload"),
        ("/api/v1/files", "files"),
        ("/api/v1/files/9f8e/download", "files"),
        ("/api/v1/templates/1/render", "documents"),
        ("/api/v1/admin/settings", "admin"),
        ("/api/v1/audit/export", "audit"),
        ("/api/v1/governance/dashboard", "governance"),
        ("/api/v1/gaps", "governance"),
        ("/api/v1/sot/packages", "sot"),
        ("/api/v1/research/x", "research"),
        ("/auth/callback", "auth"),
        ("/health/ready", "health"),
        ("/metrics", "metrics"),
        ("/system/ping", "system"),
        ("/totally/unknown/path", "other"),
    ],
)
def test_route_class_is_bounded(path: str, expected: str) -> None:
    assert route_class(path) == expected


def test_route_class_never_leaks_ids_into_a_new_class() -> None:
    # A subject-id-bearing path collapses to a fixed class, never a per-id one.
    a = route_class("/api/v1/files/11111111-1111-1111-1111-111111111111")
    b = route_class("/api/v1/files/22222222-2222-2222-2222-222222222222")
    assert a == b == "files"


# --------------------------------------------------------------------------- #
# Metric labels stay bounded (no subject id / ip / raw path dimensions)
# --------------------------------------------------------------------------- #
def test_no_metric_uses_an_unbounded_label() -> None:
    forbidden = {"subject", "subject_id", "user", "user_id", "ip", "path",
                 "request_id", "actor", "object_key", "email"}
    metric_objects = [
        m.HTTP_REQUEST_DURATION, m.HTTP_ERRORS, m.DB_POOL_CONNECTIONS,
        m.PROVIDER_CALL_DURATION, m.PROVIDER_CALL_FAILURES,
        m.PROVIDER_BUDGET_EXHAUSTED, m.PROVIDER_BREAKER_OPEN,
        m.PROVIDER_BREAKER_REFUSALS, m.RATE_LIMIT_REJECTIONS,
        m.JOB_QUEUE_DEPTH, m.JOB_QUEUE_SATURATION, m.JOB_DURATION,
        m.JOBS_PROCESSED,
    ]
    for metric in metric_objects:
        assert not (set(metric._labelnames) & forbidden), metric._name


# --------------------------------------------------------------------------- #
# Typed-error meter
# --------------------------------------------------------------------------- #
def test_meter_error_increments_typed_counter() -> None:
    labels = {"code": "not_found", "route_class": "files"}
    before = _sample("rtr_http_errors_total", labels)
    meter_error("not_found", "/api/v1/files/x")
    assert _sample("rtr_http_errors_total", labels) == before + 1


# --------------------------------------------------------------------------- #
# HTTP latency middleware + /metrics exposition (through the real ASGI stack)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_http_middleware_records_latency_for_root() -> None:
    labels = {"route_class": "root", "method": "GET", "status": "200"}
    before = _sample("rtr_http_request_duration_seconds_count", labels)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert _sample("rtr_http_request_duration_seconds_count", labels) == before + 1


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_all_custom_series() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    for name in (
        "rtr_http_request_duration_seconds",
        "rtr_http_errors_total",
        "rtr_db_pool_connections",
        "rtr_provider_call_duration_seconds",
        "rtr_provider_budget_debit_units_total",
        "rtr_provider_breaker_open",
        "rtr_rate_limit_rejections_total",
        "rtr_job_queue_depth",
        "rtr_worker_job_duration_seconds",
        "rtr_audit_chain_valid",
    ):
        assert name in body, name
    # /metrics stays internal: it is NOT one of the app's documented routes and
    # carries the Prometheus content type.
    assert "text/plain" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_scrape_refreshes_db_pool_without_error() -> None:
    # The /metrics handler calls refresh_db_pool_metrics(); the gauge is present
    # and numeric after a scrape even with no DB connection opened.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/metrics")
    assert REGISTRY.get_sample_value(
        "rtr_db_pool_connections", {"state": "size"},
    ) is not None


def test_refresh_db_pool_metrics_never_raises() -> None:
    refresh_db_pool_metrics()  # must not raise even if the engine is unused
    assert REGISTRY.get_sample_value(
        "rtr_db_pool_connections", {"state": "checked_out"},
    ) is not None


# --------------------------------------------------------------------------- #
# Worker job telemetry + request-id log line
# --------------------------------------------------------------------------- #
def test_observe_job_records_success_and_error() -> None:
    ok = {"family": "ingestion", "result": "success"}
    bad = {"family": "ingestion", "result": "error"}
    ok_before = _sample("rtr_worker_jobs_total", ok)
    bad_before = _sample("rtr_worker_jobs_total", bad)
    with observe_job("ingestion"):
        pass
    with pytest.raises(RuntimeError), observe_job("ingestion"):
        raise RuntimeError("boom")
    assert _sample("rtr_worker_jobs_total", ok) == ok_before + 1
    assert _sample("rtr_worker_jobs_total", bad) == bad_before + 1


def test_log_job_request_id_emits_worker_chain_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="rtr_copilot.worker"):
        log_job_request_id("ingestion", "req-CHAIN-XYZ", job_id="job-1")
    events = [
        json.loads(rec.message)
        for rec in caplog.records
        if rec.name == "rtr_copilot.worker"
    ]
    match = [e for e in events if e.get("event") == "worker_job_processing"]
    assert match and match[0]["request_id"] == "req-CHAIN-XYZ"
    assert match[0]["family"] == "ingestion"


# --------------------------------------------------------------------------- #
# Audit export: gate + secret-free serialization
# --------------------------------------------------------------------------- #
def test_audit_export_gate_denies_non_admin_and_admits_admin() -> None:
    service = AuditExportService()
    with pytest.raises(PermissionError):
        service._admin_gate(_subject(Role.STAFF), "req-1")
    # An admin passes the gate (returns None, no raise).
    service._admin_gate(_subject(Role.ADMIN), "req-2")


def test_serialize_event_redacts_secret_details() -> None:
    import uuid
    from datetime import UTC, datetime

    row: dict[str, Any] = {
        "sequence": 7,
        "event_id": uuid.uuid4(),
        "occurred_at": datetime(2026, 8, 1, tzinfo=UTC),
        "actor_kind": "user",
        "actor_user_id": uuid.uuid4(),
        "action": "auth.login",
        "result": "success",
        "reason_code": "ok",
        "request_id": "req-9",
        "session_fingerprint": None,
        "resource_id": None,
        "resource_type": None,
        "matched_policy_ids": [],
        # A hostile details blob: secret-shaped KEYS are dropped entirely, and a
        # value that itself carries a forbidden word is replaced with [REDACTED].
        "details": {
            "access_token": "super-secret-token-value",
            "password": "hunter2",
            "header": "authorization: Bearer abc",
            "note": "ok",
        },
        "event_hash": "a" * 64,
    }
    line = _serialize_event(row)
    # Secret-keyed entries never leave the system.
    assert "super-secret-token-value" not in line
    assert "hunter2" not in line
    assert "access_token" not in line
    assert "password" not in line
    # A forbidden-word value is masked.
    assert "Bearer abc" not in line
    assert "[REDACTED]" in line
    # The event is still valid JSON with its metadata + safe fields intact.
    parsed = json.loads(line)
    assert parsed["action"] == "auth.login"
    assert parsed["request_id"] == "req-9"
    assert parsed["details"]["note"] == "ok"
