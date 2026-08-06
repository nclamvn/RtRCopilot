import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rtr_copilot.enterprise_corpus.theskywatch import (
    TheSkyWatchAdapterError,
    emit_package,
)
from rtr_copilot.research.package import ResearchPackageParser


def _write_snapshot(root: Path, *, field_tier: str = "B", fingerprint_ok: bool = True) -> None:
    root.mkdir(parents=True)
    master = {
        "schema_version": "1.1.0",
        "generated": "2026-08-01",
        "family_count": 1,
        "variant_count": 1,
        "families": [],
        "variants": [],
    }
    source_sha = hashlib.sha256(
        json.dumps(master, sort_keys=True, ensure_ascii=False).encode(),
    ).hexdigest()
    site = {
        "schema": "site-data/2",
        "schema_version": 2,
        "source_registry_sha256": source_sha if fingerprint_ok else "0" * 64,
        "entities": [
            {
                "canonical_id": "uav:rtr:hera:industrial",
                "entity_type": "uav",
                "name": {
                    "value": "HERA Industrial",
                    "status": "verified",
                    "confidence": "high",
                    "source_tier": "A",
                    "sources": [{
                        "url": "https://rtrobotics.com/hera",
                        "tier": "A",
                        "retrieved": "2026-07-31",
                    }],
                },
                "max_range_km": {
                    "value": 15,
                    "status": "sourced",
                    "confidence": "medium",
                    "source_tier": field_tier,
                    "sources": [{
                        "url": "https://example.com/hera",
                        "tier": field_tier,
                        "retrieved": "2026-07-30",
                    }],
                },
                "market_segment": {
                    "value": "isr",
                    "status": "derived",
                    "confidence": "derived",
                    "source_tier": "derived",
                    "sources": [{
                        "url": "taxonomy:market-segment-v1",
                        "tier": "derived",
                    }],
                },
                "empty": {"value": None, "status": None, "source_tier": None},
                "unsafe": {
                    "value": "guess",
                    "status": "unverified",
                    "source_tier": "C",
                },
            },
            {
                "entity_type": "company",
                "slug": "real-time-robotics",
                "name": "Real-time Robotics",
                "hq_country": {
                    "value": "Vietnam",
                    "source": "rtrobotics.com/company",
                    "tier": "A",
                },
            },
        ],
    }
    articles = [
        {
            "slug": "uav-registry-method",
            "title": "How the UAV registry is verified",
            "body": "The registry leaves a field empty when evidence is missing.",
            "type": "data-note",
            "date": "2026-08-02",
            "author": "TheSkyWatch Data Desk",
            "entity_tags": [],
            "primary_section": "technology",
            "sample": False,
            "status": "published",
            "sources": [
                {"url": "https://manufacturer.example/spec", "tier": "A"},
                {"url": "https://regulator.example/record", "tier": "B"},
            ],
        },
        {
            "slug": "draft",
            "title": "Draft",
            "body": "Not publishable.",
            "type": "news",
            "date": "2026-08-03",
            "sample": False,
            "status": "draft",
            "sources": [],
        },
    ]
    for name, value in (
        ("master_registry.json", master),
        ("site-data.json", site),
        ("articles_records.json", articles),
    ):
        (root / name).write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8",
        )


def test_theskywatch_adapter_is_deterministic_and_preserves_tiers(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    _write_snapshot(snapshot)
    first = emit_package(snapshot, tmp_path / "out-a")
    second = emit_package(snapshot, tmp_path / "out-b")
    assert first.fingerprint == second.fingerprint
    assert first.record_count == 5
    assert first.entity_count == 2
    assert first.entity_record_count == 4
    assert first.admitted_field_count == 4
    assert first.article_count == 1
    assert first.excluded_null_count == 1
    assert first.excluded_unverified_count == 1
    assert first.tier_counts == {"P": 2, "S": 2, "H": 0, "X": 1}
    assert (first.package_root / "manifest.json").read_bytes() == (
        second.package_root / "manifest.json"
    ).read_bytes()
    assert (first.package_root / "records.jsonl").read_bytes() == (
        second.package_root / "records.jsonl"
    ).read_bytes()
    staged = ResearchPackageParser(tmp_path / "out-a").stage(
        first.staging_name,
        now=datetime(2026, 8, 4, tzinfo=UTC),
    )
    records = staged.load_records()
    assert len(records) == 5
    derived = next(item for item in records if item.tier == "X")
    assert derived.content["facts"]["market_segment"]["status"] == "derived"
    assert all(
        item.content["kind"] != "published_article" or item.tier == "S"
        for item in records
    )


def test_theskywatch_adapter_rejects_snapshot_fingerprint_drift(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    _write_snapshot(snapshot, fingerprint_ok=False)
    with pytest.raises(TheSkyWatchAdapterError) as caught:
        emit_package(snapshot, tmp_path / "out")
    assert caught.value.code == "source_registry_fingerprint_mismatch"


def test_theskywatch_adapter_rejects_unknown_source_tier(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    _write_snapshot(snapshot, field_tier="Z")
    with pytest.raises(TheSkyWatchAdapterError) as caught:
        emit_package(snapshot, tmp_path / "out")
    assert caught.value.code == "source_tier_invalid"
