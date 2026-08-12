"""Immutable, provenance-bound enterprise pilot campaign contracts.

The scorecard deliberately contains no question or answer plaintext.  Human
usefulness judgements are accepted only when they bind to a real acceptance
run, its runtime build, and the immutable question digest from the governed
enterprise suite.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rtr_copilot.enterprise_corpus.pilot_scorecard import (
    PilotObservation,
    PilotScorecardInput,
    PilotThresholds,
    evaluate_pilot_scorecard,
)

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_CASE_ID_PATTERN = r"^[A-Z0-9][A-Z0-9._-]{2,127}$"
_BUILD_PATTERN = r"^[0-9a-f]{12,64}\+[0-9a-f]{12,64}$"
_MESSY_SHAPES = frozenset({
    "abbreviation",
    "ambiguity",
    "ambiguous_abbreviation",
    "ambiguous_name",
    "code_switching",
    "colloquial",
    "ellipsis",
    "filler",
    "gibberish",
    "indirect_description",
    "malformed",
    "missing_diacritics",
    "partial_name",
    "pronoun",
    "short",
    "spacing_variant",
    "typo",
})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_of(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def question_digest(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()


class PilotCampaignCaseRef(StrictModel):
    case_id: str = Field(pattern=_CASE_ID_PATTERN)
    clarification_probe: bool = False


class PilotCampaignThresholds(StrictModel):
    scorecard: PilotThresholds = Field(default_factory=PilotThresholds)
    domain_minimums: dict[str, int] = Field(min_length=1)
    shape_minimums: dict[str, int] = Field(default_factory=dict)
    min_messy_observations: int = Field(default=8, ge=1, le=10_000)
    max_single_domain_share: float = Field(default=0.25, gt=0, le=1)
    require_all_cases: bool = True

    @field_validator("domain_minimums", "shape_minimums")
    @classmethod
    def positive_named_minimums(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not key.strip() or count < 1 for key, count in value.items()):
            raise ValueError("pilot_campaign_minimum_invalid")
        return value


class PilotCampaignSpec(StrictModel):
    schema_version: Literal[1]
    campaign_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    source_campaign_digest: str = Field(pattern=_DIGEST_PATTERN)
    thresholds: PilotCampaignThresholds
    cases: tuple[PilotCampaignCaseRef, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> PilotCampaignSpec:
        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("pilot_campaign_case_duplicate")
        return self

    @property
    def digest(self) -> str:
        return digest_of(self)


class PilotCampaignObservation(StrictModel):
    observation_id: str = Field(min_length=8, max_length=128)
    case_id: str = Field(pattern=_CASE_ID_PATTERN)
    source_run_id: uuid.UUID
    question_digest: str = Field(pattern=_DIGEST_PATTERN)
    runtime_build_identity: str = Field(pattern=_BUILD_PATTERN)
    observed_at: datetime
    evaluator_digest: str = Field(pattern=_DIGEST_PATTERN)
    useful: bool
    clarification_recovered: bool | None = None
    authz_leakage: bool = False
    authz_trace_digest: str = Field(pattern=_DIGEST_PATTERN)
    provider_cost_usd: float = Field(ge=0)
    cost_trace_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("observed_at")
    @classmethod
    def timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pilot_campaign_observed_at_timezone_required")
        return value


class PilotCampaignLedger(StrictModel):
    schema_version: Literal[1]
    campaign_key: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,127}$")
    campaign_digest: str = Field(pattern=_DIGEST_PATTERN)
    campaign_state: Literal["not_started", "running", "completed"]
    observations: tuple[PilotCampaignObservation, ...] = ()

    @model_validator(mode="after")
    def observations_are_unique_and_match_state(self) -> PilotCampaignLedger:
        if self.campaign_state == "not_started" and self.observations:
            raise ValueError("pilot_campaign_not_started_has_observations")
        observation_ids = [item.observation_id for item in self.observations]
        case_ids = [item.case_id for item in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("pilot_campaign_observation_duplicate")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("pilot_campaign_case_observed_twice")
        return self


def source_case_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten a governed E2E suite without importing test-harness code."""
    if payload.get("schema_version") != 1:
        raise ValueError("pilot_campaign_source_schema_invalid")
    rows: list[dict[str, Any]] = []
    for raw in payload.get("cases", []):
        rows.append({**raw, "scenario_id": None})
    for scenario in payload.get("scenarios", []):
        scenario_id = str(scenario.get("id", ""))
        domain = str(scenario.get("domain", "conversation"))
        for turn_index, raw in enumerate(scenario.get("turns", []), start=1):
            rows.append({
                **raw,
                "domain": domain,
                "scenario_id": scenario_id,
                "turn_index": turn_index,
            })
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("id", ""))
        if not case_id or case_id in index:
            raise ValueError("pilot_campaign_source_case_invalid_or_duplicate")
        if not str(row.get("question", "")).strip():
            raise ValueError(f"pilot_campaign_source_question_missing:{case_id}")
        if not str(row.get("domain", "")).strip():
            raise ValueError(f"pilot_campaign_source_domain_missing:{case_id}")
        if row.get("expect") not in {"grounded", "honest_null"}:
            raise ValueError(f"pilot_campaign_source_expectation_invalid:{case_id}")
        if not isinstance(row.get("shapes"), list) or not row["shapes"]:
            raise ValueError(f"pilot_campaign_source_shapes_missing:{case_id}")
        index[case_id] = row
    return index


