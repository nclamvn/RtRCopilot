"""Seven finite R14 real-SQL controls; no native executor/provider activation.

Delegated scheduling hooks and one labelled receipt-SQL column fault do not
replace persisted authority or outcomes. SHOW/protocol/oracle SQL is outside the
application count. Status does not promise latest-at-return or atomic receipts.
"""

import asyncio
import os
import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_action_contracts_integration import deny, principal
from test_action_policy_batching_integration import wait_blocked

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_api import bounded
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import RequestConnection, _OwnerSession
from rtr_copilot.auth.models import Role
from rtr_copilot.db.uow import UnitOfWork

pytestmark = adversarial.pytestmark


@pytest_asyncio.fixture(loop_scope="session")
async def factory() -> Any:
    async for original in previous.factory.__wrapped__():
        engine = original.kw["bind"].execution_options(isolation_level="READ COMMITTED")
        yield async_sessionmaker(engine, expire_on_commit=False)


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


async def setup(factory: Any, tmp_path: Path, execution_config: Any) -> Any:
    result = await adversarial.submitted(factory, tmp_path, execution_config)
    assert result[0]._status_read_admitted()
    return result


def clean(factory: Any, owners: list[Any]) -> None:
    assert factory.kw["bind"].pool.checkedout() == 0
    for owner in owners:
        assert owner.terminal_task is None and owner.connection is None and owner.session is None
        assert not owner.phase_active and not owner.entered and not owner.has_retained_lease


def capture(monkeypatch: Any) -> list[Any]:
    owners: list[Any] = []
    real = RequestConnection.__aenter__

    async def enter(owner: Any) -> Any:
        owners.append(owner)
        return await real(owner)

    monkeypatch.setattr(RequestConnection, "__aenter__", enter)
    return owners


async def immutable_snapshot(oracle: Any, run: Any) -> Any:
    async with oracle() as session:
        return (
            await session.execute(
                text("""
            SELECT (SELECT to_jsonb(e) FROM action_executions e WHERE run_id=:run),
              (SELECT count(*) FROM action_execution_events WHERE run_id=:run),
              (SELECT count(*) FROM action_execution_receipts WHERE run_id=:run),
              (SELECT count(*) FROM action_step_attempts WHERE run_id=:run),
              (SELECT count(*) FROM audit_events),
              (SELECT count(*) FROM document_publication_outbox)
        """),
                {"run": run},
            )
        ).one()


