"""Strict, domain-neutral contracts for TIP-025 governance ledgers."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rtr_copilot.governance.models import Classification
from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.ontology import OntologySpec

DomainState = Literal["proposed", "active", "rejected", "suspended", "retired"]
CorpusState = Literal["proposed", "validated", "active", "rejected", "superseded"]
OntologyState = Literal["proposed", "approved", "rejected", "active", "superseded"]
SuiteState = Literal["proposed", "approved", "rejected", "retired"]
EvaluationStatus = Literal["passed", "failed", "incomplete"]
RiskClass = Literal["critical", "high", "standard"]
EvaluationKind = Literal["query", "retrieval", "answer"]
ResolutionState = Literal["resolved", "open", "clarification_required"]
AnswerState = Literal["grounded", "honest_null"]
SourceKind = Literal["sot", "research"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class CorpusSourceRef(StrictModel):
    kind: SourceKind
    source_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorpusManifestSpec(StrictModel):
    schema_version: Literal[1] = 1
    domain_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    sources: tuple[CorpusSourceRef, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def source_refs_are_unique(self) -> CorpusManifestSpec:
        identities = [(item.kind, item.source_key) for item in self.sources]
        if len(identities) != len(set(identities)):
            raise ValueError("enterprise_source_ref_duplicate")
        return self

    def canonical(self) -> CorpusManifestSpec:
        return self.model_copy(
            update={
                "sources": tuple(
                    sorted(self.sources, key=lambda item: (item.kind, item.source_key))
                ),
            }
        )

    @property
    def digest(self) -> str:
        return digest_of(self.canonical())


class EvaluationExpectation(StrictModel):
    resolution_state: ResolutionState | None = None
    entity_ids: tuple[str, ...] = ()
    required_record_keys: tuple[str, ...] = ()
    forbidden_record_keys: tuple[str, ...] = ()
    answer_state: AnswerState | None = None
    required_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def fields_match_kind_agnostic_contract(self) -> EvaluationExpectation:
        if set(self.required_record_keys) & set(self.forbidden_record_keys):
            raise ValueError("enterprise_eval_record_expectation_conflict")
        if any(not normalize_query(term) for term in self.required_terms):
            raise ValueError("enterprise_eval_required_term_empty")
        return self


class EvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    domain_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    risk_class: RiskClass
    kind: EvaluationKind
    question: str = Field(min_length=2, max_length=4000)
    expectation: EvaluationExpectation

    @model_validator(mode="after")
    def expectation_matches_kind(self) -> EvaluationCase:
        expected = self.expectation
        if self.kind == "query" and expected.resolution_state is None:
            raise ValueError("enterprise_eval_query_expectation_missing")
        if self.kind == "retrieval" and not (
            expected.required_record_keys or expected.forbidden_record_keys
        ):
            raise ValueError("enterprise_eval_retrieval_expectation_missing")
        if self.kind == "answer" and expected.answer_state is None:
            raise ValueError("enterprise_eval_answer_expectation_missing")
        return self


class EvaluationSuiteSpec(StrictModel):
    schema_version: Literal[1] = 1
    suite_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> EvaluationSuiteSpec:
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("enterprise_eval_case_duplicate")
        return self

    def coverage_errors(self, minimums: dict[str, int]) -> list[str]:
        counts = Counter(item.domain_key for item in self.cases)
        critical = {item.domain_key for item in self.cases if item.risk_class == "critical"}
        kinds: dict[str, set[EvaluationKind]] = defaultdict(set)
        for case in self.cases:
            kinds[case.domain_key].add(case.kind)
        errors: list[str] = []
        for domain_key, minimum in sorted(minimums.items()):
            if counts[domain_key] < minimum:
                errors.append(f"domain_minimum:{domain_key}")
            if domain_key not in critical:
                errors.append(f"domain_critical_missing:{domain_key}")
            for kind in ("query", "retrieval", "answer"):
                if kind not in kinds[domain_key]:
                    errors.append(f"domain_kind_missing:{domain_key}:{kind}")
        unknown = set(counts) - set(minimums)
        errors.extend(f"domain_unknown:{item}" for item in sorted(unknown))
        return errors

    def ambiguity_coverage_errors(self, ontology: OntologySpec) -> list[str]:
        collisions: dict[str, set[str]] = defaultdict(set)
        for entity in ontology.entities:
            for surface in (entity.canonical_name, *entity.aliases):
                collisions[normalize_query(surface)].add(entity.entity_id)
        ambiguous = {surface for surface, ids in collisions.items() if len(ids) > 1}
        covered = {
            normalize_query(case.question)
            for case in self.cases
            if case.kind == "query"
            and case.expectation.resolution_state == "clarification_required"
        }
        return [
            f"ontology_ambiguity_uncovered:{digest_of(surface)[:16]}"
            for surface in sorted(ambiguous)
            if not any(surface in question for question in covered)
        ]

    @property
    def digest(self) -> str:
        ordered = self.model_copy(
            update={
                "cases": tuple(sorted(self.cases, key=lambda item: item.case_id)),
            }
        )
        return digest_of(ordered)


class DomainCreate(StrictModel):
    domain_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,127}$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    owner_subject_id: uuid.UUID
    classification: Classification = "internal"
    minimum_eval_cases: int = Field(default=3, ge=1, le=1000)


class DecisionInput(StrictModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


class OntologyRevisionCreate(StrictModel):
    version: int = Field(gt=0)
    ontology: OntologySpec


class EvaluationSuiteCreate(StrictModel):
    version: int = Field(gt=0)
    suite: EvaluationSuiteSpec


class EvaluationRunRequest(StrictModel):
    ontology_revision_id: uuid.UUID


class OntologyActivationRequest(StrictModel):
    evaluation_run_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)


class DomainRecord(StrictModel):
    domain_id: uuid.UUID
    domain_key: str
    display_name: str
    description: str
    owner_subject_id: uuid.UUID
    classification: Classification
    minimum_eval_cases: int
    state: DomainState
    proposed_by: uuid.UUID
    approved_by: uuid.UUID | None
    decision_reason: str | None
    proposed_at: datetime
    decided_at: datetime | None
    updated_at: datetime


class CorpusManifestRecord(StrictModel):
    manifest_id: uuid.UUID
    domain_id: uuid.UUID
    version: int
    manifest_digest: str
    sources: tuple[CorpusSourceRef, ...]
    source_count: int
    state: CorpusState
    validated_snapshot_digest: str | None
    proposed_by: uuid.UUID
    validated_by: uuid.UUID | None
    decided_by: uuid.UUID | None
    decision_reason: str | None
    proposed_at: datetime
    validated_at: datetime | None
    decided_at: datetime | None


class OntologyRevisionRecord(StrictModel):
    revision_id: uuid.UUID
    registry_id: str
    version: int
    ontology_digest: str
    payload: OntologySpec
    entity_count: int
    state: OntologyState
    proposed_by: uuid.UUID
    decided_by: uuid.UUID | None
    decision_reason: str | None
    activated_by: uuid.UUID | None
    evaluation_run_id: uuid.UUID | None
    proposed_at: datetime
    decided_at: datetime | None
    activated_at: datetime | None


class EvaluationSuiteRecord(StrictModel):
    suite_id: uuid.UUID
    suite_key: str
    version: int
    suite_digest: str
    definition: EvaluationSuiteSpec
    case_count: int
    domain_count: int
    state: SuiteState
    proposed_by: uuid.UUID
    decided_by: uuid.UUID | None
    decision_reason: str | None
    proposed_at: datetime
    decided_at: datetime | None


class EvaluationRunRecord(StrictModel):
    run_id: uuid.UUID
    suite_id: uuid.UUID
    ontology_revision_id: uuid.UUID
    ontology_digest: str
    suite_digest: str
    corpus_snapshot_digest: str
    evaluation_subject_digest: str
    status: EvaluationStatus
    passed_count: int
    failed_count: int
    critical_failed_count: int
    domain_metrics: dict[str, Any]
    result_payload: dict[str, Any]
    result_digest: str
    executed_by: uuid.UUID
    started_at: datetime
    finished_at: datetime


class ReleaseAttestation(StrictModel):
    attestation_id: uuid.UUID
    registry_id: str
    ontology_revision_id: uuid.UUID
    evaluation_run_id: uuid.UUID
    ontology_digest: str
    corpus_snapshot_digest: str
    suite_digest: str
    result_digest: str
    release_digest: str
    state: Literal["active", "superseded"]
    approved_by: uuid.UUID
    activated_at: datetime


class EnterpriseReadiness(StrictModel):
    ready: bool
    code: str
    active_domain_count: int
    active_manifest_count: int
    active_ontology_digest: str | None = None
    corpus_snapshot_digest: str | None = None
    release_digest: str | None = None
    drifted_source_count: int = 0


class ValidationResult(StrictModel):
    manifest: CorpusManifestRecord
    snapshot_digest: str
