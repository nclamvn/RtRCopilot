"""Private lifecycle controls; fake delegates here are NOT SQL/permission proof."""

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

from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import (
    LegacyInitialRequired,
    RequestConnection,
    _OwnerSession,
)


def control() -> tuple[RequestConnection, _OwnerSession]:
    # Engine construction never connects. Deliberately fake transaction flags.
    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    owner = RequestConnection(async_sessionmaker(engine, expire_on_commit=False))
    owner.entered = owner.phase_active = True
    session = _OwnerSession(request_owner=owner)
    owner.connection = SimpleNamespace(  # type: ignore[assignment]
        in_transaction=lambda: False,
        in_nested_transaction=lambda: False,
        invalidated=False,
        closed=False,
    )
    return owner, session


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "scalar", "scalars", "connection"])
async def test_already_yielded_session_rejects_child_before_delegate(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    owner, session = control()
    calls = []

    async def delegate(*args: Any, **kwargs: Any) -> Any:
        calls.append(method)
        return 17

    monkeypatch.setattr(AsyncSession, method, delegate)
    with pytest.raises(RuntimeError, match="task_mismatch"):
        await asyncio.create_task(
            getattr(session, method)(*(() if method == "connection" else ("never SQL",)))
        )
    assert calls == []
    assert (
        await getattr(session, method)(*(() if method == "connection" else ("unit delegate",)))
        == 17
    )
    with pytest.raises(RuntimeError, match="binding_options_unsupported"):
        await getattr(session, method)(bind_arguments={"bind": object()})
    with pytest.raises(RuntimeError, match="binding_options_unsupported"):
        await getattr(session, method)(execution_options={"isolation_level": "AUTOCOMMIT"})
    assert calls == [method]
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "scalar", "scalars", "exec_driver_sql"])
async def test_connection_child_rejects_before_delegate(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    owner, session = control()
    from rtr_copilot.actions.request_connection import _OwnerConnection

    engine = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/unused")
    connection = _OwnerConnection(engine, owner)
    calls = []

    async def delegate(*args: Any, **kwargs: Any) -> Any:
        calls.append(method)

    monkeypatch.setattr(AsyncConnection, method, delegate)
    with pytest.raises(RuntimeError, match="task_mismatch"):
        await asyncio.create_task(getattr(connection, method)("never SQL"))
    assert calls == []
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
async def test_child_phase_and_nested_owner_phase_reject_before_session_creation() -> None:
    owner, session = control()

    async def enter() -> None:
        async with owner.read_phase():
            pytest.fail("child borrowed a phase")

    with pytest.raises(RuntimeError, match="task_mismatch"):
        await asyncio.create_task(enter())
    with pytest.raises(RuntimeError, match="phase_reentry"):
        async with owner.mutation_phase():
            pytest.fail("nested phase entered")
    assert owner.session is session
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["root", "nested", "invalidated", "closed"])
async def test_nonfree_connection_is_not_committed_or_repaired(state: str) -> None:
    owner, session = control()
    owner.phase_active = False
    owner.session = None
    owner.connection = SimpleNamespace(  # type: ignore[assignment]
        in_transaction=lambda: state == "root",
        in_nested_transaction=lambda: state == "nested",
        invalidated=state == "invalidated",
        closed=state == "closed",
    )
    with pytest.raises(RuntimeError, match="existing_transaction|unavailable"):
        owner.begin_phase()
    assert owner.phase_active is False
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
async def test_closed_session_cannot_be_reused_as_permission_or_connection() -> None:
    owner, session = control()
    await owner.join_terminal(session.close())
    with pytest.raises(RuntimeError, match="session_inactive"):
        await session.scalar("never SQL")


@pytest.mark.asyncio
async def test_connection_cannot_start_an_external_root_for_session_to_join() -> None:
    owner, session = control()
    with pytest.raises(RuntimeError, match="transactions_are_session_owned"):
        owner.check_connection_sql()
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
async def test_repeated_cancellation_joins_one_terminal_task_and_propagates() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    owners = []

    async def run() -> None:
        owner, session = control()
        owners.append(owner)

        async def finish() -> None:
            calls.append(asyncio.current_task())
            started.set()
            await release.wait()
            await session.close()

        await owner.join_terminal(finish())

    task = asyncio.create_task(run())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and len(calls) == 1
    assert owners[0].terminal_task is calls[0]
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls[0].done() and owners[0].terminal_task is None


