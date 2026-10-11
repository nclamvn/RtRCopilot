"""Independent finite R2 checkout/audit-tail SQL regressions.

Only synthetic application-role SQL is used. Engine/scalar/execute observations
delegate unchanged; scheduling pauses are not SQL-lock or SDK proof. Real waits
require pg_blocking_pids and independent fresh policy premises. Frozen prior
modules and the shared fixture helpers are imported, never modified.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from test_action_policy_batching_integration import (
    acl,
    reference_attributes,
    reference_projection,
    wait_after,
    wait_blocked,
)
from test_action_source_batching_integration import requested

from rtr_copilot.actions import policy as policy_module
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Role
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.context.sources import revalidate_sot_references
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.repositories.audit import AuditRepository

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


async def record_id(factory: Any, refs: Any) -> uuid.UUID:
    async with factory() as session:
        return await session.scalar(
            text("SELECT record_id FROM record_versions WHERE version_id=:version"),
            {"version": refs[0].record_version_id},
        )


async def premise(factory: Any, actor: Any, resource: uuid.UUID, allow: bool) -> Any:
    # Independent frozen SQL + unchanged ResourceRepository; not candidate helpers.
    async with factory() as session:
        current, principals = await reference_projection(session, uuid.UUID(actor.user_id))
        effective = await reference_attributes(session, resource, "view", principals)
        assert effective is not None
        decision = PolicyEngine(StructuredAuditSink()).decide(
            current, "view", effective[0], PolicyContext(request_id="RQT-independent")
        )
        assert decision.allow is allow
        return current


async def counts(factory: Any, actor: Any, key: str) -> tuple[int, ...]:
    async with factory() as session:
        row = (
            await session.execute(
                text("""
            SELECT (SELECT count(*) FROM action_plans
                WHERE actor_id=:actor AND idempotency_key=:key),
              (SELECT count(*) FROM action_runs r JOIN action_plans p USING(plan_id)
                WHERE p.actor_id=:actor AND p.idempotency_key=:key),
              (SELECT count(*) FROM action_events e JOIN action_runs r USING(run_id)
                JOIN action_plans p USING(plan_id)
                WHERE p.actor_id=:actor AND p.idempotency_key=:key),
              (SELECT count(*) FROM action_receipts c JOIN action_runs r USING(run_id)
                JOIN action_plans p USING(plan_id)
                WHERE p.actor_id=:actor AND p.idempotency_key=:key),
              (SELECT count(*) FROM audit_events WHERE actor_user_id=:actor
                AND action='action.plan.create')
        """),
                {"actor": uuid.UUID(actor.user_id), "key": key},
            )
        ).one()
        return tuple(row)


async def execution_metadata(factory: Any, run_id: uuid.UUID) -> Any:
    """Independent app-role ledger snapshot, not a guarded public view oracle."""
    async with factory() as session:
        return dict(
            (
                await session.execute(
                    text("""
            SELECT to_jsonb(e) execution,
              COALESCE((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.receipt_id)
                FROM action_execution_receipts c WHERE c.run_id=e.run_id),'[]'::jsonb) receipts,
              COALESCE((SELECT jsonb_agg(to_jsonb(v) ORDER BY v.sequence)
                FROM action_execution_events v WHERE v.run_id=e.run_id),'[]'::jsonb) events
            FROM action_executions e WHERE e.run_id=:run
        """),
                    {"run": run_id},
                )
            )
            .mappings()
            .one()
        )


class Observation:
    """Transparent task-scoped Engine and both actual AsyncSession entry points."""

    def __init__(self, factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.engine = factory.kw["bind"].sync_engine
        self.monkeypatch = monkeypatch
        self.tasks: set[Any] = set()
        self.sql: list[str] = []
        self.sessions: list[tuple[int, str, str]] = []
        self.checkouts = 0
        self.held = 0
        self.max_held = 0
        self.owned_connections: set[int] = set()
        self.execute = AsyncSession.execute
        self.scalar = AsyncSession.scalar

    def active(self) -> bool:
        return asyncio.current_task() in self.tasks

    @contextmanager
    def watching(self) -> Any:
        def before(*args: Any) -> None:
            if self.active():
                self.sql.append(args[2])

        def checkout(*args: Any) -> None:
            if self.active():
                record_id = id(args[1])
                assert record_id not in self.owned_connections
                self.owned_connections.add(record_id)
                self.checkouts += 1
                self.held += 1
                self.max_held = max(self.max_held, self.held)

        def checkin(*args: Any) -> None:
            # AsyncSession.__aexit__ shields a child close task in installed SA.
            # Release is matched to an actually observed owned connection, not
            # to the task invoking checkin. Unmatched records never decrement.
            record_id = id(args[1])
            if record_id in self.owned_connections:
                self.owned_connections.remove(record_id)
                self.held -= 1

        async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
            if self.active():
                self.sessions.append((id(session), "execute", str(statement)))
            return await self.execute(session, statement, *args, **kwargs)

        async def scalar(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
            if self.active():
                self.sessions.append((id(session), "scalar", str(statement)))
            return await self.scalar(session, statement, *args, **kwargs)

        event.listen(self.engine, "before_cursor_execute", before)
        event.listen(self.engine, "checkout", checkout)
        event.listen(self.engine, "checkin", checkin)
        self.monkeypatch.setattr(AsyncSession, "execute", execute)
        self.monkeypatch.setattr(AsyncSession, "scalar", scalar)
        try:
            yield self
        finally:
            event.remove(self.engine, "before_cursor_execute", before)
            event.remove(self.engine, "checkout", checkout)
            event.remove(self.engine, "checkin", checkin)
            self.monkeypatch.setattr(AsyncSession, "execute", self.execute)
            self.monkeypatch.setattr(AsyncSession, "scalar", self.scalar)

    async def control(self, factory: Any) -> None:
        self.tasks.add(asyncio.current_task())
        async with factory() as session:
            assert (await session.execute(text("SELECT 17"))).scalar_one() == 17
            assert await session.scalar(text("SELECT 19")) == 19
        assert len(self.sql) == 2 and {item[1] for item in self.sessions} == {"scalar", "execute"}
        assert self.checkouts == 1 and self.held == 0 and self.max_held == 1
        self.reset()

    def reset(self) -> None:
        assert not self.owned_connections
        self.tasks.clear()
        self.sql.clear()
        self.sessions.clear()
        self.checkouts = self.held = self.max_held = 0


async def expired_role(factory: Any, actor: Any, due: datetime) -> None:
    async with factory() as session, session.begin():
        changed = await session.execute(
            text("""
            UPDATE subject_roles SET expires_at=:due WHERE subject_id=:actor
              AND role_id IN(SELECT role_id FROM roles WHERE key=:role)
        """),
            {"due": due, "actor": uuid.UUID(actor.user_id), "role": Role.CURATOR.value},
        )
        assert changed.rowcount == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fence", ["capability", "source", "evidence", "audit"])
async def test_real_final_wait_role_expiry_rolls_back_staged_success(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fence: str,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    resource = await record_id(factory, refs)
    await premise(factory, actor, resource, True)
    if fence == "evidence":
        async with factory() as session:
            key = await session.scalar(
                text(
                    "SELECT evidence_key FROM evidence_spans WHERE record_version_id=:v "
                    "AND lifecycle='active' ORDER BY span_id LIMIT 1"
                ),
                {"v": refs[0].record_version_id},
            )
        assert key
        refs = (refs[0].model_copy(update={"evidence_key": key}),)
    request = requested(refs)
    before = await counts(factory, actor, request.idempotency_key)
    due = datetime.now(UTC) + timedelta(seconds=2)
    await expired_role(factory, actor, due)
    entered = asyncio.get_running_loop().create_future()
    original = actions.uow.transaction

    @asynccontextmanager
    async def observed() -> Any:
        async with original() as session:
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions.uow, "transaction", observed)
    task = None
    try:
        async with factory() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            sql, params = {
                "capability": (
                    "SELECT capability_id FROM capability_versions WHERE "
                    "capability_id='sot.read' AND version='2' FOR UPDATE",
                    {},
                ),
                "source": (
                    "SELECT record_id FROM records WHERE record_id=:r FOR UPDATE",
                    {"r": resource},
                ),
                "evidence": (
                    "SELECT span_id FROM evidence_spans WHERE record_version_id=:v "
                    "AND evidence_key=:key AND lifecycle='active' FOR UPDATE",
                    {"v": refs[0].record_version_id, "key": refs[0].evidence_key},
                ),
                "audit": ("SELECT pg_advisory_xact_lock(827004)", {}),
            }[fence]
            await blocker.execute(text(sql), params)
            task = asyncio.create_task(
                actions.create_plan(actor, request, request_id="RQT-real-wait")
            )
            waiter = await asyncio.wait_for(entered, 5)
            await wait_blocked(factory, waiter, blocker_pid)
            await wait_after(factory, due)
            fresh = await premise(factory, actor, resource, False)
            assert Role.CURATOR not in fresh.roles
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 10)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert await counts(factory, actor, request.idempotency_key) == before


@pytest.mark.asyncio
async def test_freshness_deadline_crosses_actual_audit_wait_no_admission(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, expiring=True)
    request = requested(refs)
    before = await counts(factory, actor, request.idempotency_key)
    async with factory() as session:
        due = await session.scalar(
            text("SELECT freshness_due_at FROM record_versions WHERE version_id=:v"),
            {"v": refs[0].record_version_id},
        )
    assert due is not None and due > datetime.now(UTC)
    entered = asyncio.get_running_loop().create_future()
    original = actions.uow.transaction

    @asynccontextmanager
    async def observed() -> Any:
        async with original() as session:
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions.uow, "transaction", observed)
    task = None
    try:
        async with factory() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
            task = asyncio.create_task(
                actions.create_plan(actor, request, request_id="RQT-freshness")
            )
            await wait_blocked(factory, await asyncio.wait_for(entered, 5), blocker_pid)
            await wait_after(factory, due)
            independent = await revalidate_sot_references(
                actor, refs, factory=factory, request_id="RQT-stale-oracle", include_text=False
            )
            assert not independent.sources and [gap.code for gap in independent.gaps] == ["stale"]
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 10)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert await counts(factory, actor, request.idempotency_key) == before


@pytest.mark.asyncio
async def test_parallel_independent_creates_keep_chained_audit_exactly_once(
    factory: Any,
    tmp_path: Path,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    requests = [requested(refs) for _ in range(3)]
    views = await asyncio.wait_for(
        asyncio.gather(
            *(
                actions.create_plan(actor, request, request_id=f"RQT-independent-{i}")
                for i, request in enumerate(requests)
            )
        ),
        10,
    )
    assert len({view.plan_id for view in views}) == 3
    for request in requests:
        assert await counts(factory, actor, request.idempotency_key) == (1, 1, 1, 1, 3)
    async with factory() as session:
        assert (await AuditRepository().verify(session))[0]


@pytest.mark.asyncio
async def test_identical_concurrent_key_has_one_plan_event_receipt_audit(
    factory: Any,
    tmp_path: Path,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    first, second = await asyncio.wait_for(
        asyncio.gather(
            actions.create_plan(actor, request, request_id="RQT-equal-a"),
            actions.create_plan(actor, request, request_id="RQT-equal-b"),
        ),
        10,
    )
    assert first.plan_id == second.plan_id and first.plan_digest == second.plan_digest
    assert await counts(factory, actor, request.idempotency_key) == (1, 1, 1, 1, 1)


@pytest.mark.asyncio
async def test_conflicting_key_is_denial_not_second_mutation_or_audit(
    factory: Any,
    tmp_path: Path,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    await actions.create_plan(actor, request, request_id="RQT-conflict-before")
    with pytest.raises(ActionError, match="idempotency_conflict"):
        await actions.create_plan(
            actor,
            request.model_copy(update={"objective": "Different"}),
            request_id="RQT-conflict-after",
        )
    assert await counts(factory, actor, request.idempotency_key) == (1, 1, 1, 1, 1)


@pytest.mark.asyncio
async def test_duplicate_submit_preserves_partial_cancel_spend_deadline_and_audit(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_config: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    resource = await record_id(factory, refs)
    plan = await actions.create_plan(actor, requested(refs), request_id="RQT-submit-deadline-plan")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    original = actions.uow.transaction
    entered = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def observed() -> Any:
        async with original() as session:
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions.uow, "transaction", observed)
    task = None
    try:
        async with factory() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
            task = asyncio.create_task(
                executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="RQT-new-submit-audit-wait"
                )
            )
            await wait_blocked(factory, await asyncio.wait_for(entered, 5), blocker_pid)
            released = await blocker.scalar(text("SELECT clock_timestamp()"))
        view = await asyncio.wait_for(task, 10)
    finally:
        monkeypatch.setattr(actions.uow, "transaction", original)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    # No pre-audit admission deadline and no initial-budget reset.
    assert view.deadline_at >= released + timedelta(seconds=plan.payload.budget.wall_seconds)
    await executor.advance(view.run_id)
    await executor.cancel(actor, view.run_id)
    before = await executor.status(actor, view.run_id)
    immutable_before = await execution_metadata(factory, view.run_id)
    assert before.cancel_requested and before.spent_tool_calls == 1 and before.state == "partial"
    async with factory() as session:
        audits = await session.scalar(
            text(
                "SELECT count(*) FROM audit_events WHERE actor_user_id=:a "
                "AND action='action.execution.submit'"
            ),
            {"a": uuid.UUID(actor.user_id)},
        )
    observation = Observation(factory, monkeypatch)
    with observation.watching():
        await observation.control(factory)
        observation.tasks.add(asyncio.current_task())
        after = await executor.submit(
            actor, plan.plan_id, plan.plan_digest, request_id="RQT-duplicate"
        )
    assert after == before
    assert await execution_metadata(factory, view.run_id) == immutable_before
    assert not any("pg_advisory_xact_lock(827004)" in sql for sql in observation.sql)
    assert not any("INSERT INTO action_executions" in sql for sql in observation.sql)
    async with factory() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE actor_user_id=:a "
                    "AND action='action.execution.submit'"
                ),
                {"a": uuid.UUID(actor.user_id)},
            )
            == audits
        )
    # A duplicate's REAL execution-row lock is another last-wait boundary.
    due = datetime.now(UTC) + timedelta(seconds=2)
    await expired_role(factory, actor, due)
    entered = asyncio.get_running_loop().create_future()
    monkeypatch.setattr(actions.uow, "transaction", observed)
    task = None
    try:
        async with factory() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                text("SELECT run_id FROM action_executions WHERE run_id=:run FOR UPDATE"),
                {"run": view.run_id},
            )
            task = asyncio.create_task(
                executor.submit(
                    actor, plan.plan_id, plan.plan_digest, request_id="RQT-duplicate-row-expiry"
                )
            )
            await wait_blocked(factory, await asyncio.wait_for(entered, 5), blocker_pid)
            await wait_after(factory, due)
            await premise(factory, actor, resource, False)
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 10)
    finally:
        monkeypatch.setattr(actions.uow, "transaction", original)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert await executor.status(actor, view.run_id) == before
    assert await execution_metadata(factory, view.run_id) == immutable_before
    with pytest.raises(ActionError):
        await executor.read_output(actor, view.run_id, "read", request_id="RQT-no-expired-content")


@pytest.mark.asyncio
async def test_actual_audit_function_failure_rolls_back_staged_contract(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    before = await counts(factory, actor, request.idempotency_key)
    original = AuditRepository.append
    reached: list[str] = []

    async def bad_audit(repo: Any, session: Any, **kwargs: Any) -> Any:
        # Explicit SQL fault injection, not a fake exception/result: the actual
        # SECURITY DEFINER append reaches its NOT NULL constraint and rolls back.
        if kwargs["action"] == "action.plan.create":
            reached.append(kwargs["action"])
            kwargs["request_id"] = None
        return await original(repo, session, **kwargs)

    monkeypatch.setattr(AuditRepository, "append", bad_audit)
    with pytest.raises(DBAPIError):
        await actions.create_plan(actor, request, request_id="RQT-actual-audit-failure")
    assert reached == ["action.plan.create"]
    assert await counts(factory, actor, request.idempotency_key) == before
    async with factory() as session:
        assert (await AuditRepository().verify(session))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "submit"])
async def test_real_engine_controls_initial_same_session_no_nested_checkout_or_body(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_config: Any,
    operation: str,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    plan = (
        await actions.create_plan(actor, request, request_id="RQT-count-existing")
        if operation == "submit"
        else None
    )
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    observation = Observation(factory, monkeypatch)
    with observation.watching():
        await observation.control(factory)
        observation.tasks.add(asyncio.current_task())
        if operation == "create":
            result = await actions.create_plan(actor, request, request_id="RQT-count-create")
        else:
            assert plan is not None
            result = await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="RQT-count-submit"
            )
    assert result is not None and observation.checkouts == 3 and observation.max_held == 1
    assert observation.held == 0
    first = observation.sessions[0][0]
    initial_sql = [sql for session, _, sql in observation.sessions if session == first]
    assert any("WITH" in sql and "identity" in sql for sql in initial_sql)
    assert any("evidence_count" in sql for sql in initial_sql)
    assert any("capability_versions" in sql for sql in initial_sql)
    assert not any(
        "SELECT rv.value_payload," in sql or "quoted_text" in sql for sql in observation.sql
    )
    # Purpose-key projection is permitted; full fact bodies/searchable text are not.
    assert all("value_payload" not in sql or "value_payload->" in sql for sql in observation.sql)


@pytest.mark.asyncio
async def test_unsupported_whole_initial_attempt_closes_before_fresh_shared_fallback(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for topology in ("nonrecord", "overflow"):
        actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
        resource = await record_id(factory, refs)
        async with factory() as session, session.begin():
            if topology == "nonrecord":
                await session.execute(
                    text("UPDATE resources SET resource_type='document' WHERE resource_id=:r"),
                    {"r": resource},
                )
            else:
                row = (
                    await session.execute(
                        text(
                            "SELECT span_id,evidence_key FROM evidence_spans "
                            "WHERE record_version_id=:v AND lifecycle='active' LIMIT 1"
                        ),
                        {"v": refs[0].record_version_id},
                    )
                ).one()
                await session.execute(
                    text("""
                    INSERT INTO evidence_spans(evidence_key,record_version_id,package_id,source_ref,
                      locator,quoted_text,normalized_text,evidence_sha256,
                      source_label,classification,lifecycle)
                    SELECT :prefix || n::text,e.record_version_id,
                      e.package_id,e.source_ref,e.locator,e.quoted_text,e.normalized_text,
                      e.evidence_sha256,e.source_label,e.classification,'active'
                    FROM evidence_spans e CROSS JOIN generate_series(1,1001) n WHERE e.span_id=:id
                """),
                    {"prefix": f"RQT-{uuid.uuid4()}-", "id": row.span_id},
                )
                refs = (refs[0].model_copy(update={"evidence_key": row.evidence_key}),)
        expected = await revalidate_sot_references(
            actor, refs, factory=factory, include_text=False, request_id="RQT-fallback-independent"
        )
        observation = Observation(factory, monkeypatch)
        real_shared = policy_module.revalidate_sot_references
        seen: list[int] = []

        async def shared(
            *args: Any,
            _seen: Any = seen,
            _observation: Any = observation,
            _real: Any = real_shared,
            **kwargs: Any,
        ) -> Any:
            _seen.append(_observation.held)
            assert _observation.held == 0
            return await _real(*args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(policy_module, "revalidate_sot_references", shared)
            with observation.watching():
                await observation.control(factory)
                observation.tasks.add(asyncio.current_task())
                if expected.gaps:
                    with pytest.raises(ActionError):
                        await actions.create_plan(
                            actor, requested(refs), request_id="RQT-fallback-denied"
                        )
                else:
                    await actions.create_plan(
                        actor, requested(refs), request_id="RQT-fallback-permitted"
                    )
        assert seen and observation.max_held == 1


@pytest.mark.asyncio
async def test_borrowed_transaction_keeps_conservative_private_allow_clocks(
    factory: Any,
    tmp_path: Path,
) -> None:
    actions, owner, refs, _, _ = await adversarial.domain(factory, tmp_path)
    viewer = await fixtures.principal(factory)
    resource = await record_id(factory, refs)
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE resources SET source_zone='private_context' WHERE resource_id=:r"),
            {"r": resource},
        )
    async with factory() as held:
        started = await held.scalar(text("SELECT transaction_timestamp()"))
        begins = datetime.now(UTC) + timedelta(milliseconds=150)
        await acl(factory, resource, uuid.UUID(viewer.user_id), starts=begins)
        await wait_after(factory, begins)
        assert started < begins
        with pytest.raises(ActionError):
            await actions.policy.session_resource(
                held, viewer, resource, "view", "RQT-conservative"
            )
    await premise(factory, viewer, resource, True)


@pytest.mark.asyncio
async def test_r1_body_binding_remains_real_separate_nonborrowed_path(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    actions, actor, refs, _, version = await adversarial.domain(factory, tmp_path, locked=True)
    request = PlanRequest(
        idempotency_key=f"RQT-R1-{uuid.uuid4()}",
        objective="Actual R1 binding",
        source_refs=refs,
        requested_internal_draft=True,
        steps=(
            StepRequest(
                step_key="draft",
                capability_id="documents.create_draft",
                capability_version="2",
                arguments={"template_version_id": str(version), "parameters": {}},
            ),
        ),
    )
    original = DocumentOSService.bind
    values: list[Any] = []

    async def binding(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        values.append(result)
        return result

    monkeypatch.setattr(DocumentOSService, "bind", binding)
    plan = await actions.create_plan(actor, request, request_id="RQT-R1-create")
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    await executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="RQT-R1-submit")
    assert len(values) >= 2 and all(value.valid for value in values)
    assert any(
        field.source == "locked_fact" and "HERA" in str(field.value)
        for value in values
        for field in value.fields
    )


@pytest.mark.asyncio
async def test_staged_rows_then_real_audit_wait_late_deny_is_atomic(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    request = requested(refs)
    resource = await record_id(factory, refs)
    await premise(factory, actor, resource, True)
    before = await counts(factory, actor, request.idempotency_key)
    entered = asyncio.get_running_loop().create_future()
    original = actions.uow.transaction

    @asynccontextmanager
    async def observed() -> Any:
        async with original() as session:
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions.uow, "transaction", observed)
    observation = Observation(factory, monkeypatch)

    async def create() -> Any:
        observation.tasks.add(asyncio.current_task())
        return await actions.create_plan(actor, request, request_id="RQT-staged-late-deny")

    task = None
    with observation.watching():
        await observation.control(factory)
        try:
            async with factory() as blocker, blocker.begin():
                blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
                await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
                task = asyncio.create_task(create())
                await wait_blocked(factory, await asyncio.wait_for(entered, 5), blocker_pid)
                sql = "\n".join(observation.sql)
                assert "INSERT INTO action_plans" in sql and "INSERT INTO action_receipts" in sql
                assert sql.index("INSERT INTO action_receipts") < sql.index(
                    "pg_advisory_xact_lock(827004)"
                )
                assert await counts(factory, actor, request.idempotency_key) == before
                await fixtures.deny(factory, refs[0], actor)
                await premise(factory, actor, resource, False)
            with pytest.raises(ActionError):
                await asyncio.wait_for(task, 10)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert await counts(factory, actor, request.idempotency_key) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["permit", "bad_checksum", "late_deny"])
async def test_grouped_clock_retry_is_once_after_close_and_never_hard_error_permission(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    resource = await record_id(factory, refs)
    due = datetime.now(UTC) + timedelta(seconds=2)
    await acl(
        factory,
        resource,
        uuid.UUID(actor.user_id),
        effect="deny",
        starts=datetime.now(UTC) - timedelta(seconds=1),
        expires=due,
    )
    if scenario == "bad_checksum":
        refs = (refs[0].model_copy(update={"content_sha256": "0" * 64}),)
    request = requested(refs)
    before = await counts(factory, actor, request.idempotency_key)
    real_project = policy_module.project_subject
    real_legacy = actions._legacy_initial_plan
    observation = Observation(factory, monkeypatch)
    first = True
    retries = 0

    async def project(session: Any, actor_id: Any) -> Any:
        nonlocal first
        result = await real_project(session, actor_id)
        if first and actor_id == uuid.UUID(actor.user_id):
            first = False
            started = await session.scalar(text("SELECT transaction_timestamp()"))
            assert started < due
            # Controlled scheduling AFTER real initial actor projection; this is
            # not a claim that a production query waited on a PostgreSQL row lock.
            await wait_after(factory, due)
            await premise(factory, actor, resource, True)
            flags = (
                await session.execute(
                    text("""
                SELECT EXISTS(SELECT 1 FROM acl_entries WHERE resource_id=:r
                  AND principal_id=:a AND effect='deny' AND action='view'
                  AND valid_from<=transaction_timestamp()
                  AND expires_at>transaction_timestamp()) old_deny,
                  EXISTS(SELECT 1 FROM acl_entries WHERE resource_id=:r
                    AND principal_id=:a AND effect='deny' AND action='view'
                    AND valid_from<=statement_timestamp()
                    AND expires_at>statement_timestamp()) new_deny
            """),
                    {"r": resource, "a": uuid.UUID(actor.user_id)},
                )
            ).one()
            assert flags.old_deny and not flags.new_deny
        return result

    async def legacy(*args: Any, **kwargs: Any) -> Any:
        nonlocal retries
        retries += 1
        assert retries == 1 and observation.held == 0
        if scenario == "late_deny":
            await fixtures.deny(factory, refs[0], actor)
            await premise(factory, actor, resource, False)
        return await real_legacy(*args, **kwargs)

    monkeypatch.setattr(policy_module, "project_subject", project)
    monkeypatch.setattr(actions, "_legacy_initial_plan", legacy)
    with observation.watching():
        await observation.control(factory)
        observation.tasks.add(asyncio.current_task())
        if scenario == "permit":
            result = await actions.create_plan(actor, request, request_id="RQT-clock-retry")
            assert result.payload.source_refs == refs
        else:
            with pytest.raises(ActionError):
                await actions.create_plan(actor, request, request_id="RQT-clock-denied")
    assert not first and retries == int(scenario != "bad_checksum")
    if scenario != "permit":
        assert await counts(factory, actor, request.idempotency_key) == before
    else:
        assert await counts(factory, actor, request.idempotency_key) == (1, 1, 1, 1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("late_revoke", [False, True])
async def test_new_entitlement_is_visible_in_grouped_fresh_statement_not_grant_shadow(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    late_revoke: bool,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    resource = await record_id(factory, refs)
    # STAFF initially views an internal SOT record. Restrict it only AFTER the
    # real initial projection, then commit an actual current grant. No born-at
    # predicate exists in entitlements; the held READ COMMITTED statement must
    # observe the newly committed row, while later revocation must still deny.
    async with factory() as session, session.begin():
        await session.execute(
            text("DELETE FROM subject_roles WHERE subject_id=:a"), {"a": uuid.UUID(actor.user_id)}
        )
    await premise(factory, actor, resource, True)
    request = requested(refs)
    before = await counts(factory, actor, request.idempotency_key)
    grant = uuid.uuid4()
    expiry = datetime.now(UTC) + timedelta(minutes=1)
    real_project = policy_module.project_subject
    real_transaction = actions.uow.transaction
    real_legacy = actions._legacy_initial_plan
    projections: list[Any] = []
    retries = 0

    async def project(session: Any, actor_id: Any) -> Any:
        result = await real_project(session, actor_id)
        if not projections and actor_id == uuid.UUID(actor.user_id):
            projections.append(result)
            started = await session.scalar(text("SELECT transaction_timestamp()"))
            async with factory() as writer, writer.begin():
                await writer.execute(
                    text("UPDATE resources SET classification='restricted' WHERE resource_id=:r"),
                    {"r": resource},
                )
                born = await writer.scalar(text("SELECT clock_timestamp()"))
                await writer.execute(
                    text("""
                    INSERT INTO entitlements(entitlement_id,subject_id,resource_id,action,
                      effect,conditions,active,expires_at,reason)
                    VALUES(:id,:actor,:resource,'view','allow',
                      '{"classification":"restricted"}'::jsonb,true,:expiry,'RQT-current-grant')
                """),
                    {
                        "id": grant,
                        "actor": uuid.UUID(actor.user_id),
                        "resource": resource,
                        "expiry": expiry,
                    },
                )
            assert born > started and Role.CURATOR not in result.subject.roles
            fresh = await premise(factory, actor, resource, True)
            assert fresh.temporary_entitlements
            # Independent SQL in the very SAME original transaction witnesses
            # the committed grant; no candidate helper supplies this premise.
            assert await session.scalar(
                text("""
                SELECT EXISTS(SELECT 1 FROM entitlements WHERE entitlement_id=:id
                  AND active AND effect='allow' AND expires_at>transaction_timestamp())
            """),
                {"id": grant},
            )
        return result

    @asynccontextmanager
    async def mutation() -> Any:
        if late_revoke:
            async with factory() as writer, writer.begin():
                changed = await writer.execute(
                    text(
                        "UPDATE entitlements SET active=false WHERE entitlement_id=:id AND active"
                    ),
                    {"id": grant},
                )
                assert changed.rowcount == 1
            await premise(factory, actor, resource, False)
        async with real_transaction() as session:
            yield session

    async def legacy(*args: Any, **kwargs: Any) -> Any:
        nonlocal retries
        retries += 1
        return await real_legacy(*args, **kwargs)

    monkeypatch.setattr(policy_module, "project_subject", project)
    monkeypatch.setattr(actions.uow, "transaction", mutation)
    monkeypatch.setattr(actions, "_legacy_initial_plan", legacy)
    if late_revoke:
        with pytest.raises(ActionError):
            await actions.create_plan(actor, request, request_id="RQT-late-entitlement-revoke")
        assert await counts(factory, actor, request.idempotency_key) == before
    else:
        result = await actions.create_plan(actor, request, request_id="RQT-new-entitlement")
        assert result.payload.steps[0].resources[0].classification == "restricted"
    assert len(projections) == 1 and retries == 0
