"""Independent RQB SQL parity and real post-projection lock-wait proofs.

The pre-R 64 scenarios remain untouched. Reference projection/ACL queries below
are independent of the Action candidate, and decisions use the real PolicyEngine.
Two-session barriers prove PostgreSQL actually blocked before changing time or
metadata. No SDK, provider, external storage or fixture lifecycle is invoked.
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
import test_document_recovery_integration as recovery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.execution import action_output_guard
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.policy import (
    ActionPolicy,
    current_effective_attributes,
    current_principal_ids,
)
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import (
    PolicyContext,
    Role,
    Subject,
    SubjectStatus,
    TemporaryEntitlement,
)
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import RenderRequest
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository

pytestmark = fixtures.pytestmark
UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


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


async def reference_projection(
    session: AsyncSession, actor_id: uuid.UUID
) -> tuple[Subject, set[uuid.UUID]]:
    """Independent SQL projection; never calls ActionPolicy or identity helpers."""
    row = (
        (
            await session.execute(
                text("""
        SELECT user_id,issuer,provider_sub,email,canonical_domain,display_name,status,
          security_version FROM subjects WHERE user_id=:id
    """),
                {"id": actor_id},
            )
        )
        .mappings()
        .one()
    )
    roles = (
        await session.execute(
            text("""
        SELECT r.role_id,r.key FROM subject_roles sr JOIN roles r USING(role_id)
        WHERE sr.subject_id=:id AND sr.valid_from<=statement_timestamp()
          AND (sr.expires_at IS NULL OR sr.expires_at>statement_timestamp())
    """),
            {"id": actor_id},
        )
    ).all()
    groups = (
        await session.execute(
            text("""
        SELECT g.group_id,g.provider_group_key FROM subject_groups sg JOIN groups g USING(group_id)
        WHERE sg.subject_id=:id AND sg.valid_from<=statement_timestamp()
          AND (sg.expires_at IS NULL OR sg.expires_at>statement_timestamp())
    """),
            {"id": actor_id},
        )
    ).all()
    scopes = (
        await session.execute(
            text("""
        SELECT scope_type,scope_key,CASE WHEN scope_key ~* :pattern
          THEN CAST(scope_key AS uuid) END principal FROM subject_scopes
        WHERE subject_id=:id AND valid_from<=statement_timestamp()
          AND (expires_at IS NULL OR expires_at>statement_timestamp())
    """),
            {"id": actor_id, "pattern": UUID_PATTERN},
        )
    ).all()
    grants = (
        (
            await session.execute(
                text("""
        SELECT action,resource_id,conditions,expires_at FROM entitlements
        WHERE subject_id=:id AND active AND effect='allow'
          AND expires_at IS NOT NULL AND expires_at>now()
    """),
                {"id": actor_id},
            )
        )
        .mappings()
        .all()
    )
    subject = Subject(
        user_id=str(row["user_id"]),
        issuer=row["issuer"],
        sub=row["provider_sub"],
        email=row["email"] or "",
        canonical_domain=row["canonical_domain"] or "",
        display_name=row["display_name"],
        status=SubjectStatus(row["status"]),
        security_version=row["security_version"],
        roles={Role(item.key) for item in roles} or {Role.STAFF},
        groups={item.provider_group_key for item in groups},
        departments={item.scope_key for item in scopes if item.scope_type == "department"},
        projects={item.scope_key for item in scopes if item.scope_type == "project"},
        temporary_entitlements=[
            TemporaryEntitlement(
                action=item["action"],
                resource_id=str(item["resource_id"]) if item["resource_id"] else None,
                classification=item["conditions"].get("classification"),
                expires_at=item["expires_at"],
            )
            for item in grants
        ],
    )
    principals = {
        actor_id,
        *(item.role_id for item in roles),
        *(item.group_id for item in groups),
        *(item.principal for item in scopes if item.principal is not None),
    }
    return subject, principals


async def reference_attributes(
    session: AsyncSession, resource: uuid.UUID, action: str, principals: set[uuid.UUID]
) -> Any:
    """Unchanged full Repo plus independently expressed old/current ACL overlay."""
    result = await ResourceRepository().effective_policy_attributes(
        session, resource, action=action, principal_ids=principals
    )
    if result is None:
        return None
    attributes, lineage = result
    current = (
        await session.execute(
            text("""
        SELECT EXISTS(SELECT 1 FROM acl_entries WHERE resource_id=ANY(:lineage)
          AND principal_id=ANY(:principals) AND action=:action AND effect='deny'
          AND valid_from<=statement_timestamp()
          AND (expires_at IS NULL OR expires_at>statement_timestamp())) denied,
          EXISTS(SELECT 1 FROM acl_entries WHERE resource_id=ANY(:lineage)
          AND principal_id=ANY(:principals) AND action=:action AND effect='allow'
          AND valid_from<=statement_timestamp()
          AND (expires_at IS NULL OR expires_at>statement_timestamp())) allowed
    """),
            {"lineage": lineage, "principals": list(principals), "action": action},
        )
    ).one()
    owner = attributes.owner_id in {str(principal) for principal in principals}
    attributes.explicit_deny = (
        attributes.explicit_deny
        or current.denied
        or (attributes.source_zone == "private_context" and not owner and not current.allowed)
    )
    return attributes, lineage


def normalized(subject: Subject) -> dict[str, Any]:
    value = subject.model_dump()
    value["temporary_entitlements"] = sorted(
        value["temporary_entitlements"],
        key=lambda grant: (
            grant["action"],
            grant["resource_id"] or "",
            grant["classification"] or "",
            grant["expires_at"],
        ),
    )
    return value


async def leaf(factory: Any, owner: Subject, **kwargs: Any) -> uuid.UUID:
    record = ResourceRecord(
        resource_type=kwargs.pop("resource_type", "record"),
        owner_subject_id=uuid.UUID(owner.user_id),
        classification="internal",
        source_zone="sot",
        lifecycle_state="active",
    ).model_copy(update=kwargs)
    async with factory() as session, session.begin():
        await ResourceRepository().create(session, record)
    return record.resource_id


async def acl(
    factory: Any,
    resource: uuid.UUID,
    principal: uuid.UUID,
    *,
    action: str = "view",
    effect: str = "allow",
    principal_type: str = "user",
    expires: datetime | None = None,
    starts: datetime | None = None,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO acl_entries(resource_id,principal_type,principal_id,action,effect,
              valid_from,expires_at,reason)
            VALUES(:resource,:kind,:principal,:action,:effect,
              COALESCE(:starts,statement_timestamp()),:expires,'RQB-synthetic')
        """),
            {
                "resource": resource,
                "kind": principal_type,
                "principal": principal,
                "action": action,
                "effect": effect,
                "starts": starts,
                "expires": expires,
            },
        )


