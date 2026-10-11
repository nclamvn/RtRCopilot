"""Independent full-path Action overlay parity and controlled scheduling races.

Discovery, SQL metadata mutations, the unchanged Repository oracle and real
PolicyEngine are unmocked. Pauses after delegated discovery are scheduling only,
not SQL row-lock or SDK proof. Frozen prior test modules remain unchanged.
"""

import asyncio
import uuid
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_document_recovery_integration as recovery
from sqlalchemy import text
from test_action_policy_batching_integration import (
    acl,
    leaf,
    reference_attributes,
    reference_projection,
)

from rtr_copilot.actions import policy as policy_module
from rtr_copilot.actions.authority import LeafRequest
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


async def generated(factory: Any) -> dict[str, Any]:
    # The recovery helper's default Subject carries roles only in memory.
    # Positive restricted-source policy needs the same role persisted in SQL.
    owner = await fixtures.principal(factory, Role.CURATOR)
    service, owner, template = await recovery.approved_template(factory, owner=owner)
    job = await service.create_render(
        owner,
        template,
        RenderRequest(
            idempotency_key=f"RQB-overlay-{uuid.uuid4()}", parameters={"customer_name": "Synthetic"}
        ),
        request_id="RQB-overlay-render",
    )
    await service.process_render(job.render_job_id, worker_id="RQB-overlay")
    output = await service.status(owner, job.render_job_id, request_id="RQB-overlay-status")
    assert output.state == "completed" and output.version_id
    async with factory() as session:
        row = (
            (
                await session.execute(
                    text("""
            SELECT v.version_id,v.document_id,v.object_id,
              (SELECT rendition_id FROM renditions WHERE version_id=v.version_id
               ORDER BY created_at,rendition_id LIMIT 1) AS rendition_id,
              (SELECT parent_resource_id FROM upload_sessions
               WHERE document_id=v.document_id ORDER BY created_at DESC LIMIT 1) AS parent_id
            FROM document_versions v WHERE v.version_id=:version
        """),
                    {"version": output.version_id},
                )
            )
            .mappings()
            .one()
        )
    assert row["rendition_id"] and row["parent_id"]
    return {**dict(row), "owner": owner, "template": template}


