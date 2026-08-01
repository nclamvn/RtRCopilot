import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Classification = Literal[
    "public_internal",
    "internal",
    "restricted",
    "highly_restricted",
]
ResearchOrigin = Literal["refinery", "manual", "partner"]
ResearchSourceLifecycle = Literal["active", "suspended", "retired"]
PackageImportState = Literal["received", "validating", "imported", "rejected"]
ResearchTier = Literal["P", "S", "H", "X"]
ResearchZone = Literal["research"]
CorroborationState = Literal["uncorroborated", "corroborated", "disputed"]
GapOrigin = Literal["honest_null", "manual"]
GapState = Literal["open", "triaged", "assigned", "answered", "published", "declined"]
LegacyGapState = Literal["resolved", "dismissed"]
GapPriority = Literal["low", "normal", "high", "urgent"]
GapReasonCategory = Literal[
    "no_evidence",
    "denied_or_unavailable",
    "insufficient_confidence",
    "stale_only",
    "grounding_failed",
    "manual_entry",
]
QueueKind = Literal["freshness", "conflict", "owner_review"]
ReviewTaskState = Literal["assigned", "completed", "reopened"]
ProposalState = Literal["proposed", "approved", "rejected"]
ProposalDecision = Literal["approved", "rejected"]
SettingValueType = Literal["integer", "decimal", "boolean", "string", "duration_hours"]
SettingValue = int | float | bool | str

RESEARCH_ZONE_LABEL: ResearchZone = "research"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchSource(StrictModel):
    source_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    origin: ResearchOrigin
    owner_subject_id: uuid.UUID
    classification: Classification
    lifecycle: ResearchSourceLifecycle = "active"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ResearchPackage(StrictModel):
    package_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_manifest: dict[str, Any]
    captured_at: datetime
    snapshot_scope: str = Field(min_length=1, max_length=512)
    adapter_version: str = Field(pattern=r"^[a-z0-9._-]{1,64}$")
    tier_composition: dict[str, int] = Field(default_factory=dict)
    import_state: PackageImportState = "received"
    rejection_code: str | None = None
    record_count: int = Field(default=0, ge=0)
    importer_subject_id: uuid.UUID
    received_at: datetime = Field(default_factory=_utcnow)
    imported_at: datetime | None = None


class PackageIntake(StrictModel):
    """Result of a fingerprint-idempotent package registration."""

    package: ResearchPackage
    created: bool


class ResearchEvidenceSpan(StrictModel):
    source_url: str = Field(min_length=1, max_length=2048)
    locator: dict[str, Any]
    quoted_text: str = Field(min_length=1, max_length=200_000)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResearchRecord(StrictModel):
    research_record_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    package_id: uuid.UUID
    record_key: str = Field(min_length=1, max_length=256)
    version_ordinal: int = Field(gt=0)
    tier: ResearchTier
    zone_label: ResearchZone = RESEARCH_ZONE_LABEL
    content: dict[str, Any]
    searchable_text: str = Field(max_length=200_000)
    evidence_spans: list[ResearchEvidenceSpan] = Field(min_length=1, max_length=1000)
    corroboration_state: CorroborationState = "uncorroborated"
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=_utcnow)


class Gap(StrictModel):
    gap_id: uuid.UUID
    question_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    sanitized_question: str
    sanitized_summary: str
    reason_category: GapReasonCategory
    classification: Classification
    requester_id: uuid.UUID
    owner_subject_id: uuid.UUID | None = None
    routing_key: str
    occurrence_count: int = Field(ge=1)
    lifecycle: GapState | LegacyGapState
    answer_run_id: uuid.UUID | None = None
    resolving_record_id: uuid.UUID | None = None
    origin: GapOrigin = "honest_null"
    priority: GapPriority = "normal"
    first_seen_at: datetime
    last_seen_at: datetime
    triaged_at: datetime | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    answered_at: datetime | None = None
    closed_at: datetime | None = None
    resolving_version_id: uuid.UUID | None = None
    decline_reason: str | None = None


class GapPage(StrictModel):
    items: list[Gap]
    next_cursor: str | None = None


class GapTransition(StrictModel):
    sequence: int
    transition_id: uuid.UUID
    gap_id: uuid.UUID
    from_state: GapState
    to_state: GapState
    actor_subject_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime


class ReviewTask(StrictModel):
    task_id: uuid.UUID
    queue_kind: QueueKind
    record_version_id: uuid.UUID
    assignee_subject_id: uuid.UUID
    assigned_by: uuid.UUID
    state: ReviewTaskState
    due_at: datetime | None = None
    note: str = Field(default="", max_length=2000)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class GraduationProposal(StrictModel):
    proposal_id: uuid.UUID
    research_record_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    claim_draft: dict[str, Any]
    target_record_key: str = Field(min_length=1, max_length=256)
    proposer_subject_id: uuid.UUID
    rationale: str = Field(min_length=1, max_length=4000)
    state: ProposalState = "proposed"
    decided_by: uuid.UUID | None = None
    decision_reason: str | None = None
    attestation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    publish_package_id: uuid.UUID | None = None
    supersedes_proposal_id: uuid.UUID | None = None
    proposed_at: datetime
    decided_at: datetime | None = None


class GovernanceSetting(StrictModel):
    setting_id: uuid.UUID
    setting_key: str = Field(pattern=r"^[a-z][a-z0-9._]{1,127}$")
    version: int = Field(gt=0)
    value_type: SettingValueType
    value: SettingValue
    updated_by: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)
    created_at: datetime
