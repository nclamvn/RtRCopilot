"""Four real SDK/SQL observer controls; not a latency or HTTP-503 simulation.

Terminal pauses are labelled controlled scheduling. Actual database errors,
pool waiters, original UOW commits and separate NullPool witnesses are retained.
"""

import asyncio
import inspect
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from pool_boundary_observer import PoolBoundaryObserver
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.pool.base import _ConnectionRecord
from sqlalchemy.util.queue import AsyncAdaptedQueue
from test_action_checkout_audit_tail_integration import counts, execution_metadata
from test_action_source_batching_integration import requested

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.request_connection import RequestConnection
from rtr_copilot.actions.service import ActionService
from rtr_copilot.db.uow import UnitOfWork

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in previous.factory.__wrapped__():
        yield value


@pytest_asyncio.fixture
async def oracle(factory: Any) -> Any:
    async for value in previous.oracle.__wrapped__(factory):
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: Any, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.fixture
def execution_config(monkeypatch: Any) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


def clean(snapshot: Any) -> None:
    integrity = snapshot["integrity"]
    expected = {
        "dropped",
        "late",
        "callback_errors",
        "unmapped_wake",
        "unweak_resource",
        "costs_dropped",
        "late_events",
        "open_events",
        "pending_getters",
        "timer_active",
        "sampler_limit",
    }
    assert set(integrity) == expected
    assert all(value == 0 for value in integrity.values()), integrity
    assert all(item["end_ns"] >= item["start_ns"] for item in snapshot["events"])
    assert not any("http_status" in item for item in snapshot["events"])


async def pending(queue: Any, task: Any) -> Any:
    """Observe the actual installed Future, not a fabricated readiness event."""
    async with asyncio.timeout(5):
        while not any(getattr(task, "_fut_waiter", None) is item for item in queue._getters):
            assert not task.done()
            await asyncio.sleep(0)
    return next(item for item in queue._getters if getattr(task, "_fut_waiter", None) is item)


def descriptors(engine: Any) -> list[tuple[Any, str, bool, Any]]:
    targets = [
        (engine.sync_engine.pool, "connect"),
        (engine.sync_engine.pool, "_do_get"),
        (engine.sync_engine.pool, "_create_connection"),
        (AsyncAdaptedQueue, "get"),
        (AsyncAdaptedQueue, "await_"),
        (_ConnectionRecord, "get_connection"),
        (asyncio.Queue, "get"),
        (asyncio.Queue, "_wakeup_next"),
        (AsyncSession, "close"),
        (AsyncConnection, "close"),
        (RequestConnection, "join_terminal"),
    ]
    return [
        (target, name, name in vars(target), inspect.getattr_static(target, name))
        for target, name in targets
    ]


def restored(before: Any) -> None:
    for target, name, present, raw in before:
        assert (name in vars(target)) is present
        assert inspect.getattr_static(target, name) is raw


@pytest.mark.asyncio
async def test_real_queue_release_and_pre_ping_preserve_delegation(factory: Any) -> None:
    engine = factory.kw["bind"]
    probe = PoolBoundaryObserver(engine)
    before = descriptors(engine)
    observation = previous.EngineProof(factory)
    waiter = None
    try:
        async with AsyncExitStack() as holders:
            connections = [await holders.enter_async_context(engine.connect()) for _ in range(10)]
            assert engine.pool.checkedout() == 10
            assert engine.pool.size() == 5 and engine.pool._max_overflow == 5
            queue = engine.sync_engine.pool._pool._queue
            probe.install()

            async def query() -> Any:
                observation.tasks.add(asyncio.current_task())
                with probe.scope("real-queue-consumer"):
                    async with engine.connect() as connection:
                        assert await connection.scalar(text("SELECT 17")) == 17
                        assert (await connection.execute(text("SELECT 29"))).scalar_one() == 29
                        return "original-result"

            with observation.watching():
                waiter = asyncio.create_task(query())
                future = await pending(queue, waiter)
                assert not future.done() and not waiter.done()
                with probe.scope("real-queue-producer"):
                    await connections[0].close()
                assert await asyncio.wait_for(waiter, 5) == "original-result"
                assert future.done() and not future.cancelled()
                assert len(observation.sql) == 2
                assert [kind for kind, _ in observation.events] == ["out", "in"]
                assert not observation.owned
            probe.close()
            snapshot = probe.snapshot()
            clean(snapshot)
            events = snapshot["events"]
            wake = next(
                item
                for item in events
                if item["name"] == "queue.wake_ready" and item["future_id"] == probe.ids.get(future)
            )
            getter = next(item for item in events if item["span_id"] == wake["getter_span_id"])
            assert wake["mapping"] == "unique" and wake["future_ready"]
            assert wake["getter_task_id"] == probe.ids.get(waiter) == getter["task_id"]
            assert wake["task_id"] != wake["getter_task_id"]
            assert wake["getter_request_id"] == "real-queue-consumer"
            assert wake["request_id"] == "real-queue-producer"
            assert "reserved_record_id" not in wake
            assert getter["result_resource_id"] is not None and getter["error_type"] is None
            pings = [item for item in events if item["name"] == "adapter._async_ping"]
            assert len(pings) == 1 and pings[0]["error_type"] is None
            # The genuine driver ping is not an extra cursor SELECT in the two above.
            assert len(observation.sql) == 2
        assert engine.pool.checkedout() == 0
        restored(before)
    finally:
        await previous.cancel_join(waiter)
        probe.close()


