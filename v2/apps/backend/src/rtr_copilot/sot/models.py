import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Classification = Literal[
    "public_internal",
    "internal",
    "restricted",
    "highly_restricted",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestMember(StrictModel):
    path: str
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PackageManifest(StrictModel):
    schema_version: str
    package_id: uuid.UUID
    source_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    revision: int = Field(gt=0)
    trust_zone: Literal["sot"]
    producer: str = Field(min_length=1, max_length=256)
    generated_at: datetime
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    members: list[ManifestMember]


class SourceFingerprint(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: Classification


class PackageACL(StrictModel):
    principal_type: Literal["user", "group", "role", "department", "project"]
    principal_id: uuid.UUID
    action: str = Field(min_length=1, max_length=64)
    effect: Literal["allow", "deny"]


class PackageRecord(StrictModel):
    record_key: str = Field(min_length=1, max_length=256)
    version_ordinal: int = Field(gt=0)
    owner_id: uuid.UUID
    classification: Classification
    department_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    value: Any
    searchable_text: str = Field(max_length=200_000)
    provenance_level: Literal[
        "verified_primary",
        "verified_secondary",
        "approved_internal",
        "claim",
    ]
    confidence: float = Field(ge=0, le=1)
    verification_state: Literal["verified", "approved", "claim"]
    fact_state: Literal[
        "approved",
        "verified",
        "claim",
        "flagged",
        "placeholder",
        "unspecified",
        "conflict",
    ]
    effective_from: datetime
    effective_to: datetime | None = None
    freshness_policy: dict[str, Any] = Field(default_factory=dict)
    freshness_due_at: datetime | None = None
    evidence_keys: list[str] = Field(default_factory=list, max_length=1000)
    source_refs: list[str] = Field(min_length=1, max_length=1000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_record_key: str | None = None
    acl: list[PackageACL] = Field(min_length=1, max_length=1000)


class PackageEvidence(StrictModel):
    evidence_key: str = Field(min_length=1, max_length=256)
    record_key: str = Field(min_length=1, max_length=256)
    source_ref: str = Field(min_length=1, max_length=512)
    source_document_id: uuid.UUID | None = None
    source_version_id: uuid.UUID | None = None
    source_blob_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    locator: dict[str, Any]
    quoted_text: str = Field(min_length=1, max_length=200_000)
    normalized_text: str = Field(min_length=1, max_length=200_000)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_label: str = Field(min_length=1, max_length=512)
    classification: Classification


class PublishAttestation(StrictModel):
    package_id: uuid.UUID
    revision: int = Field(gt=0)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validator_version: str
    schema_version: str
    policy_version: str
    validated_at: datetime
    curator_subject_id: uuid.UUID
    decision: Literal["approved"]
    expires_at: datetime | None = None
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class Finding(StrictModel):
    code: str
    subject: str


class ValidationReport(StrictModel):
    valid: bool
    validator_version: str
    policy_version: str
    findings: list[Finding]
    record_count: int
    evidence_count: int
    source_count: int
    deterministic_checksum: str


class ParsedPackage(StrictModel):
    root_name: str
    manifest: PackageManifest
    manifest_sha256: str
    records: list[PackageRecord]
    evidence: list[PackageEvidence]
    source_hashes: dict[str, SourceFingerprint]
    attestation: PublishAttestation


class PublishResult(StrictModel):
    package_id: uuid.UUID
    run_id: uuid.UUID
    source_key: str
    revision: int
    state: str
    idempotent: bool = False


class ActiveEvidence(StrictModel):
    evidence_key: str
    locator: dict[str, Any]
    quoted_text: str
    source_label: str
    evidence_sha256: str


class ActiveRecord(StrictModel):
    record_key: str
    value: Any
    searchable_text: str
    provenance_level: str
    verification_state: str
    effective_from: datetime
    effective_to: datetime | None
    freshness_state: str
    content_sha256: str
    evidence: list[ActiveEvidence] = Field(default_factory=list)
