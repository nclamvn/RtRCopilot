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

AnswerCoverageState = Literal["complete", "partial", "not_assessed"]

AskProgressStage = Literal[
    "understanding",
    "retrieving",
    "verifying",
    "synthesizing",
    "grounding",
]


class AskProgressSource(StrictModel):
    """Content-free summary of one already-authorized retrieval candidate."""

    marker: str = Field(pattern=r"^C\d{1,3}$", max_length=8)
    record_key: str = Field(min_length=1, max_length=500)
    source_label: str = Field(min_length=1, max_length=500)
    verification_state: str = Field(min_length=1, max_length=100)
    freshness_state: str = Field(min_length=1, max_length=100)


class AskProgressEvent(StrictModel):
    """Observable Ask checkpoint; never contains prompts, snippets or CoT."""

    stage: AskProgressStage
    status: Literal["started", "completed"]
    elapsed_ms: int = Field(ge=0)
    detail: str | None = Field(default=None, max_length=500)
    source_count: int = Field(default=0, ge=0, le=20)
    sources: list[AskProgressSource] = Field(default_factory=list, max_length=20)


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
    # Utility-first coverage is separate from grounding: ``partial`` still
    # means every rendered claim is cited, but not every configured facet or
    # collection member was available in the authorized evidence set.
    coverage_state: AnswerCoverageState = "not_assessed"
    # TIP-030: internal refusal decision label, populated on honest-null ONLY
    # when rag_expose_decision_diagnostics is enabled (isolated e2e stacks).
    # A fixed label such as "called_answer_irrelevant" — never evidence.
    decision_diagnostic: str | None = None
    request_id: str


class ProviderEvidence(StrictModel):
    marker: str
    text: str
    record_key: str | None = None
    provenance_level: str
    verification_state: str
    freshness_state: str


class ProviderAnswer(StrictModel):
    answer: str = Field(max_length=12000)
    used_markers: list[str] = Field(min_length=1, max_length=20)
    follow_ups: list[str] = Field(default_factory=list, max_length=3)
    # Internal-only trust signal. It is never rendered or persisted as answer
    # content. The reviewer is advisory because enterprise acceptance exposed
    # false negatives on correct evidence-bound answers; deterministic
    # grounding and coverage gates remain the final authority.
    review_state: Literal[
        "not_reviewed", "accepted", "advisory_rejected",
    ] = "not_reviewed"


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