async def wait_blocked(factory: Any, waiter: int, blocker: int) -> None:
    """Actual PG wait evidence, not an elapsed-time assumption or scheduling flag."""
    async with factory() as session:
        for _ in range(100):
            blocked = await session.scalar(
                text("SELECT :blocker=ANY(pg_blocking_pids(:waiter))"),
                {"blocker": blocker, "waiter": waiter},
            )
            if blocked:
                return
            await asyncio.sleep(0.025)
    raise AssertionError("candidate never reached the required real SQL lock wait")


async def wait_after(factory: Any, instant: datetime) -> None:
    async with factory() as session:
        for _ in range(600):
            if await session.scalar(
                text("SELECT clock_timestamp()>:instant"), {"instant": instant}
            ):
                return
            await asyncio.sleep(0.025)
    raise AssertionError("finite SQL expiry boundary not reached")


@pytest.mark.asyncio
@pytest.mark.parametrize("memberships", ["none", "active", "temporal_duplicates"])
async def test_projection_matches_independent_sql(factory: Any, memberships: str) -> None:
    actor = await fixtures.principal(factory)
    identity = uuid.UUID(actor.user_id)
    group, department, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with factory() as session, session.begin():
        await session.execute(
            text("DELETE FROM subject_roles WHERE subject_id=:id"), {"id": identity}
        )
        if memberships != "none":
            await session.execute(
                text("""
                INSERT INTO groups(group_id,issuer,provider_group_key,name)
                VALUES(:group,'RQB-synthetic',:label,'Synthetic')
            """),
                {"group": group, "label": f"provider-label-{group}"},
            )
            offsets = (
                [(-120, 3600)]
                if memberships == "active"
                else [(-120, 3600), (-60, 3600), (3600, 7200), (-3600, -60)]
            )
            for starts, ends in offsets:
                params = {"id": identity, "starts": starts, "ends": ends, "group": group}
                await session.execute(
                    text("""
                    INSERT INTO subject_roles(subject_id,role_id,valid_from,expires_at)
                    SELECT :id,role_id,now()+make_interval(secs=>:starts),
                      now()+make_interval(secs=>:ends) FROM roles WHERE key='curator'
                """),
                    params,
                )
                await session.execute(
                    text("""
                    INSERT INTO subject_groups(subject_id,group_id,valid_from,expires_at)
                    VALUES(:id,:group,now()+make_interval(secs=>:starts),
                      now()+make_interval(secs=>:ends))
                """),
                    params,
                )
                for kind, key in [
                    ("department", str(department)),
                    ("project", str(project)),
                    ("project", "non-uuid-project"),
                    ("department", "00000000-0000-0000-0000-000000000001"),
                ]:
                    await session.execute(
                        text("""
                        INSERT INTO subject_scopes(subject_id,scope_type,scope_key,
                          valid_from,expires_at) VALUES(:id,:kind,:key,
                          now()+make_interval(secs=>:starts),now()+make_interval(secs=>:ends))
                    """),
                        {**params, "kind": kind, "key": key},
                    )
        await session.execute(
            text("""
            INSERT INTO entitlements(subject_id,action,effect,conditions,expires_at)
            VALUES(:id,'view','allow','{"classification":"classified"}',now()+interval '1 hour')
        """),
            {"id": identity},
        )
    policy = ActionPolicy(UnitOfWork(factory))
    async with factory() as session, session.begin():
        expected, principals = await reference_projection(session, identity)
        actual = await policy.session_current(session, actor)
        assert normalized(actual) == normalized(expected)
        assert await current_principal_ids(session, actual) == principals
        if memberships == "none":
            assert principals == {identity}  # STAFF fallback is not a grant of the role UUID.
        else:
            assert actual.groups == {f"provider-label-{group}"}
            assert department in principals and project in principals
            assert uuid.UUID("00000000-0000-0000-0000-000000000001") not in principals


