"""R2 pure classification/ownership tests, NOT SQL or native durability proof."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_action_authority_batching_unit import identity

from rtr_copilot.actions import service as service_module
from rtr_copilot.actions.authority import LeafRequest, clock_retry_allowed, parse_leaf_checkpoint
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.service import ActionService
from rtr_copilot.actions.source_metadata import (
    InitialClockDenied,
    UnsupportedSourceTopology,
    _resolve_source_row,
)
from rtr_copilot.auth.models import Subject
from rtr_copilot.context.models import SOTReference
from rtr_copilot.db.uow import UnitOfWork


def source_row() -> tuple[Any, Subject, SOTReference]:
    row = identity()
    actor = row["identity"]["user_id"]
    ref = SOTReference(source_key="synthetic", record_key="HERA_RANGE_KM",
                       record_version_id=uuid.uuid4(), content_sha256="a" * 64)
    resource = str(uuid.uuid4())
    instant = datetime.now(UTC)
    row["leaves"] = [{
        **ref.model_dump(mode="json"), "resource_id": resource, "record_id": resource,
        "version_id": str(ref.record_version_id), "owner_subject_id": actor,
        "current_version_id": str(ref.record_version_id), "actual_checksum": ref.content_sha256,
        "record_lifecycle": "active", "version_lifecycle": "active",
        "package_lifecycle": "active", "verification_state": "verified",
        "fact_state": "verified", "provenance_level": "verified_primary",
        "freshness_state": "current", "effective_from": (instant-timedelta(days=1)).isoformat(),
        "effective_to": None, "freshness_due_at": None, "package_revision": 1,
        "purpose": {"use_class": ["proposal"]}, "action": "view", "evidence_count": 0,
        "evidence_present": True, "deny_tx": True, "deny_current": False,
        "allow_tx": False, "allow_current": False,
        "resource": {"resource_id": resource, "resource_type": "record",
                     "classification": "internal", "source_zone": "sot",
                     "lifecycle_state": "active", "owner_subject_id": actor},
    }]
    actor_subject = Subject(user_id=actor, issuer="synthetic", sub="subject", email="",
                            canonical_domain="", security_version=4)
    return row, actor_subject, ref


def parse(row: Any, actor: Subject, refs: tuple[SOTReference, ...], *, retry: bool) -> Any:
    return _resolve_source_row(row, actor, refs, sorted(set(refs), key=lambda r: r.record_key),
                                "proposal", "RQT-unit", None, clock_retry=retry)


def test_clock_eligibility_does_not_replace_conservative_permission() -> None:
    row, _, _ = source_row()
    resource = uuid.UUID(row["leaves"][0]["resource_id"])
    frame = parse_leaf_checkpoint(row, {(resource, "view"): LeafRequest(resource, "view")},
                                  clock_retry=True)
    assert frame.clock_denials == frozenset({(resource, "view")})
    assert frame.attributes[(resource, "view")][0].explicit_deny is True


@pytest.mark.parametrize("change", ["current_deny", "no_tx_deny", "restricted",
                                    "private", "template", "inactive"])
def test_only_current_policy_permitted_exact_sot_clock_difference_is_eligible(change: str) -> None:
    from rtr_copilot.actions.authority import projection

    row, _, _ = source_row()
    leaf = row["leaves"][0]
    if change == "current_deny":
        leaf["deny_current"] = True
    elif change == "no_tx_deny":
        leaf["deny_tx"] = False
    elif change == "restricted":
        leaf["resource"]["classification"] = "restricted"
    elif change == "private":
        leaf["resource"]["source_zone"] = "private_context"
    elif change == "template":
        leaf["resource"]["resource_type"] = "template_version"
    else:
        leaf["resource"]["lifecycle_state"] = "draft"
    assert not clock_retry_allowed(leaf, projection(row))


def test_default_source_path_retains_denial_not_clock_signal() -> None:
    row, actor, ref = source_row()
    result = parse(row, actor, (ref,), retry=False)
    assert not result.sources and result.gaps[0].code == "unavailable"


def test_borrowed_clock_signal_returns_no_source_or_permission() -> None:
    row, actor, ref = source_row()
    with pytest.raises(InitialClockDenied):
        parse(row, actor, (ref,), retry=True)


@pytest.mark.parametrize("change", ["checksum", "purpose", "evidence", "pointer",
                                    "lifecycle", "verification", "freshness", "duplicate"])
def test_hard_source_error_suppresses_clock_signal(change: str) -> None:
    row, actor, ref = source_row()
    leaf = row["leaves"][0]
    refs = (ref,)
    if change == "checksum":
        leaf["actual_checksum"] = "b" * 64
    elif change == "purpose":
        leaf["purpose"] = {"use_class": ["sales"]}
    elif change == "evidence":
        ref = ref.model_copy(update={"evidence_key": "requested"})
        leaf["evidence_key"] = "requested"
        leaf["evidence_present"] = False
        refs = (ref,)
    elif change == "pointer":
        leaf["current_version_id"] = str(uuid.uuid4())
    elif change == "lifecycle":
        leaf["package_lifecycle"] = "superseded"
    elif change == "verification":
        leaf["verification_state"] = "pending"
    elif change == "freshness":
        leaf["effective_to"] = (datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    else:
        refs = (ref, ref)
    result = parse(row, actor, refs, retry=True)
    assert result.gaps and not result.sources


@pytest.mark.parametrize("change", ["disabled", "version"])
def test_actual_actor_status_and_version_are_hard_not_clock_retry(change: str) -> None:
    from rtr_copilot.context.models import ContextError

    row, actor, ref = source_row()
    if change == "disabled":
        row["identity"]["status"] = "disabled"
        expected = ContextError
    else:
        row["identity"]["security_version"] += 1
        expected = ActionError
    with pytest.raises(expected):
        parse(row, actor, (ref,), retry=True)


@pytest.mark.parametrize("reverse", [False, True])
def test_one_hard_bad_leaf_suppresses_whole_batch_clock_retry(reverse: bool) -> None:
    row, actor, ref = source_row()
    wrong = ref.model_copy(update={"content_sha256": "0" * 64})
    leaf = {**row["leaves"][0], "content_sha256": wrong.content_sha256}
    row["leaves"] = [leaf, row["leaves"][0]] if reverse else [row["leaves"][0], leaf]
    result = parse(row, actor, (wrong, ref) if reverse else (ref, wrong), retry=True)
    assert result.gaps and not result.sources


def proposed(ref: SOTReference, **changes: Any) -> PlanRequest:
    return PlanRequest(idempotency_key="RQT-owner-unit", objective="Synthetic protocol only",
                       source_refs=(ref,), steps=(StepRequest(step_key="read",
                         capability_id="sot.read", capability_version="2",
                         arguments={"record_key": ref.record_key}),), **changes)


class Owner:
    active = 0
    closed = 0

    @asynccontextmanager
    async def __call__(self) -> Any:
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1
            self.closed += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", [InitialClockDenied, UnsupportedSourceTopology])
async def test_initial_owner_closes_discards_then_calls_old_path_once(
    monkeypatch: pytest.MonkeyPatch, signal: Any,
) -> None:
    _, actor, ref = source_row()
    owner = Owner()
    service = ActionService(UnitOfWork(owner))  # type: ignore[arg-type]
    calls = []

    async def current(*args: Any, **kwargs: Any) -> Subject:
        assert owner.active == 1
        return actor

    async def candidate(*args: Any, **kwargs: Any) -> Any:
        raise signal()

    async def preflight(*args: Any, **kwargs: Any) -> None:
        calls.append("hard-preflight")

    async def old(*args: Any, **kwargs: Any) -> Any:
        assert owner.active == 0 and owner.closed == 1
        calls.append("old-once")
        return actor, "opaque-unit-payload"

    monkeypatch.setattr(service.policy, "current", current)
    monkeypatch.setattr(service, "_payload", candidate)
    monkeypatch.setattr(service, "_clock_retry_preflight", preflight)
    monkeypatch.setattr(service, "_legacy_initial_plan", old)
    result = await service._initial_plan(actor, proposed(ref), "RQT-unit-owner")
    assert result == (actor, "opaque-unit-payload", False)
    assert calls.count("old-once") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["arguments_invalid", "contract_changed", "authority_changed",
                                  "subject_unavailable", "budget_limit_invalid"])
async def test_initial_owner_never_catches_hard_action_error(
    monkeypatch: pytest.MonkeyPatch, code: str,
) -> None:
    _, actor, ref = source_row()
    owner = Owner()
    service = ActionService(UnitOfWork(owner))  # type: ignore[arg-type]

    async def current(*args: Any, **kwargs: Any) -> Subject:
        return actor

    async def candidate(*args: Any, **kwargs: Any) -> Any:
        raise ActionError(code)

    async def old(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("hard error cannot route fresh old-path fallback")

    monkeypatch.setattr(service.policy, "current", current)
    monkeypatch.setattr(service, "_payload", candidate)
    monkeypatch.setattr(service, "_legacy_initial_plan", old)
    with pytest.raises(ActionError, match=code):
        await service._initial_plan(actor, proposed(ref), "RQT-hard-owner")
    assert owner.active == 0 and owner.closed == 1


def snapshot_protocol(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Control-order unit only; real lock/rollback proof is a separate SQL gate."""
    _, actor, _ = source_row()
    service = ActionService(UnitOfWork(Owner()))  # type: ignore[arg-type]
    order = []

    class Session:
        async def execute(self, statement: Any) -> None:
            assert str(statement) == "SELECT pg_advisory_xact_lock(827004)"
            order.append("audit")

    session = Session()
    payload = object()

    async def locks(received: Any, bound: Any, actors: Any) -> None:
        assert received is session and bound is payload
        assert actors == (uuid.UUID(actor.user_id),)
        order.append("locks")

    async def fresh(received: Any, current: Any, bound: Any, request_id: str) -> None:
        assert received is session and current is actor and bound is payload
        order.append("fresh")

    monkeypatch.setattr(service_module, "lock_inputs", locks)
    monkeypatch.setattr(service, "_check_locked_snapshot", fresh)
    return service, session, actor, payload, order


