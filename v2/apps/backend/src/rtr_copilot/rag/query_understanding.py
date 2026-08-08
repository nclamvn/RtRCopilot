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

from rtr_copilot.rag.adapters import QUERY_STOPWORDS, normalize_query
from rtr_copilot.rag.ontology import (
    EnterpriseOntology,
    OntologyMatch,
    OntologyProfileFacet,
    load_ontology,
)

# A single unmatched token is fuzzy-matched to a canonical only above this
# ratio; deliberately strict so near-words ("mega" vs "vega") never resolve.
FUZZY_THRESHOLD = 0.86
# Tokens shorter than this are never fuzzy-matched (abbreviations like "hr"
# resolve via the explicit table, never by similarity).
MIN_FUZZY_LEN = 4
# Bounds on LLM-proposed expansion terms (blast-radius cap; they only ADD
# lexical/vector search terms, never grounding).
MAX_EXPANSIONS = 5
MAX_EXPANSION_LEN = 80
MAX_RETRIEVAL_QUERIES = 6
MAX_STANDALONE_QUESTION_LEN = 4096
MAX_CONTEXT_MESSAGES = 4
MAX_CONTEXT_MESSAGE_CHARS = 600
# Fallback timeout for a rewriter call before the deterministic path takes over.
DEFAULT_REWRITE_TIMEOUT = 2.0

CANONICALS: frozenset[str] = load_ontology().canonical_names()

QueryIntent = Literal[
    "definition", "enumeration", "comparison", "procedure", "summarization",
    "analysis", "lookup",
]
QueryCompleteness = Literal["point", "bounded", "exhaustive"]
AnswerShape = Literal["direct", "list", "comparison", "steps", "summary", "analysis"]
QueryResolutionState = Literal[
    "resolved", "open", "clarification_required", "planning_required",
]

_DEFINITION_PATTERNS = (
    "la gi", "what is", "define", "definition", "gioi thieu", "tong quan",
)
_COMPARISON_PATTERNS = ("so sanh", "khac nhau", "versus", " vs ", "compare")
_PROCEDURE_PATTERNS = (
    "lam sao", "nhu the nao", "quy trinh", "cac buoc", "how to", "procedure",
    "to chuc sao", "duoc to chuc", "van hanh sao", "duoc van hanh",
    "hoat dong sao", "hoat dong nhu nao", "cau truc sao", "how does",
)
_SUMMARY_PATTERNS = ("tom tat", "tong hop", "summary", "summarize")
_ANALYSIS_PATTERNS = ("phan tich", "danh gia", "tai sao", "analysis", "evaluate")
_ENUMERATION_PATTERNS = (
    "danh sach", "danh muc", "liet ke", "tat ca", "toan bo", "day du",
    "co nhung", "gom nhung", "cac san pham", "cac chinh sach", "cac du an",
    "what are", "which are", "list all", "full list", "complete list",
)

_EXPLICIT_EXHAUSTIVE_PATTERNS = (
    "tat ca", "toan bo", "day du", "tron bo", "khong thieu", "liet ke het",
    "all products", "all policies", "all projects", "complete list",
    "full list", "exhaustive", "every item", "without omissions",
)

# ``đầy đủ`` describes both set coverage (``liệt kê đầy đủ sản phẩm``) and a
# single attribute (``tên pháp nhân đầy đủ``). Treating the latter as an
# exhaustive enumeration forced a clarification even though the ontology had
# an exact company match and an authoritative legal-name record.
_POINT_ATTRIBUTE_PATTERNS = (
    "ten day du", "ten phap nhan", "ten cong ty", "full name",
    "full legal name", "legal name", "dia chi day du", "full address",
    "email cty", "email cong ty", "mail cong ty", "company email",
    "so dien thoai cong ty", "company phone", "ma so doanh nghiep",
    "business registration number", "ma so thue", "tax code",
    "triet ly thuong hieu", "brand philosophy", "brand doctrine",
    "gio goi la gi", "ten moi", "renamed to", "former name",
    "tech stack", "technology stack", "cong nghe su dung",
)