async def source(factory: Any, owner: Any) -> uuid.UUID:
    resource = await leaf(factory, owner, resource_type="source")
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO sources(source_id,kind,name)
            VALUES(:id,'RQB-overlay','Synthetic overlay source')
        """),
            {"id": resource},
        )
    return resource


async def oracle(factory: Any, actor: Any, resource: uuid.UUID) -> Any:
    async with factory() as session:
        subject, principals = await reference_projection(session, uuid.UUID(actor.user_id))
        result = await reference_attributes(session, resource, "view", principals)
        allowed = (
            result is not None
            and PolicyEngine(StructuredAuditSink())
            .decide(subject, "view", result[0], PolicyContext(request_id="RQB-overlay-independent"))
            .allow
        )
        return result, allowed


async def update_resource(factory: Any, resource: uuid.UUID, **changes: Any) -> None:
    permitted = {
        "classification",
        "owner_subject_id",
        "source_zone",
        "department_id",
        "project_id",
        "lifecycle_state",
    }
    assert changes and changes.keys() <= permitted
    assignments = ",".join(f"{column}=:{column}" for column in changes)
    async with factory() as session, session.begin():
        await session.execute(
            text(f"UPDATE resources SET {assignments} WHERE resource_id=:id"),
            {"id": resource, **changes},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["version_id", "object_id", "document_id", "rendition_id"])
@pytest.mark.parametrize("case", ["ordinary", "source_ancestor", "leaf_scope"])
async def test_full_path_overlay_matches_unchanged_repository_and_policy(
    factory: Any, local_boundaries: Any, kind: str, case: str
) -> None:
    item = await generated(factory)
    actor, resource = item["owner"], item[kind]
    if case == "source_ancestor":
        ancestor = await source(factory, actor)
        await update_resource(
            factory, ancestor, classification="restricted", source_zone="private_context"
        )
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE documents SET source_id=:source WHERE document_id=:id"),
                {"source": ancestor, "id": item["document_id"]},
            )
    elif case == "leaf_scope":
        department, project = uuid.uuid4(), uuid.uuid4()
        await update_resource(factory, resource, department_id=department, project_id=project)
        async with factory() as session, session.begin():
            for kind_, key in [("department", department), ("project", project)]:
                await session.execute(
                    text("""
                    INSERT INTO subject_scopes(subject_id,scope_type,scope_key)
                    VALUES(:actor,:kind,:key)
                """),
                    {"actor": uuid.UUID(actor.user_id), "kind": kind_, "key": str(key)},
                )
    expected, permitted = await oracle(factory, actor, resource)
    assert expected is not None and permitted
    async with factory() as session, session.begin():
        policy = ActionPolicy(UnitOfWork(factory))
        actual = await policy.checkpoint(session, actor, [LeafRequest(resource, "view")])
        assert actual.attributes[(resource, "view")] == expected
        decision = PolicyEngine(StructuredAuditSink()).decide(
            actual.subject,
            "view",
            actual.attributes[(resource, "view")][0],
            PolicyContext(request_id="RQB-overlay-candidate"),
        )
        assert decision.allow == permitted


async def paused_check(
    factory: Any, monkeypatch: pytest.MonkeyPatch, actor: Any, resource: uuid.UUID
) -> tuple[Any, Any, Any]:
    reached, release = asyncio.Event(), asyncio.Event()
    original = policy_module.current_effective_attributes

    async def scheduling(session: Any, resource_id: Any, **kwargs: Any) -> Any:
        attributes = await original(session, resource_id, **kwargs)
        if resource_id == resource and not reached.is_set():
            assert attributes is not None and not attributes[0].explicit_deny
            assert len(attributes[1]) > 1
            reached.set()
            await asyncio.wait_for(release.wait(), 10)
        return attributes

    monkeypatch.setattr(policy_module, "current_effective_attributes", scheduling)

    async def check() -> Any:
        async with factory() as session, session.begin():
            return await ActionPolicy(UnitOfWork(factory)).session_resource(
                session, actor, resource, "view", "RQB-overlay-after-discovery"
            )

    task = asyncio.create_task(check())
    await asyncio.wait_for(reached.wait(), 5)
    return task, release, reached


async def cleanup(task: Any, release: Any) -> None:
    release.set()
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "ancestor_class",
        "ancestor_zone_owner",
        "ancestor_owner",
        "ancestor_deleted",
        "ancestor_quarantine",
        "leaf_deleted",
        "leaf_quarantine",
        "department",
        "project",
        "source_security",
        "source_class",
    ],
)
async def test_final_overlay_rejects_real_metadata_drift_after_discovery(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    item = await generated(factory)
    actor, resource, parent = item["owner"], item["version_id"], item["parent_id"]
    ancestor = None
    if fault.startswith("source_"):
        ancestor = await source(factory, actor)
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE documents SET source_id=:source WHERE document_id=:id"),
                {"source": ancestor, "id": item["document_id"]},
            )
    if fault == "ancestor_owner":
        await update_resource(
            factory,
            parent,
            source_zone="private_context",
            owner_subject_id=uuid.UUID(actor.user_id),
        )
    assert (await oracle(factory, actor, resource))[1]
    other = await fixtures.principal(factory)
    task, release, _ = await paused_check(factory, monkeypatch, actor, resource)
    try:
        if fault in {"ancestor_class", "source_class"}:
            await update_resource(factory, ancestor or parent, classification="highly_restricted")
        elif fault in {"ancestor_zone_owner", "ancestor_owner", "source_security"}:
            await update_resource(
                factory,
                ancestor or parent,
                source_zone="private_context",
                owner_subject_id=uuid.UUID(other.user_id),
            )
        elif fault.startswith("ancestor_"):
            await update_resource(
                factory,
                parent,
                lifecycle_state=("deleted" if fault.endswith("deleted") else "quarantined"),
            )
        elif fault.startswith("leaf_"):
            await update_resource(
                factory,
                resource,
                lifecycle_state=("deleted" if fault.endswith("deleted") else "quarantined"),
            )
        else:
            await update_resource(factory, resource, **{f"{fault}_id": uuid.uuid4()})
        _, allowed = await oracle(factory, actor, resource)
        assert not allowed
        release.set()
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
    finally:
        await cleanup(task, release)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["document", "source", "upload_parent", "rendition_version"])
async def test_actual_path_change_denies_even_when_new_path_itself_is_allowed(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    item = await generated(factory)
    actor = item["owner"]
    resource = item["rendition_id"] if path == "rendition_version" else item["version_id"]
    before, allowed = await oracle(factory, actor, resource)
    assert allowed and before is not None
    replacement = await leaf(
        factory, actor, resource_type="document" if path == "document" else "record"
    )
    replacement_version = None
    if path == "rendition_version":
        replacement_document = await leaf(factory, actor, resource_type="document")
        replacement_version = await leaf(factory, actor, resource_type="document_version")
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                INSERT INTO documents(document_id,logical_name)
                VALUES(:document,'Synthetic replacement rendition association')
            """),
                {"document": replacement_document},
            )
            # Legal new version content references the existing immutable blob.
            # It has no competing rendition pipeline key; no uniqueness or
            # immutable-content trigger is disabled or altered.
            await session.execute(
                text("""
                INSERT INTO document_versions(version_id,document_id,version_no,object_id,
                  original_filename,mime_type,sha256,byte_size,created_by)
                SELECT :version,:document,1,object_id,original_filename,mime_type,
                  sha256,byte_size,:actor FROM document_versions WHERE version_id=:original
            """),
                {
                    "version": replacement_version,
                    "document": replacement_document,
                    "actor": uuid.UUID(actor.user_id),
                    "original": item["version_id"],
                },
            )
    new_source = await source(factory, actor) if path == "source" else None
    task, release, _ = await paused_check(factory, monkeypatch, actor, resource)
    try:
        async with factory() as session, session.begin():
            if path == "document":
                await session.execute(
                    text("""
                    INSERT INTO documents(document_id,logical_name)
                    VALUES(:id,'Synthetic replacement path')
                """),
                    {"id": replacement},
                )
                await session.execute(
                    text("""
                    UPDATE document_versions SET document_id=:new WHERE version_id=:id
                """),
                    {"new": replacement, "id": resource},
                )
            elif path == "source":
                await session.execute(
                    text("UPDATE documents SET source_id=:new WHERE document_id=:id"),
                    {"new": new_source, "id": item["document_id"]},
                )
            elif path == "upload_parent":
                await session.execute(
                    text("""
                    UPDATE upload_sessions SET parent_resource_id=:new WHERE document_id=:id
                """),
                    {"new": replacement, "id": item["document_id"]},
                )
            else:
                assert replacement_version is not None
                await session.execute(
                    text("UPDATE renditions SET version_id=:new WHERE rendition_id=:id"),
                    {"new": replacement_version, "id": resource},
                )
        after, allowed = await oracle(factory, actor, resource)
        assert after is not None and after[1] != before[1] and allowed
        release.set()
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
    finally:
        await cleanup(task, release)


