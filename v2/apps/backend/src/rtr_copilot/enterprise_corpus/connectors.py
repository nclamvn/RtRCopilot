"""Governed connector contracts and explicit knowledge-federation planning.

This module deliberately contains no vendor credentials and performs no remote
I/O.  It is the admission gate between RtR transaction systems and Copilot:
connectors remain inactive until an approved read-only endpoint and credential
are supplied at runtime. Research is never relabeled as company SOT.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConnectorLifecycle = Literal["contract_ready", "blocked", "enabled"]
ConnectorReadiness = Literal["blocked", "contract_ready", "active"]
KnowledgeScope = Literal["company", "research", "federated"]
ResearchTier = Literal["P", "S", "H", "X"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectorBudget(StrictModel):
    max_records_per_sync: int = Field(ge=1, le=1_000_000)
    max_bytes_per_sync: int = Field(ge=1024, le=1_000_000_000)
    max_requests_per_minute: int = Field(ge=1, le=10_000)


class ConnectorContract(StrictModel):
    stable_key: str = Field(pattern=r"^rtr\.[a-z0-9-]+$")
    display_name: str = Field(min_length=3, max_length=200)
    lifecycle: ConnectorLifecycle
    source_root: str = Field(min_length=1)
    owner_boundary: str = Field(min_length=3, max_length=300)
    transport: Literal["rest_api", "snapshot_api", "cdc_projection"]
    endpoint_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    credential_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    read_only: Literal[True] = True
    direct_database_access: Literal[False] = False
    deletion_propagation: Literal[True] = True
    classification: Literal["internal", "restricted", "highly_restricted"]
    entity_scopes: list[str] = Field(min_length=1, max_length=100)
    row_policy: str = Field(min_length=10, max_length=500)
    field_policy: str = Field(min_length=10, max_length=500)
    purpose_limitation: str = Field(min_length=10, max_length=500)
    provenance_fields: list[str] = Field(min_length=4, max_length=30)
    cursor_field: str = Field(min_length=1, max_length=100)
    freshness_sla_seconds: int = Field(ge=60, le=604_800)
    budget: ConnectorBudget
    blocked_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def blocked_contract_has_reason(self) -> ConnectorContract:
        if self.lifecycle == "blocked" and not self.blocked_reason:
            raise ValueError("blocked_connector_requires_reason")
        return self


class ResearchFederationPolicy(StrictModel):
    default_scope: Literal["company"] = "company"
    research_requires_explicit_scope: Literal[True] = True
    research_never_promotes_to_sot: Literal[True] = True
    preserve_zone_labels: Literal[True] = True
    allowed_tiers: list[ResearchTier] = Field(min_length=1, max_length=4)
    max_company_hits: int = Field(ge=1, le=20)
    max_research_hits: int = Field(ge=1, le=20)
    max_total_hits: int = Field(ge=1, le=40)

    @model_validator(mode="after")
    def total_budget_is_bounded(self) -> ResearchFederationPolicy:
        if self.max_total_hits > self.max_company_hits + self.max_research_hits:
            raise ValueError("federation_total_exceeds_source_budgets")
        if len(set(self.allowed_tiers)) != len(self.allowed_tiers):
            raise ValueError("federation_tiers_duplicate")
        return self


class ConnectorRegistry(StrictModel):
    schema_version: Literal[1]
    connectors: list[ConnectorContract] = Field(min_length=1, max_length=50)
    federation: ResearchFederationPolicy

    @model_validator(mode="after")
    def stable_keys_are_unique(self) -> ConnectorRegistry:
        keys = [item.stable_key for item in self.connectors]
        if len(keys) != len(set(keys)):
            raise ValueError("connector_stable_key_duplicate")
        return self


class ConnectorReadinessItem(StrictModel):
    stable_key: str
    readiness: ConnectorReadiness
    repository_discovered: bool
    endpoint_configured: bool
    credential_configured: bool
    reasons: list[str]


class FederationPlan(StrictModel):
    scope: KnowledgeScope
    zones: list[Literal["sot", "private", "research"]]
    answer_contract: Literal[
        "company_grounded", "research_supported", "federated_segmented",
    ]
    company_hit_budget: int
    research_hit_budget: int
    preserve_zone_labels: Literal[True] = True
    research_never_promotes_to_sot: Literal[True] = True


class ConnectorCanaryAttestation(StrictModel):
    """Content-free proof emitted by an approved source-side canary."""

    schema_version: Literal[1]
    stable_key: str
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    read_only: Literal[True]
    direct_database_access: Literal[False]
    deletion_propagation: Literal[True]
    acl_probe: Literal["pass"]
    denied_row_probe: Literal["pass"]
    field_mask_probe: Literal["pass"]
    provenance_probe: Literal["pass"]
    deletion_probe: Literal["pass"]
    observed_freshness_seconds: int = Field(ge=0, le=604_800)
    sample_record_count: int = Field(ge=0, le=10)


def registry_path() -> Path:
    return Path(__file__).with_name("connector_registry.json")


def load_connector_registry(path: Path | None = None) -> ConnectorRegistry:
    source = path or registry_path()
    return ConnectorRegistry.model_validate_json(source.read_text(encoding="utf-8"))


def connector_registry_digest(registry: ConnectorRegistry) -> str:
    payload = json.dumps(
        registry.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def connector_contract_digest(contract: ConnectorContract) -> str:
    payload = json.dumps(
        contract.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_canary_attestation(
    contract: ConnectorContract,
    attestation: ConnectorCanaryAttestation,
) -> None:
    """Fail closed unless the source-side proof matches this exact contract."""
    if contract.lifecycle != "enabled":
        raise ValueError("connector_lifecycle_not_enabled")
    if attestation.stable_key != contract.stable_key:
        raise ValueError("connector_canary_stable_key_mismatch")
    if attestation.contract_digest != connector_contract_digest(contract):
        raise ValueError("connector_canary_contract_digest_mismatch")
    if attestation.observed_freshness_seconds > contract.freshness_sla_seconds:
        raise ValueError("connector_canary_freshness_sla_failed")


def connector_readiness(
    registry: ConnectorRegistry,
    *,
    rtr_root: Path,
) -> list[ConnectorReadinessItem]:
    output: list[ConnectorReadinessItem] = []
    for contract in registry.connectors:
        discovered = (rtr_root / contract.source_root).resolve().is_dir()
        endpoint = bool(os.getenv(contract.endpoint_env, "").strip())
        credential = bool(os.getenv(contract.credential_env, "").strip())
        reasons: list[str] = []
        if not discovered:
            reasons.append("authoritative_repository_not_discovered")
        if contract.lifecycle == "blocked":
            reasons.append(contract.blocked_reason or "owner_gate_blocked")
        if not endpoint:
            reasons.append("approved_read_only_endpoint_not_configured")
        if not credential:
            reasons.append("connector_credential_not_configured")
        readiness: ConnectorReadiness = "contract_ready"
        if contract.lifecycle == "blocked" or not discovered:
            readiness = "blocked"
        elif contract.lifecycle == "enabled" and endpoint and credential:
            readiness = "active"
        output.append(ConnectorReadinessItem(
            stable_key=contract.stable_key,
            readiness=readiness,
            repository_discovered=discovered,
            endpoint_configured=endpoint,
            credential_configured=credential,
            reasons=reasons,
        ))
    return output


def plan_federation(
    registry: ConnectorRegistry,
    scope: KnowledgeScope,
    *,
    authenticated: bool,
    research_authorized: bool,
) -> FederationPlan:
    """Return a content-free plan; callers execute each zone independently."""

    if not authenticated:
        raise PermissionError("federation_authentication_required")
    if scope in {"research", "federated"} and not research_authorized:
        raise PermissionError("research_scope_not_authorized")
    policy = registry.federation
    if scope == "company":
        return FederationPlan(
            scope=scope,
            zones=["sot", "private"],
            answer_contract="company_grounded",
            company_hit_budget=min(policy.max_company_hits, policy.max_total_hits),
            research_hit_budget=0,
        )
    if scope == "research":
        return FederationPlan(
            scope=scope,
            zones=["research"],
            answer_contract="research_supported",
            company_hit_budget=0,
            research_hit_budget=min(policy.max_research_hits, policy.max_total_hits),
        )
    return FederationPlan(
        scope=scope,
        zones=["sot", "private", "research"],
        answer_contract="federated_segmented",
        company_hit_budget=min(policy.max_company_hits, policy.max_total_hits),
        research_hit_budget=min(
            policy.max_research_hits,
            max(0, policy.max_total_hits - policy.max_company_hits),
        ),
    )
