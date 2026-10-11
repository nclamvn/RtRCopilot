"""Two independent real SQL controls; no simulated HTTP-503 or commit outcome.

Only Technical executes. Terminal pauses are controlled scheduling, not SQL
locks or TCP loss. Actual references and the original UOW remain authoritative.
"""

import asyncio
import inspect
import json
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import audit_tail_observer as audit_module
import phase_profiler as phase_module
import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
import test_action_transaction_scoped_lease_integration as previous
from httpx import ASGITransport, AsyncClient
from minimal_observer import FAULT_KEYS, MinimalObserver, decoded_records
from pool_boundary_observer import PoolBoundaryObserver
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from test_action_checkout_audit_tail_integration import execution_metadata
from test_action_source_batching_integration import requested
from test_pool_boundary_review_integration import clean as clean_boundary
from test_pool_boundary_review_integration import pending

from rtr_copilot.actions.api import action_service
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_api import execution_service
from rtr_copilot.actions.request_connection import RequestConnection
from rtr_copilot.api.main import app
from rtr_copilot.ingestion.api import file_subject

pytestmark = fixtures.pytestmark


REFERENCE_LABELS = {
    "phase.finish_phase",
    "phase.serialize",
    "phase.write",
    "phase.flush",
    "audit.emit",
    "audit.serialize",
    "audit.write",
    "audit.flush",
}


def omitted_bindings(boundary: Any) -> list[Any]:
    return [
        (
            target,
            name,
            name in vars(target),
            vars(target).get(name),
            inspect.getattr_static(target, name),
        )
        for target, names in (
            (boundary, ("begin", "finish", "request", "resource")),
            (boundary.ids, ("get",)),
        )
        for name in names
    ]


def assert_omitted_unchanged(bindings: list[Any]) -> None:
    for target, name, present, raw, descriptor in bindings:
        assert (name in vars(target)) is present
        assert vars(target).get(name) is raw
        assert inspect.getattr_static(target, name) is descriptor


@pytest_asyncio.fixture(loop_scope="session")
async def factory() -> Any:
    async for value in previous.factory.__wrapped__():
        yield value


@pytest_asyncio.fixture(loop_scope="session")
async def oracle(factory: Any) -> Any:
    async for value in previous.oracle.__wrapped__(factory):
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: Any, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.fixture
def execution_config(monkeypatch: Any) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


def clean_exposure(snapshot: Any) -> None:
    assert set(snapshot["integrity"]) == set(FAULT_KEYS)
    assert not any(snapshot["integrity"].values()), snapshot["integrity"]
    assert snapshot["records"], "unwired empty observation cannot pass a positive SQL control"
    records = decoded_records(snapshot)
    assert all(
        row["label"].startswith("R9.recording@") or row["label"] in REFERENCE_LABELS
        for row in records
    ), "a separately patched helper or original delegate leaked into selected exposure"
    ids = [row["span_id"] for row in records]
    assert len(ids) == len(set(ids))
    for row in records:
        assert type(row["start_ns"]) is int and type(row["end_ns"]) is int
        assert row["end_ns"] >= row["start_ns"]
        if row["task_id"] is None:
            assert row["request_id"] is None and row["origin"] in {
                "timer_inherited_unassigned",
                "outside_loop_unassigned",
            }
        else:
            assert type(row["task_id"]) is int and row["task_id"] > 0
        assert not {"parameters", "sql_text", "body", "resource", "task"} & row.keys()


