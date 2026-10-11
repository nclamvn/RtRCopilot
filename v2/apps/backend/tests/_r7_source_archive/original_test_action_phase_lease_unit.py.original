"""Eight structural controls. Fake generations/delegates are NOT SQL authority proof."""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rtr_copilot.actions.request_connection import (
    RequestConnection,
    _OwnerConnection,
    _OwnerSession,
)


def generations() -> tuple[Any, Any, Any]:
    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    owner = RequestConnection(async_sessionmaker(engine))
    owner.entered = owner.phase_active = True
    owner.generation = object()
    old = _OwnerConnection(engine, owner, generation=owner.generation)
    owner.connection = old
    _OwnerSession(request_owner=owner, request_generation=owner.generation)
    owner.session = None
    owner.generation = object()
    current = _OwnerConnection(engine, owner, generation=owner.generation)
    owner.connection = current
    _OwnerSession(request_owner=owner, request_generation=owner.generation)
    return owner, old, current


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "scalar", "scalars", "exec_driver_sql"])
async def test_departed_connection_sql_cannot_borrow_new_generation(
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, old, current = generations()
    calls = []

    async def delegate(*args: Any, **kwargs: Any) -> int:
        calls.append(args[0])
        return 17

    monkeypatch.setattr(AsyncConnection, method, delegate)
    monkeypatch.setattr(AsyncConnection, "in_transaction", lambda self: True)
    monkeypatch.setattr(AsyncSession, "in_transaction", lambda self: True)
    with pytest.raises(RuntimeError, match="generation_inactive"):
        await getattr(old, method)("never SQL")
    assert calls == []
    assert await getattr(current, method)("fake positive delegate") == 17
    assert calls == [current] and owner.connection is current


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["start", "close", "invalidate"])
async def test_departed_connection_lifecycle_rejects_before_delegate(
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, old, current = generations()
    calls = []

    async def delegate(*args: Any, **kwargs: Any) -> None:
        calls.append(args[0])

    monkeypatch.setattr(AsyncConnection, method, delegate)
    with pytest.raises(RuntimeError, match="generation_inactive"):
        await getattr(old, method)()
    with pytest.raises(RuntimeError, match="generation_inactive"):
        await owner.release_phase(old, None)
    with pytest.raises(RuntimeError, match="generation_inactive"):
        await owner.close_connection(old)
    assert calls == [] and owner.connection is current
    assert not owner.poisoned and owner.phase_active


@pytest.mark.asyncio
async def test_uncertain_cleanup_never_enables_next_phase_or_initial_retry() -> None:
    owner, _, _ = generations()
    owner.connection = None
    owner.session = None
    owner.generation = None
    owner.phase_active = False
    owner.poisoned = True
    owner.cleanup_complete = False
    assert not owner.mutation_started and not owner.fallback_allowed
    with pytest.raises(RuntimeError, match="cleanup_uncertain"):
        owner.begin_phase()
    assert owner.connection is None and not owner.phase_active
    owner.poisoned = False
    owner.cleanup_complete = True
    owner.mutation_started = True
    with pytest.raises(RuntimeError, match="mutation_reentry"):
        async with owner.mutation_phase():
            pytest.fail("second mutation replayed")
    assert owner.connection is None and owner.mutation_started
