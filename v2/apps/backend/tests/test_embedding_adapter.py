"""TIP-014RE · Real embedding adapter — hermetic unit tests.

Covers the four laws of the lane:
1. Factory trust surface: offline by default; provider path fail-closed.
2. Provider adapter correctness: batching, ordering, L2 normalization,
   dimension-mismatch refusal.
3. Query-path degrade: a provider failure yields ``None`` (lexical-only),
   never an exception and never a hash-space fallback.
4. Offline stub keeps working at the new schema dimension.
"""

import json
import math

import httpx
import pytest

from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import (
    EMBEDDING_BATCH_SIZE,
    EmbeddingProviderError,
    OfflineHashEmbedding,
    OpenAIEmbedding,
    build_embedding_adapter,
)
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
