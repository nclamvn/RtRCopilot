"""Actual mounted HTTP boundaries with synthetic PostgreSQL/Redis identity."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.api import clients
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.infra.dependencies import DatabaseSchemaOutdated, _postgres
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(not DATABASE_DSN, reason="integration database not configured")


@pytest.mark.asyncio
@pytest.mark.parametrize("table", [
    "context_packets", "memory_entries", "capability_versions", "action_plans",
    "action_runs", "action_approvals", "action_events", "action_receipts",
])
async def test_schema_storage_probe_denies_each_missing_new_domain_table(table: str) -> None:
    """Storage presence is necessary, never an executor-readiness certificate."""
    owner_dsn = os.environ["MIGRATION_DSN"]
    assert unquote(urlsplit(owner_dsn).path.lstrip("/")).startswith("rtr_tip054_")
    engine = create_async_engine(owner_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    hidden = f"tip054_probe_hidden_{table}"
    try:
        await _postgres(get_settings())
        async with factory() as session, session.begin():
            await session.execute(text(f"ALTER TABLE {table} RENAME TO {hidden}"))
        try:
            with pytest.raises(DatabaseSchemaOutdated):
                await _postgres(get_settings())
        finally:
            async with factory() as session, session.begin():
                await session.execute(text(f"ALTER TABLE {hidden} RENAME TO {table}"))
        await _postgres(get_settings())
    finally:
        await engine.dispose()


async def cookie(factory: async_sessionmaker[Any]) -> str:
    suffix = uuid.uuid4().hex
    identity = await PostgresSubjectRepository(factory).upsert_from_claims({
        "iss": "https://tip054.shared.synthetic", "sub": suffix,
        "email": f"{suffix}@rtrobotics.com", "email_verified": True,
        "name": "Synthetic shared HTTP staff", "groups": [],
    }, {})
    subject = Subject(
        user_id=identity.user_id, issuer="https://tip054.shared.synthetic", sub=suffix,
        email=f"{suffix}@rtrobotics.com", canonical_domain="rtrobotics.com",
        security_version=identity.security_version, roles={Role.STAFF},
    )
    redis, sessions, _ = clients(get_settings())
    try:
        await sessions.sync_authority(subject)
        return await sessions.create(subject)
    finally:
        await redis.aclose()


def memory_payload() -> dict[str, Any]:
    return {
        "kind": "preference", "text": "Synthetic preference is not authority",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/context/memory",
    "/api/v1/context/packets/00000000-0000-0000-0000-000000000001",
    "/api/v1/actions/capabilities",
    "/api/v1/actions/plans/00000000-0000-0000-0000-000000000001",
])
async def test_mounted_new_routes_deny_anonymous_with_safe_request_envelope(path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers={"X-Request-ID": "shared-anonymous"})
    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "shared-anonymous"
    payload = response.json()
    assert payload["request_id"] == "shared-anonymous"
    assert isinstance(payload["error"]["code"], str)
    assert "traceback" not in response.text.lower()
    assert "postgresql" not in response.text.lower()


@pytest.mark.asyncio
async def test_actual_cookie_memory_flow_validation_and_maintenance_boundary() -> None:
    assert DATABASE_DSN
    engine = create_async_engine(DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_dsn = os.environ["MIGRATION_DSN"]
    owner_engine = create_async_engine(
        owner_dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    owner_factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    try:
        session_id = await cookie(factory)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set(get_settings().session_cookie_name, session_id)
            created = await client.post("/api/v1/context/memory", json=memory_payload())
            assert created.status_code in {200, 201}, created.text
            memory_id = created.json()["memory_id"]
            read = await client.get(f"/api/v1/context/memory/{memory_id}")
            assert read.status_code == 200
            assert read.json()["text"] == "Synthetic preference is not authority"
            # Unknown authority fields reject without echoing their arbitrary value.
            sentinel = "SYNTHETIC_DO_NOT_ECHO_54"
            invalid = await client.post("/api/v1/context/memory", json={
                **memory_payload(), "owner_subject_id": sentinel,
            }, headers={"X-Request-ID": "shared-validation"})
            assert invalid.status_code == 422
            assert invalid.json()["request_id"] == "shared-validation"
            assert sentinel not in invalid.text
            async with owner_factory() as session, session.begin():
                await session.execute(text(
                    "UPDATE maintenance_state SET enabled=true WHERE singleton",
                ))
            try:
                denied = await client.post("/api/v1/context/memory", json=memory_payload(),
                                           headers={"X-Request-ID": "shared-maintenance"})
                assert denied.status_code == 503, denied.text
                assert denied.json()["request_id"] == "shared-maintenance"
                assert "maintenance" in denied.json()["error"]["code"]
                read = await client.get(f"/api/v1/context/memory/{memory_id}")
                assert read.status_code == 200
            finally:
                async with owner_factory() as session, session.begin():
                    await session.execute(text(
                        "UPDATE maintenance_state SET enabled=false WHERE singleton",
                    ))
    finally:
        await owner_engine.dispose()
        await engine.dispose()
