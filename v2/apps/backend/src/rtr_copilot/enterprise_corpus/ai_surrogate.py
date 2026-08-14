"""Truthful AI-surrogate operator gate for the immutable TIP-034 campaign.

The gate combines a real build-bound technical capture with a hermetic browser
journey authored from employee personas.  It never turns an AI observation
into a human attestation and never reads answer or evidence plaintext from a
release artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rtr_copilot.enterprise_corpus.pilot_campaign import (
    PilotCampaignSpec,
    question_digest,
    source_case_index,
)

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_BUILD_PATTERN = r"^[0-9a-f]{12,64}$"
_CASE_ID_PATTERN = r"^[A-Z0-9][A-Z0-9._-]{2,127}$"
_TESTER_KIND = "ai_surrogate_not_human_attestation"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class AISurrogateCaseRef(StrictModel):
    case_id: str = Field(pattern=_CASE_ID_PATTERN)
    persona: str = Field(min_length=3, max_length=64)
    scenario: str = Field(min_length=3, max_length=160)


class AISurrogatePlan(StrictModel):
    schema_version: Literal[1]
    campaign_key: Literal["tip035.12-ai-surrogate-operator-e2e"]
    tester_kind: Literal["ai_surrogate_not_human_attestation"]
    purpose: str = Field(min_length=20, max_length=500)
    source_manifest: str
    source_suite: str
    prohibitions: tuple[str, ...] = Field(min_length=3)
    personas: dict[str, str] = Field(min_length=3)
    common_checks: tuple[str, ...] = Field(min_length=6)
    cases: tuple[AISurrogateCaseRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases_and_known_personas(self) -> AISurrogatePlan:
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("ai_surrogate_case_duplicate")
        unknown = sorted({item.persona for item in self.cases} - set(self.personas))
        if unknown:
            raise ValueError(f"ai_surrogate_persona_unknown:{','.join(unknown)}")
        return self


class AISurrogateCaseResult(StrictModel):
    case_id: str = Field(pattern=_CASE_ID_PATTERN)
    persona: str = Field(min_length=3, max_length=64)
    question_digest: str = Field(pattern=_DIGEST_PATTERN)
    expected_state: Literal["grounded", "honest_null"]
    rendered_state: Literal["grounded", "honest_null"]
    exact_input_round_trip: bool
    composer_cleared: bool
    processing_visible: bool
    response_state_rendered: bool
    citation_or_honest_null_rendered: bool
    evidence_rail_consistent: bool
    conversation_context_preserved: bool
    prompt_leak_absent: bool


class AISurrogateUIResult(StrictModel):
    schema_version: Literal[1]
    campaign_key: Literal["tip035.12-ai-surrogate-operator-e2e"]
    generated_at: str
    candidate_build: str = Field(pattern=_BUILD_PATTERN)
    tester_kind: Literal["ai_surrogate_not_human_attestation"]
    plan_digest: str = Field(pattern=_DIGEST_PATTERN)
    source_suite_digest: str = Field(pattern=_DIGEST_PATTERN)
    human_ledger_digest: str = Field(pattern=_DIGEST_PATTERN)
    human_ledger_modified: Literal[False]
    external_calls_executed: Literal[0]
    case_results: tuple[AISurrogateCaseResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> AISurrogateUIResult:
        ids = [item.case_id for item in self.case_results]
        if len(ids) != len(set(ids)):
            raise ValueError("ai_surrogate_ui_case_duplicate")
        return self


def _technical_rows(
    technical_report: dict[str, Any],
    *,
    candidate_build: str,
    source: dict[str, dict[str, Any]],
    expected_ids: set[str],
    latency_limit_ms: float,
) -> dict[str, Any]:
    if technical_report.get("runtime_build_identity") != candidate_build:
        raise ValueError("ai_surrogate_technical_build_mismatch")
    metrics = technical_report.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("ai_surrogate_technical_metrics_missing")
    required_metrics = {
        "total": 27,
        "passed": 27,
        "failed": 0,
        "false_grounded_count": 0,
    }
    for key, expected in required_metrics.items():
        if metrics.get(key) != expected:
            raise ValueError(f"ai_surrogate_technical_metric_failed:{key}")
    if metrics.get("citation_accuracy") != 1.0:
        raise ValueError("ai_surrogate_technical_citation_failed")
    p95 = metrics.get("p95_latency_ms")
    if not isinstance(p95, int | float) or p95 > latency_limit_ms:
        raise ValueError("ai_surrogate_technical_latency_failed")

    rows = technical_report.get("results")
    if not isinstance(rows, list):
        raise ValueError("ai_surrogate_technical_results_missing")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("ai_surrogate_technical_result_invalid")
        case_id = row["id"]
        if case_id in by_id:
            raise ValueError("ai_surrogate_technical_case_duplicate")
        by_id[case_id] = row
    if set(by_id) != expected_ids:
        raise ValueError("ai_surrogate_technical_case_set_mismatch")
    for case_id, row in by_id.items():
        case = source[case_id]
        expected_state = case["expect"]
        if row.get("question_digest") != question_digest(str(case["question"])):
            raise ValueError(f"ai_surrogate_question_digest_mismatch:{case_id}")
        if row.get("actual_state") != expected_state:
            raise ValueError(f"ai_surrogate_state_mismatch:{case_id}")
        if row.get("citation_ok") is not True or row.get("false_grounded") is True:
            raise ValueError(f"ai_surrogate_grounding_failed:{case_id}")
        if row.get("failures") != []:
            raise ValueError(f"ai_surrogate_oracle_failed:{case_id}")
        citations = row.get("citations")
        if not isinstance(citations, list):
            raise ValueError(f"ai_surrogate_citations_missing:{case_id}")
        if expected_state == "grounded" and not citations:
            raise ValueError(f"ai_surrogate_grounded_without_citation:{case_id}")
        if expected_state == "honest_null" and citations:
            raise ValueError(f"ai_surrogate_honest_null_with_citation:{case_id}")
    return {
        "cases_passed": len(by_id),
        "citation_accuracy": metrics["citation_accuracy"],
        "false_grounded_count": metrics["false_grounded_count"],
        "p95_latency_ms": p95,
    }


def evaluate_ai_surrogate(
    *,
    plan: AISurrogatePlan,
    plan_digest: str,
    manifest: PilotCampaignSpec,
    source_payload: dict[str, Any],
    source_digest: str,
    technical_report: dict[str, Any],
    ui_result: AISurrogateUIResult,
    human_ledger_digest: str,
) -> dict[str, Any]:
    """Evaluate a segregated AI-surrogate gate without human impersonation."""
    if ui_result.plan_digest != plan_digest:
        raise ValueError("ai_surrogate_plan_digest_mismatch")
    if ui_result.source_suite_digest != source_digest:
        raise ValueError("ai_surrogate_source_digest_mismatch")
    if ui_result.human_ledger_digest != human_ledger_digest:
        raise ValueError("ai_surrogate_human_ledger_digest_mismatch")

    source = source_case_index(source_payload)
    manifest_ids = {item.case_id for item in manifest.cases}
    plan_ids = {item.case_id for item in plan.cases}
    if plan_ids != manifest_ids or len(plan.cases) != 27:
        raise ValueError("ai_surrogate_plan_case_set_mismatch")
    if manifest.source_campaign_digest != source_digest:
        raise ValueError("ai_surrogate_manifest_source_digest_mismatch")
    if not plan_ids <= set(source):
        raise ValueError("ai_surrogate_source_case_missing")

    technical = _technical_rows(
        technical_report,
        candidate_build=ui_result.candidate_build,
        source=source,
        expected_ids=plan_ids,
        latency_limit_ms=manifest.thresholds.scorecard.p95_latency_ms,
    )

    plan_by_id = {item.case_id: item for item in plan.cases}
    ui_by_id = {item.case_id: item for item in ui_result.case_results}
    if set(ui_by_id) != plan_ids:
        raise ValueError("ai_surrogate_ui_case_set_mismatch")
    check_names = (
        "exact_input_round_trip",
        "composer_cleared",
        "processing_visible",
        "response_state_rendered",
        "citation_or_honest_null_rendered",
        "evidence_rail_consistent",
        "conversation_context_preserved",
        "prompt_leak_absent",
    )
    for case_id, result in ui_by_id.items():
        case = source[case_id]
        if result.persona != plan_by_id[case_id].persona:
            raise ValueError(f"ai_surrogate_ui_persona_mismatch:{case_id}")
        if result.question_digest != question_digest(str(case["question"])):
            raise ValueError(f"ai_surrogate_ui_question_digest_mismatch:{case_id}")
        if result.expected_state != case["expect"]:
            raise ValueError(f"ai_surrogate_ui_expectation_mismatch:{case_id}")
        if result.rendered_state != result.expected_state:
            raise ValueError(f"ai_surrogate_ui_rendered_state_mismatch:{case_id}")
        if not all(getattr(result, name) for name in check_names):
            raise ValueError(f"ai_surrogate_ui_check_failed:{case_id}")

    personas = Counter(item.persona for item in ui_result.case_results)
    return {
        "schema_version": 1,
        "campaign_key": plan.campaign_key,
        "candidate_build": ui_result.candidate_build,
        "tester_kind": _TESTER_KIND,
        "verdict": "go",
        "human_usefulness_measured": False,
        "human_ledger_modified": False,
        "external_calls_executed": 0,
        "technical_capture": technical,
        "ui_e2e": {
            "cases_passed": len(ui_by_id),
            "personas": dict(sorted(personas.items())),
            "checks_per_case": len(check_names),
            "assertions_passed": len(ui_by_id) * len(check_names),
        },
        "input_digests": {
            "plan": plan_digest,
            "manifest": hashlib.sha256(
                json.dumps(
                    manifest.model_dump(mode="json"),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "source_suite": source_digest,
            "technical_report": file_digest(
                json.dumps(
                    technical_report,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ),
            "ui_result": file_digest(
                json.dumps(
                    ui_result.model_dump(mode="json"),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ),
            "human_ledger": human_ledger_digest,
        },
        "release_interpretation": (
            "eligible_for_explicit_homeowner_ai_surrogate_override"
        ),
        "residual_risk": [
            "human_subjective_usefulness_not_measured",
            "mocked_browser_responses_do_not_retest_live_answer_generation",
        ],
    }


__all__ = [
    "AISurrogatePlan",
    "AISurrogateUIResult",
    "evaluate_ai_surrogate",
    "file_digest",
]
