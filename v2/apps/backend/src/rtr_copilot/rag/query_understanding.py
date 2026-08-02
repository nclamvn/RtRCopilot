"""Deterministic query understanding — TIP-014 Phase 1.

Resolves RtR product-name variants / typos / abbreviations to canonical product
names and augments the *retrieval* query with them.

Scope discipline (the hard line from TIP-014): this layer shapes ONLY the string
handed to retrieval. It is fully deterministic (no LLM, no network), and it can
only ever emit a canonical that already exists in the curator-owned table
(``product_aliases.PRODUCT_ALIASES``) — it cannot invent an entity. Honest-null,
citations, ranking, DLP and the grounding gate are all untouched: augmentation
can help retrieval FIND real evidence, never fabricate it. If nothing resolves,
the query is returned verbatim.
"""
from __future__ import annotations

import difflib

from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.product_aliases import PRODUCT_ALIASES

# A single unmatched token is fuzzy-matched to a canonical only above this
# ratio; deliberately strict so near-words ("mega" vs "vega") never resolve.
FUZZY_THRESHOLD = 0.86
# Tokens shorter than this are never fuzzy-matched (abbreviations like "hr"
# resolve via the explicit table, never by similarity).
MIN_FUZZY_LEN = 4


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


def augment_query(question: str) -> str:
    """Return *question* augmented with resolved canonical names, for retrieval.

    Additive: the original question text is preserved verbatim and a canonical
    surface is appended only when it is not already present (normalized) — so
    typos/abbreviations ("hr", "hira", "vga") gain the real product name while
    an exact mention adds nothing. Returns the question unchanged when nothing
    new resolves. This never removes user terms and never alters grounding.
    """
    canonicals = resolve_entities(question)
    if not canonicals:
        return question
    present = set(normalize_query(question).split())
    extra = [
        canonical for canonical in canonicals
        if not set(normalize_query(canonical).split()) <= present
    ]
    if not extra:
        return question
    return f"{question} {' '.join(extra)}"
