"""Generic Action nonleaf fallback: controlled AFTER-real-attrs scheduling.

This is not an ordinary SELECT lock or SDK proof. Actual generated nonleaf
lineage, unchanged ResourceRepository, SQL ACLs and PolicyEngine run unmocked.
Only scheduling pauses after the real fallback result, before its final batch.
Strict bound record/template paths are separately type-fenced and not implicated.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_document_recovery_integration as recovery
from sqlalchemy import text
from test_action_policy_batching_integration import (
    reference_attributes,
    reference_projection,
    wait_after,
)

from rtr_copilot.actions import policy as policy_module
from rtr_copilot.actions.policy import ActionPolicy
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Role
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import RenderRequest

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return recovery.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["allow_expiry", "late_deny"])
async def test_real_nonleaf_acl_does_not_survive_the_final_projection_wait(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    documents, owner, template = await recovery.approved_template(factory)
    job = await documents.create_render(
        owner,
        template,
        RenderRequest(
            idempotency_key=f"RQB-generic-{uuid.uuid4()}", parameters={"customer_name": "Synthetic"}
        ),
        request_id="RQB-generic-render",
    )
    await documents.process_render(job.render_job_id, worker_id="RQB-generic")
    output = await documents.status(owner, job.render_job_id, request_id="RQB-generic-status")
    assert output.state == "completed" and output.version_id
    viewer = await fixtures.principal(factory, Role.CURATOR)
    grant = uuid.uuid4()
    async with factory() as session, session.begin():
        document = await session.scalar(
            text("SELECT document_id FROM document_versions WHERE version_id=:version"),
            {"version": output.version_id},
        )
        await session.execute(
            text("""
            INSERT INTO acl_entries(acl_id,resource_id,principal_type,principal_id,
              action,effect,reason) VALUES(:grant,:document,'user',:viewer,'view','allow',
              'RQB-real-inherited-grant')
        """),
            {"grant": grant, "document": document, "viewer": uuid.UUID(viewer.user_id)},
        )
    policy = ActionPolicy(UnitOfWork(factory))
    async with factory() as session:
        await policy.session_resource(session, viewer, output.version_id, "view", "RQB-before")
    reached, release = asyncio.Event(), asyncio.Event()
    real_attributes = policy_module.current_effective_attributes

    async def observed_attributes(session: Any, resource: Any, **kwargs: Any) -> Any:
        result = await real_attributes(session, resource, **kwargs)
        if resource == output.version_id and not reached.is_set():
            assert result is not None and not result[0].explicit_deny
            assert document in result[1] and len(result[1]) > 1
            reached.set()
            await asyncio.wait_for(release.wait(), 10)
        return result

    monkeypatch.setattr(policy_module, "current_effective_attributes", observed_attributes)

    async def check() -> Any:
        async with factory() as session, session.begin():
            return await policy.session_resource(
                session, viewer, output.version_id, "view", "RQB-after-fallback-wait"
            )

    task = asyncio.create_task(check())
    try:
        await asyncio.wait_for(reached.wait(), 5)
        boundary = datetime.now(UTC) + timedelta(seconds=2)
        async with factory() as session, session.begin():
            if fault == "allow_expiry":
                await session.execute(
                    text("UPDATE acl_entries SET expires_at=:expires WHERE acl_id=:id"),
                    {"expires": boundary, "id": grant},
                )
            else:
                await session.execute(
                    text("""
                    INSERT INTO acl_entries(resource_id,principal_type,principal_id,action,
                      effect,reason) VALUES(:document,'user',:viewer,'view','deny',
                      'RQB-late-denial')
                """),
                    {"document": document, "viewer": uuid.UUID(viewer.user_id)},
                )
        if fault == "allow_expiry":
            await wait_after(factory, boundary)
        async with factory() as session:
            current, principals = await reference_projection(session, uuid.UUID(viewer.user_id))
            fresh = await reference_attributes(session, output.version_id, "view", principals)
            assert current.security_version == viewer.security_version
            assert fresh is not None and fresh[0].explicit_deny
            assert (
                not PolicyEngine(StructuredAuditSink())
                .decide(
                    current,
                    "view",
                    fresh[0],
                    PolicyContext(request_id="RQB-independent-fallback-oracle"),
                )
                .allow
            )
        release.set()
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
