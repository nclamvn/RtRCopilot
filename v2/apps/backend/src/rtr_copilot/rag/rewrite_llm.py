"""External enterprise query planner — TIP-024.7.

The quality-primary OpenAI route runs first, with an optional configured
Anthropic fallback.  Every call is timeout- and breaker-bounded.  The model may
interpret wording and propose search expansions, but entity choices are limited
to a small ontology-derived candidate catalog and validated again by the caller.
If all providers fail, the immutable query plan falls back deterministically.

This is domain-agnostic: the same planner can normalize products, policies,
projects, customers and future entity types without code changes.  It never
answers the question and never bypasses DLP, authorization, evidence selection,
honest-null, citations or final grounding verification.
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
from rtr_copilot.rag.ontology import EnterpriseOntology, load_ontology
from rtr_copilot.rag.query_understanding import (
    OfflineRewriter,
    QueryRewriter,
    RewriteResult,
)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/responses"
REWRITE_MAX_TOKENS = 256
REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "expansions": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["entities", "expansions"],
    "additionalProperties": False,
}


def _system_prompt(catalog: list[str]) -> str:
    names = ", ".join(catalog)
    return (
        "You normalize a user's SEARCH QUERY for a retrieval system over "
        "authorized enterprise knowledge. Do NOT answer the question. "
        "Return ONLY a JSON object with two keys: \"entities\" — a list whose "
        "items are entity names chosen ONLY from this exact candidate catalog, never "
        f"invented: [{names}] — and \"expansions\" — up to 5 short alternative "
        "search terms or synonyms. If no catalog entity is referenced, return "
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
                    "store": False,
                    "reasoning": {"effort": "medium"},
                    "max_output_tokens": REWRITE_MAX_TOKENS,
                    "instructions": _system_prompt(catalog),
                    "input": question,
                    "text": {"format": {
                        "type": "json_schema",
                        "name": "rtr_query_plan",
                        "strict": True,
                        "schema": REWRITE_SCHEMA,
                    }},
                },
            )
            response.raise_for_status()
            body = response.json()
        if body.get("status") != "completed":
            raise ValueError("openai_rewrite_incomplete")
        text = ""
        for item in body.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for block in item.get("content", []):
                if isinstance(block, dict) and block.get("type") == "output_text":
                    text = str(block.get("text", ""))
                    break
        if not text:
            raise ValueError("openai_rewrite_text_missing")
        return _parse_rewrite(text)


class ExternalLLMRewriter:
    """Try configured clients in order behind one breaker per provider.

    The builder places OpenAI first and Anthropic second.  The first valid
    result wins; if every provider fails, the query planner performs its
    deterministic fallback.
    """

    external = True

    def __init__(
        self,
        clients: list[RewriteClient],
        *,
        timeout: float,
        breaker_factory: Callable[[str], CircuitBreaker] | None = None,
        registry: EnterpriseOntology | None = None,
        candidate_limit: int = 16,
    ) -> None:
        self.clients = clients
        self.calls = 0
        self._timeout = timeout
        # The outer query-understanding guard must leave enough time for every
        # configured provider to receive its own bounded attempt.
        self.total_timeout = timeout * max(1, len(clients)) + 0.1
        self._breaker_factory = breaker_factory
        self._registry = registry or load_ontology()
        self._candidate_limit = candidate_limit

    async def rewrite(self, question: str) -> RewriteResult:
        catalog = self._registry.candidate_catalog(
            question,
            limit=self._candidate_limit,
        )
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


def build_rewriter(
    settings: Settings,
    registry: EnterpriseOntology | None = None,
) -> QueryRewriter:
    """Choose the rewriter from settings.

    Returns an ``ExternalLLMRewriter`` (OpenAI quality-primary, Anthropic
    fallback) when query planning is enabled, export policy permits internal
    content and at least one API key is present. Otherwise it returns the
    deterministic ``OfflineRewriter``.
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
    if settings.openai_api_key is not None:
        clients.append(OpenAIRewriteClient(
            settings.openai_api_key.get_secret_value(),
            settings.rag_rewrite_openai_model,
            timeout=settings.rag_rewrite_timeout_seconds,
        ))
    if settings.anthropic_api_key is not None:
        clients.append(AnthropicRewriteClient(
            settings.anthropic_api_key.get_secret_value(),
            settings.rag_rewrite_anthropic_model,
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
        registry=registry,
        candidate_limit=settings.rag_query_candidate_limit,
    )
