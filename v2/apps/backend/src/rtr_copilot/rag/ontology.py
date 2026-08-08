"""Domain-agnostic enterprise ontology registry for query intelligence.

The registry is data.  Resolver behavior is generic: adding a customer, policy,
project or future entity type changes registry data, not query code.  Exact and
approved aliases are authoritative; fuzzy and partial matches are candidates
only and never silently become truth when more than one entity can match.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.db.engine import session_factory
from rtr_copilot.rag.adapters import normalize_query

MatchKind = Literal["exact", "weak", "fuzzy", "partial", "candidate"]

# A partial-name signal must come from an identifying token, not a generic
# domain noun. Without this boundary, a registered alias such as "Da Nang
# drone" made every ordinary question containing "drone" look like a partial
# project name and forced an unnecessary clarification. These terms may still
# contribute moderate candidate similarity for an external planner; they just
# cannot independently trigger the fail-closed ambiguity gate.
GENERIC_ENTITY_PARTS = frozenset({
    "ai", "company", "cong", "customer", "data", "drone", "du", "enterprise",
    "he", "internal", "khach", "management", "platform", "policy", "product",
    "project", "robot", "robotics", "solution", "system", "technology", "thong",
    "time", "uav",
})


class OntologyProfileFacet(BaseModel):
    """One curator-defined evidence dimension of an entity profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facet_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    label: str = Field(min_length=1, max_length=160)
    presentation_labels: tuple[str, ...] = Field(default=(), max_length=12)
    # Curator-governed ordinary-language surfaces that route a point lookup to
    # this facet's authoritative records.  A profile is therefore both a
    # definition dossier and a scalable attribute index; product/domain growth
    # remains registry data instead of accumulating question-specific code.
    query_aliases: tuple[str, ...] = Field(default=(), max_length=40)
    record_keys: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def record_keys_are_well_formed(self) -> OntologyProfileFacet:
        if any(
            not record_key.strip() or len(record_key) > 160
            for record_key in self.record_keys
        ):
            raise ValueError("ontology_profile_record_key_invalid")
        if len(self.record_keys) != len(set(self.record_keys)):
            raise ValueError("ontology_profile_record_key_duplicate")
        normalized_labels = [
            normalize_query(label) for label in self.presentation_labels
        ]
        if any(not label for label in normalized_labels):
            raise ValueError("ontology_profile_presentation_label_invalid")
        if len(normalized_labels) != len(set(normalized_labels)):
            raise ValueError("ontology_profile_presentation_label_duplicate")
        normalized_aliases = [normalize_query(alias) for alias in self.query_aliases]
        if any(not alias for alias in normalized_aliases):
            raise ValueError("ontology_profile_query_alias_invalid")
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError("ontology_profile_query_alias_duplicate")
        return self


class OntologyEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    canonical_name: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    aliases: tuple[str, ...] = ()
    # TIP-029.2: a weak alias is curated shorthand whose surface collides with
    # a common outside meaning (e.g. "hr" -> HERA vs human resources). It
    # resolves ONLY when the question carries corroborating content beyond the
    # alias itself; a bare definition question about the alias must ask for
    # clarification instead of confidently answering (SAFE-007 trap).
    weak_aliases: tuple[str, ...] = ()
    definition_record_keys: tuple[str, ...] = ()
    profile_facets: tuple[OntologyProfileFacet, ...] = ()
    lifecycle: Literal["active", "retired"] = "active"
    owner: str = Field(min_length=1, max_length=160)
    provenance_level: Literal["verified_primary", "approved_internal", "claim", "flagged"]

    @model_validator(mode="after")
    def aliases_are_meaningful(self) -> OntologyEntity:
        if any(not normalize_query(alias) for alias in self.aliases):
            raise ValueError("ontology_alias_empty_after_normalization")
        if any(not normalize_query(alias) for alias in self.weak_aliases):
            raise ValueError("ontology_weak_alias_empty_after_normalization")
        strong = {normalize_query(alias) for alias in self.aliases}
        strong.add(normalize_query(self.canonical_name))
        if any(normalize_query(alias) in strong for alias in self.weak_aliases):
            raise ValueError("ontology_weak_alias_shadows_strong_surface")
        if any(
            not record_key.strip() or len(record_key) > 160
            for record_key in self.definition_record_keys
        ):
            raise ValueError("ontology_definition_record_key_invalid")
        if len(self.definition_record_keys) != len(set(self.definition_record_keys)):
            raise ValueError("ontology_definition_record_key_duplicate")
        facet_ids = [facet.facet_id for facet in self.profile_facets]
        if len(facet_ids) != len(set(facet_ids)):
            raise ValueError("ontology_profile_facet_duplicate")
        return self


