"""Synthetic signed SOT + actual SQL ACL/identity/context/memory operations.

Active ontology rows are test fixtures, not an assertion that a release passed
the separate enterprise activation gate. No successful context service is stubbed.
Fault hooks wrap real checks, mutate only the disposable DB, and return real results.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_tip054_baseline_integration import actor, synthetic_settings

from rtr_copilot.auth.models import Subject
from rtr_copilot.context import api, service, sources
from rtr_copilot.context.models import (
    ContextError,
    MemoryCorrection,
    MemoryCreate,
    MemoryScope,
    PacketRequest,
    SOTReference,
)
from rtr_copilot.context.service import ContextService
from rtr_copilot.rag.ontology import EnterpriseOntology, OntologySpec
from rtr_copilot.sot.models import PackageManifest, PackageRecord, PublishAttestation
from rtr_copilot.sot.package import (
    canonical_json,
    manifest_identity_sha,
    record_content_sha,
    sha256_bytes,
    sign_attestation,
)
from rtr_copilot.sot.service import SOTPublishService

DSN = os.getenv("INTEGRATION_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="dedicated synthetic integration DB required")


@pytest_asyncio.fixture
async def factory() -> Any:
    engine = create_async_engine(
        DSN.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool
    )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def annotate_package(package: Path, annotations: dict[str, dict[str, Any]]) -> None:
    records = [json.loads(line) for line in (package / "records.jsonl").read_text().splitlines()]
    for record in records:
        record.update(annotations.get(record["record_key"], {}))
        record["content_sha256"] = record_content_sha(PackageRecord.model_validate(record))
    (package / "records.jsonl").write_bytes(
        b"".join(canonical_json(row) + b"\n" for row in records)
    )
    manifest = json.loads((package / "manifest.json").read_text())
    payload = [item for item in manifest["members"] if item["path"] != "publish_attestation.json"]
    for item in payload:
        content = (package / item["path"]).read_bytes()
        item.update(byte_size=len(content), sha256=sha256_bytes(content))
    manifest["payload_sha256"] = sha256_bytes(
        canonical_json(
            [
                {"path": item["path"], "sha256": item["sha256"]}
                for item in sorted(payload, key=lambda item: item["path"])
            ]
        )
    )
    attestation = json.loads((package / "publish_attestation.json").read_text())
    attestation.update(
        payload_sha256=manifest["payload_sha256"],
        manifest_sha256=manifest_identity_sha(PackageManifest.model_validate(manifest)),
    )
    attestation["signature"] = sign_attestation(
        PublishAttestation.model_validate(attestation).model_dump(mode="json"),
        SECRET,
    )
    content = canonical_json(attestation)
    (package / "publish_attestation.json").write_bytes(content)
    for item in manifest["members"]:
        if item["path"] == "publish_attestation.json":
            item.update(byte_size=len(content), sha256=sha256_bytes(content))
    (package / "manifest.json").write_bytes(canonical_json(manifest))


async def publish(
    root: Path,
    factory: Any,
    owner: Subject,
    source: str,
    core: str,
    *,
    extra: list[tuple[str, str]] | None = None,
    annotations: dict[str, dict[str, Any]] | None = None,
    revision: int = 1,
) -> tuple[SOTReference, ...]:
    package = build_package(
        root,
        curator_id=UUID(owner.user_id),
        owner_id=UUID(owner.user_id),
        source_key=source,
        record_key=core,
        text="HERA current permitted capability.",
        additional_records=extra,
        revision=revision,
        ordinal=revision,
        supersedes=revision > 1,
    )
    if annotations:
        annotate_package(package, annotations)
    pipeline = SOTPublishService(synthetic_settings(root), factory=factory, clock=lambda: NOW)
    staged = await pipeline.stage(
        package.name, actor_id=UUID(owner.user_id), request_id="ctx-stage"
    )
    result = await pipeline.validate(
        staged.package_id, actor_id=UUID(owner.user_id), request_id="ctx-validate"
    )
    assert result.valid, result
    await pipeline.publish(
        staged.package_id, actor_id=UUID(owner.user_id), request_id="ctx-publish"
    )
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT r.source_key,r.record_key,v.version_id,v.content_sha256
            FROM records r JOIN record_versions v ON v.version_id=r.current_version_id
            WHERE r.source_key=:source ORDER BY r.record_key
        """),
                    {"source": source},
                )
            )
            .mappings()
            .all()
        )
    return tuple(
        SOTReference(
            source_key=row["source_key"],
            record_key=row["record_key"],
            record_version_id=row["version_id"],
            content_sha256=row["content_sha256"],
        )
        for row in rows
    )


