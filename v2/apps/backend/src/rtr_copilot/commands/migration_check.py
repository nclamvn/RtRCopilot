import asyncio

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.engine import session_factory


async def check() -> int:
    expected = get_settings().expected_schema_revision
    async with session_factory()() as session:
        actual = await session.scalar(
            text("SELECT version_num FROM alembic_version LIMIT 1"),
        )
    if actual != expected:
        print(f"database_schema_outdated expected={expected} actual={actual}")
        return 1
    print(f"database_schema_ready revision={actual}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(check()))


if __name__ == "__main__":
    main()
