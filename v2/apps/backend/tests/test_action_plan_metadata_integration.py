"""Strict builtin v2 response seam: real post-commit disclosure races."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_document_recovery_integration as recovery
from sqlalchemy import text
from test_action_execution_adversarial import domain, narrower_revision

from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError, HostRegistry
from rtr_copilot.auth.models import Role

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.fixture
def local_boundaries(monkeypatch: pytest.MonkeyPatch, factory: Any) -> Any:
    return recovery.local_boundaries.__wrapped__(monkeypatch, factory)


def requested(
    refs: Any, *, template: Any = None, versions: tuple[str, ...] = ("2",)
) -> PlanRequest:
    return PlanRequest(
        idempotency_key=uuid.uuid4().hex,
        objective="Bounded metadata admission",
        source_refs=refs,
        requested_internal_draft=bool(template),
        steps=tuple(
            StepRequest(
                step_key=f"step-{n}",
                capability_version=version,
                capability_id="documents.create_draft" if template else "sot.read",
                arguments={"template_version_id": str(template), "parameters": {}}
                if template
                else {"record_key": refs[0].record_key},
            )
            for n, version in enumerate(versions)
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("draft", [False, True])
async def test_v2_builtin_fresh_metadata_without_a_second_content_bind(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_boundaries: Any,
    draft: bool,
) -> None:
    actions, owner, refs, _, template = await domain(factory, tmp_path, locked=draft)
    payload_calls = 0
    original = actions._payload

    async def payload(*args: Any, **kwargs: Any) -> Any:
        nonlocal payload_calls
        payload_calls += 1
        return await original(*args, **kwargs)

    async def legacy(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("strict builtin v2 unexpectedly entered legacy rebind path")

    monkeypatch.setattr(actions, "_payload", payload)
    monkeypatch.setattr(actions, "read_plan", legacy)
    view = await actions.create_plan(
        owner, requested(refs, template=template), request_id="c-valid"
    )
    assert payload_calls == 1 and view.state == "contract_ready"
    async with factory() as session:
        fresh = await actions.repo.plan(session, view.plan_id)
    assert fresh == view


@pytest.mark.asyncio
@pytest.mark.parametrize("versions", [("1",), ("1", "2")])
async def test_legacy_and_mixed_use_unchanged_read_plan(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    versions: tuple[str, ...],
) -> None:
    actions, owner, refs, _, _ = await domain(factory, tmp_path)
    admin = await fixtures.principal(factory, Role.ADMIN)
    await actions.admit_capability(admin, "sot.read", "1", request_id="c-legacy-admit")
    calls = 0
    original = actions.read_plan

    async def read(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    async def fast(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("legacy or mixed plan entered builtin v2 metadata path")

    monkeypatch.setattr(actions, "read_plan", read)
    monkeypatch.setattr(actions, "_metadata_plan", fast)
    await actions.create_plan(owner, requested(refs, versions=versions), request_id="c-fallback")
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "actor",
        "acl",
        "revision",
        "classification",
        "build",
        "host_contract",
        "freshness",
        "template_retired",
        "template_class",
        "template_acl",
    ],
)
async def test_post_insert_pre_response_current_fence_denies(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_boundaries: Any,
    mutation: str,
) -> None:
    draft = mutation.startswith("template")
    actions, owner, refs, _, template = await domain(
        factory, tmp_path, locked=draft, expiring=mutation == "freshness"
    )
    original = actions._metadata_plan
    persisted = []

    async def mutate_after_commit(
        subject: Any, plan_id: Any, expected: Any, request_id: Any, *, _owner: Any = None
    ) -> Any:
        # This checkout can see the actual committed plan. Mutations cannot be
        # hidden in an old insertion transaction or rolled back with its guard.
        async with factory() as session:
            persisted.append(await actions.repo.plan(session, plan_id))
        if mutation == "acl":
            await fixtures.deny(factory, refs[0], owner)
        elif mutation == "revision":
            await narrower_revision(factory, tmp_path, owner, refs)
        elif mutation == "freshness":
            async with factory() as session:
                due = await session.scalar(
                    text("SELECT freshness_due_at FROM record_versions WHERE version_id=:id"),
                    {"id": refs[0].record_version_id},
                )
            await asyncio.sleep(max(0, (due - datetime.now(UTC)).total_seconds()) + 0.05)
        elif mutation == "build":
            actions.build_id = "different-build"
        elif mutation == "host_contract":
            actions.registry = HostRegistry(
                tuple(
                    spec.model_copy(update={"timeout_seconds": spec.timeout_seconds + 1})
                    if spec.version == "2" and spec.capability_id == "sot.read"
                    else spec
                    for spec in actions.registry.all()
                )
            )
        else:
            async with factory() as session, session.begin():
                if mutation == "actor":
                    await session.execute(
                        text(
                            "UPDATE subjects SET security_version=security_version+1 "
                            "WHERE user_id=:id"
                        ),
                        {"id": uuid.UUID(owner.user_id)},
                    )
                elif mutation == "classification":
                    await session.execute(
                        text(
                            "UPDATE resources SET classification='restricted' WHERE resource_id IN "
                            "(SELECT record_id FROM records WHERE source_key=:source)"
                        ),
                        {"source": refs[0].source_key},
                    )
                elif mutation == "template_retired":
                    await session.execute(
                        text("UPDATE template_versions SET status='retired' WHERE version_id=:id"),
                        {"id": template},
                    )
                elif mutation == "template_acl":
                    await session.execute(
                        text(
                            "INSERT INTO acl_entries(resource_id,principal_type,principal_id,"
                            "action,effect,reason) "
                            "VALUES(:id,'user',:actor,'render','deny','c-race')"
                        ),
                        {"id": template, "actor": uuid.UUID(owner.user_id)},
                    )
                else:
                    await session.execute(
                        text(
                            "UPDATE templates SET document_class='official' "
                            "WHERE current_version_id=:id"
                        ),
                        {"id": template},
                    )
        return await original(subject, plan_id, expected, request_id, _owner=_owner)

    monkeypatch.setattr(actions, "_metadata_plan", mutate_after_commit)
    with pytest.raises(ActionError):
        await actions.create_plan(owner, requested(refs, template=template), request_id="c-race")
    assert len(persisted) == 1
    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_receipts WHERE run_id=:run"),
                {"run": persisted[0].run_id},
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM action_executions WHERE run_id=:run"),
                {"run": persisted[0].run_id},
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["unknown", "R2", "R3"])
async def test_strict_metadata_predicate_excludes_unknown_or_higher_effects(
    factory: Any,
    tmp_path: Path,
    unsupported: str,
) -> None:
    # Predicate evidence only; no fabricated adapter is installed or dispatched.
    actions, owner, refs, _, _ = await domain(factory, tmp_path)
    view = await actions.create_plan(owner, requested(refs), request_id="c-predicate")
    step = view.payload.steps[0].model_copy(
        update=(
            {"capability_id": "unknown.read"}
            if unsupported == "unknown"
            else {"effect_class": unsupported}
        )
    )
    changed = view.payload.model_copy(update={"steps": (step,)})
    assert not actions._builtin_execution_payload(changed)


@pytest.mark.asyncio
async def test_post_commit_capability_revoke_denies_response_last(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions, owner, refs, _, _ = await domain(factory, tmp_path)
    original = actions._metadata_plan
    persisted = []

    async def revoked(
        subject: Any, plan_id: Any, expected: Any, request_id: Any, *, _owner: Any = None
    ) -> Any:
        async with factory() as session, session.begin():
            persisted.append(await actions.repo.plan(session, plan_id))
            await session.execute(
                text(
                    "UPDATE capability_versions SET admission='revoked',revoked_at=now() "
                    "WHERE capability_id='sot.read' AND version='2'"
                )
            )
        return await original(subject, plan_id, expected, request_id, _owner=_owner)

    monkeypatch.setattr(actions, "_metadata_plan", revoked)
    with pytest.raises(ActionError, match="capability_unavailable"):
        await actions.create_plan(owner, requested(refs), request_id="c-revoked")
    assert len(persisted) == 1
