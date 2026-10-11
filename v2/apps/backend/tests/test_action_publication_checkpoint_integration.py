"""Real R1 reconstruction/publication with controlled final-check scheduling.

These are domain SQL/pipeline proofs, not native SDK or ordinary SELECT-lock
proofs. The hook pauses entry to the REAL final Action snapshot only after real
canonical reconstruction has run in the final, staged publication transaction.
No authorization return, canonical value, database result or outcome is mocked.
"""

import asyncio
import base64
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fitz
import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
import test_document_recovery_integration as recovery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from test_action_policy_batching_integration import wait_after as real_wait_after
from test_action_policy_batching_integration import wait_blocked
from test_documents_unit import pdf_template

from rtr_copilot.actions import execution as execution_module
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.service import ActionService
from rtr_copilot.auth.models import Role
from rtr_copilot.documents.models import (
    BindingDefinition,
    FieldRules,
    TemplateImport,
    TemplateSchema,
)
from rtr_copilot.documents.service import DocumentOSService

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return recovery.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


async def source_and_multibinding_job(
    factory: Any, tmp_path: Path, settings: Any, *, restricted: bool = False
) -> Any:
    actions, owner, refs, documents, _ = await adversarial.domain(
        factory, tmp_path, restricted=restricted
    )
    actor = await fixtures.principal(factory, Role.CURATOR)
    strings = FieldRules(max_length=100)
    numbers = FieldRules(minimum=0, maximum=3000)
    schema = TemplateSchema(
        bindings=[
            BindingDefinition(
                field_path="first", field_type="string", source="user", required=True, rules=strings
            ),
            BindingDefinition(
                field_path="second",
                field_type="string",
                source="user",
                required=True,
                rules=strings,
            ),
            BindingDefinition(
                field_path="report_date", field_type="date", source="user", required=True
            ),
            BindingDefinition(
                field_path="quantity",
                field_type="integer",
                source="user",
                required=True,
                rules=numbers,
            ),
            BindingDefinition(
                field_path="combined",
                field_type="string",
                source="derived",
                required=True,
                rules=strings,
                derived_operation="concat",
                derived_fields=["first", "second"],
            ),
            *(
                BindingDefinition(
                    field_path=part,
                    field_type="integer",
                    source="derived",
                    required=True,
                    rules=numbers,
                    derived_operation=f"date_{part}",
                    derived_fields=["report_date"],
                )
                for part in ["day", "month", "year"]
            ),
            # Last binding makes the observed locked_fact_value return prove that
            # every earlier user/derived/date branch completed before the pause.
            BindingDefinition(
                field_path="range",
                field_type="string",
                source="locked_fact",
                required=True,
                rules=strings,
                record_key=refs[0].record_key,
                value_literal="HERA",
                accepted_provenance=["approved_internal"],
            ),
        ]
    )
    imported = await documents.import_template(
        owner,
        TemplateImport(
            stable_key=f"rqb.canonical.{uuid.uuid4().hex}",
            display_name="Synthetic canonical proof",
            category="verification",
            format="pdf",
            field_schema=schema,
            source_base64=base64.b64encode(pdf_template()).decode(),
        ),
        request_id="RQB-canonical-import",
    )
    template = imported.version_id
    await documents.lifecycle(owner, template, "submit", request_id="RQB-canonical-submit")
    await documents.lifecycle(owner, template, "approve", request_id="RQB-canonical-approve")
    async with factory() as session, session.begin():
        for action in ["render", "view"]:
            await session.execute(
                text("""
                INSERT INTO acl_entries(resource_id,principal_type,principal_id,
                  action,effect,reason)
                VALUES(:template,'user',:actor,:action,'allow','RQB-canonical-delegation')
            """),
                {"template": template, "actor": uuid.UUID(actor.user_id), "action": action},
            )
    parameters = {
        "first": "=Synthetic",
        "second": "Customer",
        "report_date": "2026-10-06",
        "quantity": 3,
    }
    plan = await actions.create_plan(
        actor,
        PlanRequest(
            idempotency_key=f"RQB-canonical-{uuid.uuid4()}",
            objective="Synthetic real reconstruction",
            requested_internal_draft=True,
            source_refs=refs,
            steps=(
                StepRequest(
                    step_key="draft",
                    capability_id="documents.create_draft",
                    capability_version="2",
                    arguments={
                        "template_version_id": str(template),
                        "parameters": parameters,
                    },
                ),
            ),
        ),
        request_id="RQB-canonical-plan",
    )
    executor = ExecutionService(actions.uow, actions=actions)
    executor.settings = settings
    view = await executor.submit(
        actor, plan.plan_id, plan.plan_digest, request_id="RQB-canonical-execute"
    )
    job = await adversarial.accepted_job(executor, actor, view.run_id)
    expected = {
        "first": "'=Synthetic",
        "second": "Customer",
        "report_date": "2026-10-06",
        "quantity": 3,
        "combined": "=Synthetic Customer",
        "day": 6,
        "month": 10,
        "year": 2026,
        "range": "HERA",
    }
    return executor, actor, refs, documents, plan, template, job, expected


