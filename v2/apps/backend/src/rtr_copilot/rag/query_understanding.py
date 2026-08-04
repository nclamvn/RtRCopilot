"""Deterministic query understanding — TIP-014 Phase 1 + Phase 2 skeleton.

Phase 1 (active, deterministic): resolve RtR product-name variants / typos /
abbreviations to canonical product names and augment the *retrieval* query.

Phase 2 (skeleton, provider-gated): a ``QueryRewriter`` seam so a real LLM can
rewrite/expand the question BEFORE retrieval — behind two hard guards:
  * every entity the rewriter proposes is validated against the curated
    registry; an unregistered entity (e.g. an LLM hallucinating
    "human resources" from "hr") is dropped and never reaches retrieval;
  * any rewriter failure/timeout falls back to the deterministic Phase 1 path,
    so the query is never lost.

The hard line (TIP-014): this layer shapes ONLY the string handed to retrieval.
It is deterministic by default (the shipped rewriter is offline, no LLM/network),
can only ever emit a canonical from ``product_aliases.PRODUCT_ALIASES``, and
never touches honest-null, citations, ranking, DLP or grounding. Augmentation
helps retrieval FIND real evidence; it can never fabricate it.
"""
from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass, field
from typing import Protocol

from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.product_aliases import PRODUCT_ALIASES

# A single unmatched token is fuzzy-matched to a canonical only above this
# ratio; deliberately strict so near-words ("mega" vs "vega") never resolve.
FUZZY_THRESHOLD = 0.86
# Tokens shorter than this are never fuzzy-matched (abbreviations like "hr"
# resolve via the explicit table, never by similarity).
MIN_FUZZY_LEN = 4
# Bounds on LLM-proposed expansion terms (blast-radius cap; they only ADD
# lexical/vector search terms, never grounding).
MAX_EXPANSIONS = 5
MAX_EXPANSION_LEN = 40
# Fallback timeout for a rewriter call before the deterministic path takes over.
DEFAULT_REWRITE_TIMEOUT = 2.0

CANONICALS: frozenset[str] = frozenset(PRODUCT_ALIASES)


def _build_index() -> tuple[dict[str, str], dict[str, str], int]:
    """Return (exact-key -> canonical, single-token-key -> canonical, max_tokens)."""
    exact: dict[str, str] = {}
    single: dict[str, str] = {}
    max_tokens = 1
    for canonical, variants in PRODUCT_ALIASES.items():
        for surface in (canonical, *variants):
            key = normalize_query(surface)
            if not key:
                continue
            exact.setdefault(key, canonical)
            parts = key.split()
            max_tokens = max(max_tokens, len(parts))
            if len(parts) == 1:
                single.setdefault(key, canonical)
    return exact, single, max_tokens


_EXACT, _SINGLE, _MAX_TOKENS = _build_index()


def resolve_entities(question: str) -> list[str]:
    """Canonical product names referenced by *question*, in order of appearance.

    Deterministic. Greedy longest n-gram exact match first (so "hera hub" ->
    HeraHub, not HERA), then a strict fuzzy fallback for single unmatched
    tokens. The result is always a subset of the curated canonical set.
    """
    tokens = normalize_query(question).split()
    resolved: list[str] = []
    seen: set[str] = set()
    index = 0
    count = len(tokens)
    while index < count:
        matched = False
        upper = min(_MAX_TOKENS, count - index)
        for size in range(upper, 0, -1):
            gram = " ".join(tokens[index:index + size])
            canonical = _EXACT.get(gram)
            if canonical is not None:
                if canonical not in seen:
                    seen.add(canonical)
                    resolved.append(canonical)
                index += size
                matched = True
                break
        if matched:
            continue
        token = tokens[index]
        if len(token) >= MIN_FUZZY_LEN:
            best_ratio = 0.0
            best_canonical: str | None = None
            for key, canonical in _SINGLE.items():
                if len(key) < MIN_FUZZY_LEN:
                    continue
                ratio = difflib.SequenceMatcher(None, token, key).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_canonical = canonical
            if (
                best_canonical is not None
                and best_ratio >= FUZZY_THRESHOLD
                and best_canonical not in seen
            ):
                seen.add(best_canonical)
                resolved.append(best_canonical)
        index += 1
    return resolved


