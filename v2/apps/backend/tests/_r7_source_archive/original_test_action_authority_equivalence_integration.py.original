"""Direct candidate SQL parity, independent of unchanged compatibility helpers.

Reference SQL/ResourceRepository oracles are imported from the frozen baseline
test module; its source is never edited. These assertions call the NEW candidate
functions directly rather than comparing an unchanged helper against itself.
"""

import uuid
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
from sqlalchemy import text
from test_action_policy_batching_integration import (
    acl,
    leaf,
    normalized,
    reference_attributes,
    reference_projection,
)

from rtr_copilot.actions.authority import LeafRequest, batch_leaf_attributes, project_subject
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Role
from rtr_copilot.auth.policy import PolicyEngine

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.mark.asyncio
@pytest.mark.parametrize("memberships", [False, True])
async def test_direct_new_projection_matches_real_baseline_sql(
    factory: Any, memberships: bool
) -> None:
    actor = await fixtures.principal(factory, Role.CURATOR)
    identity, group, scope = uuid.UUID(actor.user_id), uuid.uuid4(), uuid.uuid4()
    async with factory() as session, session.begin():
        if not memberships:
            await session.execute(
                text("DELETE FROM subject_roles WHERE subject_id=:actor"), {"actor": identity}
            )
        else:
            await session.execute(
                text("""
                INSERT INTO groups(group_id,issuer,provider_group_key,name)
                VALUES(:group,'RQB-direct',:label,'Synthetic direct projection')
            """),
                {"group": group, "label": f"provider-label-{group}"},
            )
            for starts, ends in [(-120, 3600), (-60, 3600), (3600, 7200), (-3600, -60)]:
                params = {"actor": identity, "group": group, "starts": starts, "ends": ends}
                await session.execute(
                    text("""
                    INSERT INTO subject_groups(subject_id,group_id,valid_from,expires_at)
                    VALUES(:actor,:group,now()+make_interval(secs=>:starts),
                      now()+make_interval(secs=>:ends))
                """),
                    params,
                )
                for kind, key in [("department", str(scope)), ("project", "non-uuid-project")]:
                    await session.execute(
                        text("""
                        INSERT INTO subject_scopes(subject_id,scope_type,scope_key,
                          valid_from,expires_at) VALUES(:actor,:kind,:key,
                          now()+make_interval(secs=>:starts),now()+make_interval(secs=>:ends))
                    """),
                        {**params, "kind": kind, "key": key},
                    )
            await session.execute(
                text("""
                INSERT INTO entitlements(subject_id,action,effect,conditions,expires_at)
                VALUES(:actor,'view','allow','{"classification":"classified"}',
                  now()+interval '1 hour')
            """),
                {"actor": identity},
            )
    async with factory() as session, session.begin():
        expected, principals = await reference_projection(session, identity)
        actual = await project_subject(session, identity)
        assert normalized(actual.subject) == normalized(expected)
        assert actual.principal_ids == principals
        if not memberships:
            assert actual.subject.roles == {Role.STAFF} and principals == {identity}


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
async def test_direct_new_leaf_batch_matches_independent_repository_and_policy(
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
        expected_subject, principals = await reference_projection(session, uuid.UUID(actor.user_id))
        expected = await reference_attributes(session, resource, "view", principals)
        actual = await batch_leaf_attributes(
            session, uuid.UUID(actor.user_id), [LeafRequest(resource, "view", kind)]
        )
        assert normalized(actual.subject) == normalized(expected_subject)
        assert actual.principal_ids == principals and not actual.unsupported
        assert actual.attributes[(resource, "view")] == expected
        if expected is not None:
            context = PolicyContext(request_id="RQB-direct-leaf")
            engine = PolicyEngine(StructuredAuditSink())
            assert engine.decide(
                actual.subject, "view", actual.attributes[(resource, "view")][0], context
            ) == engine.decide(expected_subject, "view", expected[0], context)


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_kind", ["template_version", "document"])
async def test_bound_leaf_type_drift_is_not_generic_fallback(
    factory: Any, actual_kind: str
) -> None:
    actor = await fixtures.principal(factory, Role.CURATOR)
    resource = await leaf(factory, actor, resource_type=actual_kind)
    async with factory() as session:
        result = await batch_leaf_attributes(
            session, uuid.UUID(actor.user_id), [LeafRequest(resource, "view", "record")]
        )
    assert (resource, "view") not in result.unsupported
    assert result.attributes[(resource, "view")] is None


@pytest.mark.asyncio
async def test_conflicting_expected_leaf_types_are_not_order_dependent(factory: Any) -> None:
    actor = await fixtures.principal(factory)
    resource = await leaf(factory, actor)
    async with factory() as session:
        with pytest.raises(ActionError, match="resource_unavailable"):
            await batch_leaf_attributes(
                session,
                uuid.UUID(actor.user_id),
                [
                    LeafRequest(resource, "view", "record"),
                    LeafRequest(resource, "view", "template_version"),
                ],
            )


@pytest.mark.asyncio
async def test_direct_batch_keeps_actions_callers_and_fresh_call_boundaries(factory: Any) -> None:
    owner = await fixtures.principal(factory)
    actor = await fixtures.principal(factory)
    resource = await leaf(
        factory, owner, resource_type="template_version", source_zone="private_context"
    )
    await acl(factory, resource, uuid.UUID(actor.user_id), action="view")
    requests = [LeafRequest(resource, action, "template_version") for action in ["view", "render"]]
    async with factory() as session:
        first = await batch_leaf_attributes(session, uuid.UUID(actor.user_id), requests)
        assert not first.attributes[(resource, "view")][0].explicit_deny
        assert first.attributes[(resource, "render")][0].explicit_deny
        other = await batch_leaf_attributes(session, uuid.UUID(owner.user_id), requests)
        assert not other.attributes[(resource, "render")][0].explicit_deny
        await acl(factory, resource, uuid.UUID(actor.user_id), effect="deny")
        last = await batch_leaf_attributes(session, uuid.UUID(actor.user_id), requests)
        assert last.attributes[(resource, "view")][0].explicit_deny
