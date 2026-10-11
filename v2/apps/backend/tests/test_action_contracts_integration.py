"""Actual PostgreSQL/HTTP contract lifecycle; no executor or providers exist."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_document_recovery_integration as recovery
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_context_memory_integration import publish
from test_tip054_baseline_integration import actor

from rtr_copilot.actions import api
from rtr_copilot.actions.models import (
    ApprovalRequest,
    BudgetRequest,
    BudgetUnits,
    CapabilitySpec,
    Destination,
    PlanRequest,
    StepRequest,
)
from rtr_copilot.actions.registry import (
    CONTRACT_OUTPUT,
    HOST_CONTRACTS,
    ActionError,
    HostRegistry,
    canonical,
)
from rtr_copilot.actions.service import ActionService
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.context.models import SOTReference
from rtr_copilot.db.uow import MaintenanceActive, UnitOfWork
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository

DSN = os.getenv("INTEGRATION_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="dedicated synthetic integration DB required")


@pytest.fixture
def local_boundaries(monkeypatch: Any, factory: Any) -> Any:
    return recovery.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest_asyncio.fixture
async def factory() -> Any:
    engine = create_async_engine(
        DSN.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool
    )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def principal(factory: Any, role: Role = Role.STAFF) -> Subject:
    created = await actor(factory)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO subject_roles(subject_id,role_id)
            SELECT :id,role_id FROM roles WHERE key=:role
        """),
            {"id": uuid.UUID(created.user_id), "role": role.value},
        )
    current = await PostgresSubjectRepository(factory).get_by_user_id(uuid.UUID(created.user_id))
    assert current
    return current


async def fixture_domain(
    factory: Any,
    tmp_path: Path,
    *,
    risk: str | None = None,
    annotations: Any = None,
    extra: bool = False,
) -> Any:
    admin = await principal(factory, Role.ADMIN)
    owner = await principal(factory)
    reviewer = await principal(factory, Role.LEADER)
    suffix = uuid.uuid4().hex
    core = f"ACTION.{suffix}"
    refs = await publish(
        tmp_path,
        factory,
        owner,
        f"actions.{suffix}",
        core,
        extra=[(f"ACTION.EXTRA.{suffix}", "extra permitted source")] if extra else None,
        annotations={core: annotations} if annotations else None,
    )
    version = uuid.uuid4().hex
    specs = tuple(spec.model_copy(update={"version": version}) for spec in HOST_CONTRACTS)
    if risk:
        spec = CapabilitySpec(
            capability_id=f"synthetic.{risk.lower()}",
            version=version,
            effect_class=risk,
            policy_action="view",
            implementation_ref="contract_only",
            input_schema={
                "type": "object",
                "maxProperties": 2,
                "additionalProperties": False,
                "required": ["record_key", "amount"],
                "properties": {
                    "record_key": {"type": "string", "maxLength": 256},
                    "amount": {"type": "number", "minimum": 0, "maximum": 1000},
                },
            },
            output_schema=CONTRACT_OUTPUT,
            allowed_destinations=("external_recipient",),
            reconciliation="contract_only",
            compensation="irreversible",
        )
        specs += (spec,)
    service = ActionService(UnitOfWork(factory), registry=HostRegistry(specs))
    for spec in specs:
        await service.admit_capability(admin, spec.capability_id, spec.version, request_id="admit")
    return service, admin, owner, reviewer, refs, version


def request_for(
    refs: tuple[SOTReference, ...],
    version: str,
    *,
    risk: str | None = None,
    reviewer: Subject | None = None,
    **kwargs: Any,
) -> PlanRequest:
    capability = f"synthetic.{risk.lower()}" if risk else "sot.read"
    arguments = {"record_key": refs[0].record_key, **({"amount": 10} if risk else {})}
    return PlanRequest(
        idempotency_key=f"plan-{uuid.uuid4()}",
        objective="Internal contract requested",
        source_refs=refs,
        steps=(
            StepRequest(
                step_key="read",
                capability_id=capability,
                capability_version=version,
                arguments=arguments,
                destination=Destination(kind="external_recipient", recipient="demo@example.invalid")
                if risk
                else None,
            ),
        ),
        reviewers=(uuid.UUID(reviewer.user_id),) if reviewer else (),
        **kwargs,
    )