@pytest.mark.asyncio
async def test_minimal_real_action_shapes_and_complete_reference_labels(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    """Actual existing API and profiler finally path, not copied HTTP logic."""
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    engine = factory.kw["bind"]
    original_overrides = dict(app.dependency_overrides)
    real_outcomes: list[Any] = []

    async def auth() -> Any:
        return actor

    app.dependency_overrides[file_subject] = auth
    app.dependency_overrides[action_service] = lambda: actions
    app.dependency_overrides[execution_service] = lambda: executor
    try:
        for mode in (False, True):
            folder = tmp_path / ("reference-on" if mode else "reference-off")
            folder.mkdir()
            phase = phase_module.PhaseProfiler(engine, folder)
            tail = audit_module.AuditTailObserver(engine, folder)
            boundary = PoolBoundaryObserver(engine)
            exposure = MinimalObserver()
            sql: list[tuple[str, str]] = []
            pool: list[tuple[str, str]] = []

            def statement(*args: Any, sql: Any = sql) -> None:
                current = phase_module.active.get()
                if current is not None:
                    sql.append((current["request_id"], args[2]))

            def checkout(*_args: Any, pool: Any = pool) -> None:
                current = phase_module.active.get()
                if current is not None:
                    pool.append((current["request_id"], "out"))

            def checkin(*_args: Any, pool: Any = pool) -> None:
                current = phase_module.active.get()
                if current is not None:
                    pool.append((current["request_id"], "in"))

            event.listen(engine.sync_engine, "before_cursor_execute", statement)
            event.listen(engine.sync_engine.pool, "checkout", checkout)
            event.listen(engine.sync_engine.pool, "checkin", checkin)
            phase.install()
            boundary.install()
            tail.install()
            omitted = omitted_bindings(boundary)
            recording_present = "recording" in vars(boundary)
            recording_raw = vars(boundary).get("recording")
            recording_descriptor = inspect.getattr_static(boundary, "recording")
            if mode:
                exposure.attach_boundary(boundary)
                exposure.attach_phase(phase, phase_module)
                exposure.attach_audit(tail, audit_module)
            assert_omitted_unchanged(omitted)
            request = requested(refs)
            case = int(mode)
            admission_id = f"tip054-latency-1-{case}-admission"
            submit_id = f"tip054-latency-1-{case}-submit"
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://synthetic.test"
                ) as client:
                    plan = await client.post(
                        "/api/v1/actions/plans",
                        json=request.model_dump(mode="json"),
                        headers={"X-Request-ID": admission_id},
                    )
                    assert plan.status_code == 201, plan.text
                    assert (folder / "phase-requests.jsonl").stat().st_size > 0
                    result = await client.post(
                        f"/api/v1/actions/plans/{plan.json()['plan_id']}/execute",
                        json={"expected_plan_digest": plan.json()["plan_digest"]},
                        headers={"X-Request-ID": submit_id},
                    )
                    assert result.status_code == 202, result.text
                    body = result.json()
                assert count_id(sql, admission_id) == 29
                assert count_id(sql, submit_id) == 22
                assert [kind for key, kind in pool if key == admission_id] == ["out", "in"] * 2
                assert [kind for key, kind in pool if key == submit_id] == ["out", "in"] * 2
                assert body["state"] == "queued" and body["spent_tool_calls"] == 0
                assert body["receipts"] == []
                actual = await execution_metadata(oracle, uuid.UUID(plan.json()["run_id"]))
                assert actual["execution"]["state"] == "queued"
                assert actual["events"] == [] and actual["receipts"] == []
                await previous.chain(oracle)
                assert_omitted_unchanged(omitted)
                real_outcomes.append(
                    (
                        body["state"],
                        body["spent_tool_calls"],
                        len(actual["events"]),
                        len(actual["receipts"]),
                    )
                )
            finally:
                # Exact NEW driver order: references finish before new restoration.
                try:
                    try:
                        tail.close()
                    finally:
                        try:
                            boundary.close()
                        finally:
                            phase.close()
                finally:
                    try:
                        exposure.close()
                    finally:
                        event.remove(engine.sync_engine, "before_cursor_execute", statement)
                        event.remove(engine.sync_engine.pool, "checkout", checkout)
                        event.remove(engine.sync_engine.pool, "checkin", checkin)
            clean_boundary(boundary.snapshot())
            assert_omitted_unchanged(omitted)
            assert ("recording" in vars(boundary)) is recording_present
            assert vars(boundary).get("recording") is recording_raw
            assert inspect.getattr_static(boundary, "recording") is recording_descriptor
            originals = [
                json.loads(line)
                for line in (folder / "phase-requests.jsonl").read_bytes().splitlines()
            ]
            assert {row["request_id"] for row in originals} == {admission_id, submit_id}
            assert all(row["closed"] and row["end_ns"] is not None for row in originals)
            assert audit_module.json.dumps is json.dumps and phase_module.json.dumps is json.dumps
            transactions = [
                json.loads(line)
                for line in (folder / "audit-transactions.jsonl").read_bytes().splitlines()
            ]
            assert transactions and all(row["emitted"] for row in transactions)
            assert (
                len(
                    [r for r in boundary.snapshot()["events"] if r["name"] == "adapter._async_ping"]
                )
                > 0
            )
            if mode:
                snapshot = exposure.snapshot()
                clean_exposure(snapshot)
                measured = decoded_records(snapshot)
                assert {r["request_id"] for r in measured if r["request_id"] is not None} == {
                    admission_id,
                    submit_id,
                }
                assert all(r["error_type"] is None for r in measured)
                assert any(r["label"].startswith("R9.recording@") for r in measured)
                for original in originals:
                    scoped = [r for r in measured if r["request_id"] == original["request_id"]]
                    by_label = {
                        name: [r for r in scoped if r["label"] == name]
                        for name in (
                            "phase.finish_phase",
                            "phase.serialize",
                            "phase.write",
                            "phase.flush",
                            "audit.emit",
                            "audit.serialize",
                            "audit.write",
                            "audit.flush",
                        )
                    }
                    assert all(by_label.values()), by_label
                    assert len(by_label["phase.finish_phase"]) == len(original["phases"])
                    assert (
                        len(by_label["phase.serialize"])
                        == len(by_label["phase.write"])
                        == len(by_label["phase.flush"])
                        == 1
                    )
                    for name in (
                        "phase.finish_phase",
                        "phase.serialize",
                        "phase.write",
                        "phase.flush",
                    ):
                        assert all(
                            r["reference_closed"] is True
                            and r["origin"] == "post_http_reference"
                            and r["start_ns"] >= original["end_ns"]
                            for r in by_label[name]
                        )
                    serialize, write, flush = (
                        by_label[name][0]
                        for name in ("phase.serialize", "phase.write", "phase.flush")
                    )
                    assert (
                        serialize["end_ns"]
                        <= write["start_ns"]
                        <= write["end_ns"]
                        <= flush["start_ns"]
                    )
                    assert (
                        len(by_label["audit.emit"])
                        == len(by_label["audit.serialize"])
                        == len(by_label["audit.write"])
                        == len(by_label["audit.flush"])
                    )
                    assert all(r["origin"] == "audit_record" for r in by_label["audit.emit"])
                    assert len(by_label["audit.emit"]) == sum(
                        row["request_id"] == original["request_id"] for row in transactions
                    )
                    for emit in by_label["audit.emit"]:
                        children = {
                            name: [r for r in by_label[name] if emit["span_id"] in r["parent_ids"]]
                            for name in ("audit.serialize", "audit.write", "audit.flush")
                        }
                        assert all(len(rows) == 1 for rows in children.values())
                        serialize, write, flush = (children[name][0] for name in children)
                        assert emit["start_ns"] <= serialize["start_ns"]
                        assert serialize["end_ns"] <= write["start_ns"]
                        assert (
                            write["end_ns"]
                            <= flush["start_ns"]
                            <= flush["end_ns"]
                            <= emit["end_ns"]
                        )
            assert engine.pool.checkedout() == 0
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
    assert real_outcomes[0] == real_outcomes[1]