class OntologyCollectionMember(BaseModel):
    """One governed member of an enterprise collection.

    ``entity_id`` is optional because operational catalogs can legitimately
    contain bundles, service rows and workflow placeholders that are not
    standalone ontology entities.  ``kind`` keeps that distinction explicit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    entity_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$",
    )


class OntologyCollection(BaseModel):
    """Provenance-bound set used to prove exhaustive answer coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    collection_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    canonical_name: str = Field(min_length=1, max_length=160)
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    aliases: tuple[str, ...] = ()
    subject_entity_ids: tuple[str, ...] = ()
    members: tuple[OntologyCollectionMember, ...] = Field(
        min_length=1,
        max_length=512,
    )
    record_keys: tuple[str, ...] = Field(min_length=1, max_length=64)
    lifecycle: Literal["active", "retired"] = "active"
    owner: str = Field(min_length=1, max_length=160)
    provenance_level: Literal[
        "verified_primary", "approved_internal", "claim", "flagged",
    ]

    @model_validator(mode="after")
    def collection_is_well_formed(self) -> OntologyCollection:
        if any(not normalize_query(alias) for alias in self.aliases):
            raise ValueError("ontology_collection_alias_empty")
        member_names = [normalize_query(member.name) for member in self.members]
        if any(not name for name in member_names):
            raise ValueError("ontology_collection_member_empty")
        if len(member_names) != len(set(member_names)):
            raise ValueError("ontology_collection_member_duplicate")
        if len(self.record_keys) != len(set(self.record_keys)):
            raise ValueError("ontology_collection_record_key_duplicate")
        return self


class OntologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    registry_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    owner: str = Field(min_length=1, max_length=160)
    entities: tuple[OntologyEntity, ...] = Field(min_length=1, max_length=100_000)
    collections: tuple[OntologyCollection, ...] = Field(
        default=(),
        max_length=10_000,
    )

    @model_validator(mode="after")
    def stable_ids_are_unique(self) -> OntologySpec:
        ids = [entity.entity_id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("ontology_entity_id_duplicate")
        collection_ids = [item.collection_id for item in self.collections]
        if len(collection_ids) != len(set(collection_ids)):
            raise ValueError("ontology_collection_id_duplicate")
        entity_ids = set(ids)
        for collection in self.collections:
            references = set(collection.subject_entity_ids) | {
                member.entity_id
                for member in collection.members
                if member.entity_id is not None
            }
            if not references <= entity_ids:
                raise ValueError("ontology_collection_entity_unknown")
        return self


@dataclass(frozen=True)
class OntologyMatch:
    entity_id: str
    canonical_name: str
    entity_type: str
    domain: str
    matched_surface: str
    match_kind: MatchKind
    confidence: float


class EnterpriseOntology:
    """Validated, digest-bound registry with deterministic candidate lookup."""

    def __init__(self, spec: OntologySpec) -> None:
        self.spec = spec
        self.entities = tuple(entity for entity in spec.entities if entity.lifecycle == "active")
        self.by_id = {entity.entity_id: entity for entity in self.entities}
        self.collections = tuple(
            item for item in spec.collections if item.lifecycle == "active"
        )
        self.collections_by_id = {
            item.collection_id: item for item in self.collections
        }
        self.collections_by_name = {
            item.canonical_name: item for item in self.collections
        }
        self.by_canonical: dict[str, list[OntologyEntity]] = defaultdict(list)
        self._surface_index: dict[str, list[OntologyEntity]] = defaultdict(list)
        self._surfaces: list[tuple[str, OntologyEntity]] = []
        self._max_tokens = 1
        self._weak_surfaces: set[str] = set()
        for entity in self.entities:
            self.by_canonical[entity.canonical_name].append(entity)
            seen: set[str] = set()
            for surface in (entity.canonical_name, *entity.aliases):
                normalized = normalize_query(surface)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                self._surface_index[normalized].append(entity)
                self._surfaces.append((normalized, entity))
                self._max_tokens = max(self._max_tokens, len(normalized.split()))
            for surface in entity.weak_aliases:
                normalized = normalize_query(surface)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                self._surface_index[normalized].append(entity)
                self._surfaces.append((normalized, entity))
                self._weak_surfaces.add(normalized)
                self._max_tokens = max(self._max_tokens, len(normalized.split()))
        canonical = json.dumps(
            spec.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.digest = hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def from_path(cls, path: Path) -> EnterpriseOntology:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(OntologySpec.model_validate(payload))

    def _match(
        self,
        entity: OntologyEntity,
        *,
        surface: str,
        kind: MatchKind,
        confidence: float,
    ) -> OntologyMatch:
        return OntologyMatch(
            entity_id=entity.entity_id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            domain=entity.domain,
            matched_surface=surface,
            match_kind=kind,
            confidence=confidence,
        )

    @staticmethod
    def _dedupe(matches: list[OntologyMatch]) -> list[OntologyMatch]:
        kind_rank = {"candidate": 0, "partial": 1, "fuzzy": 2, "weak": 3, "exact": 4}
        best: dict[str, OntologyMatch] = {}
        for match in matches:
            existing = best.get(match.entity_id)
            if (
                existing is None
                or kind_rank[match.match_kind] > kind_rank[existing.match_kind]
                or (
                    match.match_kind == existing.match_kind
                    and match.confidence > existing.confidence
                )
            ):
                best[match.entity_id] = match
        return list(best.values())

    def exact_matches(self, question: str) -> list[OntologyMatch]:
        tokens = normalize_query(question).split()
        matches: list[OntologyMatch] = []
        index = 0
        while index < len(tokens):
            found = False
            upper = min(self._max_tokens, len(tokens) - index)
            for size in range(upper, 0, -1):
                surface = " ".join(tokens[index : index + size])
                entities = self._surface_index.get(surface, [])
                if not entities:
                    continue
                matches.extend(
                    self._match(
                        entity,
                        surface=surface,
                        kind=(
                            "weak"
                            if surface in self._weak_surfaces
                            else "exact"
                        ),
                        confidence=1.0,
                    )
                    for entity in entities
                )
                index += size
                found = True
                break
            if not found:
                index += 1
        return self._dedupe(matches)

    def fuzzy_matches(
        self,
        question: str,
        *,
        threshold: float = 0.86,
        ambiguity_margin: float = 0.02,
    ) -> list[OntologyMatch]:
        matches: list[OntologyMatch] = []
        for token in normalize_query(question).split():
            if len(token) < 4:
                continue
            scored: list[tuple[float, str, OntologyEntity]] = []
            for surface, entity in self._surfaces:
                if " " in surface or len(surface) < 4:
                    continue
                ratio = difflib.SequenceMatcher(None, token, surface).ratio()
                if ratio >= threshold:
                    scored.append((ratio, surface, entity))
            if not scored:
                continue
            highest = max(item[0] for item in scored)
            matches.extend(
                self._match(
                    entity,
                    surface=surface,
                    kind="fuzzy",
                    confidence=ratio,
                )
                for ratio, surface, entity in scored
                if highest - ratio <= ambiguity_margin
            )
        return sorted(
            self._dedupe(matches),
            key=lambda item: (-item.confidence, item.canonical_name, item.entity_id),
        )

    def resolved_matches(self, question: str) -> list[OntologyMatch]:
        exact = self.exact_matches(question)
        return exact or self.fuzzy_matches(question)

    def candidate_matches(
        self,
        question: str,
        *,
        limit: int = 16,
    ) -> list[OntologyMatch]:
        """Return a bounded catalog for ambiguity handling / LLM planning.

        Exact or safe-fuzzy matches lead.  Otherwise partial-token and moderate
        similarity candidates are offered; they are never confirmed here.
        """
        resolved = self.resolved_matches(question)
        if resolved:
            return resolved[:limit]
        tokens = [token for token in normalize_query(question).split() if len(token) >= 4]
        candidates: list[OntologyMatch] = []
        for surface, entity in self._surfaces:
            surface_tokens = surface.split()
            best = 0.0
            kind: MatchKind = "candidate"
            for token in tokens:
                if any(
                    token not in GENERIC_ENTITY_PARTS
                    and part not in GENERIC_ENTITY_PARTS
                    and part != token
                    and part.startswith(token)
                    for part in surface_tokens
                    if min(len(part), len(token)) >= 4
                ):
                    score = min(
                        len(token) / max(len(part), 1)
                        for part in surface_tokens
                        if (
                            token not in GENERIC_ENTITY_PARTS
                            and part not in GENERIC_ENTITY_PARTS
                            and part != token
                            and part.startswith(token)
                        )
                    )
                    if score > best:
                        best = score
                        kind = "partial"
                for part in surface_tokens:
                    ratio = difflib.SequenceMatcher(None, token, part).ratio()
                    if ratio >= 0.62 and ratio > best:
                        best = ratio * 0.8
                        kind = "candidate"
            if best:
                candidates.append(
                    self._match(
                        entity,
                        surface=surface,
                        kind=kind,
                        confidence=min(best, 0.84),
                    )
                )
        return sorted(
            self._dedupe(candidates),
            key=lambda item: (-item.confidence, item.canonical_name, item.entity_id),
        )[:limit]

    def candidate_catalog(self, question: str, *, limit: int = 16) -> list[str]:
        return [match.canonical_name for match in self.candidate_matches(question, limit=limit)]

    def collection_candidate_catalog(
        self,
        question: str,
        *,
        subject_entity_ids: tuple[str, ...] = (),
        limit: int = 16,
    ) -> list[str]:
        """Bounded collection names whose governed aliases fit the question.

        Subject ownership is a hard filter when the question resolved a known
        entity.  Ranking is lexical and deterministic; the external planner may
        choose only from the returned names.
        """
        normalized = normalize_query(question)
        question_tokens = set(normalized.split())
        subject_ids = set(subject_entity_ids)
        ranked: list[tuple[float, str]] = []
        for collection in self.collections:
            if (
                subject_ids
                and collection.subject_entity_ids
                and not subject_ids.intersection(collection.subject_entity_ids)
            ):
                continue
            best = 0.0
            for surface in (collection.canonical_name, *collection.aliases):
                candidate = normalize_query(surface)
                if not candidate:
                    continue
                if candidate in normalized or normalized in candidate:
                    best = max(best, 1.0)
                    continue
                candidate_tokens = set(candidate.split())
                union = question_tokens | candidate_tokens
                overlap = len(question_tokens & candidate_tokens) / len(union) if union else 0
                best = max(best, overlap)
            if best > 0:
                ranked.append((best, collection.canonical_name))
        return [
            name
            for _, name in sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]
        ]

    def canonical_names(self) -> frozenset[str]:
        return frozenset(entity.canonical_name for entity in self.entities)

    def legacy_aliases(self, *, entity_type: str | None = None) -> dict[str, list[str]]:
        return {
            entity.canonical_name: list(entity.aliases)
            for entity in self.entities
            if entity_type is None or entity.entity_type == entity_type
        }


DEFAULT_ONTOLOGY_PATH = Path(__file__).with_name("enterprise_ontology.json")


@lru_cache(maxsize=8)
def load_ontology(path: Path | None = None) -> EnterpriseOntology:
    return EnterpriseOntology.from_path(path or DEFAULT_ONTOLOGY_PATH)


async def load_runtime_ontology(
    factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    fallback_path: Path | None = None,
) -> EnterpriseOntology:
    """Load the governed active revision, or bootstrap when none exists.

    Database failures intentionally propagate. Falling back on an unavailable
    governance ledger could silently resurrect a superseded registry. The
    packaged file is used only for the explicit, observable no-active-revision
    state during bootstrap.
    """
    async with (factory or session_factory())() as session:
        payload = await session.scalar(
            text("""
            SELECT payload FROM enterprise_ontology_revisions
            WHERE state='active' ORDER BY activated_at DESC LIMIT 1
        """)
        )
    if payload is None:
        return load_ontology(fallback_path)
    return EnterpriseOntology(OntologySpec.model_validate(payload))
