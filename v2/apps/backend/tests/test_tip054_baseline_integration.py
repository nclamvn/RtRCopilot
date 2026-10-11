"""TIP-054 BRC-007: synthetic, offline business-boundary regressions.

These exercise actual signed publication, indexing, SQL authorization,
AnswerService planning/filtering/grounding and persisted citations. The fake
planner proposes context; it does not replace retrieval or policy. No real
company evidence, external provider, connector, or serving database is used.
"""

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer, OfflineHashEmbedding
from rtr_copilot.rag.answering import AnswerService, GroundingError
from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence, SearchFilters
from rtr_copilot.rag.ontology import EnterpriseOntology, OntologySpec
from rtr_copilot.rag.query_understanding import OfflineRewriter, RewriteResult
from rtr_copilot.rag.reindex import ReindexService
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.sot.models import PackageManifest, PackageRecord, PublishAttestation
from rtr_copilot.sot.package import (
    canonical_json,
    manifest_identity_sha,
    record_content_sha,
    sha256_bytes,
    sign_attestation,
)
from rtr_copilot.sot.service import SOTPublishService

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(not DATABASE_DSN, reason="isolated integration database required")


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    # conftest.py independently rejects any non-disposable database name.
    engine = create_async_engine(DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1))
    return async_sessionmaker(engine, expire_on_commit=False)


def synthetic_settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        postgres_dsn=DATABASE_DSN,
        redis_url="redis://localhost:1/0",
        s3_endpoint="http://localhost:1",
        s3_access_key="synthetic-only",
        s3_secret_key="synthetic-only",
        s3_bucket="synthetic-tip054",
        sot_staging_root=root,
        sot_signing_secret=SecretStr(SECRET),
        openai_api_key=SecretStr(""),
        anthropic_api_key=SecretStr(""),
        rag_embedding_provider="offline",
        rag_embedding_dimension=1536,
        rag_provider_mode="local",
        rag_external_classification_allowlist="",
        rag_rewrite_enabled=False,
    )