async def activate_fixture(
    factory: Any,
    owner: Subject,
    keys: list[str],
    *,
    collision: bool = False,
    second_entity: bool = False,
) -> EnterpriseOntology:
    entities: list[dict[str, Any]] = [
        {
            "entity_id": "synthetic.hera",
            "canonical_name": "HERA",
            "entity_type": "product",
            "domain": "products",
            "aliases": ["hira"],
            "definition_record_keys": [keys[0]],
            "profile_facets": [{"facet_id": "overview", "label": "Overview", "record_keys": keys}],
            "owner": "curator:fixture",
            "provenance_level": "approved_internal",
        }
    ]
    if collision or second_entity:
        entities.append(
            {
                **entities[0],
                "entity_id": "synthetic.vega",
                "canonical_name": "VEGA",
                "aliases": ["hira"] if collision else [],
                "definition_record_keys": [keys[-1]],
                "profile_facets": [],
            }
        )
    spec = OntologySpec.model_validate(
        {
            "schema_version": 1,
            "registry_id": f"ctx.{uuid4().hex}",
            "owner": "fixture",
            "entities": entities,
        }
    )
    ontology = EnterpriseOntology(spec)
    decider = await actor(factory)
    revision, suite, run = uuid4(), uuid4(), uuid4()
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE enterprise_ontology_revisions SET state='superseded' WHERE state='active'")
        )
        await session.execute(
            text("""
            INSERT INTO enterprise_evaluation_suites(suite_id,suite_key,version,suite_digest,
              definition,case_count,domain_count,state,proposed_by,decided_by,
              decision_reason,decided_at)
            VALUES (:suite,:key,1,:digest,'{}',1,1,'approved',:owner,:decider,'fixture',now())
        """),
            {
                "suite": suite,
                "key": spec.registry_id,
                "digest": suite.hex * 2,
                "owner": UUID(owner.user_id),
                "decider": UUID(decider.user_id),
            },
        )
        await session.execute(
            text("""
            INSERT INTO enterprise_ontology_revisions(revision_id,registry_id,version,
              ontology_digest,payload,entity_count,state,proposed_by,decided_by,
              decision_reason,decided_at,activated_by,evaluation_run_id,activated_at)
            VALUES (:revision,:key,1,:digest,CAST(:payload AS jsonb),:count,'active',
              :owner,:decider,'synthetic fixture',now(),:decider,:run,now())
        """),
            {
                "revision": revision,
                "key": spec.registry_id,
                "digest": ontology.digest,
                "payload": spec.model_dump_json(),
                "count": len(entities),
                "owner": UUID(owner.user_id),
                "decider": UUID(decider.user_id),
                "run": run,
            },
        )
        await session.execute(
            text("""
            INSERT INTO enterprise_evaluation_runs(run_id,suite_id,ontology_revision_id,
              ontology_digest,suite_digest,corpus_snapshot_digest,evaluation_subject_digest,
              status,passed_count,failed_count,critical_failed_count,domain_metrics,
              result_payload,result_digest,executed_by,started_at,finished_at)
            VALUES (:run,:suite,:revision,:digest,:suite_digest,:digest,:digest,'passed',
              1,0,0,'{}','{}',:result,:owner,now(),now())
        """),
            {
                "run": run,
                "suite": suite,
                "revision": revision,
                "digest": ontology.digest,
                "suite_digest": suite.hex * 2,
                "result": run.hex * 2,
                "owner": UUID(owner.user_id),
            },
        )
    return ontology


