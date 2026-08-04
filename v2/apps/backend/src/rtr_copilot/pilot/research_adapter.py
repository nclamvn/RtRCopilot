"""Deterministic adapter from the flat CNCL refinery ledger to Research V2.

The adapter never changes the source claims or snapshots.  It verifies every
quote against its named snapshot, reconciles current claims by ``entity`` and
``field``, and emits the existing rooted Research package contract.  Different
wording remains disputed even when one source has a stronger tier.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from rtr_copilot.research.package import (
    RESEARCH_ADAPTER_VERSION,
    RefineryEvidence,
    RefineryRecord,
    ResearchManifestMember,
    evidence_checksum,
    research_fingerprint,
    research_payload_sha,
    research_record_sha,
)
from rtr_copilot.sot.package import canonical_json, sha256_bytes

ADAPTER_VERSION = "cncl-refinery-adapter-1.0"
SOURCE_KEY = "refinery.vn-strategic-technology"
SCOPE = "Vietnam strategic-technology policy and UAV opportunity space"
CURRENT_STATE = "sourced"
SAFE_KEY = re.compile(r"[^a-z0-9._-]+")


class PilotResearchError(ValueError):
    """Fail-loud adapter error carrying a stable gate code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ResearchBuildResult:
    staging_name: str
    package_root: Path
    fingerprint: str
    record_count: int
    input_claim_count: int
    current_claim_count: int
    span_pass_count: int
    corroboration_counts: dict[str, int]
    tier_counts: dict[str, int]


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _source_host(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold()
    return host.removeprefix("www.")


def _record_key(entity: str, field: str) -> str:
    raw = f"cncl.{entity}.{field}".casefold()
    key = SAFE_KEY.sub("-", raw).strip("-.")
    if not key or len(key) > 256:
        raise PilotResearchError("record_key_invalid", raw)
    return key


def _tier(claims: list[dict[str, Any]]) -> Literal["P", "S", "H"]:
    tiers = {str(item.get("tier", "")) for item in claims}
    if "A" in tiers:
        return "P"
    if "B" in tiers:
        return "S"
    return "H"


def _corroboration(
    claims: list[dict[str, Any]],
) -> Literal["uncorroborated", "corroborated", "disputed"]:
    values = {canonical_json(item.get("value")) for item in claims}
    if len(values) > 1:
        return "disputed"
    independent_hosts = {
        _source_host(str(item.get("source_url", ""))) for item in claims
    }
    independent_hosts.discard("")
    strong = all(item.get("tier") in {"A", "B"} for item in claims)
    if strong and len(independent_hosts) >= 2:
        return "corroborated"
    return "uncorroborated"


def load_claims(dataset_root: Path) -> list[dict[str, Any]]:
    path = dataset_root / "claims.jsonl"
    if not path.is_file():
        raise PilotResearchError("claims_missing", str(path))
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise PilotResearchError("claim_json_invalid", str(line_number)) from error
        required = {
            "id", "entity", "field", "value", "evidence_span", "snapshot",
            "source_url", "tier", "captured_at", "state",
        }
        if not isinstance(item, dict) or not required.issubset(item):
            raise PilotResearchError("claim_schema_invalid", str(line_number))
        claim_id = str(item["id"])
        if claim_id in seen:
            raise PilotResearchError("claim_id_duplicate", claim_id)
        seen.add(claim_id)
        claims.append(item)
    if not claims:
        raise PilotResearchError("claims_empty")
    return claims


def verify_spans(dataset_root: Path, claims: list[dict[str, Any]]) -> int:
    snapshots_root = (dataset_root / "snapshots").resolve()
    passed = 0
    for item in claims:
        snapshot = snapshots_root / str(item["snapshot"])
        resolved = snapshot.resolve()
        if snapshots_root not in resolved.parents or not resolved.is_file():
            raise PilotResearchError("snapshot_missing", str(item["id"]))
        quote = _normalized(str(item["evidence_span"]))
        source = _normalized(resolved.read_text(encoding="utf-8"))
        if not quote or quote not in source:
            raise PilotResearchError("span_not_found", str(item["id"]))
        passed += 1
    return passed


def reconcile(claims: list[dict[str, Any]]) -> list[RefineryRecord]:
    current = [item for item in claims if item["state"] == CURRENT_STATE]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in current:
        groups[(str(item["entity"]), str(item["field"]))].append(item)
    records: list[RefineryRecord] = []
    for (entity, field), grouped in sorted(groups.items()):
        ordered = sorted(grouped, key=lambda item: str(item["id"]))
        state = _corroboration(ordered)
        unique_values = sorted(
            {canonical_json(item["value"]) for item in ordered},
        )
        values = [json.loads(value) for value in unique_values]
        content = {
            "entity": entity,
            "field": field,
            "value": values[0] if len(values) == 1 else None,
            "corroboration_state": state,
            "claims": [
                {
                    "claim_id": str(item["id"]),
                    "value": item["value"],
                    "source_tier": str(item["tier"]),
                    "source_url": str(item["source_url"]),
                    "captured_at": str(item["captured_at"]),
                    "extraction": str(item.get("extraction", "verbatim")),
                }
                for item in ordered
            ],
        }
        evidence = [
            RefineryEvidence(
                source_url=str(item["source_url"]),
                locator={
                    "snapshot": str(item["snapshot"]),
                    "claim_id": str(item["id"]),
                },
                quoted_text=str(item["evidence_span"]),
                checksum=evidence_checksum(str(item["evidence_span"])),
            )
            for item in ordered
        ]
        searchable = "\n".join([
            entity,
            field,
            *(str(item["value"]) for item in ordered),
            *(str(item["evidence_span"]) for item in ordered),
        ])
        record = RefineryRecord(
            record_key=_record_key(entity, field),
            version_ordinal=1,
            tier=_tier(ordered),
            content=content,
            searchable_text=searchable,
            evidence=evidence,
            corroboration_state=state,
            content_sha256="0" * 64,
        )
        records.append(record.model_copy(update={
            "content_sha256": research_record_sha(record),
        }))
    if not records:
        raise PilotResearchError("current_record_set_empty")
    return records


def emit_package(
    dataset_root: Path,
    out_root: Path,
    *,
    source_key: str = SOURCE_KEY,
    scope: str = SCOPE,
) -> ResearchBuildResult:
    dataset_root = dataset_root.resolve()
    claims = load_claims(dataset_root)
    span_pass_count = verify_spans(dataset_root, claims)
    records = reconcile(claims)
    records_bytes = b"".join(
        canonical_json(item.model_dump(mode="json")) + b"\n" for item in records
    )
    member = ResearchManifestMember(
        path="records.jsonl",
        byte_size=len(records_bytes),
        sha256=sha256_bytes(records_bytes),
    )
    payload_sha = research_payload_sha([member])
    captured_at = datetime.combine(
        max(datetime.fromisoformat(str(item["captured_at"])).date() for item in claims),
        datetime.min.time(),
        tzinfo=UTC,
    )
    fingerprint = research_fingerprint(
        source_key=source_key,
        scope=scope,
        captured_at=captured_at,
        adapter_version=ADAPTER_VERSION,
        payload_sha256=payload_sha,
    )
    manifest = {
        "schema_version": "1.0",
        "source_key": source_key,
        "fingerprint": fingerprint,
        "payload_sha256": payload_sha,
        "captured_at": captured_at.isoformat(),
        "scope": scope,
        "adapter_version": ADAPTER_VERSION,
        "record_count": len(records),
        "members": [member.model_dump(mode="json")],
        "upstream_adapter_contract": RESEARCH_ADAPTER_VERSION,
    }
    # The rooted parser refuses unknown manifest fields. Keep the upstream
    # contract in this adapter's report, not inside the package manifest.
    manifest.pop("upstream_adapter_contract")
    staging_name = f"research-cncl-{fingerprint[:12]}"
    package_root = out_root.resolve() / staging_name
    package_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "manifest.json": canonical_json(manifest),
        "records.jsonl": records_bytes,
    }
    for name, payload in outputs.items():
        target = package_root / name
        if target.exists() and target.read_bytes() != payload:
            raise PilotResearchError("output_drift", str(target))
        target.write_bytes(payload)
    corroboration_counts: dict[str, int] = defaultdict(int)
    tier_counts: dict[str, int] = defaultdict(int)
    for item in records:
        corroboration_counts[item.corroboration_state] += 1
        tier_counts[item.tier] += 1
    return ResearchBuildResult(
        staging_name=staging_name,
        package_root=package_root,
        fingerprint=fingerprint,
        record_count=len(records),
        input_claim_count=len(claims),
        current_claim_count=sum(
            item["state"] == CURRENT_STATE for item in claims
        ),
        span_pass_count=span_pass_count,
        corroboration_counts=dict(sorted(corroboration_counts.items())),
        tier_counts=dict(sorted(tier_counts.items())),
    )
