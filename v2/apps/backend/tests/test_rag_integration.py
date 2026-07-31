import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.api import rag_subject
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.rag.models import (
    ProviderAnswer,
    ProviderEvidence,
    SearchFilters,
)
from rtr_copilot.rag.reindex import ReindexError, ReindexService
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.sot.service import SOTPublishService

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
BENCHMARK_RECALL_AT_5_MIN = 1.0
BENCHMARK_MRR_MIN = 0.8
BENCHMARK_EXACT_ID_MIN = 1.0
BENCHMARK_LOCAL_P95_MS_MAX = 500.0


class HangingAnswer:
    name = "hanging-test"
    model = "never-returns"

    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: list[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        del question, evidence, system_policy
        self.calls += 1
        await asyncio.sleep(60)
        raise AssertionError("timeout failed")
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


async def actor(factory: async_sessionmaker[Any]) -> uuid.UUID:
    actor_id = uuid.uuid4()
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,'rag-integration',:sub,:email,'rtrobotics.com')
        """), {
            "id": actor_id,
            "sub": actor_id.hex,
            "email": f"{actor_id.hex}@rtrobotics.com",
        })
    return actor_id


def settings(root: Path) -> Any:
    return get_settings().model_copy(update={
        "sot_staging_root": root,
        "sot_signing_secret": SecretStr(SECRET),
        "rag_provider_mode": "local",
    })


def subject(user_id: uuid.UUID, role: Role = Role.STAFF) -> Subject:
    return Subject(
        user_id=str(user_id),
        issuer="rag-integration",
        sub=user_id.hex,
        email=f"{user_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


async def publish_and_index(
    root: Path,
    factory: async_sessionmaker[Any],
    actor_id: uuid.UUID,
    *,
    source_key: str,
    record_key: str,
    text_value: str,
    revision: int = 1,
    ordinal: int = 1,
    supersedes: bool = False,
    classification: str = "internal",
    additional_records: list[tuple[str, str]] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    package_root = build_package(
        root,
        curator_id=actor_id,
        owner_id=actor_id,
        source_key=source_key,
        record_key=record_key,
        revision=revision,
        ordinal=ordinal,
        supersedes=supersedes,
        classification=classification,
        text=text_value,
        additional_records=additional_records,
    )
    sot = SOTPublishService(
        settings(root),
        factory=factory,
        clock=lambda: NOW,
    )
    staged = await sot.stage(
        package_root.name,
        actor_id=actor_id,
        request_id=f"stage-{revision}",
    )
    assert (await sot.validate(
        staged.package_id,
        actor_id=actor_id,
        request_id=f"validate-{revision}",
    )).valid
    published = await sot.publish(
        staged.package_id,
        actor_id=actor_id,
        request_id=f"publish-{revision}",
    )
    async with factory() as session:
        outbox_id = await session.scalar(text("""
            SELECT outbox_id FROM sot_reindex_outbox WHERE run_id=:run_id
        """), {"run_id": published.run_id})
    assert outbox_id
    generation_id = await ReindexService(
        settings(root),
        factory=factory,
    ).process(outbox_id)
    return published.package_id, generation_id


@pytest.mark.asyncio
async def test_active_reindex_search_grounded_answer_and_citation(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    source_key = f"rag.{uuid.uuid4().hex}"
    record_key = f"HERA.{uuid.uuid4().hex}"
    _, generation_id = await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=record_key,
        text_value="HERA autonomous drone supports synthetic inspection missions.",
    )
    retrieval = RetrievalService(settings(tmp_path), factory=factory)
    hits = await retrieval.search(
        subject(owner),
        "What inspection can the autonomous drone support?",
        filters=SearchFilters(source_key=source_key),
        request_id="search-grounded",
    )
    assert hits
    assert retrieval.trace.metadata_rows >= 1
    assert retrieval.trace.content_queries == 1
    assert set(retrieval.trace.loaded_chunk_ids) == {item.chunk_id for item in hits}
    assert hits[0].citation.record_key == record_key
    assert hits[0].citation.locator == {"paragraph": 2}
    provider = OfflineExtractiveAnswer()
    response = await AnswerService(
        settings(tmp_path),
        factory=factory,
        retrieval=retrieval,
        provider=provider,
    ).ask(
        subject(owner),
        "What inspection can the autonomous drone support?",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="ask-grounded",
    )
    assert response.state == "grounded"
    assert provider.calls == 1
    assert response.citations
    assert all(f"[{item.marker}]" in response.answer for item in response.citations)
    async with factory() as session:
        persisted = await session.scalar(text("""
            SELECT count(*) FROM answer_citations
            WHERE answer_run_id=:run_id
        """), {"run_id": response.answer_run_id})
        pointer = await session.scalar(text("""
            SELECT generation_id FROM active_search_generations
            WHERE source_key=:source_key
        """), {"source_key": source_key})
    assert persisted == len(response.citations)
    assert pointer == generation_id


@pytest.mark.asyncio
async def test_policy_denial_short_circuits_content_and_provider_and_upserts_gap(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    denied_user = await actor(factory)
    source_key = f"denied.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"DENIED.{uuid.uuid4().hex}",
        text_value="NEVER-LOAD-DENIED-TEXT synthetic classified fact.",
    )
    async with factory() as session, session.begin():
        record_id = await session.scalar(text("""
            SELECT record_id FROM records WHERE source_key=:source_key
        """), {"source_key": source_key})
        await session.execute(text("""
            INSERT INTO acl_entries(
              resource_id,principal_type,principal_id,action,effect,granted_by
            ) VALUES (:record_id,'user',:principal,'view','deny',:owner)
        """), {
            "record_id": record_id,
            "principal": denied_user,
            "owner": owner,
        })
    retrieval = RetrievalService(settings(tmp_path), factory=factory)
    hits = await retrieval.search(
        subject(denied_user),
        "NEVER-LOAD-DENIED-TEXT",
        filters=SearchFilters(source_key=source_key),
        request_id="denied-search",
    )
    assert hits == []
    assert retrieval.trace.metadata_rows == 1
    assert retrieval.trace.policy_allowed == 0
    assert retrieval.trace.content_queries == 0
    assert retrieval.trace.loaded_chunk_ids == []
    provider = OfflineExtractiveAnswer()
    answer = AnswerService(
        settings(tmp_path),
        factory=factory,
        retrieval=retrieval,
        provider=provider,
    )
    first = await answer.ask(
        subject(denied_user),
        "NEVER-LOAD-DENIED-TEXT",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="denied-ask-1",
    )
    second = await answer.ask(
        subject(denied_user),
        "NEVER-LOAD-DENIED-TEXT",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=first.conversation_id,
        request_id="denied-ask-2",
    )
    assert first.state == second.state == "honest_null"
    assert first.gap_id == second.gap_id
    assert provider.calls == 0
    assert "NEVER-LOAD-DENIED-TEXT" not in first.answer
    async with factory() as session:
        occurrence = await session.scalar(text("""
            SELECT occurrence_count FROM gaps WHERE gap_id=:gap_id
        """), {"gap_id": first.gap_id})
    assert occurrence == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal_type",
    ["group", "role", "department", "project"],
)
async def test_effective_principal_deny_overrides_role_allow_before_content(
    principal_type: str,
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    viewer = await actor(factory)
    source_key = f"principal-{principal_type}.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"PRINCIPAL.{uuid.uuid4().hex}",
        text_value=f"NEVER-LOAD-{principal_type.upper()}-DENIED synthetic fact.",
    )
    async with factory() as session, session.begin():
        record_id = await session.scalar(text("""
            SELECT record_id FROM records WHERE source_key=:source_key
        """), {"source_key": source_key})
        if principal_type == "group":
            principal_id = uuid.uuid4()
            await session.execute(text("""
                INSERT INTO groups(
                  group_id,issuer,provider_group_key,name
                ) VALUES (:id,'rag-integration',:key,:key)
            """), {"id": principal_id, "key": principal_id.hex})
            await session.execute(text("""
                INSERT INTO subject_groups(subject_id,group_id)
                VALUES (:viewer,:principal)
            """), {"viewer": viewer, "principal": principal_id})
        elif principal_type == "role":
            principal_id = await session.scalar(text("""
                SELECT role_id FROM roles WHERE key='staff'
            """))
            await session.execute(text("""
                INSERT INTO subject_roles(subject_id,role_id)
                VALUES (:viewer,:principal)
            """), {"viewer": viewer, "principal": principal_id})
        else:
            principal_id = uuid.uuid4()
            await session.execute(text("""
                INSERT INTO subject_scopes(subject_id,scope_type,scope_key)
                VALUES (:viewer,:scope_type,:scope_key)
            """), {
                "viewer": viewer,
                "scope_type": principal_type,
                "scope_key": str(principal_id),
            })
        await session.execute(text("""
            INSERT INTO acl_entries(
              resource_id,principal_type,principal_id,action,effect,granted_by
            ) VALUES (
              :record_id,:principal_type,:principal_id,'view','deny',:owner
            )
        """), {
            "record_id": record_id,
            "principal_type": principal_type,
            "principal_id": principal_id,
            "owner": owner,
        })
    retrieval = RetrievalService(settings(tmp_path), factory=factory)
    hits = await retrieval.search(
        subject(viewer),
        f"NEVER-LOAD-{principal_type.upper()}-DENIED",
        filters=SearchFilters(source_key=source_key),
        request_id=f"principal-deny-{principal_type}",
    )
    assert hits == []
    assert retrieval.trace.policy_allowed == 0
    assert retrieval.trace.content_queries == 0
    assert retrieval.trace.loaded_chunk_ids == []


@pytest.mark.asyncio
async def test_denied_metadata_pages_cannot_starve_later_authorized_candidate(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    viewer = await actor(factory)
    suffix = uuid.uuid4().hex
    source_key = f"pagination.{suffix}"
    denied_keys = [f"AAA-{suffix}", f"AAB-{suffix}"]
    allowed_key = f"ZZZ-{suffix}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=denied_keys[0],
        text_value="DENIED-FIRST-PAGE-ONE synthetic text.",
        additional_records=[
            (denied_keys[1], "DENIED-FIRST-PAGE-TWO synthetic text."),
            (allowed_key, "AUTHORIZED-LATER-PAGE unique synthetic target."),
        ],
    )
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO acl_entries(
              resource_id,principal_type,principal_id,action,effect,granted_by
            )
            SELECT record_id,'user',:viewer,'view','deny',:owner
            FROM records
            WHERE source_key=:source_key AND record_key=ANY(CAST(:keys AS text[]))
        """), {
            "viewer": viewer,
            "owner": owner,
            "source_key": source_key,
            "keys": denied_keys,
        })
    paging_settings = settings(tmp_path).model_copy(update={
        "rag_candidate_limit": 2,
        "rag_metadata_scan_limit": 10,
    })
    retrieval = RetrievalService(paging_settings, factory=factory)
    hits = await retrieval.search(
        subject(viewer),
        "AUTHORIZED-LATER-PAGE unique target",
        filters=SearchFilters(source_key=source_key),
        request_id="metadata-pagination",
    )
    assert hits
    assert hits[0].citation.record_key == allowed_key
    assert retrieval.trace.metadata_rows == 3
    assert retrieval.trace.content_queries == 1
    assert all(
        "DENIED-FIRST-PAGE" not in hit.snippet
        for hit in hits
    )


