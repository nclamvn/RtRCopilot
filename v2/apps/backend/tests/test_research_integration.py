import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from research_fixtures import (
    build_research_package,
    research_record_row,
    research_record_sha_raw,
)
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.governance.models import ResearchSource
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.models import SearchFilters
from rtr_copilot.rag.reindex import ReindexService
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.repositories.governance import GovernanceError, GovernanceRepository
from rtr_copilot.research.models import CandidateClaim, GraduationProposalInput
from rtr_copilot.research.service import ResearchService
from rtr_copilot.sot.package import PackageParser
from rtr_copilot.sot.service import PublishError, SOTPublishService

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    research_root = tmp_path / "research-staging"
    sot_root = tmp_path / "sot-staging"
    research_root.mkdir()
    sot_root.mkdir()
    return research_root, sot_root


def research_settings(roots: tuple[Path, Path]) -> Any:
    return get_settings().model_copy(update={
        "research_staging_root": roots[0],
        "sot_staging_root": roots[1],
        "sot_signing_secret": SecretStr(SECRET),
        "rag_provider_mode": "local",
    })


@pytest.fixture
def service(
    roots: tuple[Path, Path],
    factory: async_sessionmaker[Any],
) -> ResearchService:
    return ResearchService(research_settings(roots), factory=factory)


