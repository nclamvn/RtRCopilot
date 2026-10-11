"""Six real SDK controls; no worker/provider and no fabricated HTTP outcome."""

import asyncio
from contextlib import AsyncExitStack, contextmanager

import pytest
import pytest_asyncio
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from pool_boundary_observer import PoolBoundaryObserver
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from test_action_checkout_audit_tail_integration import counts
from test_action_source_batching_integration import requested

from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import RequestConnection

pytestmark = previous.pytestmark


@pytest_asyncio.fixture
async def factory():
    async for value in previous.factory.__wrapped__():
        yield value


@pytest_asyncio.fixture
async def oracle(factory):
    async for value in previous.oracle.__wrapped__(factory):
        yield value


@pytest.fixture
def local_boundaries(monkeypatch, factory):
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


@contextmanager
def cursors(engine):
    calls = []

    def before(connection, cursor, statement, parameters, context, executemany):
        # Count only. Never retain statement text, parameters or result bodies.
        calls.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield calls
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


def sealed(probe):
    probe.close()
    integrity = probe.snapshot()["integrity"]
    assert len(integrity) == 11 and not any(integrity.values()), integrity


@pytest.mark.asyncio
async def test_real_nonblocking_empty_overflow_and_returned_records(factory):
    engine = factory.kw["bind"]
    probe = PoolBoundaryObserver(engine)
    probe.install()
    try:
        with probe.scope("S01"), cursors(engine) as sql:
            async with AsyncExitStack() as stack:
                connections = [await stack.enter_async_context(engine.connect()) for _ in range(6)]
                assert engine.pool.checkedout() == 6
                assert len({id(item.sync_connection) for item in connections}) == 6
            assert engine.pool.checkedout() == 0 and len(sql) == 0
        events = probe.snapshot()["events"]
        assert sum(item["name"] == "pool._create_connection" for item in events) == 6
        assert any(
            item["name"] == "adapter_queue.get" and item["error_type"] == "Empty" for item in events
        )
        assert all(item["end_ns"] is not None for item in events)
    finally:
        sealed(probe)


@pytest.mark.asyncio
async def test_original_uow_rollback_and_captured_join(factory):
    engine = factory.kw["bind"]
    probe, failure = PoolBoundaryObserver(engine), ValueError("controlled original failure")
    probe.install()
    try:
        with probe.scope("S02"), pytest.raises(ValueError) as caught:
            async with RequestConnection(factory) as owner:
                async with owner.read_phase() as session:
                    assert await session.scalar(text("SELECT 31")) == 31
                async with owner.mutation_phase() as session:
                    assert await session.scalar(text("SELECT 37")) == 37
                    raise failure
        assert caught.value is failure and engine.pool.checkedout() == 0
        events = probe.snapshot()["events"]
        joins = [item for item in events if item["name"] == "owner.join_terminal"]
        closes = [item for item in events if item["name"] == "AsyncSession.close"]
        assert joins and closes
        assert all(item["terminal_task_id"] == item["task_id"] for item in closes)
        assert all(item["task_id"] != item["owner_task_id"] for item in closes)
        assert any(item["name"] == "adapter._rollback_and_discard" for item in events)
        assert all(item["end_ns"] is not None for item in events)
    finally:
        sealed(probe)


@pytest.mark.asyncio
async def test_warmed_actual_ping_on_off_and_unchanged_cursor_count(factory):
    engine = factory.kw["bind"]
    async with engine.connect():
        pass
    with cursors(engine) as off:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 41")) == 41
    probe = PoolBoundaryObserver(engine)
    probe.install()
    try:
        with probe.scope("S03"), cursors(engine) as on:
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT 41")) == 41
        assert len(on) == len(off) == 1
        ping = [item for item in probe.events if item["name"] == "adapter._async_ping"]
        assert len(ping) == 1 and ping[0]["error_type"] is None
        assert ping[0]["end_ns"] > ping[0]["start_ns"]
        assert engine.pool.checkedout() == 0
    finally:
        sealed(probe)


@pytest.mark.asyncio
async def test_real_terminal_cancel_is_joined_before_pool_return(factory, monkeypatch):
    engine = factory.kw["bind"]
    entered, release = asyncio.Event(), asyncio.Event()
    original_close = AsyncSession.close

    async def close(session):
        entered.set()
        await release.wait()
        return await original_close(session)

    monkeypatch.setattr(AsyncSession, "close", close)
    probe = PoolBoundaryObserver(engine)
    probe.install()

    async def operation():
        with probe.scope("S04"):
            async with RequestConnection(factory) as owner:
                async with owner.read_phase() as session:
                    assert await session.scalar(text("SELECT 43")) == 43

    task = None
    try:
        task = asyncio.create_task(operation())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and engine.pool.checkedout() == 1
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine.pool.checkedout() == 0
        events = probe.snapshot()["events"]
        assert any(
            item["name"] == "owner.join_terminal" and item["error_type"] == "CancelledError"
            for item in events
        )
        assert all(item["end_ns"] is not None for item in events)
        async with factory() as session:
            assert await session.scalar(text("SELECT 47")) == 47
        assert engine.pool.checkedout() == 0
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        sealed(probe)


@pytest.mark.asyncio
async def test_foreign_engine_is_unobserved_and_descriptors_restore(factory):
    engine = factory.kw["bind"]
    foreign = create_async_engine(engine.url, poolclass=NullPool)
    raw = vars(asyncio.Queue)["_wakeup_next"]
    pool_keys = set(vars(engine.sync_engine.pool))
    probe = PoolBoundaryObserver(engine)
    probe.install()
    try:
        with probe.scope("S05"):
            async with foreign.connect() as connection:
                assert await connection.scalar(text("SELECT 53")) == 53
        assert probe.events == []
    finally:
        sealed(probe)
        await foreign.dispose()
    assert vars(asyncio.Queue)["_wakeup_next"] is raw
    assert set(vars(engine.sync_engine.pool)) == pool_keys
    with probe.scope("S05-after"):
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 59")) == 59
    assert probe.events == [] and engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_real_source_denial_keeps_guard_and_no_execution(
    factory, oracle, tmp_path, local_boundaries
):
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    await adversarial.deny(factory, refs[0], actor)
    before = await counts(oracle, actor, request.idempotency_key)
    with cursors(factory.kw["bind"]) as off, pytest.raises(ActionError) as off_error:
        await actions.create_plan(actor, request, request_id="S06-off")
    probe = PoolBoundaryObserver(factory.kw["bind"])
    probe.install()
    try:
        with (
            probe.scope("S06"),
            cursors(factory.kw["bind"]) as on,
            pytest.raises(ActionError) as on_error,
        ):
            await actions.create_plan(actor, request, request_id="S06-on")
        assert on_error.value.code == off_error.value.code
        assert len(on) == len(off) and len(on) > 0
        assert await counts(oracle, actor, request.idempotency_key) == before
        assert factory.kw["bind"].pool.checkedout() == 0
        assert probe.events and not probe.snapshot()["integrity"]["open_events"]
        await previous.chain(oracle)
    finally:
        sealed(probe)
