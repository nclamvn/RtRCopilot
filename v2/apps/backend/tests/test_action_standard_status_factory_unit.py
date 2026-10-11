"""Five fixed R15 configuration-only controls; no SQL or connection checkout."""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.db import engine as runtime
from rtr_copilot.db.uow import UnitOfWork


@pytest.fixture
def cold_runtime(monkeypatch: Any) -> Any:
    runtime.session_factory.cache_clear()
    runtime.runtime_engine.cache_clear()
    runtime._runtime_status_pair.cache_clear()
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            postgres_dsn="postgresql://synthetic:synthetic@invalid/rtr_tip054_r15_local_e1"
        ),
    )
    yield
    runtime.session_factory.cache_clear()
    runtime.runtime_engine.cache_clear()
    runtime._runtime_status_pair.cache_clear()


def test_canonical_factory_selected_without_write_factory_change(cold_runtime: Any) -> None:
    service = ExecutionService()
    source = runtime.session_factory()
    base = runtime.runtime_engine()
    selected = service._status_read_factory()
    assert selected is not None and selected is not source
    assert service._status_read_admitted() and service._status_read_factory() is selected
    assert selected.kw["bind"].pool is base.pool
    assert (
        service.uow.factory
        is service.actions.uow.factory
        is service.actions.policy.uow.factory
        is source
    )
    assert not base.get_execution_options()
    assert runtime._runtime_status_pair.cache_info().maxsize == 1
    assert runtime._runtime_status_pair.cache_info().currsize == 1


def test_unknown_injected_and_mismatched_origins_never_construct_default_cache(
    cold_runtime: Any,
) -> None:
    base = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/domain")
    injected = async_sessionmaker(base, expire_on_commit=False)
    service = ExecutionService(UnitOfWork(injected))
    assert service._status_read_factory() is None
    assert runtime.session_factory.cache_info().currsize == 0
    assert runtime.runtime_engine.cache_info().currsize == 0
    standard = ExecutionService()
    assert standard._status_read_factory() is not None
    assert service._status_read_factory() is None
    standard.actions.policy.uow = UnitOfWork(injected)
    assert standard._status_read_factory() is None


def test_cached_derived_factory_tamper_rejected_without_repair(cold_runtime: Any) -> None:
    service = ExecutionService()
    selected = service._status_read_factory()
    assert selected is not None
    selected.configure(expire_on_commit=True)
    assert service._status_read_factory() is None
    assert service._status_read_factory() is None
    assert runtime._runtime_status_pair(runtime.runtime_engine())[1] is selected
    # Restore only in this test, then prove view option mutation is rejected too.
    selected.configure(expire_on_commit=False)
    selected.configure(autoflush=1)
    assert service._status_read_factory() is None
    selected.configure(autoflush=True, expire_on_commit=0)
    assert service._status_read_factory() is None
    selected.configure(expire_on_commit=False)
    view = selected.kw["bind"]
    view.update_execution_options(isolation_level="SERIALIZABLE")
    assert service._status_read_factory() is None
    assert runtime._runtime_status_pair(runtime.runtime_engine())[0] is view
    assert not runtime.runtime_engine().get_execution_options()


def test_runtime_cache_clear_and_factory_rebind_fall_back(cold_runtime: Any) -> None:
    service = ExecutionService()
    selected = service._status_read_factory()
    assert selected is not None
    old_root = runtime.runtime_engine()
    runtime.runtime_engine.cache_clear()
    assert service._status_read_factory() is None
    assert runtime.runtime_engine.cache_info().currsize == 0
    fresh_root = runtime.runtime_engine()
    assert fresh_root is not old_root and service._status_read_factory() is None
    runtime.session_factory.cache_clear()
    fresh = ExecutionService()
    assert fresh._status_read_factory() is not selected
    fresh.uow.factory.configure(bind=old_root)
    assert fresh._status_read_factory() is None
    fresh.uow.factory.configure(bind=fresh_root)
    fresh.uow.factory.configure(bind=fresh_root.execution_options(isolation_level="READ COMMITTED"))
    assert fresh._status_read_factory() is None
    fresh.uow.factory.configure(bind=fresh_root)
    fresh_root.update_execution_options(isolation_level="READ COMMITTED")
    assert fresh._status_read_factory() is None
    fresh_root.update_execution_options(isolation_level="REPEATABLE READ")
    assert fresh._status_read_factory() is None
    assert runtime._runtime_status_pair.cache_info().currsize == 1


def test_existing_explicit_rc_original_factory_retained(cold_runtime: Any) -> None:
    base = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/domain")
    for level in ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
        factory = async_sessionmaker(
            base.execution_options(isolation_level=level), expire_on_commit=False
        )
        service = ExecutionService(UnitOfWork(factory))
        assert service._status_read_factory() is (factory if level == "READ COMMITTED" else None)
    assert runtime.session_factory.cache_info().currsize == 0
    assert runtime.runtime_engine.cache_info().currsize == 0