def _is_point_attribute_request(normalized: str) -> bool:
    return any(pattern in normalized for pattern in _POINT_ATTRIBUTE_PATTERNS)


def _facet_matches_question(
    facet: OntologyProfileFacet,
    normalized_question: str,
) -> bool:
    """Match only curator-declared whole phrase aliases for point routing."""
    padded = f" {normalized_question} "
    return any(
        f" {normalized_alias} " in padded
        for alias in facet.query_aliases
        if (normalized_alias := normalize_query(alias))
    )


def requests_exhaustive(question: str) -> bool:
    """True only when the user explicitly requests certified completeness.

    Plural or list-shaped wording is intentionally insufficient. An internal
    employee asking "các sản phẩm là gì" wants a useful list, not an
    all-or-nothing refusal if one catalog attribute is unavailable.
    """
    normalized = normalize_query(question)
    if _is_point_attribute_request(normalized):
        return False
    return any(pattern in normalized for pattern in _EXPLICIT_EXHAUSTIVE_PATTERNS)


def classify_intent(question: str) -> QueryIntent:
    normalized = normalize_query(question)
    padded = f" {normalized} "
    # A request for one entity attribute remains a direct lookup even when the
    # Vietnamese surface ends in ``là gì``. Treating it as an entity definition
    # made the final relevance gate reject perfectly responsive answers such as
    # "Tên pháp nhân đầy đủ của ..." because the entity was not in the first
    # four words of the sentence.
    if _is_point_attribute_request(normalized):
        return "lookup"
    # Enumeration wins over definition: Vietnamese questions such as
    # "các sản phẩm ... là gì?" contain the definition phrase but request a
    # complete set, not one entity definition.
    if (
        not _is_point_attribute_request(normalized)
        and any(pattern in normalized for pattern in _ENUMERATION_PATTERNS)
    ):
        return "enumeration"
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
        # TIP-029.2: a weak alias ("hr" -> HERA) is trusted only when the
        # question carries content beyond the alias itself. A bare identity
        # question about the shorthand ("HR là gì?") stays unresolved here so
        # the planner can require clarification instead of the runtime
        # confidently defining the wrong thing (SAFE-007 false-grounded trap).
        weak_surfaces = {
            match.matched_surface
            for match in exact
            if match.match_kind == "weak"
        }
        if weak_surfaces and not _weak_alias_corroborated(
            question,
            weak_surfaces,
        ):
            exact = [
                match for match in exact if match.match_kind != "weak"
            ]
        if exact:
            return [match.canonical_name for match in exact]
    fuzzy = ontology.fuzzy_matches(
        question,
        threshold=FUZZY_THRESHOLD,
    )
    return [fuzzy[0].canonical_name] if len(fuzzy) == 1 else []


def _weak_alias_corroborated(
    question: str,
    weak_surfaces: set[str],
) -> bool:
    """Whether *question* has content beyond the weak alias + function words."""
    surface_tokens = {
        token for surface in weak_surfaces for token in surface.split()
    }
    return any(
        token not in surface_tokens
        and token not in QUERY_STOPWORDS
        and len(token) >= 3
        for token in normalize_query(question).split()
    )


