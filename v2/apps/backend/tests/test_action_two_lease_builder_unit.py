"""Eight structural controls; fake terminal delegates are NOT SQL/return proof."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine

from rtr_copilot.actions import request_connection as module
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import RequestConnection


def pending() -> tuple[Any, Any, Any]:
    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    owner = RequestConnection(async_sessionmaker(engine))
    owner.entered = owner.phase_active = owner.mutation_started = True
    token = object()
    carrier = SimpleNamespace(
        request_generation=token,
        sync_connection=object(),
        closed=False,
        invalidated=False,
        in_transaction=lambda: False,
        in_nested_transaction=lambda: False,
    )
    session = SimpleNamespace(request_closed=True)
    owner.connection, owner.generation, owner.session = carrier, token, session
    owner._retain_phase(carrier)
    return owner, carrier, token


def state(owner: Any) -> tuple[Any, ...]:
    return (
        owner.connection,
        owner.session,
        owner.generation,
        owner.phase_active,
        owner._retained_connection,
        owner._retained_ready,
        owner._closing_retained,
        owner.poisoned,
        owner.cleanup_complete,
        owner.terminal_task,
    )


@pytest.mark.asyncio
async def test_retirement_revokes_logical_identity_without_changing_carrier_token() -> None:
    owner, carrier, token = pending()
    assert owner.connection is owner.session is owner.generation is None
    assert not owner.phase_active and not owner.cleanup_complete
    assert owner.has_retained_lease and owner._retained_ready
    assert owner._retained_connection is carrier and carrier.request_generation is token
    assert not owner.fallback_allowed and owner.mutation_started
    with pytest.raises(RuntimeError, match="generation_inactive"):
        owner.check_connection(carrier)


@pytest.mark.asyncio
async def test_stale_parent_child_and_wrong_carrier_cleanup_are_inert(monkeypatch: Any) -> None:
    owner, carrier, _ = pending()
    calls = []

    async def close(target: Any) -> None:
        calls.append(target)

    monkeypatch.setattr(AsyncConnection, "close", close)
    before = state(owner)
    for target in (carrier, object()):
        for child in (False, True):
            with pytest.raises(RuntimeError):
                operation = owner._close_retained(target)
                if child:
                    await asyncio.create_task(operation)
                else:
                    await operation
            assert state(owner) == before
    with pytest.raises(RuntimeError, match="task_mismatch"):
        await asyncio.create_task(owner._release_retained(None))
    with pytest.raises(RuntimeError, match="generation_inactive"):
        await owner.release_phase(carrier, None)
    assert calls == [] and state(owner) == before


@pytest.mark.asyncio
async def test_final_constructor_fault_joins_exact_carrier_close_without_replay(
    monkeypatch: Any,
) -> None:
    owner, carrier, token = pending()
    calls = []

    def constructor(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["sync_connection"] is carrier.sync_connection
        assert kwargs["generation"] is not token
        raise ValueError("controlled final facade construction")

    async def close(target: Any) -> None:
        calls.append((target, asyncio.current_task()))

    monkeypatch.setattr(module, "_OwnerConnection", constructor)
    monkeypatch.setattr(AsyncConnection, "close", close)
    with pytest.raises(ValueError, match="final facade construction"):
        async with owner.read_phase():
            pytest.fail("failed constructor entered a Session")
    assert len(calls) == 1 and calls[0][0] is carrier and calls[0][1].done()
    assert carrier.request_generation is token and not owner.has_retained_lease
    assert owner.connection is None and owner.terminal_task is None and not owner.fallback_allowed


@pytest.mark.asyncio
async def test_pending_nonfree_or_unavailable_carrier_never_repairs_into_final(
    monkeypatch: Any,
) -> None:
    constructed = []

    def constructor(*args: Any, **kwargs: Any) -> Any:
        constructed.append(args)
        raise AssertionError("nonfree carrier reached final construction")

    monkeypatch.setattr(module, "_OwnerConnection", constructor)
    for kind in ("root", "nested", "invalidated", "closed"):
        owner, carrier, token = pending()
        carrier.in_transaction = lambda kind=kind: kind == "root"
        carrier.in_nested_transaction = lambda kind=kind: kind == "nested"
        carrier.invalidated, carrier.closed = kind == "invalidated", kind == "closed"
        with pytest.raises(RuntimeError, match="existing_transaction|unavailable"):
            async with owner.read_phase():
                pytest.fail("invalid retained carrier entered final")
        assert owner.poisoned and not owner.cleanup_complete
        assert owner._retained_connection is carrier and carrier.request_generation is token
        assert not owner.fallback_allowed and owner.terminal_task is None
    assert constructed == []


@pytest.mark.asyncio
async def test_unjoined_session_or_uncertain_mutation_cannot_install_retention() -> None:
    for kind in ("open_session", "poison", "terminal"):
        owner, carrier, token = pending()
        owner._retained_connection, owner._retained_ready = None, False
        owner.connection, owner.generation = carrier, token
        owner.session = SimpleNamespace(request_closed=kind != "open_session")
        owner.phase_active = True
        owner.poisoned = kind == "poison"
        sentinel = object()
        if kind == "terminal":
            owner.terminal_task = sentinel
        before = state(owner)
        with pytest.raises(RuntimeError, match="retention_incomplete"):
            owner._retain_phase(carrier)
        assert state(owner) == before and not owner.has_retained_lease


@pytest.mark.asyncio
async def test_repeated_cancel_pending_cleanup_joins_one_task_and_preserves_cancel(
    monkeypatch: Any,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    owners, calls = [], []

    async def close(target: Any) -> None:
        calls.append((target, asyncio.current_task()))
        started.set()
        await release.wait()

    monkeypatch.setattr(AsyncConnection, "close", close)

    async def run() -> None:
        owner, carrier, _ = pending()
        owners.append((owner, carrier))
        await owner._release_retained(None)

    task = asyncio.create_task(run())
    try:
        await started.wait()
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and len(calls) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        owner, carrier = owners[0]
        assert calls[0][0] is carrier and calls[0][1].done()
        assert owner.terminal_task is None and owner.poisoned and not owner.fallback_allowed
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_primary_action_error_survives_close_invalidate_fault_and_no_replay(
    monkeypatch: Any,
) -> None:
    owner, carrier, _ = pending()
    primary = ActionError("source_unavailable", 403)
    calls = []

    async def close(target: Any) -> None:
        calls.append(("close", target, asyncio.current_task()))
        raise ValueError("controlled close acknowledgement")

    async def invalidate(target: Any, error: Any = None) -> None:
        calls.append(("invalidate", target, asyncio.current_task()))
        raise ValueError("controlled invalidation acknowledgement")

    monkeypatch.setattr(AsyncConnection, "close", close)
    monkeypatch.setattr(AsyncConnection, "invalidate", invalidate)
    with pytest.raises(ActionError) as raised:
        await owner._release_retained(primary)
    assert raised.value is primary and len(calls) == 2
    assert all(row[1] is carrier and row[2].done() for row in calls)
    assert calls[0][2] is calls[1][2] and owner._closing_retained is carrier
    assert owner.poisoned and not owner.cleanup_complete and not owner.fallback_allowed
    with pytest.raises(RuntimeError):
        await owner._close_retained(carrier)
    with pytest.raises(RuntimeError, match="cleanup_uncertain"):
        async with owner.read_phase():
            pytest.fail("poisoned capture replayed final")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_pending_terminal_child_has_no_query_or_final_phase_authority(
    monkeypatch: Any,
) -> None:
    owner, carrier, token = pending()

    async def close(target: Any) -> None:
        assert target is carrier
        with pytest.raises(RuntimeError, match="task_mismatch"):
            owner.check_connection_sql(carrier)
        with pytest.raises(RuntimeError, match="task_mismatch"):
            async with owner.read_phase():
                pytest.fail("terminal child entered final")
        assert carrier.request_generation is token

    monkeypatch.setattr(AsyncConnection, "close", close)
    await owner._release_retained(None)
    assert owner.cleanup_complete and owner._closing_retained is None
    assert owner.connection is owner.session is owner.generation is owner.terminal_task is None