async def deny(factory: Any, ref: SOTReference, subject: Subject, *, action: str = "view") -> None:
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO acl_entries(resource_id,principal_type,principal_id,action,effect,reason)
            SELECT record_id,'user',:actor,:action,'deny','synthetic-action-denial'
            FROM records WHERE record_key=:key AND source_key=:source
        """),
            {
                "actor": uuid.UUID(subject.user_id),
                "action": action,
                "key": ref.record_key,
                "source": ref.source_key,
            },
        )


@asynccontextmanager
async def client_for(service: ActionService, subject: Subject | None) -> Any:
    app = FastAPI()
    app.include_router(api.router)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        request.state.request_id = request.headers.get("X-Request-ID", "action-http-case")
        result = await call_next(request)
        result.headers["X-Request-ID"] = request.state.request_id
        return result

    app.dependency_overrides[api.action_service] = lambda: service
    app.dependency_overrides[api.file_subject] = lambda: subject
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
        yield client


@pytest.mark.asyncio
async def test_real_http_read_domain_and_no_public_effect_accounting(
    factory: Any, tmp_path: Path
) -> None:
    service, admin, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    request = request_for(refs, version)
    async with client_for(service, owner) as client:
        response = await client.post("/api/v1/actions/plans", json=request.model_dump(mode="json"))
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["state"] == "contract_ready" and not payload["execution_available"]
        assert payload["payload"]["actor_id"] == owner.user_id
        plan = payload["plan_id"]
        ready = await client.post(f"/api/v1/actions/plans/{plan}/validate-ready")
        assert ready.status_code == 200 and not ready.json()["execution_available"]
        receipts = (await client.get(f"/api/v1/actions/plans/{plan}/receipts")).json()
        assert {entry["kind"] for entry in receipts} == {
            "contract_admission",
            "contract_validation",
        }
        assert all(
            entry["outcome"] == "contract_ready" and not entry["execution_available"]
            for entry in receipts
        )
        assert (
            await client.post(f"/api/v1/actions/plans/{plan}/reserve-budget", json={})
        ).status_code == 404
        assert (
            await client.post(f"/api/v1/actions/plans/{plan}/receipts", json={})
        ).status_code == 405
        spoof = request.model_dump(mode="json")
        spoof["actor_id"] = admin.user_id
        assert (await client.post("/api/v1/actions/plans", json=spoof)).status_code == 422
        forbidden = await client.post(
            "/api/v1/actions/capabilities/sot.read/admit",
            json={"version": version},
            headers={"X-Request-ID": "opaque-http-42"},
        )
        assert forbidden.status_code == 403
        assert (
            forbidden.json()["request_id"] == forbidden.headers["X-Request-ID"] == "opaque-http-42"
        )
    async with client_for(service, None) as client:
        assert (await client.get("/api/v1/actions/capabilities")).status_code == 401
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM render_jobs WHERE request_id='action-http-case'")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_canonical_reorder_and_changed_version_are_new_immutable_plans(
    factory: Any, tmp_path: Path
) -> None:
    service, _, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    request = request_for(refs, version)
    first = await service.create_plan(owner, request, request_id="create")
    duplicate = await service.create_plan(owner, request, request_id="duplicate")
    assert first.plan_id == duplicate.plan_id
    changed_key = request.model_copy(update={"idempotency_key": f"new-{uuid.uuid4()}"})
    another = await service.create_plan(owner, changed_key, request_id="new")
    assert first.plan_digest == another.plan_digest
    changed = changed_key.model_copy(
        update={
            "idempotency_key": f"version-{uuid.uuid4()}",
            "objective": "Changed objective",
            "supersedes_plan_id": first.plan_id,
        }
    )
    newer = await service.create_plan(owner, changed, request_id="change")
    assert newer.root_plan_id == first.plan_id and newer.plan_version == 2
    assert newer.plan_digest != first.plan_digest
    async with factory() as session:
        with pytest.raises(DBAPIError):
            async with session.begin():
                await session.execute(
                    text("UPDATE action_plans SET payload='{}' WHERE plan_id=:id"),
                    {"id": first.plan_id},
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("risk", ["R2", "R3"])
async def test_approval_is_digest_bound_and_contract_only(
    factory: Any, tmp_path: Path, risk: str
) -> None:
    service, _, owner, reviewer, refs, version = await fixture_domain(factory, tmp_path, risk=risk)
    request = request_for(refs, version, risk=risk, reviewer=reviewer)
    plan = await service.create_plan(owner, request, request_id="create")
    assert plan.state == "awaiting_approval"
    approval = await service.approve(
        reviewer,
        plan.plan_id,
        ApprovalRequest(
            expected_plan_digest=plan.plan_digest,
        ),
        request_id="approve",
    )
    ready = await service.validate_ready(owner, plan.plan_id, request_id="ready")
    assert ready.state == "contract_ready" and not ready.execution_available
    assert approval.binding.plan_digest == plan.plan_digest
    step = request.steps[0].model_copy(
        update={"arguments": {"record_key": refs[0].record_key, "amount": 11}}
    )
    changed = request.model_copy(
        update={
            "idempotency_key": f"changed-{uuid.uuid4()}",
            "steps": (step,),
            "supersedes_plan_id": plan.plan_id,
        }
    )
    newer = await service.create_plan(owner, changed, request_id="changed")
    assert newer.plan_digest != plan.plan_digest
    with pytest.raises(ActionError, match="approval_required"):
        await service.validate_ready(owner, newer.plan_id, request_id="ready")
    with pytest.raises(ActionError, match="approval_binding_changed"):
        await service.approve(
            reviewer,
            newer.plan_id,
            ApprovalRequest(
                expected_plan_digest=approval.binding.plan_digest,
            ),
            request_id="replay",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["recipient", "version", "source"])
async def test_approval_cannot_authorize_different_scope(
    factory: Any, tmp_path: Path, change: str
) -> None:
    service, admin, owner, reviewer, refs, version = await fixture_domain(
        factory, tmp_path, risk="R3"
    )
    request = request_for(refs, version, risk="R3", reviewer=reviewer)
    plan = await service.create_plan(owner, request, request_id="create")
    old = await service.approve(
        reviewer,
        plan.plan_id,
        ApprovalRequest(
            expected_plan_digest=plan.plan_digest,
        ),
        request_id="approve",
    )
    step = request.steps[0]
    if change == "recipient":
        step = step.model_copy(
            update={
                "destination": Destination(
                    kind="external_recipient", recipient="other@example.invalid"
                )
            }
        )
    elif change == "version":
        current = service.registry.contract(step.capability_id, step.capability_version)
        new_spec = current.model_copy(update={"version": "next"})
        service.registry = HostRegistry(service.registry.all() + (new_spec,))
        await service.admit_capability(
            admin, new_spec.capability_id, "next", request_id="new-version"
        )
        step = step.model_copy(update={"capability_version": "next"})
    else:
        refs = await publish(
            tmp_path, factory, owner, refs[0].source_key, refs[0].record_key, revision=2
        )
    newer = await service.create_plan(
        owner,
        request.model_copy(
            update={
                "idempotency_key": f"changed-{uuid.uuid4()}",
                "steps": (step,),
                "source_refs": refs,
                "supersedes_plan_id": plan.plan_id,
            }
        ),
        request_id="new",
    )
    assert newer.plan_digest != old.binding.plan_digest
    with pytest.raises(ActionError, match="approval_required"):
        await service.validate_ready(owner, newer.plan_id, request_id="ready")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "expired",
        "revoked",
        "reviewer_disabled",
        "reviewer_role",
        "actor_disabled",
        "capability_revoked",
        "source_denied",
    ],
)
async def test_current_authority_and_approval_prevent_ready(
    factory: Any, tmp_path: Path, fault: str
) -> None:
    service, admin, owner, reviewer, refs, version = await fixture_domain(
        factory, tmp_path, risk="R2"
    )
    plan = await service.create_plan(
        owner, request_for(refs, version, risk="R2", reviewer=reviewer), request_id="create"
    )
    approval = await service.approve(
        reviewer,
        plan.plan_id,
        ApprovalRequest(
            expected_plan_digest=plan.plan_digest,
            expires_in_seconds=3600,
        ),
        request_id="approve",
    )
    if fault == "expired":
        service.clock = lambda: approval.binding.expires_at + timedelta(seconds=1)
    elif fault == "revoked":
        await service.revoke_approval(owner, approval.approval_id, request_id="revoke")
    elif fault in {"reviewer_disabled", "actor_disabled"}:
        target = reviewer if fault == "reviewer_disabled" else owner
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE subjects SET status='disabled' WHERE user_id=:id"),
                {"id": uuid.UUID(target.user_id)},
            )
    elif fault == "reviewer_role":
        async with factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM subject_roles WHERE subject_id=:id"),
                {"id": uuid.UUID(reviewer.user_id)},
            )
    elif fault == "capability_revoked":
        await service.revoke_capability(admin, "synthetic.r2", version, request_id="revoke")
    else:
        await deny(factory, refs[0], owner)
    with pytest.raises(ActionError):
        await service.validate_ready(owner, plan.plan_id, request_id="ready")
    async with factory() as session:
        assert (
            await session.scalar(
                text("""
            SELECT count(*) FROM action_receipts WHERE run_id=:run AND kind='contract_validation'
        """),
                {"run": plan.run_id},
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["revoked", "reviewer_disabled", "unused_source_acl"])
async def test_transaction_final_guard_closes_precheck_race(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    service, _, owner, reviewer, refs, version = await fixture_domain(
        factory, tmp_path, risk="R2", extra=True
    )
    plan = await service.create_plan(
        owner, request_for(refs, version, risk="R2", reviewer=reviewer), request_id="create"
    )
    approval = await service.approve(
        reviewer,
        plan.plan_id,
        ApprovalRequest(
            expected_plan_digest=plan.plan_digest,
        ),
        request_id="approve",
    )
    original = service._snapshot
    fired = False

    async def inject(session: Any, current: Any, payload: Any, request_id: str) -> None:
        nonlocal fired
        if not fired:
            fired = True
            if fault == "revoked":
                # Direct, genuine row transition avoids acquiring the run lock
                # already held by the final guard; represents a committed prior revocation.
                async with factory() as other, other.begin():
                    await other.execute(
                        text("""
                        UPDATE action_approvals SET revoked_at=now(),revoked_by=:actor
                        WHERE approval_id=:id
                    """),
                        {"actor": uuid.UUID(owner.user_id), "id": approval.approval_id},
                    )
            elif fault == "reviewer_disabled":
                async with factory() as other, other.begin():
                    await other.execute(
                        text("UPDATE subjects SET status='disabled' WHERE user_id=:id"),
                        {"id": uuid.UUID(reviewer.user_id)},
                    )
            else:
                await deny(factory, refs[1], owner)
        await original(session, current, payload, request_id)

    monkeypatch.setattr(service, "_snapshot", inject)
    with pytest.raises(ActionError):
        await service.validate_ready(owner, plan.plan_id, request_id="race")
    async with factory() as session:
        assert (
            await session.scalar(
                text("""
            SELECT count(*) FROM action_receipts WHERE run_id=:run AND kind='contract_validation'
        """),
                {"run": plan.run_id},
            )
            == 0
        )


@pytest.mark.asyncio
async def test_parent_budget_reservation_is_atomic_and_idempotent(
    factory: Any, tmp_path: Path
) -> None:
    service, _, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    plan = await service.create_plan(
        owner, request_for(refs, version, budget=BudgetRequest(tool_calls=2)), request_id="create"
    )
    results = await asyncio.gather(
        *(
            service.reserve_budget(
                owner,
                plan.plan_id,
                BudgetUnits(tool_calls=1),
                idempotency_key=f"child-{number:08}",
                request_id="reserve",
            )
            for number in range(6)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(value, BudgetUnits) for value in results) == 2
    assert (
        sum(
            isinstance(value, ActionError) and value.code == "budget_exhausted" for value in results
        )
        == 4
    )
    events = await service.events(owner, plan.plan_id, request_id="events")
    assert sum(entry.event_type == "budget_reserved" for entry in events) == 2
    successful_key = next(
        number for number, value in enumerate(results) if isinstance(value, BudgetUnits)
    )
    same = await service.reserve_budget(
        owner,
        plan.plan_id,
        BudgetUnits(tool_calls=1),
        idempotency_key=f"child-{successful_key:08}",
        request_id="same",
    )
    assert same.tool_calls == 2
    with pytest.raises(ActionError, match="idempotency_conflict"):
        await service.reserve_budget(
            owner,
            plan.plan_id,
            BudgetUnits(tool_calls=2),
            idempotency_key=f"child-{successful_key:08}",
            request_id="different",
        )


@pytest.mark.asyncio
async def test_private_reads_and_redacted_receipts_do_not_leak_payload(
    factory: Any, tmp_path: Path
) -> None:
    service, _, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    unrelated = await principal(factory, Role.LEADER)
    secret = "private objective and source text never belongs in domain event"
    request = request_for(refs, version).model_copy(update={"objective": secret})
    header = "password=untrusted-header-secret"
    plan = await service.create_plan(owner, request, request_id=header)
    async with client_for(service, unrelated) as client:
        for suffix in ("", "/approvals", "/events", "/receipts"):
            denied = await client.get(f"/api/v1/actions/plans/{plan.plan_id}{suffix}")
            assert denied.status_code == 404, denied.text
            assert secret not in denied.text and refs[0].record_key not in denied.text
    async with factory() as session:
        events = await session.scalar(
            text("""
            SELECT jsonb_agg(to_jsonb(e))::text FROM action_events e WHERE run_id=:id
        """),
            {"id": plan.run_id},
        )
        audit = await session.scalar(
            text("""
            SELECT jsonb_agg(to_jsonb(a))::text FROM audit_events a
            WHERE details->>'plan_id'=:id
        """),
            {"id": str(plan.plan_id)},
        )
    assert all(
        value not in str(events) + str(audit)
        for value in (secret, header, refs[0].record_key, "HERA current permitted capability")
    )
    await deny(factory, refs[0], owner)
    async with client_for(service, owner) as client:
        blocked = await client.get(f"/api/v1/actions/plans/{plan.plan_id}")
        assert blocked.status_code == 403 and secret not in blocked.text


@pytest.mark.asyncio
async def test_denied_purpose_unknown_scope_and_unpriced_work_fail_admission(
    factory: Any, tmp_path: Path
) -> None:
    annotations = {
        "value": {
            "capability": "Sensitive sales only",
            "sot_tier": "attested_practice",
            "use_class": ["sales"],
        }
    }
    service, _, owner, _, refs, version = await fixture_domain(
        factory, tmp_path, annotations=annotations
    )
    request = request_for(refs, version, purpose="attestation")
    with pytest.raises(ActionError, match="source_unavailable"):
        await service.create_plan(owner, request, request_id="purpose")
    with pytest.raises(ActionError, match="scope_unavailable"):
        await service.create_plan(
            owner, request.model_copy(update={"workspace_id": uuid.uuid4()}), request_id="scope"
        )
    with pytest.raises(ActionError, match="unpriced_work_unavailable"):
        await service.create_plan(
            owner,
            request.model_copy(update={"budget": BudgetRequest(model_calls=1)}),
            request_id="unpriced",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["official", "parameters", "revoked_template"])
async def test_internal_draft_contract_reuses_current_template_rules(
    factory: Any,
    tmp_path: Path,
    local_boundaries: Any,
    fault: str,
) -> None:
    service, _, _, _, _, version = await fixture_domain(factory, tmp_path)
    documents, owner, template = await recovery.approved_template(factory)
    request = PlanRequest(
        idempotency_key=f"draft-{uuid.uuid4()}",
        objective="Requested internal draft",
        requested_internal_draft=True,
        steps=(
            StepRequest(
                step_key="draft",
                capability_id="documents.create_draft",
                capability_version=version,
                arguments={
                    "template_version_id": str(template),
                    "parameters": {"customer_name": "Demo"},
                },
            ),
        ),
    )
    if fault == "official":
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                UPDATE templates SET document_class='official' WHERE current_version_id=:id
            """),
                {"id": template},
            )
        with pytest.raises(ActionError, match="template_unavailable"):
            await service.create_plan(owner, request, request_id="draft")
    elif fault == "parameters":
        step = request.steps[0].model_copy(
            update={
                "arguments": {
                    "template_version_id": str(template),
                    "parameters": {"model_added_field": "No"},
                }
            }
        )
        with pytest.raises(ActionError, match="arguments_invalid"):
            await service.create_plan(
                owner, request.model_copy(update={"steps": (step,)}), request_id="draft"
            )
    else:
        plan = await service.create_plan(owner, request, request_id="draft")
        assert plan.state == "contract_ready" and not plan.execution_available
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE template_versions SET status='retired' WHERE version_id=:id"),
                {"id": template},
            )
        with pytest.raises(ActionError, match="template_unavailable"):
            await service.validate_ready(owner, plan.plan_id, request_id="ready")
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM render_jobs WHERE template_version_id=:id"),
                {"id": template},
            )
            == 0
        )