class FinalReconstructionPause:
    """Scheduling-only hook; delegates every production call unchanged."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, job_id: uuid.UUID) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.final_active = False
        self.reconstructed = False
        self.calls = 0
        self.last_value: Any = None
        original_publication = DocumentOSService._publication_guard
        original_locked = execution_module.locked_fact_value
        original_snapshot = ActionService._snapshot

        async def publication(
            service: Any,
            job: Any,
            fields: Any,
            requester: Any,
            *,
            session: Any = None,
            **kwargs: Any,
        ) -> None:
            final = (
                session is not None
                and kwargs.get("audit_writing", True)
                and job["render_job_id"] == job_id
            )
            if final:
                self.final_active = True
                self.reconstructed = False
            try:
                await original_publication(
                    service, job, fields, requester, session=session, **kwargs
                )
            finally:
                if final:
                    self.final_active = False

        def locked(binding: Any, payload: Any) -> Any:
            value = original_locked(binding, payload)
            if self.final_active and binding.field_path == "range":
                self.reconstructed = True
                self.last_value = value
            return value

        async def snapshot(
            service: Any, session: Any, subject: Any, payload: Any, request_id: str, **kwargs: Any
        ) -> None:
            if self.final_active and self.reconstructed and not self.reached.is_set():
                self.calls += 1
                self.reached.set()
                await asyncio.wait_for(self.release.wait(), 15)
            await original_snapshot(service, session, subject, payload, request_id, **kwargs)

        monkeypatch.setattr(DocumentOSService, "_publication_guard", publication)
        monkeypatch.setattr(execution_module, "locked_fact_value", locked)
        monkeypatch.setattr(ActionService, "_snapshot", snapshot)


async def wait_after(factory: Any, boundary: datetime) -> None:
    async with factory() as session:
        for _ in range(160):
            if await session.scalar(
                text("SELECT clock_timestamp()>:boundary"), {"boundary": boundary}
            ):
                return
            await asyncio.sleep(0.025)
    raise AssertionError("controlled scheduling did not cross the SQL expiry boundary")


@pytest.mark.asyncio
async def test_real_user_derived_date_locked_reconstruction_and_atomic_publication(
    factory: Any,
    tmp_path: Path,
    local_boundaries: Any,
    execution_config: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, actor, _, documents, plan, _, job, expected = await source_and_multibinding_job(
        factory, tmp_path, execution_config
    )
    pause = FinalReconstructionPause(monkeypatch, job)
    task = asyncio.create_task(documents.process_render(job, worker_id="RQB-canonical-positive"))
    try:
        await asyncio.wait_for(pause.reached.wait(), 10)
        assert pause.last_value == "HERA" and pause.calls == 1
        pause.release.set()
        await asyncio.wait_for(task, 20)
    finally:
        pause.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    output = await documents.status(actor, job, request_id="RQB-canonical-positive-status")
    assert output.state == "completed" and output.generated_file_id and output.version_id
    async with factory() as session:
        stored = (
            await session.execute(
                text("""
            SELECT field_path,canonical_value FROM render_job_bindings WHERE render_job_id=:job
        """),
                {"job": job},
            )
        ).all()
        manifest = await session.scalar(
            text("SELECT render_manifest FROM generated_files WHERE render_job_id=:job"),
            {"job": job},
        )
        assert {row.field_path: row.canonical_value for row in stored} == expected
        assert {row["field_path"]: row["canonical_value"] for row in manifest["fields"]} == expected
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM document_publication_outbox "
                    "WHERE render_job_id=:job AND state='finalized'"
                ),
                {"job": job},
            )
            == 1
        )
        key = await session.scalar(
            text("""
            SELECT b.object_key FROM document_versions v JOIN object_blobs b USING(object_id)
            WHERE v.version_id=:version
        """),
            {"version": output.version_id},
        )
    with fitz.open(stream=local_boundaries.objects[key], filetype="pdf") as rendered:
        actual_text = "\n".join(page.get_text() for page in rendered)
    assert "HERA" in actual_text and "Synthetic" in actual_text and "Customer" in actual_text
    decision = await executor.advance(plan.run_id)
    if decision.state != "succeeded":
        decision = await executor.advance(plan.run_id)
    assert decision.state == "succeeded"
    execution = await executor.status(actor, plan.run_id)
    assert any(receipt.kind == "artifact_verified" for receipt in execution.receipts)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["role_expiry", "allow_expiry", "grant_revoked", "explicit_deny"])
async def test_rederived_staged_job_cannot_publish_after_late_authority_change(
    factory: Any,
    tmp_path: Path,
    local_boundaries: Any,
    execution_config: Any,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    executor, actor, refs, documents, plan, template, job, _ = await source_and_multibinding_job(
        factory, tmp_path, execution_config, restricted=fault == "role_expiry"
    )
    pause = FinalReconstructionPause(monkeypatch, job)
    task = asyncio.create_task(documents.process_render(job, worker_id="RQB-canonical-negative"))
    try:
        await asyncio.wait_for(pause.reached.wait(), 10)
        assert pause.reconstructed and pause.last_value == "HERA" and pause.calls == 1
        async with factory() as session:
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM generated_files WHERE render_job_id=:job"),
                    {"job": job},
                )
                == 0
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM document_publication_outbox WHERE render_job_id=:job"),
                    {"job": job},
                )
                == "preparing"
            )
            assert (
                await session.scalar(
                    text("""
                SELECT count(*) FROM upload_sessions WHERE original_filename=:filename
                  AND state='accepted' AND document_id IS NOT NULL AND version_id IS NOT NULL
            """),
                    {"filename": f"generated-{job}.pdf"},
                )
                == 1
            )
        boundary = datetime.now(UTC) + timedelta(seconds=2)
        async with factory() as session, session.begin():
            params = {"actor": uuid.UUID(actor.user_id), "template": template, "expires": boundary}
            if fault == "role_expiry":
                await session.execute(
                    text("UPDATE subject_roles SET expires_at=:expires WHERE subject_id=:actor"),
                    params,
                )
            elif fault == "allow_expiry":
                await session.execute(
                    text(
                        "UPDATE acl_entries SET expires_at=:expires "
                        "WHERE resource_id=:template AND principal_id=:actor "
                        "AND effect='allow'"
                    ),
                    params,
                )
            elif fault == "grant_revoked":
                await session.execute(
                    text(
                        "DELETE FROM acl_entries WHERE resource_id=:template "
                        "AND principal_id=:actor AND effect='allow'"
                    ),
                    params,
                )
            else:
                await session.execute(
                    text("""
                    INSERT INTO acl_entries(resource_id,principal_type,principal_id,action,
                      effect,reason) SELECT record_id,'user',:actor,'view','deny','RQB-late-deny'
                    FROM records WHERE source_key=:source AND record_key=:key
                """),
                    {
                        "actor": uuid.UUID(actor.user_id),
                        "source": refs[0].source_key,
                        "key": refs[0].record_key,
                    },
                )
        if fault in {"role_expiry", "allow_expiry"}:
            await wait_after(factory, boundary)
        pause.release.set()
        await asyncio.wait_for(task, 20)
    finally:
        pause.release.set()
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
            SELECT count(*) FROM resources WHERE lifecycle_state='active' AND resource_id IN (
              SELECT document_id FROM upload_sessions WHERE original_filename=:filename
              UNION SELECT version_id FROM upload_sessions WHERE original_filename=:filename)
        """),
                {"filename": f"generated-{job}.pdf"},
            )
            == 0
        )
    decision = await executor.advance(plan.run_id)
    assert decision.state != "succeeded"
    execution = await executor.status(actor, plan.run_id)
    assert not any(receipt.kind == "artifact_verified" for receipt in execution.receipts)


