import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import boto3  # type: ignore[import-untyped]
from redis.asyncio import Redis

from rtr_copilot.config import Settings

Probe = Callable[[], Awaitable[None]]

REQUIRED_SCHEMA_RELATIONS: tuple[str, ...] = (
    "subjects",
    "resources",
    "records",
    "file_chunks",
    "render_jobs",
    "document_publication_outbox",
    "enterprise_domains",
    "context_packets",
    "memory_entries",
    "capability_versions",
    "action_plans",
    "action_runs",
    "action_approvals",
    "action_events",
    "action_receipts",
)


class DatabaseSchemaOutdated(RuntimeError):
    pass


async def _postgres(settings: Settings) -> None:
    conn = await asyncpg.connect(str(settings.postgres_dsn), timeout=2)
    try:
        await conn.fetchval("SELECT 1")
        version_table = await conn.fetchval(
            "SELECT to_regclass('public.alembic_version')",
        )
        if version_table is None:
            raise DatabaseSchemaOutdated
        revision = await conn.fetchval(
            "SELECT version_num FROM alembic_version LIMIT 1",
        )
        if revision != settings.expected_schema_revision:
            raise DatabaseSchemaOutdated
        missing = await conn.fetchval(
            """
            SELECT count(*) FROM unnest($1::text[]) AS required(name)
            WHERE to_regclass('public.' || required.name) IS NULL
            """,
            list(REQUIRED_SCHEMA_RELATIONS),
        )
        if missing:
            raise DatabaseSchemaOutdated
    finally:
        await conn.close()


async def _redis(settings: Settings) -> None:
    client: Redis = Redis.from_url(settings.redis_url, socket_timeout=2)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _s3(settings: Settings) -> None:
    def head() -> None:
        client: Any = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint),
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        client.head_bucket(Bucket=settings.s3_bucket)

    await asyncio.wait_for(asyncio.to_thread(head), timeout=3)


async def probe_dependencies(settings: Settings) -> dict[str, str]:
    probes: dict[str, Probe] = {
        "postgres": lambda: _postgres(settings),
        "redis": lambda: _redis(settings),
        "object_storage": lambda: _s3(settings),
    }

    async def run(name: str, probe: Probe) -> tuple[str, str]:
        try:
            await asyncio.wait_for(probe(), timeout=4)
            return name, "ready"
        except DatabaseSchemaOutdated:
            return name, "database_schema_outdated"
        except Exception:
            return name, "unavailable"

    return dict(await asyncio.gather(*(run(name, probe) for name, probe in probes.items())))
