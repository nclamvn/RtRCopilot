import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFilters(StrictModel):
    source_key: str | None = None
    version_id: uuid.UUID | None = None
    classification_ceiling: Literal[
        "public_internal",
        "internal",
        "restricted",
        "highly_restricted",
    ] | None = None
    provenance: list[str] = Field(default_factory=list, max_length=10)
    include_stale: bool = False

    @model_validator(mode="after")
    def one_scope(self) -> "SearchFilters":
        if self.source_key is not None and self.version_id is not None:
            raise ValueError("source_key_and_version_id_are_mutually_exclusive")
        return self


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
    """Deep citation into SOT evidence (TIP-007, frozen retrieval semantics).

    ``zone_label`` (TIP-011 AC-07) is a server constant on the response model
    only: TIP-007 retrieval is SOT-only by construction (D-011-03), so every
    citation is structurally SOT-plane. Nothing is stored and no retrieval or
    grounding logic changes — the literal simply makes the existing invariant
    visible to clients.
    """

    zone_label: Literal["sot", "private"] = "sot"
    marker: str
    chunk_id: uuid.UUID
    record_key: str
    record_version_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
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
    # TIP-013B AC-3: additive answer-time metadata. True when this cited
    # record carries the soft-tier ``confidence_signal`` marker (Part A) and
    # its answer should surface the double-check caveat. Rides ALONG the
    # existing grounding — nothing about retrieval, ranking or DLP changes,
    # and it is never persisted (not stored on ``answer_citations``).
    needs_double_check: bool = False


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


AskOutcomeReason = Literal[
    "no_evidence",
    "denied_or_unavailable",
    "insufficient_confidence",
    "stale_only",
    "grounding_failed",
    "manual_entry",
    "answer_quality_configuration_required",
]


class AskResponse(StrictModel):
    state: Literal["grounded", "honest_null", "failed"]
    answer: str
    citations: list[Citation]
    conversation_id: uuid.UUID
    answer_run_id: uuid.UUID
    gap_id: uuid.UUID | None = None
    answer_mode: Literal["quality_llm", "evidence_only"] | None = None
    # Honest-null is an abstention, not necessarily a knowledge gap.  This
    # typed reason lets clients distinguish missing/unsafe evidence from an
    # unavailable answer-quality provider without inferring from prose.
    reason_code: AskOutcomeReason | None = None
    # TIP-013B AC-3: True iff the answer is grounded on at least one cited
    # record carrying the soft-tier ``needs_double_check`` marker (Part A).
    # Strict-only answers and honest-null answers stay False. Additive
    # response field only — no schema change, nothing stored.
    confidence_caveat: bool = False
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


class ConversationSummary(StrictModel):
    """DLP-safe conversation metadata for the caller's own list (TIP-011).

    ``first_question_digest`` is the first user message's ``content_sha256``
    exactly as TIP-007 already stores it — no new content is stored or
    disclosed by this surface.
    """

    conversation_id: uuid.UUID
    started_at: datetime
    last_activity_at: datetime
    first_question_digest: str | None = None


class ConversationListPage(StrictModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None
    request_id: str


class ErrorDetail(StrictModel):
    code: str
    message: str


class KnowledgeErrorEnvelope(StrictModel):
    error: ErrorDetail
    request_id: str
