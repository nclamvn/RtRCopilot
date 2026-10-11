from functools import lru_cache

from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
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


@lru_cache(maxsize=1)
def _runtime_status_pair(
    engine: AsyncEngine,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    # Configuration only. The view shares the original pool; never dispose it.
    view = engine.execution_options(isolation_level="READ COMMITTED")
    return view, async_sessionmaker(view, expire_on_commit=False)


def _standard_status_factory(
    source: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession] | None:
    # A custom injected source must not initialize the default engine for lookup.
    if not session_factory.cache_info().currsize or not runtime_engine.cache_info().currsize:
        return None
    base = runtime_engine()
    if (
        source is not session_factory()
        or type(source) is not async_sessionmaker
        or source.class_ is not AsyncSession
        or set(source.kw) != {"bind", "autoflush", "expire_on_commit"}
        or source.kw["bind"] is not base
        or source.kw["autoflush"] is not True
        or source.kw["expire_on_commit"] is not False
        or type(base) is not AsyncEngine
        or type(base.sync_engine.dialect) is not PGDialect_asyncpg
        or base.get_execution_options()
    ):
        return None
    view, factory = _runtime_status_pair(base)
    # Reject mutated cached configuration; never silently manufacture admission.
    if (
        type(view) is not AsyncEngine
        or view.pool is not base.pool
        or view.sync_engine.dialect is not base.sync_engine.dialect
        or dict(view.get_execution_options()) != {"isolation_level": "READ COMMITTED"}
        or type(factory) is not async_sessionmaker
        or factory.class_ is not AsyncSession
        or set(factory.kw) != {"bind", "autoflush", "expire_on_commit"}
        or factory.kw["bind"] is not view
        or factory.kw["autoflush"] is not True
        or factory.kw["expire_on_commit"] is not False
    ):
        return None
    return factory


def _is_cached_runtime_factory(source: async_sessionmaker[AsyncSession]) -> bool:
    # Inspect identity only when already populated; never initialize for injection.
    return bool(session_factory.cache_info().currsize) and source is session_factory()
