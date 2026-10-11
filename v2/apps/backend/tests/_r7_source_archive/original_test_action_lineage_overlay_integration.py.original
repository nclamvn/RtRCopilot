"""Builder real-Repository parity, query ceiling and ordered path drift."""

import asyncio
import uuid
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_document_recovery_integration as recovery
from sqlalchemy import event, text
from test_action_nonleaf_overlay_integration import generated

from rtr_copilot.actions import policy as policy_module
from rtr_copilot.actions.policy import ActionPolicy, current_effective_attributes
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return recovery.local_boundaries.__wrapped__(monkeypatch, factory)


@pytest.mark.asyncio
async def test_real_generated_lineage_parity_and_generic_query_budget(
    factory: Any, local_boundaries: Any,
) -> None:
    data = await generated(factory)
    owner, version = data["owner"], data["version_id"]
    policy = ActionPolicy(UnitOfWork(factory))
    async with factory() as session:
        expected = await current_effective_attributes(
            session, version, action="view", principal_ids={uuid.UUID(owner.user_id)}
        )
    statements = []
    engine = factory.kw["bind"].sync_engine

    def observed(*args: Any) -> None:
        statements.append(args[2])

    async with factory() as session:
        event.listen(engine, "before_cursor_execute", observed)
        try:
            actual = await policy.session_resource(session, owner, version, "view", "RQB-generic")
        finally:
            event.remove(engine, "before_cursor_execute", observed)
    assert expected is not None and actual == expected[0]
    assert len(statements) <= 12


@pytest.mark.asyncio
async def test_changed_latest_upload_parent_fails_closed_even_when_new_path_allows(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = await generated(factory)
    owner, version = data["owner"], data["version_id"]
    parent = ResourceRecord(
        resource_type="template_version", owner_subject_id=uuid.UUID(owner.user_id),
        classification="internal", source_zone="private_context", lifecycle_state="active",
    )
    async with factory() as session, session.begin():
        await ResourceRepository().create(session, parent)
    reached, release = asyncio.Event(), asyncio.Event()
    original = policy_module.current_effective_attributes
    old_path = []

    async def pause(session: Any, resource: Any, **kwargs: Any) -> Any:
        result = await original(session, resource, **kwargs)
        if resource == version and not reached.is_set():
            assert result is not None
            old_path.extend(result[1])
            reached.set()
            await asyncio.wait_for(release.wait(), 5)
        return result

    monkeypatch.setattr(policy_module, "current_effective_attributes", pause)
    policy = ActionPolicy(UnitOfWork(factory))

    async def check() -> Any:
        async with factory() as session:
            return await policy.session_resource(session, owner, version, "view", "RQB-path-drift")

    task = asyncio.create_task(check())
    try:
        await asyncio.wait_for(reached.wait(), 5)
        async with factory() as session, session.begin():
            await session.execute(text("""
                UPDATE upload_sessions SET parent_resource_id=:parent
                WHERE upload_id=(SELECT upload_id FROM upload_sessions
                  WHERE document_id=:document ORDER BY created_at DESC LIMIT 1)
            """), {"parent": parent.resource_id, "document": data["document_id"]})
        async with factory() as session:
            fresh = await original(session, version, action="view",
                                   principal_ids={uuid.UUID(owner.user_id)})
        assert fresh is not None and not fresh[0].explicit_deny
        assert fresh[1] != old_path and fresh[1][-1] == parent.resource_id
        release.set()
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