def subject(role: Role, user_id: uuid.UUID) -> Subject:
    return Subject(
        user_id=str(user_id),
        issuer="research-integration",
        sub=user_id.hex,
        email=f"{user_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


async def insert_actor(
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
) -> None:
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,'research-integration',:sub,:email,'rtrobotics.com')
        """), {
            "id": actor_id,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
        })


async def create_source(
    factory: async_sessionmaker[Any],
    owner_id: uuid.UUID,
    *,
    classification: str = "internal",
    lifecycle: str = "active",
) -> ResearchSource:
    source = ResearchSource(
        stable_key=f"refinery.{uuid.uuid4().hex}",
        display_name="Synthetic refinery corpus",
        origin="refinery",
        owner_subject_id=owner_id,
        classification=classification,  # type: ignore[arg-type]
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )
    async with factory() as session, session.begin():
        await GovernanceRepository().create_source(session, source)
    return source


async def record_rows(
    factory: async_sessionmaker[Any],
    package_id: uuid.UUID,
) -> int:
    async with factory() as session:
        count = await session.scalar(text("""
            SELECT count(*) FROM research_records WHERE package_id=:package_id
        """), {"package_id": package_id})
    return int(count or 0)


async def audit_rows(
    factory: async_sessionmaker[Any],
    key: str,
    value: str,
) -> list[tuple[str, str, str]]:
    async with factory() as session:
        rows = (await session.execute(text(f"""
            SELECT action, result, reason_code FROM audit_events
            WHERE details->>'{key}'=:value ORDER BY sequence
        """), {"value": value})).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def import_ok(
    service: ResearchService,
    factory: async_sessionmaker[Any],
    curator_id: uuid.UUID,
    source: ResearchSource,
    *,
    records: list[dict[str, Any]],
    request_id: str = "import",
) -> Any:
    staging = build_research_package(
        Path(service.settings.research_staging_root),
        source_key=source.stable_key,
        records=records,
    )
    return await service.import_package(
        subject(Role.CURATOR, curator_id),
        staging,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_import_is_atomic_idempotent_and_audited(
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    curator_id = uuid.uuid4()
    await insert_actor(factory, curator_id)
    source = await create_source(factory, curator_id)
    rows = [
        research_record_row(tier="P", text="alpha claim"),
        research_record_row(tier="S", text="beta claim"),
    ]
    rows[0]["corroboration_state"] = "corroborated"
    rows[0]["content_sha256"] = research_record_sha_raw(rows[0])
    result = await service.import_package(
        subject(Role.CURATOR, curator_id),
        build_research_package(
            Path(service.settings.research_staging_root),
            source_key=source.stable_key,
            records=rows,
        ),
        request_id="import-1",
    )
    assert result.created
    assert not result.idempotent
    package = result.package
    assert package.zone_label == "research"
    assert package.import_state == "imported"
    assert package.record_count == 2
    assert package.tier_composition == {"P": 1, "S": 1}
    assert await record_rows(factory, package.package_id) == 2
    async with factory() as session:
        persisted = (await session.execute(text("""
            SELECT zone_label,corroboration_state FROM research_records
            WHERE package_id=:package_id
            ORDER BY searchable_text
        """), {"package_id": package.package_id})).mappings().all()
    assert {row["zone_label"] for row in persisted} == {"research"}
    assert {row["corroboration_state"] for row in persisted} == {
        "corroborated", "uncorroborated",
    }
    audits = await audit_rows(factory, "package_id", str(package.package_id))
    assert ("research.package.import", "success", "package_imported") in audits
    # Same content in a differently named staging unit: identical fingerprint.
    again = await service.import_package(
        subject(Role.CURATOR, curator_id),
        build_research_package(
            Path(service.settings.research_staging_root),
            source_key=source.stable_key,
            records=rows,
        ),
        request_id="import-2",
    )
    assert not again.created
    assert again.idempotent
    assert again.package.package_id == package.package_id
    assert await record_rows(factory, package.package_id) == 2
    audits = await audit_rows(factory, "package_id", str(package.package_id))
    assert ("research.package.import", "success", "idempotent_reimport") in audits
    # The archive upload path imports through the same quarantine contract.
    zipped = await service.import_package(
        subject(Role.CURATOR, curator_id),
        build_research_package(
            Path(service.settings.research_staging_root),
            source_key=source.stable_key,
            records=[research_record_row(tier="X", text="zipped rumor claim")],
            as_zip=True,
        ),
        request_id="import-3",
    )
    assert zipped.created
    assert zipped.package.import_state == "imported"
    assert zipped.package.tier_composition == {"X": 1}


@pytest.mark.asyncio
async def test_contract_violations_reject_the_whole_package_fail_closed(
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    curator_id, staff_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, curator_id)
    await insert_actor(factory, staff_id)
    curator = subject(Role.CURATOR, curator_id)
    source = await create_source(factory, curator_id)
    root = Path(service.settings.research_staging_root)

    forged = research_record_row(text="tampered claim")
    forged["evidence"][0]["checksum"] = "f" * 64
    innocent = research_record_row()
    staging = build_research_package(
        root,
        source_key=source.stable_key,
        records=[innocent, forged],
    )
    with pytest.raises(GovernanceError, match="evidence_checksum_mismatch"):
        await service.import_package(curator, staging, request_id="reject-1")
    async with factory() as session:
        row = (await session.execute(text("""
            SELECT package_id, import_state, rejection_code
            FROM research_packages p JOIN research_sources s USING (source_id)
            WHERE s.stable_key=:key
        """), {"key": source.stable_key})).mappings().one()
    assert row["import_state"] == "rejected"
    assert row["rejection_code"] == "evidence_checksum_mismatch"
    assert await record_rows(factory, row["package_id"]) == 0
    audits = await audit_rows(factory, "package_id", str(row["package_id"]))
    assert (
        "research.package.import",
        "deny",
        "evidence_checksum_mismatch",
    ) in audits
    # Identical re-import of a rejected fingerprint yields the same result.
    replay = build_research_package(
        root,
        source_key=source.stable_key,
        records=[innocent, forged],
    )
    with pytest.raises(GovernanceError, match="evidence_checksum_mismatch"):
        await service.import_package(curator, replay, request_id="reject-2")
    assert await record_rows(factory, row["package_id"]) == 0

    # Manifest-level violation: identity untrusted, no registry row appears.
    bad_identity = build_research_package(
        root,
        source_key=source.stable_key,
        fingerprint="a" * 64,
    )
    with pytest.raises(GovernanceError, match="fingerprint_mismatch"):
        await service.import_package(curator, bad_identity, request_id="reject-3")
    async with factory() as session:
        ghost = await GovernanceRepository().get_package_by_fingerprint(
            session,
            "a" * 64,
        )
    assert ghost is None

    with pytest.raises(PermissionError, match="curator_required"):
        await service.import_package(
            subject(Role.STAFF, staff_id),
            build_research_package(root, source_key=source.stable_key),
            request_id="reject-4",
        )
    with pytest.raises(GovernanceError, match="research_source_unknown"):
        await service.import_package(
            curator,
            build_research_package(root, source_key="refinery.unregistered"),
            request_id="reject-5",
        )
    suspended = await create_source(factory, curator_id, lifecycle="suspended")
    with pytest.raises(GovernanceError, match="research_source_inactive"):
        await service.import_package(
            curator,
            build_research_package(root, source_key=suspended.stable_key),
            request_id="reject-6",
        )

    # Cross-package record-version collision rejects atomically at insert time.
    shared_key = f"IND.{uuid.uuid4().hex[:12].upper()}"
    sibling_key = f"IND.{uuid.uuid4().hex[:12].upper()}"
    await import_ok(
        service, factory, curator_id, source,
        records=[research_record_row(record_key=shared_key, text="first import")],
        request_id="conflict-1",
    )
    colliding = build_research_package(
        root,
        source_key=source.stable_key,
        records=[
            research_record_row(record_key=shared_key, text="colliding rewrite"),
            research_record_row(record_key=sibling_key, text="innocent sibling"),
        ],
    )
    with pytest.raises(GovernanceError, match="record_version_conflict"):
        await service.import_package(curator, colliding, request_id="conflict-2")
    async with factory() as session:
        survivors = (await session.execute(text("""
            SELECT searchable_text FROM research_records
            WHERE record_key IN (:a, :b)
        """), {"a": shared_key, "b": sibling_key})).scalars().all()
    assert list(survivors) == ["first import"]


@pytest.mark.asyncio
async def test_visibility_scoping_and_leak_probes(
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    curator_id, owner_id, stranger_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for actor_id in (curator_id, owner_id, stranger_id):
        await insert_actor(factory, actor_id)
    curator = subject(Role.CURATOR, curator_id)
    stranger = subject(Role.STAFF, stranger_id)
    owner = subject(Role.STAFF, owner_id)
    restricted = await create_source(
        factory,
        owner_id,
        classification="restricted",
    )
    result = await import_ok(
        service, factory, curator_id, restricted,
        records=[research_record_row()],
    )
    package_id = result.package.package_id
    # Curator clearance covers restricted; the staff owner's does not.
    curator_page = await service.list_packages(curator, request_id="vis-1")
    assert package_id in {item.package_id for item in curator_page.items}
    owner_page = await service.list_packages(owner, request_id="vis-2")
    assert owner_page.items == []
    stranger_page = await service.list_packages(stranger, request_id="vis-3")
    assert stranger_page.items == []
    with pytest.raises(GovernanceError, match="research_package_not_found"):
        await service.package_detail(stranger, package_id, request_id="vis-4")
    with pytest.raises(GovernanceError, match="research_package_not_found"):
        await service.list_records(stranger, package_id, request_id="vis-5")
    records = await service.list_records(curator, package_id, request_id="vis-6")
    assert all(item.zone_label == "research" for item in records.items)
    record_id = records.items[0].research_record_id
    with pytest.raises(GovernanceError, match="research_record_not_found"):
        await service.record_detail(stranger, record_id, request_id="vis-7")
    detail = await service.record_detail(curator, record_id, request_id="vis-8")
    assert detail.zone_label == "research"
    assert detail.tier == "P"
    disclosure = await audit_rows(factory, "research_record_id", str(record_id))
    assert ("research.record.view", "success", "record_disclosed") in disclosure

    # Beyond curator clearance: highly restricted sources stay invisible.
    classified = await create_source(
        factory,
        owner_id,
        classification="highly_restricted",
    )
    with pytest.raises(GovernanceError, match="research_source_unknown"):
        await service.import_package(
            curator,
            build_research_package(
                Path(service.settings.research_staging_root),
                source_key=classified.stable_key,
            ),
            request_id="vis-9",
        )

    # Cursor pagination walks without duplicates under policy filtering.
    open_source = await create_source(factory, curator_id)
    for index in range(3):
        await import_ok(
            service, factory, curator_id, open_source,
            records=[research_record_row(text=f"pagination claim {index}")],
            request_id=f"vis-page-{index}",
        )
    seen: list[uuid.UUID] = []
    cursor: str | None = None
    for _ in range(6):
        page = await service.list_packages(
            curator,
            request_id="vis-10",
            source_key=open_source.stable_key,
            cursor=cursor,
            limit=1,
        )
        seen.extend(item.package_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == 3
    assert len(set(seen)) == 3


@pytest.mark.asyncio
async def test_research_search_is_scoped_labeled_and_dlp_guarded(
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    curator_id, stranger_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, curator_id)
    await insert_actor(factory, stranger_id)
    curator = subject(Role.CURATOR, curator_id)
    source = await create_source(factory, curator_id)
    token = f"quantumforge{uuid.uuid4().hex[:8]}"
    primary_key = f"IND.{uuid.uuid4().hex[:12].upper()}.P"
    hypothesis_key = f"IND.{uuid.uuid4().hex[:12].upper()}.H"
    leaky_key = f"IND.{uuid.uuid4().hex[:12].upper()}.DLP"
    result = await import_ok(
        service, factory, curator_id, source,
        records=[
            research_record_row(
                record_key=primary_key,
                tier="P",
                text=f"{token} produces verified industry telemetry",
            ),
            research_record_row(
                record_key=hypothesis_key,
                tier="H",
                text=f"{token} might expand into maritime robotics",
            ),
            research_record_row(
                record_key=leaky_key,
                tier="S",
                text=f"{token} leaked credentials password: hunter2secret",
            ),
        ],
    )
    search_request_id = f"search-{uuid.uuid4().hex}"
    response = await service.search(curator, token, request_id=search_request_id)
    assert response.zone_label == "research"
    assert response.grounding == "research_supported"
    keys = {hit.record_key for hit in response.results}
    assert keys == {primary_key, hypothesis_key}
    for hit in response.results:
        assert hit.zone_label == "research"
        assert hit.citation.zone_label == "research"
        assert hit.citation.package_fingerprint == result.package.fingerprint
        assert hit.citation.source_key == source.stable_key
        assert hit.citation.evidence_checksums
        assert "hunter2secret" not in hit.snippet
    tiered = await service.search(
        curator,
        token,
        request_id="search-2",
        tiers=["H"],
    )
    assert {hit.record_key for hit in tiered.results} == {hypothesis_key}
    assert all(hit.tier == "H" for hit in tiered.results)
    stranger_view = await service.search(
        subject(Role.STAFF, stranger_id),
        token,
        request_id="search-3",
    )
    assert stranger_view.results == []
    async with factory() as session:
        searched = (await session.execute(text("""
            SELECT reason_code FROM audit_events WHERE action='research.search'
              AND request_id=:request_id
        """), {"request_id": search_request_id})).scalars().all()
    assert list(searched) == ["research_scope_results"]


@pytest.mark.asyncio
async def test_masquerade_probes_research_never_appears_as_sot(
    roots: tuple[Path, Path],
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    curator_id = uuid.uuid4()
    await insert_actor(factory, curator_id)
    curator = subject(Role.CURATOR, curator_id)
    settings = research_settings(roots)
    shared_token = f"orbitalanchor{uuid.uuid4().hex[:8]}"
    research_token = f"refineryghost{uuid.uuid4().hex[:8]}"
    source_key = f"masq.{uuid.uuid4().hex}"
    record_key = f"MASQ.{uuid.uuid4().hex}"
    # Real SOT content through the publish + reindex pipeline.
    package_root = build_package(
        roots[1],
        curator_id=curator_id,
        owner_id=curator_id,
        source_key=source_key,
        record_key=record_key,
        text=f"{shared_token} anchors the approved company deployment.",
    )
    sot = SOTPublishService(settings, factory=factory, clock=lambda: NOW)
    staged = await sot.stage(package_root.name, actor_id=curator_id, request_id="m-1")
    assert (await sot.validate(
        staged.package_id, actor_id=curator_id, request_id="m-2",
    )).valid
    published = await sot.publish(
        staged.package_id, actor_id=curator_id, request_id="m-3",
    )
    async with factory() as session:
        outbox_id = await session.scalar(text("""
            SELECT outbox_id FROM sot_reindex_outbox WHERE run_id=:run_id
        """), {"run_id": published.run_id})
    await ReindexService(settings, factory=factory).process(outbox_id)
    # Research content that adversarially matches the same query terms.
    research_source = await create_source(factory, curator_id)
    await import_ok(
        service, factory, curator_id, research_source,
        records=[research_record_row(
            record_key=f"IND.{uuid.uuid4().hex[:12].upper()}.MASQ",
            tier="X",
            text=(
                f"{shared_token} {research_token} unverified rumor "
                "masquerading as company fact"
            ),
        )],
        request_id="m-4",
    )
    retrieval = RetrievalService(settings, factory=factory)
    # AC-08: the genuine SOT chunk is retrievable in the SOT scope.
    scoped_hits = await retrieval.search(
        curator,
        shared_token,
        filters=SearchFilters(source_key=source_key),
        request_id="m-5",
    )
    assert scoped_hits, "the genuine SOT chunk must be retrievable"
    assert {hit.citation.source_key for hit in scoped_hits} == {source_key}
    # Adversarial: SOT-scoped searches — filtered or not — return ZERO
    # research chunks even though a research record matches every term.
    async with factory() as session:
        for probe_id, query in (("m-6", shared_token), ("m-7", research_token)):
            hits = await retrieval.search(
                curator,
                query,
                filters=SearchFilters(),
                request_id=probe_id,
            )
            for hit in hits:
                assert research_token not in hit.snippet
                assert "masquerading" not in hit.snippet
                version_exists = await session.scalar(text("""
                    SELECT EXISTS(SELECT 1 FROM record_versions
                      WHERE version_id=:version_id)
                """), {"version_id": hit.citation.record_version_id})
                assert version_exists, "every citation resolves to record_versions"
                in_research = await session.scalar(text("""
                    SELECT EXISTS(SELECT 1 FROM research_records
                      WHERE research_record_id=:chunk_id
                      OR content_sha256=:record_checksum
                    )
                """), {
                    "chunk_id": hit.chunk_id,
                    "record_checksum": hit.citation.record_checksum,
                })
                assert not in_research, "no SOT hit may identify research content"
    # The SOT index namespace contains no research content at all.
    async with factory() as session:
        leaked = await session.scalar(text("""
            SELECT count(*) FROM chunks WHERE display_text ILIKE :needle
        """), {"needle": f"%{research_token}%"})
        assert int(leaked or 0) == 0
        non_sot = await session.scalar(text("""
            SELECT count(*) FROM chunks WHERE source_zone <> 'sot'
        """))
        assert int(non_sot or 0) == 0
    # The namespace physically rejects a forged research zone label.
    with pytest.raises(DBAPIError) as forged:
        async with factory() as session, session.begin():
            await session.execute(text("""
                UPDATE chunks SET source_zone='research'
                WHERE chunk_key IN (
                  SELECT chunk_key FROM chunks LIMIT 1
                )
            """))
    assert "source_zone" in str(forged.value)
    # Prompt-assembly path: asking about research-only knowledge never
    # grounds on research content — citations resolve to SOT or not at all.
    answer = await AnswerService(
        settings,
        factory=factory,
        provider=OfflineExtractiveAnswer(),
    ).ask(
        curator,
        research_token,
        filters=SearchFilters(),
        require_verified=False,
        conversation_id=None,
        request_id=f"m-ask-{uuid.uuid4().hex[:8]}",
    )
    assert research_token not in answer.answer
    async with factory() as session:
        for citation in answer.citations:
            resolves = await session.scalar(text("""
                SELECT EXISTS(SELECT 1 FROM record_versions
                  WHERE version_id=:version_id)
            """), {"version_id": citation.record_version_id})
            assert resolves, "answer citations must resolve to SOT versions"
    # Research-scoped search returns only zone-labeled research results.
    research_view = await service.search(curator, shared_token, request_id="m-8")
    assert research_view.results
    async with factory() as session:
        for hit in research_view.results:
            assert hit.zone_label == "research"
            in_research = await session.scalar(text("""
                SELECT EXISTS(SELECT 1 FROM research_records
                  WHERE research_record_id=:record_id)
            """), {"record_id": hit.research_record_id})
            assert in_research
    assert {hit.citation.source_key for hit in research_view.results} == {
        research_source.stable_key,
    }


async def graduation_fixture(
    service: ResearchService,
    factory: async_sessionmaker[Any],
    *,
    classification: str = "internal",
) -> tuple[uuid.UUID, uuid.UUID, ResearchSource, list[uuid.UUID]]:
    proposer_id, decider_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, proposer_id)
    await insert_actor(factory, decider_id)
    source = await create_source(
        factory,
        proposer_id,
        classification=classification,
    )
    result = await import_ok(
        service, factory, proposer_id, source,
        records=[
            research_record_row(text="industry deploys beacon relays"),
            research_record_row(text="operators corroborate beacon relays"),
        ],
        request_id="grad-import",
    )
    async with factory() as session:
        record_ids = (await session.execute(text("""
            SELECT research_record_id FROM research_records
            WHERE package_id=:package_id ORDER BY record_key
        """), {"package_id": result.package.package_id})).scalars().all()
    return proposer_id, decider_id, source, list(record_ids)


def claim(classification: str = "internal") -> CandidateClaim:
    return CandidateClaim(
        claim_text="Company operates beacon relay deployments",
        value={"category": "capability"},
        classification=classification,  # type: ignore[arg-type]
    )


def proposal_input(
    record_ids: list[uuid.UUID],
    *,
    target: str,
    classification: str = "internal",
    supersedes: uuid.UUID | None = None,
) -> GraduationProposalInput:
    return GraduationProposalInput(
        research_record_ids=record_ids,
        claim=claim(classification),
        target_record_key=target,
        rationale="verbatim evidence supports the claim",
        supersedes_proposal_id=supersedes,
    )


@pytest.mark.asyncio
async def test_graduation_gate_separation_of_duties_and_no_auto_activation(
    roots: tuple[Path, Path],
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    proposer_id, decider_id, _, record_ids = await graduation_fixture(
        service,
        factory,
    )
    staff_id = uuid.uuid4()
    await insert_actor(factory, staff_id)
    proposer = subject(Role.CURATOR, proposer_id)
    decider = subject(Role.CURATOR, decider_id)
    target = f"company.claims.{uuid.uuid4().hex[:8]}"

    with pytest.raises(PermissionError, match="curator_required"):
        await service.propose(
            subject(Role.STAFF, staff_id),
            proposal_input(record_ids, target=target),
            request_id="g-1",
        )
    with pytest.raises(GovernanceError, match="research_record_not_graduatable"):
        await service.propose(
            proposer,
            proposal_input([uuid.uuid4()], target=target),
            request_id="g-2",
        )
    first = await service.propose(
        proposer,
        proposal_input(record_ids, target=target),
        request_id="g-3",
    )
    assert first.state == "proposed"
    # Strangers can neither see nor decide the proposal.
    with pytest.raises(GovernanceError, match="proposal_not_found"):
        await service.proposal_detail(
            subject(Role.STAFF, staff_id),
            first.proposal_id,
            request_id="g-4",
        )
    with pytest.raises(GovernanceError, match="proposal_not_found"):
        await service.decide(
            subject(Role.STAFF, staff_id),
            first.proposal_id,
            decision="approved",
            reason="stranger approval probe",
            request_id="g-5",
        )
    # Separation of duties: the proposer can never decide.
    with pytest.raises(GovernanceError, match="proposer_cannot_decide"):
        await service.decide(
            proposer,
            first.proposal_id,
            decision="approved",
            reason="self approval must fail",
            request_id="g-6",
        )
    denied = await audit_rows(factory, "proposal_id", str(first.proposal_id))
    assert (
        "governance.graduation.decide",
        "deny",
        "proposer_cannot_decide",
    ) in denied
    rejected = await service.decide(
        decider,
        first.proposal_id,
        decision="rejected",
        reason="insufficient corroboration",
        request_id="g-7",
    )
    assert rejected.state == "rejected"
    assert rejected.decided_by == decider_id
    assert rejected.attestation_hash is not None
    assert rejected.publish_package_id is None
    # Stale duplicate decision fails closed and is audited.
    with pytest.raises(GovernanceError, match="proposal_already_decided"):
        await service.decide(
            decider,
            first.proposal_id,
            decision="approved",
            reason="stale duplicate decision",
            request_id="g-8",
        )
    # Re-proposal is a new proposal referencing the rejected one.
    second = await service.propose(
        proposer,
        proposal_input(
            record_ids,
            target=target,
            supersedes=first.proposal_id,
        ),
        request_id="g-9",
    )
    assert second.supersedes_proposal_id == first.proposal_id
    approved = await service.decide(
        decider,
        second.proposal_id,
        decision="approved",
        reason="evidence verified against snapshot",
        request_id="g-10",
    )
    assert approved.state == "approved"
    assert approved.publish_package_id is not None
    # AC-09: only a staged draft exists; nothing activated automatically.
    async with factory() as session:
        lifecycle = await session.scalar(text("""
            SELECT lifecycle FROM sot_packages WHERE package_id=:package_id
        """), {"package_id": approved.publish_package_id})
        activated = await session.scalar(text("""
            SELECT count(*) FROM record_versions WHERE package_id=:package_id
        """), {"package_id": approved.publish_package_id})
    assert lifecycle == "staged"
    assert int(activated or 0) == 0
    # Full lineage rides in the staged candidate package.
    staging_name = f"graduation-{second.proposal_id.hex}"
    parsed = PackageParser(roots[1]).parse(staging_name)
    record = parsed.records[0]
    assert record.provenance_level == "claim"
    lineage = record.value["lineage"]
    assert set(lineage["research_record_ids"]) == {
        str(item) for item in record_ids
    }
    assert lineage["packages"][0]["fingerprint"] in {
        fingerprint.removeprefix("research:")
        for fingerprint in parsed.source_hashes
    }
    assert lineage["evidence_checksums"]
    # The publish gate still guards the candidate: publish before validation
    # fails, and validation + publish by the attesting decider activates it
    # as an explicit company *claim*, never as verified fact.
    settings = research_settings(roots)
    sot = SOTPublishService(settings, factory=factory)
    with pytest.raises(PublishError, match="candidate_not_validated"):
        await sot.publish(
            approved.publish_package_id,
            actor_id=decider_id,
            request_id="g-11",
        )
    report = await sot.validate(
        approved.publish_package_id,
        actor_id=decider_id,
        request_id="g-12",
    )
    assert report.valid, [item.code for item in report.findings]
    published = await sot.publish(
        approved.publish_package_id,
        actor_id=decider_id,
        request_id="g-13",
    )
    assert published.state == "active"
    async with factory() as session:
        states = (await session.execute(text("""
            SELECT verification_state, provenance_level FROM record_versions
            WHERE package_id=:package_id AND lifecycle='active'
        """), {"package_id": approved.publish_package_id})).all()
    assert states == [("claim", "claim")]
    submitted = await audit_rows(factory, "proposal_id", str(second.proposal_id))
    assert (
        "governance.graduation.submit",
        "success",
        "draft_candidate_staged",
    ) in submitted


@pytest.mark.asyncio
async def test_graduation_races_and_policy_recheck_fail_closed(
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    proposer_id, decider_id, source, record_ids = await graduation_fixture(
        service,
        factory,
    )
    other_id = uuid.uuid4()
    await insert_actor(factory, other_id)
    proposer = subject(Role.CURATOR, proposer_id)
    target = f"company.claims.{uuid.uuid4().hex[:8]}"
    raced = await service.propose(
        proposer,
        proposal_input(record_ids, target=target),
        request_id="race-1",
    )
    outcomes = await asyncio.gather(
        service.decide(
            subject(Role.CURATOR, decider_id),
            raced.proposal_id,
            decision="rejected",
            reason="concurrent rejection",
            request_id="race-2",
        ),
        service.decide(
            subject(Role.CURATOR, other_id),
            raced.proposal_id,
            decision="rejected",
            reason="concurrent duplicate rejection",
            request_id="race-3",
        ),
        return_exceptions=True,
    )
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], GovernanceError)
    assert failures[0].code == "proposal_already_decided"
    async with factory() as session:
        state = await session.scalar(text("""
            SELECT state FROM graduation_proposals WHERE proposal_id=:proposal_id
        """), {"proposal_id": raced.proposal_id})
    assert state == "rejected"

    # AC-14: classification escalation between proposal and approval denies
    # the approval and leaves the proposal undecided.
    guarded = await service.propose(
        proposer,
        proposal_input(record_ids, target=f"{target}.guarded"),
        request_id="race-4",
    )
    async with factory() as session, session.begin():
        await session.execute(text("""
            UPDATE research_sources SET classification='highly_restricted'
            WHERE source_id=:source_id
        """), {"source_id": source.source_id})
    with pytest.raises(GovernanceError, match="research_record_not_graduatable"):
        await service.decide(
            subject(Role.CURATOR, decider_id),
            guarded.proposal_id,
            decision="approved",
            reason="approval after escalation must fail",
            request_id="race-5",
        )
    async with factory() as session:
        held = await session.scalar(text("""
            SELECT state FROM graduation_proposals WHERE proposal_id=:proposal_id
        """), {"proposal_id": guarded.proposal_id})
    assert held == "proposed"
    denied = await audit_rows(factory, "proposal_id", str(guarded.proposal_id))
    assert (
        "governance.graduation.decide",
        "deny",
        "research_record_not_graduatable",
    ) in denied


@pytest.mark.asyncio
async def test_publish_gate_rejects_downgrading_graduated_candidate(
    roots: tuple[Path, Path],
    service: ResearchService,
    factory: async_sessionmaker[Any],
) -> None:
    proposer_id, decider_id, _, record_ids = await graduation_fixture(
        service,
        factory,
        classification="restricted",
    )
    target = f"company.claims.{uuid.uuid4().hex[:8]}"
    proposal = await service.propose(
        subject(Role.CURATOR, proposer_id),
        proposal_input(record_ids, target=target, classification="internal"),
        request_id="gate-1",
    )
    approved = await service.decide(
        subject(Role.CURATOR, decider_id),
        proposal.proposal_id,
        decision="approved",
        reason="approval of a downgrading claim",
        request_id="gate-2",
    )
    assert approved.publish_package_id is not None
    sot = SOTPublishService(research_settings(roots), factory=factory)
    report = await sot.validate(
        approved.publish_package_id,
        actor_id=decider_id,
        request_id="gate-3",
    )
    assert not report.valid
    assert "classification_downgrade" in {item.code for item in report.findings}
    with pytest.raises(PublishError, match="candidate_not_validated"):
        await sot.publish(
            approved.publish_package_id,
            actor_id=decider_id,
            request_id="gate-4",
        )
    async with factory() as session:
        lifecycle = await session.scalar(text("""
            SELECT lifecycle FROM sot_packages WHERE package_id=:package_id
        """), {"package_id": approved.publish_package_id})
        activated = await session.scalar(text("""
            SELECT count(*) FROM record_versions WHERE package_id=:package_id
        """), {"package_id": approved.publish_package_id})
    assert lifecycle == "rejected"
    assert int(activated or 0) == 0


@pytest.mark.asyncio
async def test_publish_gate_flips_answered_gap_to_published(
    roots: tuple[Path, Path],
    factory: async_sessionmaker[Any],
) -> None:
    curator_id, requester_id = uuid.uuid4(), uuid.uuid4()
    await insert_actor(factory, curator_id)
    await insert_actor(factory, requester_id)
    settings = research_settings(roots)
    source_key = f"gapflip.{uuid.uuid4().hex}"
    record_key = f"GAPFLIP.{uuid.uuid4().hex}"
    sot = SOTPublishService(settings, factory=factory, clock=lambda: NOW)
    first_root = build_package(
        roots[1],
        curator_id=curator_id,
        owner_id=curator_id,
        source_key=source_key,
        record_key=record_key,
        text="Approved deployment coverage statement revision one.",
    )
    staged = await sot.stage(first_root.name, actor_id=curator_id, request_id="f-1")
    assert (await sot.validate(
        staged.package_id, actor_id=curator_id, request_id="f-2",
    )).valid
    await sot.publish(staged.package_id, actor_id=curator_id, request_id="f-3")
    async with factory() as session:
        version_id = await session.scalar(text("""
            SELECT rv.version_id FROM record_versions rv
            JOIN records r ON r.record_id=rv.record_id
            WHERE r.record_key=:record_key AND rv.lifecycle='active'
        """), {"record_key": record_key})
    assert version_id is not None
    repository = GovernanceRepository()
    async with factory() as session, session.begin():
        gap = await repository.create_or_increment_gap(
            session,
            question_digest=uuid.uuid4().hex + uuid.uuid4().hex,
            sanitized_question="Which deployment coverage is approved?",
            sanitized_summary="deployment coverage",
            requester_id=requester_id,
            routing_key="curator:sot",
            origin="manual",
            reason_category="manual_entry",
        )
        await repository.transition_gap(
            session, gap.gap_id, to_state="triaged",
            actor_subject_id=curator_id, reason="triaged",
        )
        await repository.transition_gap(
            session, gap.gap_id, to_state="assigned",
            actor_subject_id=curator_id, reason="assigned",
            owner_subject_id=curator_id,
        )
        await repository.transition_gap(
            session, gap.gap_id, to_state="answered",
            actor_subject_id=curator_id, reason="answered by activated record",
            resolving_version_id=version_id,
        )
    second_root = build_package(
        roots[1],
        curator_id=curator_id,
        owner_id=curator_id,
        source_key=source_key,
        record_key=record_key,
        revision=2,
        ordinal=2,
        supersedes=True,
        text="Approved deployment coverage statement revision two.",
    )
    staged_two = await sot.stage(
        second_root.name, actor_id=curator_id, request_id="f-4",
    )
    assert (await sot.validate(
        staged_two.package_id, actor_id=curator_id, request_id="f-5",
    )).valid
    await sot.publish(staged_two.package_id, actor_id=curator_id, request_id="f-6")
    async with factory() as session:
        published_gap = await repository.get_gap(session, gap.gap_id)
        history = await repository.list_gap_transitions(session, gap.gap_id)
    assert published_gap is not None
    assert published_gap.lifecycle == "published"
    assert published_gap.closed_at is not None
    assert [(item.from_state, item.to_state) for item in history][-1] == (
        "answered",
        "published",
    )
    audits = await audit_rows(factory, "gap_id", str(gap.gap_id))
    assert ("governance.gap.publish", "success", "linked_record_activated") in audits