def validate_entities(entities: list[str]) -> list[str]:
    """Anti-hallucination guard: keep only entities that ARE curated canonicals.

    Whatever a rewriter (LLM or otherwise) proposes, this drops anything outside
    ``PRODUCT_ALIASES`` — the resolver/rewriter can never inject an entity such
    as "human resources". Order preserved, de-duplicated.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for entity in entities:
        if entity in CANONICALS and entity not in seen:
            seen.add(entity)
            kept.append(entity)
    return kept


def _augment_with(
    question: str, entities: list[str], expansions: list[str],
) -> str:
    """Additive augmentation: append terms not already present (normalized)."""
    present = set(normalize_query(question).split())
    extra: list[str] = []
    for term in (*entities, *expansions):
        tokens = set(normalize_query(term).split())
        if tokens and not tokens <= present and term not in extra:
            extra.append(term)
    return f"{question} {' '.join(extra)}" if extra else question


def augment_query(question: str) -> str:
    """Question augmented with deterministically resolved canonical names.

    Additive: the original question text is preserved verbatim and a canonical
    is appended only when it is not already present — so typos/abbreviations
    ("hr", "hira", "vga") gain the real product name while an exact mention adds
    nothing. Returns the question unchanged when nothing new resolves. This is
    the deterministic Phase 1 path and the fallback for ``understand``.
    """
    return _augment_with(question, resolve_entities(question), [])


@dataclass(frozen=True)
class RewriteResult:
    """A rewriter's proposal. ``entities`` are validated against the registry;
    ``expansions`` are free-text search terms (bounded, additive only)."""

    entities: list[str] = field(default_factory=list)
    expansions: list[str] = field(default_factory=list)


class QueryRewriter(Protocol):
    """Phase 2 seam. A real LLM rewriter plugs in here (behind the provider
    circuit breaker + cost budget, mirroring ``AnswerService._call_provider``).
    The shipped default is offline + deterministic, so runtime behavior is
    unchanged until a provider is injected."""

    calls: int

    async def rewrite(self, question: str) -> RewriteResult: ...


class OfflineRewriter:
    """Deterministic, no LLM/network. Also the fallback path for ``understand``:
    it simply returns the Phase 1 resolution, so with no provider the pipeline
    behaves exactly as Phase 1."""

    calls = 0

    async def rewrite(self, question: str) -> RewriteResult:
        return RewriteResult(entities=resolve_entities(question))


def _clean_expansions(expansions: list[str]) -> list[str]:
    cleaned: list[str] = []
    for term in expansions:
        stripped = term.strip()
        if stripped and len(stripped) <= MAX_EXPANSION_LEN:
            cleaned.append(stripped)
        if len(cleaned) >= MAX_EXPANSIONS:
            break
    return cleaned


async def understand(
    question: str,
    rewriter: QueryRewriter,
    *,
    timeout: float = DEFAULT_REWRITE_TIMEOUT,
) -> str:
    """Return the retrieval query for *question*.

    Always applies the deterministic Phase 1 resolution, then ADDS the rewriter's
    proposals on top: every proposed entity is validated against the registry
    (any unregistered one dropped), and bounded expansions are appended. So a
    weak or empty LLM response can never lose the reliable alias resolution, and
    no unregistered entity can ever reach retrieval. ANY rewriter failure/timeout
    falls back to the deterministic path alone. The original question is
    preserved; grounding is untouched.
    """
    deterministic = resolve_entities(question)
    try:
        result = await asyncio.wait_for(rewriter.rewrite(question), timeout)
    except Exception:  # noqa: BLE001 — any rewriter failure must fall back safely
        return _augment_with(question, deterministic, [])
    entities = validate_entities([*deterministic, *result.entities])
    expansions = _clean_expansions(result.expansions)
    return _augment_with(question, entities, expansions)
