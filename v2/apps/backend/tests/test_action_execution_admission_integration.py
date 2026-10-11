"""A/B admission regression: real SQL fences, no runtime/provider simulation."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
from sqlalchemy import text
from test_action_execution_adversarial import domain, narrower_revision

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.models import Role
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


async def setup(factory: Any, tmp_path: Path) -> Any:
    actions, owner, refs, _, _ = await domain(factory, tmp_path)
    admin = await fixtures.principal(factory, Role.ADMIN)
    await actions.admit_capability(admin, "sot.read", "1", request_id="ab-v1-admit")
    executor = ExecutionService(UnitOfWork(factory), actions=actions)
    executor.settings = get_settings().model_copy(update={"action_executor_enabled": True})
    assert executor.settings.action_workflow_dsn is not None
    return actions, executor, owner, refs


def request(refs: Any, *, version: str = "2", key: str | None = None,
            supersedes: Any = None, objective: str = "Bounded real admission") -> PlanRequest:
    return PlanRequest(
        idempotency_key=key or uuid.uuid4().hex, objective=objective, source_refs=refs,
        supersedes_plan_id=supersedes,
        steps=(StepRequest(step_key="read", capability_id="sot.read",
                           capability_version=version,
                           arguments={"record_key": refs[0].record_key}),),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["equal", "different", "mixed"])
async def test_concurrent_same_key_maps_equal_or_conflict(
    factory: Any, tmp_path: Path, mode: str,
) -> None:
    actions, _, owner, refs = await setup(factory, tmp_path)
    key = uuid.uuid4().hex
    first = request(refs, key=key)
    second = request(refs, key=key, version="1" if mode == "mixed" else "2",
                     objective="Conflicting objective" if mode == "different" else first.objective)
    results = await asyncio.gather(
        actions.create_plan(owner, first, request_id="ab-first"),
        actions.create_plan(owner, second, request_id="ab-second"), return_exceptions=True,
    )
    if mode == "equal":
        assert not any(isinstance(r, Exception) for r in results)
        assert results[0].plan_id == results[1].plan_id
    else:
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 1 and isinstance(errors[0], ActionError)
        assert errors[0].code == "idempotency_conflict"
    async with factory() as session:
        assert await session.scalar(text(
            "SELECT count(*) FROM action_plans WHERE actor_id=:actor AND idempotency_key=:key"
        ), {"actor": uuid.UUID(owner.user_id), "key": key}) == 1


@pytest.mark.asyncio
async def test_independent_v2_does_not_wait_for_legacy_actor_fence(
    factory: Any, tmp_path: Path,
) -> None:
    actions, _, owner, refs = await setup(factory, tmp_path)
    async with factory() as blocker, blocker.begin():
        await blocker.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                              {"key": f"action-plan:{owner.user_id}"})
        plans = await asyncio.wait_for(asyncio.gather(*(
            actions.create_plan(owner, request(refs), request_id=f"ab-independent-{n}")
            for n in range(6)
        )), 10)
    assert len({p.plan_id for p in plans}) == 6
    assert all(p.plan_version == 1 and p.root_plan_id == p.plan_id for p in plans)


@pytest.mark.asyncio
async def test_mixed_supersedes_share_contiguous_ordinals(factory: Any, tmp_path: Path) -> None:
    actions, _, owner, refs = await setup(factory, tmp_path)
    base = await actions.create_plan(owner, request(refs), request_id="ab-root")
    plans = await asyncio.gather(*(
        actions.create_plan(owner, request(refs, version="1" if n % 2 else "2",
                            supersedes=base.plan_id), request_id=f"ab-supersedes-{n}")
        for n in range(6)
    ))
    assert {p.root_plan_id for p in plans} == {base.root_plan_id}
    assert sorted(p.plan_version for p in plans) == list(range(2, 8))


@pytest.mark.asyncio
async def test_duplicate_submission_audits_once_and_preserves_cancel_budget_history(
    factory: Any, tmp_path: Path,
) -> None:
    actions, executor, owner, refs = await setup(factory, tmp_path)
    plan = await actions.create_plan(owner, request(refs), request_id="ab-plan")
    submitted = await asyncio.gather(*(
        executor.submit(owner, plan.plan_id, plan.plan_digest, request_id=f"ab-submit-{n}")
        for n in range(5)
    ))
    assert {v.run_id for v in submitted} == {plan.run_id}
    first = submitted[0]
    await executor.advance(plan.run_id)
    stopped = await executor.cancel(owner, plan.run_id)
    assert stopped.state == "partial" and stopped.cancel_requested
    repeated = await executor.submit(owner, plan.plan_id, plan.plan_digest, request_id="ab-repeat")
    assert repeated.state == stopped.state
    assert repeated.cancel_requested == stopped.cancel_requested
    assert repeated.spent_tool_calls == stopped.spent_tool_calls == 1
    assert repeated.deadline_at == first.deadline_at
    async with factory() as session:
        assert await session.scalar(text(
            "SELECT count(*) FROM action_receipts WHERE run_id=:run"
        ), {"run": plan.run_id}) == 1
        assert await session.scalar(text(
            "SELECT count(*) FROM action_events WHERE run_id=:run"
        ), {"run": plan.run_id}) == 1
        assert await session.scalar(text(
            "SELECT count(*) FROM audit_events WHERE action='action.execution.submit' "
            "AND details->>'run_id'=:run"
        ), {"run": str(plan.run_id)}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("negative", ["digest", "build", "v1", "cancelled", "awaiting_approval"])
async def test_execution_boundaries_deny_without_inserting(
    factory: Any, tmp_path: Path, negative: str,
) -> None:
    actions, executor, owner, refs = await setup(factory, tmp_path)
    plan = await actions.create_plan(owner, request(refs, version="1" if negative == "v1" else "2"),
                                     request_id="ab-boundary")
    if negative in {"cancelled", "awaiting_approval"}:
        async with factory() as session, session.begin():
            await session.execute(text("UPDATE action_runs SET state=:state WHERE run_id=:run"),
                                  {"state": negative, "run": plan.run_id})
    if negative == "build":
        actions.build_id = "different-build"
    with pytest.raises(ActionError):
        await executor.submit(owner, plan.plan_id,
                              "a" * 64 if negative == "digest" else plan.plan_digest,
                              request_id="ab-deny")
    async with factory() as session:
        assert await session.scalar(text(
            "SELECT count(*) FROM action_executions WHERE run_id=:run"
        ), {"run": plan.run_id}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["actor", "acl", "source", "cancelled"])
async def test_post_rebind_mutation_cannot_cross_final_execution_fence(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    actions, executor, owner, refs = await setup(factory, tmp_path)
    plan = await actions.create_plan(owner, request(refs), request_id="ab-barrier-plan")
    entered, release = asyncio.Event(), asyncio.Event()
    original = actions._revalidate

    async def revalidated(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        entered.set()
        await release.wait()

    monkeypatch.setattr(actions, "_revalidate", revalidated)
    task = asyncio.create_task(executor.submit(
        owner, plan.plan_id, plan.plan_digest, request_id="ab-barrier-submit"))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        if mutation == "acl":
            await fixtures.deny(factory, refs[0], owner)
        elif mutation == "source":
            await narrower_revision(factory, tmp_path, owner, refs)
        else:
            async with factory() as session, session.begin():
                if mutation == "actor":
                    await session.execute(text(
                        "UPDATE subjects SET security_version=security_version+1 WHERE user_id=:id"
                    ), {"id": uuid.UUID(owner.user_id)})
                else:
                    await session.execute(text(
                        "UPDATE action_runs SET state='cancelled' WHERE run_id=:id"
                    ), {"id": plan.run_id})
    finally:
        release.set()
    with pytest.raises(ActionError):
        await asyncio.wait_for(task, 10)
    async with factory() as session:
        assert await session.scalar(text(
            "SELECT count(*) FROM action_executions WHERE run_id=:run"
        ), {"run": plan.run_id}) == 0


@pytest.mark.asyncio
async def test_post_rebind_capability_revoke_denies_admission_last(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Last: immutable capability revocation is not undone as fixture cleanup.
    actions, executor, owner, refs = await setup(factory, tmp_path)
    plan = await actions.create_plan(owner, request(refs), request_id="ab-revoke-plan")
    original = actions._revalidate

    async def revoke_after_bind(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        async with factory() as session, session.begin():
            await session.execute(text(
                "UPDATE capability_versions SET admission='revoked',revoked_at=now() "
                "WHERE capability_id='sot.read' AND version='2'"
            ))

    monkeypatch.setattr(actions, "_revalidate", revoke_after_bind)
    with pytest.raises(ActionError, match="capability_unavailable"):
        await executor.submit(owner, plan.plan_id, plan.plan_digest, request_id="ab-revoke-submit")
    async with factory() as session:
        assert await session.scalar(text(
            "SELECT count(*) FROM action_executions WHERE run_id=:run"
        ), {"run": plan.run_id}) == 0
