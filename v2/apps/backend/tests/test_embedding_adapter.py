"""TIP-014RE · Real embedding adapter — hermetic unit tests.

Covers the four laws of the lane:
1. Factory trust surface: offline by default; provider path fail-closed.
2. Provider adapter correctness: batching, ordering, L2 normalization,
   dimension-mismatch refusal.
3. Query-path degrade: a provider failure yields ``None`` (lexical-only),
   never an exception and never a hash-space fallback.
4. Offline stub keeps working at the new schema dimension.
"""

import asyncio
import json
import math
import uuid

import httpx
import pytest

from rtr_copilot.auth.models import Subject
from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import (
    EMBEDDING_BATCH_SIZE,
    EmbeddingProviderError,
    OfflineHashEmbedding,
    OpenAIEmbedding,
    build_embedding_adapter,
)
from rtr_copilot.rag.models import SearchFilters
from rtr_copilot.rag.retrieval import RetrievalService


def _adapter(handler, *, dimension: int = 8) -> OpenAIEmbedding:
    return OpenAIEmbedding(
        api_key="sk-test",
        model="text-embedding-3-small",
        dimension=dimension,
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )


def _response(vectors: list[list[float]]) -> httpx.Response:
    return httpx.Response(200, json={
        "data": [
            {"index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
    })


class TestFactoryTrustSurface:
    def test_default_settings_build_offline_stub(self) -> None:
        adapter = build_embedding_adapter(Settings())
        assert isinstance(adapter, OfflineHashEmbedding)
        assert adapter.dimension == 1536

    def test_provider_requires_policy_even_on_bypassed_settings(self) -> None:
        # model_construct skips the validator; the factory must still refuse.
        bypassed = Settings.model_construct(
            rag_embedding_provider="openai",
            openai_api_key=None,
            rag_external_classification_allowlist="",
            rag_embedding_dimension=1536,
            rag_embedding_openai_model="text-embedding-3-small",
            rag_embedding_timeout_seconds=8.0,
        )
        with pytest.raises(ValueError, match="policy_required"):
            build_embedding_adapter(bypassed)

    def test_provider_builds_when_policy_satisfied(self) -> None:
        settings = Settings(
            rag_embedding_provider="openai",
            openai_api_key="sk-test",
            rag_external_classification_allowlist="internal",
        )
        adapter = build_embedding_adapter(settings)
        assert isinstance(adapter, OpenAIEmbedding)
        assert adapter.dimension == 1536
        assert adapter.model == "text-embedding-3-small"


class TestOpenAIEmbedding:
    def test_batch_pages_requests_and_preserves_order(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["dimensions"] == 8
            assert request.headers["Authorization"] == "Bearer sk-test"
            batch = payload["input"]
            calls.append(len(batch))
            # Distinct vector per text; reversed index order in the response
            # must NOT reorder results (the adapter sorts by index).
            data = [
                {
                    "index": index,
                    "embedding": [float(len(text))] + [1.0] * 7,
                }
                for index, text in enumerate(batch)
            ]
            return httpx.Response(200, json={"data": list(reversed(data))})

        texts = [("x" * (index + 1)) for index in range(EMBEDDING_BATCH_SIZE + 3)]
        vectors = _adapter(handler).embed_batch(texts)
        assert calls == [EMBEDDING_BATCH_SIZE, 3]
        assert len(vectors) == len(texts)
        # Order preserved: first component scales with text length rank.
        firsts = [vector[0] for vector in vectors]
        assert firsts == sorted(firsts)

    def test_vectors_are_l2_normalized(self) -> None:
        adapter = _adapter(lambda request: _response([[3.0, 4.0] + [0.0] * 6]))
        vector = adapter.embed("anything")
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)
        assert math.isclose(vector[0], 0.6)

    def test_dimension_mismatch_is_refused(self) -> None:
        adapter = _adapter(lambda request: _response([[1.0, 2.0]]))
        with pytest.raises(EmbeddingProviderError, match="dimension_mismatch"):
            adapter.embed("anything")

    def test_http_error_wraps_as_provider_error(self) -> None:
        adapter = _adapter(lambda request: httpx.Response(500))
        with pytest.raises(EmbeddingProviderError, match="embedding_http"):
            adapter.embed("anything")

    @pytest.mark.asyncio
    async def test_aembed_success_and_failure(self) -> None:
        good = _adapter(lambda request: _response([[1.0] + [0.0] * 7]))
        vector = await good.aembed("anything")
        assert math.isclose(vector[0], 1.0)
        bad = _adapter(lambda request: httpx.Response(429))
        with pytest.raises(EmbeddingProviderError):
            await bad.aembed("anything")


class TestQueryPathDegrade:
    @pytest.mark.asyncio
    async def test_provider_failure_degrades_to_lexical_only(self) -> None:
        service = RetrievalService(Settings())
        service.embedding = _adapter(lambda request: httpx.Response(503))
        vector = await service._query_vector("hera mtow")
        assert vector is None
        assert service.trace.embedding_degraded is True

    @pytest.mark.asyncio
    async def test_offline_adapter_never_degrades(self) -> None:
        service = RetrievalService(Settings())
        vector = await service._query_vector("hera mtow")
        assert vector is not None
        assert len(vector) == 1536
        assert service.trace.embedding_degraded is False

    @pytest.mark.asyncio
    async def test_embedding_starts_before_metadata_authorization_scan(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class OverlapRetrieval(RetrievalService):
            async def _query_vector(self, terms_text: str) -> list[float] | None:
                del terms_text
                started.set()
                await release.wait()
                return [0.0] * 1536

            async def _metadata(self, *args: object, **kwargs: object) -> list[dict]:
                del args, kwargs
                await asyncio.wait_for(started.wait(), timeout=0.5)
                release.set()
                return []

        service = OverlapRetrieval(Settings())
        subject = Subject(
            user_id=str(uuid.uuid4()),
            issuer="https://issuer.test",
            sub="overlap-test",
            email="staff@rtrobotics.com",
            canonical_domain="rtrobotics.com",
        )
        hits = await service.search(
            subject,
            "HERA là gì?",
            filters=SearchFilters(source_key="test.source"),
            request_id="overlap-test",
        )
        assert hits == []
        assert started.is_set()


class TestOfflineStubAtSchemaDimension:
    def test_offline_default_matches_schema_dimension(self) -> None:
        adapter = OfflineHashEmbedding()
        vector = adapter.embed("autonomous drone")
        assert len(vector) == 1536
        assert math.isclose(
            math.sqrt(sum(value * value for value in vector)), 1.0,
        )
        assert adapter.embed_batch(["a", "b"]) == [
            adapter.embed("a"), adapter.embed("b"),
        ]


class TestSemanticRelevanceFloor:
    """TIP-014RE: high provider-cosine admits zero-overlap candidates; the
    hash-era hard exclusions stay intact whenever the floor is absent."""

    def _score(self, *, vector_score: float, floor: float | None):
        from rtr_copilot.rag.relevance import (
            candidate_relevance_score,
            profile_query,
        )
        # "tech stack" question vs a technology record sharing zero tokens.
        profile = profile_query("cong ty dung tech stack gi")
        return candidate_relevance_score(
            profile,
            text="Next.js FastAPI pgvector Redis MinIO",
            record_key="L3F.4.011",
            base_score=0.03,
            vector_score=vector_score,
            min_vector_score=0.15,
            semantic_floor=floor,
        )

    def test_semantic_bridge_admits_above_floor(self) -> None:
        assert self._score(vector_score=0.52, floor=0.48) is not None

    def test_below_floor_stays_excluded(self) -> None:
        assert self._score(vector_score=0.40, floor=0.48) is None

    def test_no_floor_preserves_hash_era_exclusion(self) -> None:
        assert self._score(vector_score=0.99, floor=None) is None

    def test_degraded_query_zero_vector_never_bridges(self) -> None:
        assert self._score(vector_score=0.0, floor=0.48) is None

    def test_retrieval_floor_only_for_provider_adapter(self) -> None:
        offline = RetrievalService(Settings())
        assert offline._semantic_floor is None
        provider = RetrievalService(Settings())
        provider.embedding = OpenAIEmbedding(
            api_key="sk-test",
            model="text-embedding-3-small",
            dimension=1536,
            timeout_seconds=5.0,
        )
        assert provider._semantic_floor == pytest.approx(0.48)


class TestMergeEnterpriseHitsSemanticBoundary:
    """TIP-014RE: a resolved entity dossier (reserved) must not discard the
    non-reserved record that actually answers a specific-attribute question,
    yet must keep the strict boundary for exact definition questions and for
    offline/degraded runs (floor None)."""

    @staticmethod
    def _hit(record_key: str, *, vector_score: float, fusion: float) -> object:
        import uuid as _uuid

        from rtr_copilot.rag.models import Citation, RetrievalHit
        cid = _uuid.uuid4()
        return RetrievalHit(
            chunk_id=cid,
            chunk_key=f"k:{record_key}",
            snippet=f"text of {record_key}",
            lexical_score=0.0,
            vector_score=vector_score,
            fusion_score=fusion,
            classification="internal",
            citation=Citation(
                marker="C1", chunk_id=cid, record_key=record_key,
                record_version_id=None, evidence_key=None,
                record_checksum="0" * 64, evidence_checksum=None,
                source_key="rtr.l3_facts", source_revision=1,
                provenance_level="verified_primary", verification_state="verified",
                freshness_state="current", source_label=record_key, locator={},
            ),
        )

    def _merge(self, sot, files, *, intent, floor):
        return RetrievalService._merge_enterprise_hits(
            sot, files, limit=12,
            priority_record_keys=("L3F.ENT.001", "L3F.ENT.002"),
            query_intent=intent, semantic_floor=floor,
        )

    def _keys(self, hits):
        return [h.citation.record_key for h in hits]

    def test_lookup_admits_semantic_answer_above_floor(self) -> None:
        sot = [
            self._hit("L3F.ENT.001", vector_score=0.29, fusion=1.5),
            self._hit("L3F.ENT.002", vector_score=0.29, fusion=1.6),
            self._hit("L3F.4.011", vector_score=0.52, fusion=1.29),  # the answer
        ]
        keys = self._keys(self._merge(sot, [], intent="lookup", floor=0.48))
        assert "L3F.4.011" in keys

    def test_lookup_below_floor_still_excluded(self) -> None:
        sot = [
            self._hit("L3F.ENT.001", vector_score=0.29, fusion=1.5),
            self._hit("L3F.9.999", vector_score=0.30, fusion=1.1),  # noise
        ]
        keys = self._keys(self._merge(sot, [], intent="lookup", floor=0.48))
        assert keys == ["L3F.ENT.001"]

    def test_definition_keeps_strict_dossier_boundary(self) -> None:
        sot = [
            self._hit("L3F.ENT.001", vector_score=0.29, fusion=1.5),
            self._hit("L3F.4.011", vector_score=0.52, fusion=1.29),
        ]
        keys = self._keys(self._merge(sot, [], intent="definition", floor=0.48))
        assert keys == ["L3F.ENT.001"]

    def test_offline_floor_none_preserves_old_boundary(self) -> None:
        sot = [
            self._hit("L3F.ENT.001", vector_score=0.99, fusion=1.5),
            self._hit("L3F.4.011", vector_score=0.99, fusion=1.29),
        ]
        keys = self._keys(self._merge(sot, [], intent="lookup", floor=None))
        assert keys == ["L3F.ENT.001"]

    def test_open_question_no_reserved_unchanged(self) -> None:
        sot = [
            self._hit("L3F.4.011", vector_score=0.20, fusion=1.29),
            self._hit("L3F.5.010", vector_score=0.20, fusion=1.10),
        ]
        keys = self._keys(self._merge(sot, [], intent="lookup", floor=0.48))
        assert set(keys) == {"L3F.4.011", "L3F.5.010"}