@pytest.mark.asyncio
async def test_small_pool_concurrent_duplicate_plan_does_not_nest_checkout(
    factory: Any, tmp_path: Path
) -> None:
    service, _, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    engine = create_async_engine(
        DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
    )
    bounded = ActionService(
        UnitOfWork(async_sessionmaker(engine, expire_on_commit=False)), registry=service.registry
    )
    request = request_for(refs, version)
    try:
        plans = await asyncio.wait_for(
            asyncio.gather(
                *(bounded.create_plan(owner, request, request_id="duplicate") for _ in range(6))
            ),
            8,
        )
        assert len({plan.plan_id for plan in plans}) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_maintenance_and_admin_drift_block_mutations(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, admin, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    original = service.policy.manage_registry
    calls = 0

    def precheck(current: Subject, request_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            assert Role.ADMIN not in current.roles
        original(current, request_id)

    original_current = service.policy.current

    async def admin_loses_role(subject: Subject) -> Subject:
        current = await original_current(subject)
        async with factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM subject_roles WHERE subject_id=:id"),
                {"id": uuid.UUID(admin.user_id)},
            )
        return current

    monkeypatch.setattr(service.policy, "manage_registry", precheck)
    monkeypatch.setattr(service.policy, "current", admin_loses_role)
    with pytest.raises(ActionError, match="forbidden"):
        await service.revoke_capability(admin, "sot.read", version, request_id="admin-drift")
    monkeypatch.setattr(service.policy, "current", original_current)
    async with factory() as session, session.begin():
        await session.execute(text("UPDATE maintenance_state SET enabled=true WHERE singleton"))
    try:
        with pytest.raises(MaintenanceActive):
            await service.create_plan(owner, request_for(refs, version), request_id="maintenance")
    finally:
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE maintenance_state SET enabled=false WHERE singleton")
            )


