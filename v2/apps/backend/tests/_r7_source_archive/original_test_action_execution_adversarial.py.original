"""Independent .4b SQL/domain adversarial tests, not native SDK certification.

Real UOW, immutable ledgers, subject projection and PolicyEngine are exercised.
Only synthetic object storage/queue hints and an explicit staging pause are
controlled. Native process death/restore and measured HTTP loads are separate
proof gates. The capability-revocation test is deliberately last: v2 admission
is immutable and revocation must not be undone merely to clean up a test.
"""

import asyncio
import base64
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as action_fixtures
import test_document_recovery_integration as recovery
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_action_contracts_integration import deny, principal
from test_context_memory_integration import publish
from test_documents_unit import pdf_template

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_models import ExecutionLeaseLost
from rtr_copilot.actions.models import BudgetRequest, PlanRequest, StepRequest
from rtr_copilot.actions.registry import EXECUTION_CONTRACTS, ActionError, HostRegistry
from rtr_copilot.actions.service import ActionService
from rtr_copilot.auth.models import Role
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import MaintenanceActive, UnitOfWork
from rtr_copilot.documents.models import (
    BindingDefinition,
    FieldRules,
    RenderRequest,
    TemplateImport,
    TemplateSchema,
)
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.ingestion import api as files_api

pytestmark = recovery.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for session_factory in action_fixtures.factory.__wrapped__():
        yield session_factory


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    # Domain tests do not launch an SDK or contact this URL. The fixture runner
    # supplies the real engine URL for separate native-runtime tests.
    configured = get_settings().model_copy(
        update={
            "action_executor_enabled": True,
            "action_workflow_dsn": get_settings().action_workflow_dsn
            or PostgresDsn("postgresql://synthetic:synthetic@engine.invalid/action_engine"),
        }
    )
    monkeypatch.setattr("rtr_copilot.actions.execution.get_settings", lambda: configured)
    return configured


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return recovery.local_boundaries.__wrapped__(monkeypatch, factory)


