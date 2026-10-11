"""Builder-owned real SQL budgets and an existing audit-fence expiry race."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
from sqlalchemy import event, text
from test_action_execution_adversarial import domain

from rtr_copilot.actions.authority import LeafRequest, batch_leaf_attributes, project_subject
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


def request(refs: Any) -> PlanRequest:
    return PlanRequest(idempotency_key=uuid.uuid4().hex, objective="Action-local SQL budget",
                       source_refs=refs, steps=(StepRequest(
                           step_key="read", capability_id="sot.read", capability_version="2",
                           arguments={"record_key": refs[0].record_key},
                       ),))


@pytest.mark.asyncio
async def test_projection_one_statement_matches_actual_identity(factory: Any) -> None:
    subject = await fixtures.principal(factory)
    expected = await PostgresSubjectRepository(factory).get_by_user_id(uuid.UUID(subject.user_id))
    statements = []
    engine = factory.kw["bind"].sync_engine

    def observed(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", observed)
    try:
        async with factory() as session:
            frame = await project_subject(session, uuid.UUID(subject.user_id))
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert len(statements) == 1 and frame.subject == expected
    assert uuid.UUID(subject.user_id) in frame.principal_ids


@pytest.mark.asyncio
async def test_exact_type_drift_denies_while_generic_preserves_fallback(
    factory: Any, tmp_path: Path,
) -> None:
    _, owner, refs, _, _ = await domain(factory, tmp_path)
    async with factory() as session, session.begin():
        record = await session.scalar(text(
            "SELECT record_id FROM record_versions WHERE version_id=:v"
        ), {"v": refs[0].record_version_id})
        await session.execute(text(
            "UPDATE resources SET resource_type='document' WHERE resource_id=:r"
        ), {"r": record})
    async with factory() as session:
        strict = await batch_leaf_attributes(session, uuid.UUID(owner.user_id),
                                             [LeafRequest(record, "view", "record")])
        generic = await batch_leaf_attributes(session, uuid.UUID(owner.user_id),
                                              [LeafRequest(record, "view")])
    assert strict.attributes[(record, "view")] is None and not strict.unsupported
    assert (record, "view") in generic.unsupported


@pytest.mark.asyncio
@pytest.mark.parametrize("audited", [False, True])
async def test_one_source_final_checkpoint_query_ceiling(
    factory: Any, tmp_path: Path, audited: bool,
) -> None:
    actions, owner, refs, _, _ = await domain(factory, tmp_path)
    plan = await actions.create_plan(owner, request(refs), request_id="RQB-count-plan")
    statements = []
    engine = factory.kw["bind"].sync_engine

    def observed(*args: Any) -> None:
        statements.append(args[2])

    async with factory() as session, session.begin():
        event.listen(engine, "before_cursor_execute", observed)
        try:
            await actions._snapshot(session, owner, plan.payload, "RQB-count",
                                    audit_fence=audited)
        finally:
            event.remove(engine, "before_cursor_execute", observed)
    assert len(statements) <= 10
    assert sum("pg_advisory_xact_lock(827004)" in sql for sql in statements) == int(audited)


@pytest.mark.asyncio
async def test_real_audit_wait_expiry_rolls_back_plan_and_success_audit(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, owner, refs, _, _ = await domain(factory, tmp_path, restricted=True)
    proposed = request(refs)
    due = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        await session.execute(text(
            "UPDATE subject_roles SET expires_at=:due WHERE subject_id=:actor"
        ), {"due": due, "actor": uuid.UUID(owner.user_id)})
    pid: list[int] = []
    entered = asyncio.Event()
    original = actions._snapshot

    async def snapshot(session: Any, *args: Any, **kwargs: Any) -> None:
        pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
        entered.set()
        await original(session, *args, **kwargs)

    monkeypatch.setattr(actions, "_snapshot", snapshot)
    task = None
    try:
        async with factory() as blocker, blocker.begin():
            await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
            task = asyncio.create_task(actions.create_plan(owner, proposed, request_id="RQB-audit"))
            await asyncio.wait_for(entered.wait(), timeout=3)
            observed = False
            for _ in range(80):
                async with factory() as observer:
                    observed = bool(await observer.scalar(text("""
                        SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                          WHERE pid=:pid AND wait_event_type='Lock' AND wait_event='advisory')
                    """), {"pid": pid[0]}))
                if observed:
                    break
                await asyncio.sleep(.025)
            assert observed, "the final Action checkpoint did not really wait on the audit lock"
            await asyncio.sleep(max(0, (due - datetime.now(UTC)).total_seconds()) + .05)
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, timeout=4)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with factory() as session:
        assert not await session.scalar(text("""
            SELECT EXISTS(SELECT 1 FROM action_plans WHERE actor_id=:actor AND idempotency_key=:key)
        """), {"actor": uuid.UUID(owner.user_id), "key": proposed.idempotency_key})
        assert not await session.scalar(text("""
            SELECT EXISTS(SELECT 1 FROM audit_events WHERE actor_user_id=:actor
              AND action='action.plan.create' AND result='success')
        """), {"actor": uuid.UUID(owner.user_id)})