@pytest.mark.asyncio
async def test_effective_classification_is_pinned_not_raw_fact_label(
    factory: Any,
    tmp_path: Path,
) -> None:
    service, _, owner, leader, refs, version = await fixture_domain(factory, tmp_path)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            UPDATE resources SET classification='restricted' WHERE resource_id IN
              (SELECT record_id FROM records WHERE source_key=:source)
        """),
            {"source": refs[0].source_key},
        )
    with pytest.raises(ActionError, match="source_unavailable"):
        await service.create_plan(owner, request_for(refs, version), request_id="low-clearance")
    plan = await service.create_plan(leader, request_for(refs, version), request_id="restricted")
    assert plan.payload.steps[0].resources[0].classification == "restricted"
    assert plan.payload.steps[0].resources[0].content_sha256 == refs[0].content_sha256


@pytest.mark.asyncio
async def test_locked_draft_sources_are_frozen_resource_bindings(
    factory: Any,
    tmp_path: Path,
    local_boundaries: Any,
) -> None:
    service, _, owner, _, refs, version = await fixture_domain(factory, tmp_path)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO subject_roles(subject_id,role_id)
            SELECT :id,role_id FROM roles WHERE key='curator'
        """),
            {"id": uuid.UUID(owner.user_id)},
        )
    current_owner = await PostgresSubjectRepository(factory).get_by_user_id(
        uuid.UUID(owner.user_id)
    )
    assert current_owner is not None
    owner = current_owner
    refs = await publish(
        tmp_path,
        factory,
        owner,
        refs[0].source_key,
        refs[0].record_key,
        revision=2,
        annotations={refs[0].record_key: {"value": {"capability": "15 km"}}},
    )
    _, _, template = await recovery.approved_template(factory, refs[0].record_key, owner)
    request = PlanRequest(
        idempotency_key=f"locked-{uuid.uuid4()}",
        objective="Internal locked draft",
        source_refs=refs,
        requested_internal_draft=True,
        steps=(
            StepRequest(
                step_key="draft",
                capability_id="documents.create_draft",
                capability_version=version,
                arguments={"template_version_id": str(template), "parameters": {}},
            ),
        ),
    )
    plan = await service.create_plan(owner, request, request_id="locked-draft")
    resources = plan.payload.steps[0].resources
    assert {item.resource_type for item in resources} == {"record", "template_version"}
    fact = next(item for item in resources if item.resource_type == "record")
    assert fact.version_id == refs[0].record_version_id
    assert fact.content_sha256 == refs[0].content_sha256
    await deny(factory, refs[0], owner)
    with pytest.raises(ActionError):
        await service.validate_ready(owner, plan.plan_id, request_id="revoked-fact")


