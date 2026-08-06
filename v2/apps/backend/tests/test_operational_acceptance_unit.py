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
    term_present,
    validate_database_target,
)
from run_real_world_acceptance import bounded_cases, validate_http_target  # noqa: E402


def test_real_world_fixture_is_valid_and_broad() -> None:
    campaign = load_campaign(EVAL / "real_world" / "cases.json")
    cases = campaign["flattened_cases"]
    domains = {case["domain"] for case in cases}
    shapes = {shape for case in cases for shape in case["shapes"]}
    assert len(cases) >= 77
    assert len(domains) >= 6
    assert len(shapes) >= 8
    assert any("follow_up" in case["shapes"] for case in cases)
    assert any(case["expect"] == "honest_null" for case in cases)
    assert campaign["http_thresholds"]["p95_latency_ms"] <= 60_000


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


def test_http_target_guard_accepts_loopback_only() -> None:
    assert validate_http_target("http://127.0.0.1:3101/") == (
        "http://127.0.0.1:3101"
    )
    with pytest.raises(ValueError, match="must_be_loopback"):
        validate_http_target("https://example.com")


def test_campaign_smoke_slice_is_explicit_bounded_and_deterministic() -> None:
    campaign = {"flattened_cases": [{"id": "A"}, {"id": "B"}, {"id": "C"}]}
    assert [item["id"] for item in bounded_cases(campaign, 2)] == ["A", "B"]
    assert bounded_cases(campaign, None) == campaign["flattened_cases"]
    assert [
        item["id"] for item in bounded_cases(campaign, None, ("C", "A", "C"))
    ] == ["C", "A"]
    with pytest.raises(ValueError, match="campaign_case_ids_unknown:D"):
        bounded_cases(campaign, None, ("D",))
    with pytest.raises(ValueError, match="must_be_positive"):
        bounded_cases(campaign, 0)


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


def test_incomplete_grounded_answer_is_not_mislabeled_false_grounded() -> None:
    row = score_case(
        {
            "id": "X",
            "domain": "product",
            "shapes": ["broad"],
            "question": "HERA có gì?",
            "expect": "grounded",
            "expected_record_groups": [["HC-001"]],
            "required_terms": ["15 km", "12 trường hợp sử dụng"],
        },
        state="grounded",
        answer="HERA có tầm điều khiển 15 km [C1]",
        citations=["HC-001"],
        reason_code=None,
        latency_ms=15,
    )
    assert row["passed"] is False
    assert row["false_grounded"] is False
    assert row["failures"] == ["required_term_miss"]


def test_alternate_approved_citation_is_not_mislabeled_false_grounded() -> None:
    row = score_case(
        {
            "id": "X",
            "domain": "operations",
            "shapes": ["natural"],
            "question": "Lịch bảo dưỡng là gì?",
            "expect": "grounded",
            "expected_record_groups": [["L3F.4.020"]],
            "required_terms": ["3/6/12 tháng"],
        },
        state="grounded",
        answer="Bảo dưỡng theo mốc 3, 6 và 12 tháng [C1]",
        citations=["tip024.xlsx.maintenance-program"],
        reason_code=None,
        latency_ms=15,
    )
    assert row["passed"] is False
    assert row["false_grounded"] is False
    assert row["failures"] == ["citation_miss"]


def test_grounded_answer_when_honest_null_expected_is_false_grounded() -> None:
    row = score_case(
        {
            "id": "X",
            "domain": "safety",
            "shapes": ["ambiguous"],
            "question": "IP là gì?",
            "expect": "honest_null",
            "allowed_reason_codes": ["ambiguous_entity"],
        },
        state="grounded",
        answer="IP là quản lý tài sản trí tuệ [C1]",
        citations=["L3F.4.002"],
        reason_code=None,
        latency_ms=15,
    )
    assert row["passed"] is False
    assert row["false_grounded"] is True
    assert "unexpected_state" in row["failures"]


def test_term_oracle_tolerates_business_number_and_date_formatting() -> None:
    assert term_present("64900", "Giá niêm yết là 64,900 USD.")
    assert term_present(
        "11-14/05/2026",
        "Sự kiện diễn ra từ 11 đến 14 tháng 5 năm 2026.",
    )
    assert term_present(
        "3/6/12 tháng",
        "Bảo dưỡng ở mốc 3 tháng, 6 tháng và 12 tháng.",
    )
    assert term_present("50.4V", "Điện áp danh định là 50,4 V.")
    assert term_present("61MP", "Camera RGB có độ phân giải 61 MP.")
    assert not term_present("500 UAV", "Nền tảng có 50 nhà sản xuất UAV.")


def test_term_group_accepts_one_governed_wording_variant() -> None:
    row = score_case(
        {
            "id": "X",
            "domain": "product",
            "shapes": ["definition"],
            "question": "HERA là gì?",
            "expect": "grounded",
            "expected_record_groups": [["HC-050"]],
            "required_term_groups": [["12 use case", "12 trường hợp sử dụng"]],
        },
        state="grounded",
        answer="HERA hỗ trợ 12 use case. [C1]",
        citations=["HC-050"],
        reason_code=None,
        latency_ms=15,
    )
    assert row["passed"] is True


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