@pytest.mark.asyncio
async def test_nullable_object_association_preserves_real_leaf_only_repository_case(
    factory: Any, local_boundaries: Any
) -> None:
    _, actor, template = await recovery.approved_template(factory)
    async with factory() as session:
        resource = await session.scalar(
            text("""
            SELECT source_object_id FROM template_versions WHERE version_id=:template
        """),
            {"template": template},
        )
    expected, permitted = await oracle(factory, actor, resource)
    assert expected is not None and expected[1] == [resource] and permitted
    async with factory() as session, session.begin():
        actual = await ActionPolicy(UnitOfWork(factory)).checkpoint(
            session, actor, [LeafRequest(resource, "view")]
        )
        assert actual.attributes[(resource, "view")] == expected


@pytest.mark.asyncio
async def test_final_overlay_never_undoes_true_discovery_denial(
    factory: Any, local_boundaries: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = await generated(factory)
    actor, resource = item["owner"], item["version_id"]
    await acl(factory, item["document_id"], uuid.UUID(actor.user_id), effect="deny")
    before, permitted = await oracle(factory, actor, resource)
    assert before is not None and before[0].explicit_deny and not permitted
    reached, release = asyncio.Event(), asyncio.Event()
    original = policy_module.current_effective_attributes

    async def scheduling(session: Any, resource_id: Any, **kwargs: Any) -> Any:
        result = await original(session, resource_id, **kwargs)
        if resource_id == resource and not reached.is_set():
            assert result is not None and result[0].explicit_deny
            reached.set()
            await asyncio.wait_for(release.wait(), 10)
        return result

    monkeypatch.setattr(policy_module, "current_effective_attributes", scheduling)

    async def check() -> None:
        async with factory() as session, session.begin():
            await ActionPolicy(UnitOfWork(factory)).session_resource(
                session, actor, resource, "view", "RQB-conservative-deny"
            )

    task = asyncio.create_task(check())
    try:
        await asyncio.wait_for(reached.wait(), 5)
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                DELETE FROM acl_entries WHERE resource_id=:document
                  AND principal_id=:actor AND action='view' AND effect='deny'
            """),
                {"document": item["document_id"], "actor": uuid.UUID(actor.user_id)},
            )
        assert (await oracle(factory, actor, resource))[1]
        release.set()
        with pytest.raises(ActionError):
            await asyncio.wait_for(task, 5)
    finally:
        await cleanup(task, release)