@pytest.mark.asyncio
async def test_persisted_packet_link_requires_current_owner_and_purpose(
    factory: Any,
    tmp_path: Path,
) -> None:
    service, _, owner, stranger, refs, version = await fixture_domain(factory, tmp_path)
    packet = uuid.uuid4()
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO context_packets(packet_id,owner_subject_id,scope_kind,use_class,
              ontology_digest,query_digest,source_refs,entity_ids,memory_refs,
              max_bytes,max_estimated_tokens)
            VALUES (:packet,:actor,'private','proposal',:digest,:digest,
              CAST(:refs AS jsonb),'{}','[]',4096,1024)
        """),
            {
                "packet": packet,
                "actor": uuid.UUID(owner.user_id),
                "digest": "a" * 64,
                "refs": canonical([ref.model_dump(mode="json") for ref in refs]).decode(),
            },
        )
    request = request_for(refs, version, context_packet_id=packet)
    plan = await service.create_plan(owner, request, request_id="packet")
    assert plan.payload.context_packet_id == packet
    with pytest.raises(ActionError, match="scope_unavailable"):
        await service.create_plan(stranger, request, request_id="wrong-owner")
    with pytest.raises(ActionError, match="scope_unavailable"):
        await service.create_plan(
            owner, request.model_copy(update={"purpose": "sales"}), request_id="wrong-purpose"
        )
