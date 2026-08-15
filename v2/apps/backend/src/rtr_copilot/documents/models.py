import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class FieldRules(StrictModel):
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)
    # JSONB stores Decimal bounds as strings. These two fields deliberately
    # accept that canonical round-trip while the surrounding schema stays strict.
    minimum: Decimal | None = Field(default=None, strict=False)
    maximum: Decimal | None = Field(default=None, strict=False)
    enum: list[str] = Field(default_factory=list, max_length=100)
    max_items: int | None = Field(default=None, ge=1, le=500)
    max_rows: int | None = Field(default=None, ge=1, le=5_000)


class BindingDefinition(StrictModel):
    field_path: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,127}$")
    field_type: Literal[
        "string", "multiline", "integer", "decimal", "boolean", "date",
        "enum", "list", "table",
    ]
    source: Literal["user", "locked_fact", "derived"]
    required: bool = False
    rules: FieldRules = Field(default_factory=FieldRules)
    record_key: str | None = Field(default=None, min_length=1, max_length=256)
    accepted_provenance: list[
        Literal["verified_primary", "verified_secondary", "approved_internal"]
    ] = Field(default_factory=list, max_length=3)
    require_fresh: bool = True
    value_template: str | None = Field(default=None, min_length=1, max_length=500)
    value_literal: str | None = Field(default=None, min_length=1, max_length=500)
    derived_operation: Literal[
        "concat", "date_day", "date_month", "date_year",
    ] | None = None
    derived_fields: list[str] = Field(default_factory=list, max_length=20)


class TemplateSchema(StrictModel):
    schema_version: Literal[1] = 1
    bindings: list[BindingDefinition] = Field(min_length=1, max_length=200)


class TemplateImport(StrictModel):
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    category: str = Field(min_length=1, max_length=100)
    classification: Literal[
        "public_internal", "internal", "restricted", "highly_restricted",
    ] = "internal"
    document_class: Literal["internal", "official", "legal"] = "internal"
    format: Literal["docx", "xlsx", "pptx", "pdf"]
    field_schema: TemplateSchema = Field(alias="schema")
    source_base64: str = Field(min_length=4, max_length=70_000_000)


class TemplateListItem(StrictModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    stable_key: str
    display_name: str
    category: str
    classification: str
    document_class: str
    format: str
    version_ordinal: int
    status: str
    owner_display_name: str | None


class TemplatePage(StrictModel):
    items: list[TemplateListItem]
    next_cursor: str | None = None


ArtifactKind = Literal["document", "report", "form", "presentation", "spreadsheet"]
ArtifactPlanState = Literal[
    "not_applicable", "clarification_required", "no_approved_template", "ready",
]


class ArtifactPlanRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=4_096)


class ArtifactTemplateCandidate(StrictModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    format: Literal["docx", "xlsx", "pptx", "pdf"]
    document_class: Literal["internal", "official", "legal"]
    required_user_fields: list[str] = Field(default_factory=list, max_length=200)


class ArtifactPlanResponse(StrictModel):
    state: ArtifactPlanState
    artifact_kind: ArtifactKind | None = None
    candidates: list[ArtifactTemplateCandidate] = Field(default_factory=list, max_length=3)
    confirmation_required: bool = True
    request_id: str = Field(min_length=1, max_length=128)


class TemplateVersionDetail(StrictModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    source_sha256: str
    renderer_kind: str
    renderer_version: str
    status: str
    field_schema: TemplateSchema = Field(alias="schema")


class TemplateVersionSummary(StrictModel):
    version_id: uuid.UUID
    version_ordinal: int
    format: str
    source_sha256: str
    renderer_version: str
    status: str
    created_at: datetime
    approved_at: datetime | None


class TemplateHistory(StrictModel):
    template_id: uuid.UUID
    versions: list[TemplateVersionSummary]


FieldValue = str | int | float | bool | date | list[Any] | dict[str, Any] | None


class BindRequest(StrictModel):
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=200)
    extraction_text: str | None = Field(default=None, max_length=20_000)


class BoundField(StrictModel):
    field_path: str
    source: str
    value: Any
    record_key: str | None = None
    record_version_id: uuid.UUID | None = None
    record_checksum: str | None = None
    evidence_key: str | None = None
    evidence_checksum: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    provenance_level: str | None = None
    verification_state: str | None = None
    freshness_state: str | None = None
    confidence: float | None = None
    source_span: tuple[int, int] | None = None


class BindResult(StrictModel):
    valid: bool
    fields: list[BoundField]
    missing: list[str]
    blocked: list[dict[str, str]]
    sot_revision: int | None = None


class RenderRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=200)


class RenderStatus(StrictModel):
    render_job_id: uuid.UUID
    state: str
    progress: int
    generated_file_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    checksum: str | None = None
    error_code: str | None = None


class DecisionRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=2_000)


class IssuanceResult(StrictModel):
    issuance_id: uuid.UUID
    issue_number: str
    state: Literal["issued", "revoked"]
    checksum: str
    at: datetime


class ApprovalEvent(StrictModel):
    approval_id: uuid.UUID
    stage: str
    reviewer_subject_id: uuid.UUID
    reviewer_display_name: str | None
    decision: str
    checksum: str
    reason: str
    decided_at: datetime


class GeneratedVersionDetail(StrictModel):
    generated_file_id: uuid.UUID
    render_job_id: uuid.UUID
    template_version_id: uuid.UUID
    version_id: uuid.UUID
    output_format: str
    checksum: str
    lifecycle: str
    render_manifest: dict[str, Any]
    created_at: datetime
    approvals: list[ApprovalEvent]
    issuance: IssuanceResult | None = None


class GeneratedComparison(StrictModel):
    previous_generated_file_id: uuid.UUID | None
    changed_parameters: list[str]
    changed_locked_facts: list[str]
    template_changed: bool
    checksum_changed: bool
    lifecycle_changed: bool


class GeneratedHistoryItem(StrictModel):
    generated_file_id: uuid.UUID
    template_version_id: uuid.UUID
    version_id: uuid.UUID
    lifecycle: str
    checksum: str
    created_at: datetime
    parameters: dict[str, Any]
    locked_snapshots: dict[str, dict[str, Any]]
    comparison: GeneratedComparison


class GeneratedHistory(StrictModel):
    template_id: uuid.UUID
    items: list[GeneratedHistoryItem]
