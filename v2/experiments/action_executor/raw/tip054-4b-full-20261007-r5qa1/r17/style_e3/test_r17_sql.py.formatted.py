"""Exactly three new grouped SQL controls; campaign is collected separately."""

import asyncio
from contextlib import AsyncExitStack, contextmanager
from pathlib import Path

import pytest
import test_action_execution_adversarial as adversarial
import test_action_standard_status_factory_integration as controls
import test_action_status_fusion_integration as fusion
from observer import Observation
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from test_action_contracts_integration import principal
from test_standard_status_comparator import TAG, seed_receipts

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import _OwnerSession
from rtr_copilot.db import engine as runtime
from rtr_copilot.db.uow import UnitOfWork

factory = controls.factory
oracle = controls.oracle
execution_config = controls.execution_config
local_boundaries = controls.local_boundaries
pytestmark = adversarial.pytestmark


@contextmanager
def tagged(identity):
    token = TAG.set(identity)
    try:
        yield
    finally:
        TAG.reset(token)


def services(config):
    base = runtime.runtime_engine()
    assert base.url.database == "rtr_tip054_r17_local_e1"
    assert config.action_executor_operation_timeout_seconds == 0.9
    source = async_sessionmaker(base, expire_on_commit=False)
    legacy, new = ExecutionService(UnitOfWork(source)), ExecutionService()
    legacy.settings = new.settings = config
    assert legacy._status_read_factory() is None
    selected = new._status_read_factory()
    assert selected is not None and selected.kw["bind"].pool is base.pool
    assert base.pool.size() == 5 and base.pool._max_overflow == 5 and base.pool._pre_ping
    assert not base.get_execution_options()
    return base, legacy, new


@pytest.mark.asyncio
async def test_canonical_legacy_equivalence(
    factory, oracle, tmp_path: Path, execution_config, local_boundaries
):
    base, legacy, new = services(execution_config)
    observer = Observation(base)
    for n in (0, 2, 100):
        _, actor, _, _, _, view = await adversarial.submitted(factory, tmp_path, execution_config)
        await seed_receipts(factory, view.run_id, n)
        expected = await new.status(actor, view.run_id)
        before = await fusion.immutable_snapshot(oracle, view.run_id)
        for mode in ("M", "D"):
            with observer.watching(mode):
                for lane, service, sql, leases in (("legacy", legacy, 4, 3), ("new", new, 3, 1)):
                    tag = f"equivalence_{mode}_{lane}_{n}"
                    with tagged(tag):
                        value = await service.status(actor, view.run_id)
                    assert value.model_dump(mode="json") == expected.model_dump(mode="json")
                    assert len(value.receipts) == n
                    row = observer.row(tag, mode)
                    assert (
                        row["sql"],
                        row["checkout"],
                        row["checkin"],
                        row["receipt_sql"],
                        row["row_sql"],
                    ) == (sql, leases, leases, 1, 2 if lane == "legacy" else 1)
                    assert row["detail_events"] == 0 if mode == "M" else row["detail_events"] > 0
            assert (
                not observer.installed
                and not observer.aggregate.held
                and base.pool.checkedout() == 0
            )
        foreign = await principal(factory)
        with observer.watching("D"), tagged(f"foreign_{n}"):
            for service in (legacy, new):
                with pytest.raises(ActionError) as fault:
                    await service.status(foreign, view.run_id)
                assert fault.value.status == 404
        assert await fusion.immutable_snapshot(oracle, view.run_id) == before
    assert new.uow.factory is factory
    assert not observer.collector.faults and not observer.aggregate.integrity


@pytest.mark.asyncio
async def test_creation_reuse_overflow_and_isolation(factory, execution_config):
    base, _, new = services(execution_config)
    await base.dispose()
    observer = Observation(base)
    selected = new._status_read_factory()
    with observer.watching("D"):
        async with AsyncExitStack() as warm:
            for n in range(10):
                with tagged(f"warm_{n}"):
                    await warm.enter_async_context(base.connect())
            assert base.pool.checkedout() == 10
        assert base.pool.checkedout() == 0 and base.pool.checkedin() == 5
        connects = [e for e in observer.collector.events if e["kind"] == "connect_observed"]
        assert len(connects) == 10 and len({e["generation"] for e in connects}) == 10
        with tagged("reuse"):
            async with selected() as session:
                assert await session.scalar(text("SHOW transaction_isolation")) == "read committed"
            async with factory() as session:
                assert await session.scalar(text("SHOW transaction_isolation")) == "read committed"
        assert not [
            e
            for e in observer.collector.events
            if e["kind"] == "connect_observed" and e["attempt"] == "reuse"
        ]
        # Capture physical invalidation then real reconnect; no fabricated generation.
        with tagged("reconnect"):
            async with base.connect() as connection:
                await connection.invalidate()
            # FIFO can choose another idle record, so exhaust all five retained records.
            async with AsyncExitStack() as held:
                for _ in range(5):
                    await held.enter_async_context(base.connect())
    reconnect = [
        e
        for e in observer.collector.events
        if e["attempt"] == "reconnect" and e["kind"] == "connect_observed"
    ]
    assert reconnect and reconnect[0]["generation"] > max(e["generation"] for e in connects)
    callbacks = [e for e in observer.collector.events if e["kind"] == "checkin_callback"]
    assert callbacks and all(e["availability"] == "not_yet_pool_return" for e in callbacks)
    assert any(e["pool_checkedout"] > e["held_ledger"] for e in callbacks)
    assert (
        not observer.lifecycle.held and not observer.aggregate.held and base.pool.checkedout() == 0
    )
    assert (
        not observer.installed
        and not observer.collector.faults
        and not base.get_execution_options()
    )


