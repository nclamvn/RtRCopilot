"""Independent R5 real SQL proofs; controlled scheduling is not a row-lock proof.

Physical facade generations may reuse pooled drivers/PIDs. No authority or
business outcome is mocked; Engine observations and phase methods delegate.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_action_checkout_audit_tail_integration import (
    counts,
    execution_metadata,
    expired_role,
    premise,
    record_id,
)
from test_action_policy_batching_integration import wait_after, wait_blocked
from test_action_source_batching_integration import requested

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_api import bounded
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import RequestConnection
from rtr_copilot.auth.models import Role
from rtr_copilot.repositories.audit import AuditRepository

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    assert "/rtr_tip054_" in fixtures.DSN
    engine = create_async_engine(
        fixtures.DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        assert engine.pool.checkedout() == 0
        await engine.dispose()


@pytest_asyncio.fixture
async def oracle(factory: Any) -> Any:
    engine = create_async_engine(factory.kw["bind"].url, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


async def chain(factory: Any) -> None:
    async with factory() as session:
        assert (await AuditRepository().verify(session))[0]


async def cancel_join(task: Any) -> None:
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class EngineProof:
    """Real events, checkin matched by record ownership across shielded children."""

    def __init__(self, factory: Any) -> None:
        self.engine = factory.kw["bind"].sync_engine
        self.tasks: set[Any] = set()
        self.owned: set[int] = set()
        self.events: list[tuple[str, int]] = []
        self.sql: list[str] = []
        self.maxheld = 0

    @contextmanager
    def watching(self) -> Any:
        def checkout(dbapi: Any, record: Any, proxy: Any) -> None:
            if asyncio.current_task() in self.tasks:
                identity = id(record)
                assert identity not in self.owned
                self.owned.add(identity)
                self.events.append(("out", identity))
                self.maxheld = max(self.maxheld, len(self.owned))

        def checkin(dbapi: Any, record: Any) -> None:
            identity = id(record)
            if identity in self.owned:
                self.owned.remove(identity)
                self.events.append(("in", identity))

        def before(connection: Any, cursor: Any, statement: str, *args: Any) -> None:
            if asyncio.current_task() in self.tasks:
                self.sql.append(statement)

        event.listen(self.engine, "checkout", checkout)
        event.listen(self.engine, "checkin", checkin)
        event.listen(self.engine, "before_cursor_execute", before)
        try:
            yield self
        finally:
            event.remove(self.engine, "checkout", checkout)
            event.remove(self.engine, "checkin", checkin)
            event.remove(self.engine, "before_cursor_execute", before)

    async def control(self, factory: Any) -> None:
        self.tasks.add(asyncio.current_task())
        async with factory() as session:
            assert (await session.execute(text("SELECT 17"))).scalar_one() == 17
            assert await session.scalar(text("SELECT 19")) == 19
        assert len(self.sql) == 2
        assert [kind for kind, _ in self.events] == ["out", "in"]
        assert not self.owned and self.maxheld == 1
        self.events.clear()
        self.sql.clear()
        self.maxheld = 0


class PhaseProof:
    def __init__(self, observation: EngineProof) -> None:
        self.observation = observation
        self.rows: list[Any] = []
        self.connections: list[Any] = []

    def install(self, monkeypatch: Any) -> None:
        real_read = RequestConnection.read_phase
        real_mutation = RequestConnection.mutation_phase

        async def capture(session: Any, label: str) -> Any:
            connection = await session.connection()
            assert (await session.execute(text("SELECT 23"))).scalar_one() == 23
            assert await session.scalar(text("SELECT 29")) == 29
            row = (
                await session.execute(
                    text("SELECT pg_backend_pid(),txid_current(),transaction_timestamp()")
                )
            ).one()
            self.rows.append((label, session, *row))
            self.connections.append(connection)
            return connection

        @asynccontextmanager
        async def read(owner: Any, *, commit: bool = False) -> Any:
            assert owner.connection is None
            assert len(self.observation.owned) == int(owner.has_retained_lease)
            async with real_read(owner, commit=commit) as session:
                connection = await capture(session, "read")
                yield session
            assert connection.closed and owner.connection is None
            assert not self.observation.owned

        @asynccontextmanager
        async def mutation(owner: Any) -> Any:
            assert owner.connection is None and not self.observation.owned
            async with real_mutation(owner) as session:
                connection = await capture(session, "mutation")
                yield session
            assert not connection.closed and owner.connection is None
            assert owner.has_retained_lease and not connection.in_transaction()
            assert len(self.observation.owned) == 1

        monkeypatch.setattr(RequestConnection, "read_phase", read)
        monkeypatch.setattr(RequestConnection, "mutation_phase", mutation)

    def assert_three(self) -> None:
        assert [row[0] for row in self.rows] == ["read", "mutation", "read"]
        assert len({id(row[1]) for row in self.rows}) == 3
        assert len({id(connection) for connection in self.connections}) == 3
        assert self.connections[1].sync_connection is self.connections[2].sync_connection
        assert len({row[3] for row in self.rows}) == 3
        assert self.rows[0][4] < self.rows[1][4] < self.rows[2][4]
        # Driver and PG PID reuse is deliberately permitted, not mistaken for reuse of a facade.
        assert [kind for kind, _ in self.observation.events] == ["out", "in"] * 2
        assert self.observation.maxheld == 1 and not self.observation.owned
        assert all(connection.closed for connection in self.connections)
        assert not any(
            "quoted_text" in sql or "SELECT rv.value_payload," in sql
            for sql in self.observation.sql
        )
        assert all(
            "value_payload" not in sql or "value_payload->" in sql for sql in self.observation.sql
        )


@pytest.mark.asyncio
async def test_create_three_returned_generations_and_real_clocks(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    observation = EngineProof(factory)
    proof = PhaseProof(observation)
    proof.install(monkeypatch)
    with observation.watching():
        await observation.control(factory)
        result = await actions.create_plan(actor, request, request_id="TPL-independent-create")
    proof.assert_three()
    assert result.state == "contract_ready"
    assert await counts(oracle, actor, request.idempotency_key) == (1, 1, 1, 1, 1)
    await chain(oracle)


@pytest.mark.asyncio
async def test_submit_generations_return_before_fresh_concurrent_cancel_view(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TPL-submit-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    independent = ExecutionService(type(actions.uow)(oracle), actions=actions)
    independent.settings = execution_config
    real_view = executor._view
    cancelled: list[Any] = []

    async def view(run_id: Any, *, _owner: Any = None) -> Any:
        assert _owner is not None and _owner.connection is None
        before = await execution_metadata(oracle, run_id)
        assert before["execution"]["state"] == "queued"
        await chain(oracle)
        cancelled.append(await asyncio.create_task(independent.cancel(actor, run_id)))
        return await real_view(run_id, _owner=_owner)

    monkeypatch.setattr(executor, "_view", view)
    observation = EngineProof(factory)
    proof = PhaseProof(observation)
    proof.install(monkeypatch)
    with observation.watching():
        await observation.control(factory)
        result = await executor.submit(
            actor, plan.plan_id, plan.plan_digest, request_id="TPL-independent-submit"
        )
    proof.assert_three()
    assert result == cancelled[0] and result.state == "cancelled"
    assert result.cancel_requested and result.spent_tool_calls == 0 and result.receipts == ()
    await chain(oracle)


@pytest.mark.asyncio
async def test_old_connection_sql_start_and_terminal_inert_during_new_generation(
    factory: Any,
) -> None:
    observation = EngineProof(factory)
    with observation.watching():
        await observation.control(factory)
        async with RequestConnection(factory) as owner:
            async with owner.read_phase() as session:
                old = await session.connection()
                assert await old.scalar(text("SELECT 31")) == 31
            assert old.closed and owner.connection is None and not observation.owned
            async with owner.read_phase() as session:
                current = await session.connection()
                assert current is not old
                txid = await session.scalar(text("SELECT txid_current()"))
                for child in (False, True):
                    for name in (
                        "execute",
                        "scalar",
                        "scalars",
                        "exec_driver_sql",
                        "start",
                        "close",
                        "invalidate",
                        "release_phase",
                        "close_connection",
                    ):

                        async def probe(method: str = name) -> None:
                            observation.tasks.add(asyncio.current_task())
                            if method == "release_phase":
                                await owner.release_phase(old, None)
                            elif method == "close_connection":
                                await owner.close_connection(old)
                            elif method == "exec_driver_sql":
                                await getattr(old, method)("SELECT 97")
                            elif method in {"execute", "scalar", "scalars"}:
                                await getattr(old, method)(text("SELECT 97"))
                            else:
                                await getattr(old, method)()

                        before = (len(observation.sql), list(observation.events))
                        state = (
                            owner.connection,
                            owner.session,
                            owner.generation,
                            owner.phase_active,
                            owner.poisoned,
                            owner.cleanup_complete,
                            owner.terminal_task,
                        )
                        with pytest.raises(RuntimeError):
                            if child:
                                await asyncio.create_task(probe())
                            else:
                                await probe()
                        assert (len(observation.sql), observation.events) == before
                        assert (
                            owner.connection,
                            owner.session,
                            owner.generation,
                            owner.phase_active,
                            owner.poisoned,
                            owner.cleanup_complete,
                            owner.terminal_task,
                        ) == state
                        assert owner.connection is current and not current.closed
                assert await current.scalar(text("SELECT 37")) == 37
                assert await session.scalar(text("SELECT txid_current()")) == txid
            assert owner.connection is None and not observation.owned


@pytest.mark.asyncio
async def test_old_session_and_real_unstarted_facade_inert_during_new_generation(
    factory: Any,
) -> None:
    observation = EngineProof(factory)
    with observation.watching():
        await observation.control(factory)
        async with RequestConnection(factory) as owner:
            async with owner.read_phase() as old:
                assert await old.scalar(text("SELECT 41")) == 41
                facade = old.begin()  # Real parent-created unstarted facade, no authority mock.
            async with owner.read_phase() as current:
                assert current is not old
                txid = await current.scalar(text("SELECT txid_current()"))
                for child in (False, True):
                    for surface, names in (
                        (
                            old,
                            (
                                "execute",
                                "scalar",
                                "scalars",
                                "connection",
                                "begin",
                                "close",
                                "invalidate",
                                "__aexit__",
                            ),
                        ),
                        (facade, ("start", "commit", "rollback", "__aexit__")),
                    ):
                        for name in names:

                            async def probe(target: Any = surface, method: str = name) -> None:
                                observation.tasks.add(asyncio.current_task())
                                if method == "begin":
                                    target.begin()
                                elif method == "__aexit__":
                                    await target.__aexit__(None, None, None)
                                elif method in {"execute", "scalar", "scalars"}:
                                    await getattr(target, method)(text("SELECT 101"))
                                else:
                                    await getattr(target, method)()

                            before = (len(observation.sql), list(observation.events))
                            state = (
                                owner.connection,
                                owner.session,
                                owner.generation,
                                owner.phase_active,
                                owner.poisoned,
                                owner.cleanup_complete,
                                owner.terminal_task,
                            )
                            with pytest.raises(RuntimeError):
                                if child:
                                    await asyncio.create_task(probe())
                                else:
                                    await probe()
                            assert (len(observation.sql), observation.events) == before
                            assert (
                                owner.connection,
                                owner.session,
                                owner.generation,
                                owner.phase_active,
                                owner.poisoned,
                                owner.cleanup_complete,
                                owner.terminal_task,
                            ) == state
                assert await current.scalar(text("SELECT 43")) == 43
                assert await current.scalar(text("SELECT txid_current()")) == txid
        assert not observation.owned


@pytest.mark.asyncio
async def test_repeated_cancel_joins_exact_phase_release_before_any_new_acquire(
    factory: Any, monkeypatch: Any
) -> None:
    observation = EngineProof(factory)
    target: list[Any] = []
    owners: list[Any] = []
    calls: list[Any] = []
    ready, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_close = AsyncConnection.close

    async def close(connection: Any) -> None:
        if target and connection is target[0]:
            calls.append((asyncio.current_task(), connection))
            closing.set()
            await release.wait()  # Controlled terminal scheduling, not PG-lock evidence.
        await real_close(connection)

    monkeypatch.setattr(AsyncConnection, "close", close)

    async def run() -> None:
        observation.tasks.add(asyncio.current_task())
        async with RequestConnection(factory) as owner:
            owners.append(owner)
            async with owner.read_phase() as session:
                target.append(await session.connection())
                assert await session.scalar(text("SELECT 47")) == 47
                ready.set()
            raise AssertionError("cancelled release returned permission to continue")

    task = None
    with observation.watching():
        await observation.control(factory)
        try:
            task = asyncio.create_task(run())
            await asyncio.wait_for(ready.wait(), 5)
            await asyncio.wait_for(closing.wait(), 5)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
            assert not task.done() and len(calls) == 1
            assert calls[0][1] is target[0] and len(observation.owned) == 1
            assert [kind for kind, _ in observation.events] == ["out"]
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert calls[0][0].done() and not observation.owned
            assert [kind for kind, _ in observation.events] == ["out", "in"]
            assert owners[0].connection is None
        finally:
            release.set()
            await cancel_join(task)
    async with factory() as session:
        assert await session.scalar(text("SELECT 53")) == 53


def acquisition_observer(monkeypatch: Any, factory: Any, task: Any, waiting: Any) -> None:
    pool = factory.kw["bind"].sync_engine.pool
    real = pool._do_get

    def getting() -> Any:
        marker = waiting()
        if asyncio.current_task() is task() and not marker.done():
            marker.set_result(asyncio.current_task())
        return real()

    monkeypatch.setattr(pool, "_do_get", getting)


@pytest.mark.asyncio
async def test_mutation_reacquire_cancellation_after_initial_checkin_has_no_ledger(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    ready, resume = asyncio.Event(), asyncio.Event()
    waiting = asyncio.get_running_loop().create_future()
    owners: list[Any] = []
    task = None
    real = actions._initial_plan

    async def initial(*args: Any, **kwargs: Any) -> Any:
        result = await real(*args, **kwargs)
        owner = kwargs["_owner"]
        owners.append(owner)
        assert owner.connection is None and factory.kw["bind"].pool.checkedout() == 0
        ready.set()
        await resume.wait()
        return result

    monkeypatch.setattr(actions, "_initial_plan", initial)
    acquisition_observer(monkeypatch, factory, lambda: task, lambda: waiting)
    try:
        task = asyncio.create_task(
            actions.create_plan(actor, request, request_id="TPL-cancel-phase2")
        )
        await asyncio.wait_for(ready.wait(), 5)
        waiting = asyncio.get_running_loop().create_future()
        async with AsyncExitStack() as stack:
            for _ in range(10):
                await stack.enter_async_context(factory.kw["bind"].connect())
            assert factory.kw["bind"].pool.checkedout() == 10
            resume.set()
            assert await asyncio.wait_for(waiting, 5) is task
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert factory.kw["bind"].pool.checkedout() == 10
            assert owners[0].mutation_started and not owners[0].fallback_allowed
            assert await counts(oracle, actor, request.idempotency_key) == (0, 0, 0, 0, 0)
        assert owners[0].connection is None and factory.kw["bind"].pool.checkedout() == 0
        await chain(oracle)
    finally:
        resume.set()
        await cancel_join(task)


@pytest.mark.asyncio
async def test_real_commit_then_final_acquire_timeout_is_truthful_and_never_replays(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TPL-outcome-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    ready, resume = asyncio.Event(), asyncio.Event()
    waiting = asyncio.get_running_loop().create_future()
    task = None
    real_view = executor._view
    real_read = RequestConnection.read_phase
    view_calls: list[Any] = []

    async def view(run_id: Any, *, _owner: Any = None) -> Any:
        assert _owner is not None and _owner.connection is None
        view_calls.append(run_id)
        ready.set()
        await resume.wait()
        return await real_view(run_id, _owner=_owner)

    @asynccontextmanager
    async def read(owner: Any, *, commit: bool = False) -> Any:
        async with real_read(owner, commit=commit) as session:
            if owner.has_retained_lease and not waiting.done():
                waiting.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/actions/execute",
            "headers": [],
            "state": {"request_id": "TPL-final-acquire"},
        }
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(executor, "_view", view)
        scoped.setattr(RequestConnection, "read_phase", read)
        try:
            task = asyncio.create_task(
                bounded(
                    request,
                    actor,
                    executor,
                    executor.submit(
                        actor, plan.plan_id, plan.plan_digest, request_id="TPL-final-acquire"
                    ),
                )
            )
            await asyncio.wait_for(ready.wait(), 5)
            assert factory.kw["bind"].pool.checkedout() == 1
            before = await execution_metadata(oracle, plan.run_id)
            assert before["execution"]["state"] == "queued"
            await chain(oracle)  # Independently visible actual commit, never a mock.
            async with oracle() as blocker, blocker.begin():
                blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
                # A row UPDATE does not block ordinary MVCC SELECT; this real
                # existing-table lock blocks the exact unmodified final query.
                await blocker.execute(text("LOCK TABLE action_executions IN ACCESS EXCLUSIVE MODE"))
                resume.set()
                victim_pid = await asyncio.wait_for(waiting, 5)
                await wait_blocked(oracle, victim_pid, blocker_pid)
                response = await asyncio.wait_for(task, 5)
                assert response.status_code == 503 and b"action_operation_timeout" in response.body
                assert b"Check durable action status before resubmitting" in response.body
                assert factory.kw["bind"].pool.checkedout() == 0 and view_calls == [plan.run_id]
            assert await execution_metadata(oracle, plan.run_id) == before
        finally:
            resume.set()
            await cancel_join(task)
    assert (await executor.status(actor, plan.run_id)).state == "queued"
    await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="TPL-outcome-retry")
    assert await execution_metadata(oracle, plan.run_id) == before
    await chain(oracle)


@pytest.mark.asyncio
async def test_final_create_reacquire_spans_role_expiry_and_denies_disclosure(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    resource = await record_id(oracle, refs)
    await premise(oracle, actor, resource, True)
    request = requested(refs)
    ready, resume = asyncio.Event(), asyncio.Event()
    waiting = asyncio.get_running_loop().create_future()
    task = None
    real = actions._metadata_plan
    real_read = RequestConnection.read_phase
    committed: list[Any] = []

    async def metadata(*args: Any, **kwargs: Any) -> Any:
        owner = kwargs["_owner"]
        assert owner.connection is None
        committed.append(args[1])
        ready.set()
        await resume.wait()
        return await real(*args, **kwargs)

    @asynccontextmanager
    async def read(owner: Any, *, commit: bool = False) -> Any:
        async with real_read(owner, commit=commit) as session:
            if owner.has_retained_lease and not waiting.done():
                waiting.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions, "_metadata_plan", metadata)
    monkeypatch.setattr(RequestConnection, "read_phase", read)
    try:
        task = asyncio.create_task(
            actions.create_plan(actor, request, request_id="TPL-final-expiry")
        )
        await asyncio.wait_for(ready.wait(), 5)
        before = await counts(oracle, actor, request.idempotency_key)
        assert before == (1, 1, 1, 1, 1) and len(committed) == 1
        await chain(oracle)
        due = datetime.now(UTC) + timedelta(seconds=0.4)
        await expired_role(oracle, actor, due)
        async with oracle() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            assert await blocker.scalar(
                text("SELECT version_id FROM record_versions WHERE version_id=:v FOR UPDATE"),
                {"v": refs[0].record_version_id},
            ) == refs[0].record_version_id
            resume.set()
            victim_pid = await asyncio.wait_for(waiting, 5)
            await wait_blocked(oracle, victim_pid, blocker_pid)
            assert not task.done() and factory.kw["bind"].pool.checkedout() == 1
            await wait_after(oracle, due)
            current = await premise(oracle, actor, resource, False)
            assert Role.CURATOR not in current.roles and Role.STAFF in current.roles
            assert current.security_version == actor.security_version
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
        assert await counts(oracle, actor, request.idempotency_key) == before
        await chain(oracle)
    finally:
        resume.set()
        await cancel_join(task)
