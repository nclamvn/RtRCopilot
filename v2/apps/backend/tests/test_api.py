import json
import uuid

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from rtr_copilot.api import health
from rtr_copilot.api import main as api_main
from rtr_copilot.api.health import get_settings
from rtr_copilot.api.main import app
from rtr_copilot.config import Settings
from rtr_copilot.ingestion.api import file_subject


def settings() -> Settings:
    return Settings(
        postgres_dsn="postgresql://user:password@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="local",
        s3_secret_key="local-secret",
        s3_bucket="rtr-test",
    )


def test_live_has_request_id() -> None:
    app.dependency_overrides[get_settings] = settings
    with TestClient(app) as test_client:
        response = test_client.get("/health/live", headers={"X-Request-ID": "req-test"})
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test"
    assert response.json() == {"ok": True, "status": "live"}


def test_ready_is_503_without_dependencies(monkeypatch: MonkeyPatch) -> None:
    async def unavailable(_: Settings) -> dict[str, str]:
        return {"postgres": "unavailable", "redis": "ready", "object_storage": "ready"}

    monkeypatch.setattr(health, "probe_dependencies", unavailable)
    app.dependency_overrides[get_settings] = settings
    with TestClient(app) as test_client:
        response = test_client.get("/health/ready")
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "localhost" not in response.text
    assert response.json()["dependencies"]["postgres"] == "unavailable"


class FakePingRedis:
    def __init__(self) -> None:
        self.job: dict[str, str] | None = None

    async def exists(self, _: str) -> bool:
        return True

    async def lpush(self, _: str, raw: str) -> int:
        self.job = json.loads(raw)
        return 1

    async def get(self, _: str) -> str | None:
        if self.job is None:
            return None
        return json.dumps({
            "job_id": self.job["job_id"],
            "request_id": self.job["request_id"],
            "status": "pong",
        })

    async def aclose(self) -> None:
        return None


def ping_client(monkeypatch: MonkeyPatch) -> TestClient:
    fake = FakePingRedis()
    monkeypatch.setattr(api_main.Redis, "from_url", lambda *_args, **_kwargs: fake)
    app.dependency_overrides[get_settings] = settings
    return TestClient(app)


def test_ping_preserves_caller_request_id(monkeypatch: MonkeyPatch) -> None:
    with ping_client(monkeypatch) as test_client:
        response = test_client.post("/system/ping", headers={"X-Request-ID": "caller-id"})
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "caller-id"
    assert response.json()["request_id"] == "caller-id"


def test_ping_generated_request_id_has_one_source(monkeypatch: MonkeyPatch) -> None:
    with ping_client(monkeypatch) as test_client:
        response = test_client.post("/system/ping")
    app.dependency_overrides.clear()
    request_id = response.headers["X-Request-ID"]
    assert uuid.UUID(request_id)
    assert response.json()["request_id"] == request_id


def test_not_found_is_machine_readable() -> None:
    app.dependency_overrides[get_settings] = settings
    with TestClient(app) as test_client:
        response = test_client.get("/missing", headers={"X-Request-ID": "missing-id"})
    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "missing-id"
    assert response.json() == {
        "error": {"code": "not_found", "message": "Resource not found"},
        "request_id": "missing-id",
    }


@pytest.mark.asyncio
async def test_validation_error_is_machine_readable() -> None:
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/system/ping",
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    })
    request.state.request_id = "validation-id"
    response = await api_main.validation_error(request, RequestValidationError([]))
    assert response.status_code == 422
    assert json.loads(response.body) == {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed",
        },
        "request_id": "validation-id",
    }


@pytest.mark.asyncio
async def test_request_exception_log_redacts_message_and_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/redaction-proof",
        "headers": [(b"x-request-id", b"redaction-id")],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    })
    secret = "Bearer private-token /sensitive/path customer payload"

    async def injected_failure(_: Request) -> None:
        raise RuntimeError(secret)

    with caplog.at_level("ERROR", logger="rtr_copilot"):
        response = await api_main.request_context(request, injected_failure)
    assert response.status_code == 500
    assert secret not in caplog.text
    assert "private-token" not in caplog.text
    assert "/sensitive/path" not in caplog.text
    event = json.loads(caplog.records[-1].message)
    assert event["error_code"] == "internal_error"
    assert len(event["error_fingerprint"]) == 64


def test_ingestion_openapi_contract_is_typed_and_storage_opaque() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/files/uploads",
        "/api/v1/files/uploads/{upload_id}",
        "/api/v1/files/uploads/{upload_id}/retry",
        "/api/v1/files/versions/{version_id}/viewer-manifest",
        "/api/v1/files/renditions/{rendition_id}/content",
    }
    assert expected <= paths.keys()
    upload_operation = paths["/api/v1/files/uploads"]["post"]
    assert upload_operation["responses"]["202"]["content"]["application/json"]["schema"]
    assert upload_operation["responses"]["413"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/ErrorEnvelope")
    manifest_schema = paths[
        "/api/v1/files/versions/{version_id}/viewer-manifest"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert manifest_schema["$ref"].endswith("/ViewerManifest")
    serialized = json.dumps(schema).lower()
    for forbidden in ("object_key", "s3_bucket", "presigned_url", "filesystem_path"):
        assert forbidden not in serialized


def test_ingestion_upload_requires_auth_before_reading_body() -> None:
    async def anonymous() -> None:
        return None

    app.dependency_overrides[file_subject] = anonymous
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/files/uploads",
            headers={
                "X-Parent-Resource-ID": str(uuid.uuid4()),
                "X-Logical-Name": "safe",
                "X-Original-Filename": "safe.pdf",
            },
            content=b"must-not-be-ingested",
        )
    app.dependency_overrides.clear()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert "quarantine" not in response.text