def uncorroborated_weak_surfaces(
    question: str,
    registry: EnterpriseOntology | None = None,
) -> tuple[str, ...]:
    """Weak-alias surfaces present in *question* without corroborating context.

    Used by the planner as a governed ambiguity signal: the user typed a
    curated shorthand whose everyday meaning differs, and nothing else in the
    question disambiguates it.
    """
    ontology = registry or load_ontology()
    weak = {
        match.matched_surface
        for match in ontology.exact_matches(question)
        if match.match_kind == "weak"
    }
    if not weak or _weak_alias_corroborated(question, weak):
        return ()
    return tuple(sorted(weak))


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
    completeness: QueryCompleteness
    answer_shape: AnswerShape
    entities: tuple[str, ...]
    entity_ids: tuple[str, ...]
    entity_types: tuple[str, ...]
    definition_record_keys: tuple[str, ...]
    profile_facets: tuple[OntologyProfileFacet, ...]
    profile_record_keys: tuple[str, ...]
    candidates: tuple[OntologyMatch, ...]
    collection_candidate_ids: tuple[str, ...]
    collection_ids: tuple[str, ...]
    collection_record_keys: tuple[str, ...]
    required_items: tuple[str, ...]
    required_entities: tuple[str, ...]
    resolution_state: QueryResolutionState
    resolved_question: str
    context_message_count: int
    retrieval_query: str
    retrieval_queries: tuple[str, ...]
    expansions: tuple[str, ...]
    planner_source: Literal["deterministic", "external", "fallback"]
    ontology_digest: str

    def audit_metadata(self) -> dict[str, object]:
        """Bounded non-plaintext metadata safe for answer-run audit records."""
        payload: dict[str, object] = {
            "intent": self.intent,
            "completeness": self.completeness,
            "coverage_policy": self.coverage_policy,
            "answer_shape": self.answer_shape,
            "resolution_state": self.resolution_state,
            "entity_count": len(self.entities),
            "answer_entity_count": len(self.answer_entities),
            "required_item_count": len(self.required_items),
            "required_entity_count": len(self.required_entities),
            "definition_record_count": len(self.definition_record_keys),
            "profile_facet_count": len(self.profile_facets),
            "profile_record_count": len(self.profile_record_keys),
            "candidate_count": len(self.candidates),
            "collection_candidate_count": len(self.collection_candidate_ids),
            "collection_count": len(self.collection_ids),
            "collection_record_count": len(self.collection_record_keys),
            "retrieval_query_count": len(self.retrieval_queries),
            "expansion_count": len(self.expansions),
            "planner_source": self.planner_source,
            "context_message_count": self.context_message_count,
            "ontology_digest": self.ontology_digest,
            "query_digest": hashlib.sha256(self.normalized.encode()).hexdigest(),
            "resolved_question_digest": hashlib.sha256(
                normalize_query(self.resolved_question).encode(),
            ).hexdigest(),
            "entity_set_digest": hashlib.sha256(
                "\n".join(sorted(self.entity_ids)).encode(),
            ).hexdigest(),
            "definition_record_set_digest": hashlib.sha256(
                "\n".join(sorted(self.definition_record_keys)).encode(),
            ).hexdigest(),
            "profile_facet_set_digest": hashlib.sha256(
                "\n".join(sorted(facet.facet_id for facet in self.profile_facets)).encode(),
            ).hexdigest(),
            "profile_record_set_digest": hashlib.sha256(
                "\n".join(sorted(self.profile_record_keys)).encode(),
            ).hexdigest(),
            "candidate_set_digest": hashlib.sha256(
                "\n".join(sorted(item.entity_id for item in self.candidates)).encode(),
            ).hexdigest(),
            "collection_set_digest": hashlib.sha256(
                "\n".join(sorted(self.collection_ids)).encode(),
            ).hexdigest(),
            "required_item_set_digest": hashlib.sha256(
                "\n".join(sorted(normalize_query(item) for item in self.required_items)).encode(),
            ).hexdigest(),
            "expansion_set_digest": hashlib.sha256(
                "\n".join(sorted(self.expansions)).encode(),
            ).hexdigest(),
        }
        payload["plan_digest"] = hashlib.sha256(
            repr(sorted(payload.items())).encode(),
        ).hexdigest()
        return payload

    @property
    def requires_synthesis(self) -> bool:
        return self.intent in {
            "enumeration", "comparison", "procedure", "summarization", "analysis",
        } or self.completeness != "point" or self.answer_shape != "direct" \
            or bool(self.profile_facets)

    @property
    def coverage_policy(self) -> Literal["best_effort", "require_complete"]:
        return "require_complete" if self.completeness == "exhaustive" \
            else "best_effort"

    @property
    def retrieval_entities(self) -> tuple[str, ...]:
        return self.required_entities or self.entities

    @property
    def answer_entities(self) -> tuple[str, ...]:
        """Entities the rendered answer must name to prove question alignment.

        Retrieval keeps every resolved entity because an organization name is
        useful scope (``CRM của RtR``, ``dự án của công ty``).  Requiring that
        same owner/context entity to be repeated in every otherwise-correct
        answer caused false rejections: a CRM procedure that names CRM and all
        nine steps is still responsive even if it does not restate the legal
        company name.  Governed collection members remain explicit answer
        targets.  For ordinary multi-entity questions, drop company context
        only when at least one non-company subject exists; comparisons between
        companies therefore continue to require every company named.
        """
        if self.required_entities:
            return self.required_entities
        if len(self.entities) <= 1:
            return self.entities
        subject_entities = tuple(
            entity
            for entity, entity_type in zip(
                self.entities,
                self.entity_types,
                strict=True,
            )
            if entity_type != "company"
        )
        return subject_entities or self.entities