def validate_campaign_source(
    campaign: PilotCampaignSpec,
    source_payload: dict[str, Any],
    *,
    source_digest: str,
) -> dict[str, dict[str, Any]]:
    if source_digest != campaign.source_campaign_digest:
        raise ValueError("pilot_campaign_source_digest_mismatch")
    source = source_case_index(source_payload)
    selected: dict[str, dict[str, Any]] = {}
    for ref in campaign.cases:
        if ref.case_id not in source:
            raise ValueError(f"pilot_campaign_case_unknown:{ref.case_id}")
        selected[ref.case_id] = source[ref.case_id]

    thresholds = campaign.thresholds
    domains = Counter(str(row["domain"]) for row in selected.values())
    shapes = Counter(
        str(shape)
        for row in selected.values()
        for shape in row["shapes"]
    )
    for domain, minimum in thresholds.domain_minimums.items():
        if domains[domain] < minimum:
            raise ValueError(f"pilot_campaign_manifest_domain_minimum:{domain}")
    if set(domains) != set(thresholds.domain_minimums):
        raise ValueError("pilot_campaign_manifest_domain_set_mismatch")
    for shape, minimum in thresholds.shape_minimums.items():
        if shapes[shape] < minimum:
            raise ValueError(f"pilot_campaign_manifest_shape_minimum:{shape}")
    messy = sum(
        bool(_MESSY_SHAPES & {str(shape) for shape in row["shapes"]})
        for row in selected.values()
    )
    if messy < thresholds.min_messy_observations:
        raise ValueError("pilot_campaign_manifest_messy_minimum")
    if len(selected) < thresholds.scorecard.min_observations:
        raise ValueError("pilot_campaign_manifest_scorecard_minimum")
    honest_nulls = sum(row["expect"] == "honest_null" for row in selected.values())
    if honest_nulls < thresholds.scorecard.min_honest_null_observations:
        raise ValueError("pilot_campaign_manifest_honest_null_minimum")
    clarification = sum(ref.clarification_probe for ref in campaign.cases)
    if clarification < thresholds.scorecard.min_clarification_observations:
        raise ValueError("pilot_campaign_manifest_clarification_minimum")
    return selected


