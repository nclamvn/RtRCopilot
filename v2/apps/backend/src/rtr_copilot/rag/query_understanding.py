"""Enterprise query intelligence and trust contract — TIP-024.7.

Every Ask produces one immutable ``QueryPlan`` shared by retrieval, evidence
selection, answer verification and audit.  Entity resolution is driven by a
domain-agnostic, provenance-bound ontology rather than product-specific code.
An optional external planner may interpret incomplete wording, but it can only
confirm bounded registry candidates; it cannot invent an entity or evidence.

The ontology is an accelerator, not a whitelist for company knowledge.  A
normal question with no registered entity remains open and proceeds through
retrieval and grounding.  Only an actual alias collision, ambiguous safe-fuzzy
match, or partial registered name requires clarification.  Planner failure
falls back deterministically, and every factual answer still requires current,
authorized evidence and citation verification.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Literal, Protocol

from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.ontology import EnterpriseOntology, OntologyMatch, load_ontology

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

CANONICALS: frozenset[str] = load_ontology().canonical_names()

QueryIntent = Literal[
    "definition", "comparison", "procedure", "summarization", "analysis", "lookup"
]
QueryResolutionState = Literal["resolved", "open", "clarification_required"]

_DEFINITION_PATTERNS = (
    "la gi", "what is", "define", "definition", "gioi thieu", "tong quan",
)
_COMPARISON_PATTERNS = ("so sanh", "khac nhau", "versus", " vs ", "compare")
_PROCEDURE_PATTERNS = (
    "lam sao", "nhu the nao", "quy trinh", "cac buoc", "how to", "procedure",
)
_SUMMARY_PATTERNS = ("tom tat", "tong hop", "summary", "summarize")
_ANALYSIS_PATTERNS = ("phan tich", "danh gia", "tai sao", "analysis", "evaluate")


def classify_intent(question: str) -> QueryIntent:
    normalized = normalize_query(question)
    padded = f" {normalized} "
    if any(pattern in normalized for pattern in _DEFINITION_PATTERNS):
        return "definition"
    if any(pattern in padded for pattern in _COMPARISON_PATTERNS):
        return "comparison"
    if any(pattern in normalized for pattern in _PROCEDURE_PATTERNS):
        return "procedure"
    if any(pattern in normalized for pattern in _SUMMARY_PATTERNS):
        return "summarization"
    if any(pattern in normalized for pattern in _ANALYSIS_PATTERNS):
        return "analysis"
    return "lookup"


def resolve_entities(
    question: str,
    registry: EnterpriseOntology | None = None,
) -> list[str]:
    """Canonical ontology entities referenced by *question*, in question order.

    Deterministic. Greedy longest n-gram exact match first (so "hera hub" ->
    HeraHub, not HERA), then a strict fuzzy fallback for single unmatched
    tokens. The result is always a subset of the curated canonical set.
    """
    ontology = registry or load_ontology()
    exact = ontology.exact_matches(question)
    if exact:
        by_surface: dict[str, list[OntologyMatch]] = {}
        for match in exact:
            by_surface.setdefault(match.matched_surface, []).append(match)
        # A colliding exact alias is ambiguous by definition.  Never preserve
        # the old setdefault/first-match behavior.
        if any(len(items) > 1 for items in by_surface.values()):
            return []
        return [match.canonical_name for match in exact]
    fuzzy = ontology.fuzzy_matches(
        question,
        threshold=FUZZY_THRESHOLD,
    )
    return [fuzzy[0].canonical_name] if len(fuzzy) == 1 else []


def validate_entities(
    entities: list[str],
    registry: EnterpriseOntology | None = None,
    *,
    allowed: set[str] | None = None,
) -> list[str]:
    """Anti-hallucination guard: keep only entities that ARE curated canonicals.

    Whatever a rewriter (LLM or otherwise) proposes, this drops anything outside
    the governed enterprise ontology. Order preserved, de-duplicated.
    """
    canonicals = (registry or load_ontology()).canonical_names()
    seen: set[str] = set()
    kept: list[str] = []
    for entity in entities:
        if (
            entity in canonicals
            and (allowed is None or entity in allowed)
            and entity not in seen
        ):
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


def augment_query(
    question: str,
    registry: EnterpriseOntology | None = None,
) -> str:
    """Question augmented with deterministically resolved canonical names.

    Additive: the original question text is preserved verbatim and a canonical
    is appended only when it is not already present — so typos/abbreviations
    ("hr", "hira", "vga") gain the real product name while an exact mention adds
    nothing. Returns the question unchanged when nothing new resolves. This is
    the deterministic Phase 1 path and the fallback for ``understand``.
    """
    return _augment_with(question, resolve_entities(question, registry), [])


@dataclass(frozen=True)
class QueryPlan:
    normalized: str
    terms: tuple[str, ...]
    intent: QueryIntent
    entities: tuple[str, ...]
    entity_ids: tuple[str, ...]
    candidates: tuple[OntologyMatch, ...]
    resolution_state: QueryResolutionState
    retrieval_query: str
    expansions: tuple[str, ...]
    planner_source: Literal["deterministic", "external", "fallback"]
    ontology_digest: str

    def audit_metadata(self) -> dict[str, object]:
        """Bounded non-plaintext metadata safe for answer-run audit records."""
        payload: dict[str, object] = {
            "intent": self.intent,
            "resolution_state": self.resolution_state,
            "entity_count": len(self.entities),
            "candidate_count": len(self.candidates),
            "expansion_count": len(self.expansions),
            "planner_source": self.planner_source,
            "ontology_digest": self.ontology_digest,
            "query_digest": hashlib.sha256(self.normalized.encode()).hexdigest(),
            "entity_set_digest": hashlib.sha256(
                "\n".join(sorted(self.entity_ids)).encode(),
            ).hexdigest(),
            "candidate_set_digest": hashlib.sha256(
                "\n".join(sorted(item.entity_id for item in self.candidates)).encode(),
            ).hexdigest(),
            "expansion_set_digest": hashlib.sha256(
                "\n".join(sorted(self.expansions)).encode(),
            ).hexdigest(),
        }
        payload["plan_digest"] = hashlib.sha256(
            repr(sorted(payload.items())).encode(),
        ).hexdigest()
        return payload


@dataclass(frozen=True)
class RewriteResult:
    """A rewriter's proposal. ``entities`` are validated against the registry;
    ``expansions`` are free-text search terms (bounded, additive only)."""

    entities: list[str] = field(default_factory=list)
    expansions: list[str] = field(default_factory=list)


class QueryRewriter(Protocol):
    """Optional semantic-planner seam behind timeout, breaker and cost gates."""

    calls: int
    external: bool

    async def rewrite(self, question: str) -> RewriteResult: ...


class OfflineRewriter:
    """Deterministic, no-network planner and external-provider fallback."""

    calls = 0
    external = False

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
    return (await plan_query(question, rewriter, timeout=timeout)).retrieval_query


async def plan_query(
    question: str,
    rewriter: QueryRewriter,
    *,
    registry: EnterpriseOntology | None = None,
    timeout: float = DEFAULT_REWRITE_TIMEOUT,
    candidate_limit: int = 16,
) -> QueryPlan:
    """Build the immutable semantic contract consumed by every trust stage."""
    ontology = registry or load_ontology()
    normalized = normalize_query(question)
    deterministic = resolve_entities(question, ontology)
    candidates = ontology.candidate_matches(question, limit=candidate_limit)
    candidate_names = {item.canonical_name for item in candidates}
    external = bool(getattr(rewriter, "external", True))
    planner_source: Literal["deterministic", "external", "fallback"] = (
        "external" if external else "deterministic"
    )
    result = RewriteResult()
    try:
        result = await asyncio.wait_for(rewriter.rewrite(question), timeout)
    except Exception:  # noqa: BLE001 — any rewriter failure must fall back safely
        planner_source = "fallback"
        external = False
    proposed = validate_entities(
        result.entities,
        ontology,
        allowed=candidate_names,
    )
    entities = list(deterministic)
    if not entities and external:
        entities = proposed
    elif entities and external and classify_intent(question) == "comparison":
        # Exact/safe-fuzzy deterministic identity is authoritative.  The LLM
        # cannot append a different catalog entity to a single-entity question.
        entities = validate_entities([*entities, *proposed], ontology)
    expansions = _clean_expansions(result.expansions)
    # A broad similarity candidate is context for an external planner, not
    # evidence that the user intended a registered entity.  Treating every
    # weak catalog resemblance as ambiguity would make the ontology a hidden
    # whitelist and block ordinary enterprise questions ("inspection",
    # "policy", project prose, etc.).  Fail closed only for a structural
    # entity signal: exact collision, unresolved safe-fuzzy match, or partial
    # registered name such as "Omni" / "Sight".
    ambiguous_candidates = bool(
        not entities
        and any(match.match_kind != "candidate" for match in candidates)
    )
    state: QueryResolutionState = (
        "clarification_required"
        if ambiguous_candidates
        else "resolved" if entities else "open"
    )
    entity_ids = tuple(
        ontology_entity.entity_id
        for entity in entities
        for ontology_entity in ontology.by_canonical.get(entity, ())
    )
    retrieval_query = _augment_with(question, entities, expansions)
    terms = tuple(dict.fromkeys(normalized.split()))
    return QueryPlan(
        normalized=normalized,
        terms=terms,
        intent=classify_intent(question),
        entities=tuple(entities),
        entity_ids=entity_ids,
        candidates=tuple(candidates),
        resolution_state=state,
        retrieval_query=retrieval_query,
        expansions=tuple(expansions),
        planner_source=planner_source,
        ontology_digest=ontology.digest,
    )
