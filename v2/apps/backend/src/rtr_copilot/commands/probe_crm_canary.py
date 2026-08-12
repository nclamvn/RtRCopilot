"""Probe the governed CRM read-only canary without retrieving business data."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from rtr_copilot.enterprise_corpus.connectors import (
    ConnectorCanaryAttestation,
    connector_contract_digest,
    connector_readiness,
    load_connector_registry,
    validate_canary_attestation,
)


def _write(result: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def _approved_endpoint(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    approved = {
        item.strip().lower()
        for item in os.getenv("RTR_CONNECTOR_APPROVED_HOSTS", "").split(",")
        if item.strip()
    }
    if not hostname or hostname not in approved:
        raise ValueError("crm_canary_host_not_approved")
    if parsed.scheme != "https" and hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("crm_canary_https_required")
    return value.rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtr-root", type=Path, default=Path("/ecosystem"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    registry = load_connector_registry()
    contract = next(item for item in registry.connectors if item.stable_key == "rtr.crm")
    readiness = next(
        item for item in connector_readiness(registry, rtr_root=args.rtr_root)
        if item.stable_key == "rtr.crm"
    )
    base_result: dict[str, object] = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "stable_key": contract.stable_key,
        "contract_digest": connector_contract_digest(contract),
        "read_only": contract.read_only,
        "direct_database_access": contract.direct_database_access,
    }
    if readiness.readiness != "active":
        _write({
            **base_result,
            "readiness": readiness.readiness,
            "reasons": readiness.reasons,
            "verdict": "blocked_not_connected",
        }, args.output)
        raise SystemExit(1)
    try:
        endpoint = _approved_endpoint(os.environ[contract.endpoint_env])
        token = os.environ[contract.credential_env]
        response = httpx.get(
            f"{endpoint}/.well-known/rtr-copilot/connector-canary",
            headers={
                "authorization": f"Bearer {token}",
                "accept": "application/json",
                "x-rtr-purpose": "copilot-read-only-canary",
            },
            timeout=args.timeout,
        )
        response.raise_for_status()
        attestation = ConnectorCanaryAttestation.model_validate(response.json())
        validate_canary_attestation(contract, attestation)
    except (KeyError, ValueError, httpx.HTTPError) as error:
        _write({
            **base_result,
            "readiness": "blocked",
            "reasons": [type(error).__name__],
            "verdict": "canary_failed",
        }, args.output)
        raise SystemExit(1) from error
    _write({
        **base_result,
        "readiness": "active",
        "observed_freshness_seconds": attestation.observed_freshness_seconds,
        "sample_record_count": attestation.sample_record_count,
        "probes": {
            "acl": attestation.acl_probe,
            "denied_row": attestation.denied_row_probe,
            "field_mask": attestation.field_mask_probe,
            "provenance": attestation.provenance_probe,
            "deletion": attestation.deletion_probe,
        },
        "verdict": "canary_pass",
    }, args.output)


if __name__ == "__main__":
    main()
