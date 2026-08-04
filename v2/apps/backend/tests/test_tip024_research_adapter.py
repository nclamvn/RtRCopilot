import json
from datetime import UTC, datetime
from pathlib import Path

from rtr_copilot.pilot.research_adapter import emit_package
from rtr_copilot.research.package import ResearchPackageParser


def _claim(
    claim_id: str,
    entity: str,
    value: str,
    snapshot: str,
    url: str,
    tier: str,
    *,
    state: str = "sourced",
) -> dict[str, str]:
    return {
        "id": claim_id,
        "entity": entity,
        "field": "name",
        "value": value,
        "evidence_span": value,
        "snapshot": snapshot,
        "source_url": url,
        "tier": tier,
        "extraction": "verbatim",
        "captured_at": "2026-07-18",
        "state": state,
    }


def test_cncl_adapter_is_deterministic_and_preserves_conflicts(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    snapshots = dataset / "snapshots"
    snapshots.mkdir(parents=True)
    claims = [
        _claim("A1", "alpha", "same", "a.md", "https://gov.vn/a", "A"),
        _claim("A2", "alpha", "same", "b.md", "https://law.vn/b", "B"),
        _claim("B1", "beta", "first", "c.md", "https://gov.vn/c", "A"),
        _claim("B2", "beta", "second", "d.md", "https://law.vn/d", "B"),
        _claim("C1", "gamma", "only", "e.md", "https://gov.vn/e", "A"),
        _claim(
            "OLD", "legacy", "old", "f.md", "https://gov.vn/f", "A",
            state="superseded",
        ),
    ]
    for item in claims:
        (snapshots / item["snapshot"]).write_text(
            f"prefix {item['evidence_span']} suffix", encoding="utf-8",
        )
    (dataset / "claims.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in claims) + "\n",
        encoding="utf-8",
    )
    first = emit_package(dataset, tmp_path / "out-a")
    second = emit_package(dataset, tmp_path / "out-b")
    assert first.fingerprint == second.fingerprint
    assert (first.package_root / "manifest.json").read_bytes() == (
        second.package_root / "manifest.json"
    ).read_bytes()
    assert (first.package_root / "records.jsonl").read_bytes() == (
        second.package_root / "records.jsonl"
    ).read_bytes()
    assert first.input_claim_count == 6
    assert first.current_claim_count == 5
    assert first.span_pass_count == 6
    assert first.record_count == 3
    assert first.corroboration_counts == {
        "corroborated": 1,
        "disputed": 1,
        "uncorroborated": 1,
    }
    staged = ResearchPackageParser(tmp_path / "out-a").stage(
        first.staging_name,
        now=datetime(2026, 7, 19, tzinfo=UTC),
    )
    records = staged.load_records()
    disputed = next(item for item in records if item.content["entity"] == "beta")
    assert disputed.corroboration_state == "disputed"
    assert disputed.content["value"] is None
    assert [item["value"] for item in disputed.content["claims"]] == [
        "first", "second",
    ]
