"""External LLM query rewriter — TIP-014 Phase 2b.

A real LLM proposes entities + expansion terms for a search query. Default
provider is **Anthropic**, with **automatic fallback to OpenAI** on any failure.
Every call is bounded by a timeout and a per-provider circuit breaker (mirroring
``AnswerService._guarded_generate``), and the whole thing sits behind the two
hard guards already in ``query_understanding.understand``:

  * proposed entities are validated against the curated registry (an LLM can
    never inject an entity that isn't a real RtR product);
  * if BOTH providers fail, ``ExternalLLMRewriter.rewrite`` raises, and
    ``understand`` falls back to the deterministic Phase 1 path.

Keys are read from the environment (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``)
via ``Settings`` — never hard-coded, never committed. The rewriter shapes ONLY
the retrieval query; honest-null, citations, ranking, DLP and grounding are
untouched.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from redis.exceptions import RedisError

from rtr_copilot.config import Settings
from rtr_copilot.limits.breaker import CircuitBreaker, ProviderUnavailable
from rtr_copilot.limits.redis_support import open_redis
from rtr_copilot.rag.query_understanding import (
    CANONICALS,
    OfflineRewriter,
    QueryRewriter,
    RewriteResult,
)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
REWRITE_MAX_TOKENS = 256


def _system_prompt(catalog: list[str]) -> str:
    names = ", ".join(catalog)
    return (
        "You normalize a user's SEARCH QUERY for a retrieval system over "
        "Real-time Robotics (RtR) product facts. Do NOT answer the question. "
        "Return ONLY a JSON object with two keys: \"entities\" — a list whose "
        "items are product names chosen ONLY from this exact catalog, never "
        f"invented: [{names}] — and \"expansions\" — up to 5 short alternative "
        "search terms or synonyms. If no catalog product is referenced, return "
        "an empty entities list. Output JSON only, no prose."
    )


def _parse_rewrite(text: str) -> RewriteResult:
    """Best-effort parse of a model's JSON reply into a RewriteResult.

    Tolerant: unparseable output yields an empty result (understand() then keeps
    the deterministic resolution). Non-catalog entities are dropped downstream by
    ``validate_entities``.
    """
    payload: Any = None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            with contextlib.suppress(ValueError, TypeError):
                payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        return RewriteResult()
    entities = [item for item in payload.get("entities", []) if isinstance(item, str)]
    expansions = [item for item in payload.get("expansions", []) if isinstance(item, str)]
    return RewriteResult(entities=entities, expansions=expansions)


class RewriteClient(Protocol):
    name: str

    async def propose(self, question: str, catalog: list[str]) -> RewriteResult: ...


class AnthropicRewriteClient:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport

    async def propose(self, question: str, catalog: list[str]) -> RewriteResult:
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
        ) as client:
            response = await client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": REWRITE_MAX_TOKENS,
                    "temperature": 0,
                    "system": _system_prompt(catalog),
                    "messages": [{"role": "user", "content": question}],
                },
            )
            response.raise_for_status()
            blocks = response.json()["content"]
        text = "".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        )
        return _parse_rewrite(text)


class OpenAIRewriteClient:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport

    async def propose(self, question: str, catalog: list[str]) -> RewriteResult:
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
        ) as client:
            response = await client.post(
                OPENAI_URL,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": REWRITE_MAX_TOKENS,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": _system_prompt(catalog)},
                        {"role": "user", "content": question},
                    ],
                },
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
        return _parse_rewrite(text)


class ExternalLLMRewriter:
    """Try each client in order (Anthropic then OpenAI) behind a per-provider
    breaker; the first success wins, and if all fail we raise so ``understand``
    falls back to the deterministic path."""

    def __init__(
        self,
        clients: list[RewriteClient],
        *,
        timeout: float,
        breaker_factory: Callable[[str], CircuitBreaker] | None = None,
    ) -> None:
        self.clients = clients
        self.calls = 0
        self._timeout = timeout
        # The outer query-understanding guard must leave enough time for every
        # configured provider to receive its own bounded attempt.
        self.total_timeout = timeout * max(1, len(clients)) + 0.1
        self._breaker_factory = breaker_factory

    async def rewrite(self, question: str) -> RewriteResult:
        catalog = sorted(CANONICALS)
        for client in self.clients:
            breaker = (
                self._breaker_factory(client.name)
                if self._breaker_factory is not None
                else None
            )
            if breaker is not None:
                try:
                    admitted, _ = await breaker.allow()
                except RedisError:
                    admitted = True  # limiter outage must never block rewrite
                if not admitted:
                    continue
            try:
                self.calls += 1
                async with asyncio.timeout(self._timeout):
                    result = await client.propose(question, catalog)
            except Exception:  # noqa: BLE001 — any provider failure -> next/fallback
                if breaker is not None:
                    with contextlib.suppress(RedisError):
                        await breaker.record_failure()
                continue
            if breaker is not None:
                with contextlib.suppress(RedisError):
                    await breaker.record_success()
            return result
        raise ProviderUnavailable("llm_rewrite", retry_after=0)


def build_rewriter(settings: Settings) -> QueryRewriter:
    """Choose the rewriter from settings.

    Returns an ``ExternalLLMRewriter`` (Anthropic primary, OpenAI fallback) when
    query rewrite is enabled and at least one API key is present; otherwise the
    deterministic ``OfflineRewriter`` (so behavior is unchanged by default).
    """
    if not settings.rag_rewrite_enabled:
        return OfflineRewriter()
    # A rewrite sends the user's question to an external provider.  Require an
    # explicit classification export decision in addition to the feature flag
    # and credential: keys alone are never authorization to export data.
    external_allowlist = {
        item.strip()
        for item in settings.rag_external_classification_allowlist.split(",")
        if item.strip()
    }
    if "internal" not in external_allowlist:
        return OfflineRewriter()
    clients: list[RewriteClient] = []
    if settings.anthropic_api_key is not None:
        clients.append(AnthropicRewriteClient(
            settings.anthropic_api_key.get_secret_value(),
            settings.rag_rewrite_anthropic_model,
            timeout=settings.rag_rewrite_timeout_seconds,
        ))
    if settings.openai_api_key is not None:
        clients.append(OpenAIRewriteClient(
            settings.openai_api_key.get_secret_value(),
            settings.rag_rewrite_openai_model,
            timeout=settings.rag_rewrite_timeout_seconds,
        ))
    if not clients:
        return OfflineRewriter()

    def breaker_factory(name: str) -> CircuitBreaker:
        return CircuitBreaker(
            open_redis(settings),
            f"rewrite:{name}",
            threshold=settings.limits_breaker_failure_threshold,
            cooldown_seconds=settings.limits_breaker_cooldown_seconds,
        )

    return ExternalLLMRewriter(
        clients,
        timeout=settings.rag_rewrite_timeout_seconds,
        breaker_factory=breaker_factory,
    )
