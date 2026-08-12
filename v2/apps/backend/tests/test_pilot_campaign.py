"""TIP-034 pilot campaign provenance and anti-gaming regressions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rtr_copilot.enterprise_corpus.pilot_campaign import (
    PilotCampaignLedger,
    PilotCampaignObservation,
    PilotCampaignSpec,
    evaluate_pilot_campaign,
    question_digest,
    validate_campaign_source,
)

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_PATH = ROOT / "eval" / "pilot" / "tip034_campaign.json"
LEDGER_PATH = ROOT / "eval" / "pilot" / "tip034_observations.json"
SOURCE_PATH = ROOT / "eval" / "real_world" / "cases.json"
BUILD_IDENTITY = "a" * 12 + "+" + "b" * 12
RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def load_contract() -> tuple[
    PilotCampaignSpec,
    PilotCampaignLedger,
    dict[str, dict[str, Any]],
]:
    campaign = PilotCampaignSpec.model_validate_json(CAMPAIGN_PATH.read_text())
    ledger = PilotCampaignLedger.model_validate_json(LEDGER_PATH.read_text())
    source_bytes = SOURCE_PATH.read_bytes()
    source = json.loads(source_bytes)
    selected = validate_campaign_source(
        campaign,
        source,
        source_digest=hashlib.sha256(source_bytes).hexdigest(),
    )
    return campaign, ledger, selected


def completed_fixture() -> tuple[
    PilotCampaignSpec,
    PilotCampaignLedger,
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    campaign, _, selected = load_contract()
    observations: list[PilotCampaignObservation] = []
    results: list[dict[str, Any]] = []
    refs = {item.case_id: item for item in campaign.cases}
    for index, (case_id, source) in enumerate(selected.items(), start=1):
        digest = question_digest(str(source["question"]))
        grounded = source["expect"] == "grounded"
        results.append({
            "id": case_id,
            "question_digest": digest,
            "actual_state": "grounded" if grounded else "honest_null",
            "citations": [f"record-{index:03d}"] if grounded else [],
            "citation_ok": True,
            "false_grounded": False,
            "latency_ms": 1000.0 + index,
        })
        ref = refs[case_id]
        observations.append(PilotCampaignObservation(
            observation_id=f"tip034-observation-{index:03d}",
            case_id=case_id,
            source_run_id=RUN_ID,
            question_digest=digest,
            runtime_build_identity=BUILD_IDENTITY,
            observed_at=datetime(2026, 8, 12, 4, index, tzinfo=UTC),
            evaluator_digest="c" * 64,
            useful=True,
            clarification_recovered=True if ref.clarification_probe else None,
            authz_leakage=False,
            authz_trace_digest="d" * 64,
            provider_cost_usd=0.02,
            cost_trace_digest="e" * 64,
        ))
    ledger = PilotCampaignLedger(
        schema_version=1,
        campaign_key=campaign.campaign_key,
        campaign_digest=campaign.digest,
        campaign_state="completed",
        observations=tuple(observations),
    )
    report = {
        "schema_version": 1,
        "run_id": str(RUN_ID),
        "computed_at": "2026-08-12T04:00:00+00:00",
        "runtime_build_identity": BUILD_IDENTITY,
        "results": results,
    }
    return campaign, ledger, selected, report


def test_committed_campaign_is_immutable_broad_and_not_started() -> None:
    campaign, ledger, selected = load_contract()
    assert campaign.digest == ledger.campaign_digest
    assert len(selected) == 27
    assert set(campaign.thresholds.domain_minimums) == {
        "company", "conversation", "methods", "operations", "product", "safety", "systems",
    }
    result = evaluate_pilot_campaign(campaign, ledger, selected, [])
    assert result["verdict"] == "not_started"
    assert result["sample_size"] == 0


def test_completed_real_run_bindings_pass_every_gate() -> None:
    campaign, ledger, selected, report = completed_fixture()
    result = evaluate_pilot_campaign(campaign, ledger, selected, [report])
    assert result["verdict"] == "go"
    assert result["sample_size"] == 27
    assert all(result["coverage_gates"].values())
    assert all(result["scorecard"]["gates"].values())


def test_completed_campaign_cannot_cherry_pick_an_easy_subset() -> None:
    campaign, ledger, selected, report = completed_fixture()
    partial = ledger.model_copy(update={"observations": ledger.observations[:-1]})
    result = evaluate_pilot_campaign(campaign, partial, selected, [report])
    assert result["verdict"] == "insufficient_sample"
    assert result["coverage_gates"]["all_manifest_cases_observed"] is False


def test_observation_must_bind_to_exact_question_and_runtime_build() -> None:
    campaign, ledger, selected, report = completed_fixture()
    report["results"][0]["question_digest"] = "f" * 64
    with pytest.raises(ValueError, match="report_question_digest_mismatch"):
        evaluate_pilot_campaign(campaign, ledger, selected, [report])

    _, ledger, selected, report = completed_fixture()
    report.pop("runtime_build_identity")
    with pytest.raises(ValueError, match="report_build_identity_missing"):
        evaluate_pilot_campaign(campaign, ledger, selected, [report])

    campaign, ledger, selected, report = completed_fixture()
    report["computed_at"] = "2026-08-13T04:00:00+00:00"
    with pytest.raises(ValueError, match="observation_predates_report"):
        evaluate_pilot_campaign(campaign, ledger, selected, [report])


def test_case_cannot_be_counted_twice() -> None:
    campaign, ledger, _, _ = completed_fixture()
    duplicate = ledger.observations[0].model_copy(
        update={"observation_id": "tip034-observation-duplicate"},
    )
    with pytest.raises(ValidationError, match="case_observed_twice"):
        PilotCampaignLedger(
            schema_version=1,
            campaign_key=campaign.campaign_key,
            campaign_digest=campaign.digest,
            campaign_state="running",
            observations=(ledger.observations[0], duplicate),
        )


def test_source_suite_change_fails_loud() -> None:
    campaign, _, _ = load_contract()
    source = json.loads(SOURCE_PATH.read_text())
    with pytest.raises(ValueError, match="source_digest_mismatch"):
        validate_campaign_source(campaign, source, source_digest="0" * 64)