async def deny(factory: Any, owner: Subject, key: str) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO acl_entries(resource_id,principal_type,principal_id,action,effect)
            SELECT record_id,'user',:owner,'view','deny' FROM records WHERE record_key=:key
        """),
            {"owner": UUID(owner.user_id), "key": key},
        )


def note(**changes: Any) -> MemoryCreate:
    return MemoryCreate.model_validate(
        {
            "kind": "preference",
            "text": "Prefer Vietnamese",
            "expires_at": NOW + timedelta(days=20),
            **changes,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["HERA là gì?", "hira tổng quan", "What is HERA?"])
async def test_canonical_context_normal_and_noisy(factory: Any, tmp_path: Path, query: str) -> None:
    owner = await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    refs = await publish(tmp_path, factory, owner, source, core)
    ontology = await activate_fixture(factory, owner, [core])
    packet = await ContextService(factory=factory, clock=lambda: NOW).resolve(
        owner,
        PacketRequest(query=query),
        request_id="ctx-normal",
        persist=True,
    )
    assert packet.entities[0].entity_id == "synthetic.hera"
    assert packet.entities[0].authority == "ontology_projection"
    assert packet.sources[0].reference == refs[0]
    assert packet.ontology_digest == ontology.digest and packet.coverage == "supported"
    async with factory() as session:
        persisted = (
            (
                await session.execute(
                    text("SELECT * FROM context_packets WHERE packet_id=:id"),
                    {"id": packet.packet_id},
                )
            )
            .mappings()
            .one()
        )
    assert "capability" not in json.dumps(dict(persisted), default=str)
    assert query not in json.dumps(dict(persisted), default=str)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["denied", "stale", "purpose", "missing"])
async def test_context_preserves_useful_partial_without_denied_names(
    factory: Any,
    tmp_path: Path,
    fault: str,
) -> None:
    owner = await actor(factory)
    core, second, source = f"CTX.{uuid4().hex}", f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    annotations = (
        {second: {"value": {"use_class": ["sales", "proposal"]}}} if fault == "purpose" else {}
    )
    if fault == "stale":
        annotations[second] = {"freshness_due_at": (NOW + timedelta(hours=1)).isoformat()}
    await publish(
        tmp_path,
        factory,
        owner,
        source,
        core,
        extra=None if fault == "missing" else [(second, "NEVER-DISCLOSE-SECOND")],
        annotations=annotations,
    )
    await activate_fixture(factory, owner, [core, second])
    if fault == "denied":
        await deny(factory, owner, second)
    domain = ContextService(factory=factory, clock=lambda: NOW + timedelta(days=1))
    packet = await domain.resolve(
        owner,
        PacketRequest(query="HERA", use_class="attestation"),
        request_id="ctx-partial",
        persist=True,
    )
    assert len(packet.sources) == 1 and packet.sources[0].reference.record_key == core
    assert packet.coverage == "partial" and packet.gaps
    assert (
        "NEVER-DISCLOSE" not in packet.model_dump_json() and second not in packet.model_dump_json()
    )


@pytest.mark.asyncio
async def test_alias_collision_is_explicit_and_no_backing_is_generic(
    factory: Any, tmp_path: Path
) -> None:
    owner = await actor(factory)
    core, second, source = f"CTX.{uuid4().hex}", f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    await publish(tmp_path, factory, owner, source, core, extra=[(second, "VEGA allowed")])
    await activate_fixture(factory, owner, [core, second], collision=True)
    domain = ContextService(factory=factory, clock=lambda: NOW)
    packet = await domain.resolve(owner, PacketRequest(query="hira"), request_id="ctx-collision")
    assert {entity.entity_id for entity in packet.entities} == {"synthetic.hera", "synthetic.vega"}
    assert "ambiguous" in {gap.code for gap in packet.gaps} and packet.coverage == "partial"
    await deny(factory, owner, core)
    await deny(factory, owner, second)
    hidden = await domain.resolve(owner, PacketRequest(query="hira"), request_id="ctx-denied")
    assert hidden.entities == hidden.sources == hidden.relations == ()
    assert hidden.coverage == "unavailable" and [gap.code for gap in hidden.gaps] == ["unavailable"]
    assert "HERA" not in hidden.model_dump_json() and "VEGA" not in hidden.model_dump_json()
    assert core not in hidden.model_dump_json() and second not in hidden.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["acl", "superseded", "expiry", "subject"])
async def test_packet_and_reference_memory_recheck_live_changes(
    factory: Any,
    tmp_path: Path,
    fault: str,
) -> None:
    owner = await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    refs = await publish(tmp_path, factory, owner, source, core)
    await activate_fixture(factory, owner, [core])
    domain = ContextService(factory=factory, clock=lambda: NOW)
    memory = await domain.create_memory(
        owner,
        note(kind="inference", references=refs, text="SYNTHETIC-INFERENCE"),
        request_id="ctx-note",
    )
    packet = await domain.resolve(
        owner, PacketRequest(query="HERA"), request_id="ctx-create", persist=True
    )
    assert packet.notes and packet.sources
    if fault == "acl":
        await deny(factory, owner, core)
    elif fault == "superseded":
        await publish(tmp_path, factory, owner, source, core, revision=2)
    elif fault == "expiry":
        domain.clock = lambda: NOW + timedelta(days=366)
    else:
        async with factory() as session, session.begin():
            await session.execute(
                text("UPDATE subjects SET status='disabled' WHERE user_id=:id"),
                {"id": UUID(owner.user_id)},
            )
        with pytest.raises(ContextError, match="context_subject_unavailable"):
            await domain.read_packet(owner, packet.packet_id, request_id="ctx-revoked")
        return
    reread = await domain.read_packet(owner, packet.packet_id, request_id="ctx-reuse")
    assert reread.sources == reread.notes == () and reread.coverage == "unavailable"
    assert "SYNTHETIC-INFERENCE" not in reread.model_dump_json()
    checked = await domain.read_memory(owner, memory.memory_id, request_id="ctx-note-reuse")
    assert checked.text is None and checked.references == ()


@pytest.mark.asyncio
async def test_memory_revision_delete_expiry_and_audit_redaction(factory: Any) -> None:
    owner, other = await actor(factory), await actor(factory)
    domain = ContextService(factory=factory, clock=lambda: NOW)
    created = await domain.create_memory(
        owner, note(text="SENSITIVE-NOTE-ONLY"), request_id="ctx-memory"
    )
    with pytest.raises(ContextError, match="memory_unavailable"):
        await domain.read_memory(other, created.memory_id, request_id="ctx-other")
    correction = MemoryCorrection(
        **note(text="CORRECTED-NOTE-ONLY").model_dump(), expected_revision=1
    )
    updated = await domain.correct_memory(
        owner, created.memory_id, correction, request_id="ctx-correct"
    )
    assert updated.revision == 2 and updated.text == "CORRECTED-NOTE-ONLY"
    with pytest.raises(ContextError, match="memory_revision_conflict"):
        await domain.correct_memory(owner, created.memory_id, correction, request_id="ctx-stale")
    deleted = await domain.delete_memory(owner, created.memory_id, 2, request_id="ctx-delete")
    assert deleted.revision == 3 and len(deleted.model_dump()) == 3
    again = await domain.delete_memory(owner, created.memory_id, 3, request_id="ctx-repeat-delete")
    assert again == deleted
    view = await domain.read_memory(owner, created.memory_id, request_id="ctx-deleted")
    assert view.lifecycle == "deleted" and view.text is None and view.references == ()
    second = await domain.create_memory(owner, note(), request_id="ctx-expiring")
    domain.clock = lambda: NOW + timedelta(days=21)
    assert (
        await domain.read_memory(owner, second.memory_id, request_id="ctx-expired")
    ).lifecycle == "expired"
    with pytest.raises(ContextError, match="memory_ttl_invalid"):
        await domain.correct_memory(
            owner,
            second.memory_id,
            MemoryCorrection(
                **note(expires_at=NOW + timedelta(days=40)).model_dump(),
                expected_revision=1,
            ),
            request_id="ctx-ttl",
        )
    async with factory() as session:
        raw = await session.scalar(
            text("SELECT note_text FROM memory_entries WHERE memory_id=:id"),
            {"id": created.memory_id},
        )
        audits = (
            (
                await session.execute(
                    text("SELECT details FROM audit_events WHERE actor_user_id=:id"),
                    {"id": UUID(owner.user_id)},
                )
            )
            .scalars()
            .all()
        )
    assert raw is None
    assert "SENSITIVE-NOTE-ONLY" not in json.dumps(
        audits
    ) and "CORRECTED-NOTE-ONLY" not in json.dumps(audits)


@pytest.mark.asyncio
async def test_team_memory_uses_current_membership_role_and_safe_owner_delete(factory: Any) -> None:
    owner, member, outsider = await actor(factory), await actor(factory), await actor(factory)
    project = uuid4()
    scope = MemoryScope(kind="project", key=project)
    domain = ContextService(factory=factory, clock=lambda: NOW)
    async with factory() as session, session.begin():
        for identity in (owner.user_id, member.user_id):
            await session.execute(
                text("""
                INSERT INTO subject_scopes(subject_id,scope_type,scope_key)
                VALUES (:id,'project',:key)
            """),
                {"id": UUID(identity), "key": str(project)},
            )
    with pytest.raises(ContextError, match="memory_scope_write_denied"):
        await domain.create_memory(owner, note(scope=scope), request_id="ctx-staff-write")
    async with factory() as session, session.begin():
        await session.execute(
            text("""
            INSERT INTO subject_roles(subject_id,role_id)
            SELECT :id,role_id FROM roles WHERE key='leader'
        """),
            {"id": UUID(owner.user_id)},
        )
    shared = await domain.create_memory(
        owner, note(scope=scope, text="TEAM-NOTE"), request_id="ctx-team"
    )
    assert (
        await domain.read_memory(member, shared.memory_id, request_id="ctx-member")
    ).text == "TEAM-NOTE"
    with pytest.raises(ContextError, match="memory_unavailable"):
        await domain.read_memory(outsider, shared.memory_id, request_id="ctx-outsider")
    async with factory() as session, session.begin():
        await session.execute(
            text("DELETE FROM subject_scopes WHERE subject_id=ANY(:ids)"),
            {"ids": [UUID(owner.user_id), UUID(member.user_id)]},
        )
    with pytest.raises(ContextError, match="memory_unavailable"):
        await domain.read_memory(member, shared.memory_id, request_id="ctx-revoked-member")
    with pytest.raises(ContextError, match="context_scope_unavailable"):
        await domain.correct_memory(
            owner,
            shared.memory_id,
            MemoryCorrection(
                **note(scope=scope).model_dump(),
                expected_revision=1,
            ),
            request_id="ctx-revoked-write",
        )
    tombstone = await domain.delete_memory(owner, shared.memory_id, 1, request_id="ctx-safe-delete")
    assert tombstone.model_dump().keys() == {"memory_id", "revision", "lifecycle"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "correct"])
async def test_memory_final_revision_guard_rejects_inflight_old_text(
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    owner = await actor(factory)
    domain = ContextService(factory=factory, clock=lambda: NOW)
    created = await domain.create_memory(
        owner, note(text="OLD-TEXT-MUST-NOT-LEAK"), request_id="ctx-old"
    )
    original, calls = service.revalidate_sot_references, 0

    async def injected(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 2:  # Text was loaded; inject during final source check.
            async with factory() as session, session.begin():
                await session.execute(
                    text("""
                    UPDATE memory_entries SET note_text=:content,lifecycle=:state,
                      revision=revision+1,updated_at=:now WHERE memory_id=:id
                """),
                    {
                        "content": None if mutation == "delete" else "NEW-TEXT",
                        "state": "deleted" if mutation == "delete" else "active",
                        "now": NOW,
                        "id": created.memory_id,
                    },
                )
        return result

    monkeypatch.setattr(service, "revalidate_sot_references", injected)
    result = await domain.read_memory(owner, created.memory_id, request_id="ctx-race")
    assert result.text is None and result.lifecycle == "withheld" and result.references == ()
    assert "OLD-TEXT" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_revoke_between_source_metadata_and_text_never_loads_text(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    refs = await publish(tmp_path, factory, owner, source, core)
    original = sources.ResourceRepository.effective_policy_attributes
    calls, text_queries = 0, []

    async def injected(repository: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        result = await original(repository, *args, **kwargs)
        calls += 1
        if calls == 1:
            await deny(factory, owner, core)
        return result

    monkeypatch.setattr(sources.ResourceRepository, "effective_policy_attributes", injected)
    engine = factory.kw["bind"].sync_engine

    def capture(
        _conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        if "searchable_text" in statement.lower():
            text_queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await sources.revalidate_sot_references(
            owner,
            refs,
            factory=factory,
            request_id="ctx-mid-revoke",
            now=NOW,
            include_text=True,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.sources == () and text_queries == []


@pytest.mark.asyncio
async def test_reference_metadata_mode_never_selects_content(factory: Any, tmp_path: Path) -> None:
    owner = await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    refs = await publish(tmp_path, factory, owner, source, core)
    queries: list[str] = []
    engine = factory.kw["bind"].sync_engine

    def capture(
        _conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
    ) -> None:
        queries.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await sources.revalidate_sot_references(
            owner, refs, factory=factory, request_id="ctx-metadata", now=NOW
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.sources[0].text is None
    assert all("searchable_text" not in query for query in queries)
    assert all("select value_payload " not in query for query in queries)
    assert all("context_relations" not in query for query in queries)


@pytest.mark.asyncio
async def test_relations_require_visible_endpoints_and_exact_evidence(
    factory: Any, tmp_path: Path
) -> None:
    owner = await actor(factory)
    core, second, source = f"CTX.{uuid4().hex}", f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    relation = {
        "subject_entity_id": "synthetic.hera",
        "predicate": "related_to",
        "object_entity_id": "synthetic.vega",
        "evidence_key": f"{core}.e1",
    }
    await publish(
        tmp_path,
        factory,
        owner,
        source,
        core,
        extra=[(second, "VEGA permitted fact")],
        annotations={
            core: {
                "value": {
                    "context_relations": [
                        relation,
                        {**relation, "object_entity_id": "synthetic.denied"},
                        {**relation, "evidence_key": "invented"},
                    ]
                }
            }
        },
    )
    await activate_fixture(factory, owner, [core, second], second_entity=True)
    domain = ContextService(factory=factory, clock=lambda: NOW)
    request = PacketRequest(query="HERA and VEGA", include_memory=False)
    result = await domain.resolve(owner, request, request_id="ctx-relations")
    assert len(result.relations) == 1 and result.relations[0].authority == "source_assertion"
    assert result.relations[0].evidence_key == f"{core}.e1"
    assert "synthetic.denied" not in result.model_dump_json()
    assert "context_relations" not in result.sources[0].model_dump_json()
    await deny(factory, owner, second)
    partial = await domain.resolve(owner, request, request_id="ctx-denied-endpoint")
    assert partial.relations == () and all(
        e.entity_id != "synthetic.vega" for e in partial.entities
    )


@pytest.mark.asyncio
async def test_packet_note_disappears_but_permitted_source_remains(
    factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    await publish(tmp_path, factory, owner, source, core)
    await activate_fixture(factory, owner, [core])
    domain = ContextService(factory=factory, clock=lambda: NOW)
    memory = await domain.create_memory(owner, note(), request_id="ctx-note")
    original, calls = domain.read_memory, 0

    async def injected(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            await domain.delete_memory(owner, memory.memory_id, 1, request_id="ctx-racing-delete")
            raise ContextError("memory_unavailable", 404)
        return await original(*args, **kwargs)

    monkeypatch.setattr(domain, "read_memory", injected)
    result = await domain.resolve(
        owner, PacketRequest(query="HERA"), request_id="ctx-useful-partial"
    )
    assert result.sources and result.notes == () and result.coverage == "partial"
    assert "memory_unavailable" in {gap.code for gap in result.gaps}


@pytest.mark.asyncio
async def test_packet_owner_scope_and_forged_evidence_boundaries(
    factory: Any,
    tmp_path: Path,
) -> None:
    owner, other = await actor(factory), await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    refs = await publish(tmp_path, factory, owner, source, core)
    await activate_fixture(factory, owner, [core])
    domain = ContextService(factory=factory, clock=lambda: NOW)
    packet = await domain.resolve(
        owner, PacketRequest(query="HERA"), request_id="ctx-owner-packet", persist=True
    )
    with pytest.raises(ContextError, match="context_packet_unavailable"):
        await domain.read_packet(other, packet.packet_id, request_id="ctx-other-packet")
    with pytest.raises(ContextError, match="context_scope_unavailable"):
        await domain.resolve(
            owner,
            PacketRequest(
                query="HERA",
                scope=MemoryScope(
                    kind="department",
                    key=uuid4(),
                ),
            ),
            request_id="ctx-unadmitted-scope",
        )
    forged = refs[0].model_copy(update={"evidence_key": "invented-evidence"})
    result = await sources.revalidate_sot_references(
        owner, [forged], factory=factory, request_id="ctx-forged-evidence", now=NOW
    )
    assert result.sources == ()
    with pytest.raises(ContextError, match="memory_sources_unavailable"):
        await domain.create_memory(
            owner, note(kind="inference", references=[forged]), request_id="ctx-forged-inference"
        )


@pytest.mark.asyncio
async def test_purpose_specific_memory_and_complete_wire_budget(
    factory: Any, tmp_path: Path
) -> None:
    owner = await actor(factory)
    core, source = f"CTX.{uuid4().hex}", f"ctx.{uuid4().hex}"
    refs = await publish(tmp_path, factory, owner, source, core)
    await activate_fixture(factory, owner, [core])
    domain = ContextService(factory=factory, clock=lambda: NOW)
    memory = await domain.create_memory(
        owner,
        note(kind="inference", references=refs, text="Ưu tiên dữ liệu hợp lệ 🚁 " * 70),
        request_id="ctx-large-memory",
    )
    withheld = await domain.read_memory(
        owner, memory.memory_id, use_class="attestation", request_id="ctx-purpose-bound-note"
    )
    assert withheld.text is None and withheld.lifecycle == "withheld"
    packet = await domain.resolve(
        owner,
        PacketRequest(query="HERA", max_bytes=2048, max_estimated_tokens=512),
        request_id="ctx-budget-memory",
        persist=True,
    )
    wire = json.dumps(
        packet.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert len(wire) <= 2048 and packet.truncated and packet.coverage == "partial"
    assert "budget_limited" in {gap.code for gap in packet.gaps}


@pytest.mark.asyncio
async def test_authenticated_route_validation_and_maintenance_no_mutations(factory: Any) -> None:
    owner = await actor(factory)
    domain = ContextService(factory=factory, clock=lambda: NOW)
    app = FastAPI()
    app.include_router(api.router)

    @app.middleware("http")
    async def correlation(request: Request, call_next: Any) -> Any:
        request.state.request_id = "ctx-http-synthetic"
        return await call_next(request)

    async def authenticated() -> Subject:
        return owner

    app.dependency_overrides[api.context_service] = lambda: domain
    app.dependency_overrides[api.file_subject] = authenticated
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
        payload = note().model_dump(mode="json")
        rejected = await client.post("/api/v1/context/memory", json={**payload, "authority": "sot"})
        assert rejected.status_code == 422
        created = await client.post("/api/v1/context/memory", json=payload)
        assert created.status_code == 200
        identity = created.json()["memory_id"]
        async with factory() as session, session.begin():
            await session.execute(text("UPDATE maintenance_state SET enabled=true WHERE singleton"))
        try:
            response = await client.get(f"/api/v1/context/memory/{identity}")
            assert response.status_code == 200
            mutations = [
                await client.post("/api/v1/context/memory", json=payload),
                await client.post(
                    "/api/v1/context/packets", json={"query": "unknown synthetic domain"}
                ),
                await client.patch(
                    f"/api/v1/context/memory/{identity}", json={**payload, "expected_revision": 1}
                ),
                await client.delete(f"/api/v1/context/memory/{identity}?expected_revision=1"),
            ]
            assert all(response.status_code == 503 for response in mutations)
            assert all(
                response.json()["error"]["code"] == "maintenance_active" for response in mutations
            )
            async with factory() as session:
                revision = await session.scalar(
                    text("SELECT revision FROM memory_entries WHERE memory_id=:id"),
                    {"id": UUID(identity)},
                )
            assert revision == 1
        finally:
            async with factory() as session, session.begin():
                await session.execute(
                    text("UPDATE maintenance_state SET enabled=false WHERE singleton")
                )
        app.dependency_overrides[api.file_subject] = lambda: None
        denied = await client.get(f"/api/v1/context/memory/{identity}")
        assert denied.status_code == 401 and denied.json()["request_id"] == "ctx-http-synthetic"