@pytest.mark.asyncio
async def test_reindex_failure_preserves_prior_then_swap_and_replay_are_atomic(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    source_key = f"swap.{uuid.uuid4().hex}"
    record_key = f"SWAP.{uuid.uuid4().hex}"
    _, first_generation = await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=record_key,
        text_value="Revision one synthetic evidence.",
    )
    package_root = build_package(
        tmp_path,
        curator_id=owner,
        owner_id=owner,
        source_key=source_key,
        record_key=record_key,
        revision=2,
        ordinal=2,
        supersedes=True,
        text="Revision two replacement synthetic evidence.",
    )
    sot = SOTPublishService(
        settings(tmp_path),
        factory=factory,
        clock=lambda: NOW,
    )
    staged = await sot.stage(
        package_root.name,
        actor_id=owner,
        request_id="swap-stage",
    )
    assert (await sot.validate(
        staged.package_id,
        actor_id=owner,
        request_id="swap-validate",
    )).valid
    published = await sot.publish(
        staged.package_id,
        actor_id=owner,
        request_id="swap-publish",
    )
    async with factory() as session:
        outbox_id = await session.scalar(text("""
            SELECT outbox_id FROM sot_reindex_outbox WHERE run_id=:run_id
        """), {"run_id": published.run_id})
    reindex = ReindexService(settings(tmp_path), factory=factory)
    with pytest.raises(ReindexError, match="injected_failure"):
        await reindex.process(outbox_id, inject_failure="after_chunks")
    async with factory() as session:
        pointer = await session.scalar(text("""
            SELECT generation_id FROM active_search_generations
            WHERE source_key=:source_key
        """), {"source_key": source_key})
    assert pointer == first_generation
    concurrent = await asyncio.gather(
        reindex.process(outbox_id),
        ReindexService(settings(tmp_path), factory=factory).process(outbox_id),
    )
    assert len(set(concurrent)) == 1
    second_generation = concurrent[0]
    replay = await reindex.process(outbox_id)
    assert replay == second_generation
    assert second_generation != first_generation
    async with factory() as session:
        visible = await session.scalar(text("""
            SELECT count(*) FROM chunks c JOIN active_search_generations ag
              ON ag.generation_id=c.generation_id
            WHERE c.source_key=:source_key
        """), {"source_key": source_key})
        generations = await session.scalar(text("""
            SELECT count(*) FROM search_generations
            WHERE source_key=:source_key AND lifecycle='active'
        """), {"source_key": source_key})
    assert visible == 1
    assert generations == 1


