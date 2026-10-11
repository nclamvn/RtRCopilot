"""Two actual SQL/SDK controls; direct control scopes never fabricate HTTP."""

import asyncio
import inspect
from contextlib import AsyncExitStack

import pytest
import pytest_asyncio
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from minimal_observer import FAULT_KEYS, MinimalObserver, decoded_records
from pool_boundary_observer import PoolBoundaryObserver
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from test_action_checkout_audit_tail_integration import counts, execution_metadata
from test_action_source_batching_integration import requested
from test_pool_boundary_review_integration import clean, pending

from rtr_copilot.actions.execution import ExecutionService

pytestmark = previous.pytestmark


@pytest_asyncio.fixture(loop_scope="session")
async def factory():
    async for value in previous.factory.__wrapped__():
        yield value


@pytest_asyncio.fixture(loop_scope="session")
async def oracle(factory):
    async for value in previous.oracle.__wrapped__(factory):
        yield value


@pytest.fixture
def local_boundaries(monkeypatch, factory):
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.fixture
def execution_config(monkeypatch):
    return adversarial.execution_config.__wrapped__(monkeypatch)


def helper_state(boundary):
    targets = [(boundary, name) for name in ("begin", "finish", "request", "resource")]
    targets.append((boundary.ids, "get"))
    return [
        (
            target,
            name,
            inspect.getattr_static(target, name),
            name in vars(target),
            vars(target).get(name),
        )
        for target, name in targets
    ]


def unchanged_helpers(saved):
    for target, name, raw, present, value in saved:
        assert inspect.getattr_static(target, name) is raw
        assert (name in vars(target)) is present
        if present:
            assert vars(target)[name] is value


def finish(boundary, exposure, enabled):
    try:
        boundary.close()
    finally:
        exposure.close()
    clean(boundary.snapshot())
    packet = exposure.snapshot()
    assert set(packet["integrity"]) == set(FAULT_KEYS)
    assert not any(packet["integrity"].values()), packet["integrity"]
    rows = decoded_records(packet)
    assert bool(rows) is enabled
    assert all(row["end_ns"] >= row["start_ns"] for row in rows)


@pytest.mark.asyncio
async def test_real_r0_admission_and_submit_keep_queries_leases_and_durable_outputs(
    factory, oracle, tmp_path, local_boundaries, execution_config
):
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    engine = factory.kw["bind"]
    outcomes = []
    for enabled in (False, True):
        observation = previous.EngineProof(factory)
        with observation.watching():
            await observation.control(factory)
        boundary, exposure = PoolBoundaryObserver(engine), MinimalObserver()
        boundary.install()
        saved_helpers = helper_state(boundary)
        if enabled:
            exposure.attach_boundary(boundary)
            unchanged_helpers(saved_helpers)
        request = requested(refs)
        try:
            with (
                observation.watching(),
                boundary.scope("MB-D1-create"),
                exposure.scope("MB-D1-create"),
            ):
                plan = await actions.create_plan(actor, request, request_id="MB-D1-create")
            assert len(observation.sql) == 29
            assert [kind for kind, _ in observation.events] == ["out", "in"] * 2
            assert not observation.owned and engine.pool.checkedout() == 0
            observation.sql.clear()
            observation.events.clear()
            with (
                observation.watching(),
                boundary.scope("MB-D1-submit"),
                exposure.scope("MB-D1-submit"),
            ):
                result = await executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="MB-D1-submit"
                )
            assert len(observation.sql) == 22
            assert [kind for kind, _ in observation.events] == ["out", "in"] * 2
            assert not observation.owned and engine.pool.checkedout() == 0
            actual = await execution_metadata(oracle, plan.run_id)
            assert (await counts(oracle, actor, request.idempotency_key))[:4] == (1, 1, 1, 1)
            assert actual["execution"]["state"] == result.state == "queued"
            assert result.spent_tool_calls == 0 and result.receipts == ()
            assert actual["receipts"] == [] and actual["events"] == []
            await previous.chain(oracle)
            outcomes.append((plan.state, result.state, result.spent_tool_calls, actual["receipts"]))
        finally:
            finish(boundary, exposure, enabled)
            unchanged_helpers(saved_helpers)
        if enabled:
            rows = decoded_records(exposure.snapshot())
            assert {row["request_id"] for row in rows if row["request_id"] is not None} == {
                "MB-D1-create",
                "MB-D1-submit",
            }
            assert not {"R9.begin", "R9.finish", "R9.request", "R9.resource", "R9.WeakIds.get"} & {
                row["label"] for row in rows
            }
            assert any(row["label"].startswith("R9.recording@") for row in rows)
    assert outcomes[0] == outcomes[1]


@pytest.mark.asyncio
async def test_real_sql_error_queue_cancel_and_recovery_keep_original_outcomes(factory):
    engine = factory.kw["bind"]
    errors, cursor_count = [], []

    def original_error(context):
        errors.append(context.sqlalchemy_exception)

    def cursor(*args):
        cursor_count.append(1)  # No text, bound values or result body retained.

    event.listen(engine.sync_engine, "handle_error", original_error)
    event.listen(engine.sync_engine, "before_cursor_execute", cursor)
    try:
        for enabled in (False, True):
            boundary, exposure = PoolBoundaryObserver(engine), MinimalObserver()
            boundary.install()
            saved_helpers = helper_state(boundary)
            if enabled:
                exposure.attach_boundary(boundary)
                unchanged_helpers(saved_helpers)
            start, waiter = len(cursor_count), None
            try:
                with boundary.scope("MB-D2-error"), exposure.scope("MB-D2-error"):
                    async with factory() as session:
                        with pytest.raises(DBAPIError) as caught:
                            await session.scalar(text("SELECT 1 / 0"))
                        assert caught.value is errors[-1]
                        assert caught.value.orig.sqlstate == "22012"
                assert len(cursor_count) - start == 1
                async with AsyncExitStack() as holders:
                    for _ in range(10):
                        await holders.enter_async_context(engine.connect())
                    assert engine.pool.checkedout() == 10
                    queue = engine.sync_engine.pool._pool._queue

                    async def acquire(_boundary=boundary, _exposure=exposure):
                        with _boundary.scope("MB-D2-cancel"), _exposure.scope("MB-D2-cancel"):
                            async with engine.connect():
                                pytest.fail("cancelled saturated getter acquired")

                    waiter = asyncio.create_task(acquire())
                    future = await pending(queue, waiter)
                    waiter.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await waiter
                    assert future.cancelled() and future not in queue._getters
                    assert engine.pool.checkedout() == 10
                assert engine.pool.checkedout() == 0
                with boundary.scope("MB-D2-recovery"), exposure.scope("MB-D2-recovery"):
                    async with factory() as session:
                        assert await session.scalar(text("SELECT 67")) == 67
                assert len(cursor_count) - start == 2 and engine.pool.checkedout() == 0
            finally:
                await previous.cancel_join(waiter)
                finish(boundary, exposure, enabled)
                unchanged_helpers(saved_helpers)
    finally:
        event.remove(engine.sync_engine, "handle_error", original_error)
        event.remove(engine.sync_engine, "before_cursor_execute", cursor)
