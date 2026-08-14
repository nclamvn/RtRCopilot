"""TIP-035.12 AI-surrogate provenance and anti-impersonation tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rtr_copilot.enterprise_corpus.ai_surrogate import (
    AISurrogatePlan,
    AISurrogateUIResult,
    evaluate_ai_surrogate,
    file_digest,
)
from rtr_copilot.enterprise_corpus.pilot_campaign import (
    PilotCampaignSpec,
    question_digest,
    source_case_index,
)

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / "eval" / "pilot" / "tip035_12_ai_surrogate_plan.json"
MANIFEST = ROOT / "eval" / "pilot" / "tip034_campaign.json"
SOURCE = ROOT / "eval" / "real_world" / "cases.json"
LEDGER = ROOT / "eval" / "pilot" / "tip034_observations.json"
BUILD = "a" * 12


def fixture() -> tuple[
    AISurrogatePlan,
    PilotCampaignSpec,
    dict[str, object],
    dict[str, object],
    AISurrogateUIResult,
]:
    plan = AISurrogatePlan.model_validate_json(PLAN.read_text())
    manifest = PilotCampaignSpec.model_validate_json(MANIFEST.read_text())
    source_payload = json.loads(SOURCE.read_text())
    source = source_case_index(source_payload)
    results = []
    ui_rows = []
    plan_by_id = {item.case_id: item for item in plan.cases}
    for item in plan.cases:
        case = source[item.case_id]
        grounded = case["expect"] == "grounded"
        digest = question_digest(str(case["question"]))
        results.append({
            "id": item.case_id,
            "question_digest": digest,
            "actual_state": "grounded" if grounded else "honest_null",
            "citations": ["HC-001"] if grounded else [],
            "citation_ok": True,
            "false_grounded": False,
            "latency_ms": 1000.0,
            "failures": [],
        })
        ui_rows.append({
            "case_id": item.case_id,
            "persona": plan_by_id[item.case_id].persona,
            "question_digest": digest,
            "expected_state": case["expect"],
            "rendered_state": case["expect"],
            "exact_input_round_trip": True,
            "composer_cleared": True,
            "processing_visible": True,
            "response_state_rendered": True,
            "citation_or_honest_null_rendered": True,
            "evidence_rail_consistent": True,
            "conversation_context_preserved": True,
            "prompt_leak_absent": True,
        })
    technical = {
        "runtime_build_identity": BUILD,
        "metrics": {
            "total": 27,
            "passed": 27,
            "failed": 0,
            "false_grounded_count": 0,
            "citation_accuracy": 1.0,
            "p95_latency_ms": 12_000.0,
        },
        "results": results,
    }
    ui = AISurrogateUIResult.model_validate({
        "schema_version": 1,
        "campaign_key": plan.campaign_key,
        "generated_at": "2026-08-14T00:00:00Z",
        "candidate_build": BUILD,
        "tester_kind": plan.tester_kind,
        "plan_digest": file_digest(PLAN.read_bytes()),
        "source_suite_digest": file_digest(SOURCE.read_bytes()),
        "human_ledger_digest": file_digest(LEDGER.read_bytes()),
        "human_ledger_modified": False,
        "external_calls_executed": 0,
        "case_results": ui_rows,
    })
    return plan, manifest, source_payload, technical, ui


def evaluate(
    plan: AISurrogatePlan,
    manifest: PilotCampaignSpec,
    source: dict[str, object],
    technical: dict[str, object],
    ui: AISurrogateUIResult,
) -> dict[str, object]:
    return evaluate_ai_surrogate(
        plan=plan,
        plan_digest=file_digest(PLAN.read_bytes()),
        manifest=manifest,
        source_payload=source,
        source_digest=file_digest(SOURCE.read_bytes()),
        technical_report=technical,
        ui_result=ui,
        human_ledger_digest=file_digest(LEDGER.read_bytes()),
    )


def test_ai_surrogate_combines_technical_and_ui_without_human_impersonation() -> None:
    plan, manifest, source, technical, ui = fixture()
    result = evaluate(plan, manifest, source, technical, ui)

    assert result["verdict"] == "go"
    assert result["tester_kind"] == "ai_surrogate_not_human_attestation"
    assert result["human_usefulness_measured"] is False
    assert result["human_ledger_modified"] is False
    assert result["external_calls_executed"] == 0
    assert result["technical_capture"]["cases_passed"] == 27
    assert result["ui_e2e"]["cases_passed"] == 27
    assert "human_subjective_usefulness_not_measured" in result["residual_risk"]


def test_ai_surrogate_rejects_stale_technical_build() -> None:
    plan, manifest, source, technical, ui = fixture()
    technical["runtime_build_identity"] = "b" * 12

    with pytest.raises(ValueError, match="technical_build_mismatch"):
        evaluate(plan, manifest, source, technical, ui)


def test_ai_surrogate_rejects_a_failed_browser_check() -> None:
    plan, manifest, source, technical, ui = fixture()
    broken = ui.model_copy(deep=True)
    broken.case_results[0].composer_cleared = False

    with pytest.raises(ValueError, match="ui_check_failed"):
        evaluate(plan, manifest, source, technical, broken)


def test_ai_surrogate_rejects_modified_human_ledger_binding() -> None:
    plan, manifest, source, technical, ui = fixture()
    broken = ui.model_copy(update={"human_ledger_digest": "f" * 64})

    with pytest.raises(ValueError, match="human_ledger_digest_mismatch"):
        evaluate(plan, manifest, source, technical, broken)


def test_ai_surrogate_rejects_cherry_picked_technical_capture() -> None:
    plan, manifest, source, technical, ui = fixture()
    broken = copy.deepcopy(technical)
    broken["results"] = broken["results"][:-1]

    with pytest.raises(ValueError, match="technical_case_set_mismatch"):
        evaluate(plan, manifest, source, broken, ui)
