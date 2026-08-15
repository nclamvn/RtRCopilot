"""Strict public contracts for the TIP-038 intelligence briefing."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IntelligenceZone = Literal["sot", "research"]
IntelligenceKind = Literal["update", "attention", "research"]
IntelligencePriority = Literal["high", "normal"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntelligenceEvidence(StrictModel):
    zone_label: IntelligenceZone
    record_key: str = Field(min_length=1, max_length=256)
    source_key: str = Field(min_length=1, max_length=256)
    source_label: str = Field(min_length=1, max_length=512)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: dict[str, object] = Field(default_factory=dict)
    record_version_id: uuid.UUID | None = None
    source_revision: int | None = Field(default=None, gt=0)
    provenance_level: str | None = Field(default=None, max_length=64)
    verification_state: str | None = Field(default=None, max_length=64)
    freshness_state: str | None = Field(default=None, max_length=64)
    research_record_id: uuid.UUID | None = None
    package_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    tier: str | None = Field(default=None, pattern=r"^[PSHX]$")
    corroboration_state: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def enforce_zone_identity(self) -> IntelligenceEvidence:
        if self.zone_label == "sot":
            if self.record_version_id is None or self.source_revision is None:
                raise ValueError("sot_evidence_identity_required")
            if self.research_record_id is not None or self.package_fingerprint is not None:
                raise ValueError("mixed_evidence_zone")
        else:
            if self.research_record_id is None or self.package_fingerprint is None:
                raise ValueError("research_evidence_identity_required")
            if self.record_version_id is not None or self.source_revision is not None:
                raise ValueError("mixed_evidence_zone")
        return self


class IntelligenceItem(StrictModel):
    item_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    zone_label: IntelligenceZone
    kind: IntelligenceKind
    priority: IntelligencePriority
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=700)
    observed_at: datetime
    ask_query: str = Field(min_length=1, max_length=500)
    evidence: IntelligenceEvidence

    @model_validator(mode="after")
    def enforce_kind_zone(self) -> IntelligenceItem:
        if self.kind == "research" and self.zone_label != "research":
            raise ValueError("research_kind_zone_mismatch")
        if self.kind != "research" and self.zone_label != "sot":
            raise ValueError("sot_kind_zone_mismatch")
        if self.evidence.zone_label != self.zone_label:
            raise ValueError("item_evidence_zone_mismatch")
        return self


class IntelligenceCounts(StrictModel):
    updates: int = Field(ge=0)
    attention: int = Field(ge=0)
    research: int = Field(ge=0)


class IntelligenceBriefing(StrictModel):
    generated_at: datetime
    items: list[IntelligenceItem] = Field(max_length=20)
    counts: IntelligenceCounts
    request_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def enforce_aggregate_counts(self) -> IntelligenceBriefing:
        actual = {
            "updates": sum(item.kind == "update" for item in self.items),
            "attention": sum(item.kind == "attention" for item in self.items),
            "research": sum(item.kind == "research" for item in self.items),
        }
        if self.counts.model_dump() != actual:
            raise ValueError("intelligence_counts_mismatch")
        return self
