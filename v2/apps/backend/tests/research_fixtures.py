"""Synthetic Refinery package builders for TIP-010 research-zone tests."""

import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rtr_copilot.research.package import (
    ResearchManifestMember,
    evidence_checksum,
    research_fingerprint,
    research_payload_sha,
)
from rtr_copilot.sot.package import canonical_json, sha256_bytes

CAPTURED_AT = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)


def research_record_sha_raw(row: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json({
        "record_key": row["record_key"],
        "version_ordinal": row["version_ordinal"],
        "tier": row["tier"],
        "content": row["content"],
        "searchable_text": row["searchable_text"],
        "corroboration_state": row.get(
            "corroboration_state", "uncorroborated",
        ),
        "evidence": [
            {
                "source_url": span["source_url"],
                "locator": span["locator"],
                "quoted_text": span["quoted_text"],
                "checksum": span["checksum"],
            }
            for span in row["evidence"]
        ],
    }))


def research_record_row(
    *,
    record_key: str | None = None,
    ordinal: int = 1,
    tier: str = "P",
    text: str | None = None,
    source_url: str = "https://example.org/refinery/source",
    locator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = text or f"synthetic refinery insight {uuid.uuid4().hex}"
    row: dict[str, Any] = {
        "record_key": record_key or f"IND.{uuid.uuid4().hex[:16].upper()}",
        "version_ordinal": ordinal,
        "tier": tier,
        "content": {"claim": body},
        "searchable_text": body,
        "corroboration_state": "uncorroborated",
        "evidence": [{
            "source_url": source_url,
            "locator": locator or {"selector": "main > p:nth-of-type(2)"},
            "quoted_text": body,
            "checksum": evidence_checksum(body),
        }],
        "content_sha256": "0" * 64,
    }
    row["content_sha256"] = research_record_sha_raw(row)
    return row


def build_research_package(
    root: Path,
    *,
    source_key: str = "refinery.synthetic",
    records: list[dict[str, Any]] | None = None,
    name: str | None = None,
    captured_at: datetime = CAPTURED_AT,
    scope: str = "industry-uav",
    adapter_version: str = "refinery-adapter-1.2",
    record_count: int | None = None,
    fingerprint: str | None = None,
    payload_sha256: str | None = None,
    as_zip: bool = False,
    mutate_manifest: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Build a staged Refinery package; returns the staging name."""
    rows = records if records is not None else [research_record_row()]
    records_bytes = b"".join(canonical_json(row) + b"\n" for row in rows)
    members = [{
        "path": "records.jsonl",
        "byte_size": len(records_bytes),
        "sha256": sha256_bytes(records_bytes),
    }]
    payload = payload_sha256 or research_payload_sha([
        ResearchManifestMember.model_validate(member) for member in members
    ])
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "source_key": source_key,
        "fingerprint": fingerprint or research_fingerprint(
            source_key=source_key,
            scope=scope,
            captured_at=captured_at,
            adapter_version=adapter_version,
            payload_sha256=payload,
        ),
        "payload_sha256": payload,
        "captured_at": captured_at.isoformat(),
        "scope": scope,
        "adapter_version": adapter_version,
        "record_count": record_count if record_count is not None else len(rows),
        "members": members,
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    staging_name = name or f"research-{uuid.uuid4().hex}"
    if as_zip:
        staging_name = f"{staging_name}.zip"
        with zipfile.ZipFile(root / staging_name, "w") as archive:
            archive.writestr("manifest.json", canonical_json(manifest))
            archive.writestr("records.jsonl", records_bytes)
    else:
        package_root = root / staging_name
        package_root.mkdir(parents=True)
        (package_root / "manifest.json").write_bytes(canonical_json(manifest))
        (package_root / "records.jsonl").write_bytes(records_bytes)
    return staging_name
