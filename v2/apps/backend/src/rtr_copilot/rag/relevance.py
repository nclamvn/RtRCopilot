"""Fail-closed question/evidence relevance controls for TIP-024.6.

Grounding is a three-link chain: question -> evidence -> claim.  The original
TIP-007 gate protected only the second link.  This module supplies deterministic
entity, intent and meaningful-term checks for the first link, plus a final
question/answer consistency check.  It never decides truth or bypasses policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rtr_copilot.rag.adapters import QUERY_STOPWORDS, normalize_query
from rtr_copilot.rag.models import ProviderEvidence
from rtr_copilot.rag.query_understanding import (
    QueryIntent,
    classify_intent,
    resolve_entities,
)

_RECORD_PREFIX = re.compile(r"^[A-Za-z0-9_.-]+:\s*")
@dataclass(frozen=True)
class QueryProfile:
    normalized: str
    terms: tuple[str, ...]
    entities: tuple[str, ...]
    intent: QueryIntent
    definition_record_keys: tuple[str, ...]


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
) -> QueryProfile:
    normalized = normalize_query(value)
    return QueryProfile(
        normalized=normalized,
        terms=meaningful_terms(value),
        entities=tuple(resolve_entities(value) if entities is None else entities),
        intent=intent or classify_intent(value),
        definition_record_keys=tuple(definition_record_keys or ()),
    )


def mentioned_entities(text: str, record_key: str = "") -> set[str]:
    return set(resolve_entities(f"{record_key} {text}"))


def primary_entities(text: str, record_key: str = "") -> set[str]:
    """Entities presented as the record subject, not incidental mentions.

    The record key is authoritative naming metadata.  Otherwise only the first
    entity in the lead is treated as primary, so a HERA fact that says
    "VEGA is different" cannot masquerade as a VEGA definition.
    """
    primary = set(resolve_entities(record_key))
    lead = _RECORD_PREFIX.sub("", text, count=1)
    lead_entities = resolve_entities(" ".join(normalize_query(lead).split()[:4]))
    if lead_entities:
        primary.add(lead_entities[0])
    return primary


def candidate_relevance_score(
    profile: QueryProfile,
    *,
    text: str,
    record_key: str,
    base_score: float,
    vector_score: float,
    min_vector_score: float,
) -> float | None:
    """Return an adjusted rank, or ``None`` when evidence is ineligible."""
    if (
        profile.intent == "definition"
        and profile.definition_record_keys
        and record_key not in profile.definition_record_keys
    ):
        return None
    mentions = mentioned_entities(text, record_key)
    primary = primary_entities(text, record_key)
    targets = set(profile.entities)
    text_terms = set(meaningful_terms(f"{record_key} {text}"))
    term_overlap = (
        len(set(profile.terms) & text_terms) / len(profile.terms)
        if profile.terms else 0.0
    )

    adjustment = term_overlap * 0.18
    if targets:
        matched = targets & mentions
        if not matched:
            return None
        # Definition evidence must make the requested entity its subject.
        if profile.intent == "definition" and len(targets) == 1 and not targets <= primary:
            return None
        coverage = len(matched) / len(targets)
        adjustment += coverage * 0.24
        if matched & primary:
            adjustment += 0.38
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
    elif term_overlap == 0:
        # Hash-vector proximity alone is not evidence relevance. External query
        # planning may add a validated synonym, but at least one discriminative
        # term must still match before content can reach answer generation.
        return None

    return base_score + adjustment


def evidence_relevant(
    question: str,
    evidence: list[ProviderEvidence],
    *,
    entities: tuple[str, ...] | list[str] | None = None,
    intent: QueryIntent | None = None,
    support_terms: tuple[str, ...] | list[str] | None = None,
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
    combined = " ".join(item.text for item in evidence)
    if targets:
        mentions = mentioned_entities(combined)
        if not targets <= mentions:
            return False
        if (
            profile.intent == "definition"
            and len(targets) == 1
            and not any(targets <= primary_entities(item.text) for item in evidence)
        ):
            return False
        # Single-entity answers may not be padded with evidence that never
        # mentions the requested product.
        return not (len(targets) == 1 and any(
            not targets <= mentioned_entities(item.text) for item in evidence
        ))
    if not profile.terms:
        return False
    evidence_terms = set(meaningful_terms(combined))
    if set(profile.terms) & evidence_terms:
        return True
    bridge_terms = set(meaningful_terms(" ".join(support_terms or ())))
    return bool(bridge_terms & evidence_terms)


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
    if targets:
        answer_entities = mentioned_entities(answer)
        if not targets <= answer_entities:
            return False
        if profile.intent == "definition" and len(targets) == 1:
            return targets <= primary_entities(answer)
        return True
    if not profile.terms:
        return False
    answer_terms = set(meaningful_terms(answer))
    if set(profile.terms) & answer_terms:
        return True
    bridge_terms = set(meaningful_terms(" ".join(support_terms or ())))
    return bool(bridge_terms & answer_terms)