@dataclass(frozen=True)
class RewriteResult:
    """A rewriter's proposal. ``entities`` are validated against the registry;
    ``expansions`` are free-text search terms (bounded, additive only)."""

    entities: list[str] = field(default_factory=list)
    expansions: list[str] = field(default_factory=list)
    intent: QueryIntent | None = None
    completeness: QueryCompleteness | None = None
    answer_shape: AnswerShape | None = None
    collections: list[str] = field(default_factory=list)
    retrieval_queries: list[str] = field(default_factory=list)
    standalone_question: str = ""
    clarification_required: bool = False


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


def _clean_retrieval_queries(queries: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in queries:
        stripped = value.strip()
        if stripped and len(stripped) <= 240 and stripped not in cleaned:
            cleaned.append(stripped)
        if len(cleaned) >= MAX_RETRIEVAL_QUERIES:
            break
    return cleaned


def _planner_question(question: str, context: tuple[str, ...]) -> str:
    """Bounded context envelope used only by an eligible external planner.

    History is already owner-checked and DLP-inspected by ``AnswerService``.
    Delimiters tell the planner that history is reference context, never a
    source of enterprise truth or an instruction channel.
    """
    bounded = tuple(
        item.strip()[:MAX_CONTEXT_MESSAGE_CHARS]
        for item in context[-MAX_CONTEXT_MESSAGES:]
        if item.strip()
    )
    if not bounded:
        return question
    history = "\n".join(f"- {item}" for item in bounded)
    return (
        "<conversation_history>\n"
        f"{history}\n"
        "</conversation_history>\n"
        "<current_question>\n"
        f"{question}\n"
        "</current_question>"
    )


def _clean_standalone_question(value: str, fallback: str) -> str:
    cleaned = " ".join(value.replace("<", " ").replace(">", " ").split())
    if not cleaned or len(cleaned) > MAX_STANDALONE_QUESTION_LEN:
        return fallback
    return cleaned


def _default_contract(
    intent: QueryIntent,
    *,
    exhaustive: bool,
) -> tuple[QueryCompleteness, AnswerShape]:
    if intent == "enumeration":
        return ("exhaustive" if exhaustive else "bounded"), "list"
    if intent == "comparison":
        return "bounded", "comparison"
    if intent == "procedure":
        return "bounded", "steps"
    if intent == "summarization":
        return "bounded", "summary"
    if intent == "analysis":
        return "bounded", "analysis"
    return "point", "direct"


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
    conversation_context: tuple[str, ...] = (),
    profile_enabled: bool = True,
) -> QueryPlan:
    """Build the immutable semantic contract consumed by every trust stage."""
    ontology = registry or load_ontology()
    normalized = normalize_query(question)
    deterministic = resolve_entities(question, ontology)
    external = bool(getattr(rewriter, "external", True))
    deterministic_intent = classify_intent(question)
    bounded_context = (
        tuple(
            item.strip()[:MAX_CONTEXT_MESSAGE_CHARS]
            for item in conversation_context[-MAX_CONTEXT_MESSAGES:]
            if item.strip()
        )
        if external
        else ()
    )
    planner_question = (
        _planner_question(question, bounded_context)
        if external and bounded_context
        else question
    )
    candidates = ontology.candidate_matches(
        planner_question,
        limit=candidate_limit,
    )
    current_question_candidates = ontology.candidate_matches(
        question,
        limit=candidate_limit,
    )
    structural_candidate_ids = {
        item.entity_id
        for item in current_question_candidates
        if item.match_kind != "candidate"
    }
    # Two or more exact/fuzzy/partial identities for an otherwise unresolved
    # surface are a governed ambiguity (for example bare ``IP`` or ``Sight``).
    # The language model may explain or rewrite the wording, but it cannot pick
    # one enterprise identity without additional user context. The ambiguity
    # check is intentionally based on the current turn only: a previous answer
    # may legitimately mention HERA, HeraHub and HeraSight while the planner
    # resolves "nó" back to the HERA anchor.
    structural_ambiguity = bool(
        not deterministic
        and (
            len(structural_candidate_ids) > 1
            # TIP-029.2: a lone uncorroborated weak alias is governed
            # ambiguity even with a single identity behind it — the everyday
            # meaning of the shorthand ("hr") competes with the curated one.
            or uncorroborated_weak_surfaces(question, ontology)
        )
    )
    # Exact, unambiguous definitions and governed point attributes already
    # have a complete semantic contract in the ontology. Calling an external
    # planner cannot add authority and only adds cost/latency. Fuzzy identity,
    # conversation ellipsis, enumeration, comparison and open language always
    # retain the LLM planner.
    deterministic_fast_path = bool(
        external
        and deterministic
        and not bounded_context
        and not structural_ambiguity
        and all(item.match_kind == "exact" for item in current_question_candidates)
        and (
            deterministic_intent == "definition"
            or _is_point_attribute_request(normalized)
        )
    )
    # Moderate character similarity is useful for giving the planner search
    # vocabulary, but it is not identity evidence.  Accepting an LLM choice
    # from that weak pool made ordinary questions such as "tên pháp nhân" or
    # "app quản lý sáng chế" acquire an unrelated product entity.  The final
    # answer-alignment gate then rejected otherwise relevant SOT evidence.  An
    # external planner may confirm only a structural identity signal (exact,
    # safe fuzzy or partial registered name).  For semantically described but
    # unregistered concepts it still contributes bounded expansions and
    # retrieval queries; the plan remains open instead of becoming wrongly
    # constrained.  Curators add stable descriptive aliases to the ontology
    # when a concept should become a governed entity.
    confirmable_candidate_names = {
        item.canonical_name
        for item in candidates
        if item.match_kind != "candidate"
    }
    deterministic_entity_ids = tuple(
        ontology_entity.entity_id
        for entity in deterministic
        for ontology_entity in ontology.by_canonical.get(entity, ())
    )
    contextual_entity_ids = tuple(
        match.entity_id for match in ontology.resolved_matches(planner_question)
    )
    collection_candidate_names = ontology.collection_candidate_catalog(
        planner_question,
        subject_entity_ids=tuple(dict.fromkeys((
            *deterministic_entity_ids,
            *contextual_entity_ids,
        ))),
        limit=candidate_limit,
    )
    collection_candidate_ids = tuple(
        ontology.collections_by_name[name].collection_id
        for name in collection_candidate_names
    )
    planner_source: Literal["deterministic", "external", "fallback"] = (
        "external" if external else "deterministic"
    )
    result = RewriteResult()
    if deterministic_fast_path:
        external = False
        planner_source = "deterministic"
    else:
        try:
            result = await asyncio.wait_for(rewriter.rewrite(planner_question), timeout)
        except Exception:  # noqa: BLE001 — any rewriter failure must fall back safely
            planner_source = "fallback"
            external = False
            bounded_context = ()
    proposed = validate_entities(
        result.entities,
        ontology,
        allowed=confirmable_candidate_names,
    )
    entities = list(deterministic)
    if not entities and external and not structural_ambiguity:
        entities = proposed
    elif entities and external and classify_intent(question) == "comparison":
        # Exact/safe-fuzzy deterministic identity is authoritative.  The LLM
        # cannot append a different catalog entity to a single-entity question.
        entities = validate_entities([*entities, *proposed], ontology)
    expansions = _clean_expansions(result.expansions)
    resolved_question = _clean_standalone_question(
        result.standalone_question if external else "",
        question,
    )
    selected_ontology_entities = tuple(
        ontology_entity
        for entity in entities
        for ontology_entity in ontology.by_canonical.get(entity, ())
    )
    point_attribute_request = (
        _is_point_attribute_request(normalized)
        or any(
            _facet_matches_question(facet, normalized)
            for ontology_entity in selected_ontology_entities
            for facet in ontology_entity.profile_facets
        )
    )
    allowed_intents = {
        "definition", "enumeration", "comparison", "procedure",
        "summarization", "analysis", "lookup",
    }
    # Explicit linguistic structure is a user contract, not an LLM proposal.
    # A planner once reclassified "quy trình ... gồm các bước nào" as an
    # enumeration and selected the company product catalog; retrieval then did
    # exactly the wrong job with high confidence. External planning may infer
    # intent only when deterministic language is genuinely open/lookup-shaped.
    intent: QueryIntent = (
        result.intent
        if (
            external
            and deterministic_intent == "lookup"
            and not point_attribute_request
            and result.intent in allowed_intents
        )
        else deterministic_intent
    )
    planner_contract_compatible = (
        result.intent is None
        or result.intent == intent
        or (deterministic_intent == "lookup" and not point_attribute_request)
    )
    explicitly_exhaustive = requests_exhaustive(question)
    default_completeness, default_shape = _default_contract(
        intent,
        exhaustive=explicitly_exhaustive,
    )
    proposed_completeness = (
        result.completeness
        if external and result.completeness in {"point", "bounded", "exhaustive"}
        else default_completeness
    )
    # Completeness is a user contract, not an LLM escalation. The semantic
    # planner may recognize an enumeration but cannot silently turn an
    # ordinary plural question into an all-or-nothing exhaustive request.
    completeness: QueryCompleteness = (
        "point"
        if point_attribute_request
        else "exhaustive"
        if explicitly_exhaustive
        else "bounded" if proposed_completeness == "exhaustive"
        else proposed_completeness
    )
    answer_shape: AnswerShape = (
        result.answer_shape
        if external and planner_contract_compatible and result.answer_shape in {
            "direct", "list", "comparison", "steps", "summary", "analysis",
        }
        else default_shape
    )
    profile_facets = (
        tuple(
            facet
            for ontology_entity in selected_ontology_entities
            for facet in ontology_entity.profile_facets
        )
        if intent == "definition" and profile_enabled
        else tuple(
            facet
            for ontology_entity in selected_ontology_entities
            for facet in ontology_entity.profile_facets
            if intent == "lookup" and _facet_matches_question(facet, normalized)
        )
    )
    profile_record_keys = tuple(dict.fromkeys(
        record_key
        for facet in profile_facets
        for record_key in facet.record_keys
    ))
    if profile_facets and intent == "definition":
        # A curator opting an entity into a profile is a stronger completeness
        # contract than a generic LLM's point/direct interpretation.
        completeness = "bounded"
        answer_shape = "summary"
    allowed_collections = set(collection_candidate_names)
    selected_collection_names = list(dict.fromkeys(
        name
        for name in result.collections
        if external and intent == "enumeration" and name in allowed_collections
    ))
    selected_collections = [
        ontology.collections_by_name[name] for name in selected_collection_names
    ]
    collection_ids = tuple(item.collection_id for item in selected_collections)
    collection_record_keys = tuple(dict.fromkeys(
        record_key
        for collection in selected_collections
        for record_key in collection.record_keys
    ))
    required_items = tuple(dict.fromkeys(
        member.name
        for collection in selected_collections
        for member in collection.members
    ))
    required_entity_ids = tuple(dict.fromkeys(
        member.entity_id
        for collection in selected_collections
        for member in collection.members
        if member.entity_id is not None
    ))
    required_entities = tuple(
        ontology.by_id[entity_id].canonical_name
        for entity_id in required_entity_ids
    )
    collection_subject_entity_ids = {
        entity_id
        for collection in selected_collections
        for entity_id in collection.subject_entity_ids
    }
    retrieval_queries = tuple(_clean_retrieval_queries(result.retrieval_queries))
    # A broad similarity candidate is context for an external planner, not
    # evidence that the user intended a registered entity.  Treating every
    # weak catalog resemblance as ambiguity would make the ontology a hidden
    # whitelist and block ordinary enterprise questions ("inspection",
    # "policy", project prose, etc.).  Fail closed only for a structural
    # entity signal: exact collision, unresolved safe-fuzzy match, or partial
    # registered name such as "Omni" / "Sight".
    ambiguous_candidates = bool(
        not entities
        and (
            structural_ambiguity
            or any(match.match_kind != "candidate" for match in candidates)
        )
    )
    synthesis_required = (
        intent in {
            "enumeration", "comparison", "procedure", "summarization", "analysis",
        }
        or completeness != "point"
        or answer_shape != "direct"
    )
    if ambiguous_candidates:
        state: QueryResolutionState = "clarification_required"
    elif synthesis_required and not external and not deterministic_fast_path:
        state = "planning_required"
    elif (
        intent == "enumeration"
        and completeness == "exhaustive"
        and not selected_collections
    ):
        # A claim of completeness needs a governed collection boundary.  The
        # LLM may interpret language, but it cannot invent that boundary.
        state = "clarification_required"
    else:
        state = "resolved" if entities or selected_collections else "open"
    entity_ids = tuple(
        ontology_entity.entity_id
        for entity in entities
        for ontology_entity in ontology.by_canonical.get(entity, ())
    )
    entity_types = tuple(
        ontology_entity.entity_type
        for entity in entities
        for ontology_entity in ontology.by_canonical.get(entity, ())
    )
    # A governed collection is more than its membership anchor.  Bind the
    # authoritative definition records of every registered member so detail
    # evidence cannot disappear behind the global metadata candidate window as
    # an enterprise corpus grows.  The collection anchor already proves its
    # subject relationship, so omit that subject's generic definition record
    # for an enumeration; this preserves the bounded evidence budget for member
    # facts.  All bindings remain registry-governed and retrieval still applies
    # ACL/DLP before loading their content.
    explicit_definition_record_keys = tuple(
        record_key
        for ontology_entity in selected_ontology_entities
        if not (
            selected_collections
            and intent == "enumeration"
            and ontology_entity.entity_id in collection_subject_entity_ids
        )
        for record_key in ontology_entity.definition_record_keys
    )
    member_definition_record_keys = tuple(
        record_key
        for entity_id in required_entity_ids
        for record_key in ontology.by_id[entity_id].definition_record_keys
    )
    definition_record_keys = tuple(dict.fromkeys((
        *explicit_definition_record_keys,
        *member_definition_record_keys,
        *profile_record_keys,
    )))
    retrieval_base = (
        question
        if normalize_query(resolved_question) == normalized
        else f"{question} {resolved_question}"
    )
    retrieval_query = _augment_with(
        retrieval_base,
        [
            *entities,
            *selected_collection_names,
            *required_items,
        ],
        [*expansions, *retrieval_queries],
    )
    terms = tuple(dict.fromkeys(normalized.split()))
    return QueryPlan(
        normalized=normalized,
        terms=terms,
        intent=intent,
        completeness=completeness,
        answer_shape=answer_shape,
        entities=tuple(entities),
        entity_ids=entity_ids,
        entity_types=entity_types,
        definition_record_keys=definition_record_keys,
        profile_facets=profile_facets,
        profile_record_keys=profile_record_keys,
        candidates=tuple(candidates),
        collection_candidate_ids=collection_candidate_ids,
        collection_ids=collection_ids,
        collection_record_keys=collection_record_keys,
        required_items=required_items,
        required_entities=required_entities,
        resolution_state=state,
        resolved_question=resolved_question,
        context_message_count=len(bounded_context),
        retrieval_query=retrieval_query,
        retrieval_queries=retrieval_queries,
        expansions=tuple(expansions),
        planner_source=planner_source,
        ontology_digest=ontology.digest,
    )
