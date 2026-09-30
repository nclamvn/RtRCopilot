"""Fail-closed question/evidence relevance controls for TIP-024.6.

Grounding is a three-link chain: question -> evidence -> claim.  The original
TIP-007 gate protected only the second link.  This module supplies deterministic
entity, intent and meaningful-term checks for the first link, plus a final
question/answer consistency check.  It never decides truth or bypasses policy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rtr_copilot.rag.adapters import (
    QUERY_STOPWORDS,
    lexical_terms,
    normalize_query,
)
from rtr_copilot.rag.models import ProviderEvidence
from rtr_copilot.rag.query_understanding import (
    QueryIntent,
    classify_intent,
    resolve_entities,
)

_RECORD_PREFIX = re.compile(r"^[A-Za-z0-9_.-]+:\s*")
_RECORD_KEY_SEPARATOR = re.compile(r"[._-]+")
_PROCEDURE_ROW = re.compile(r"^(?:b|buoc|step)\s*\d{1,3}\b")
CORPUS_IDF_WEIGHT = 0.08
# On the measured 400-chunk active corpus this floor means a term occurs in at
# most a handful of chunks (Argon2id=1, ``idf=6.30``; ``bam``=3, ``idf=5.61``).
# An exact match on such an identifier is evidence on par with a governed
# definition binding, but never bypasses that binding or any security gate.
RARE_TERM_IDF_FLOOR = 5.0
RARE_TERM_WEIGHT = 0.72


def _record_key_text(record_key: str) -> str:
    """Expose governed identifier segments as ordinary semantic metadata.

    Enterprise file logical names are deliberately stable identifiers such as
    ``tip027.crm.service-request-process``.  Query normalization preserves
    punctuation inside tokens, which is correct for user prose but previously
    hid ``crm``, ``service`` and ``process`` from entity/relevance checks.  A
    record key is trusted naming metadata, so expand only its structural
    separators before matching; document content remains unchanged.
    """
    return _RECORD_KEY_SEPARATOR.sub(" ", record_key)


def is_procedure_row(value: str) -> bool:
    """Whether a text unit is an explicitly numbered workflow step."""
    return bool(_PROCEDURE_ROW.match(normalize_query(value)))


@dataclass(frozen=True)
class QueryProfile:
    normalized: str
    terms: tuple[str, ...]
    entities: tuple[str, ...]
    intent: QueryIntent
    definition_record_keys: tuple[str, ...]
    profile_record_keys: tuple[str, ...]
    collection_record_keys: tuple[str, ...]


def meaningful_terms(value: str) -> tuple[str, ...]:
    """Unique normalized content terms, preserving question order."""
    seen: list[str] = []
    for token in normalize_query(value).split():
        if token not in QUERY_STOPWORDS and token not in seen:
            seen.append(token)
    return tuple(seen)


def profile_query(
    value: str,
    *,
    entities: tuple[str, ...] | list[str] | None = None,
    intent: QueryIntent | None = None,
    definition_record_keys: tuple[str, ...] | list[str] | None = None,
    profile_record_keys: tuple[str, ...] | list[str] | None = None,
    collection_record_keys: tuple[str, ...] | list[str] | None = None,
) -> QueryProfile:
    normalized = normalize_query(value)
    return QueryProfile(
        normalized=normalized,
        terms=meaningful_terms(value),
        entities=tuple(resolve_entities(value) if entities is None else entities),
        intent=intent or classify_intent(value),
        definition_record_keys=tuple(definition_record_keys or ()),
        profile_record_keys=tuple(profile_record_keys or ()),
        collection_record_keys=tuple(collection_record_keys or ()),
    )


def mentioned_entities(text: str, record_key: str = "") -> set[str]:
    return set(resolve_entities(f"{_record_key_text(record_key)} {text}"))


def primary_entities(text: str, record_key: str = "") -> set[str]:
    """Entities presented as the record subject, not incidental mentions.

    The record key is authoritative naming metadata.  Otherwise only the first
    entity in the lead is treated as primary, so a HERA fact that says
    "VEGA is different" cannot masquerade as a VEGA definition.
    """
    primary = set(resolve_entities(_record_key_text(record_key)))
    lead = _RECORD_PREFIX.sub("", text, count=1)
    lead_entities = resolve_entities(" ".join(normalize_query(lead).split()[:4]))
    if lead_entities:
        primary.add(lead_entities[0])
    return primary


def corpus_idf_signals(
    query_terms: Sequence[str],
    *,
    text: str,
    record_key: str,
    idf_by_term: Mapping[str, float],
) -> tuple[float, float]:
    """Return weighted coverage and rare-anchor coverage in one tokenization.

    Missing or stale statistics fail neutral (zero), never as a penalty or an
    authority bypass. Candidate lexemes use the same tokenizer as PostgreSQL's
    ``simple`` dictionary query path, including punctuation splitting.
    """
    weighted = {
        term: max(0.0, float(idf_by_term.get(term, 0.0)))
        for term in dict.fromkeys(query_terms)
    }
    denominator = sum(weighted.values())
    if denominator <= 0:
        return 0.0, 0.0
    candidate_terms = set(lexical_terms(normalize_query(
        f"{_record_key_text(record_key)} {text}",
    )))
    numerator = sum(
        weight for term, weight in weighted.items() if term in candidate_terms
    )
    weighted_coverage = min(1.0, numerator / denominator)
    rare = {
        term: weight
        for term, weight in weighted.items()
        if weight >= RARE_TERM_IDF_FLOOR
    }
    rare_denominator = sum(rare.values())
    if rare_denominator <= 0:
        return weighted_coverage, 0.0
    rare_coverage = min(
        1.0,
        sum(weight for term, weight in rare.items() if term in candidate_terms)
        / rare_denominator,
    )
    return weighted_coverage, rare_coverage


def corpus_idf_coverage(
    query_terms: Sequence[str],
    *,
    text: str,
    record_key: str,
    idf_by_term: Mapping[str, float],
) -> float:
    """Weighted component of :func:`corpus_idf_signals`."""
    return corpus_idf_signals(
        query_terms,
        text=text,
        record_key=record_key,
        idf_by_term=idf_by_term,
    )[0]


def corpus_rare_term_coverage(
    query_terms: Sequence[str],
    *,
    text: str,
    record_key: str,
    idf_by_term: Mapping[str, float],
) -> float:
    """Coverage of genuinely rare exact anchors in the active corpus."""
    return corpus_idf_signals(
        query_terms,
        text=text,
        record_key=record_key,
        idf_by_term=idf_by_term,
    )[1]


def candidate_relevance_score(
    profile: QueryProfile,
    *,
    text: str,
    record_key: str,
    base_score: float,
    vector_score: float,
    min_vector_score: float,
    support_queries: Sequence[str] = (),
    allow_unbound_definition: bool = False,
    semantic_floor: float | None = None,
    idf_coverage: float = 0.0,
    rare_idf_coverage: float = 0.0,
) -> float | None:
    """Return an adjusted rank, or ``None`` when evidence is ineligible.

    The user's original wording is the ranking authority. LLM expansions and
    focused retrieval queries may bridge colloquial language for recall, but
    receive a deliberately smaller boost. Treating the concatenated rewrite as
    the primary profile let generic terms such as ``company`` and ``system``
    outrank the user's discriminative term such as ``CRM`` or ``SOT``.

    ``semantic_floor`` (TIP-014RE): with REAL provider embeddings a high
    cosine score IS relevance evidence — "tech stack" must be able to reach a
    technology record that shares zero tokens with the question. Retrieval
    passes the configured floor ONLY when the provider adapter is active
    (never for the offline hash stub, never on a degraded query where
    vector_score collapsed to 0), and a candidate admitted purely on
    semantics still faces the unchanged downstream gates: evidence
    relevance, provider review, deterministic grounding and final answer
    relevance. ``None`` preserves the hash-era hard exclusions exactly.
    """
    semantically_bridged = (
        semantic_floor is not None and vector_score >= semantic_floor
    )
    definition_anchor = record_key in profile.definition_record_keys
    profile_anchor = record_key in profile.profile_record_keys
    if (
        profile.intent == "definition"
        and profile.definition_record_keys
        and not definition_anchor
        and not allow_unbound_definition
    ):
        return None
    collection_anchor = record_key in profile.collection_record_keys
    mentions = mentioned_entities(text, record_key)
    primary = primary_entities(text, record_key)
    targets = set(profile.entities)
    record_terms = set(meaningful_terms(_record_key_text(record_key)))
    text_terms = set(meaningful_terms(f"{_record_key_text(record_key)} {text}"))
    original_matches = len(set(profile.terms) & text_terms)
    term_overlap = (
        original_matches / len(profile.terms)
        if profile.terms else 0.0
    )
    support_profiles = [meaningful_terms(query) for query in support_queries]
    support_overlap = max(
        (
            len(set(terms) & text_terms) / len(terms)
            for terms in support_profiles
            if terms
        ),
        default=0.0,
    )

    # Original intent dominates noisy offline-vector proximity. Rewrites can
    # recover synonyms, but cannot take semantic authority from the question.
    adjustment = term_overlap * 0.62 + min(original_matches, 3) * 0.04
    adjustment += support_overlap * 0.18
    # TIP-053: rare exact terms are more discriminative than ubiquitous
    # company prose. The bounded additive signal cannot outrank authority
    # contracts by itself and is a no-op when corpus statistics are absent.
    adjustment += min(1.0, max(0.0, idf_coverage)) * CORPUS_IDF_WEIGHT
    adjustment += (
        min(1.0, max(0.0, rare_idf_coverage)) * RARE_TERM_WEIGHT
    )
    if profile.intent == "procedure":
        # Select the governing process/SOP before adjacent intake, quotation
        # and survey forms when document admission is metadata-only. Forms are
        # useful supporting evidence, but choosing one as the sole priority
        # document prevents the complete numbered workflow from ever reaching
        # sequence reconstruction.
        if record_terms & {
            "process", "procedure", "workflow", "protocol", "sop",
        }:
            adjustment += 0.35
        # Structured workflow rows often carry an ordinal (B1, Step 2, Bước
        # 3) while the question names only the process. Prefer those actionable
        # rows over covers, purpose statements and adjacent forms after the
        # document itself has passed entity and relevance gates.
        if is_procedure_row(text):
            # The former 0.50 no longer offset the combined title-term and
            # entity-primary bonus of a cover row (1.299 vs 1.043 in the
            # invariant test), so the answer evidence could lead with the
            # document cover rather than an executable step. A numbered row is
            # already constrained to an admitted procedure document; make that
            # structural signal decisive inside that document.
            adjustment += 0.90
        elif text_terms & {
            "deadline", "form", "owner", "responsibility", "sla",
            "bieu", "mau", "thoi", "han", "trach", "nhiem",
        }:
            adjustment += 0.10
    if targets:
        matched = targets & mentions
        # TIP-052: cổng "phải nhắc tên thực thể" làm mọi FACT NGUYÊN TỬ không
        # lặp lại tên công ty trở nên vô hình với bất kỳ câu hỏi nào có nhắc
        # tên công ty. Đo ngày 21/09: "Mật khẩu người dùng được băm bằng thuật
        # toán nào?" trả đúng L3F.INF.014, nhưng thêm hai chữ "của RtR" thì
        # bản ghi đó biến mất hoàn toàn, vì nội dung của nó không chứa chữ
        # RtR. Chỉ những bản ghi mở đầu bằng "RtR có ..." sống sót, và đó là
        # lý do câu hỏi kỹ thuật bị trả lời bằng bản kiểm kê tài liệu. Kernel
        # càng được curate sạch thành fact ngắn gọn thì càng vô hình.
        #
        # Cứu bản ghi KHÔNG nhắc thực thể nào cả và trúng đủ từ quyết định của
        # câu hỏi. Bản ghi nhắc một thực thể KHÁC vẫn bị loại nguyên như cũ,
        # nên tính cách ly giữa HERA và VEGA không suy giảm: fact sản phẩm
        # luôn mang tên sản phẩm trong khóa bản ghi nên vẫn tính là có nhắc.
        unbound_but_specific = (
            not mentions
            and original_matches >= 2
            and term_overlap >= 0.25
        )
        if (
            not matched
            and not collection_anchor
            and not profile_anchor
            and not definition_anchor
            and not semantically_bridged
            and not unbound_but_specific
        ):
            return None
        # Definition evidence must make the requested entity its subject.
        if (
            profile.intent == "definition"
            and len(targets) == 1
            and not targets <= primary
            and not profile_anchor
            and not definition_anchor
        ):
            return None
        coverage = len(matched) / len(targets)
        # TIP-052.1: thưởng cho việc NHẮC ĐÚNG TÊN thực thể phải tỉ lệ với độ
        # trùng chủ đề, không được đứng độc lập. Đo ngày 21/09 bằng chính hàm
        # này: với câu "Mật khẩu người dùng của RtR được băm bằng Argon2id",
        # bản ghi đúng trúng 7/9 từ được 0,702 còn bản ghi kiểm kê tài liệu chỉ
        # trúng 3/9 từ lại được 1,047, vì nó mở đầu bằng "RtR có ..." nên ăn
        # trọn 0,62 tiền thưởng nhắc tên. Nhắc đúng tên đang đáng giá gần bằng
        # trả lời đúng câu hỏi, và đó là lý do mọi câu có chữ RtR đều rơi vào
        # bản ghi kiểm kê.
        #
        # Nhân hai khoản thưởng với độ trùng chủ đề: bản ghi vừa đúng tên vừa
        # đúng chủ đề gần như không mất gì (fact sản phẩm giữ nguyên điểm 1,460
        # trong phép đo), còn bản ghi đúng tên mà lạc đề mất gần hết. Ba biến
        # thể đã được chấm trên cùng tập trước khi chọn cái này; chỉ cái này
        # đúng cả ba case, xem eval/tip050/bonus_probe.py.
        entity_weight = max(term_overlap, support_overlap)
        adjustment += coverage * 0.24 * entity_weight
        if matched & primary:
            adjustment += 0.38 * entity_weight
        if profile.intent == "definition":
            definition_terms = {
                "drone", "heavy", "lifter", "multirotor", "platform", "tactical", "uav",
            }
            if text_terms & definition_terms:
                adjustment += 0.28
            if record_key.upper().startswith("HC-"):
                adjustment += 0.12
        competing = len(mentions - targets)
        adjustment -= min(0.20, competing * 0.04)
    elif term_overlap == 0 and support_overlap == 0:
        # Hash-era rule: hash-vector proximity alone was noise, so at least
        # one discriminative term had to match. With a real provider adapter
        # a score above ``semantic_floor`` is legitimate relevance evidence
        # (TIP-014RE adjudication: the newer approved spec wins); anything
        # below the floor keeps the original hard exclusion.
        if not semantically_bridged:
            return None

    if collection_anchor:
        # Exhaustive plans must not lose their governed set boundary to a
        # semantically similar detail chunk.
        adjustment += 1.0
    if definition_anchor:
        # A governed definition binding is the strongest ranking signal. An
        # explicitly source-scoped search may also admit a primary-subject
        # definition while its ontology binding is being curated; the normal
        # company-wide path stays strictly authority-bound.
        adjustment += 0.72
    if profile_anchor:
        # A curator explicitly linked this record to an entity-profile facet.
        # That relationship is stronger subject metadata than the first words
        # of cross-product records such as maintenance, warranty, controller
        # or sensor facts. It never bypasses ACL/DLP; the reviewed registry
        # link supplies the entity relationship when the record uses a distinct
        # component name (for example HeraSight LR).
        adjustment += 0.24
    return base_score + adjustment


def collection_items_covered(required_items: tuple[str, ...], text: str) -> bool:
    """Whether normalized text explicitly contains every governed item name."""
    if not required_items:
        return False
    haystack = re.findall(r"[a-z0-9]+", normalize_query(text))

    def contains(item: str) -> bool:
        needle = re.findall(r"[a-z0-9]+", normalize_query(item))
        if not needle:
            return False
        width = len(needle)
        return any(
            haystack[index:index + width] == needle
            for index in range(len(haystack) - width + 1)
        )

    return all(contains(item) for item in required_items)


def evidence_relevant(
    question: str,
    evidence: list[ProviderEvidence],
    *,
    entities: tuple[str, ...] | list[str] | None = None,
    intent: QueryIntent | None = None,
    support_terms: tuple[str, ...] | list[str] | None = None,
    definition_record_keys: tuple[str, ...] | list[str] | None = None,
    profile_record_keys: tuple[str, ...] | list[str] | None = None,
) -> bool:
    """Question -> evidence gate; false means abstain before provider use.

    ``support_terms`` are semantic bridges from an external query planner. They
    are considered only when the original meaningful terms have no overlap and
    never override a confirmed entity contract. The answer provider still sees
    the original question and evidence, and its independent review remains
    mandatory before grounding can pass.
    """
    if not evidence:
        return False
    profile = profile_query(question, entities=entities, intent=intent)
    targets = set(profile.entities)
    definition_bindings = set(definition_record_keys or ())
    del profile_record_keys  # bindings already shaped candidate retrieval
    combined = " ".join(item.text for item in evidence)
    if targets:
        # File logical names and SOT record keys are governed subject metadata.
        # A workflow row naturally begins ``B6 | sửa chữa...`` and need not
        # repeat ``RtR CRM`` in every cell. Ignoring the bound record key made
        # a complete, authorized process look entity-irrelevant immediately
        # before synthesis.
        mentions = {
            entity
            for item in evidence
            for entity in mentioned_entities(
                item.text,
                item.record_key or "",
            )
        }
        has_definition_binding = any(
            item.record_key in definition_bindings for item in evidence
        )
        if not targets <= mentions and not has_definition_binding:
            return False
        if profile.intent == "definition" and len(targets) == 1:
            return has_definition_binding or any(
                targets <= primary_entities(item.text, item.record_key or "")
                for item in evidence
            )
        # Retrieval may include a low-ranked adjacent hit. Rejecting the whole
        # authorized evidence set because of that padding made ordinary Ask
        # turns fail before the LLM could ignore it. At least one correct
        # primary/entity record is still mandatory above; final-answer entity
        # consistency and marker-level grounding remain strict below.
        return True
    if not profile.terms:
        return False
    evidence_terms = set(meaningful_terms(combined))
    if set(profile.terms) & evidence_terms:
        return True
    bridge_terms = set(meaningful_terms(" ".join(support_terms or ())))
    return bool(bridge_terms & evidence_terms)


_META_REPLY_RE_ASK = re.compile(r"\b(khach|khach hang|customer|client|nguoi ta|ai do)\s+hoi\b")
_META_REPLY_RE_HOW = re.compile(
    r"\b(answer|tra loi|noi|phan hoi|reply)\b.{0,30}\b(sao|the nao|nhu nao|gi)\b",
)


def _is_meta_reply_question(normalized: str) -> bool:
    """TIP-030: "khách hỏi X thì mình answer sao" asks for a SUGGESTED REPLY.

    The natural answer is reply prose ("chúng tôi ...") that legitimately may
    not restate the canonical entity name, so the strict entity-mention rule
    produced deterministic false refusals (COM-008: called_answer_irrelevant
    across every campaign run). Detection is deliberately narrow: an explicit
    ask-verb about how to answer/reply."""
    return bool(
        _META_REPLY_RE_ASK.search(normalized)
        and _META_REPLY_RE_HOW.search(normalized)
    )


def answer_relevant(
    question: str,
    answer: str,
    *,
    entities: tuple[str, ...] | list[str] | None = None,
    intent: QueryIntent | None = None,
    support_terms: tuple[str, ...] | list[str] | None = None,
) -> bool:
    """Final question -> answer consistency gate."""
    profile = profile_query(question, entities=entities, intent=intent)
    targets = set(profile.entities)
    if targets and _is_meta_reply_question(profile.normalized):
        # Suggested-reply mode: accept a canonical mention OR lexical overlap
        # with the question/support vocabulary. Marker-level grounding stays
        # mandatory upstream, so nothing uncited can pass through here.
        answer_terms = set(meaningful_terms(answer))
        bridge_terms = set(meaningful_terms(" ".join(support_terms or ())))
        return bool(
            (targets & mentioned_entities(answer))
            or (set(profile.terms) & answer_terms)
            or (bridge_terms & answer_terms)
        )
    if targets:
        answer_entities = mentioned_entities(answer)
        if not targets <= answer_entities:
            return False
        if profile.intent == "definition" and len(targets) == 1:
            # A correct answer may open with a short structural label before
            # naming the entity. Requiring the canonical name within the first
            # four words caused deterministic false negatives for The Sky
            # Watch. Inspect the first entity-bearing clause instead: a short
            # non-entity lead may be skipped, but an adjacent product named
            # first still makes the answer irrelevant.
            for clause in re.split(r"[\n;]+", answer)[:4]:
                resolved_clause_entities = resolve_entities(clause)
                clause_entities = set(resolved_clause_entities)
                if clause_entities:
                    return (
                        targets <= clause_entities
                        and resolved_clause_entities[0] in targets
                    )
                if len(meaningful_terms(clause)) > 6:
                    return False
            return False
        return True
    if not profile.terms:
        return False
    answer_terms = set(meaningful_terms(answer))
    if set(profile.terms) & answer_terms:
        return True
    bridge_terms = set(meaningful_terms(" ".join(support_terms or ())))
    return bool(bridge_terms & answer_terms)
