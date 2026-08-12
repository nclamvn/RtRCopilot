from pathlib import Path

import pytest
from pydantic import ValidationError

from rtr_copilot.enterprise_corpus.connectors import (
    ConnectorCanaryAttestation,
    ConnectorContract,
    ConnectorRegistry,
    connector_contract_digest,
    connector_readiness,
    load_connector_registry,
    plan_federation,
    validate_canary_attestation,
)


def test_registry_locks_read_only_and_provenance_contracts() -> None:
    registry = load_connector_registry()
    assert {item.stable_key for item in registry.connectors} == {
        "rtr.crm", "rtr.mrp", "rtr.ip", "rtr.hrm",
    }
    assert all(item.read_only for item in registry.connectors)
    assert all(not item.direct_database_access for item in registry.connectors)
    assert all(item.deletion_propagation for item in registry.connectors)
    assert all("checksum" in item.provenance_fields for item in registry.connectors)
    assert registry.federation.research_never_promotes_to_sot is True
    assert registry.federation.preserve_zone_labels is True


def test_invalid_connector_cannot_enable_direct_database_access() -> None:
    raw = load_connector_registry().model_dump(mode="json")
    raw["connectors"][0]["direct_database_access"] = True
    with pytest.raises(ValidationError):
        ConnectorRegistry.model_validate(raw)


def test_readiness_never_reports_active_without_runtime_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_connector_registry()
    for name in ("crm", "rtr-mrp", "ip"):
        (tmp_path / name).mkdir()
    for contract in registry.connectors:
        monkeypatch.delenv(contract.endpoint_env, raising=False)
        monkeypatch.delenv(contract.credential_env, raising=False)
    rows = connector_readiness(registry, rtr_root=tmp_path)
    by_key = {row.stable_key: row for row in rows}
    assert by_key["rtr.crm"].readiness == "contract_ready"
    assert by_key["rtr.mrp"].readiness == "contract_ready"
    assert by_key["rtr.ip"].readiness == "contract_ready"
    assert by_key["rtr.hrm"].readiness == "blocked"
    assert all(row.readiness != "active" for row in rows)


def test_federation_requires_explicit_research_authority_and_keeps_zones() -> None:
    registry = load_connector_registry()
    company = plan_federation(
        registry, "company", authenticated=True, research_authorized=False,
    )
    assert company.zones == ["sot", "private"]
    assert company.research_hit_budget == 0
    with pytest.raises(PermissionError, match="research_scope_not_authorized"):
        plan_federation(
            registry, "federated", authenticated=True, research_authorized=False,
        )
    federated = plan_federation(
        registry, "federated", authenticated=True, research_authorized=True,
    )
    assert federated.zones == ["sot", "private", "research"]
    assert federated.answer_contract == "federated_segmented"
    assert federated.research_never_promotes_to_sot is True


def enabled_crm() -> ConnectorContract:
    crm = load_connector_registry().connectors[0]
    return crm.model_copy(update={"lifecycle": "enabled"})


def canary(contract: ConnectorContract, **overrides: object) -> ConnectorCanaryAttestation:
    values: dict[str, object] = {
        "schema_version": 1,
        "stable_key": contract.stable_key,
        "contract_digest": connector_contract_digest(contract),
        "read_only": True,
        "direct_database_access": False,
        "deletion_propagation": True,
        "acl_probe": "pass",
        "denied_row_probe": "pass",
        "field_mask_probe": "pass",
        "provenance_probe": "pass",
        "deletion_probe": "pass",
        "observed_freshness_seconds": 30,
        "sample_record_count": 1,
    }
    values.update(overrides)
    return ConnectorCanaryAttestation.model_validate(values)


def test_crm_canary_binds_exact_read_only_contract_and_freshness() -> None:
    contract = enabled_crm()
    validate_canary_attestation(contract, canary(contract))
    with pytest.raises(ValueError, match="contract_digest_mismatch"):
        validate_canary_attestation(
            contract,
            canary(contract, contract_digest="0" * 64),
        )
    with pytest.raises(ValueError, match="freshness_sla_failed"):
        validate_canary_attestation(
            contract,
            canary(
                contract,
                observed_freshness_seconds=contract.freshness_sla_seconds + 1,
            ),
        )


def test_contract_ready_crm_cannot_pass_canary() -> None:
    contract = load_connector_registry().connectors[0]
    with pytest.raises(ValueError, match="lifecycle_not_enabled"):
        validate_canary_attestation(contract, canary(contract))