@pytest.mark.asyncio
async def test_current_full_identity_is_persisted_not_caller_assertions(factory: Any) -> None:
    actor = await fixtures.principal(factory, Role.CURATOR)
    spoofed = actor.model_copy(
        update={
            "issuer": "unchecked",
            "sub": "unchecked",
            "email": "unchecked@example.invalid",
            "display_name": "unchecked",
            "roles": {Role.ADMIN},
        }
    )
    policy = ActionPolicy(UnitOfWork(factory))
    async with factory() as session:
        expected, _ = await reference_projection(session, uuid.UUID(actor.user_id))
    actual = await policy.current(spoofed)
    assert normalized(actual) == normalized(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_missing_or_disabled_subject_has_no_projection(factory: Any, missing: bool) -> None:
    actor = await fixtures.principal(factory)
    if missing:
        actor = actor.model_copy(update={"user_id": str(uuid.uuid4())})
    else:
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE subjects SET status='disabled' WHERE user_id=:id"),
                {"id": uuid.UUID(actor.user_id)},
            )
    policy = ActionPolicy(UnitOfWork(factory))
    with pytest.raises(ActionError, match="subject_unavailable"):
        await policy.current(actor)
    async with factory() as session:
        with pytest.raises(ActionError, match="subject_unavailable"):
            await policy.session_current(session, actor)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["record", "template_version"])
