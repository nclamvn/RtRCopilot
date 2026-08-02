"""Hermetic tests for TIP-014 Phase 2b — LLM query rewrite.

No real network and no real keys. The two provider clients are exercised with
``httpx.MockTransport``; the fallback chain and factory use fakes. Proves:
Anthropic-primary/OpenAI-fallback ordering, breaker-open skip, both-fail raises
(so understand() falls back), tolerant JSON parsing, and the enable/keys gating.
"""
import asyncio

import httpx
import pytest

from rtr_copilot.config import Settings
from rtr_copilot.limits.breaker import ProviderUnavailable
from rtr_copilot.rag.query_understanding import OfflineRewriter, RewriteResult
from rtr_copilot.rag.rewrite_llm import (
    AnthropicRewriteClient,
    ExternalLLMRewriter,
    OpenAIRewriteClient,
    _parse_rewrite,
    build_rewriter,
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

    async def propose(self, question: str, catalog: list[str]) -> RewriteResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


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
        result = _parse_rewrite('{"entities": ["HERA"], "expansions": ["payload"]}')
        assert result.entities == ["HERA"]
        assert result.expansions == ["payload"]

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

    def test_primary_failure_falls_to_secondary(self) -> None:
        primary = _FakeClient("anthropic", error=RuntimeError("boom"))
        fallback = _FakeClient("openai", result=RewriteResult(entities=["VEGA"]))
        rewriter = ExternalLLMRewriter([primary, fallback], timeout=1)
        out = asyncio.run(rewriter.rewrite("vega"))
        assert out.entities == ["VEGA"]
        assert primary.calls == 1 and fallback.calls == 1

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


class TestRealClients:
    def test_anthropic_parses_messages_response(self) -> None:
        payload = {"content": [
            {"type": "text",
             "text": '{"entities": ["HERA"], "expansions": ["payload"]}'},
        ]}
        client = AnthropicRewriteClient(
            "key", "model", timeout=2, transport=_transport(payload),
        )
        out = asyncio.run(client.propose("hr payload", ["HERA", "VEGA"]))
        assert out.entities == ["HERA"] and out.expansions == ["payload"]

    def test_openai_parses_chat_response(self) -> None:
        payload = {"choices": [
            {"message": {"content": '{"entities": ["VEGA"], "expansions": []}'}},
        ]}
        client = OpenAIRewriteClient(
            "key", "model", timeout=2, transport=_transport(payload),
        )
        out = asyncio.run(client.propose("vga", ["HERA", "VEGA"]))
        assert out.entities == ["VEGA"]

    def test_http_error_raises(self) -> None:
        client = OpenAIRewriteClient(
            "key", "model", timeout=2, transport=_transport({}, status=500),
        )
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.propose("q", ["HERA"]))


class TestBuildRewriter:
    def test_disabled_returns_offline(self) -> None:
        assert isinstance(build_rewriter(_settings()), OfflineRewriter)

    def test_enabled_without_key_returns_offline(self) -> None:
        settings = _settings(rag_rewrite_enabled=True)
        assert isinstance(build_rewriter(settings), OfflineRewriter)

    def test_anthropic_only(self) -> None:
        settings = _settings(rag_rewrite_enabled=True, anthropic_api_key="k")
        rewriter = build_rewriter(settings)
        assert isinstance(rewriter, ExternalLLMRewriter)
        assert [client.name for client in rewriter.clients] == ["anthropic"]

    def test_both_keys_anthropic_first(self) -> None:
        settings = _settings(
            rag_rewrite_enabled=True,
            anthropic_api_key="k1",
            openai_api_key="k2",
        )
        rewriter = build_rewriter(settings)
        assert isinstance(rewriter, ExternalLLMRewriter)
        assert [client.name for client in rewriter.clients] == ["anthropic", "openai"]
