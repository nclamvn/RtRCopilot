"""Builder real-SQL staged-cancel and hard-clock-denial companion proofs."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
from sqlalchemy import text
from test_action_policy_batching_integration import wait_after, wait_blocked

from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.repositories.audit import AuditRepository

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return adversarial.local_boundaries.__wrapped__(monkeypatch, factory)


def proposed(refs: Any, key: str) -> PlanRequest:
    return PlanRequest(idempotency_key=key, objective="Synthetic R2 own rollback proof",
                       source_refs=refs, steps=(StepRequest(step_key="read",
                         capability_id="sot.read", capability_version="2",
                         arguments={"record_key": refs[0].record_key}),))


async def committed_counts(factory: Any, actor: Any, key: str) -> tuple[int, ...]:
    async with factory() as session:
        return tuple((await session.execute(text("""
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
        """), {"actor": uuid.UUID(actor.user_id), "key": key})).one())


@pytest.mark.asyncio
async def test_task_cancel_during_real_audit_wait_rolls_back_staged_bookkeeping(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_boundaries: Any,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    key = f"RQT-cancel-{uuid.uuid4()}"
    before = await committed_counts(factory, actor, key)
    entered = asyncio.get_running_loop().create_future()
    staged = asyncio.Event()
    real_transaction = actions.uow.transaction
    real_insert = actions._insert_plan

    @asynccontextmanager
    async def observed_transaction() -> Any:
        async with real_transaction() as session:
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    async def observed_insert(*args: Any, **kwargs: Any) -> Any:
        assert kwargs.get("append_audit") is False
        view = await real_insert(*args, **kwargs)
        session = args[0]
        assert await session.scalar(text("SELECT count(*) FROM action_events WHERE run_id=:run"),
                                     {"run": view.run_id}) == 1
        assert await session.scalar(text("SELECT count(*) FROM action_receipts WHERE run_id=:run"),
                                     {"run": view.run_id}) == 1
        staged.set()
        return view

    monkeypatch.setattr(actions.uow, "transaction", observed_transaction)
    monkeypatch.setattr(actions, "_insert_plan", observed_insert)
    async with factory() as blocker, blocker.begin():
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
        task = asyncio.create_task(actions.create_plan(actor, proposed(refs, key),
                                                       request_id="RQT-staged-cancel"))
        try:
            waiter = await asyncio.wait_for(entered, 5)
            await asyncio.wait_for(staged.wait(), 5)
            await wait_blocked(factory, waiter, blocker_pid)
            assert await committed_counts(factory, actor, key) == before
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert await committed_counts(factory, actor, key) == before
    async with factory() as session:
        valid, _, _ = await AuditRepository().verify(session)
    assert valid


@pytest.mark.asyncio
@pytest.mark.parametrize("hard", ["unmatched", "arguments", "checksum", "security"])
async def test_real_initial_clock_flags_cannot_retry_hard_input_or_version_failure(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    local_boundaries: Any, hard: str,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    key = f"RQT-hard-clock-{uuid.uuid4()}"
    request = proposed(refs, key)
    if hard == "unmatched":
        request = request.model_copy(update={"steps": (request.steps[0].model_copy(
            update={"arguments": {"record_key": "NOT_A_SUPPLIED_SOURCE"}}),)})
    elif hard == "arguments":
        request = request.model_copy(update={"steps": (request.steps[0].model_copy(
            update={"arguments": {"record_key": refs[0].record_key, "extra": True}}),)})
    elif hard == "checksum":
        request = request.model_copy(update={"source_refs": (
            refs[0].model_copy(update={"content_sha256": "0"*64}),)})
    boundary = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        resource = await session.scalar(text(
            "SELECT record_id FROM record_versions WHERE version_id=:version"
        ), {"version": refs[0].record_version_id})
        await session.execute(text("""
            INSERT INTO acl_entries(resource_id,principal_type,principal_id,action,effect,
              valid_from,expires_at) VALUES(:resource,'user',:actor,'view','deny',
              statement_timestamp(),:expires)
        """), {"resource": resource, "actor": uuid.UUID(actor.user_id), "expires": boundary})
    real_current = actions.policy.current
    real_old = actions._legacy_initial_plan
    old_calls = 0

    async def current(*args: Any, **kwargs: Any) -> Any:
        value = await real_current(*args, **kwargs)
        if kwargs.get("initial_session") is not None:
            if hard == "security":
                async with factory() as session, session.begin():
                    await session.execute(text("""
                        UPDATE subjects SET security_version=security_version+1 WHERE user_id=:actor
                    """), {"actor": uuid.UUID(actor.user_id)})
            await wait_after(factory, boundary)
        return value

    async def old(*args: Any, **kwargs: Any) -> Any:
        nonlocal old_calls
        old_calls += 1
        return await real_old(*args, **kwargs)

    monkeypatch.setattr(actions.policy, "current", current)
    monkeypatch.setattr(actions, "_legacy_initial_plan", old)
    before = await committed_counts(factory, actor, key)
    with pytest.raises(ActionError) as error:
        await actions.create_plan(actor, request, request_id="RQT-hard-clock")
    assert error.value.code == {
        "unmatched": "source_unavailable", "arguments": "arguments_invalid",
        "checksum": "source_unavailable", "security": "authority_changed",
    }[hard]
    assert old_calls == 0
    assert await committed_counts(factory, actor, key) == before