@pytest.mark.parametrize(
    "case",
    [
        "public",
        "restricted",
        "scope",
        "deny",
        "private_owner",
        "private_allow",
        "private_absent",
        "deleted",
        "quarantined",
    ],
)
async def test_leaf_attributes_and_decisions_match_old_repository(
    factory: Any, kind: str, case: str
) -> None:
    owner = await fixtures.principal(factory, Role.CURATOR)
    actor = owner if case == "private_owner" else await fixtures.principal(factory)
    updates: dict[str, Any] = {"resource_type": kind}
    if case == "public":
        updates["classification"] = "public_internal"
    if case == "restricted":
        updates["classification"] = "restricted"
    if case == "scope":
        updates.update(department_id=uuid.uuid4(), project_id=uuid.uuid4())
    if case.startswith("private_"):
        updates["source_zone"] = "private_context"
    if case in {"deleted", "quarantined"}:
        updates["lifecycle_state"] = case
    resource = await leaf(factory, owner, **updates)
    if case in {"deny", "private_allow"}:
        await acl(
            factory,
            resource,
            uuid.UUID(actor.user_id),
            effect="deny" if case == "deny" else "allow",
        )
    async with factory() as session, session.begin():
        current, principals = await reference_projection(session, uuid.UUID(actor.user_id))
        expected = await reference_attributes(session, resource, "view", principals)
        actual = await current_effective_attributes(
            session, resource, action="view", principal_ids=principals
        )
        assert actual == expected
        if actual is not None:
            context = PolicyContext(request_id="RQB-parity")
            engine = PolicyEngine(StructuredAuditSink())
            assert engine.decide(current, "view", actual[0], context) == engine.decide(
                current, "view", expected[0], context
            )
            assert actual[1] == [resource]


