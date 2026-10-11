"""Four independent R7 structural controls; NO SQL/permission/outcome proof.

The sync target and base terminal delegates are deliberate fakes. Sessions are
unbound structural objects so a non-acquired connection is never a bind oracle.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rtr_copilot.actions import request_connection as module
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.request_connection import (
    LegacyInitialRequired,
    RequestConnection,
    _OwnerConnection,
    _OwnerSession,
)
from rtr_copilot.actions.service import ActionService


class FakeSync:
    """Weakrefable structural target, never a driver or actual transaction."""

    def __init__(self) -> None:
        self.root = self.nested = self.closed = self.invalidated = False

    def in_transaction(self) -> bool:
        return self.root

    def in_nested_transaction(self) -> bool:
        return self.nested


def factory() -> Any:
    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    return async_sessionmaker(engine, expire_on_commit=False)


def retired(owner: RequestConnection) -> tuple[Any, Any, Any]:
    sync, token = FakeSync(), object()
    connection = _OwnerConnection(owner.engine, owner, generation=token, sync_connection=sync)
    owner.entered = owner.phase_active = owner.mutation_started = True
    owner.cleanup_complete = False
    owner.connection, owner.generation = connection, token
    # No real connection was acquired. Preserve exact owner/generation registration.
    session = _OwnerSession(request_owner=owner, request_generation=token)
    session.request_closed = True  # Structural successful-terminal premise only.
    owner._retain_phase(connection)
    assert owner.has_retained_lease and owner.connection is None and not owner.phase_active
    return connection, session, token


def state(owner: Any) -> tuple[Any, ...]:
    return (
        owner.connection,
        owner.session,
        owner.generation,
        owner.factory,
        owner.phase_active,
        owner.poisoned,
        owner.cleanup_complete,
        owner.terminal_task,
        owner._retained_connection,
        owner._retained_ready,
        owner._closing_retained,
        owner.mutation_started,
    )


@pytest.mark.asyncio
async def test_retained_generation_identity_never_reactivates_old_token(monkeypatch: Any) -> None:
    owner = RequestConnection(factory())
    old, old_session, token = retired(owner)
    calls: list[Any] = []

    async def close(target: Any) -> None:
        calls.append((asyncio.current_task(), target))

    monkeypatch.setattr(AsyncConnection, "close", close)
    async with owner.phase_lease() as borrowed:
        current = owner.connection
        assert current is not old and current.sync_connection is old.sync_connection
        assert owner.generation is not token and old.request_generation is token
        assert owner._retained_connection is old and not owner._retained_ready
        assert borrowed.kw["bind"] is current
        assert AsyncConnection._retrieve_proxy_for_target(old.sync_connection) is current
        for method in (old.start, old.close, old.invalidate):
            with pytest.raises(RuntimeError, match="generation_inactive"):
                await method()
        with pytest.raises(RuntimeError, match="session_inactive"):
            await old_session.close()
        assert calls == []
    assert len(calls) == 1 and calls[0][1] is current and calls[0][0].done()
    assert not owner.has_retained_lease and owner.connection is None
    assert owner.cleanup_complete and not owner.fallback_allowed  # Mutation is irreversible.


@pytest.mark.asyncio
async def test_nonfree_unknown_or_poison_transition_blocks_final(monkeypatch: Any) -> None:
    for fault in ("root", "nested", "closed", "invalidated", "poison", "unknown"):
        owner = RequestConnection(factory())
        old, _, token = retired(owner)
        if fault == "poison":
            owner.poisoned = True
        elif fault == "unknown":
            owner._retained_ready = False
        else:
            setattr(old.sync_connection, fault, True)
        with pytest.raises(RuntimeError):
            async with owner.phase_lease():
                raise AssertionError("final entered with nonfree/unknown/poison carrier")
        assert owner.connection is None and owner.generation is None and not owner.phase_active
        assert old.request_generation is token and not owner.fallback_allowed
        assert owner._retained_connection is old
    # A genuine constructor failure path, but with fake terminal base delegate.
    owner = RequestConnection(factory())
    old, _, token = retired(owner)
    primary = LegacyInitialRequired("controlled final facade constructor")
    targets: list[Any] = []

    def constructor(*args: Any, **kwargs: Any) -> Any:
        raise primary

    async def close(target: Any) -> None:
        targets.append((asyncio.current_task(), target))

    with monkeypatch.context() as scoped:
        scoped.setattr(module, "_OwnerConnection", constructor)
        scoped.setattr(AsyncConnection, "close", close)
        with pytest.raises(LegacyInitialRequired) as raised:
            async with owner.phase_lease():
                raise AssertionError("failed constructor yielded an owner")
    assert raised.value is primary and old.request_generation is token
    assert len(targets) == 1 and targets[0][1] is old and targets[0][0].done()
    assert owner.connection is None and not owner.has_retained_lease and owner.terminal_task is None
    assert owner.mutation_started and not owner.fallback_allowed


@pytest.mark.asyncio
async def test_stale_terminal_cleanup_cannot_mutate_new_generation(monkeypatch: Any) -> None:
    owner = RequestConnection(factory())
    old, old_session, token = retired(owner)
    current = _OwnerConnection(
        owner.engine, owner, generation=object(), sync_connection=old.sync_connection
    )
    owner.connection, owner.generation, owner.phase_active = (
        current,
        current.request_generation,
        True,
    )
    owner._retained_ready = False
    current_session = _OwnerSession(request_owner=owner, request_generation=owner.generation)
    calls: list[Any] = []

    async def close(target: Any) -> None:
        calls.append(target)

    monkeypatch.setattr(AsyncConnection, "close", close)
    before = state(owner)
    for child in (False, True):
        for name in ("close_connection", "release_phase", "_close_retained", "_release_retained"):

            async def probe(method: str = name) -> None:
                if method == "_release_retained":
                    await owner._release_retained(None)
                elif method == "release_phase":
                    await owner.release_phase(old, None)
                else:
                    await getattr(owner, method)(old)

            with pytest.raises(RuntimeError):
                if child:
                    await asyncio.create_task(probe())
                else:
                    await probe()
            assert state(owner) == before and calls == []
        for method in (old_session.close, old_session.invalidate):
            with pytest.raises(RuntimeError):
                if child:
                    await asyncio.create_task(method())
                else:
                    await method()
            assert state(owner) == before and calls == []

    async def terminal() -> None:
        with pytest.raises(RuntimeError):
            await owner._close_retained(old)
        with pytest.raises(RuntimeError):
            await old.close()
        with pytest.raises(RuntimeError):
            await old_session.close()
        await current.close()  # Current exact target terminal delegation remains reachable.

    await owner.join_terminal(terminal())
    assert calls == [current] and state(owner) == before
    assert old.request_generation is token and owner.session is current_session
    monkeypatch.setattr(AsyncSession, "in_transaction", lambda self: True)
    old.sync_connection.root = True

    async def scalar(target: Any, *args: Any, **kwargs: Any) -> Any:
        return 17

    monkeypatch.setattr(AsyncSession, "scalar", scalar)
    assert await current_session.scalar("structural positive only") == 17


@pytest.mark.asyncio
async def test_irreversible_mutation_and_typed_cleanup_failure_block_fallback(
    monkeypatch: Any,
) -> None:
    for submit in (False, True):
        for cancelled in (False, True):
            service = object.__new__(ExecutionService if submit else ActionService)
            service.uow = SimpleNamespace(factory=factory())
            if submit:
                monkeypatch.setattr(service, "available", lambda: None)
            else:
                monkeypatch.setattr(service, "_r0_request", lambda request: True)
            primary = LegacyInitialRequired("controlled late topology signal")
            owners: list[Any] = []
            calls: list[Any] = []
            targets: list[Any] = []

            async def attempt(
                *args: Any,
                owners: Any = owners,
                calls: Any = calls,
                targets: Any = targets,
                primary: Any = primary,
                cancelled: bool = cancelled,
                **kwargs: Any,
            ) -> Any:
                calls.append(kwargs.get("private_initial_mode", "current"))
                owner = kwargs.get("_owner")
                assert owner is not None, "legacy replay reached after mutation/cleanup uncertainty"
                owners.append(owner)
                old, _, _ = retired(owner)

                async def fault(target: Any) -> None:
                    targets.append((asyncio.current_task(), target))
                    if cancelled:
                        raise asyncio.CancelledError("controlled retained terminal")
                    raise ValueError("controlled retained terminal")

                monkeypatch.setattr(owner, "_close_retained", fault)
                with pytest.raises(RuntimeError, match="mutation_reentry"):
                    async with owner.mutation_phase():
                        raise AssertionError("second mutation entered")
                assert owner._retained_connection is old
                await owner._release_retained(primary)
                raise AssertionError("failed terminal returned success")

            monkeypatch.setattr(
                service, "_submit_attempt" if submit else "_create_plan_attempt", attempt
            )
            operation = (
                service.submit(None, None, "digest", request_id="pure-R7")
                if submit
                else service.create_plan(None, None, request_id="pure-R7")
            )
            with pytest.raises(LegacyInitialRequired) as raised:
                await operation
            owner = owners[0]
            assert raised.value is primary and calls == ["current"]
            assert owner.mutation_started and owner.poisoned and not owner.cleanup_complete
            assert not owner.fallback_allowed and not owner.has_retained_lease
            assert owner.connection is None and owner.terminal_task is None
            assert len(targets) == 1 and targets[0][0].done()
            assert owner._closing_retained is targets[0][1]
            assert any("carrier terminal work raised" in note for note in primary.__notes__)
