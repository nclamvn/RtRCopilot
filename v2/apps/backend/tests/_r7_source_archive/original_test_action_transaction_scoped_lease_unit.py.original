"""Six independent R5 structural guards; fake delegates are NOT SQL/outcome proof."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    AsyncSessionTransaction,
    async_sessionmaker,
    create_async_engine,
)

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.request_connection import (
    LegacyInitialRequired,
    RequestConnection,
    _OwnerConnection,
    _OwnerSession,
)
from rtr_copilot.actions.service import ActionService


def factory() -> Any:
    # Construction never connects; no credentials or environment values read.
    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    return async_sessionmaker(engine, expire_on_commit=False)


def generation(owner: RequestConnection) -> tuple[Any, Any]:
    token = object()
    connection = _OwnerConnection(owner.engine, owner, generation=token)
    owner.entered = owner.phase_active = True
    owner.cleanup_complete = False
    owner.connection, owner.generation, owner.session = connection, token, None
    # Deliberately unbound structural Session: the fake Connection has not acquired SQL.
    session = _OwnerSession(request_owner=owner, request_generation=token)
    return connection, session


def transaction_flags(monkeypatch: Any) -> None:
    # Explicit fake flags solely make guard delegates reachable; never policy authority.
    monkeypatch.setattr(AsyncSession, "in_transaction", lambda self: True)
    monkeypatch.setattr(AsyncConnection, "in_transaction", lambda self: True)


@pytest.mark.asyncio
async def test_stale_connection_sql_generation_denies_before_all_base_delegates(
    monkeypatch: Any,
) -> None:
    owner = RequestConnection(factory())
    old, _ = generation(owner)
    current, _ = generation(owner)
    transaction_flags(monkeypatch)
    calls: list[Any] = []

    async def delegate(connection: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(connection)
        return 17

    for name in ("execute", "scalar", "scalars", "exec_driver_sql"):
        monkeypatch.setattr(AsyncConnection, name, delegate)
        with pytest.raises(RuntimeError, match="generation_inactive"):
            await getattr(old, name)("structural SQL placeholder")
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await asyncio.create_task(getattr(old, name)("structural child placeholder"))
        assert await getattr(current, name)("structural current placeholder") == 17
    assert calls == [current] * 4


@pytest.mark.asyncio
async def test_stale_session_and_unstarted_transaction_generation_deny_before_delegate(
    monkeypatch: Any,
) -> None:
    owner = RequestConnection(factory())
    _, old = generation(owner)
    transaction_flags(monkeypatch)
    facade = old.begin()
    _, current = generation(owner)
    calls: list[Any] = []

    async def session_delegate(session: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(session)
        return 19

    async def terminal_delegate(transaction: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(transaction)

    for name in ("execute", "scalar", "scalars", "connection"):
        monkeypatch.setattr(AsyncSession, name, session_delegate)
        with pytest.raises(RuntimeError, match="session_inactive"):
            await getattr(old, name)(*(() if name == "connection" else ("never SQL",)))
    for name in ("start", "commit", "rollback", "__aexit__"):
        monkeypatch.setattr(AsyncSessionTransaction, name, terminal_delegate)
        with pytest.raises(RuntimeError, match="session_inactive"):
            await getattr(facade, name)(*((None, None, None) if name == "__aexit__" else ()))
    assert calls == []
    assert await current.scalar("structural current placeholder") == 19
    assert calls == [current]
    state = (
        owner.connection,
        owner.session,
        owner.generation,
        owner.phase_active,
        owner.poisoned,
        owner.cleanup_complete,
        owner.terminal_task,
    )
    for name in ("close", "invalidate", "__aexit__"):
        for child in (False, True):
            operation = getattr(old, name)(*((None, None, None) if name == "__aexit__" else ()))
            with pytest.raises(RuntimeError):
                if child:
                    await asyncio.create_task(operation)
                else:
                    await operation
            assert (
                owner.connection,
                owner.session,
                owner.generation,
                owner.phase_active,
                owner.poisoned,
                owner.cleanup_complete,
                owner.terminal_task,
            ) == state
    assert calls == [current]


@pytest.mark.asyncio
async def test_terminal_child_targets_exact_live_generation_not_old_start_or_close(
    monkeypatch: Any,
) -> None:
    owner = RequestConnection(factory())
    old, old_session = generation(owner)
    current, current_session = generation(owner)
    monkeypatch.setattr(AsyncConnection, "in_transaction", lambda self: False)
    monkeypatch.setattr(AsyncConnection, "in_nested_transaction", lambda self: False)
    calls: list[Any] = []

    async def delegate(target: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(target)
        return target

    for name in ("start", "close", "invalidate"):
        monkeypatch.setattr(AsyncConnection, name, delegate)
        with pytest.raises(RuntimeError, match="generation_inactive"):
            await getattr(old, name)()
    state = (
        owner.connection,
        owner.session,
        owner.generation,
        owner.phase_active,
        owner.poisoned,
        owner.cleanup_complete,
        owner.terminal_task,
    )
    for child in (False, True):
        for name in ("release_phase", "close_connection"):
            operation = (
                owner.release_phase(old, None)
                if name == "release_phase"
                else owner.close_connection(old)
            )
            with pytest.raises(RuntimeError):
                if child:
                    await asyncio.create_task(operation)
                else:
                    await operation
            assert (
                owner.connection,
                owner.session,
                owner.generation,
                owner.phase_active,
                owner.poisoned,
                owner.cleanup_complete,
                owner.terminal_task,
            ) == state
    assert calls == []
    monkeypatch.setattr(AsyncSession, "close", delegate)
    assert await current.start() is current

    async def terminal() -> None:
        for method in (old.close, old.invalidate):
            with pytest.raises(RuntimeError, match="generation_inactive"):
                await method()
        with pytest.raises(RuntimeError, match="session_inactive"):
            await old_session.close()
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await current_session.scalar("terminal child must not query")
        with pytest.raises(RuntimeError, match="task_mismatch"):
            async with owner.read_phase():
                raise AssertionError("cleanup child entered a phase")
        await current_session.close()
        await current.close()

    await owner.join_terminal(terminal())
    assert calls == [current, current_session, current]
    assert current_session.request_closed and owner.terminal_task is None


@pytest.mark.asyncio
async def test_busy_or_poisoned_cleanup_prevents_next_physical_start(monkeypatch: Any) -> None:
    owner = RequestConnection(factory())
    owner.entered = True
    starts: list[Any] = []

    async def start(connection: Any, *args: Any, **kwargs: Any) -> Any:
        starts.append(connection)
        return connection

    monkeypatch.setattr(_OwnerConnection, "start", start)
    release = asyncio.Event()
    pending = asyncio.create_task(release.wait())
    try:
        owner.terminal_task = pending
        with pytest.raises(RuntimeError, match="cleanup_uncertain"):
            async with owner.read_phase():
                raise AssertionError("acquired during pending cleanup")
        release.set()
        await pending
        owner.terminal_task = None
        for poisoned, complete in ((True, True), (False, False)):
            owner.poisoned, owner.cleanup_complete = poisoned, complete
            with pytest.raises(RuntimeError, match="cleanup_uncertain"):
                async with owner.read_phase():
                    raise AssertionError("acquired despite uncertain cleanup")
        assert starts == [] and owner.connection is None and not owner.phase_active
    finally:
        release.set()
        await pending


@pytest.mark.asyncio
async def test_mutation_started_survives_released_state_and_blocks_both_public_replays(
    monkeypatch: Any,
) -> None:
    # Exercise actual public catch boundaries; attempts are pure delegates, not business proof.
    primary = LegacyInitialRequired("structural late initial signal")
    sentinel = object()
    for submit in (False, True):
        for started in (False, True):
            uow = SimpleNamespace(factory=factory())
            service = object.__new__(ExecutionService if submit else ActionService)
            service.uow = uow
            if submit:
                monkeypatch.setattr(service, "available", lambda: None)
            else:
                monkeypatch.setattr(service, "_r0_request", lambda request: True)
            calls: list[Any] = []
            owners: list[Any] = []

            async def attempt(
                *args: Any,
                calls: Any = calls,
                owners: Any = owners,
                started: bool = started,
                **kwargs: Any,
            ) -> Any:
                owner = kwargs.get("_owner")
                calls.append(kwargs.get("private_initial_mode", "current"))
                if owner is None:
                    return sentinel
                owners.append(owner)
                owner.mutation_started = started
                assert owner.connection is None and owner.cleanup_complete
                raise primary

            monkeypatch.setattr(
                service, "_submit_attempt" if submit else "_create_plan_attempt", attempt
            )
            operation = (
                service.submit(None, None, "digest", request_id="pure-boundary")
                if submit
                else service.create_plan(None, None, request_id="pure-boundary")
            )
            if started:
                with pytest.raises(LegacyInitialRequired) as raised:
                    await operation
                assert raised.value is primary and calls == ["current"]
            else:
                assert await operation is sentinel and calls == ["current", "legacy"]
            assert len(owners) == 1 and owners[0].mutation_started is started
            assert owners[0].fallback_allowed is not started
    owner = RequestConnection(factory())
    owner.entered = True
    owner.mutation_started = True  # Released/failed mutation lifetime is irreversible.
    starts: list[Any] = []

    async def start(connection: Any, *args: Any, **kwargs: Any) -> Any:
        starts.append(connection)
        return connection

    monkeypatch.setattr(_OwnerConnection, "start", start)
    with pytest.raises(RuntimeError):
        async with owner.mutation_phase():
            raise AssertionError("request replayed a second mutation")
    assert starts == [] and owner.mutation_started and owner.connection is None
    assert not owner.fallback_allowed


@pytest.mark.asyncio
async def test_typed_initial_signal_plus_terminal_fault_poison_cannot_legacy_replay(
    monkeypatch: Any,
) -> None:
    for submit in (False, True):
        for cancellation in (False, True):
            service = object.__new__(ExecutionService if submit else ActionService)
            service.uow = SimpleNamespace(factory=factory())
            if submit:
                monkeypatch.setattr(service, "available", lambda: None)
            else:
                monkeypatch.setattr(service, "_r0_request", lambda request: True)
            primary = LegacyInitialRequired("structural topology/clock signal")
            owners: list[Any] = []
            targets: list[Any] = []
            calls: list[Any] = []

            async def attempt(
                *args: Any,
                calls: Any = calls,
                owners: Any = owners,
                targets: Any = targets,
                primary: Any = primary,
                cancellation: bool = cancellation,
                **kwargs: Any,
            ) -> Any:
                owner = kwargs.get("_owner")
                calls.append(kwargs.get("private_initial_mode", "current"))
                assert owner is not None, "unsafe old fallback reached after cleanup fault"
                owners.append(owner)
                connection, _ = generation(owner)

                async def fail(
                    target: Any, targets: Any = targets, cancellation: bool = cancellation
                ) -> None:
                    targets.append((asyncio.current_task(), target))
                    if cancellation:
                        raise asyncio.CancelledError("controlled terminal cancellation")
                    raise ValueError("controlled terminal fault")

                monkeypatch.setattr(owner, "close_connection", fail)
                await owner.release_phase(connection, primary)
                raise AssertionError("terminal failure returned success")

            monkeypatch.setattr(
                service, "_submit_attempt" if submit else "_create_plan_attempt", attempt
            )
            operation = (
                service.submit(None, None, "digest", request_id="pure-poison")
                if submit
                else service.create_plan(None, None, request_id="pure-poison")
            )
            with pytest.raises(LegacyInitialRequired) as raised:
                await operation
            assert raised.value is primary and calls == ["current"]
            owner = owners[0]
            assert owner.poisoned and not owner.cleanup_complete and not owner.fallback_allowed
            assert (
                owner.connection is None
                and owner.generation is None
                and owner.terminal_task is None
            )
            assert len(targets) == 1 and targets[0][0].done()
            assert any("terminal work raised" in note for note in primary.__notes__)