def _report_index(
    reports: list[dict[str, Any]],
) -> tuple[dict[tuple[uuid.UUID, str], dict[str, Any]], set[str]]:
    index: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
    report_digests: set[str] = set()
    for report in reports:
        try:
            run_id = uuid.UUID(str(report["run_id"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("pilot_campaign_report_run_id_invalid") from exc
        build_identity = report.get("runtime_build_identity")
        if not isinstance(build_identity, str):
            raise ValueError("pilot_campaign_report_build_identity_missing")
        computed_at = report.get("computed_at")
        if not isinstance(computed_at, str):
            raise ValueError("pilot_campaign_report_timestamp_missing")
        try:
            report_timestamp = datetime.fromisoformat(computed_at)
        except ValueError as exc:
            raise ValueError("pilot_campaign_report_timestamp_invalid") from exc
        if report_timestamp.tzinfo is None or report_timestamp.utcoffset() is None:
            raise ValueError("pilot_campaign_report_timestamp_timezone_required")
        results = report.get("results")
        if not isinstance(results, list):
            raise ValueError("pilot_campaign_report_results_missing")
        report_digests.add(digest_of(report))
        for row in results:
            if not isinstance(row, dict):
                raise ValueError("pilot_campaign_report_result_invalid")
            case_id = str(row.get("id", ""))
            key = (run_id, case_id)
            if not case_id or key in index:
                raise ValueError("pilot_campaign_report_result_duplicate")
            index[key] = {
                **row,
                "runtime_build_identity": build_identity,
                "report_computed_at": report_timestamp,
            }
    return index, report_digests


def evaluate_pilot_campaign(
    campaign: PilotCampaignSpec,
    ledger: PilotCampaignLedger,
    source_cases: dict[str, dict[str, Any]],
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    if ledger.campaign_key != campaign.campaign_key:
        raise ValueError("pilot_campaign_key_mismatch")
    if ledger.campaign_digest != campaign.digest:
        raise ValueError("pilot_campaign_digest_mismatch")

    refs = {item.case_id: item for item in campaign.cases}
    report_rows, report_digests = _report_index(reports)
    score_rows: list[PilotObservation] = []
    observed_source: list[dict[str, Any]] = []
    build_identities: set[str] = set()
    for observation in ledger.observations:
        ref = refs.get(observation.case_id)
        if ref is None:
            raise ValueError(f"pilot_campaign_observation_case_unknown:{observation.case_id}")
        source = source_cases[observation.case_id]
        expected_digest = question_digest(str(source["question"]))
        if observation.question_digest != expected_digest:
            raise ValueError("pilot_campaign_observation_question_digest_mismatch")
        report = report_rows.get((observation.source_run_id, observation.case_id))
        if report is None:
            raise ValueError("pilot_campaign_observation_report_binding_missing")
        if report.get("question_digest") != expected_digest:
            raise ValueError("pilot_campaign_report_question_digest_mismatch")
        if report["runtime_build_identity"] != observation.runtime_build_identity:
            raise ValueError("pilot_campaign_observation_build_mismatch")
        if observation.observed_at < report["report_computed_at"]:
            raise ValueError("pilot_campaign_observation_predates_report")
        report_latency = float(report.get("latency_ms", -1))
        if report_latency < 0:
            raise ValueError("pilot_campaign_report_latency_missing")
        clarification_needed = ref.clarification_probe
        if clarification_needed != (observation.clarification_recovered is not None):
            raise ValueError("pilot_campaign_clarification_attestation_mismatch")
        citations = report.get("citations")
        if not isinstance(citations, list):
            raise ValueError("pilot_campaign_report_citations_missing")
        citations_checked = len(citations)
        citations_supported = citations_checked if report.get("citation_ok") is True else 0
        expected_honest_null = source["expect"] == "honest_null"
        actual_honest_null = report.get("actual_state") == "honest_null"
        false_grounded = report.get("false_grounded") is True
        score_rows.append(PilotObservation(
            observation_id=observation.observation_id,
            useful=observation.useful,
            clarification_needed=clarification_needed,
            clarification_recovered=observation.clarification_recovered,
            citations_checked=citations_checked,
            citations_supported=citations_supported,
            expected_honest_null=expected_honest_null,
            actual_honest_null=actual_honest_null,
            false_grounded=false_grounded,
            authz_leakage=observation.authz_leakage,
            latency_ms=report_latency,
            provider_cost_usd=observation.provider_cost_usd,
        ))
        observed_source.append(source)
        build_identities.add(observation.runtime_build_identity)

    scorecard = evaluate_pilot_scorecard(PilotScorecardInput(
        schema_version=1,
        campaign_state=ledger.campaign_state,
        thresholds=campaign.thresholds.scorecard,
        observations=score_rows,
    ))
    observed_ids = {item.case_id for item in ledger.observations}
    domain_counts = Counter(str(row["domain"]) for row in observed_source)
    shape_counts = Counter(
        str(shape)
        for row in observed_source
        for shape in row["shapes"]
    )
    messy_count = sum(
        bool(_MESSY_SHAPES & {str(shape) for shape in row["shapes"]})
        for row in observed_source
    )
    sample_size = len(observed_source)
    max_domain_share = (
        max(domain_counts.values(), default=0) / sample_size if sample_size else 0.0
    )
    coverage_gates = {
        "all_manifest_cases_observed": (
            not campaign.thresholds.require_all_cases
            or observed_ids == set(refs)
        ),
        "domain_minimums": all(
            domain_counts[domain] >= minimum
            for domain, minimum in campaign.thresholds.domain_minimums.items()
        ),
        "shape_minimums": all(
            shape_counts[shape] >= minimum
            for shape, minimum in campaign.thresholds.shape_minimums.items()
        ),
        "messy_query_minimum": (
            messy_count >= campaign.thresholds.min_messy_observations
        ),
        "single_domain_share": (
            max_domain_share <= campaign.thresholds.max_single_domain_share
        ),
        "single_runtime_build": len(build_identities) == 1,
    }
    if not ledger.observations:
        verdict = "not_started"
    elif scorecard["verdict"] == "insufficient_sample":
        verdict = "insufficient_sample"
    elif (
        ledger.campaign_state == "completed"
        and scorecard["verdict"] == "go"
        and all(coverage_gates.values())
    ):
        verdict = "go"
    else:
        verdict = "no_go"
    return {
        "schema_version": 1,
        "campaign_key": campaign.campaign_key,
        "campaign_digest": campaign.digest,
        "campaign_state": ledger.campaign_state,
        "sample_size": sample_size,
        "source_report_digests": sorted(report_digests),
        "runtime_build_identities": sorted(build_identities),
        "coverage": {
            "domains": dict(sorted(domain_counts.items())),
            "shapes": dict(sorted(shape_counts.items())),
            "messy_observations": messy_count,
            "max_single_domain_share": round(max_domain_share, 6),
        },
        "coverage_gates": coverage_gates,
        "scorecard": scorecard,
        "verdict": verdict,
    }


__all__ = [
    "PilotCampaignCaseRef",
    "PilotCampaignLedger",
    "PilotCampaignObservation",
    "PilotCampaignSpec",
    "PilotCampaignThresholds",
    "digest_of",
    "evaluate_pilot_campaign",
    "question_digest",
    "source_case_index",
    "validate_campaign_source",
]