@pytest.mark.asyncio
async def test_cancel_query_close_fault_attribution_and_restoration(
    factory, oracle, tmp_path: Path, execution_config, local_boundaries, monkeypatch
):
    base, legacy, new = services(execution_config)
    _, actor, _, _, _, view = await adversarial.submitted(factory, tmp_path, execution_config)
    before = await fusion.immutable_snapshot(oracle, view.run_id)
    observer = Observation(base)
    originals = (base.pool.connect, AsyncConnection.close, AsyncSession.close)
    async with AsyncExitStack() as held:
        for _ in range(10):
            await held.enter_async_context(base.connect())
        with observer.watching("D"):
            with tagged("acquisition_cancel"):
                task = asyncio.create_task(new.status(actor, view.run_id))
            try:
                for _ in range(100):
                    if base.pool._pool._queue._getters:
                        break
                    await asyncio.sleep(0.01)
                assert base.pool._pool._queue._getters
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            assert any(
                e["attempt"] == "acquisition_cancel"
                and e["kind"] == "acquisition_error"
                and e["error_type"] == "CancelledError"
                for e in observer.collector.events
            )

    def fault(connection, cursor, statement, parameters, *args):
        if "FROM action_execution_receipts c" in statement:
            statement = statement.replace(
                "SELECT c.receipt_id", "SELECT c.r17_absent_column,c.receipt_id"
            )
        return statement, parameters

    with observer.watching("D"):
        event.listen(base.sync_engine, "before_cursor_execute", fault, retval=True)
        try:
            with tagged("receipt_error"), pytest.raises(DBAPIError):
                await new.status(actor, view.run_id)
        finally:
            event.remove(base.sync_engine, "before_cursor_execute", fault)
        assert any(
            e["attempt"] == "receipt_error"
            and e["kind"] == "query_error"
            and e["classification"] == "receipt"
            for e in observer.collector.events
        )
        real_close = _OwnerSession.close
        original_fault = RuntimeError("r17_labelled_close_ack_fault")

        async def close_fault(session):
            await real_close(session)
            raise original_fault

        with monkeypatch.context() as scoped:
            scoped.setattr(_OwnerSession, "close", close_fault)
            with tagged("close_fault"), pytest.raises(RuntimeError) as caught:
                await new.status(actor, view.run_id)
            assert caught.value is original_fault
        assert any(
            e["attempt"] == "close_fault" and e["kind"] == "owner_terminal_join_terminal_error"
            for e in observer.collector.events
        )
    # Original legacy __aexit__ shields a close child but does not join it when
    # its service parent is cancelled. D observes; M uses only exact coroutine
    # code and same-pool ownership after service/timer completion, never a hook.
    for mode in ("D", "M"):
        ready, release = asyncio.Event(), asyncio.Event()
        real_legacy_close = AsyncSession.close
        identity = "legacy_close_cancel_" + mode

        async def slow_legacy_close(
            session,
            *args,
            identity=identity,
            ready=ready,
            release=release,
            real_legacy_close=real_legacy_close,
            **kwargs,
        ):
            if TAG.get() == identity:
                ready.set()
                await release.wait()
            return await real_legacy_close(session, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(AsyncSession, "close", slow_legacy_close)
            with observer.watching(mode):
                with tagged(identity):
                    task = asyncio.create_task(legacy.status(actor, view.run_id))
                await asyncio.wait_for(ready.wait(), 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                drain = asyncio.create_task(observer.drain(mode))
                await asyncio.sleep(0)
                drain.cancel()
                await asyncio.sleep(0)
                drain.cancel()
                assert not drain.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await drain
                row = observer.row(identity, mode)
                assert row["checkout"] == row["checkin"] >= 1
                if mode == "D":
                    assert any(
                        e["attempt"] == identity
                        and e["kind"] == "checkin_callback"
                        and e["owned_checkout"]
                        for e in observer.collector.events
                    )
                else:
                    assert row["detail_events"] == 0 and not observer.installed
                assert not observer.lifecycle.held and not observer.aggregate.held
                assert base.pool.checkedout() == 0
        assert AsyncSession.close is originals[2]
    original_legacy_fault = RuntimeError("r17_legacy_close_ack_fault")
    real_legacy_close = AsyncSession.close

    async def legacy_close_fault(session, *args, **kwargs):
        result = await real_legacy_close(session, *args, **kwargs)
        if TAG.get() == "legacy_close_fault":
            raise original_legacy_fault
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(AsyncSession, "close", legacy_close_fault)
        with observer.watching("D"), tagged("legacy_close_fault"):
            with pytest.raises(RuntimeError) as caught:
                await legacy.status(actor, view.run_id)
            assert caught.value is original_legacy_fault
            await observer.drain()
        assert any(
            e["attempt"] == "legacy_close_fault" and e["kind"] == "session_terminal_close_error"
            for e in observer.collector.events
        )
    assert (base.pool.connect, AsyncConnection.close, AsyncSession.close) == originals
    assert not observer.installed and not observer.lifecycle.held and not observer.aggregate.held
    assert (
        base.pool.checkedout() == 0
        and not observer.collector.faults
        and not observer.aggregate.integrity
    )
    assert await fusion.immutable_snapshot(oracle, view.run_id) == before
    assert await new.status(actor, view.run_id) == view
