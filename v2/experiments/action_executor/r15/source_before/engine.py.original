from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rtr_copilot.config import get_settings


def async_dsn(value: object) -> str:
    return str(value).replace("postgresql://", "postgresql+asyncpg://", 1)


@lru_cache
def runtime_engine() -> AsyncEngine:
    return create_async_engine(
        async_dsn(get_settings().postgres_dsn),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


@lru_cache
def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(runtime_engine(), expire_on_commit=False)
