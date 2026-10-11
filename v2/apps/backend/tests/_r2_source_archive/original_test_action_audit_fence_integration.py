"""Real existing 827004 audit-fence waits must precede final authority.

The UOW observer adds only backend-PID observation and delegates the real
transaction unchanged. No mutation/audit outcome or authorization is mocked.
"""

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
from sqlalchemy.ext.asyncio import AsyncSession
from test_action_policy_batching_integration import wait_after, wait_blocked
from test_action_publication_checkpoint_integration import source_and_multibinding_job

from rtr_copilot.actions import execution as execution_module
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.documents.service import DocumentOSService

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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "submit"])
async def test_actual_chained_audit_wait_crossing_role_expiry_rolls_back_all_success(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_config: Any,
    operation: str,
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    request = PlanRequest(
        idempotency_key=f"RQB-audit-{uuid.uuid4()}",
        objective="Synthetic existing audit fence",
        source_refs=refs,
        steps=(
            StepRequest(
                step_key="read",
                capability_id="sot.read",
                capability_version="2",
                arguments={"record_key": refs[0].record_key},
            ),
        ),
    )
    plan = (
        await actions.create_plan(actor, request, request_id="RQB-audit-existing-plan")
        if operation == "submit"
        else None
    )
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = execution_config
    action = "action.plan.create" if operation == "create" else "action.execution.submit"
    async with factory() as session:
        before_audit = await session.scalar(
            text("""
            SELECT count(*) FROM audit_events WHERE actor_user_id=:actor AND action=:action
        """),
            {"actor": uuid.UUID(actor.user_id), "action": action},
        )
    boundary = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            UPDATE subject_roles SET expires_at=:expires WHERE subject_id=:actor
        """),
            {"expires": boundary, "actor": uuid.UUID(actor.user_id)},
        )
    entered = asyncio.get_running_loop().create_future()
    real_transaction = actions.uow.transaction

    @asynccontextmanager
    async def observed_transaction() -> Any:
        async with real_transaction() as session:
            if not entered.done():
                entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    monkeypatch.setattr(actions.uow, "transaction", observed_transaction)

    async def mutate() -> None:
        if operation == "create":
            await actions.create_plan(actor, request, request_id="RQB-audit-blocked-create")
        else:
            assert plan is not None
            await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="RQB-audit-blocked-submit"
            )

    async with factory() as blocker, blocker.begin():
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
        task = asyncio.create_task(mutate())
        try:
            waiter = await asyncio.wait_for(entered, 5)
            await wait_blocked(factory, waiter, blocker_pid)
            async with factory() as session:
                assert await session.scalar(
                    text("""
                    SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                      AND classid=0 AND objid=827004 AND NOT granted)
                """),
                    {"pid": waiter},
                )
            await wait_after(factory, boundary)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(ActionError):
        await asyncio.wait_for(task, 10)
    async with factory() as session:
        assert (
            await session.scalar(
                text("""
            SELECT count(*) FROM audit_events WHERE actor_user_id=:actor AND action=:action
        """),
                {"actor": uuid.UUID(actor.user_id), "action": action},
            )
            == before_audit
        )
        assert (
            await session.scalar(
                text("SELECT security_version FROM subjects WHERE user_id=:actor"),
                {"actor": uuid.UUID(actor.user_id)},
            )
            == actor.security_version
        )
        if operation == "create":
            assert (
                await session.scalar(
                    text("""
                SELECT count(*) FROM action_plans WHERE actor_id=:actor AND idempotency_key=:key
            """),
                    {"actor": uuid.UUID(actor.user_id), "key": request.idempotency_key},
                )
                == 0
            )
        else:
            assert plan is not None
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM action_executions WHERE run_id=:run"),
                    {"run": plan.run_id},
                )
                == 0
            )


@pytest.mark.asyncio
async def test_linked_final_publication_real_audit_wait_occurs_before_fresh_authority(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    _, actor, _, documents, _, _, job, _ = await source_and_multibinding_job(
        factory, tmp_path, execution_config, restricted=True
    )
    reached, release = asyncio.Event(), asyncio.Event()
    active, reconstructed = False, False
    waiter_pid: int | None = None
    real_publication = DocumentOSService._publication_guard
    real_locked = execution_module.locked_fact_value
    real_execute = AsyncSession.execute

    async def publication(
        service: Any,
        current_job: Any,
        fields: Any,
        requester: Any,
        *,
        session: Any = None,
        **kwargs: Any,
    ) -> None:
        nonlocal active, reconstructed
        final = (
            session is not None
            and kwargs.get("audit_writing", True)
            and current_job["render_job_id"] == job
        )
        if final:
            active, reconstructed = True, False
        try:
            await real_publication(
                service, current_job, fields, requester, session=session, **kwargs
            )
        finally:
            if final:
                active = False

    def locked(binding: Any, payload: Any) -> Any:
        nonlocal reconstructed
        value = real_locked(binding, payload)
        if active and binding.field_path == "range":
            assert value == "HERA"
            reconstructed = True
        return value

    async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal waiter_pid
        if (
            active
            and reconstructed
            and not reached.is_set()
            and "pg_advisory_xact_lock(827004)" in str(statement)
        ):
            result = await real_execute(session, text("SELECT pg_backend_pid()"))
            waiter_pid = result.scalar_one()
            reached.set()
            await asyncio.wait_for(release.wait(), 15)
        return await real_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(DocumentOSService, "_publication_guard", publication)
    monkeypatch.setattr(execution_module, "locked_fact_value", locked)
    monkeypatch.setattr(AsyncSession, "execute", execute)
    task = asyncio.create_task(
        documents.process_render(job, worker_id="RQB-real-audit-publication")
    )
    try:
        # Controlled scheduling only positions the holder. The subsequent
        # candidate audit wait is a real, separately confirmed SQL lock wait.
        await asyncio.wait_for(reached.wait(), 10)
        assert reconstructed and waiter_pid is not None
        boundary = datetime.now(UTC) + timedelta(seconds=2)
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE subject_roles SET expires_at=:expires WHERE subject_id=:actor"),
                {"expires": boundary, "actor": uuid.UUID(actor.user_id)},
            )
        async with factory() as blocker, blocker.begin():
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await asyncio.wait_for(blocker.execute(text("SELECT pg_advisory_xact_lock(827004)")), 3)
            release.set()
            await wait_blocked(factory, waiter_pid, blocker_pid)
            async with factory() as session:
                assert await session.scalar(
                    text("""
                    SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                      AND classid=0 AND objid=827004 AND NOT granted)
                """),
                    {"pid": waiter_pid},
                )
            await wait_after(factory, boundary)
        await asyncio.wait_for(task, 20)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM generated_files WHERE render_job_id=:job"), {"job": job}
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT state FROM render_jobs WHERE render_job_id=:job"), {"job": job}
            )
            == "failed"
        )
        assert (
            await session.scalar(
                text("SELECT state FROM document_publication_outbox WHERE render_job_id=:job"),
                {"job": job},
            )
            == "failed"
        )
        assert (
            await session.scalar(
                text("""
            SELECT count(*) FROM audit_events WHERE action='document.render' AND result='success'
              AND actor_user_id=:actor
        """),
                {"actor": uuid.UUID(actor.user_id)},
            )
            == 0
        )


@pytest.mark.asyncio
async def test_readonly_snapshot_does_not_take_the_global_audit_fence(
    factory: Any, tmp_path: Path
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    plan = await actions.create_plan(
        actor,
        PlanRequest(
            idempotency_key=f"RQB-readonly-{uuid.uuid4()}",
            objective="Readonly fence isolation",
            source_refs=refs,
            steps=(
                StepRequest(
                    step_key="read",
                    capability_id="sot.read",
                    capability_version="2",
                    arguments={"record_key": refs[0].record_key},
                ),
            ),
        ),
        request_id="RQB-readonly-plan",
    )
    async with factory() as blocker, blocker.begin():
        await blocker.execute(text("SELECT pg_advisory_xact_lock(827004)"))
        async with factory() as session:
            await asyncio.wait_for(
                actions._snapshot(session, actor, plan.payload, "RQB-readonly"), 3
            )
