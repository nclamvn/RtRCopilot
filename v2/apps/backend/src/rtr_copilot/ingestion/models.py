from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

UploadState = Literal[
    "receiving",
    "quarantined",
    "validating",
    "scanning",
    "accepted",
    "rejected",
    "failed",
]
JobState = Literal[
    "pending",
    "leased",
    "running",
    "retry_wait",
    "succeeded",
    "failed",
    "quarantined",
    "cancelled",
]
QualityState = Literal["complete", "partial", "low_confidence"]


class SafeError(BaseModel):
    code: str
    retryable: bool = False
    message: str
    failed_stage: str | None = None


class ErrorEnvelope(BaseModel):
    error: SafeError
    request_id: str
    job_id: UUID | None = None


class UploadAccepted(BaseModel):
    upload_id: UUID
    job_id: UUID
    state: UploadState
    status_url: str
    request_id: str


class UploadStatus(BaseModel):
    upload_id: UUID
    job_id: UUID
    state: UploadState
    progress: int = Field(ge=0, le=100)
    retryable: bool
    error_code: str | None = None
    failed_stage: str | None = None
    document_id: UUID | None = None
    version_id: UUID | None = None
    detected_mime: str | None = None
    request_id: str


class RetryResponse(BaseModel):
    upload_id: UUID
    job_id: UUID
    state: JobState
    request_id: str


class ViewerCapabilities(BaseModel):
    preview: bool
    text: bool
    search_within_file: bool
    deep_link: bool
    download_original: bool


class ViewerRendition(BaseModel):
    rendition_id: UUID
    kind: str
    mime_type: str
    byte_size: int
    sha256: str
    quality_state: QualityState
    content_url: str


class ViewerManifest(BaseModel):
    schema_version: Literal[1] = 1
    version_id: UUID
    source_sha256: str
    detected_mime: str
    viewer_kind: str
    state: str
    capabilities: ViewerCapabilities
    renditions: list[ViewerRendition]
    locator_schema: Literal["rtr.locator.v1"] = "rtr.locator.v1"
    quality: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RenditionProvenance(BaseModel):
    schema_version: Literal[1] = 1
    source_version_id: UUID
    source_object_id: UUID
    source_sha256: str
    detected_mime: str
    output_rendition_id: UUID
    output_object_id: UUID
    output_sha256: str
    output_byte_size: int
    output_mime: str
    generator: str
    generator_version: str
    pipeline_version: str
    config_fingerprint: str
    created_at: datetime
    job_id: UUID
    attempt: int
    origin: Literal["native", "ocr", "transcript", "render"]
    locator_schema: Literal["rtr.locator.v1"] = "rtr.locator.v1"
    quality: dict[str, Any]
    warnings: list[str]
    truncated: bool
    partial: bool
    upstream_rendition_ids: list[UUID] = Field(default_factory=list)


class OCRRegion(BaseModel):
    page: int = Field(ge=1)
    region: str
    bounding_box: tuple[float, float, float, float]
    coordinate_system: Literal["pixel-top-left", "pdf-points-bottom-left"]
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)
    rotation_degrees: int = Field(ge=0, lt=360)
    language: str
    text: str
    confidence: float = Field(ge=0, le=1)
    origin: Literal["ocr"] = "ocr"


class OCRPayload(BaseModel):
    schema_version: Literal[1] = 1
    regions: list[OCRRegion]
    aggregate_confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    speaker_label: str | None = None
    origin: Literal["transcript"] = "transcript"

    @model_validator(mode="after")
    def valid_time_range(self) -> "TranscriptSegment":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms_must_follow_start_ms")
        return self


class TranscriptPayload(BaseModel):
    schema_version: Literal[1] = 1
    duration_ms: int = Field(gt=0)
    language: str | None = None
    segments: list[TranscriptSegment]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def segments_within_duration(self) -> "TranscriptPayload":
        if any(segment.end_ms > self.duration_ms for segment in self.segments):
            raise ValueError("segment_outside_duration")
        return self


class DetectionResult(BaseModel):
    detected_mime: str
    viewer_kind: str
    structural: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
