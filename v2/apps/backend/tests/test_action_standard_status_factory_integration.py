"""Three finite R15 canonical-origin controls; R14 evidence/tests stay immutable."""

import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_execution_adversarial as adversarial
import test_action_status_fusion_integration as r14
import test_action_transaction_scoped_lease_integration as previous
from sqlalchemy import text
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from test_action_contracts_integration import deny, principal

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.db import engine as runtime

pytestmark = adversarial.pytestmark


@pytest_asyncio.fixture(loop_scope="session")
async def factory() -> Any:
    runtime.session_factory.cache_clear()
    runtime.runtime_engine.cache_clear()
    runtime._runtime_status_pair.cache_clear()
    factory = runtime.session_factory()
    try:
        yield factory
    finally:
        if runtime.runtime_engine.cache_info().currsize:
            base = runtime.runtime_engine()
            assert base.pool.checkedout() == 0
            await base.dispose()
        runtime.session_factory.cache_clear()
        runtime.runtime_engine.cache_clear()
        runtime._runtime_status_pair.cache_clear()


@pytest_asyncio.fixture(loop_scope="session")
async def oracle(factory: Any) -> Any:
    async for value in previous.oracle.__wrapped__(factory):
        yield value


@pytest.fixture
def execution_config(monkeypatch: Any) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