@pytest.mark.asyncio
async def test_external_provider_dlp_yields_honest_null_without_model_call(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    source_key = f"restricted.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"RESTRICTED.{uuid.uuid4().hex}",
        text_value="Restricted synthetic operational evidence.",
        classification="restricted",
    )
    retrieval = RetrievalService(
        settings(tmp_path),
        factory=factory,
        provider_policy=ProviderPolicy(
            mode="external",
            external_allowlist=frozenset({"public_internal"}),
        ),
    )
    provider = OfflineExtractiveAnswer()
    response = await AnswerService(
        settings(tmp_path),
        factory=factory,
        retrieval=retrieval,
        provider=provider,
    ).ask(
        subject(owner, Role.CURATOR),
        "What is the restricted operational evidence?",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="external-denied",
    )
    assert response.state == "honest_null"
    assert provider.calls == 0
    assert "provider.classification_denied" in retrieval.trace.dlp_rule_ids


@pytest.mark.asyncio
async def test_secret_question_is_omitted_from_storage_gap_and_provider(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    secret = "api_key=RAG-SECRET-MUST-NEVER-PERSIST"
    provider = OfflineExtractiveAnswer()
    response = await AnswerService(
        settings(tmp_path),
        factory=factory,
        provider=provider,
    ).ask(
        subject(owner),
        f"Please inspect {secret}",
        filters=SearchFilters(),
        require_verified=True,
        conversation_id=None,
        request_id="secret-question",
    )
    assert response.state == "honest_null"
    assert provider.calls == 0
    async with factory() as session:
        stored = await session.scalar(text("""
            SELECT concat(
              coalesce(string_agg(sanitized_content,' '),''),
              coalesce((SELECT string_agg(sanitized_question,' ') FROM gaps),'')
            ) FROM messages
            WHERE conversation_id=:conversation_id
        """), {"conversation_id": response.conversation_id})
    assert secret not in str(stored)
    assert "Sensitive question omitted." in str(stored)


@pytest.mark.asyncio
async def test_hanging_provider_times_out_repairs_once_then_honest_null(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    source_key = f"timeout.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"TIMEOUT.{uuid.uuid4().hex}",
        text_value="Timeout synthetic evidence is current and verified.",
    )
    timeout_settings = settings(tmp_path).model_copy(update={
        "rag_provider_timeout_seconds": 0.05,
    })
    provider = HangingAnswer()
    started = time.perf_counter()
    response = await AnswerService(
        timeout_settings,
        factory=factory,
        retrieval=RetrievalService(timeout_settings, factory=factory),
        provider=provider,
    ).ask(
        subject(owner),
        "What timeout evidence is current?",
        filters=SearchFilters(source_key=source_key),
        require_verified=True,
        conversation_id=None,
        request_id="provider-timeout",
    )
    elapsed = time.perf_counter() - started
    assert response.state == "honest_null"
    assert provider.calls == 2
    assert elapsed < 1.0
    async with factory() as session:
        decision = await session.scalar(text("""
            SELECT provider_decision FROM answer_runs
            WHERE answer_run_id=:run_id
        """), {"run_id": response.answer_run_id})
    assert decision == "called_grounding_failed"


@pytest.mark.asyncio
async def test_typed_http_api_and_conversation_rechecks_revoked_citations(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    source_key = f"http.{uuid.uuid4().hex}"
    await publish_and_index(
        tmp_path,
        factory,
        owner,
        source_key=source_key,
        record_key=f"HTTP.{uuid.uuid4().hex}",
        text_value="HTTP synthetic evidence supports grounded retrieval.",
    )

    async def authenticated() -> Subject:
        return subject(owner)

    app.dependency_overrides[rag_subject] = authenticated
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            search_response = await client.post("/api/v1/search", json={
                "query": "What supports grounded retrieval?",
                "filters": {"source_key": source_key},
            })
            assert search_response.status_code == 200
            assert search_response.json()["results"]
            ask_response = await client.post("/api/v1/ask", json={
                "question": "What supports grounded retrieval?",
                "filters": {"source_key": source_key},
            })
            assert ask_response.status_code == 200
            answer = ask_response.json()
            assert answer["state"] == "grounded"
            conversation_id = answer["conversation_id"]
            history = await client.get(
                f"/api/v1/conversations/{conversation_id}",
            )
            assert history.status_code == 200
            assert history.json()["messages"][-1]["citations"]

            async with factory() as session, session.begin():
                record_id = await session.scalar(text("""
                    SELECT record_id FROM records WHERE source_key=:source_key
                """), {"source_key": source_key})
                await session.execute(text("""
                    INSERT INTO acl_entries(
                      resource_id,principal_type,principal_id,action,effect,granted_by
                    ) VALUES (:record_id,'user',:principal,'view','deny',:principal)
                """), {"record_id": record_id, "principal": owner})
            revoked = await client.get(
                f"/api/v1/conversations/{conversation_id}",
            )
            assert revoked.status_code == 200
            assistant = revoked.json()["messages"][-1]
            assert assistant["citations"] == []
            assert assistant["content"] == "Evidence is no longer available."
    finally:
        app.dependency_overrides.pop(rag_subject, None)

    async def anonymous() -> None:
        return None

    app.dependency_overrides[rag_subject] = anonymous
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            denied = await client.post("/api/v1/search", json={"query": "safe"})
    finally:
        app.dependency_overrides.pop(rag_subject, None)
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_synthetic_hybrid_retrieval_benchmark_thresholds(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    nonce = uuid.uuid4().hex[:10]
    id_tag = f"{nonce}id"
    vi_tag = f"{nonce}vi"
    camel_tag = f"{nonce}camel"
    typo_tag = f"{nonce}typo"
    lexical_tag = f"{nonce}lexical"
    corpus = [
        (
            f"bench.id.{uuid.uuid4().hex}",
            f"L3F.ENT.002-{uuid.uuid4().hex[:8]}",
            f"L3F.ENT.{id_tag} Zephyr harmonic docking controller.",
            f"L3F.ENT.{id_tag}",
        ),
        (
            f"bench.vi.{uuid.uuid4().hex}",
            f"AQUILA-{uuid.uuid4().hex[:8]}",
            f"AQUILA-{vi_tag} thiết bị bay không người lái khảo sát điện gió.",
            f"AQUILA-{vi_tag} thiet bi bay khong nguoi lai",
        ),
        (
            f"bench.camel.{uuid.uuid4().hex}",
            f"SKYWATCH-{uuid.uuid4().hex[:8]}",
            f"SkyWatch{camel_tag} monitors thermal anomalies on synthetic assets.",
            f"sky watch{camel_tag} thermal anomalies",
        ),
        (
            f"bench.typo.{uuid.uuid4().hex}",
            f"TYPO-{uuid.uuid4().hex[:8]}",
            f"Hypercalibration-{typo_tag} synchronizes the synthetic optical manifold.",
            f"hypercalibraton-{typo_tag} optical manifold",
        ),
        (
            f"bench.lexical.{uuid.uuid4().hex}",
            f"ZXQJ-{uuid.uuid4().hex[:8]}",
            f"ZXQJ-{lexical_tag} rare synthetic calibration protocol.",
            f"ZXQJ-{lexical_tag} calibration protocol",
        ),
    ]
    for source_key, record_key, content, _ in corpus:
        await publish_and_index(
            tmp_path,
            factory,
            owner,
            source_key=source_key,
            record_key=record_key,
            text_value=content,
        )
    retrieval = RetrievalService(settings(tmp_path), factory=factory)
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    exact_identifier_hits = 0
    for index, (_, expected_record, _, query) in enumerate(corpus):
        started = time.perf_counter()
        hits = await retrieval.search(
            subject(owner),
            query,
            filters=SearchFilters(),
            request_id=f"benchmark-{index}",
        )
        latencies.append((time.perf_counter() - started) * 1000)
        positions = [
            position
            for position, hit in enumerate(hits, 1)
            if hit.citation.record_key == expected_record
        ]
        reciprocal_ranks.append(1.0 / positions[0] if positions else 0.0)
        if index == 0 and positions:
            exact_identifier_hits += 1
        assert hits == sorted(
            hits,
            key=lambda item: (-item.fusion_score, item.chunk_key),
        )
        assert all(
            hit.citation.record_checksum
            and hit.citation.record_version_id
            and hit.citation.locator == {"paragraph": 2}
            for hit in hits
        )
    recall_at_5 = sum(value > 0 for value in reciprocal_ranks) / len(corpus)
    mrr = sum(reciprocal_ranks) / len(corpus)
    exact_id = float(exact_identifier_hits)
    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
    print(
        "RAG_BENCHMARK "
        f"dataset={len(corpus)} recall_at_5={recall_at_5:.3f} "
        f"mrr={mrr:.3f} exact_id={exact_id:.3f} p95_ms={p95:.2f} "
        f"reciprocal_ranks={reciprocal_ranks}",
    )
    assert recall_at_5 >= BENCHMARK_RECALL_AT_5_MIN
    assert mrr >= BENCHMARK_MRR_MIN
    assert exact_id >= BENCHMARK_EXACT_ID_MIN
    assert p95 <= BENCHMARK_LOCAL_P95_MS_MAX