@pytest.mark.asyncio
async def test_actual_input_wait_expiry_denies_before_any_full_canonical_fact_body_query(
    factory: Any,
    tmp_path: Path,
    local_boundaries: Any,
    execution_config: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, actor, refs, documents, _, _, job, _ = await source_and_multibinding_job(
        factory, tmp_path, execution_config, restricted=True
    )
    async with factory() as session:
        record = await session.scalar(
            text("SELECT record_id FROM records WHERE source_key=:source"),
            {"source": refs[0].source_key},
        )
    boundary = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE subject_roles SET expires_at=:expires WHERE subject_id=:actor"),
            {"expires": boundary, "actor": uuid.UUID(actor.user_id)},
        )
    entered = asyncio.get_running_loop().create_future()
    reads = 0
    real_execute = AsyncSession.execute

    async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal reads
        sql = " ".join(str(statement).split())
        if sql.startswith("SELECT rv.value_payload,"):
            reads += 1
        if not entered.done() and "FROM record_versions rv" in sql and "FOR SHARE OF r,rv,p" in sql:
            result = await real_execute(session, text("SELECT pg_backend_pid()"))
            entered.set_result(result.scalar_one())
        return await real_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", execute)
    async with factory() as blocker, blocker.begin():
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(
            text("SELECT record_id FROM records WHERE record_id=:id FOR UPDATE"), {"id": record}
        )
        task = asyncio.create_task(documents.process_render(job, worker_id="RQB-prebody-authority"))
        try:
            waiter = await asyncio.wait_for(entered, 5)
            await wait_blocked(factory, waiter, blocker_pid)
            await real_wait_after(factory, boundary)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    await asyncio.wait_for(task, 15)
    assert reads == 0, "denied actor reached a full canonical source-body query"
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT state FROM render_jobs WHERE render_job_id=:job"), {"job": job}
            )
            == "failed"
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM generated_files WHERE render_job_id=:job"), {"job": job}
            )
            == 0
        )