@pytest.mark.asyncio
async def test_default_snapshot_still_returns_none_and_has_no_staging_or_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, actor, payload, order = snapshot_protocol(monkeypatch)
    assert await service._snapshot(session, actor, payload, "RQT-default") is None
    assert order == ["locks", "fresh"]


@pytest.mark.asyncio
async def test_private_staging_once_same_session_before_audit_and_fresh_none_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, actor, payload, order = snapshot_protocol(monkeypatch)
    count = 0

    async def stage(received: Any) -> None:
        nonlocal count
        assert received is session
        count += 1
        order.append("stage")

    assert await service._snapshot(session, actor, payload, "RQT-stage", audit_fence=True,
                                   _stage_own_root=stage) is None
    assert count == 1 and order == ["locks", "stage", "audit", "fresh"]


@pytest.mark.asyncio
async def test_private_stage_with_readonly_flag_rejected_before_any_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, actor, payload, order = snapshot_protocol(monkeypatch)

    async def stage(received: Any) -> None:
        pytest.fail("readonly stage must never execute")

    with pytest.raises(ValueError, match="own_root_stage_requires_audit_fence"):
        await service._snapshot(session, actor, payload, "RQT-invalid-stage",
                                _stage_own_root=stage)
    assert order == []


@pytest.mark.asyncio
async def test_stage_failure_never_reaches_audit_or_authority_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, actor, payload, order = snapshot_protocol(monkeypatch)

    async def stage(received: Any) -> None:
        assert received is session
        order.append("failed-stage")
        raise RuntimeError("stage_failed")

    with pytest.raises(RuntimeError, match="stage_failed"):
        await service._snapshot(session, actor, payload, "RQT-failed-stage", audit_fence=True,
                                _stage_own_root=stage)
    assert order == ["locks", "failed-stage"]
