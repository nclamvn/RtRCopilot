"""Independent Action initial-source parity against the unchanged shared resolver.

Actual signed publication, PostgreSQL metadata and PolicyEngine are exercised.
Observational wrappers delegate shared resolution unchanged. This does not
certify final effects, content loading, SDK execution or provider behavior.
"""

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
import test_action_execution_adversarial as adversarial
from sqlalchemy import text

from rtr_copilot.actions import policy as policy_module
from rtr_copilot.actions.models import PlanRequest, StepRequest
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.source_metadata import resolve_action_sources
from rtr_copilot.auth.models import Role
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.context.sources import revalidate_sot_references

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


def requested(refs: Any, purpose: str = "proposal", *, version: str = "2") -> PlanRequest:
    return PlanRequest(
        idempotency_key=f"RQB-source-{uuid.uuid4()}",
        objective="Synthetic metadata parity",
        purpose=purpose,
        source_refs=refs,
        steps=(
            StepRequest(
                step_key="read",
                capability_id="sot.read",
                capability_version=version,
                arguments={"record_key": refs[0].record_key},
            ),
        ),
    )


def resolution_metadata(result: Any) -> dict[str, Any]:
    value = result.model_dump(mode="json")
    # Observation times differ between two real calls; all authority/source
    # fields, gap order, counts and absent text remain compared exactly.
    for source in value["sources"]:
        source.pop("retrieved_at")
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "checksum",
        "version",
        "source",
        "record",
        "evidence_missing",
        "evidence_inactive",
        "old_pointer",
        "purpose",
        "acl",
        "class",
        "resource_lifecycle",
        "zone",
        "department",
        "project",
        "duplicate",
        "mixed_version_identity",
    ],
)
async def test_source_public_policy_result_matches_shared_real_resolver(
    factory: Any, tmp_path: Path, fault: str
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    purpose = "attestation" if fault == "purpose" else "proposal"
    async with factory() as session:
        record = await session.scalar(
            text("SELECT record_id FROM records WHERE source_key=:source"),
            {"source": refs[0].source_key},
        )
        evidence = await session.scalar(
            text("""
            SELECT evidence_key FROM evidence_spans WHERE record_version_id=:version
              AND lifecycle='active' LIMIT 1
        """),
            {"version": refs[0].record_version_id},
        )
    if fault in {"checksum", "version", "source", "record", "evidence_missing"}:
        updates = {
            "checksum": {"content_sha256": "0" * 64},
            "version": {"record_version_id": uuid.uuid4()},
            "source": {"source_key": f"missing.{uuid.uuid4().hex}"},
            "record": {"record_key": f"MISSING.{uuid.uuid4().hex}"},
            "evidence_missing": {"evidence_key": "RQB-invented-key"},
        }
        refs = (refs[0].model_copy(update=updates[fault]),)
    elif fault == "evidence_inactive":
        assert evidence
        refs = (refs[0].model_copy(update={"evidence_key": evidence}),)
        async with factory() as session, session.begin():
            await session.execute(
                text("""
                UPDATE evidence_spans SET lifecycle='superseded'
                WHERE record_version_id=:version AND evidence_key=:key
            """),
                {"version": refs[0].record_version_id, "key": evidence},
            )
    elif fault == "old_pointer":
        await adversarial.narrower_revision(factory, tmp_path, actor, refs)
    elif fault == "acl":
        await fixtures.deny(factory, refs[0], actor)
    elif fault in {"class", "resource_lifecycle", "zone", "department", "project"}:
        column, value = {
            "class": ("classification", "highly_restricted"),
            "resource_lifecycle": ("lifecycle_state", "quarantined"),
            "zone": ("source_zone", "research"),
            "department": ("department_id", uuid.uuid4()),
            "project": ("project_id", uuid.uuid4()),
        }[fault]
        async with factory() as session, session.begin():
            await session.execute(
                text(f"UPDATE resources SET {column}=:value WHERE resource_id=:id"),
                {"value": value, "id": record},
            )
    elif fault == "duplicate":
        refs = (refs[0], refs[0])
    elif fault == "mixed_version_identity":
        _, _, other_refs, _, _ = await adversarial.domain(factory, tmp_path)
        refs = (
            refs[0].model_copy(
                update={
                    "record_version_id": other_refs[0].record_version_id,
                    "content_sha256": other_refs[0].content_sha256,
                }
            ),
        )
    expected = await revalidate_sot_references(
        actor,
        refs,
        factory=factory,
        use_class=purpose,
        request_id="RQB-reference",
        include_text=False,
    )
    direct = await resolve_action_sources(
        actor, refs, factory=factory, use_class=purpose, request_id="RQB-direct-candidate"
    )
    assert resolution_metadata(direct) == resolution_metadata(expected)
    request = requested(refs, purpose)
    if expected.gaps or len(expected.sources) != len(refs):
        with pytest.raises(ActionError, match="source_unavailable"):
            await actions.policy.sources(actor, request, "RQB-candidate")
    else:
        actual = await actions.policy.sources(actor, request, "RQB-candidate")
        assert resolution_metadata(actual) == resolution_metadata(expected)
        assert all(source.text is None for source in actual.sources)
    if fault != "none":
        assert expected.gaps or len(expected.sources) != len(refs)


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["before_effective", "freshness_due"])
async def test_direct_resolver_matches_explicit_existing_temporal_bounds(
    factory: Any, tmp_path: Path, boundary: str
) -> None:
    _, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, expiring=True)
    async with factory() as session:
        dates = (
            await session.execute(
                text("""
            SELECT effective_from,freshness_due_at FROM record_versions WHERE version_id=:id
        """),
                {"id": refs[0].record_version_id},
            )
        ).one()
    instant = (
        dates.effective_from - timedelta(seconds=1)
        if boundary == "before_effective"
        else dates.freshness_due_at
    )
    assert instant is not None
    expected = await revalidate_sot_references(
        actor,
        refs,
        factory=factory,
        use_class="proposal",
        request_id="RQB-time-reference",
        include_text=False,
        now=instant,
    )
    direct = await resolve_action_sources(
        actor,
        refs,
        factory=factory,
        use_class="proposal",
        request_id="RQB-time-candidate",
        now=instant,
    )
    assert resolution_metadata(direct) == resolution_metadata(expected)
    assert [gap.code for gap in direct.gaps] == ["stale"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_first", [False, True])
async def test_distinct_checksums_do_not_collide_in_direct_reference_identity_or_wrapper_count(
    factory: Any, tmp_path: Path, bad_first: bool
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    valid = refs[0]
    invalid = valid.model_copy(update={"content_sha256": "0" * 64})
    mixed = (invalid, valid) if bad_first else (valid, invalid)
    expected = await revalidate_sot_references(
        actor,
        mixed,
        factory=factory,
        use_class="proposal",
        request_id="RQB-collision-reference",
        include_text=False,
    )
    actual = await resolve_action_sources(
        actor, mixed, factory=factory, use_class="proposal", request_id="RQB-collision-candidate"
    )
    assert resolution_metadata(actual) == resolution_metadata(expected)
    assert len(actual.sources) == 1 and actual.sources[0].reference == valid
    assert [gap.code for gap in actual.gaps] == ["unavailable"]
    with pytest.raises(ActionError, match="source_unavailable"):
        await actions.policy.sources(actor, requested(mixed), "RQB-collision-wrapper")


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1", "2"])
async def test_source_record_owner_is_not_resource_security_owner(
    factory: Any, tmp_path: Path, version: str
) -> None:
    actions, owner, refs, _, _ = await adversarial.domain(factory, tmp_path)
    security_owner = await fixtures.principal(factory, Role.CURATOR)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            UPDATE resources SET owner_subject_id=:security_owner WHERE resource_id IN
              (SELECT record_id FROM records WHERE source_key=:source)
        """),
            {"security_owner": uuid.UUID(security_owner.user_id), "source": refs[0].source_key},
        )
    expected = await revalidate_sot_references(
        owner, refs, factory=factory, request_id="RQB-owner-reference", include_text=False
    )
    actual = await actions.policy.sources(
        owner, requested(refs, version=version), "RQB-owner-actual"
    )
    assert resolution_metadata(actual) == resolution_metadata(expected)
    assert actual.sources[0].owner_subject_id == uuid.UUID(owner.user_id)
    assert actual.sources[0].owner_subject_id != uuid.UUID(security_owner.user_id)


@pytest.mark.asyncio
async def test_distinct_calls_and_actors_refresh_authority_and_acl(
    factory: Any, tmp_path: Path
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    other = await fixtures.principal(factory)
    request = requested(refs)
    assert (await actions.policy.sources(actor, request, "RQB-first")).sources
    with pytest.raises(ActionError, match="source_unavailable"):
        await actions.policy.sources(other, request, "RQB-other")
    await fixtures.deny(factory, refs[0], actor)
    with pytest.raises(ActionError, match="source_unavailable"):
        await actions.policy.sources(actor, request, "RQB-after-deny")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["role_expired", "disabled", "security_version"])
async def test_new_source_call_does_not_reuse_the_old_subject_projection(
    factory: Any, tmp_path: Path, mutation: str
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path, restricted=True)
    request = requested(refs)
    first = await actions.policy.sources(actor, request, "RQB-source-before-authority")
    async with factory() as session, session.begin():
        params = {"actor": uuid.UUID(actor.user_id)}
        if mutation == "role_expired":
            await session.execute(
                text(
                    "UPDATE subject_roles SET expires_at=now()-interval '1 second' "
                    "WHERE subject_id=:actor"
                ),
                params,
            )
        elif mutation == "disabled":
            await session.execute(
                text(
                    "UPDATE subjects SET status='disabled',"
                    "security_version=security_version+1 WHERE user_id=:actor"
                ),
                params,
            )
        else:
            await session.execute(
                text(
                    "UPDATE subjects SET security_version=security_version+1 WHERE user_id=:actor"
                ),
                params,
            )
    if mutation == "security_version":
        latest = await actions.policy.sources(actor, request, "RQB-source-new-version")
        assert latest.subject.security_version == first.subject.security_version + 1
    else:
        with pytest.raises(ActionError):
            await actions.policy.sources(actor, request, "RQB-source-no-old-authority")


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow", [False, True])
async def test_requested_evidence_limit_overflow_discards_whole_batch_to_fresh_shared_call(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overflow: bool
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    async with factory() as session, session.begin():
        original = (
            await session.execute(
                text("""
            SELECT evidence_key,span_id FROM evidence_spans
            WHERE record_version_id=:version AND lifecycle='active' LIMIT 1
        """),
                {"version": refs[0].record_version_id},
            )
        ).one()
        await session.execute(
            text("""
            INSERT INTO evidence_spans(evidence_key,record_version_id,package_id,source_ref,
              locator,quoted_text,normalized_text,evidence_sha256,source_label,
              classification,lifecycle)
            SELECT :prefix || n::text,e.record_version_id,e.package_id,e.source_ref,e.locator,
              e.quoted_text,e.normalized_text,e.evidence_sha256,e.source_label,
              e.classification,'active'
            FROM evidence_spans e CROSS JOIN generate_series(1,:count) n WHERE e.span_id=:id
        """),
            {
                "prefix": f"RQB-overflow-{uuid.uuid4()}-",
                "count": 1001 if overflow else 999,
                "id": original.span_id,
            },
        )
    refs = (refs[0].model_copy(update={"evidence_key": original.evidence_key}),)
    expected = await revalidate_sot_references(
        actor, refs, factory=factory, request_id="RQB-limit-reference", include_text=False
    )
    shared_calls = 0
    decisions_before_fallback = 0
    fallback_started = False
    real_shared = policy_module.revalidate_sot_references
    real_decide = PolicyEngine.decide

    async def observed_shared(*args: Any, **kwargs: Any) -> Any:
        nonlocal shared_calls, fallback_started
        shared_calls += 1
        fallback_started = True
        return await real_shared(*args, **kwargs)

    def observed_decide(*args: Any, **kwargs: Any) -> Any:
        nonlocal decisions_before_fallback
        if not fallback_started:
            decisions_before_fallback += 1
        return real_decide(*args, **kwargs)

    monkeypatch.setattr(policy_module, "revalidate_sot_references", observed_shared)
    monkeypatch.setattr(PolicyEngine, "decide", observed_decide)
    if expected.gaps:
        with pytest.raises(ActionError, match="source_unavailable"):
            await actions.policy.sources(actor, requested(refs), "RQB-limit-candidate")
    else:
        actual = await actions.policy.sources(actor, requested(refs), "RQB-limit-candidate")
        assert resolution_metadata(actual) == resolution_metadata(expected)
    assert shared_calls == int(overflow)
    if overflow:
        assert decisions_before_fallback == 0


@pytest.mark.asyncio
async def test_nonleaf_candidate_discards_batch_before_fresh_repository_fallback(
    factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions, actor, refs, _, _ = await adversarial.domain(factory, tmp_path)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            UPDATE resources SET resource_type='document' WHERE resource_id IN
              (SELECT record_id FROM records WHERE source_key=:source)
        """),
            {"source": refs[0].source_key},
        )
    expected = await revalidate_sot_references(
        actor, refs, factory=factory, request_id="RQB-topology-reference", include_text=False
    )
    shared_calls = 0
    decisions_before_fallback = 0
    fallback_started = False
    real_shared = policy_module.revalidate_sot_references
    real_decide = PolicyEngine.decide

    async def observed_shared(*args: Any, **kwargs: Any) -> Any:
        nonlocal shared_calls, fallback_started
        shared_calls += 1
        fallback_started = True
        return await real_shared(*args, **kwargs)

    def observed_decide(*args: Any, **kwargs: Any) -> Any:
        nonlocal decisions_before_fallback
        if not fallback_started:
            decisions_before_fallback += 1
        return real_decide(*args, **kwargs)

    monkeypatch.setattr(policy_module, "revalidate_sot_references", observed_shared)
    monkeypatch.setattr(PolicyEngine, "decide", observed_decide)
    assert expected.gaps
    with pytest.raises(ActionError, match="source_unavailable"):
        await actions.policy.sources(actor, requested(refs), "RQB-topology-candidate")
    assert shared_calls == 1
    assert decisions_before_fallback == 0
