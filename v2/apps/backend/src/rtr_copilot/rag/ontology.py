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

MatchKind = Literal["exact", "fuzzy", "partial", "candidate"]


class OntologyEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    canonical_name: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    domain: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    aliases: tuple[str, ...] = ()
    definition_record_keys: tuple[str, ...] = ()
    lifecycle: Literal["active", "retired"] = "active"
    owner: str = Field(min_length=1, max_length=160)
    provenance_level: Literal["verified_primary", "approved_internal", "claim", "flagged"]

    @model_validator(mode="after")
    def aliases_are_meaningful(self) -> OntologyEntity:
        if any(not normalize_query(alias) for alias in self.aliases):
            raise ValueError("ontology_alias_empty_after_normalization")
        if any(
            not record_key.strip() or len(record_key) > 160
            for record_key in self.definition_record_keys
        ):
            raise ValueError("ontology_definition_record_key_invalid")
        if len(self.definition_record_keys) != len(set(self.definition_record_keys)):
            raise ValueError("ontology_definition_record_key_duplicate")
        return self


class OntologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    registry_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    owner: str = Field(min_length=1, max_length=160)
    entities: tuple[OntologyEntity, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def stable_ids_are_unique(self) -> OntologySpec:
        ids = [entity.entity_id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("ontology_entity_id_duplicate")
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
        self.by_canonical: dict[str, list[OntologyEntity]] = defaultdict(list)
        self._surface_index: dict[str, list[OntologyEntity]] = defaultdict(list)
        self._surfaces: list[tuple[str, OntologyEntity]] = []
        self._max_tokens = 1
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
        best: dict[str, OntologyMatch] = {}
        for match in matches:
            existing = best.get(match.entity_id)
            if existing is None or match.confidence > existing.confidence:
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
                        kind="exact",
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
                    part.startswith(token)
                    for part in surface_tokens
                    if min(len(part), len(token)) >= 4
                ):
                    score = min(
                        len(token) / max(len(part), 1)
                        for part in surface_tokens
                        if part.startswith(token)
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
