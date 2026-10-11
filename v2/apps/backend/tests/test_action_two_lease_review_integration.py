"""Ten independent R7 real SQL proofs; scheduling/ACK faults are labelled.

No authority or business outcome is mocked. Witnesses use a separate NullPool;
physical PID reuse is allowed. The two-lease generation boundary is exercised
on the SAME sync connection, not a different checkout disguised as freshness.
"""

import asyncio
import gc
import weakref
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection
from sqlalchemy.ext.asyncio import AsyncSession
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
from rtr_copilot.actions.request_connection import RequestConnection, _OwnerSession
from rtr_copilot.actions.service import ActionService
from rtr_copilot.auth.models import Role
from rtr_copilot.context.sources import revalidate_sot_references
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


def live_state(owner: Any) -> tuple[Any, ...]:
    return (
        owner.connection,
        owner.session,
        owner.generation,
        owner.phase_active,
        owner.poisoned,
        owner.cleanup_complete,
        owner.terminal_task,
        owner.has_retained_lease,
        owner.mutation_started,
    )


async def source_denied(oracle: Any, actor: Any, refs: Any) -> None:
    result = await revalidate_sot_references(
        actor,
        refs,
        factory=oracle,
        use_class="proposal",
        request_id="TLC-independent-denial",
        include_text=False,
    )
    assert result.gaps or not result.sources


async def released_locks(oracle: Any, actor: Any, refs: Any) -> None:
    """Actual independent incompatible locks, BEFORE any final Session SQL."""
    async with oracle() as session, session.begin():
        assert await session.scalar(text("SELECT pg_try_advisory_xact_lock(827004)"))
        assert await session.scalar(text("SELECT pg_try_advisory_xact_lock(827005)"))
        assert await session.scalar(
            text("SELECT user_id FROM subjects WHERE user_id=:id FOR UPDATE NOWAIT"),
            {"id": actor.user_id},
        )
        assert await session.scalar(
            text("""
            SELECT rv.version_id FROM record_versions rv
            JOIN records r ON r.record_id=rv.record_id
            JOIN sot_packages p ON p.package_id=rv.package_id
            WHERE rv.version_id=:id FOR UPDATE OF rv,r,p NOWAIT
        """),
            {"id": refs[0].record_version_id},
        )


class ThreeTransactions:
    """Do not keep test-owned strong mutation Connection/Session references."""

    def __init__(self, observation: Any, oracle: Any, actor: Any, refs: Any) -> None:
        self.observation, self.oracle, self.actor, self.refs = observation, oracle, actor, refs
        self.rows: list[dict[str, Any]] = []

    async def capture(self, owner: Any, session: Any, label: str) -> None:
        connection = await session.connection()
        for prior in self.rows:
            assert prior["connection"]() is not connection
            assert prior["session"]() is not session
            assert prior["token"] is not owner.generation
        gc.collect()
        assert await session.connection() is connection is owner.connection
        assert (await session.execute(text("SELECT 23"))).scalar_one() == 23
        assert await session.scalar(text("SELECT 29")) == 29
        row = (
            await session.execute(
                text("SELECT pg_backend_pid(),txid_current(),transaction_timestamp()")
            )
        ).one()
        self.rows.append(
            {
                "label": label,
                "session": weakref.ref(session),
                "connection": weakref.ref(connection),
                "token": owner.generation,
                "sync": connection.sync_connection,
                "pid": row[0],
                "tx": row[1],
                "clock": row[2],
            }
        )
        if label == "final":
            assert self.rows[1]["connection"]() is not None  # Production owns it, not this test.
            assert self.rows[1]["sync"] is connection.sync_connection
            assert self.rows[1]["connection"]().request_generation is self.rows[1]["token"]
            gc.collect()
            assert await session.connection() is connection

    def install(self, monkeypatch: Any) -> None:
        real_read, real_mutation = RequestConnection.read_phase, RequestConnection.mutation_phase

        @asynccontextmanager
        async def read(owner: Any, *, commit: bool = False) -> Any:
            final = owner.has_retained_lease
            if final:
                assert owner.connection is None and len(self.observation.owned) == 1
                assert [k for k, _ in self.observation.events] == ["out", "in", "out"]
                await released_locks(self.oracle, self.actor, self.refs)
            else:
                assert not self.observation.owned
            async with real_read(owner, commit=commit) as session:
                await self.capture(owner, session, "final" if final else "initial")
                yield session
                if final:
                    gc.collect()
                    assert self.rows[1]["connection"]() is not None
                    assert await session.connection() is owner.connection
            assert owner.connection is None and not self.observation.owned
            assert not owner.has_retained_lease

        @asynccontextmanager
        async def mutation(owner: Any) -> Any:
            assert not self.observation.owned and not owner.has_retained_lease
            async with real_mutation(owner) as session:
                await self.capture(owner, session, "mutation")
                yield session
            assert owner.connection is None and owner.session is None
            assert owner.has_retained_lease and len(self.observation.owned) == 1

        monkeypatch.setattr(RequestConnection, "read_phase", read)
        monkeypatch.setattr(RequestConnection, "mutation_phase", mutation)

    def check(self) -> None:
        assert [r["label"] for r in self.rows] == ["initial", "mutation", "final"]
        assert len({r["tx"] for r in self.rows}) == 3
        assert self.rows[0]["clock"] < self.rows[1]["clock"] < self.rows[2]["clock"]
        assert self.rows[1]["sync"] is self.rows[2]["sync"]
        assert [k for k, _ in self.observation.events] == ["out", "in"] * 2
        assert self.observation.maxheld == 1 and not self.observation.owned
        assert any("827005" in sql for sql in self.observation.sql)
        assert not any(
            "quoted_text" in sql or "SELECT rv.value_payload," in sql
            for sql in self.observation.sql
        )