async def domain(
    factory: Any,
    tmp_path: Path,
    *,
    locked: bool = False,
    restricted: bool = False,
    expiring: bool = False,
) -> Any:
    admin = await principal(factory, Role.ADMIN)
    owner = await principal(factory, Role.CURATOR)
    suffix = uuid.uuid4().hex
    key = f"ADVERSARIAL.{suffix}"
    annotation: dict[str, Any] = {
        "value": {"capability": "HERA", "use_class": ["sales", "proposal"]}
    }
    if expiring:
        annotation["freshness_due_at"] = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()
    refs = await publish(
        tmp_path, factory, owner, f"adversarial.{suffix}", key, annotations={key: annotation}
    )
    if restricted:
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                UPDATE resources SET classification='restricted' WHERE resource_id IN
                  (SELECT record_id FROM records WHERE source_key=:source)
            """),
                {"source": refs[0].source_key},
            )
    actions = ActionService(UnitOfWork(factory), registry=HostRegistry())
    for spec in EXECUTION_CONTRACTS:
        await actions.admit_capability(
            admin, spec.capability_id, spec.version, request_id="adversarial-admit"
        )
    documents = DocumentOSService(UnitOfWork(factory))
    version = None
    if locked:
        template = await documents.import_template(
            owner,
            TemplateImport(
                stable_key=f"adversarial.{suffix}",
                display_name="Adversarial inherited output",
                category="verification",
                format="pdf",
                classification="internal",
                field_schema=TemplateSchema(
                    bindings=[
                        BindingDefinition(
                            field_path="range",
                            field_type="string",
                            source="locked_fact",
                            required=True,
                            record_key=key,
                            value_literal="HERA",
                            rules=FieldRules(max_length=100),
                            accepted_provenance=["approved_internal"],
                        )
                    ]
                ),
                source_base64=base64.b64encode(pdf_template()).decode(),
            ),
            request_id="adversarial-import",
        )
        version = template.version_id
        await documents.lifecycle(owner, version, "submit", request_id="template-submit")
        await documents.lifecycle(owner, version, "approve", request_id="template-approve")
    return actions, owner, refs, documents, version


async def submitted(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    *,
    draft: bool = False,
    restricted: bool = False,
    budget: BudgetRequest | None = None,
    two_reads: bool = False,
    expiring: bool = False,
) -> Any:
    actions, owner, refs, documents, version = await domain(
        factory,
        tmp_path,
        locked=draft,
        restricted=restricted,
        expiring=expiring,
    )
    step = StepRequest(
        step_key="draft" if draft else "read",
        capability_version="2",
        capability_id="documents.create_draft" if draft else "sot.read",
        arguments={"template_version_id": str(version), "parameters": {}}
        if draft
        else {"record_key": refs[0].record_key},
    )
    plan = await actions.create_plan(
        owner,
        PlanRequest(
            idempotency_key=f"adversarial-{uuid.uuid4()}",
            objective="Requested governed internal draft",
            source_refs=refs,
            steps=(
                step,
                step.model_copy(update={"step_key": "second_read", "dependencies": ("read",)}),
            )
            if two_reads
            else (step,),
            requested_internal_draft=draft,
            budget=budget or BudgetRequest(),
        ),
        request_id="adversarial-plan",
    )
    executor = ExecutionService(UnitOfWork(factory), actions=actions)
    executor.settings = execution_config
    view = await executor.submit(
        owner, plan.plan_id, plan.plan_digest, request_id="adversarial-submit"
    )
    return executor, owner, refs, documents, plan, view


async def accepted_job(executor: ExecutionService, owner: Any, run_id: uuid.UUID) -> uuid.UUID:
    decision = await executor.advance(run_id)
    assert decision.state == "waiting" and not decision.terminal
    view = await executor.status(owner, run_id)
    receipts = [item for item in view.receipts if item.kind == "job_accepted"]
    assert len(receipts) == 1 and receipts[0].source_id is not None
    assert not any(item.kind == "artifact_verified" for item in view.receipts)
    return receipts[0].source_id


async def sql_rejected(factory: Any, query: str, params: dict[str, Any]) -> None:
    with pytest.raises(DBAPIError):
        async with factory() as session, session.begin():
            await session.execute(text(query), params)


async def narrower_revision(factory: Any, tmp_path: Path, owner: Any, refs: Any) -> None:
    # Published SOT payloads are immutable. A legitimate new publication narrows
    # purpose and replaces the current version, never edits approved history.
    await publish(
        tmp_path,
        factory,
        owner,
        refs[0].source_key,
        refs[0].record_key,
        revision=2,
        annotations={
            refs[0].record_key: {
                "value": {
                    "capability": "HERA",
                    "use_class": ["sales"],
                }
            }
        },
    )


@pytest.mark.asyncio
async def test_owner_status_cancel_survive_revoked_source_but_content_does_not(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
) -> None:
    executor, owner, refs, _, _, view = await submitted(factory, tmp_path, execution_config)
    await executor.advance(view.run_id)
    first = await executor.status(owner, view.run_id)
    assert len(first.receipts) == 1 and first.receipts[0].kind == "read_verified"
    await deny(factory, refs[0], owner)
    visible = await executor.status(owner, view.run_id)
    assert visible.receipts == first.receipts and visible.spent_tool_calls == 1
    with pytest.raises(ActionError):
        await executor.read_output(owner, view.run_id, "read", request_id="revoked-output")
    stopped = await executor.cancel(owner, view.run_id)
    assert stopped.cancel_acknowledged and stopped.state == "partial"
    assert stopped.receipts == first.receipts and stopped.spent_tool_calls == 1


@pytest.mark.asyncio
async def test_partial_cancel_keeps_first_receipt_and_never_dispatches_remaining_step(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
) -> None:
    executor, owner, _, _, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        two_reads=True,
    )
    await executor.advance(view.run_id)
    first = await executor.status(owner, view.run_id)
    assert first.state == "waiting" and first.spent_tool_calls == 1
    assert [(receipt.step_key, receipt.kind) for receipt in first.receipts] == [
        ("read", "read_verified")
    ]
    stopped = await executor.cancel(owner, view.run_id)
    assert stopped.cancel_acknowledged and stopped.state == "partial"
    after = await executor.advance(view.run_id)
    assert after.terminal and after.state == "partial"
    final = await executor.status(owner, view.run_id)
    assert final.receipts == first.receipts and final.spent_tool_calls == 1
    async with factory() as session:
        attempts = (
            (
                await session.execute(
                    text("SELECT step_key FROM action_step_attempts WHERE run_id=:id"),
                    {"id": view.run_id},
                )
            )
            .scalars()
            .all()
        )
    assert attempts == ["read"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["actor_version", "acl", "purpose", "source_stale"])
async def test_current_authority_rechecked_after_persisted_wait(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    mutation: str,
) -> None:
    executor, owner, refs, _, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        expiring=mutation == "source_stale",
    )
    # Queued domain state is durably persisted; no in-memory old authority is
    # patched. A fresh service recovers after the actual database mutation.
    async with factory() as session, session.begin():
        if mutation == "actor_version":
            await session.execute(
                text("UPDATE subjects SET security_version=security_version+1 WHERE user_id=:id"),
                {"id": uuid.UUID(owner.user_id)},
            )
        elif mutation == "source_stale":
            due = await session.scalar(
                text("SELECT freshness_due_at FROM record_versions WHERE version_id=:id"),
                {"id": refs[0].record_version_id},
            )
    if mutation == "acl":
        await deny(factory, refs[0], owner)
    elif mutation == "purpose":
        await narrower_revision(factory, tmp_path, owner, refs)
    elif mutation == "source_stale":
        await asyncio.sleep(max(0, (due - datetime.now(UTC)).total_seconds()) + 0.05)
    fresh = ExecutionService(UnitOfWork(factory), actions=executor.actions)
    fresh.settings = execution_config
    outcome = await fresh.advance(view.run_id)
    assert outcome.terminal and outcome.state == "failed"
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_step_attempts WHERE run_id=:id"),
                {"id": view.run_id},
            )
            == 0
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_execution_receipts WHERE run_id=:id"),
                {"id": view.run_id},
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["cancel", "actor_version", "purpose", "build"])
async def test_linked_action_guard_blocks_after_staging_before_publication(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    executor, owner, refs, documents, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
    )
    job = await accepted_job(executor, owner, view.run_id)
    entered, release = recovery.pause_first_staged(monkeypatch, factory, local_boundaries)
    worker = asyncio.create_task(documents.process_render(job, worker_id="independent-staging"))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        if mutation == "cancel":
            stopped = await executor.cancel(owner, view.run_id)
            assert stopped.state == "partial" and stopped.cancel_acknowledged
        elif mutation == "build":
            changed = execution_config.model_copy(update={"rtr_build_sha": "incompatible-build"})
            monkeypatch.setattr("rtr_copilot.actions.execution.get_settings", lambda: changed)
        elif mutation == "purpose":
            await narrower_revision(factory, tmp_path, owner, refs)
        else:
            async with factory() as session, session.begin():
                await session.execute(
                    text(
                        "UPDATE subjects SET security_version=security_version+1 WHERE user_id=:id"
                    ),
                    {"id": uuid.UUID(owner.user_id)},
                )
    finally:
        release.set()
        await asyncio.wait_for(worker, 10)
    assert await recovery.generated_count(factory, job) == 0
    source = await documents.status(owner, job, request_id="post-staging-status")
    assert source.state == "failed"
    state = await executor.status(owner, view.run_id)
    assert not any(receipt.kind == "artifact_verified" for receipt in state.receipts)
    assert state.spent_tool_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["acl", "purpose"])
async def test_published_output_retains_source_policy_and_max_classification(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    executor, owner, refs, documents, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
        restricted=True,
    )
    job = await accepted_job(executor, owner, view.run_id)
    await documents.process_render(job, worker_id="independent-output")
    source = await documents.status(owner, job, request_id="published-status")
    assert source.state == "completed" and source.generated_file_id and source.version_id
    await executor.advance(view.run_id)
    async with factory() as session:
        resources = (
            (
                await session.execute(
                    text("""
            SELECT classification FROM resources WHERE resource_id=:version
            UNION ALL SELECT r.classification FROM renditions d JOIN resources r
              ON r.resource_id=d.rendition_id WHERE d.version_id=:version
        """),
                    {"version": source.version_id},
                )
            )
            .scalars()
            .all()
        )
    assert resources and set(resources) == {"restricted"}
    permitted = await documents.generated_detail(
        owner, source.generated_file_id, request_id="permitted-generated-detail"
    )
    assert permitted.version_id == source.version_id
    async with factory() as session:
        template_id = await session.scalar(
            text(
                "SELECT tv.template_id FROM template_versions tv "
                "JOIN render_jobs j ON j.template_version_id=tv.version_id "
                "WHERE j.render_job_id=:job"
            ),
            {"job": job},
        )
    permitted_history = await documents.generated_history(
        owner, template_id, request_id="permitted-history"
    )
    assert "HERA" in permitted_history.model_dump_json()
    monkeypatch.setattr(files_api, "UnitOfWork", lambda: UnitOfWork(factory))
    permitted_file = await files_api._version_authorized(
        owner,
        source.version_id,
        action="download",
        request_id="permitted-file",
    )
    assert permitted_file and permitted_file[1]
    if mutation == "acl":
        await deny(factory, refs[0], owner)
    else:
        await narrower_revision(factory, tmp_path, owner, refs)
    with pytest.raises((ActionError, LookupError)):
        await documents.generated_detail(
            owner, source.generated_file_id, request_id="revoked-generated-detail"
        )
    with pytest.raises((ActionError, LookupError)):
        await documents.generated_history(owner, template_id, request_id="revoked-history")
    denied_file = await files_api._version_authorized(
        owner,
        source.version_id,
        action="download",
        request_id="revoked-file",
    )
    assert denied_file is None or not denied_file[1]
    # Source metadata/history survives; protected output is not embedded in it.
    after = await executor.status(owner, view.run_id)
    assert any(receipt.kind == "artifact_verified" for receipt in after.receipts)
    assert "HERA" not in after.model_dump_json()


@pytest.mark.asyncio
async def test_unlinked_canonical_job_is_not_commandeered_or_cancelled(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    executor, owner, _, documents, plan, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
    )
    version = uuid.UUID(plan.payload.steps[0].arguments["template_version_id"])
    normal = await documents.create_render(
        owner,
        version,
        RenderRequest(
            idempotency_key=f"unlinked-{uuid.uuid4()}",
            parameters={},
        ),
        request_id="unlinked-request",
    )
    action_job = await accepted_job(executor, owner, view.run_id)
    assert action_job != normal.render_job_id
    await executor.cancel(owner, view.run_id)
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_source_links WHERE render_job_id=:job"),
                {"job": normal.render_job_id},
            )
            == 0
        )
    await documents.process_render(normal.render_job_id)
    assert await recovery.generated_count(factory, normal.render_job_id) == 1
    await documents.process_render(action_job)
    assert await recovery.generated_count(factory, action_job) == 0


@pytest.mark.asyncio
async def test_expired_owner_cannot_read_or_publish_successor_result(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
) -> None:
    executor, owner, _, _, _, view = await submitted(factory, tmp_path, execution_config)
    old = await executor.claim(view.run_id)
    assert old
    async with factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE action_executions SET lease_expires_at=now()-interval '1 second' "
                "WHERE run_id=:run"
            ),
            {"run": view.run_id},
        )
    await executor.advance(view.run_id)
    new = await executor.status(owner, view.run_id)
    assert new.epoch > old.epoch and len(new.receipts) == 1
    with pytest.raises(ExecutionLeaseLost):
        async with executor.uow.transaction() as session:
            await executor.assert_owned(session, old)
    assert await executor.status(owner, view.run_id) == new


@pytest.mark.asyncio
async def test_sql_budget_deadline_attempts_and_foreign_ownership_are_immutable(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
) -> None:
    executor, owner, _, _, _, view = await submitted(factory, tmp_path, execution_config)
    await executor.advance(view.run_id)
    before = await executor.status(owner, view.run_id)
    assert before.spent_tool_calls == 1
    for query in [
        "UPDATE action_executions SET spent_tool_calls=0 WHERE run_id=:run",
        "UPDATE action_executions SET tool_call_limit=20 WHERE run_id=:run",
        "UPDATE action_executions SET deadline_at=deadline_at+interval '1 hour' WHERE run_id=:run",
        "UPDATE action_step_attempts SET input_digest=repeat('0',64) WHERE run_id=:run",
        "DELETE FROM action_execution_receipts WHERE run_id=:run",
        "DELETE FROM action_execution_events WHERE run_id=:run",
    ]:
        await sql_rejected(factory, query, {"run": view.run_id})
    other, other_owner, _, _, _, other_view = await submitted(factory, tmp_path, execution_config)
    await other.advance(other_view.run_id)
    async with factory() as session:
        foreign_attempt = await session.scalar(
            text("SELECT attempt_id FROM action_step_attempts WHERE run_id=:run"),
            {"run": other_view.run_id},
        )
    await sql_rejected(
        factory,
        """
        INSERT INTO action_execution_receipts(receipt_id,run_id,attempt_id,step_key,attempt,
          kind,output_digest) VALUES(:id,:run,:foreign,'read',1,'needs_review',repeat('0',64))
    """,
        {"id": uuid.uuid4(), "run": view.run_id, "foreign": foreign_attempt},
    )
    assert await executor.status(owner, view.run_id) == before
    assert (await other.status(other_owner, other_view.run_id)).spent_tool_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["canonical_hash", "bound_value"])
async def test_canonical_source_input_tamper_cannot_publish_approved_output(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    mutation: str,
) -> None:
    executor, owner, _, documents, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
    )
    job = await accepted_job(executor, owner, view.run_id)
    # A runtime SQL role either rejects the mutation itself, or the linked
    # publication/source-identity guard must reject the changed source input.
    rejected = False
    try:
        async with factory() as session, session.begin():
            if mutation == "canonical_hash":
                await session.execute(
                    text(
                        "UPDATE render_jobs SET canonical_input_hash=repeat('0',64) "
                        "WHERE render_job_id=:job"
                    ),
                    {"job": job},
                )
            else:
                await session.execute(
                    text(
                        "UPDATE render_job_bindings SET canonical_value="
                        "'\"UNAPPROVED REPLACEMENT\"'::jsonb WHERE render_job_id=:job "
                        "AND field_path='range'"
                    ),
                    {"job": job},
                )
    except DBAPIError:
        rejected = True
    if rejected:
        return
    await documents.process_render(job, worker_id="independent-input-tamper")
    assert await recovery.generated_count(factory, job) == 0
    source = await documents.status(owner, job, request_id="tampered-source")
    assert source.state == "failed"
    after = await executor.status(owner, view.run_id)
    assert not any(receipt.kind == "artifact_verified" for receipt in after.receipts)


@pytest.mark.asyncio
async def test_incompatible_build_pauses_without_new_attempt_and_keeps_deadline(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
) -> None:
    executor, owner, _, _, _, view = await submitted(factory, tmp_path, execution_config)
    executor.settings = execution_config.model_copy(update={"rtr_build_sha": "incompatible-build"})
    outcome = await executor.advance(view.run_id)
    assert outcome.state == "paused"
    after = await executor.status(owner, view.run_id)
    assert after.deadline_at == view.deadline_at and after.spent_tool_calls == 0
    assert not after.receipts
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_step_attempts WHERE run_id=:id"),
                {"id": view.run_id},
            )
            == 0
        )


@pytest.mark.asyncio
async def test_repeated_source_reconciliation_never_resets_or_recharges_parent(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    executor, owner, _, documents, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
        budget=BudgetRequest(tool_calls=1, wall_seconds=60),
    )
    job = await accepted_job(executor, owner, view.run_id)
    for _ in range(3):
        recovered = ExecutionService(UnitOfWork(factory), actions=executor.actions)
        recovered.settings = execution_config
        await recovered.advance(view.run_id)
        after = await recovered.status(owner, view.run_id)
        assert after.spent_tool_calls == 1 and after.deadline_at == view.deadline_at
        assert [receipt.kind for receipt in after.receipts] == ["job_accepted"]
    await documents.process_render(job, worker_id="independent-budget-reconcile")
    await executor.advance(view.run_id)
    await executor.advance(view.run_id)
    final = await executor.status(owner, view.run_id)
    assert final.state == "succeeded" and final.spent_tool_calls == 1
    assert final.deadline_at == view.deadline_at
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_step_attempts WHERE run_id=:id"),
                {"id": view.run_id},
            )
            == 1
        )
    assert await recovery.generated_count(factory, job) == 1


@pytest.mark.asyncio
async def test_unverifiable_completed_source_requires_review_without_redispatch(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    executor, owner, _, documents, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
    )
    job = await accepted_job(executor, owner, view.run_id)
    # The source claims completion but has no artifact/outbox publication oracle.
    # This is not equivalent to a verifiably failed render, nor safe to redispatch.
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE render_jobs SET state='completed',progress=100 WHERE render_job_id=:job"),
            {"job": job},
        )
    result = await executor.advance(view.run_id)
    assert result.terminal and result.state == "needs_review"
    final = await executor.status(owner, view.run_id)
    assert final.spent_tool_calls == 1
    assert not any(receipt.kind == "artifact_verified" for receipt in final.receipts)
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_step_attempts WHERE run_id=:id"),
                {"id": view.run_id},
            )
            == 1
        )
    assert await recovery.generated_count(factory, job) == 0
    assert (await documents.status(owner, job, request_id="uncertain-source")).state == "completed"


@pytest.mark.asyncio
async def test_maintenance_blocks_execution_submit_and_claim(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
) -> None:
    executor, owner, _, _, plan, view = await submitted(factory, tmp_path, execution_config)
    async with factory() as session, session.begin():
        await session.execute(text("UPDATE maintenance_state SET enabled=true WHERE singleton"))
    try:
        with pytest.raises(MaintenanceActive):
            await executor.claim(view.run_id)
        with pytest.raises(MaintenanceActive):
            await executor.cancel(owner, view.run_id)
        with pytest.raises(MaintenanceActive):
            await executor.submit(owner, plan.plan_id, plan.plan_digest, request_id="maintenance")
    finally:
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE maintenance_state SET enabled=false WHERE singleton")
            )


@pytest.mark.asyncio
async def test_capability_revoked_after_staging_never_publishes(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LAST test: real immutable v2 revocation is intentionally retained.
    executor, owner, _, documents, _, view = await submitted(
        factory,
        tmp_path,
        execution_config,
        draft=True,
    )
    job = await accepted_job(executor, owner, view.run_id)
    entered, release = recovery.pause_first_staged(monkeypatch, factory, local_boundaries)
    worker = asyncio.create_task(documents.process_render(job, worker_id="independent-capability"))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        async with factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE capability_versions SET admission='revoked',revoked_at=now() "
                    "WHERE capability_id='documents.create_draft' AND version='2'"
                )
            )
    finally:
        release.set()
        await asyncio.wait_for(worker, 10)
    assert await recovery.generated_count(factory, job) == 0
    final = await executor.status(owner, view.run_id)
    assert [receipt.kind for receipt in final.receipts] == ["job_accepted"]
    assert final.spent_tool_calls == 1
