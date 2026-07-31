import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFilters(StrictModel):
    source_key: str | None = None
    classification_ceiling: Literal[
        "public_internal",
        "internal",
        "restricted",
        "highly_restricted",
    ] | None = None
    provenance: list[str] = Field(default_factory=list, max_length=10)
    include_stale: bool = False


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=4096)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int | None = Field(default=None, ge=1, le=20)


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4096)
    conversation_id: uuid.UUID | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    require_verified: bool = True


class Citation(StrictModel):
    marker: str
    chunk_id: uuid.UUID
    record_key: str
    record_version_id: uuid.UUID
    evidence_key: str | None
    record_checksum: str
    evidence_checksum: str | None
    source_key: str
    source_revision: int
    provenance_level: str
    verification_state: str
    freshness_state: str
    source_label: str
    locator: dict[str, Any]
    redacted: bool = False


class RetrievalHit(StrictModel):
    chunk_id: uuid.UUID
    chunk_key: str
    snippet: str
    lexical_score: float
    vector_score: float
    fusion_score: float
    classification: str
    citation: Citation


class SearchResponse(StrictModel):
    results: list[RetrievalHit]
    request_id: str


class AskResponse(StrictModel):
    state: Literal["grounded", "honest_null", "failed"]
    answer: str
    citations: list[Citation]
    conversation_id: uuid.UUID
    answer_run_id: uuid.UUID
    gap_id: uuid.UUID | None = None
    request_id: str


class ProviderEvidence(StrictModel):
    marker: str
    text: str
    provenance_level: str
    verification_state: str
    freshness_state: str


class ProviderAnswer(StrictModel):
    answer: str = Field(max_length=12000)
    used_markers: list[str] = Field(min_length=1, max_length=20)
    follow_ups: list[str] = Field(default_factory=list, max_length=3)


class DLPDecision(StrictModel):
    allow: bool
    rule_ids: list[str]
    redacted: bool = False
    text: str | None = None


class ConversationMessage(StrictModel):
    message_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    answer_state: str | None
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime


class ConversationResponse(StrictModel):
    conversation_id: uuid.UUID
    messages: list[ConversationMessage]
    request_id: str


class ErrorDetail(StrictModel):
    code: str
    message: str


class KnowledgeErrorEnvelope(StrictModel):
    error: ErrorDetail
    request_id: str
