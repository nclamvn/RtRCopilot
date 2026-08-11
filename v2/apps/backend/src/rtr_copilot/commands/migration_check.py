import asyncio

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.engine import session_factory
from rtr_copilot.infra.dependencies import REQUIRED_SCHEMA_RELATIONS


async def check() -> int:
    expected = get_settings().expected_schema_revision
    async with session_factory()() as session:
        actual = await session.scalar(
            text("SELECT version_num FROM alembic_version LIMIT 1"),
        )
    if actual != expected:
        print(f"database_schema_outdated expected={expected} actual={actual}")
        return 1
    async with session_factory()() as session:
        missing = [
            relation
            for relation in REQUIRED_SCHEMA_RELATIONS
            if await session.scalar(
                text("SELECT to_regclass(:relation) IS NULL"),
                {"relation": f"public.{relation}"},
            )
        ]
    if missing:
        print(
            "database_schema_drift "
            f"revision={actual} missing={','.join(missing)}",
        )
        return 1
    print(
        f"database_schema_ready revision={actual} "
        f"relations={len(REQUIRED_SCHEMA_RELATIONS)}",
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(check()))


if __name__ == "__main__":
    main()
