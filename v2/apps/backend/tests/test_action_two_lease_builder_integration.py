"""Eight real R7 comparator controls; controlled ACK faults are not network proof."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from sqlalchemy import text
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection
from sqlalchemy.ext.asyncio import AsyncConnection
from test_action_checkout_audit_tail_integration import counts, execution_metadata
from test_action_evidence_serialization_integration import shared
from test_action_source_batching_integration import requested

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.request_connection import RequestConnection, _OwnerSession
from rtr_copilot.actions.service import ActionService
from rtr_copilot.db.uow import MaintenanceActive, UnitOfWork

pytestmark = previous.pytestmark


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


async def prepared(factory: Any, tmp_path: Path, config: Any) -> Any:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(actor, requested(refs), request_id="TLC-builder-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = config
    return actions, actor, refs, plan, executor


async def locks_free(oracle: Any, actor: Any, refs: Any) -> None:
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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "submit"])
async def test_two_physical_leases_three_fresh_transactions_and_independent_locks(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
    operation: str,
) -> None:
    actions, actor, refs, plan, executor = await prepared(factory, tmp_path, execution_config)
    observation = previous.EngineProof(factory)
    proof = previous.PhaseProof(observation)
    proof.install(monkeypatch)
    real_read = RequestConnection.read_phase
    witnessed: list[Any] = []

    @asynccontextmanager
    async def read(owner: Any, *, commit: bool = False) -> Any:
        if owner.has_retained_lease:
            await locks_free(oracle, actor, refs)
            await previous.chain(oracle)
            assert owner.connection is None and not owner._retained_connection.in_transaction()
            witnessed.append(owner)
        async with real_read(owner, commit=commit) as session:
            connection = await session.connection()
            assert connection is owner.connection
            assert await session.scalar(text("SELECT 47")) == 47
            assert await session.connection() is connection
            yield session
            assert await session.connection() is connection

    monkeypatch.setattr(RequestConnection, "read_phase", read)
    with observation.watching():
        await observation.control(factory)
        if operation == "create":
            request = requested(refs)
            result = await actions.create_plan(actor, request, request_id="TLC-builder-create")
            assert result.state == "contract_ready"
            assert await counts(oracle, actor, request.idempotency_key) == (1, 1, 1, 1, 2)
        else:
            result = await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="TLC-builder-submit"
            )
            assert result.state == "queued"
            assert (await execution_metadata(oracle, plan.run_id))["execution"]["state"] == "queued"
    proof.assert_three()
    assert len(witnessed) == 1
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_nine_external_slots_do_not_prevent_fresh_cancelled_final_view(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    actions, actor, refs, plan, executor = await prepared(factory, tmp_path, execution_config)
    independent_actions = ActionService(UnitOfWork(oracle))
    independent = ExecutionService(UnitOfWork(oracle), actions=independent_actions)
    independent.settings = execution_config
    real_view = executor._view
    cancelled: list[Any] = []
    engine = factory.kw["bind"]

    async def view(run_id: Any, *, _owner: Any = None) -> Any:
        assert _owner is not None and _owner.has_retained_lease
        assert _owner.connection is None and engine.pool.checkedout() == 10
        await locks_free(oracle, actor, refs)
        assert (await execution_metadata(oracle, run_id))["execution"]["state"] == "queued"
        cancelled.append(await independent.cancel(actor, run_id))
        return await real_view(run_id, _owner=_owner)

    monkeypatch.setattr(executor, "_view", view)
    observation = previous.EngineProof(factory)

    async def submit() -> Any:
        observation.tasks.add(asyncio.current_task())
        return await executor.submit(
            actor, plan.plan_id, plan.plan_digest, request_id="TLC-nine-slots"
        )

    async with AsyncExitStack() as stack:
        for _ in range(9):
            await stack.enter_async_context(engine.connect())
        assert engine.pool.checkedout() == 9
        with observation.watching():
            await observation.control(factory)
            result = await asyncio.wait_for(submit(), 5)
        assert result == cancelled[0] and result.state == "cancelled"
        assert result.cancel_requested and result.spent_tool_calls == 0
        assert [kind for kind, _ in observation.events] == ["out", "in"] * 2
        assert not observation.owned and engine.pool.checkedout() == 9
    assert engine.pool.checkedout() == 0
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_original_uow_maintenance_between_initial_and_mutation_rolls_back(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    real_initial = actions._initial_plan
    before = await counts(oracle, actor, request.idempotency_key)

    async def initial(*args: Any, **kwargs: Any) -> Any:
        result = await real_initial(*args, **kwargs)
        owner = kwargs["_owner"]
        assert owner.connection is None and not owner.has_retained_lease
        assert factory.kw["bind"].pool.checkedout() == 0
        async with oracle() as session, session.begin():
            await session.execute(text("UPDATE maintenance_state SET enabled=true WHERE singleton"))
        return result

    monkeypatch.setattr(actions, "_initial_plan", initial)
    try:
        with pytest.raises(MaintenanceActive, match="maintenance_active"):
            await actions.create_plan(actor, request, request_id="TLC-maintenance")
        assert await counts(oracle, actor, request.idempotency_key) == before
        assert factory.kw["bind"].pool.checkedout() == 0
    finally:
        async with oracle() as session, session.begin():
            await session.execute(
                text("UPDATE maintenance_state SET enabled=false WHERE singleton")
            )
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_same_binding_old_handles_cannot_query_or_terminate_fresh_generation(
    factory: Any,
    monkeypatch: Any,
) -> None:
    observation = previous.EngineProof(factory)
    started: list[Any] = []
    real_begin = _OwnerSession.begin

    def begin(session: Any) -> Any:
        transaction = real_begin(session)
        started.append(transaction)
        return transaction

    monkeypatch.setattr(_OwnerSession, "begin", begin)
    with observation.watching():
        await observation.control(factory)
        async with RequestConnection(factory) as owner:
            async with owner.read_phase() as initial:
                assert await initial.scalar(text("SELECT 53")) == 53
            async with owner.mutation_phase() as old:
                transaction = started[-1]  # Actual original-UOW entered facade.
                carrier = await old.connection()
                token = carrier.request_generation
                unstarted = old.begin()
                assert await old.scalar(text("SELECT 59")) == 59
            assert owner.has_retained_lease and owner.connection is None
            async with owner.read_phase() as current:
                facade = await current.connection()
                assert facade is not carrier and facade.sync_connection is carrier.sync_connection
                assert (
                    carrier.request_generation is token and facade.request_generation is not token
                )
                txid = await current.scalar(text("SELECT txid_current()"))
                for child in (False, True):
                    for target, name, args in (
                        (carrier, "execute", (text("SELECT 101"),)),
                        (carrier, "scalar", (text("SELECT 101"),)),
                        (carrier, "scalars", (text("SELECT 101"),)),
                        (carrier, "exec_driver_sql", ("SELECT 101",)),
                        (carrier, "start", ()),
                        (carrier, "close", ()),
                        (carrier, "invalidate", ()),
                        (old, "scalar", (text("SELECT 101"),)),
                        (old, "close", ()),
                        (old, "__aexit__", (None, None, None)),
                        (unstarted, "start", ()),
                        (unstarted, "commit", ()),
                        (unstarted, "rollback", ()),
                        (transaction, "commit", ()),
                        (transaction, "rollback", ()),
                        (transaction, "__aexit__", (None, None, None)),
                        (owner, "release_phase", (carrier, None)),
                        (owner, "close_connection", (carrier,)),
                    ):

                        async def probe(t: Any = target, n: str = name, a: Any = args) -> None:
                            observation.tasks.add(asyncio.current_task())
                            await getattr(t, n)(*a)

                        state = (owner.connection, owner.session, owner.generation, owner.poisoned)
                        before = (len(observation.sql), list(observation.events))
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
                            owner.poisoned,
                        ) == state
                assert await current.connection() is facade
                assert await current.scalar(text("SELECT txid_current()")) == txid
                assert await facade.scalar(text("SELECT 61")) == 61
        assert not observation.owned and not owner.poisoned


@pytest.mark.asyncio
async def test_cancel_in_acknowledged_gap_joins_exact_physical_cleanup(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    _, actor, _, plan, executor = await prepared(factory, tmp_path, execution_config)
    reached, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    captured: list[Any] = []
    calls: list[Any] = []
    real_close = AsyncConnection.close

    async def view(run_id: Any, *, _owner: Any = None) -> Any:
        assert _owner.has_retained_lease and _owner.connection is None
        captured.append(_owner._retained_connection)
        reached.set()
        await asyncio.Event().wait()

    async def close(connection: Any) -> None:
        if captured and connection is captured[0]:
            calls.append((connection, asyncio.current_task()))
            closing.set()
            await release.wait()
        await real_close(connection)

    monkeypatch.setattr(executor, "_view", view)
    monkeypatch.setattr(AsyncConnection, "close", close)
    task = asyncio.create_task(
        executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="TLC-gap-cancel")
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)
        before = await execution_metadata(oracle, plan.run_id)
        assert before["execution"]["state"] == "queued"
        await locks_free(oracle, actor, plan.payload.source_refs)
        task.cancel()
        await asyncio.wait_for(closing.wait(), 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and len(calls) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert calls[0][1].done() and factory.kw["bind"].pool.checkedout() == 0
        assert await execution_metadata(oracle, plan.run_id) == before
    finally:
        release.set()
        await previous.cancel_join(task)
    await previous.chain(oracle)


@pytest.mark.asyncio
async def test_real_commit_delivery_fault_cannot_install_final_eligibility(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    _, actor, _, plan, executor = await prepared(factory, tmp_path, execution_config)
    committed, release = asyncio.Event(), asyncio.Event()
    target: list[Any] = []
    owners: list[Any] = []
    views: list[Any] = []
    real_phase = RequestConnection.mutation_phase
    real_commit = AsyncAdapt_asyncpg_connection._commit_and_discard

    class DeliveryFault(RuntimeError):
        pass

    @asynccontextmanager
    async def mutation(owner: Any) -> Any:
        owners.append(owner)
        async with real_phase(owner) as session:
            target.append((await session.connection()).sync_connection.connection.dbapi_connection)
            yield session

    async def delivery(adapter: Any) -> None:
        await real_commit(adapter)
        if target and adapter is target[0]:
            committed.set()
            await release.wait()
            adapter._connection.terminate()  # Exact synthetic driver, test-only ACK delivery fault.
            raise DeliveryFault("controlled after-driver-COMMIT delivery")

    async def view(*args: Any, **kwargs: Any) -> Any:
        views.append(args)
        raise AssertionError("uncertain mutation must never enter final view")

    monkeypatch.setattr(RequestConnection, "mutation_phase", mutation)
    monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "_commit_and_discard", delivery)
    monkeypatch.setattr(executor, "_view", view)
    task = asyncio.create_task(
        executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="TLC-ACK-uncertain")
    )
    try:
        await asyncio.wait_for(committed.wait(), 5)
        before = await execution_metadata(oracle, plan.run_id)
        assert before["execution"]["state"] == "queued" and not task.done()
        await previous.chain(oracle)
        release.set()
        with pytest.raises(DeliveryFault):
            await asyncio.wait_for(task, 5)
        assert not views and len(owners) == 1
        assert not owners[0].has_retained_lease and not owners[0].fallback_allowed
        assert factory.kw["bind"].pool.checkedout() == 0
        assert await execution_metadata(oracle, plan.run_id) == before
    finally:
        release.set()
        await previous.cancel_join(task)


@pytest.mark.asyncio
async def test_evidence_superseded_after_commit_blocks_fresh_final_create_metadata(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    async with oracle() as session:
        span = (
            (
                await session.execute(
                    text("""
            SELECT span_id,evidence_key FROM evidence_spans
            WHERE record_version_id=:version AND lifecycle='active'
            ORDER BY span_id LIMIT 1
        """),
                    {"version": refs[0].record_version_id},
                )
            )
            .mappings()
            .one()
        )
    refs = (refs[0].model_copy(update={"evidence_key": span["evidence_key"]}),)
    request = requested(refs)
    real_metadata = actions._metadata_plan
    preserved: list[Any] = []

    async def metadata(*args: Any, **kwargs: Any) -> Any:
        owner = kwargs["_owner"]
        assert owner.has_retained_lease and owner.connection is None
        before = await counts(oracle, actor, request.idempotency_key)
        assert before == (1, 1, 1, 1, 1)
        await locks_free(oracle, actor, refs)
        async with oracle() as session, session.begin():
            changed = await session.execute(
                text("""
                UPDATE evidence_spans SET lifecycle='superseded'
                WHERE record_version_id=:version AND evidence_key=:key AND lifecycle='active'
                RETURNING span_id
            """),
                {"version": refs[0].record_version_id, "key": span["evidence_key"]},
            )
            assert span["span_id"] in changed.scalars().all()
        result = await shared(oracle, actor, refs)
        assert result.gaps or not result.sources
        preserved.append(before)
        return await real_metadata(*args, **kwargs)

    monkeypatch.setattr(actions, "_metadata_plan", metadata)
    with pytest.raises(ActionError):
        await actions.create_plan(actor, request, request_id="TLC-final-evidence")
    assert len(preserved) == 1
    assert await counts(oracle, actor, request.idempotency_key) == preserved[0]
    assert factory.kw["bind"].pool.checkedout() == 0
    await previous.chain(oracle)