@pytest.mark.asyncio
async def test_action_specific_acl_and_actor_frames_do_not_collide(factory: Any) -> None:
    owner = await fixtures.principal(factory, Role.CURATOR)
    other = await fixtures.principal(factory, Role.CURATOR)
    resource = await leaf(
        factory, owner, resource_type="template_version", source_zone="private_context"
    )
    await acl(factory, resource, uuid.UUID(other.user_id), action="view")
    policy = ActionPolicy(UnitOfWork(factory))
    async with factory() as session:
        await policy.session_resource(session, other, resource, "view", "RQB-view")
        with pytest.raises(ActionError, match="resource_unavailable"):
            await policy.session_resource(session, other, resource, "render", "RQB-render")
        await policy.session_resource(session, owner, resource, "render", "RQB-owner")
        # Mutation occurs after the first result, in the same read session.
        await acl(factory, resource, uuid.UUID(other.user_id), effect="deny")
        with pytest.raises(ActionError, match="resource_unavailable"):
            await policy.session_resource(session, other, resource, "view", "RQB-after-deny")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "action",
        "resource",
        "classification",
        "expired",
        "inactive",
        "deny",
        "null",
    ],
)
async def test_entitlement_projection_keeps_real_policy_constraints(
    factory: Any, fault: str
) -> None:
    owner = await fixtures.principal(factory)
    resource = await leaf(factory, owner, classification="highly_restricted")
    other_resource = await leaf(factory, owner) if fault == "resource" else resource
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO entitlements(subject_id,resource_id,action,effect,conditions,
              active,expires_at) VALUES(:id,:resource,:action,:effect,
              jsonb_build_object('classification',CAST(:class AS text)),:active,:expires)
        """),
            {
                "id": uuid.UUID(owner.user_id),
                "resource": other_resource,
                "action": "render" if fault == "action" else "view",
                "effect": "deny" if fault == "deny" else "allow",
                "class": "restricted" if fault == "classification" else "classified",
                "active": fault != "inactive",
                "expires": None
                if fault == "null"
                else datetime.now(UTC) + timedelta(hours=-1 if fault == "expired" else 1),
            },
        )
    policy = ActionPolicy(UnitOfWork(factory))
    async with factory() as session:
        expected, principals = await reference_projection(session, uuid.UUID(owner.user_id))
        current = await policy.session_current(session, owner)
        assert normalized(current) == normalized(expected)
        attributes = await current_effective_attributes(
            session, resource, action="view", principal_ids=principals
        )
        assert attributes is not None
        context = PolicyContext(request_id="RQB-entitlement")
        actual = PolicyEngine(StructuredAuditSink()).decide(current, "view", attributes[0], context)
        assert actual.allow == (fault == "none")
        assert actual == PolicyEngine(StructuredAuditSink()).decide(
            expected, "view", attributes[0], context
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["deny", "classification", "quarantine"])
async def test_nonleaf_full_lineage_fallback(
    factory: Any, local_boundaries: Any, case: str
) -> None:
    documents, owner, version = await recovery.approved_template(factory)
    job = await documents.create_render(
        owner,
        version,
        RenderRequest(
            idempotency_key=f"RQB-lineage-{uuid.uuid4()}", parameters={"customer_name": "Synthetic"}
        ),
        request_id="RQB-lineage",
    )
    await documents.process_render(job.render_job_id, worker_id="RQB-lineage")
    output = await documents.status(owner, job.render_job_id, request_id="RQB-lineage-status")
    assert output.state == "completed" and output.version_id
    async with factory() as session:
        version_row = (
            await session.execute(
                text("""
            SELECT document_id,object_id FROM document_versions WHERE version_id=:version
        """),
                {"version": output.version_id},
            )
        ).one()
        rendition = await session.scalar(
            text("""
            SELECT rendition_id FROM renditions WHERE version_id=:version LIMIT 1
        """),
            {"version": output.version_id},
        )
    if case == "deny":
        await acl(factory, version_row.document_id, uuid.UUID(owner.user_id), effect="deny")
    else:
        column, value = (
            ("classification", "highly_restricted")
            if case == "classification"
            else ("lifecycle_state", "quarantined")
        )
        async with factory() as session, session.begin():
            await session.execute(
                text(f"UPDATE resources SET {column}=:value WHERE resource_id=:id"),
                {"value": value, "id": version_row.document_id},
            )
    leaves = [output.version_id, version_row.object_id, version_row.document_id]
    if rendition is not None:
        leaves.append(rendition)
    async with factory() as session:
        _, principals = await reference_projection(session, uuid.UUID(owner.user_id))
        for resource in leaves:
            expected = await reference_attributes(session, resource, "view", principals)
            actual = await current_effective_attributes(
                session, resource, action="view", principal_ids=principals
            )
            assert actual == expected
            if case == "quarantine":
                assert actual is None
            elif case == "deny":
                assert actual is not None and actual[0].explicit_deny
            else:
                assert actual is not None and actual[0].classification == "classified"


async def temporal_plan(factory: Any, tmp_path: Path, fault: str) -> Any:
    draft = fault in {"group", "private_allow"}
    actions, owner, refs, _, template = await adversarial.domain(
        factory,
        tmp_path,
        locked=draft,
        restricted=fault in {"role", "entitlement"},
        expiring=fault == "freshness",
    )
    actor = await fixtures.principal(factory, Role.CURATOR) if draft else owner
    async with factory() as session:
        record = await session.scalar(
            text("""
            SELECT record_id FROM records WHERE source_key=:source AND record_key=:key
        """),
            {"source": refs[0].source_key, "key": refs[0].record_key},
        )
    target = template if draft else record
    membership = uuid.uuid4()
    if fault == "group":
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                INSERT INTO groups(group_id,issuer,provider_group_key,name)
                VALUES(:group,'RQB-synthetic',:label,'RQB group')
            """),
                {"group": membership, "label": f"RQB-{membership}"},
            )
            await session.execute(
                text("""
                INSERT INTO subject_groups(subject_id,group_id) VALUES(:actor,:group)
            """),
                {"actor": uuid.UUID(actor.user_id), "group": membership},
            )
    if draft:
        for action in ["render", "view"]:
            await acl(
                factory,
                target,
                membership if fault == "group" else uuid.UUID(actor.user_id),
                action=action,
                principal_type="group" if fault == "group" else "user",
            )
    if fault in {"department", "project"}:
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                INSERT INTO subject_scopes(subject_id,scope_type,scope_key)
                VALUES(:actor,:kind,:key)
            """),
                {"actor": uuid.UUID(actor.user_id), "kind": fault, "key": str(membership)},
            )
            await session.execute(
                text(f"UPDATE resources SET {fault}_id=:scope WHERE resource_id=:resource"),
                {"scope": membership, "resource": record},
            )
    if fault == "entitlement":
        async with factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM subject_roles WHERE subject_id=:actor"),
                {"actor": uuid.UUID(actor.user_id)},
            )
            await session.execute(
                text("""
                INSERT INTO entitlements(subject_id,resource_id,action,effect,expires_at)
                VALUES(:actor,:resource,'view','allow',now()+interval '1 hour')
            """),
                {"actor": uuid.UUID(actor.user_id), "resource": record},
            )
    plan = await actions.create_plan(
        actor,
        PlanRequest(
            idempotency_key=f"RQB-temporal-{uuid.uuid4()}",
            objective="Synthetic post-lock authority",
            source_refs=refs,
            requested_internal_draft=draft,
            steps=(
                StepRequest(
                    step_key="draft" if draft else "read",
                    capability_version="2",
                    capability_id="documents.create_draft" if draft else "sot.read",
                    arguments={"template_version_id": str(template), "parameters": {}}
                    if draft
                    else {"record_key": refs[0].record_key},
                ),
            ),
        ),
        request_id="RQB-temporal-plan",
    )
    return actions, actor, plan, record, template, membership


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gate", "fault"),
    [
        (gate, fault)
        for gate in ["capability", "source"]
        for fault in [
            "role",
            "group",
            "department",
            "project",
            "entitlement",
            "private_allow",
            "future_deny",
        ]
    ]
    + [("template", "group"), ("template", "private_allow")],
)
async def test_actual_later_lock_wait_rejects_expired_or_new_denied_authority(
    factory: Any, tmp_path: Path, local_boundaries: Any, gate: str, fault: str
) -> None:
    actions, actor, plan, record, template, membership = await temporal_plan(
        factory, tmp_path, fault
    )
    expires = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        params = {"actor": uuid.UUID(actor.user_id), "expires": expires, "membership": membership}
        if fault == "role":
            await session.execute(
                text("""
                UPDATE subject_roles SET expires_at=:expires WHERE subject_id=:actor
            """),
                params,
            )
        elif fault == "group":
            await session.execute(
                text("""
                UPDATE subject_groups SET expires_at=:expires
                WHERE subject_id=:actor AND group_id=:membership
            """),
                params,
            )
        elif fault in {"department", "project"}:
            await session.execute(
                text("""
                UPDATE subject_scopes SET expires_at=:expires
                WHERE subject_id=:actor AND scope_type=:kind AND scope_key=:key
            """),
                {**params, "kind": fault, "key": str(membership)},
            )
        elif fault == "entitlement":
            await session.execute(
                text("""
                UPDATE entitlements SET expires_at=:expires WHERE subject_id=:actor
            """),
                params,
            )
        elif fault == "private_allow":
            await session.execute(
                text("""
                UPDATE acl_entries SET expires_at=:expires
                WHERE principal_id=:actor AND resource_id=:template AND effect='allow'
            """),
                {**params, "template": template},
            )
    if fault == "future_deny":
        await acl(factory, record, uuid.UUID(actor.user_id), effect="deny", starts=expires)
    async with factory() as session:
        await actions._snapshot(session, actor, plan.payload, "RQB-before-expiry")
    entered = asyncio.get_running_loop().create_future()

    async def final() -> None:
        async with factory() as session, session.begin():
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await actions._snapshot(session, actor, plan.payload, "RQB-final-after-wait")

    async with factory() as blocker, blocker.begin():
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        if gate == "capability":
            await blocker.execute(
                text("""
                SELECT capability_id FROM capability_versions
                WHERE capability_id=:id AND version='2' FOR UPDATE
            """),
                {"id": plan.payload.steps[0].capability_id},
            )
        elif gate == "template":
            await blocker.execute(
                text("""
                SELECT version_id FROM template_versions WHERE version_id=:id FOR UPDATE
            """),
                {"id": template},
            )
        else:
            await blocker.execute(
                text("SELECT record_id FROM records WHERE record_id=:id FOR UPDATE"), {"id": record}
            )
        task = asyncio.create_task(final())
        try:
            waiter_pid = await asyncio.wait_for(entered, 3)
            await wait_blocked(factory, waiter_pid, blocker_pid)
            await wait_after(factory, expires)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(ActionError):
        await asyncio.wait_for(task, 5)
    # Actor security_version did not change; natural time alone must remove authority.
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT security_version FROM subjects WHERE user_id=:id"),
                {"id": uuid.UUID(actor.user_id)},
            )
            == plan.payload.actor_security_version
        )


@pytest.mark.asyncio
async def test_actual_source_lock_wait_crossing_immutable_freshness_denies(
    factory: Any, tmp_path: Path, local_boundaries: Any
) -> None:
    actions, actor, plan, record, _, _ = await temporal_plan(factory, tmp_path, "freshness")
    async with factory() as session:
        expires = await session.scalar(
            text("""
            SELECT freshness_due_at FROM record_versions WHERE version_id=:id
        """),
            {"id": plan.payload.source_refs[0].record_version_id},
        )
    assert expires and expires > datetime.now(UTC)
    entered = asyncio.get_running_loop().create_future()

    async def final() -> None:
        async with factory() as session, session.begin():
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await actions._snapshot(session, actor, plan.payload, "RQB-source-time")

    async with factory() as blocker, blocker.begin():
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(
            text("SELECT record_id FROM records WHERE record_id=:id FOR UPDATE"), {"id": record}
        )
        task = asyncio.create_task(final())
        try:
            waiter_pid = await asyncio.wait_for(entered, 3)
            await wait_blocked(factory, waiter_pid, blocker_pid)
            # The fixture's published deadline is immutable, not edited by this test.
            await wait_after(factory, expires)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(ActionError, match="source_unavailable"):
        await asyncio.wait_for(task, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["expired_deny", "new_allow"])
async def test_real_wait_preserves_conservative_transaction_and_statement_acl_combination(
    factory: Any, case: str
) -> None:
    owner = await fixtures.principal(factory)
    actor = await fixtures.principal(factory)
    resource = await leaf(factory, owner, source_zone="private_context")
    if case == "expired_deny":
        # Remove absent-ALLOW as an alternate denial cause: only the old active
        # DENY can conservatively keep this otherwise granted access blocked.
        await acl(factory, resource, uuid.UUID(actor.user_id))
    boundary = datetime.now(UTC) + timedelta(seconds=2)
    await acl(
        factory,
        resource,
        uuid.UUID(actor.user_id),
        effect="deny" if case == "expired_deny" else "allow",
        expires=boundary if case == "expired_deny" else None,
        starts=boundary if case == "new_allow" else None,
    )
    entered = asyncio.get_running_loop().create_future()

    async def final() -> None:
        async with factory() as session, session.begin():
            began = await session.scalar(text("SELECT now()"))
            assert began < boundary
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await session.execute(
                text("SELECT resource_id FROM resources WHERE resource_id=:id FOR SHARE"),
                {"id": resource},
            )
            current, principals = await reference_projection(session, uuid.UUID(actor.user_id))
            expected = await reference_attributes(session, resource, "view", principals)
            actual = await current_effective_attributes(
                session, resource, action="view", principal_ids=principals
            )
            assert actual == expected and actual is not None and actual[0].explicit_deny
            assert (
                not PolicyEngine(StructuredAuditSink())
                .decide(current, "view", actual[0], PolicyContext(request_id="RQB-conservative"))
                .allow
            )

    async with factory() as blocker, blocker.begin():
        pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(
            text("SELECT resource_id FROM resources WHERE resource_id=:id FOR UPDATE"),
            {"id": resource},
        )
        task = asyncio.create_task(final())
        try:
            waiter = await asyncio.wait_for(entered, 3)
            await wait_blocked(factory, waiter, pid)
            await wait_after(factory, boundary)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    await asyncio.wait_for(task, 5)


@pytest.mark.asyncio
async def test_linked_output_viewer_is_not_reused_through_origin_capability_wait(
    factory: Any, tmp_path: Path, local_boundaries: Any, execution_config: Any
) -> None:
    executor, owner, _, documents, plan, view = await adversarial.submitted(
        factory, tmp_path, execution_config, draft=True, restricted=True
    )
    job = await adversarial.accepted_job(executor, owner, view.run_id)
    await documents.process_render(job, worker_id="RQB-output")
    output = await documents.status(owner, job, request_id="RQB-output-status")
    assert output.state == "completed" and output.version_id
    viewer = await fixtures.principal(factory, Role.CURATOR)
    template = uuid.UUID(plan.payload.steps[0].arguments["template_version_id"])
    await acl(factory, template, uuid.UUID(viewer.user_id), action="view")
    async with factory() as session:
        await action_output_guard(session, executor.uow, output.version_id, viewer)
    boundary = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE subject_roles SET expires_at=:expires WHERE subject_id=:viewer"),
            {"expires": boundary, "viewer": uuid.UUID(viewer.user_id)},
        )
    entered = asyncio.get_running_loop().create_future()

    async def final() -> None:
        async with factory() as session, session.begin():
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await action_output_guard(session, executor.uow, output.version_id, viewer)

    async with factory() as blocker, blocker.begin():
        pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(
            text("""
            SELECT capability_id FROM capability_versions
            WHERE capability_id='documents.create_draft' AND version='2' FOR UPDATE
        """)
        )
        task = asyncio.create_task(final())
        try:
            waiter = await asyncio.wait_for(entered, 3)
            await wait_blocked(factory, waiter, pid)
            await wait_after(factory, boundary)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(ActionError):
        await asyncio.wait_for(task, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["role", "department"])
async def test_standalone_source_guard_projects_after_its_own_source_wait(
    factory: Any, tmp_path: Path, local_boundaries: Any, fault: str
) -> None:
    actions, actor, plan, record, _, _ = await temporal_plan(factory, tmp_path, fault)
    boundary = datetime.now(UTC) + timedelta(seconds=2)
    async with factory() as session, session.begin():
        table = "subject_roles" if fault == "role" else "subject_scopes"
        await session.execute(
            text(f"UPDATE {table} SET expires_at=:expires WHERE subject_id=:actor"),
            {"expires": boundary, "actor": uuid.UUID(actor.user_id)},
        )
    entered = asyncio.get_running_loop().create_future()

    async def final() -> None:
        async with factory() as session, session.begin():
            current = await actions.policy.session_current(session, actor)
            entered.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await actions._source_snapshot(session, current, plan.payload, "RQB-standalone-source")

    async with factory() as blocker, blocker.begin():
        pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(
            text("SELECT record_id FROM records WHERE record_id=:id FOR UPDATE"), {"id": record}
        )
        task = asyncio.create_task(final())
        try:
            waiter = await asyncio.wait_for(entered, 3)
            await wait_blocked(factory, waiter, pid)
            await wait_after(factory, boundary)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(ActionError):
        await asyncio.wait_for(task, 5)