@pytest.fixture
def local_boundaries(monkeypatch: Any, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


async def submitted(factory: Any, tmp_path: Path, configured: Any) -> Any:
    item = await adversarial.submitted(factory, tmp_path, configured)
    assert item[0]._status_read_factory() is not factory
    assert item[0]._status_read_admitted()
    return item


@pytest.mark.asyncio
async def test_runtime_status_private_pool_and_reset_isolation(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    executor, actor, _, _, _, view = await submitted(factory, tmp_path, execution_config)
    base = runtime.runtime_engine()
    selected = executor._status_read_factory()
    assert selected is not None and selected.kw["bind"].pool is base.pool
    async with factory() as session:
        initial_pid, initial = (
            await session.execute(
                text("SELECT pg_backend_pid(),current_setting('transaction_isolation')")
            )
        ).one()
    levels: list[tuple[int, Any]] = []
    actual_start = AsyncAdapt_asyncpg_connection._start_transaction

    async def start(connection: Any) -> Any:
        levels.append((connection._connection.get_server_pid(), connection.isolation_level))
        return await actual_start(connection)

    monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "_start_transaction", start)
    assert await executor.status(actor, view.run_id) == view
    assert levels == [(initial_pid, "read_committed")]
    async with factory() as session:
        after = (
            await session.execute(
                text("SELECT pg_backend_pid(),current_setting('transaction_isolation')")
            )
        ).one()
        assert tuple(after) == (initial_pid, initial)
    assert executor.uow.factory is factory and not base.get_execution_options()
    # Exact NEW task database only; a fresh engine must sample its non-RC default.
    owner_engine = create_async_engine(
        os.environ["MIGRATION_DSN"].replace("postgresql://", "postgresql+asyncpg://", 1),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with owner_engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT current_database()"))
                == "rtr_tip054_r15_local_e1"
            )
            await connection.execute(
                text(
                    'ALTER DATABASE "rtr_tip054_r15_local_e1" '
                    "SET default_transaction_isolation TO 'repeatable read'"
                )
            )
        await base.dispose()
        runtime.session_factory.cache_clear()
        runtime.runtime_engine.cache_clear()
        runtime._runtime_status_pair.cache_clear()
        non_rc = runtime.session_factory()
        service = ExecutionService()
        service.settings = execution_config
        async with non_rc() as session:
            non_rc_pid, isolation = (
                await session.execute(
                    text("SELECT pg_backend_pid(),current_setting('transaction_isolation')")
                )
            ).one()
            assert isolation == "repeatable read"
        levels.clear()
        assert await service.status(actor, view.run_id) == view
        assert levels == [(non_rc_pid, "read_committed")]
        async with non_rc() as session:
            after = (
                await session.execute(
                    text("SELECT pg_backend_pid(),current_setting('transaction_isolation')")
                )
            ).one()
            assert tuple(after) == (non_rc_pid, "repeatable read")
        assert not runtime.runtime_engine().get_execution_options()
        assert non_rc is service.uow.factory
    finally:
        async with owner_engine.connect() as connection:
            await connection.execute(
                text('ALTER DATABASE "rtr_tip054_r15_local_e1" RESET default_transaction_isolation')
            )
        await owner_engine.dispose()


@pytest.mark.asyncio
async def test_standard_default_status_fresh_owner_cleanup_invariants(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    executor, actor, refs, _, _, view = await submitted(factory, tmp_path, execution_config)
    owners = r14.capture(monkeypatch)
    proof = previous.EngineProof(factory)
    with proof.watching():
        await proof.control(factory)
    before = await r14.immutable_snapshot(oracle, view.run_id)
    with proof.watching():
        assert (
            await executor.status(actor.model_copy(update={"security_version": -100}), view.run_id)
            == view
        )
    assert len(proof.sql) == 3 and [kind for kind, _ in proof.events] == ["out", "in"]
    r14.clean(factory, owners)
    foreign = await principal(factory)
    with pytest.raises(ActionError) as error:
        await executor.status(foreign, view.run_id)
    assert error.value.status == 404
    assert await r14.immutable_snapshot(oracle, view.run_id) == before
    await executor.advance(view.run_id)
    await deny(factory, refs[0], actor)
    assert (await executor.status(actor, view.run_id)).run_id == view.run_id
    with pytest.raises(ActionError) as error:
        await executor.read_output(actor, view.run_id, "read", request_id="r15-denied-output")
    assert error.value.status == 403
    r14.clean(factory, owners)


@pytest.mark.asyncio
async def test_interleaved_status_keeps_two_lease_write_and_postcommit_outcomes(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    # Invoke immutable established controls on the actual canonical factory.
    from types import SimpleNamespace

    import test_action_source_batching_integration as sources
    import test_action_two_lease_review_integration as writes

    from rtr_copilot.actions.execution_api import bounded

    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    proof = previous.EngineProof(factory)
    with proof.watching():
        await proof.control(factory)
    with proof.watching():
        plan = await actions.create_plan(actor, sources.requested(refs), request_id="r15-create")
    assert len(proof.sql) == 29 and [kind for kind, _ in proof.events] == ["out", "in"] * 2
    proof.sql.clear()
    proof.events.clear()
    with proof.watching():
        view = await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="r15-submit")
    assert len(proof.sql) == 22 and [kind for kind, _ in proof.events] == ["out", "in"] * 2
    assert await executor.status(actor, view.run_id) == view
    # Existing labelled durable-commit failure controls, with their full assertions.
    with monkeypatch.context() as scoped:
        await writes.test_original_final_query_lock_timeout_preserves_commit_no_replay(
            factory, oracle, tmp_path, scoped, local_boundaries, execution_config
        )
    with monkeypatch.context() as scoped:
        await writes.test_real_commit_ack_delivery_fault_blocks_final_and_replay(
            factory, oracle, tmp_path, scoped, local_boundaries, execution_config
        )
    owners = r14.capture(monkeypatch)
    async with AsyncExitStack() as held:
        for _ in range(10):
            await held.enter_async_context(runtime.runtime_engine().connect())
        task = asyncio.create_task(executor.status(actor, view.run_id))
        try:
            queue = runtime.runtime_engine().pool._pool._queue
            for _ in range(100):
                if queue._getters:
                    break
                await asyncio.sleep(0.01)
            assert queue._getters
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await previous.cancel_join(task)
    r14.clean(factory, owners)
    # All canonical fault/task-local R14 assertions are reused on this origin.
    with monkeypatch.context() as scoped:
        await r14.test_acquisition_cancel_receipt_sql_error_and_repeated_query_close_cancel_join(
            factory, oracle, tmp_path, execution_config, local_boundaries, scoped
        )
    with monkeypatch.context() as scoped:
        await r14.test_concurrent_status_uses_task_local_session_and_child_handle_is_inert(
            factory, oracle, tmp_path, execution_config, local_boundaries, scoped
        )
    stopped = await executor.cancel(actor, view.run_id)
    assert stopped.cancel_acknowledged
    response = await bounded(
        SimpleNamespace(state=SimpleNamespace(request_id="r15-status")),
        actor,
        executor,
        executor.status(actor, view.run_id),
    )
    assert response == stopped
    assert not runtime.runtime_engine().get_execution_options()
    assert executor.uow.factory is factory
    r14.clean(factory, owners)
