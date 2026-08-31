"""Hermetic tests for TIP-014 Phase 2b — LLM query rewrite.

No real network and no real keys. The two provider clients are exercised with
``httpx.MockTransport``; the fallback chain and factory use fakes. Proves:
provider fallback ordering, breaker-open skip, both-fail raises
(so understand() falls back), tolerant JSON parsing, and the enable/keys gating.
"""
import asyncio

import httpx
import pytest

from rtr_copilot.config import Settings
from rtr_copilot.limits.breaker import ProviderUnavailable
from rtr_copilot.observability import metrics as m
from rtr_copilot.rag.ontology import load_ontology
from rtr_copilot.rag.query_understanding import OfflineRewriter, RewriteResult
from rtr_copilot.rag.rewrite_llm import (
    AnthropicRewriteClient,
    ExternalLLMRewriter,
    OpenAIRewriteClient,
    _clear_runtime_rewriter_cache,
    _parse_rewrite,
    build_rewriter,
    get_runtime_rewriter,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "postgres_dsn": "postgresql://user:password@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "local",
        "s3_secret_key": "local-secret",
        "s3_bucket": "rtr-test",
        "app_env": "development",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _transport(payload: object, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


class _FakeClient:
    def __init__(
        self,
        name: str,
        *,
        result: RewriteResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._result = result or RewriteResult()
        self._error = error
        self.calls = 0

    async def propose(
        self, question: str, catalog: list[str], collections: list[str],
    ) -> RewriteResult:
        del question, catalog, collections
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


class _HangingClient(_FakeClient):
    async def propose(
        self, question: str, catalog: list[str], collections: list[str],
    ) -> RewriteResult:
        del question, catalog, collections
        self.calls += 1
        await asyncio.sleep(10)
        raise AssertionError("orchestration timeout failed")


class _CatalogClient(_FakeClient):
    def __init__(self) -> None:
        super().__init__("catalog")
        self.catalogs: list[list[str]] = []
        self.collection_catalogs: list[list[str]] = []

    async def propose(
        self, question: str, catalog: list[str], collections: list[str],
    ) -> RewriteResult:
        del question
        self.calls += 1
        self.catalogs.append(catalog)
        self.collection_catalogs.append(collections)
        return RewriteResult()


class _FakeBreaker:
    def __init__(self, admit: bool) -> None:
        self.admit = admit
        self.failures = 0
        self.successes = 0

    async def allow(self) -> tuple[bool, int]:
        return self.admit, 0

    async def record_failure(self) -> int:
        self.failures += 1
        return self.failures

    async def record_success(self) -> None:
        self.successes += 1


class TestParse:
    def test_valid_json(self) -> None:
        result = _parse_rewrite(
            '{"entities": ["HERA"], "expansions": ["payload"], '
            '"standalone_question": "HERA payload là gì?"}',
        )
        assert result.entities == ["HERA"]
        assert result.expansions == ["payload"]
        assert result.standalone_question == "HERA payload là gì?"

    def test_json_embedded_in_prose(self) -> None:
        result = _parse_rewrite('Here you go:\n{"entities": ["VEGA"]}\nthanks')
        assert result.entities == ["VEGA"]

    def test_garbage_is_empty(self) -> None:
        assert _parse_rewrite("not json at all").entities == []
        assert _parse_rewrite("").expansions == []

    def test_non_string_items_filtered(self) -> None:
        result = _parse_rewrite('{"entities": ["HERA", 5, null], "expansions": [1]}')
        assert result.entities == ["HERA"]
        assert result.expansions == []


class TestFallbackChain:
    def test_primary_success_short_circuits(self) -> None:
        primary = _FakeClient("anthropic", result=RewriteResult(entities=["HERA"]))
        fallback = _FakeClient("openai", result=RewriteResult(entities=["VEGA"]))
        rewriter = ExternalLLMRewriter([primary, fallback], timeout=1)
        out = asyncio.run(rewriter.rewrite("hr"))
        assert out.entities == ["HERA"]
        assert primary.calls == 1 and fallback.calls == 0
        assert rewriter.calls == 1

    def test_request_usage_is_task_local(self) -> None:
        rewriter = ExternalLLMRewriter([_FakeClient("openai")], timeout=1)

        async def run_one() -> int:
            rewriter.begin_request_usage()
            task = asyncio.current_task()
            await rewriter.rewrite(f"question-{id(task)}")
            return rewriter.request_usage()

        async def run_both() -> list[int]:
            return list(await asyncio.gather(run_one(), run_one()))

        assert asyncio.run(run_both()) == [1, 1]
        assert rewriter.calls == 2

    def test_identical_plan_uses_digest_cache_without_provider_call(self) -> None:
        client = _FakeClient("openai", result=RewriteResult(entities=["HERA"]))
        rewriter = ExternalLLMRewriter(
            [client], timeout=1, cache_ttl_seconds=60, cache_max_entries=4,
        )
        async def exercise() -> tuple[RewriteResult, RewriteResult, int, int, int]:
            rewriter.begin_request_usage()
            first = await rewriter.rewrite("HERA payload")
            first_calls = rewriter.request_usage()
            rewriter.begin_request_usage()
            second = await rewriter.rewrite("HERA payload")
            return (
                first,
                second,
                first_calls,
                rewriter.request_usage(),
                rewriter.request_provider_usage().calls,
            )

        first, second, first_calls, second_calls, second_provider_calls = (
            asyncio.run(exercise())
        )
        assert first == second
        assert first_calls == 1
        assert client.calls == 1
        assert rewriter.calls == 1
        assert second_calls == 0
        assert second_provider_calls == 0
        assert rewriter.cache_entry_count == 1

    def test_warm_cache_is_task_local_under_concurrency(self) -> None:
        client = _FakeClient("openai", result=RewriteResult(entities=["HERA"]))
        rewriter = ExternalLLMRewriter(
            [client], timeout=1, cache_ttl_seconds=60, cache_max_entries=4,
        )

        async def exercise() -> list[int]:
            await rewriter.rewrite("HERA endurance")

            async def read_warm_plan() -> int:
                rewriter.begin_request_usage()
                await rewriter.rewrite("HERA endurance")
                return rewriter.request_usage()

            return list(await asyncio.gather(read_warm_plan(), read_warm_plan()))

        assert asyncio.run(exercise()) == [0, 0]
        assert client.calls == 1
        assert rewriter.calls == 1

    def test_cache_metrics_are_content_free_and_eviction_is_observable(self) -> None:
        miss_before = m.QUERY_REWRITER_CACHE_MISSES._value.get()
        hit_before = m.QUERY_REWRITER_CACHE_HITS._value.get()
        eviction_before = m.QUERY_REWRITER_CACHE_EVICTIONS._value.get()
        client = _FakeClient("openai")
        rewriter = ExternalLLMRewriter(
            [client], timeout=1, cache_ttl_seconds=60, cache_max_entries=1,
        )

        async def exercise() -> None:
            await rewriter.rewrite("first governed question")
            await rewriter.rewrite("first governed question")
            await rewriter.rewrite("second governed question")

        asyncio.run(exercise())
        assert m.QUERY_REWRITER_CACHE_MISSES._value.get() == miss_before + 2
        assert m.QUERY_REWRITER_CACHE_HITS._value.get() == hit_before + 1
        assert m.QUERY_REWRITER_CACHE_EVICTIONS._value.get() == eviction_before + 1
        assert rewriter.cache_entry_count == 1
        for metric in (
            m.QUERY_REWRITER_CACHE_HITS,
            m.QUERY_REWRITER_CACHE_MISSES,
            m.QUERY_REWRITER_CACHE_EVICTIONS,
            m.QUERY_REWRITER_CACHE_ENTRIES,
        ):
            assert metric._labelnames == ()

    def test_primary_failure_falls_to_secondary(self) -> None:
        primary = _FakeClient("anthropic", error=RuntimeError("boom"))
        fallback = _FakeClient("openai", result=RewriteResult(entities=["VEGA"]))
        rewriter = ExternalLLMRewriter([primary, fallback], timeout=1)
        out = asyncio.run(rewriter.rewrite("vega"))
        assert out.entities == ["VEGA"]
        assert primary.calls == 1 and fallback.calls == 1
        assert rewriter.calls == 2
        assert rewriter.total_timeout == pytest.approx(2.1)

    def test_hanging_primary_is_bounded_and_falls_to_secondary(self) -> None:
        primary = _HangingClient("anthropic")
        fallback = _FakeClient("openai", result=RewriteResult(entities=["VEGA"]))
        rewriter = ExternalLLMRewriter([primary, fallback], timeout=0.01)
        out = asyncio.run(rewriter.rewrite("vega"))
        assert out.entities == ["VEGA"]
        assert rewriter.calls == 2

    def test_all_fail_raises(self) -> None:
        primary = _FakeClient("anthropic", error=RuntimeError("boom"))
        fallback = _FakeClient("openai", error=RuntimeError("boom2"))
        rewriter = ExternalLLMRewriter([primary, fallback], timeout=1)
        with pytest.raises(ProviderUnavailable):
            asyncio.run(rewriter.rewrite("q"))

    def test_breaker_open_skips_provider(self) -> None:
        breakers = {"anthropic": _FakeBreaker(admit=False),
                    "openai": _FakeBreaker(admit=True)}
        primary = _FakeClient("anthropic", result=RewriteResult(entities=["HERA"]))
        fallback = _FakeClient("openai", result=RewriteResult(entities=["VEGA"]))
        rewriter = ExternalLLMRewriter(
            [primary, fallback], timeout=1,
            breaker_factory=lambda name: breakers[name],
        )
        out = asyncio.run(rewriter.rewrite("q"))
        assert out.entities == ["VEGA"]
        assert primary.calls == 0 and fallback.calls == 1
        assert rewriter.calls == 1

    def test_breaker_records_failure_then_success(self) -> None:
        breakers = {"anthropic": _FakeBreaker(admit=True),
                    "openai": _FakeBreaker(admit=True)}
        primary = _FakeClient("anthropic", error=RuntimeError("boom"))
        fallback = _FakeClient("openai", result=RewriteResult(entities=["VEGA"]))
        rewriter = ExternalLLMRewriter(
            [primary, fallback], timeout=1,
            breaker_factory=lambda name: breakers[name],
        )
        asyncio.run(rewriter.rewrite("q"))
        assert breakers["anthropic"].failures == 1
        assert breakers["openai"].successes == 1

    def test_planner_receives_only_bounded_registry_candidates(self) -> None:
        client = _CatalogClient()
        rewriter = ExternalLLMRewriter([client], timeout=1, candidate_limit=3)
        asyncio.run(rewriter.rewrite("Omni là gì?"))
        assert client.catalogs == [["OmniSight"]]

        # Deliberately use tokens outside every governed surface. Natural
        # language such as "enterprise question" can legitimately become a
        # moderate candidate as the enterprise ontology grows.
        asyncio.run(rewriter.rewrite("zzzx qqqq"))
        assert client.catalogs[-1] == []


class TestRealClients:
    def test_anthropic_parses_messages_response(self) -> None:
        payload = {"content": [
            {"type": "text",
             "text": '{"entities": ["HERA"], "expansions": ["payload"]}'},
        ]}
        client = AnthropicRewriteClient(
            "key", "model", timeout=2, transport=_transport(payload),
        )
        out = asyncio.run(client.propose("hr payload", ["HERA", "VEGA"], []))
        assert out.entities == ["HERA"] and out.expansions == ["payload"]

    def test_openai_parses_responses_structured_output(self) -> None:
        payload = {
            "status": "completed",
            "usage": {
                "input_tokens": 80,
                "input_tokens_details": {"cached_tokens": 20},
                "output_tokens": 15,
                "output_tokens_details": {"reasoning_tokens": 5},
                "total_tokens": 95,
            },
            "output": [{"type": "message", "content": [{
                "type": "output_text",
                "text": '{"entities": ["VEGA"], "expansions": []}',
            }]}],
        }
        client = OpenAIRewriteClient(
            "key", "model", timeout=2, transport=_transport(payload),
        )
        async def propose_with_usage() -> tuple[RewriteResult, int]:
            out = await client.propose("vga", ["HERA", "VEGA"], [])
            return out, client.last_usage().total_tokens

        out, total_tokens = asyncio.run(propose_with_usage())
        assert out.entities == ["VEGA"]
        assert total_tokens == 95

    def test_http_error_raises(self) -> None:
        client = OpenAIRewriteClient(
            "key", "model", timeout=2, transport=_transport({}, status=500),
        )
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.propose("q", ["HERA"], []))


class TestBuildRewriter:
    def teardown_method(self) -> None:
        _clear_runtime_rewriter_cache()

    def test_disabled_returns_offline(self) -> None:
        assert isinstance(build_rewriter(_settings()), OfflineRewriter)

    def test_enabled_without_key_returns_offline(self) -> None:
        settings = _settings(rag_rewrite_enabled=True)
        assert isinstance(build_rewriter(settings), OfflineRewriter)

    def test_empty_compose_key_returns_offline(self) -> None:
        settings = _settings(
            rag_rewrite_enabled=True,
            rag_external_classification_allowlist="internal",
            openai_api_key="",
        )
        assert isinstance(build_rewriter(settings), OfflineRewriter)

    def test_anthropic_only(self) -> None:
        settings = _settings(
            rag_rewrite_enabled=True,
            rag_external_classification_allowlist="internal",
            anthropic_api_key="k",
        )
        rewriter = build_rewriter(settings)
        assert isinstance(rewriter, ExternalLLMRewriter)
        assert [client.name for client in rewriter.clients] == ["anthropic"]

    def test_both_keys_openai_quality_primary(self) -> None:
        settings = _settings(
            rag_rewrite_enabled=True,
            rag_external_classification_allowlist="internal",
            anthropic_api_key="k1",
            openai_api_key="k2",
        )
        rewriter = build_rewriter(settings)
        assert isinstance(rewriter, ExternalLLMRewriter)
        assert [client.name for client in rewriter.clients] == ["openai", "anthropic"]

    def test_key_without_external_allowlist_fails_closed(self) -> None:
        settings = _settings(
            rag_rewrite_enabled=True,
            anthropic_api_key="k",
        )
        assert isinstance(build_rewriter(settings), OfflineRewriter)

    def test_runtime_external_rewriter_is_reused_for_same_contract(self) -> None:
        settings = _settings(
            rag_rewrite_enabled=True,
            rag_external_classification_allowlist="internal",
            openai_api_key="key-a",
        )
        first = get_runtime_rewriter(settings, load_ontology())
        second = get_runtime_rewriter(settings, load_ontology())
        assert isinstance(first, ExternalLLMRewriter)
        assert second is first

    def test_runtime_rewriter_changes_with_relevant_configuration(self) -> None:
        common = {
            "rag_rewrite_enabled": True,
            "rag_external_classification_allowlist": "internal",
            "openai_api_key": "key-a",
        }
        first = get_runtime_rewriter(_settings(**common), load_ontology())
        second = get_runtime_rewriter(
            _settings(**common, rag_rewrite_openai_model="different-model"),
            load_ontology(),
        )
        assert isinstance(first, ExternalLLMRewriter)
        assert isinstance(second, ExternalLLMRewriter)
        assert second is not first

    def test_runtime_offline_rewriter_is_not_shared(self) -> None:
        settings = _settings()
        first = get_runtime_rewriter(settings, load_ontology())
        second = get_runtime_rewriter(settings, load_ontology())
        assert isinstance(first, OfflineRewriter)
        assert isinstance(second, OfflineRewriter)
        assert second is not first
