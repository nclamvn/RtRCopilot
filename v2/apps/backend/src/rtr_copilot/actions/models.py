import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rtr_copilot.context.models import SOTReference
from rtr_copilot.rag.use_class import UseClass

EffectClass = Literal["R0", "R1", "R2", "R3"]
PolicyAction = Literal["view", "render", "approve"]
ContractState = Literal["contract_ready", "awaiting_approval", "cancelled"]
CONTRACT_BUILD: Literal["rtr-action-contracts-1"] = "rtr-action-contracts-1"
RequestUUID = Annotated[uuid.UUID, Field(strict=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BudgetUnits(StrictModel):
    tool_calls: int = Field(default=0, ge=0, le=20)
    model_calls: int = Field(default=0, ge=0, le=4)
    tokens: int = Field(default=0, ge=0, le=64_000)
    wall_seconds: int = Field(default=0, ge=0, le=600)
    spend_microusd: int = Field(default=0, ge=0, le=1_000_000)


class BudgetRequest(BudgetUnits):
    tool_calls: int = Field(default=8, ge=1, le=20)
    wall_seconds: int = Field(default=120, ge=1, le=600)


class Destination(StrictModel):
    kind: Literal["response", "internal_files", "resource", "external_recipient"] = "response"
    resource_id: uuid.UUID | None = Field(default=None, strict=False)
    recipient: str | None = Field(default=None, min_length=3, max_length=254)

    @model_validator(mode="after")
    def shape(self) -> "Destination":
        if self.kind == "resource":
            if self.resource_id is None or self.recipient is not None:
                raise ValueError("destination_invalid")
        elif self.kind == "external_recipient":
            if self.recipient is None or self.resource_id is not None or "@" not in self.recipient:
                raise ValueError("destination_invalid")
        elif self.resource_id is not None or self.recipient is not None:
            raise ValueError("destination_invalid")
        return self


class CapabilitySpec(StrictModel):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,95}$")
    version: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,32}$")
    effect_class: EffectClass
    policy_action: PolicyAction
    implementation_ref: Literal["sot.read", "documents.create_draft", "contract_only"]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_destinations: tuple[
        Literal[
            "response",
            "internal_files",
            "resource",
            "external_recipient",
        ],
        ...,
    ] = Field(min_length=1, max_length=4)
    max_tool_calls: int = Field(default=1, ge=1, le=8)
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    max_attempts: int = Field(default=1, ge=1, le=3)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    preview_supported: bool = True
    reconciliation: Literal["read_only", "canonical_job", "contract_only"]
    compensation: Literal["not_applicable", "cancel_remaining", "irreversible"]
    execution_available: bool = False

    @model_validator(mode="after")
    def host_effect(self) -> "CapabilitySpec":
        if self.execution_available and (
            self.version != "2" or self.effect_class not in {"R0", "R1"}
            or self.implementation_ref == "contract_only"
        ):
            raise ValueError("effect_unavailable")
        if self.implementation_ref == "sot.read" and (
            self.capability_id != "sot.read"
            or self.effect_class != "R0"
            or self.policy_action != "view"
            or self.allowed_destinations != ("response",)
        ):
            raise ValueError("capability_contract_invalid")
        if self.implementation_ref == "documents.create_draft" and (
            self.capability_id != "documents.create_draft"
            or self.effect_class != "R1"
            or self.policy_action != "render"
            or self.allowed_destinations != ("internal_files",)
        ):
            raise ValueError("capability_contract_invalid")
        if self.effect_class in {"R2", "R3"} and self.implementation_ref != "contract_only":
            raise ValueError("effect_unavailable")
        return self


class CapabilityView(StrictModel):
    spec: CapabilitySpec
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission: Literal["not_admitted", "admitted", "revoked"]
    execution_available: bool = False


class VersionRequest(StrictModel):
    version: str = Field(default="1", pattern=r"^[a-zA-Z0-9._-]{1,32}$")


class StepRequest(StrictModel):
    step_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,95}$")
    capability_version: str = Field(default="1", pattern=r"^[a-zA-Z0-9._-]{1,32}$")
    arguments: dict[str, Any] = Field(max_length=200)
    dependencies: tuple[str, ...] = Field(default=(), max_length=20, strict=False)
    destination: Destination | None = None
    expected_outcome: str = Field(default="contract admitted", min_length=1, max_length=500)


class PlanRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    objective: str = Field(min_length=1, max_length=2_000)
    purpose: UseClass = "proposal"
    workspace_id: uuid.UUID | None = Field(default=None, strict=False)
    context_packet_id: uuid.UUID | None = Field(default=None, strict=False)
    source_refs: tuple[SOTReference, ...] = Field(default=(), max_length=20, strict=False)
    steps: tuple[StepRequest, ...] = Field(min_length=1, max_length=20, strict=False)
    budget: BudgetRequest = Field(default_factory=BudgetRequest)
    reviewers: tuple[RequestUUID, ...] = Field(default=(), max_length=3, strict=False)
    supersedes_plan_id: uuid.UUID | None = Field(default=None, strict=False)
    requested_internal_draft: bool = False


PolicyClassification = Literal["public", "internal", "restricted", "classified"]


class ResourceBinding(StrictModel):
    resource_id: uuid.UUID
    resource_type: Literal["record", "template_version"]
    version_id: uuid.UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: PolicyClassification
    policy_action: PolicyAction


class BoundStep(StrictModel):
    step_key: str
    capability_id: str
    capability_version: str
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    effect_class: EffectClass
    arguments: dict[str, Any]
    arguments_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependencies: tuple[str, ...]
    resources: tuple[ResourceBinding, ...]
    destination: Destination
    expected_outcome: str


class PlanPayload(StrictModel):
    actor_id: uuid.UUID
    actor_security_version: int = Field(ge=1)
    workspace_id: uuid.UUID | None
    context_packet_id: uuid.UUID | None
    objective: str
    purpose: UseClass
    source_refs: tuple[SOTReference, ...]
    steps: tuple[BoundStep, ...]
    budget: BudgetRequest
    reviewers: tuple[uuid.UUID, ...]
    requested_internal_draft: bool
    contract_build: Literal["rtr-action-contracts-1"] = CONTRACT_BUILD
    runtime_build_sha: str = Field(min_length=7, max_length=64)


class PlanView(StrictModel):
    plan_id: uuid.UUID
    root_plan_id: uuid.UUID
    plan_version: int
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: PlanPayload
    run_id: uuid.UUID
    state: ContractState
    reserved: BudgetUnits
    execution_available: Literal[False] = False


class ApprovalRequest(StrictModel):
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approved", "rejected"] = "approved"
    expires_in_seconds: int = Field(default=3600, ge=1, le=86_400)


class ApprovalBinding(StrictModel):
    plan_id: uuid.UUID
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: uuid.UUID
    actor_security_version: int
    reviewer_id: uuid.UUID
    reviewer_security_version: int
    resources_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    capabilities_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    destinations_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime

    @model_validator(mode="after")
    def aware(self) -> "ApprovalBinding":
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expiry_invalid")
        return self


class ApprovalView(StrictModel):
    approval_id: uuid.UUID
    binding: ApprovalBinding
    decision: Literal["approved", "rejected"]
    revoked_at: datetime | None = None


class ActionEvent(StrictModel):
    event_id: uuid.UUID
    run_id: uuid.UUID
    sequence: int
    event_type: Literal[
        "plan_admitted",
        "approval_recorded",
        "approval_revoked",
        "ready_validated",
        "budget_reserved",
    ]
    reason_code: str = Field(pattern=r"^[a-z][a-z_]{1,63}$")
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    correlation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str
    build_id: str = Field(min_length=7, max_length=64)
    contract_build: Literal["rtr-action-contracts-1"] = CONTRACT_BUILD
    usage: BudgetUnits | None = None
    occurred_at: datetime


class ContractReceipt(StrictModel):
    receipt_id: uuid.UUID
    run_id: uuid.UUID
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["contract_admission", "contract_validation"]
    outcome: Literal["contract_ready", "awaiting_approval"]
    request_id: str
    build_id: str = Field(min_length=7, max_length=64)
    contract_build: Literal["rtr-action-contracts-1"] = CONTRACT_BUILD
    occurred_at: datetime
    execution_available: Literal[False] = False