@pytest.mark.asyncio
async def test_real_sql_error_and_queued_cancel_preserve_outcomes(factory: Any) -> None:
    engine = factory.kw["bind"]
    failures: list[Any] = []
    sql: list[str] = []

    def error(context: Any) -> None:
        failures.append(context.sqlalchemy_exception)

    def statement(*args: Any) -> None:
        sql.append(args[2])

    event.listen(engine.sync_engine, "handle_error", error)
    event.listen(engine.sync_engine, "before_cursor_execute", statement)
    try:
        for enabled in (False, True):
            probe = PoolBoundaryObserver(engine)
            if enabled:
                probe.install()
            start = len(sql)
            try:
                with probe.scope("real-error-control"):
                    async with factory() as session:
                        with pytest.raises(DBAPIError) as caught:
                            await session.scalar(text("SELECT 1 / 0"))
                        assert caught.value is failures[-1]
                        assert caught.value.orig.sqlstate == "22012"
                assert len(sql) - start == 1
                waiter = None
                try:
                    async with AsyncExitStack() as holders:
                        for _ in range(10):
                            await holders.enter_async_context(engine.connect())
                        assert engine.pool.checkedout() == 10
                        queue = engine.sync_engine.pool._pool._queue

                        async def acquire(_probe: Any = probe) -> None:
                            with _probe.scope("real-cancelled-getter"):
                                async with engine.connect():
                                    pytest.fail("cancelled saturated getter acquired a slot")

                        waiter = asyncio.create_task(acquire())
                        future = await pending(queue, waiter)
                        waiter.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await waiter
                        assert future.cancelled() and future not in queue._getters
                        assert engine.pool.checkedout() == 10
                finally:
                    await previous.cancel_join(waiter)
                assert engine.pool.checkedout() == 0
                with probe.scope("real-recovery-control"):
                    async with factory() as session:
                        assert await session.scalar(text("SELECT 19")) == 19
                assert len(sql) - start == 2 and engine.pool.checkedout() == 0
            finally:
                probe.close()
            clean(probe.snapshot())
            if enabled:
                cancelled = [
                    item
                    for item in probe.snapshot()["events"]
                    if item["name"] == "queue.get" and item["request_id"] == "real-cancelled-getter"
                ]
                assert len(cancelled) == 1 and cancelled[0]["error_type"] == "CancelledError"
    finally:
        event.remove(engine.sync_engine, "handle_error", error)
        event.remove(engine.sync_engine, "before_cursor_execute", statement)


