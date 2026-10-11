"""Legal app-role evidence lifecycle change after real checkpoint metadata.

Controlled scheduling only, not a native/SDK or SQL row-lock-wait proof. The
metadata query, lifecycle trigger, source resolver, policy and submission execute
unmocked. No permission, body, receipt or outcome value is supplied by a hook.
"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
from sqlalchemy import text

from rtr_copilot.actions import service as service_module
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.context.sources import revalidate_sot_references
from rtr_copilot.db.uow import UnitOfWork

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


@pytest.mark.asyncio
async def test_committed_evidence_supersession_after_metadata_denies_actual_submission(
    factory: Any, tmp_path: Path, execution_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions, actor, original_refs, _, _ = await adversarial.domain(factory, tmp_path)
    version = original_refs[0].record_version_id
    async with factory() as session:
        span = (
            (
                await session.execute(
                    text("""
            SELECT span_id,evidence_key FROM evidence_spans
            WHERE record_version_id=:version AND lifecycle='active'
            ORDER BY span_id LIMIT 1
        """),
                    {"version": version},
                )
            )
            .mappings()
            .one()
        )
    refs = (original_refs[0].model_copy(update={"evidence_key": span["evidence_key"]}),)
    plan = await actions.create_plan(
        actor,
        PlanRequest(
            idempotency_key=f"RQB-evidence-{uuid.uuid4()}",
            objective="Read with current requested evidence",
            purpose="proposal",
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
        request_id="RQB-evidence-plan",
    )
    executor = ExecutionService(UnitOfWork(factory), actions=actions)
    executor.settings = execution_config
    reached, release = asyncio.Event(), asyncio.Event()
    real_metadata = service_module.input_metadata

    async def scheduling(session: Any, payload: Any) -> Any:
        metadata = await real_metadata(session, payload)
        if payload.actor_id == plan.payload.actor_id and not reached.is_set():
            assert len(metadata["sources"]) == 1
            assert metadata["sources"][0]["evidence_present"] is True
            reached.set()
            await asyncio.wait_for(release.wait(), 10)
        return metadata

    monkeypatch.setattr(service_module, "input_metadata", scheduling)
    task = asyncio.create_task(
        executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="RQB-evidence-submit")
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)

        async def supersede() -> None:
            async with factory() as session, session.begin():
                identity = (
                    (
                        await session.execute(
                            text("""
                    SELECT current_user AS actor,
                      has_table_privilege(current_user,'evidence_spans','UPDATE') AS may_update
                """)
                        )
                    )
                    .mappings()
                    .one()
                )
                assert identity["actor"] == "rtr_app" and identity["may_update"]
                result = await session.execute(
                    text("""
                    UPDATE evidence_spans SET lifecycle='superseded'
                    WHERE span_id=:span AND lifecycle='active'
                """),
                    {"span": span["span_id"]},
                )
                assert result.rowcount == 1

        # The mutation must genuinely COMMIT while the parent checkpoint is
        # paused. A timeout is not a successful lifecycle-race reproduction.
        await asyncio.wait_for(supersede(), 3)
        assert not task.done()
        async with factory() as session:
            current = (
                (
                    await session.execute(
                        text("""
                SELECT r.current_version_id,r.lifecycle AS record_state,
                  rv.lifecycle AS version_state,p.lifecycle AS package_state,
                  rv.content_sha256,s.security_version,
                  (SELECT lifecycle FROM evidence_spans WHERE span_id=:span) AS evidence_state
                FROM record_versions rv JOIN records r USING(record_id)
                JOIN sot_packages p ON p.package_id=rv.package_id
                JOIN subjects s ON s.user_id=:actor WHERE rv.version_id=:version
            """),
                        {
                            "actor": uuid.UUID(actor.user_id),
                            "version": version,
                            "span": span["span_id"],
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert current["current_version_id"] == version
            assert current["content_sha256"] == refs[0].content_sha256
            assert current["security_version"] == actor.security_version
            assert all(
                current[name] == "active"
                for name in ("record_state", "version_state", "package_state")
            )
            assert current["evidence_state"] == "superseded"
        independent = await revalidate_sot_references(
            actor,
            refs,
            factory=factory,
            use_class="proposal",
            request_id="RQB-evidence-independent",
            include_text=False,
        )
        assert not independent.sources and [gap.code for gap in independent.gaps] == ["unavailable"]
        release.set()
        rejected = False
        try:
            await asyncio.wait_for(task, 5)
        except ActionError:
            rejected = True
        async with factory() as session:
            executions = await session.scalar(
                text("""
                SELECT count(*) FROM action_executions WHERE run_id=:run
            """),
                {"run": plan.run_id},
            )
            false_success = await session.scalar(
                text("""
                SELECT count(*) FROM audit_events WHERE actor_user_id=:actor
                  AND action='action.execution.submit' AND result='success'
                  AND details->>'plan_id'=:plan
            """),
                {"actor": uuid.UUID(actor.user_id), "plan": str(plan.plan_id)},
            )
        assert (rejected, executions, false_success) == (True, 0, 0)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
