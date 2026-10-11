from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rtr_copilot.auth.models import Subject
from rtr_copilot.rag.use_class import UseClass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextError(RuntimeError):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code, self.status = code, status


class SOTReference(StrictModel):
    source_key: str = Field(min_length=2, max_length=128)
    record_key: str = Field(min_length=1, max_length=256)
    record_version_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_key: str | None = Field(default=None, min_length=1, max_length=256)


class ContextGap(StrictModel):
    code: Literal[
        "unavailable",
        "stale",
        "purpose_unavailable",
        "budget_limited",
        "memory_unavailable",
        "ambiguous",
        "ontology_changed",
    ]


class ExplicitRelation(StrictModel):
    subject_entity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    predicate: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    object_entity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    evidence_key: str = Field(min_length=1, max_length=256)


class RelationAssertion(ExplicitRelation):
    authority: Literal["source_assertion"] = "source_assertion"
    source: SOTReference


class ResolvedSOTSource(StrictModel):
    authority: Literal["sot"] = "sot"
    reference: SOTReference
    record_id: UUID
    owner_subject_id: UUID
    classification: str
    source_zone: Literal["sot"] = "sot"
    source_revision: int
    effective_from: datetime
    effective_to: datetime | None
    freshness_due_at: datetime | None
    retrieved_at: datetime
    text: str | None = None


class SourceResolution(StrictModel):
    subject: Subject
    sources: tuple[ResolvedSOTSource, ...]
    gaps: tuple[ContextGap, ...] = ()


class MemoryScope(StrictModel):
    kind: Literal["private", "project", "department"] = "private"
    key: UUID | None = None

    @model_validator(mode="after")
    def scope_shape(self) -> "MemoryScope":
        if (self.kind == "private") != (self.key is None):
            raise ValueError("context_scope_invalid")
        return self


class PacketRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    scope: MemoryScope = Field(default_factory=MemoryScope)
    use_class: UseClass = "proposal"
    source_keys: tuple[str, ...] = Field(default=(), max_length=10)
    max_bytes: int = Field(default=16_384, ge=1024, le=65_536)
    max_estimated_tokens: int = Field(default=4096, ge=256, le=16_384)
    include_memory: bool = True

    @model_validator(mode="after")
    def source_boundaries(self) -> "PacketRequest":
        if any(not key.strip() or len(key) > 128 for key in self.source_keys):
            raise ValueError("context_source_key_invalid")
        if len(set(self.source_keys)) != len(self.source_keys):
            raise ValueError("context_source_key_duplicate")
        return self


class EntityProjection(StrictModel):
    authority: Literal["ontology_projection"] = "ontology_projection"
    entity_id: str
    canonical_name: str
    entity_type: str
    domain: str
    references: tuple[SOTReference, ...]


class MemoryCreate(StrictModel):
    scope: MemoryScope = Field(default_factory=MemoryScope)
    kind: Literal["preference", "task_note", "inference"]
    text: str = Field(min_length=1, max_length=2000)
    references: tuple[SOTReference, ...] = Field(default=(), max_length=20)
    use_class: UseClass = "proposal"
    expires_at: datetime

    @model_validator(mode="after")
    def bounded_memory(self) -> "MemoryCreate":
        if self.expires_at.tzinfo is None:
            raise ValueError("memory_timezone_required")
        if len(self.text.encode("utf-8")) > 8000:
            raise ValueError("memory_byte_budget")
        if self.kind == "inference" and not self.references:
            raise ValueError("memory_inference_references_required")
        if len({ref.record_version_id for ref in self.references}) != len(self.references):
            raise ValueError("memory_reference_duplicate")
        return self


class MemoryCorrection(MemoryCreate):
    expected_revision: int = Field(ge=1)


class MemoryView(StrictModel):
    authority: Literal["workspace_memory"] = "workspace_memory"
    memory_id: UUID
    owner_subject_id: UUID
    scope: MemoryScope
    kind: Literal["preference", "task_note", "inference"]
    text: str | None
    references: tuple[SOTReference, ...]
    use_class: UseClass
    revision: int
    lifecycle: Literal["active", "deleted", "expired", "withheld"]
    expires_at: datetime
    updated_at: datetime


class MemoryTombstone(StrictModel):
    memory_id: UUID
    revision: int
    lifecycle: Literal["deleted"] = "deleted"


class ContextPacket(StrictModel):
    packet_id: UUID
    caller_id: UUID
    scope: MemoryScope
    use_class: UseClass
    ontology_digest: str
    retrieved_at: datetime
    sources: tuple[ResolvedSOTSource, ...] = ()
    entities: tuple[EntityProjection, ...] = ()
    relations: tuple[RelationAssertion, ...] = ()
    notes: tuple[MemoryView, ...] = ()
    gaps: tuple[ContextGap, ...] = ()
    coverage: Literal["supported", "partial", "unavailable"] = "unavailable"
    truncated: bool = False
    max_bytes: int
    max_estimated_tokens: int
    estimated_tokens: int = 0
    token_measurement: Literal["utf8_bytes_div4_estimate_not_provider_usage"] = (
        "utf8_bytes_div4_estimate_not_provider_usage"
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
