"""Reachable evidence-witness serialization, real SQL waits and source parity.

The archived pre-witness race remains unchanged historical evidence. Here actual
pg_blocking_pids proves child/parent waits; metadata hooks only control scheduling.
No SDK/native certification, permission/outcome mocks or immutable-trigger edits.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from test_action_policy_batching_integration import (
    reference_attributes,
    reference_projection,
    wait_after,
    wait_blocked,
)
from test_action_source_batching_integration import resolution_metadata

from rtr_copilot.actions import service as service_module
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Role
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.context.sources import revalidate_sot_references
from rtr_copilot.db.uow import UnitOfWork

pytestmark = fixtures.pytestmark
WITNESS_SQL = "ORDER BY span_id LIMIT 1 FOR SHARE"


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def execution_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    return adversarial.execution_config.__wrapped__(monkeypatch)


async def prepared(
    factory: Any, tmp_path: Path, config: Any, *, required: bool = True, restricted: bool = False
) -> Any:
    actions, actor, original_refs, _, _ = await adversarial.domain(
        factory, tmp_path, restricted=restricted
    )
    async with factory() as session:
        span = (
            (
                await session.execute(
                    text("""
            SELECT span_id,evidence_key,package_id FROM evidence_spans
            WHERE record_version_id=:version AND lifecycle='active'
            ORDER BY span_id LIMIT 1
        """),
                    {"version": original_refs[0].record_version_id},
                )
            )
            .mappings()
            .one()
        )
    refs = (
        original_refs[0].model_copy(
            update={"evidence_key": span["evidence_key"] if required else None}
        ),
    )
    plan = await actions.create_plan(
        actor,
        PlanRequest(
            idempotency_key=f"RQB-witness-{uuid.uuid4()}",
            objective="Read with serialized current evidence",
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
        request_id="RQB-witness-plan",
    )
    executor = ExecutionService(UnitOfWork(factory), actions=actions)
    executor.settings = config
    return actions, actor, refs, plan, executor, span


async def counts(factory: Any, plan: Any, actor: Any) -> tuple[int, int]:
    async with factory() as session:
        executions = await session.scalar(
            text("""
            SELECT count(*) FROM action_executions WHERE run_id=:run
        """),
            {"run": plan.run_id},
        )
        audits = await session.scalar(
            text("""
            SELECT count(*) FROM audit_events WHERE actor_user_id=:actor
              AND action='action.execution.submit' AND result='success'
              AND details->>'plan_id'=:plan
        """),
            {"actor": uuid.UUID(actor.user_id), "plan": str(plan.plan_id)},
        )
    return int(executions), int(audits)


def pause_metadata(monkeypatch: pytest.MonkeyPatch, plan: Any) -> Any:
    reached, release = asyncio.Event(), asyncio.Event()
    observed: dict[str, int] = {}
    original = service_module.input_metadata

    async def scheduling(session: Any, payload: Any) -> Any:
        metadata = await original(session, payload)
        if payload.actor_id == plan.payload.actor_id and not reached.is_set():
            assert len(metadata["sources"]) == 1 and metadata["sources"][0]["evidence_present"]
            observed["parent"] = await session.scalar(text("SELECT pg_backend_pid()"))
            reached.set()
            await asyncio.wait_for(release.wait(), 15)
        return metadata

    monkeypatch.setattr(service_module, "input_metadata", scheduling)
    return reached, release, observed


async def tidy(task: Any, release: Any) -> None:
    release.set()
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def shared(factory: Any, actor: Any, refs: Any) -> Any:
    return await revalidate_sot_references(
        actor,
        refs,
        factory=factory,
        use_class="proposal",
        request_id="RQB-witness-independent",
        include_text=False,
    )


def observe_witnesses(monkeypatch: pytest.MonkeyPatch, observation: Any) -> None:
    # Installed SQLAlchemy scalar delegates to sync_session.scalar, not the
    # async execute method. Observe both real APIs without changing parameters,
    # return values or exceptions; no permission/result is manufactured here.
    original_scalar, original_execute = AsyncSession.scalar, AsyncSession.execute

    async def scalar(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if WITNESS_SQL in " ".join(str(statement).split()):
            await observation(session, original_scalar)
        return await original_scalar(session, statement, *args, **kwargs)

    async def execute(session: Any, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if WITNESS_SQL in " ".join(str(statement).split()):
            await observation(session, original_scalar)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", scalar)
    monkeypatch.setattr(AsyncSession, "execute", execute)


@pytest.mark.asyncio
async def test_actual_child_lifecycle_wait_linearizes_after_valid_parent_admission(
    factory: Any, tmp_path: Path, execution_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, actor, refs, plan, executor, span = await prepared(factory, tmp_path, execution_config)
    reached, release, pids = pause_metadata(monkeypatch, plan)
    parent = asyncio.create_task(
        executor.submit(
            actor, plan.plan_id, plan.plan_digest, request_id="RQB-witness-valid-parent"
        )
    )
    child_ready = asyncio.Event()

    async def child_update() -> None:
        async with factory() as session, session.begin():
            assert await session.scalar(text("SELECT current_user")) == "rtr_app"
            pids["child"] = await session.scalar(text("SELECT pg_backend_pid()"))
            child_ready.set()
            updated = await session.execute(
                text("""
                UPDATE evidence_spans SET lifecycle='superseded'
                WHERE span_id=:span AND lifecycle='active'
            """),
                {"span": span["span_id"]},
            )
            assert updated.rowcount == 1

    child = None
    try:
        await asyncio.wait_for(reached.wait(), 5)
        child = asyncio.create_task(child_update())
        await asyncio.wait_for(child_ready.wait(), 3)
        await wait_blocked(factory, pids["child"], pids["parent"])
        assert not child.done() and not parent.done()
        current = await shared(factory, actor, refs)
        assert len(current.sources) == 1 and not current.gaps
        release.set()
        admitted = await asyncio.wait_for(parent, 5)
        assert admitted.run_id == plan.run_id and admitted.state == "queued"
        await asyncio.wait_for(child, 5)
        assert await counts(factory, plan, actor) == (1, 1)
        revoked = await shared(factory, actor, refs)
        assert not revoked.sources and [gap.code for gap in revoked.gaps] == ["unavailable"]
        # A later domain step must not reuse the formerly valid witness/frame.
        decision = await executor.advance(plan.run_id)
        assert decision.state == "failed" and decision.terminal
        view = await executor.status(actor, plan.run_id)
        assert not any(receipt.kind == "read_verified" for receipt in view.receipts)
    finally:
        await tidy(parent, release)
        if child is not None:
            if not child.done():
                child.cancel()
            await asyncio.gather(child, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["superseded", "missing_key"])
async def test_missing_active_witness_denies_checkpoint_and_persists_no_submission(
    factory: Any, tmp_path: Path, execution_config: Any, fault: str
) -> None:
    actions, actor, refs, plan, executor, span = await prepared(factory, tmp_path, execution_config)
    payload = plan.payload
    if fault == "superseded":
        async with factory() as session, session.begin():
            result = await session.execute(
                text("""
                UPDATE evidence_spans SET lifecycle='superseded' WHERE span_id=:span
            """),
                {"span": span["span_id"]},
            )
            assert result.rowcount == 1
    else:
        # Exact absent-key internal checkpoint, not mutation of immutable plan history.
        refs = (refs[0].model_copy(update={"evidence_key": "RQB-missing-witness"}),)
        payload = payload.model_copy(update={"source_refs": refs})
    independent = await shared(factory, actor, refs)
    assert not independent.sources and [gap.code for gap in independent.gaps] == ["unavailable"]
    async with factory() as session, session.begin():
        with pytest.raises(ActionError, match="source_unavailable"):
            await actions._snapshot(session, actor, payload, "RQB-absent-witness", audit_fence=True)
    if fault == "superseded":
        with pytest.raises(ActionError):
            await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="RQB-superseded-submit"
            )
    else:
        with pytest.raises(ActionError):
            await actions.create_plan(
                actor,
                PlanRequest(
                    idempotency_key=f"RQB-missing-{uuid.uuid4()}",
                    objective="Missing evidence request",
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
                request_id="RQB-missing-plan",
            )
    assert await counts(factory, plan, actor) == (0, 0)


@pytest.mark.asyncio
async def test_actual_evidence_lock_wait_rejects_naturally_expired_actor_role(
    factory: Any, tmp_path: Path, execution_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, actor, _, plan, executor, span = await prepared(
        factory, tmp_path, execution_config, restricted=True
    )
    boundary = datetime.now(UTC) + timedelta(seconds=5)
    async with factory() as session, session.begin():
        expired = await session.execute(
            text("""
            UPDATE subject_roles sr SET expires_at=:boundary FROM roles r
            WHERE sr.role_id=r.role_id AND r.key=:role AND sr.subject_id=:actor
        """),
            {"boundary": boundary, "actor": uuid.UUID(actor.user_id), "role": Role.CURATOR.value},
        )
        assert expired.rowcount == 1
    holder = factory()
    await holder.begin()
    ready, observed = asyncio.Event(), {}

    async def observe(session: Any, original_scalar: Any) -> None:
        if not ready.is_set():
            observed["waiter"] = await original_scalar(session, text("SELECT pg_backend_pid()"))
            ready.set()

    task = None
    try:
        blocker = await holder.scalar(text("SELECT pg_backend_pid()"))
        await holder.execute(
            text("""
            SELECT span_id FROM evidence_spans WHERE span_id=:span FOR UPDATE
        """),
            {"span": span["span_id"]},
        )
        observe_witnesses(monkeypatch, observe)
        task = asyncio.create_task(
            executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="RQB-evidence-role-expiry"
            )
        )
        await asyncio.wait_for(ready.wait(), 3)
        await wait_blocked(factory, observed["waiter"], blocker)
        await wait_after(factory, boundary)
        async with factory() as session:
            security = await session.scalar(
                text("SELECT security_version FROM subjects WHERE user_id=:id"),
                {"id": uuid.UUID(actor.user_id)},
            )
            assert security == actor.security_version
            installed_expiry = await session.scalar(
                text("""
                SELECT sr.expires_at FROM subject_roles sr JOIN roles r USING(role_id)
                WHERE sr.subject_id=:actor AND r.key=:role
            """),
                {"actor": uuid.UUID(actor.user_id), "role": Role.CURATOR.value},
            )
            assert installed_expiry == boundary
            assert await session.scalar(
                text("SELECT clock_timestamp()>:boundary"), {"boundary": installed_expiry}
            )
            current, principals = await reference_projection(session, uuid.UUID(actor.user_id))
            assert current.roles == {Role.STAFF}
            attributes = await reference_attributes(
                session, plan.payload.steps[0].resources[0].resource_id, "view", principals
            )
            assert attributes is not None and attributes[0].classification == "restricted"
            decision = PolicyEngine(StructuredAuditSink()).decide(
                current,
                "view",
                attributes[0],
                PolicyContext(request_id="RQB-evidence-expiry-oracle"),
            )
            assert not decision.allow and decision.reason_code == "classification_denied"
        await holder.rollback()
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
        assert await counts(factory, plan, actor) == (0, 0)
    finally:
        await holder.rollback()
        await holder.close()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_null_evidence_key_has_zero_witness_queries_and_unchanged_shared_result(
    factory: Any, tmp_path: Path, execution_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions, actor, refs, plan, executor, span = await prepared(
        factory, tmp_path, execution_config, required=False
    )
    expected = await shared(factory, actor, refs)
    direct = await actions.policy.sources(actor, plan.payload, "RQB-null-key")
    assert resolution_metadata(direct) == resolution_metadata(expected)
    assert len(expected.sources) == 1 and not expected.gaps
    witness_queries = []

    async def observe(session: Any, original_scalar: Any) -> None:
        witness_queries.append(True)

    observe_witnesses(monkeypatch, observe)
    # Positive control invokes the actual production checkpoint with a valid
    # non-NULL key. Otherwise a broken observation hook could falsely certify 0.
    required_refs = (refs[0].model_copy(update={"evidence_key": span["evidence_key"]}),)
    async with factory() as session, session.begin():
        await actions._snapshot(
            session,
            actor,
            plan.payload.model_copy(update={"source_refs": required_refs}),
            "RQB-witness-observer-positive-control",
        )
    assert witness_queries == [True]
    witness_queries.clear()
    view = await executor.submit(
        actor, plan.plan_id, plan.plan_digest, request_id="RQB-null-submit"
    )
    assert view.state == "queued" and witness_queries == []
    assert await counts(factory, plan, actor) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("retire_all", [False, True])
async def test_cross_package_matching_spans_preserve_any_active_existence_semantics(
    factory: Any,
    tmp_path: Path,
    execution_config: Any,
    monkeypatch: pytest.MonkeyPatch,
    retire_all: bool,
) -> None:
    actions, actor, refs, plan, executor, span = await prepared(factory, tmp_path, execution_config)
    _, _, other_refs, _, _ = await adversarial.domain(factory, tmp_path)
    clone = uuid.uuid4()
    async with factory() as session, session.begin():
        other_package = await session.scalar(
            text("""
            SELECT package_id FROM record_versions WHERE version_id=:version
        """),
            {"version": other_refs[0].record_version_id},
        )
        assert other_package != span["package_id"]
        # Schema permits a separate package's same key to reference this version.
        # Preserve that existing version/key predicate, rather than silently
        # adding a new package filter or locking every matching row.
        await session.execute(
            text("""
            INSERT INTO evidence_spans(span_id,evidence_key,record_version_id,package_id,
              source_ref,source_document_id,source_version_id,source_blob_sha256,locator,
              quoted_text,normalized_text,evidence_sha256,source_label,classification,lifecycle)
            SELECT :clone,evidence_key,record_version_id,:package,source_ref,
              source_document_id,source_version_id,source_blob_sha256,locator,quoted_text,
              normalized_text,evidence_sha256,source_label,classification,'active'
            FROM evidence_spans WHERE span_id=:original
        """),
            {"clone": clone, "package": other_package, "original": span["span_id"]},
        )
    expected = await shared(factory, actor, refs)
    direct = await actions.policy.sources(actor, plan.payload, "RQB-multispan-before")
    assert len(expected.sources) == 1 and not expected.gaps
    assert resolution_metadata(direct) == resolution_metadata(expected)
    if retire_all:
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                UPDATE evidence_spans SET lifecycle='superseded' WHERE span_id=ANY(:spans)
            """),
                {"spans": [span["span_id"], clone]},
            )
        denied = await shared(factory, actor, refs)
        assert not denied.sources and denied.gaps
        with pytest.raises(ActionError):
            await executor.submit(
                actor, plan.plan_id, plan.plan_digest, request_id="RQB-all-retired"
            )
        assert await counts(factory, plan, actor) == (0, 0)
        return
    reached, release, _ = pause_metadata(monkeypatch, plan)
    task = asyncio.create_task(
        executor.submit(actor, plan.plan_id, plan.plan_digest, request_id="RQB-one-witness")
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)
        async with factory() as session:
            ordered = list(
                (
                    await session.execute(
                        text("""
                SELECT span_id FROM evidence_spans WHERE record_version_id=:version
                  AND evidence_key=:key AND lifecycle='active' ORDER BY span_id
            """),
                        {"version": refs[0].record_version_id, "key": refs[0].evidence_key},
                    )
                ).scalars()
            )
        assert len(ordered) == 2

        async def retire_nonwitness() -> None:
            async with factory() as session, session.begin():
                updated = await session.execute(
                    text("""
                    UPDATE evidence_spans SET lifecycle='superseded' WHERE span_id=:span
                """),
                    {"span": ordered[1]},
                )
                assert updated.rowcount == 1

        await asyncio.wait_for(retire_nonwitness(), 3)
        assert not task.done()
        still_valid = await shared(factory, actor, refs)
        assert len(still_valid.sources) == 1 and not still_valid.gaps
        release.set()
        admitted = await asyncio.wait_for(task, 5)
        assert admitted.state == "queued" and await counts(factory, plan, actor) == (1, 1)
    finally:
        await tidy(task, release)