async def actor(factory: async_sessionmaker[Any]) -> Subject:
    identity = uuid.uuid4()
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,'tip054-synthetic',:sub,:email,'rtrobotics.com')
        """), {"id": identity, "sub": identity.hex, "email": f"{identity.hex}@rtrobotics.com"})
    return Subject(
        user_id=str(identity), issuer="tip054-synthetic", sub=identity.hex,
        email=f"{identity.hex}@rtrobotics.com", canonical_domain="rtrobotics.com",
        roles={Role.STAFF},
    )


def ontology(core: str, second: str | None = None) -> EnterpriseOntology:
    facets = [{
        "facet_id": "overview", "label": "Overview",
        "presentation_labels": ["Overview", "Tổng quan"], "record_keys": [core],
    }]
    if second:
        facets.append({
            "facet_id": "roadmap", "label": "Roadmap",
            "presentation_labels": ["Roadmap", "Lộ trình"], "record_keys": [second],
        })
    return EnterpriseOntology(OntologySpec.model_validate({
        "schema_version": 1, "registry_id": f"synthetic-tip054-{uuid.uuid4().hex}",
        "owner": "curator:synthetic",
        "entities": [{
            "entity_id": "synthetic.hera", "canonical_name": "HERA",
            "entity_type": "product", "domain": "products", "aliases": ["hira", "hr"],
            "definition_record_keys": [core], "profile_facets": facets,
            "owner": "curator:synthetic", "provenance_level": "approved_internal",
        }],
    }))


def restrict_package(package: Path, record_key: str) -> None:
    """Add an authentic payload use-class restriction, then re-sign the fixture.

    Production data is not edited; every checksum and attestation is recomputed
    before the ordinary stage/validate/publish path receives this package.
    """
    records = [json.loads(line) for line in (package / "records.jsonl").read_text().splitlines()]
    for record in records:
        if record["record_key"] == record_key:
            record["value"].update({
                "sot_tier": "attested_practice", "use_class": ["sales", "proposal"],
            })
            record["content_sha256"] = record_content_sha(PackageRecord.model_validate(record))
    (package / "records.jsonl").write_bytes(
        b"".join(canonical_json(row) + b"\n" for row in records),
    )
    manifest = json.loads((package / "manifest.json").read_text())
    payload_members = [member for member in manifest["members"]
                       if member["path"] != "publish_attestation.json"]
    for member in payload_members:
        content = (package / member["path"]).read_bytes()
        member.update({"byte_size": len(content), "sha256": sha256_bytes(content)})
    payload_sha = sha256_bytes(canonical_json([
        {"path": member["path"], "sha256": member["sha256"]}
        for member in sorted(payload_members, key=lambda row: row["path"])
    ]))
    manifest["payload_sha256"] = payload_sha
    attestation = json.loads((package / "publish_attestation.json").read_text())
    attestation["payload_sha256"] = payload_sha
    attestation["manifest_sha256"] = manifest_identity_sha(PackageManifest.model_validate(manifest))
    attestation["signature"] = sign_attestation(
        PublishAttestation.model_validate(attestation).model_dump(mode="json"), SECRET,
    )
    content = canonical_json(attestation)
    (package / "publish_attestation.json").write_bytes(content)
    for member in manifest["members"]:
        if member["path"] == "publish_attestation.json":
            member.update({"byte_size": len(content), "sha256": sha256_bytes(content)})
    (package / "manifest.json").write_bytes(canonical_json(manifest))


async def publish(
    root: Path, factory: async_sessionmaker[Any], owner: Subject,
    *, source: str, core: str, content: str,
    extra: list[tuple[str, str]] | None = None, restricted_record: str | None = None,
) -> None:
    package = build_package(
        root, curator_id=uuid.UUID(owner.user_id), owner_id=uuid.UUID(owner.user_id),
        source_key=source, record_key=core, text=content, additional_records=extra,
    )
    if restricted_record:
        restrict_package(package, restricted_record)
    tuned = synthetic_settings(root)
    sot = SOTPublishService(tuned, factory=factory, clock=lambda: NOW)
    staged = await sot.stage(
        package.name, actor_id=uuid.UUID(owner.user_id), request_id="tip054-stage",
    )
    validation = await sot.validate(
        staged.package_id, actor_id=uuid.UUID(owner.user_id), request_id="tip054-validate",
    )
    assert validation.valid, validation
    published = await sot.publish(
        staged.package_id, actor_id=uuid.UUID(owner.user_id), request_id="tip054-publish",
    )
    async with factory() as session:
        outbox = await session.scalar(text(
            "SELECT outbox_id FROM sot_reindex_outbox WHERE run_id=:id",
        ), {"id": published.run_id})
    assert outbox
    indexer = ReindexService(tuned, factory=factory)
    assert isinstance(indexer.embedding, OfflineHashEmbedding)
    await indexer.process(outbox)


class ContextPlanner:
    """Finite fake semantic proposal, contingent on actual supplied history."""

    external = True

    def __init__(self) -> None:
        self.calls = 0
        self.inputs: list[str] = []

    async def rewrite(self, question: str) -> RewriteResult:
        self.calls += 1
        self.inputs.append(question)
        has_history = "<conversation_history>" in question and "HERA" in question
        return RewriteResult(
            entities=["HERA"] if has_history else [],
            intent="lookup", completeness="point", answer_shape="direct",
            standalone_question="HERA flight endurance?" if has_history else "",
        )


class ProfilePlanner:
    external = True
    calls = 0

    async def rewrite(self, question: str) -> RewriteResult:
        del question
        self.calls += 1
        return RewriteResult(entities=["HERA"], intent="definition")


class CapturingAnswer(OfflineExtractiveAnswer):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[list[ProviderEvidence]] = []

    async def answer(
        self, question: str, evidence: list[ProviderEvidence], *, system_policy: str,
    ) -> ProviderAnswer:
        self.inputs.append(evidence)
        return await super().answer(question, evidence, system_policy=system_policy)


def service(
    root: Path, factory: async_sessionmaker[Any], core: str,
    *, second: str | None = None, planner: Any = None,
) -> tuple[AnswerService, CapturingAnswer, RetrievalService]:
    tuned = synthetic_settings(root)
    provider = CapturingAnswer()
    retrieval = RetrievalService(tuned, factory=factory)
    assert isinstance(retrieval.embedding, OfflineHashEmbedding)
    answer = AnswerService(
        tuned, factory=factory, retrieval=retrieval, provider=provider,
        rewriter=planner or OfflineRewriter(), ontology=ontology(core, second),
    )
    return answer, provider, retrieval


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "What is HERA payload capacity?", "HERA tải trọng bao nhiêu?",
    "hira payload???", "hr tải trọng???",
])
async def test_tip054_baseline_ordinary_noisy_vi_en(
    tmp_path: Path, factory: async_sessionmaker[Any], question: str,
) -> None:
    owner = await actor(factory)
    source, core = f"tip054.{uuid.uuid4().hex}", f"TIP054.CORE.{uuid.uuid4().hex}"
    await publish(tmp_path, factory, owner, source=source, core=core,
                  content="HERA payload capacity tải trọng is 15 kilograms.")
    answer, provider, _ = service(tmp_path, factory, core)
    response = await answer.ask(
        owner, question, filters=SearchFilters(source_key=source), require_verified=True,
        conversation_id=None, request_id="tip054-ordinary-noisy",
    )
    assert response.state == "grounded", (response.reason_code, response.answer)
    assert "15 kilograms" in response.answer
    assert {citation.record_key for citation in response.citations} == {core}
    assert provider.calls == 1
    async with factory() as session:
        metadata = await session.scalar(text(
            "SELECT retrieval_config->'query_intelligence' FROM answer_runs "
            "WHERE answer_run_id=:id",
        ), {"id": response.answer_run_id})
    assert metadata["entity_count"] == 1
    assert metadata["entity_set_digest"] == hashlib.sha256(b"synthetic.hera").hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("follow_up", ["thế nó bay được bao lâu?", "and its flight endurance?"])
async def test_tip054_baseline_followup_keeps_entity_and_owner(
    tmp_path: Path, factory: async_sessionmaker[Any], follow_up: str,
) -> None:
    owner, other = await actor(factory), await actor(factory)
    source, core = f"tip054.{uuid.uuid4().hex}", f"TIP054.CORE.{uuid.uuid4().hex}"
    await publish(tmp_path, factory, owner, source=source, core=core,
                  content="HERA flight endurance is 56 minutes; thời gian bay là 56 phút.")
    planner = ContextPlanner()
    answer, provider, _ = service(tmp_path, factory, core, planner=planner)
    first = await answer.ask(
        owner, "HERA flight endurance?", filters=SearchFilters(source_key=source),
        require_verified=True, conversation_id=None, request_id="tip054-context-first",
    )
    assert first.state == "grounded"
    second = await answer.ask(
        owner, follow_up, filters=SearchFilters(source_key=source), require_verified=True,
        conversation_id=first.conversation_id, request_id="tip054-context-second",
    )
    assert second.state == "grounded", (second.reason_code, second.answer)
    assert "56" in second.answer
    assert {citation.record_key for citation in second.citations} == {core}
    assert "<conversation_history>" in planner.inputs[-1]
    assert "HERA flight endurance?" in planner.inputs[-1]
    assert provider.calls == 2
    async with factory() as session:
        metadata = await session.scalar(text(
            "SELECT retrieval_config->'query_intelligence' FROM answer_runs "
            "WHERE answer_run_id=:id",
        ), {"id": second.answer_run_id})
    assert metadata["context_message_count"] == 2
    assert metadata["entity_set_digest"] == hashlib.sha256(b"synthetic.hera").hexdigest()
    with pytest.raises(GroundingError, match="conversation_not_found"):
        await answer.ask(
            other, follow_up, filters=SearchFilters(source_key=source), require_verified=True,
            conversation_id=first.conversation_id, request_id="tip054-context-wrong-owner",
        )
    assert provider.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_by", ["absence", "acl"])
async def test_tip054_baseline_absence_and_denial_do_not_load_or_generate(
    tmp_path: Path, factory: async_sessionmaker[Any], blocked_by: str,
) -> None:
    owner = await actor(factory)
    source, core = f"tip054.{uuid.uuid4().hex}", f"TIP054.CORE.{uuid.uuid4().hex}"
    denied_text = "HERA payload capacity is 987 kilograms NEVER-DISCLOSE-SYNTHETIC."
    await publish(tmp_path, factory, owner, source=source, core=core, content=denied_text)
    if blocked_by == "acl":
        async with factory() as session, session.begin():
            await session.execute(text("""
                INSERT INTO acl_entries(
                    resource_id,principal_type,principal_id,action,effect,granted_by
                )
                SELECT record_id,'user',:owner,'view','deny',:owner
                FROM records WHERE source_key=:source
            """), {"owner": uuid.UUID(owner.user_id), "source": source})
    answer, provider, retrieval = service(tmp_path, factory, core)
    response = await answer.ask(
        owner, "HERA payload capacity?",
        filters=SearchFilters(source_key=source if blocked_by == "acl" else f"absent.{source}"),
        require_verified=True, conversation_id=None, request_id="tip054-denied-absence",
    )
    assert response.state == "honest_null"
    assert response.reason_code == "denied_or_unavailable"
    assert response.citations == []
    assert provider.calls == 0 and provider.inputs == []
    assert retrieval.trace.content_queries == 0 and retrieval.trace.loaded_chunk_ids == []
    assert "987" not in response.answer and "NEVER-DISCLOSE" not in response.answer


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_kind", ["absent", "purpose_denied"])
async def test_tip054_baseline_useful_partial_not_false_complete(
    tmp_path: Path, factory: async_sessionmaker[Any], missing_kind: str,
) -> None:
    owner = await actor(factory)
    source = f"tip054.{uuid.uuid4().hex}"
    core, roadmap = f"TIP054.CORE.{uuid.uuid4().hex}", f"TIP054.ROADMAP.{uuid.uuid4().hex}"
    denied = "HERA ROADMAP-ONLY-SYNTHETIC target is 2037."
    await publish(
        tmp_path, factory, owner, source=source, core=core,
        content="HERA là nền tảng UAV đa nhiệm dùng cho kiểm tra tổng hợp.",
        extra=[(roadmap, denied)] if missing_kind == "purpose_denied" else None,
        restricted_record=roadmap if missing_kind == "purpose_denied" else None,
    )
    answer, provider, _ = service(tmp_path, factory, core, second=roadmap, planner=ProfilePlanner())
    response = await answer.ask(
        owner, "HERA là gì?", filters=SearchFilters(), require_verified=True,
        conversation_id=None, request_id="tip054-partial", use_class="attestation",
    )
    assert response.state == "grounded", (response.reason_code, response.answer)
    assert response.coverage_state == "partial"
    assert "UAV đa nhiệm" in response.answer
    assert {citation.record_key for citation in response.citations} == {core}
    assert provider.calls == 1
    assert all(item.record_key != roadmap for batch in provider.inputs for item in batch)
    assert "2037" not in response.answer and "ROADMAP-ONLY" not in response.answer


@pytest.mark.asyncio
async def test_tip054_baseline_use_class_narrows_before_provider_and_persistence(
    tmp_path: Path, factory: async_sessionmaker[Any],
) -> None:
    owner = await actor(factory)
    source, core = f"tip054.{uuid.uuid4().hex}", f"TIP054.CORE.{uuid.uuid4().hex}"
    await publish(
        tmp_path, factory, owner, source=source, core=core,
        content="HERA payload capacity is 17 kilograms PURPOSE-ONLY-SYNTHETIC.",
        restricted_record=core,
    )
    answer, provider, _ = service(tmp_path, factory, core)
    proposal = await answer.ask(
        owner, "HERA payload capacity?", filters=SearchFilters(source_key=source),
        require_verified=True, conversation_id=None, request_id="tip054-purpose-proposal",
        use_class="proposal",
    )
    assert proposal.state == "grounded" and "17 kilograms" in proposal.answer
    assert provider.calls == 1
    attestation = await answer.ask(
        owner, "HERA payload capacity?", filters=SearchFilters(source_key=source),
        require_verified=True, conversation_id=None, request_id="tip054-purpose-attestation",
        use_class="attestation",
    )
    assert attestation.state == "honest_null"
    assert attestation.reason_code == "denied_or_unavailable"
    assert attestation.citations == [] and provider.calls == 1
    assert "chứng thực" in attestation.answer and "đề xuất" in attestation.answer
    assert "17 kilograms" not in attestation.answer and "PURPOSE-ONLY" not in attestation.answer
    async with factory() as session:
        count = await session.scalar(text(
            "SELECT count(*) FROM answer_citations WHERE answer_run_id=:id",
        ), {"id": attestation.answer_run_id})
    assert count == 0
