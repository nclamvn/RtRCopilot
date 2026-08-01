"""Research-zone view models: every content-bearing shape carries the zone label.

The ``zone_label`` fields are typed ``Literal["research"]`` so no code path can
construct a research payload that presents itself as anything else — forging a
different zone raises a validation error before serialization (AC-07).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from rtr_copilot.governance.models import (
    Classification,
    CorroborationState,
    GraduationProposal,
    PackageImportState,
    ResearchTier,
    StrictModel,
)

ResearchZoneLabel = Literal["research"]


class ResearchPackageView(StrictModel):
    zone_label: ResearchZoneLabel = "research"
    package_id: uuid.UUID
    source_key: str
    fingerprint: str
    payload_sha256: str
    captured_at: datetime
    snapshot_scope: str
    adapter_version: str
    tier_composition: dict[str, int]
    import_state: PackageImportState
    rejection_code: str | None
    record_count: int
    received_at: datetime
    imported_at: datetime | None


class ResearchPackagePage(StrictModel):
    items: list[ResearchPackageView]
    next_cursor: str | None = None


class ResearchImportResult(StrictModel):
    package: ResearchPackageView
    created: bool
    idempotent: bool = False


class ResearchEvidenceView(StrictModel):
    source_url: str
    locator: dict[str, Any]
    quoted_text: str
    checksum: str


class ResearchRecordView(StrictModel):
    zone_label: ResearchZoneLabel = "research"
    research_record_id: uuid.UUID
    package_id: uuid.UUID
    package_fingerprint: str
    source_key: str
    record_key: str
    version_ordinal: int
    tier: ResearchTier
    content: dict[str, Any]
    searchable_text: str
    evidence: list[ResearchEvidenceView]
    corroboration_state: CorroborationState
    content_sha256: str
    created_at: datetime


class ResearchRecordPage(StrictModel):
    items: list[ResearchRecordView]
    next_cursor: str | None = None


class ResearchCitation(StrictModel):
    """Citation for research content; the zone label is structurally constant."""

    zone_label: ResearchZoneLabel = "research"
    research_record_id: uuid.UUID
    record_key: str
    version_ordinal: int
    tier: ResearchTier
    source_key: str
    package_fingerprint: str
    content_sha256: str
    corroboration_state: CorroborationState
    evidence_checksums: list[str]


class ResearchHit(StrictModel):
    zone_label: ResearchZoneLabel = "research"
    research_record_id: uuid.UUID
    record_key: str
    tier: ResearchTier
    snippet: str
    lexical_score: float
    citation: ResearchCitation


class ResearchSearchResponse(StrictModel):
    """Explicitly research-scoped result set; grounding metadata is constant."""

    zone_label: ResearchZoneLabel = "research"
    grounding: Literal["research_supported"] = "research_supported"
    results: list[ResearchHit]
    request_id: str


class CandidateClaim(StrictModel):
    """Target SOT record shape a graduation proposal drafts (stored claim_draft)."""

    claim_text: str = Field(min_length=1, max_length=4000)
    value: dict[str, Any] = Field(default_factory=dict)
    classification: Classification
    confidence: float = Field(default=0.5, ge=0, le=1)
    version_ordinal: int = Field(default=1, gt=0)
    owner_subject_id: uuid.UUID | None = None


class GraduationProposalInput(StrictModel):
    research_record_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    claim: CandidateClaim
    target_record_key: str = Field(min_length=1, max_length=256)
    rationale: str = Field(min_length=1, max_length=4000)
    supersedes_proposal_id: uuid.UUID | None = None


class GraduationProposalPage(StrictModel):
    items: list[GraduationProposal]
    next_cursor: str | None = None