@pytest.mark.asyncio
async def test_create_two_physical_leases_three_fresh_tx_and_lock_release(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    observation = previous.EngineProof(factory)
    proof = ThreeTransactions(observation, oracle, actor, refs)
    proof.install(monkeypatch)
    with observation.watching():
        await observation.control(factory)
        result = await actions.create_plan(actor, request, request_id="TLC-review-create")
    proof.check()
    assert result.state == "contract_ready"
    assert await counts(oracle, actor, request.idempotency_key) == (1, 1, 1, 1, 1)
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_submit_retained_final_reads_concurrent_cancel(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TLC-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    other = ExecutionService(UnitOfWork(oracle), actions=ActionService(UnitOfWork(oracle)))
    other.settings = execution_config
    actual = executor._view
    cancelled: list[Any] = []

    async def view(run_id: Any, *, _owner: Any = None) -> Any:
        assert _owner.has_retained_lease and _owner.connection is None
        assert (await execution_metadata(oracle, run_id))["execution"]["state"] == "queued"
        await previous.chain(oracle)
        cancelled.append(await asyncio.create_task(other.cancel(actor, run_id)))
        return await actual(run_id, _owner=_owner)

    monkeypatch.setattr(executor, "_view", view)
    observation = previous.EngineProof(factory)
    proof = ThreeTransactions(observation, oracle, actor, refs)
    proof.install(monkeypatch)
    with observation.watching():
        await observation.control(factory)
        result = await executor.submit(
            actor, plan.plan_id, plan.plan_digest, request_id="TLC-review-submit"
        )
    proof.check()
    assert result == cancelled[0] and result.state == "cancelled"
    assert result.cancel_requested and result.spent_tool_calls == 0 and result.receipts == ()
    await previous.chain(oracle)


async def denied_surface(observation: Any, owner: Any, operation: Any, child: bool) -> None:
    before = (len(observation.sql), list(observation.events), live_state(owner))
    with pytest.raises(RuntimeError):
        if child:
            await asyncio.create_task(operation())
        else:
            await operation()
    assert (len(observation.sql), observation.events, live_state(owner)) == before


@pytest.mark.asyncio
async def test_old_connection_same_physical_final_inert_same_and_child(factory: Any) -> None:
    observation = previous.EngineProof(factory)
    with observation.watching():
        await observation.control(factory)
        async with RequestConnection(factory) as owner:
            async with owner.mutation_phase() as session:
                old = await session.connection()
                token, sync = owner.generation, old.sync_connection
                assert await old.scalar(text("SELECT 31")) == 31
            assert owner.has_retained_lease and owner.connection is None
            async with owner.read_phase() as session:
                current = await session.connection()
                assert current is not old and current.sync_connection is sync
                assert old.request_generation is token and owner.generation is not token
                tx = await session.scalar(text("SELECT txid_current()"))
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
                                await old.exec_driver_sql("SELECT 97")
                            elif method in {"execute", "scalar", "scalars"}:
                                await getattr(old, method)(text("SELECT 97"))
                            else:
                                await getattr(old, method)()

                        await denied_surface(observation, owner, probe, child)
                assert await current.scalar(text("SELECT 37")) == 37
                assert await session.scalar(text("SELECT txid_current()")) == tx
                assert await session.connection() is current
        assert not observation.owned
        assert [k for k, _ in observation.events] == ["out", "in"]


@pytest.mark.asyncio
async def test_old_sessions_started_unstarted_tx_same_physical_final_inert(
    factory: Any, monkeypatch: Any
) -> None:
    observation = previous.EngineProof(factory)
    real_begin = _OwnerSession.begin
    facades: list[Any] = []

    def begin(session: Any) -> Any:
        result = real_begin(session)  # Original UOW starts this actual returned facade.
        facades.append(result)
        return result

    monkeypatch.setattr(_OwnerSession, "begin", begin)
    with observation.watching():
        await observation.control(factory)
        async with RequestConnection(factory) as owner:
            async with owner.mutation_phase() as old:
                assert await old.scalar(text("SELECT 41")) == 41
                sync = (await old.connection()).sync_connection
                active = facades[0]
                assert active.is_active
                unstarted = old.begin()
            assert not active.is_active and owner.has_retained_lease
            async with owner.read_phase() as current:
                assert current is not old
                assert (await current.connection()).sync_connection is sync
                tx = await current.scalar(text("SELECT txid_current()"))
                for child in (False, True):
                    for target, names in (
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
                        (active, ("commit", "rollback", "__aexit__")),
                        (unstarted, ("start", "commit", "rollback", "__aexit__")),
                    ):
                        for name in names:

                            async def probe(surface: Any = target, method: str = name) -> None:
                                observation.tasks.add(asyncio.current_task())
                                if method == "begin":
                                    surface.begin()
                                elif method == "__aexit__":
                                    await surface.__aexit__(None, None, None)
                                elif method in {"execute", "scalar", "scalars"}:
                                    await getattr(surface, method)(text("SELECT 101"))
                                else:
                                    await getattr(surface, method)()

                            await denied_surface(observation, owner, probe, child)
                assert await current.scalar(text("SELECT 43")) == 43
                assert await current.scalar(text("SELECT txid_current()")) == tx
        assert not observation.owned


@pytest.mark.asyncio
async def test_source_revision_after_commit_denies_fresh_final_disclosure(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    real = actions._metadata_plan
    committed: list[Any] = []

    async def metadata(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["_owner"].has_retained_lease
        committed.append(await counts(oracle, actor, request.idempotency_key))
        assert committed[-1] == (1, 1, 1, 1, 1)
        await adversarial.narrower_revision(oracle, tmp_path, actor, refs)
        await source_denied(oracle, actor, refs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(actions, "_metadata_plan", metadata)
    with pytest.raises(ActionError, match="source_unavailable"):
        await actions.create_plan(actor, request, request_id="TLC-revision")
    assert await counts(oracle, actor, request.idempotency_key) == committed[0]
    assert factory.kw["bind"].pool.checkedout() == 0
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_final_source_fence_role_expiry_denies_after_actual_wait(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    resource = await record_id(oracle, refs)
    await premise(oracle, actor, resource, True)
    request = requested(refs)
    ready, resume = asyncio.Event(), asyncio.Event()
    pid = asyncio.get_running_loop().create_future()
    real_metadata, real_read = actions._metadata_plan, RequestConnection.read_phase
    task = None

    async def metadata(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["_owner"].has_retained_lease
        ready.set()
        await resume.wait()  # Scheduling only; actual fence wait is proven below.
        return await real_metadata(*args, **kwargs)

    @asynccontextmanager
    async def read(owner: Any, *, commit: bool = False) -> Any:
        final = owner.has_retained_lease
        async with real_read(owner, commit=commit) as session:
            if final:
                pid.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions, "_metadata_plan", metadata)
    monkeypatch.setattr(RequestConnection, "read_phase", read)
    try:
        task = asyncio.create_task(actions.create_plan(actor, request, request_id="TLC-expiry"))
        await asyncio.wait_for(ready.wait(), 5)
        before = await counts(oracle, actor, request.idempotency_key)
        assert before == (1, 1, 1, 1, 1)
        due = datetime.now(UTC) + timedelta(seconds=0.4)
        await expired_role(oracle, actor, due)
        async with oracle() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            assert await blocker.scalar(
                text("SELECT version_id FROM record_versions WHERE version_id=:id FOR UPDATE"),
                {"id": refs[0].record_version_id},
            )
            resume.set()
            waiter = await asyncio.wait_for(pid, 5)
            await wait_blocked(oracle, waiter, blocker_pid)
            assert not task.done()
            await wait_after(oracle, due)
            current = await premise(oracle, actor, resource, False)
            assert Role.CURATOR not in current.roles and Role.STAFF in current.roles
            assert current.security_version == actor.security_version
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
        assert await counts(oracle, actor, request.idempotency_key) == before
        await previous.chain(oracle)
    finally:
        resume.set()
        await previous.cancel_join(task)


@pytest.mark.asyncio
async def test_postcommit_evidence_lifecycle_change_denies_final(
    factory: Any, oracle: Any, tmp_path: Path, monkeypatch: Any, local_boundaries: Any
) -> None:
    actions, actor, original, _, _ = await adversarial.domain(factory, tmp_path)
    async with oracle() as session:
        key = await session.scalar(
            text("""
            SELECT evidence_key FROM evidence_spans WHERE record_version_id=:id
            AND lifecycle='active' ORDER BY span_id LIMIT 1
        """),
            {"id": original[0].record_version_id},
        )
    assert key is not None
    refs = (original[0].model_copy(update={"evidence_key": key}),)
    request = requested(refs)
    actual = actions._metadata_plan
    before: list[Any] = []

    async def metadata(*args: Any, **kwargs: Any) -> Any:
        assert kwargs["_owner"].has_retained_lease
        before.append(await counts(oracle, actor, request.idempotency_key))
        assert before[-1] == (1, 1, 1, 1, 1)
        async with oracle() as session, session.begin():
            changed = await session.execute(
                text("""
                UPDATE evidence_spans SET lifecycle='superseded'
                WHERE record_version_id=:id AND evidence_key=:key AND lifecycle='active'
            """),
                {"id": refs[0].record_version_id, "key": key},
            )
            assert changed.rowcount >= 1
            assert await session.scalar(
                text("""
                SELECT current_version_id=:id FROM records WHERE source_key=:source
                  AND lifecycle='active'
            """),
                {"id": refs[0].record_version_id, "source": refs[0].source_key},
            )
        await source_denied(oracle, actor, refs)
        return await actual(*args, **kwargs)

    monkeypatch.setattr(actions, "_metadata_plan", metadata)
    with pytest.raises(ActionError, match="source_unavailable"):
        await actions.create_plan(actor, request, request_id="TLC-evidence")
    assert await counts(oracle, actor, request.idempotency_key) == before[0]
    assert factory.kw["bind"].pool.checkedout() == 0
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_repeated_cancel_transition_joins_cleanup_no_final(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TLC-cancel-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    actual_mutation, actual_close = RequestConnection.mutation_phase, AsyncSession.close
    closing, release = asyncio.Event(), asyncio.Event()
    targets: list[Any] = []
    calls: list[Any] = []
    owners: list[Any] = []
    final: list[Any] = []
    actual_view = executor._view

    @asynccontextmanager
    async def mutation(owner: Any) -> Any:
        owners.append(owner)
        async with actual_mutation(owner) as session:
            targets.append(session)
            yield session

    async def close(session: Any) -> None:
        if targets and session is targets[0]:
            calls.append(asyncio.current_task())
            closing.set()
            await release.wait()  # Controlled terminal scheduling, not a SQL wait.
        await actual_close(session)

    async def view(*args: Any, **kwargs: Any) -> Any:
        final.append(True)
        return await actual_view(*args, **kwargs)

    observation = previous.EngineProof(factory)
    task = None
    monkeypatch.setattr(RequestConnection, "mutation_phase", mutation)
    monkeypatch.setattr(AsyncSession, "close", close)
    monkeypatch.setattr(executor, "_view", view)
    with observation.watching():
        await observation.control(factory)

        async def run() -> Any:
            observation.tasks.add(asyncio.current_task())
            return await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="TLC-transition-cancel"
            )

        try:
            task = asyncio.create_task(run())
            await asyncio.wait_for(closing.wait(), 5)
            before = await execution_metadata(oracle, plan.run_id)
            assert before["execution"]["state"] == "queued"
            await previous.chain(oracle)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
            assert not task.done() and len(calls) == 1 and not final
            assert len(observation.owned) == 1
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert calls[0].done() and not observation.owned and not final
            assert owners[0].mutation_started and owners[0].poisoned
            assert not owners[0].fallback_allowed
            assert await execution_metadata(oracle, plan.run_id) == before
        finally:
            release.set()
            await previous.cancel_join(task)
    monkeypatch.setattr(executor, "_view", actual_view)
    await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="TLC-cancel-reconcile")
    assert await execution_metadata(oracle, plan.run_id) == before


@pytest.mark.asyncio
async def test_original_final_query_lock_timeout_preserves_commit_no_replay(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TLC-timeout-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    actual_view, actual_read = executor._view, RequestConnection.read_phase
    ready, resume = asyncio.Event(), asyncio.Event()
    pid = asyncio.get_running_loop().create_future()
    view_calls: list[Any] = []
    task = None

    async def view(run_id: Any, *, _owner: Any = None) -> Any:
        assert _owner.has_retained_lease and _owner.connection is None
        view_calls.append(run_id)
        ready.set()
        await resume.wait()
        return await actual_view(run_id, _owner=_owner)

    @asynccontextmanager
    async def read(owner: Any, *, commit: bool = False) -> Any:
        final = owner.has_retained_lease
        async with actual_read(owner, commit=commit) as session:
            if final:
                pid.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(executor, "_view", view)
    monkeypatch.setattr(RequestConnection, "read_phase", read)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/actions/execute",
            "headers": [],
            "state": {"request_id": "TLC-real-final-lock"},
        }
    )
    try:
        task = asyncio.create_task(
            bounded(
                request,
                actor,
                executor,
                executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="TLC-real-final-lock"
                ),
            )
        )
        await asyncio.wait_for(ready.wait(), 5)
        before = await execution_metadata(oracle, plan.run_id)
        assert before["execution"]["state"] == "queued"
        await previous.chain(oracle)
        async with oracle() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(text("LOCK TABLE action_executions IN ACCESS EXCLUSIVE MODE"))
            resume.set()
            await wait_blocked(oracle, await asyncio.wait_for(pid, 5), blocker_pid)
            assert not task.done()
            response = await asyncio.wait_for(task, 5)
            assert response.status_code == 503 and b"action_operation_timeout" in response.body
            assert b"Check durable action status before resubmitting" in response.body
            assert view_calls == [plan.run_id] and factory.kw["bind"].pool.checkedout() == 0
        assert await execution_metadata(oracle, plan.run_id) == before
    finally:
        resume.set()
        await previous.cancel_join(task)
        monkeypatch.setattr(executor, "_view", actual_view)
        monkeypatch.setattr(RequestConnection, "read_phase", actual_read)
    assert (await executor.status(actor, plan.run_id)).state == "queued"
    await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="TLC-lock-reconcile")
    assert await execution_metadata(oracle, plan.run_id) == before
    await previous.chain(oracle)


class AckDeliveryFault(RuntimeError):
    """Controlled delivery failure AFTER genuine installed driver COMMIT."""


@pytest.mark.asyncio
async def test_real_commit_ack_delivery_fault_blocks_final_and_replay(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TLC-ACK-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    real_mutation = RequestConnection.mutation_phase
    real_commit = AsyncAdapt_asyncpg_connection._commit_and_discard
    actual_view = executor._view
    target: list[Any] = []
    owners: list[Any] = []
    delegated: list[Any] = []
    finals: list[Any] = []
    committed, release = asyncio.Event(), asyncio.Event()
    task = None

    @asynccontextmanager
    async def mutation(owner: Any) -> Any:
        owners.append(owner)
        async with real_mutation(owner) as session:
            target.append((await session.connection()).sync_connection.connection.dbapi_connection)
            yield session

    async def delivery(adapter: Any) -> None:
        await real_commit(adapter)  # Genuine driver operation, independently witnessed below.
        if target and adapter is target[0]:
            delegated.append(adapter)
            committed.set()
            await release.wait()
            adapter._connection.terminate()  # Exact owned synthetic driver, NOT TCP-loss proof.
            assert adapter._connection.is_closed()
            raise AckDeliveryFault("controlled post-COMMIT delivery")

    async def view(*args: Any, **kwargs: Any) -> Any:
        finals.append(True)
        return await actual_view(*args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(RequestConnection, "mutation_phase", mutation)
        scoped.setattr(AsyncAdapt_asyncpg_connection, "_commit_and_discard", delivery)
        scoped.setattr(executor, "_view", view)
        try:
            task = asyncio.create_task(
                executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="TLC-real-ACK-fault"
                )
            )
            await asyncio.wait_for(committed.wait(), 5)
            before = await execution_metadata(oracle, plan.run_id)
            assert before["execution"]["state"] == "queued"
            await previous.chain(oracle)
            assert not task.done() and delegated == target
            release.set()
            with pytest.raises(AckDeliveryFault):
                await asyncio.wait_for(task, 5)
            assert not finals and owners[0].mutation_started and not owners[0].fallback_allowed
            assert not owners[0].has_retained_lease and owners[0].connection is None
            assert factory.kw["bind"].pool.checkedout() == 0
            assert await execution_metadata(oracle, plan.run_id) == before
        finally:
            release.set()
            await previous.cancel_join(task)
    assert (await executor.status(actor, plan.run_id)).state == "queued"
    await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="TLC-ACK-reconcile")
    assert await execution_metadata(oracle, plan.run_id) == before
    await previous.chain(oracle)
