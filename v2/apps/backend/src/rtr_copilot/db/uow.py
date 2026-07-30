from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.db.engine import session_factory


class MaintenanceActive(RuntimeError):
    pass


async def ensure_mutation_allowed(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock_shared(827005)"))
    enabled = await session.scalar(text(
        "SELECT enabled FROM maintenance_state WHERE singleton",
    ))
    if enabled:
        raise MaintenanceActive("maintenance_active")


class UnitOfWork:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.factory = factory or session_factory()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self.factory() as session, session.begin():
            await ensure_mutation_allowed(session)
            yield session