@pytest.mark.asyncio
async def test_supported_owner_three_sql_one_checkout_after_joined_cleanup(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    executor, actor, _, _, _, view = await setup(factory, tmp_path, execution_config)
    owners = capture(monkeypatch)
    before = await immutable_snapshot(oracle, view.run_id)
    proof = previous.EngineProof(factory)
    with proof.watching():
        await proof.control(factory)
    actual_builder = ExecutionService._execution_view

    def builder(service: Any, *args: Any) -> Any:
        clean(factory, owners)
        return actual_builder(service, *args)

    monkeypatch.setattr(ExecutionService, "_execution_view", builder)
    with proof.watching():
        result = await executor.status(actor, view.run_id)
    assert result == view and len(proof.sql) == 3
    assert sum("SELECT e.*,r.plan_id" in sql for sql in proof.sql) == 1
    assert [kind for kind, _ in proof.events] == ["out", "in"] and not proof.owned
    assert await immutable_snapshot(oracle, view.run_id) == before
    clean(factory, owners)


@pytest.mark.asyncio
async def test_current_actor_owner_errors_and_receipt_shape_cap(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    executor, actor, _, _, _, view = await setup(factory, tmp_path, execution_config)
    stale = actor.model_copy(update={"security_version": -999, "roles": {Role.ADMIN}})
    assert await executor.status(stale, view.run_id) == view
    foreign = await principal(factory)
    missing = actor.model_copy(update={"user_id": str(uuid.uuid4())})
    disabled = await principal(factory)
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE subjects SET status='disabled' WHERE user_id=:id"),
            {"id": uuid.UUID(disabled.user_id)},
        )
    for supplied, run, code in (
        (foreign, view.run_id, 404),
        (actor, uuid.uuid4(), 404),
        (missing, view.run_id, 403),
        (disabled, view.run_id, 403),
    ):
        proof = previous.EngineProof(factory)
        proof.tasks.add(asyncio.current_task())
        with proof.watching(), pytest.raises(ActionError) as error:
            await executor.status(supplied, run)
        assert error.value.status == code
        assert not any("FROM action_execution_receipts c" in sql for sql in proof.sql)
        assert not proof.owned
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    for target in (2, 101):
        async with factory() as session, session.begin():
            for ordinal in range(0 if target == 2 else 2, target):
                attempt, receipt = uuid.uuid4(), uuid.UUID(int=ordinal + 1)
                await session.execute(
                    text("""
                    INSERT INTO action_step_attempts(attempt_id,run_id,step_key,attempt,epoch,
                      owner_token,source_key,input_digest,charged_calls)
                    VALUES(:aid,:run,:step,1,1,:token,:source,:digest,1)
                """),
                    {
                        "aid": attempt,
                        "run": view.run_id,
                        "step": f"r14_{ordinal}",
                        "token": uuid.uuid4(),
                        "source": f"r14:{view.run_id}:{ordinal}",
                        "digest": "a" * 64,
                    },
                )
                await session.execute(
                    text("""
                    INSERT INTO action_execution_receipts(receipt_id,run_id,attempt_id,step_key,
                      attempt,kind,output_digest,reused_source,occurred_at)
                    VALUES(:rid,:run,:aid,:step,1,'read_verified',:digest,false,:instant)
                """),
                    {
                        "rid": receipt,
                        "run": view.run_id,
                        "aid": attempt,
                        "step": f"r14_{ordinal}",
                        "digest": "b" * 64,
                        "instant": instant,
                    },
                )
        optimized = await executor.status(stale, view.run_id)
        reference = await executor._view(view.run_id)
        assert optimized == reference and len(optimized.receipts) == min(target, 100)
        assert [r.receipt_id.int for r in optimized.receipts] == list(
            range(1, min(target, 100) + 1)
        )
        assert all(
            r.input_digest == "a" * 64
            and r.output_digest == "b" * 64
            and r.charged_tool_calls == 1
            and r.kind == "read_verified"
            and r.source_id is None
            and r.version_id is None
            for r in optimized.receipts
        )
    assert factory.kw["bind"].pool.checkedout() == 0


@pytest.mark.asyncio
async def test_isolation_and_cancel_before_row_are_fresh(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    executor, actor, _, _, _, view = await setup(factory, tmp_path, execution_config)
    levels: list[Any] = []
    real_start = AsyncAdapt_asyncpg_connection._start_transaction

    async def start(connection: Any) -> Any:
        levels.append(connection.isolation_level)
        return await real_start(connection)

    monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "_start_transaction", start)
    # Actual SHOW on two acquisitions (same fixed pool), never a status request probe.
    pids = []
    for _ in range(2):
        async with factory() as session:
            assert await session.scalar(text("SHOW transaction_isolation")) == "read committed"
            pids.append(await session.scalar(text("SELECT pg_backend_pid()")))
    assert pids[0] == pids[1]
    levels.clear()
    projected, continue_row = asyncio.Event(), asyncio.Event()
    real_execute = _OwnerSession.execute

    async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = await real_execute(session, statement, *args, **kwargs)
        if "principal_ids" in str(statement):
            projected.set()
            await continue_row.wait()
        return result

    monkeypatch.setattr(_OwnerSession, "execute", execute)
    task = asyncio.create_task(executor.status(actor, view.run_id))
    try:
        await asyncio.wait_for(projected.wait(), 2)
        async with oracle() as session, session.begin():
            await session.execute(
                text("""
                UPDATE action_executions SET state='cancelled',cancel_requested=true,
                  reason_code='cancel_remaining',epoch=epoch+1 WHERE run_id=:run
            """),
                {"run": view.run_id},
            )
        continue_row.set()
        result = await task
        assert result.state == "cancelled" and result.cancel_acknowledged
        assert levels and all(level == "read_committed" for level in levels if level is not None)
        assert levels[0] == "read_committed"
    finally:
        await previous.cancel_join(task)
    assert factory.kw["bind"].pool.checkedout() == 0


@pytest.mark.asyncio
async def test_unknown_nonstandard_and_mismatched_origins_keep_old_path(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    executor, actor, _, _, _, view = await setup(factory, tmp_path, execution_config)
    base = factory.kw["bind"].sync_engine._proxied
    from sqlalchemy.ext.asyncio import AsyncEngine

    for level in (None, "REPEATABLE READ", "SERIALIZABLE"):
        engine = (
            AsyncEngine(base)
            if level is None
            else AsyncEngine(base).execution_options(isolation_level=level)
        )
        legacy_factory = async_sessionmaker(engine, expire_on_commit=False)
        legacy = ExecutionService(UnitOfWork(legacy_factory))
        legacy.settings = execution_config
        assert not legacy._status_read_admitted()
        proof = previous.EngineProof(legacy_factory)
        proof.tasks.add(asyncio.current_task())
        with proof.watching():
            assert await legacy.status(actor, view.run_id) == view
        assert len(proof.sql) == 4 and [kind for kind, _ in proof.events] == ["out", "in"] * 3
    same_url_factory = async_sessionmaker(factory.kw["bind"], expire_on_commit=False)
    executor.actions.policy.uow = UnitOfWork(same_url_factory)
    assert not executor._status_read_admitted()
    proof = previous.EngineProof(factory)
    proof.tasks.add(asyncio.current_task())
    with proof.watching():
        assert await executor.status(actor, view.run_id) == view
    assert len(proof.sql) == 4 and [kind for kind, _ in proof.events] == ["out", "in"] * 3


@pytest.mark.asyncio
async def test_status_metadata_survives_source_revoke_without_output_grant(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    executor, actor, refs, _, _, view = await setup(factory, tmp_path, execution_config)
    await executor.advance(view.run_id)
    first = await executor.status(actor, view.run_id)
    await deny(factory, refs[0], actor)
    before = await immutable_snapshot(oracle, view.run_id)
    assert await executor.status(actor, view.run_id) == first
    with pytest.raises(ActionError) as error:
        await executor.read_output(actor, view.run_id, "read", request_id="r14-revoked-output")
    assert error.value.status == 403
    assert await immutable_snapshot(oracle, view.run_id) == before


@pytest.mark.asyncio
async def test_acquisition_cancel_receipt_sql_error_and_repeated_query_close_cancel_join(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    executor, actor, _, _, _, view = await setup(factory, tmp_path, execution_config)
    owners = capture(monkeypatch)
    engine = factory.kw["bind"]
    immutable_before = await immutable_snapshot(oracle, view.run_id)
    async with AsyncExitStack() as held:
        for _ in range(10):
            await held.enter_async_context(engine.connect())
        task = asyncio.create_task(executor.status(actor, view.run_id))
        try:
            queue = engine.sync_engine.pool._pool._queue
            for _ in range(100):
                if queue._getters:
                    break
                await asyncio.sleep(0.01)
            assert queue._getters and not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not queue._getters
        finally:
            await previous.cancel_join(task)
    clean(factory, owners)

    def fault(conn: Any, cursor: Any, sql: str, params: Any, *args: Any) -> Any:
        if "FROM action_execution_receipts c" in sql:
            sql = sql.replace("SELECT c.receipt_id", "SELECT c.r14_absent_column,c.receipt_id")
        return sql, params

    event.listen(engine.sync_engine, "before_cursor_execute", fault, retval=True)
    try:
        with pytest.raises(DBAPIError) as error:
            await executor.status(actor, view.run_id)
        assert "r14_absent_column" in str(error.value)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fault)
    clean(factory, owners)
    admin_engine = create_async_engine(
        os.environ["MIGRATION_DSN"].replace("postgresql://", "postgresql+asyncpg://", 1),
        poolclass=NullPool,
    )
    admin = async_sessionmaker(admin_engine, expire_on_commit=False)
    real_execute, real_close = _OwnerSession.execute, _OwnerSession.close
    receipt_started, close_started, allow_close = asyncio.Event(), asyncio.Event(), asyncio.Event()
    status_pid: list[int] = []

    async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if "FROM action_execution_receipts c" in str(statement):
            status_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            receipt_started.set()
        return await real_execute(session, statement, *args, **kwargs)

    async def close(session: Any) -> Any:
        close_started.set()
        await allow_close.wait()
        return await real_close(session)

    monkeypatch.setattr(_OwnerSession, "execute", execute)
    monkeypatch.setattr(_OwnerSession, "close", close)
    task = None
    try:
        async with admin() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                text("LOCK TABLE action_execution_receipts IN ACCESS EXCLUSIVE MODE")
            )
            task = asyncio.create_task(executor.status(actor, view.run_id))
            await asyncio.wait_for(receipt_started.wait(), 2)
            await wait_blocked(oracle, status_pid[0], blocker_pid)
            task.cancel()
            await asyncio.wait_for(close_started.wait(), 2)
            task.cancel()
            task.cancel()
            assert not task.done() and owners[-1].terminal_task is not None
            allow_close.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        clean(factory, owners)
    finally:
        allow_close.set()
        await previous.cancel_join(task)
    monkeypatch.setattr(_OwnerSession, "close", real_close)
    from types import SimpleNamespace

    # API timeout is an actual table-lock receipt wait; persistent settings stay OFF.
    receipt_started.clear()
    try:
        async with admin() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                text("LOCK TABLE action_execution_receipts IN ACCESS EXCLUSIVE MODE")
            )
            task = asyncio.create_task(
                bounded(
                    SimpleNamespace(state=SimpleNamespace(request_id="r14-actual-timeout")),
                    actor,
                    executor,
                    executor.status(actor, view.run_id),
                )
            )
            await asyncio.wait_for(receipt_started.wait(), 2)
            await wait_blocked(oracle, status_pid[-1], blocker_pid)
            response = await task
            assert response.status_code == 503 and b"action_operation_timeout" in response.body
            clean(factory, owners)
    finally:
        await previous.cancel_join(task)
        await admin_engine.dispose()
    monkeypatch.setattr(_OwnerSession, "execute", real_execute)

    # Labelled synthetic ACK fault after real Session terminal work, not TCP loss.
    async def close_fault(session: Any) -> Any:
        await real_close(session)
        raise RuntimeError("r14_close_ack_fault")

    with monkeypatch.context() as terminal_fault:
        terminal_fault.setattr(_OwnerSession, "close", close_fault)
        with pytest.raises(RuntimeError, match="r14_close_ack_fault"):
            await executor.status(actor, view.run_id)
    clean(factory, owners)
    assert await immutable_snapshot(oracle, view.run_id) == immutable_before
    response = await bounded(
        SimpleNamespace(state=SimpleNamespace(request_id="r14-bounded")),
        actor,
        executor,
        executor.status(actor, view.run_id),
    )
    assert response == view
    clean(factory, owners)


@pytest.mark.asyncio
async def test_concurrent_status_uses_task_local_session_and_child_handle_is_inert(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: Any,
) -> None:
    executor, actor, _, _, _, view = await setup(factory, tmp_path, execution_config)
    owners = capture(monkeypatch)
    sessions: list[Any] = []
    both, resume = asyncio.Event(), asyncio.Event()
    real = _OwnerSession.execute

    async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = await real(session, statement, *args, **kwargs)
        if "principal_ids" in str(statement):
            sessions.append(session)
            if len(sessions) == 2:
                both.set()
            await resume.wait()
        return result

    monkeypatch.setattr(_OwnerSession, "execute", execute)
    tasks = [asyncio.create_task(executor.status(actor, view.run_id)) for _ in range(2)]
    try:
        await asyncio.wait_for(both.wait(), 2)
        assert sessions[0] is not sessions[1]
        assert sessions[0].request_connection is not sessions[1].request_connection
        for session in sessions:
            with pytest.raises(RuntimeError, match="task_mismatch"):
                await asyncio.create_task(session.execute(text("SELECT 17")))
        resume.set()
        assert await asyncio.gather(*tasks) == [view, view]
        for session in sessions:
            with pytest.raises(RuntimeError):
                await session.execute(text("SELECT 19"))
        clean(factory, owners)
    finally:
        resume.set()
        for task in tasks:
            await previous.cancel_join(task)