@pytest.mark.asyncio
async def test_cleanup_child_has_no_query_or_phase_authority() -> None:
    owner, session = control()

    async def finish() -> None:
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await session.scalar("never SQL")
        with pytest.raises(RuntimeError, match="task_mismatch"):
            async with owner.read_phase():
                pytest.fail("cleanup child borrowed")
        await session.close()

    await owner.join_terminal(finish())
    assert session.request_closed and owner.terminal_task is None


@pytest.mark.asyncio
async def test_terminal_error_is_not_business_success() -> None:
    owner, session = control()

    async def fail() -> None:
        raise ValueError("controlled terminal fault")

    with pytest.raises(ValueError, match="terminal fault"):
        await owner.join_terminal(fail())
    assert owner.terminal_task is None
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
async def test_unknown_external_bind_uses_explicit_old_path_signal() -> None:
    with pytest.raises(LegacyInitialRequired):
        RequestConnection(async_sessionmaker(bind=None))


@pytest.mark.asyncio
async def test_terminal_child_cannot_create_another_terminal_task() -> None:
    owner, session = control()

    async def nested() -> None:
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await owner.join_terminal(asyncio.sleep(0))
        await session.close()

    await owner.join_terminal(nested())
    assert owner.terminal_task is None


@pytest.mark.asyncio
async def test_child_cannot_manufacture_or_use_parent_terminal_facade() -> None:
    owner, session = control()
    facade = session.begin()

    async def child() -> None:
        with pytest.raises(RuntimeError):
            session.begin()
        with pytest.raises(RuntimeError):
            session.begin_nested()
        with pytest.raises(RuntimeError):
            session.get_transaction()
        with pytest.raises(RuntimeError):
            session.get_nested_transaction()
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await facade.commit()
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await facade.rollback()
        with pytest.raises(RuntimeError, match="task_mismatch"):
            await facade.start()

    await asyncio.create_task(child())
    assert not session.in_transaction()
    await owner.join_terminal(session.close())


@pytest.mark.asyncio
async def test_parent_cannot_reuse_old_transaction_facade_in_a_later_phase() -> None:
    owner, session = control()
    facade = session.begin()
    await owner.join_terminal(session.close())
    owner.session = None
    with pytest.raises(RuntimeError, match="session_inactive"):
        await facade.commit()
    with pytest.raises(RuntimeError, match="session_inactive"):
        await facade.rollback()


@pytest.mark.asyncio
async def test_cancellation_precedes_terminal_failure_without_detaching_work() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    owners = []

    async def run() -> None:
        owner, session = control()
        owners.append(owner)

        async def fail() -> None:
            entered.set()
            await release.wait()
            await session.close()
            raise ValueError("controlled close acknowledgement failure")

        await owner.join_terminal(fail())

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    cleanup = owners[0].terminal_task
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleanup is not None and cleanup.done() and owners[0].terminal_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["session", "owner"])
@pytest.mark.parametrize("primary_kind", ["cancel", "action"])
async def test_existing_primary_failure_survives_joined_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    primary_kind: str,
) -> None:
    owner, session = control()
    primary = (
        asyncio.CancelledError("original request cancellation")
        if primary_kind == "cancel"
        else ActionError("source_unavailable", 403)
    )
    calls = []

    async def fail() -> None:
        calls.append(asyncio.current_task())
        raise ValueError("controlled cleanup acknowledgement failure")

    with monkeypatch.context() as scoped:
        target = session if surface == "session" else owner
        scoped.setattr(target, "close" if surface == "session" else "close_connection", fail)
        with pytest.raises(type(primary)) as raised:
            await target.__aexit__(type(primary), primary, None)
        assert raised.value is primary
    assert len(calls) == 1 and calls[0].done() and owner.terminal_task is None
    assert any("terminal work raised ValueError" in note for note in primary.__notes__)
    await owner.join_terminal(session.close())
