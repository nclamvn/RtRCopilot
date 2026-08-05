"""Hermetic tests for TIP-026 campaign validation and scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EVAL = ROOT / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from lib.operational_acceptance import (  # noqa: E402
    load_campaign,
    score_case,
    summarize,
    validate_database_target,
)


def test_real_world_fixture_is_valid_and_broad() -> None:
    campaign = load_campaign(EVAL / "real_world" / "cases.json")
    cases = campaign["flattened_cases"]
    domains = {case["domain"] for case in cases}
    shapes = {shape for case in cases for shape in case["shapes"]}
    assert len(cases) >= 60
    assert len(domains) >= 6
    assert len(shapes) >= 8
    assert any("follow_up" in case["shapes"] for case in cases)
    assert any(case["expect"] == "honest_null" for case in cases)


def test_loader_rejects_answerable_case_without_citation_oracle(tmp_path: Path) -> None:
    fixture = {
        "schema_version": 1,
        "thresholds": {},
        "cases": [{
            "id": "X",
            "domain": "product",
            "shapes": ["clean"],
            "question": "HERA?",
            "expect": "grounded",
        }],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(ValueError, match="campaign_citation_oracle_missing"):
        load_campaign(path)


def test_database_target_guard_requires_exact_disposable_clone() -> None:
    validate_database_target("rtr_tip026_run_1", "rtr_tip026_run_1")
    with pytest.raises(ValueError, match="campaign_database_prefix_invalid"):
        validate_database_target("rtr_copilot", "rtr_copilot")
    with pytest.raises(ValueError, match="campaign_database_target_mismatch"):
        validate_database_target("rtr_copilot", "rtr_tip026_run_1")


def test_wrong_grounded_citation_is_counted_as_false_grounded() -> None:
    row = score_case(
        {
            "id": "X",
            "domain": "systems",
            "shapes": ["name_collision"],
            "question": "The Sky Watch có bao nhiêu UAV?",
            "expect": "grounded",
            "expected_record_groups": [["L3F.3.006"]],
            "required_terms": ["500 UAV"],
        },
        state="grounded",
        answer="SkyWatch 360 tethered [C1]",
        citations=["HC-014"],
        reason_code=None,
        latency_ms=15,
    )
    assert row["passed"] is False
    assert row["false_grounded"] is True
    assert "citation_miss" in row["failures"]


def test_safe_refusal_and_correct_grounded_answer_pass() -> None:
    safe = score_case(
        {
            "id": "SAFE",
            "domain": "safety",
            "shapes": ["unknown_entity"],
            "question": "ORION?",
            "expect": "honest_null",
            "allowed_reason_codes": ["denied_or_unavailable"],
        },
        state="honest_null",
        answer="No evidence",
        citations=[],
        reason_code="denied_or_unavailable",
        latency_ms=10,
    )
    grounded = score_case(
        {
            "id": "KNOWN",
            "domain": "product",
            "shapes": ["clean"],
            "question": "HERA range?",
            "expect": "grounded",
            "expected_record_groups": [["HC-001"]],
            "required_terms": ["15 km"],
        },
        state="grounded",
        answer="HERA range 15 km [C1]",
        citations=["HC-001"],
        reason_code=None,
        latency_ms=20,
    )
    assert safe["passed"] is True
    assert grounded["passed"] is True


def test_summary_gate_has_teeth() -> None:
    thresholds = {
        "overall_pass_rate": 0.9,
        "grounded_success_rate": 0.9,
        "citation_accuracy": 0.95,
        "honest_null_precision": 1.0,
        "false_grounded_count": 0,
        "minimum_domain_pass_rate": 0.8,
        "follow_up_pass_rate": 0.8,
        "p95_latency_ms": 1500,
    }
    good = {
        "id": "A",
        "domain": "product",
        "shapes": ["follow_up"],
        "expected_state": "grounded",
        "citation_ok": True,
        "false_grounded": False,
        "latency_ms": 20,
        "passed": True,
    }
    bad = {
        **good,
        "id": "B",
        "citation_ok": False,
        "false_grounded": True,
        "passed": False,
    }
    assert summarize([good], thresholds)["passed"] is True
    failed = summarize([good, bad], thresholds)
    assert failed["passed"] is False
    assert failed["metrics"]["false_grounded_count"] == 1