def count_id(rows: Any, key: str) -> int:
    return sum(request == key for request, _ in rows)


@pytest.mark.asyncio
async def test_minimal_real_error_queue_cancel_and_committed_cleanup(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    monkeypatch: Any,
    local_boundaries: Any,
    execution_config: Any,
) -> None:
    engine = factory.kw["bind"]
    boundary = PoolBoundaryObserver(engine)
    exposure = MinimalObserver()
    delegated_errors: list[Any] = []

    def failed(context: Any) -> None:
        delegated_errors.append(context.sqlalchemy_exception)

    event.listen(engine.sync_engine, "handle_error", failed)
    boundary.install()
    omitted = omitted_bindings(boundary)
    exposure.attach_boundary(boundary)
    assert_omitted_unchanged(omitted)
    task = None
    release = asyncio.Event()
    try:
        with boundary.scope("r12-real-error"), exposure.scope("r12-real-error"):
            async with factory() as session:
                with pytest.raises(DBAPIError) as caught:
                    await session.scalar(text("SELECT 1 / 0"))
                assert caught.value is delegated_errors[-1]
                assert caught.value.orig.sqlstate == "22012"
        async with AsyncExitStack() as holders:
            for _ in range(10):
                await holders.enter_async_context(engine.connect())
            assert engine.pool.checkedout() == 10
            queue = engine.sync_engine.pool._pool._queue

            async def acquire() -> None:
                with (
                    boundary.scope("r12-real-queued-cancel"),
                    exposure.scope("r12-real-queued-cancel"),
                ):
                    async with engine.connect():
                        pytest.fail("a saturated cancelled getter acquired a slot")

            task = asyncio.create_task(acquire())
            future = await pending(queue, task)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert future.cancelled() and future not in queue._getters
            assert engine.pool.checkedout() == 10
        assert engine.pool.checkedout() == 0
        with boundary.scope("r12-real-recovery"), exposure.scope("r12-real-recovery"):
            async with factory() as session:
                assert await session.scalar(text("SELECT 19")) == 19

        actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
        plan = await actions.create_plan(actor, requested(refs), request_id="r12-cleanup-plan")
        executor = ExecutionService(actions.uow, actions=actions)
        executor.settings = execution_config
        real_mutation, real_close = RequestConnection.mutation_phase, AsyncSession.close
        closing = asyncio.Event()
        sessions: list[Any] = []
        owners: list[Any] = []
        terminal_tasks: list[Any] = []
        original_view = executor._view
        views: list[Any] = []

        @asynccontextmanager
        async def mutation(owner: Any) -> Any:
            owners.append(owner)
            async with real_mutation(owner) as session:
                sessions.append(session)
                yield session

        async def close(session: Any) -> None:
            if sessions and session is sessions[0]:
                terminal_tasks.append(asyncio.current_task())
                closing.set()
                await release.wait()  # Scheduling only; actual close below, no outcome mock.
            await real_close(session)

        async def view(*args: Any, **kwargs: Any) -> Any:
            views.append(True)
            return await original_view(*args, **kwargs)

        monkeypatch.setattr(RequestConnection, "mutation_phase", mutation)
        monkeypatch.setattr(AsyncSession, "close", close)
        monkeypatch.setattr(executor, "_view", view)

        async def submit() -> Any:
            with (
                boundary.scope("r12-real-committed-cleanup"),
                exposure.scope("r12-real-committed-cleanup"),
            ):
                return await executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="r12-real-commit"
                )

        task = asyncio.create_task(submit())
        await asyncio.wait_for(closing.wait(), 5)
        before = await execution_metadata(oracle, plan.run_id)
        assert before["execution"]["state"] == "queued"
        await previous.chain(oracle)
        assert len(terminal_tasks) == 1 and terminal_tasks[0] is owners[0].terminal_task
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not views and len(terminal_tasks) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert terminal_tasks[0].done() and not views
        assert owners[0].mutation_started and owners[0].poisoned
        assert not owners[0].fallback_allowed and owners[0].terminal_task is None
        assert engine.pool.checkedout() == 0
        assert await execution_metadata(oracle, plan.run_id) == before
        with pytest.raises(RuntimeError):
            await sessions[0].scalar(text("SELECT 31"))
    finally:
        release.set()
        await previous.cancel_join(task)
        try:
            boundary.close()
        finally:
            try:
                exposure.close()
            finally:
                event.remove(engine.sync_engine, "handle_error", failed)
    clean_boundary(boundary.snapshot())
    clean_exposure(exposure.snapshot())
    assert_omitted_unchanged(omitted)
    assert any(
        r["name"] == "queue.get" and r["error_type"] == "CancelledError"
        for r in boundary.snapshot()["events"]
    )
    assert any(
        r["name"] == "owner.join_terminal" and r["error_type"] == "CancelledError"
        for r in boundary.snapshot()["events"]
    )
    assert not any("http_status" in r for r in decoded_records(exposure.snapshot()))