@pytest.mark.asyncio
async def test_real_committed_mutation_repeated_cancel_joins_captured_cleanup(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="PBT-cleanup-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    real_mutation, real_close = RequestConnection.mutation_phase, AsyncSession.close
    real_view = executor._view
    closing, release = asyncio.Event(), asyncio.Event()
    sessions: list[Any] = []
    owners: list[Any] = []
    close_tasks: list[Any] = []
    final: list[Any] = []

    @asynccontextmanager
    async def mutation(owner: Any) -> Any:
        owners.append(owner)
        async with real_mutation(owner) as session:
            sessions.append(session)
            yield session

    async def close(session: Any) -> None:
        if sessions and session is sessions[0]:
            close_tasks.append(asyncio.current_task())
            closing.set()
            await release.wait()  # Controlled terminal scheduling, NOT a SQL wait.
        await real_close(session)

    async def view(*args: Any, **kwargs: Any) -> Any:
        final.append(True)
        return await real_view(*args, **kwargs)

    monkeypatch.setattr(RequestConnection, "mutation_phase", mutation)
    monkeypatch.setattr(AsyncSession, "close", close)
    monkeypatch.setattr(executor, "_view", view)
    probe = PoolBoundaryObserver(factory.kw["bind"])
    probe.install()
    task = None
    before = None

    async def run() -> Any:
        with probe.scope("real-committed-cleanup-control"):
            return await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="PBT-real-committed-cancel"
            )

    try:
        task = asyncio.create_task(run())
        await asyncio.wait_for(closing.wait(), 5)
        before = await execution_metadata(oracle, plan.run_id)
        assert before["execution"]["state"] == "queued"
        await previous.chain(oracle)
        assert len(close_tasks) == 1 and close_tasks[0] is owners[0].terminal_task
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not final and len(close_tasks) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert close_tasks[0].done() and not final
        assert owners[0].mutation_started and owners[0].poisoned
        assert not owners[0].fallback_allowed and owners[0].terminal_task is None
        assert factory.kw["bind"].pool.checkedout() == 0
        assert await execution_metadata(oracle, plan.run_id) == before
        with pytest.raises(RuntimeError):
            await sessions[0].scalar(text("SELECT 31"))
    finally:
        release.set()
        await previous.cancel_join(task)
        probe.close()
    snapshot = probe.snapshot()
    clean(snapshot)
    closes = [
        item
        for item in snapshot["events"]
        if item["name"] == "AsyncSession.close"
        and item["resource_id"] == probe.ids.get(sessions[0])
    ]
    assert len(closes) == 1 and closes[0]["task_id"] == probe.ids.get(close_tasks[0])
    assert closes[0]["task_id"] != probe.ids.get(task)
    assert closes[0]["owner_task_id"] == probe.ids.get(task)
    assert closes[0]["terminal_task_id"] == probe.ids.get(close_tasks[0])
    joins = [
        item
        for item in snapshot["events"]
        if item["name"] == "owner.join_terminal" and item["error_type"] == "CancelledError"
    ]
    assert joins and closes[0]["span_id"] in range(len(snapshot["events"]))
    assert any(item["span_id"] in closes[0]["parent_ids"] for item in joins)
    cleanup = [item for item in snapshot["events"] if item["name"] == "owner.close_connection"]
    assert cleanup and all(item["captured_resource_id"] is not None for item in cleanup)
    monkeypatch.setattr(executor, "_view", real_view)
    await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="PBT-reconcile")
    assert await execution_metadata(oracle, plan.run_id) == before
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_real_action_shapes_and_audit_survive_observer_on_off(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    other = ExecutionService(UnitOfWork(oracle), actions=ActionService(UnitOfWork(oracle)))
    other.settings = execution_config
    engine = factory.kw["bind"]
    before = descriptors(engine)
    states: list[Any] = []
    real_view = executor._view
    for enabled in (False, True):
        request = requested(refs)
        probe = PoolBoundaryObserver(engine)
        observation = previous.EngineProof(factory)
        if enabled:
            probe.install()
        try:
            with observation.watching():
                await observation.control(factory)
                with probe.scope("real-admission-control"):
                    plan = await actions.create_plan(actor, request, request_id="PBT-real-plan")
            assert len(observation.sql) == 29
            assert [kind for kind, _ in observation.events] == ["out", "in"] * 2
            assert not observation.owned and observation.maxheld == 1
            # Cumulative create-audit count is intentionally not reset between modes.
            assert (await counts(oracle, actor, request.idempotency_key))[:4] == (1, 1, 1, 1)
            cancelled: list[Any] = []

            async def view(
                run_id: Any,
                *,
                _owner: Any = None,
                _actual: Any = real_view,
                _cancelled: Any = cancelled,
            ) -> Any:
                assert _owner.has_retained_lease and _owner.connection is None
                assert (await execution_metadata(oracle, run_id))["execution"]["state"] == "queued"
                _cancelled.append(await asyncio.create_task(other.cancel(actor, run_id)))
                return await _actual(run_id, _owner=_owner)

            monkeypatch.setattr(executor, "_view", view)
            observation.sql.clear()
            observation.events.clear()
            observation.maxheld = 0
            with observation.watching(), probe.scope("real-submit-control"):
                result = await executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="PBT-real-submit"
                )
            assert len(observation.sql) == 22
            assert [kind for kind, _ in observation.events] == ["out", "in"] * 2
            assert not observation.owned and observation.maxheld == 1
            assert result == cancelled[0] and result.state == "cancelled"
            assert (
                result.cancel_requested and result.spent_tool_calls == 0 and result.receipts == ()
            )
            actual = await execution_metadata(oracle, plan.run_id)
            assert actual["execution"]["state"] == "cancelled"
            states.append(
                (
                    result.state,
                    result.cancel_requested,
                    result.spent_tool_calls,
                    len(actual["receipts"]),
                    len(actual["events"]),
                )
            )
            await previous.chain(oracle)
        finally:
            monkeypatch.setattr(executor, "_view", real_view)
            probe.close()
        clean(probe.snapshot())
        restored(before)
        if enabled:
            assert any(
                item["name"] == "adapter._commit_and_discard" for item in probe.snapshot()["events"]
            )
    assert states[0] == states[1] and engine.pool.checkedout() == 0
