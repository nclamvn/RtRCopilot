"""Content-free usefulness/trust/latency scorecard for bounded internal pilots."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PilotThresholds(StrictModel):
    min_observations: int = Field(default=20, ge=1, le=100_000)
    min_clarification_observations: int = Field(default=3, ge=1, le=100_000)
    min_honest_null_observations: int = Field(default=3, ge=1, le=100_000)
    min_citations_checked: int = Field(default=20, ge=1, le=1_000_000)
    usefulness_rate: float = Field(default=0.80, ge=0, le=1)
    clarification_recovery_rate: float = Field(default=0.80, ge=0, le=1)
    citation_accuracy: float = Field(default=0.95, ge=0, le=1)
    honest_null_precision: float = Field(default=1.0, ge=0, le=1)
    honest_null_recall: float = Field(default=1.0, ge=0, le=1)
    false_grounded_count: int = Field(default=0, ge=0)
    authz_leakage_count: int = Field(default=0, ge=0)
    p95_latency_ms: float = Field(default=25_000, gt=0)
    average_provider_cost_usd: float = Field(default=0.10, ge=0)


class PilotObservation(StrictModel):
    observation_id: str = Field(min_length=8, max_length=128)
    useful: bool
    clarification_needed: bool = False
    clarification_recovered: bool | None = None
    citations_checked: int = Field(default=0, ge=0, le=10_000)
    citations_supported: int = Field(default=0, ge=0, le=10_000)
    expected_honest_null: bool = False
    actual_honest_null: bool = False
    false_grounded: bool = False
    authz_leakage: bool = False
    latency_ms: float = Field(ge=0)
    provider_cost_usd: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent_counts(self) -> PilotObservation:
        if self.citations_supported > self.citations_checked:
            raise ValueError("supported_citations_exceed_checked")
        if self.clarification_needed and self.clarification_recovered is None:
            raise ValueError("clarification_outcome_required")
        if not self.clarification_needed and self.clarification_recovered is not None:
            raise ValueError("clarification_outcome_without_need")
        return self


class PilotScorecardInput(StrictModel):
    schema_version: Literal[1]
    campaign_state: Literal["not_started", "running", "completed"]
    thresholds: PilotThresholds = Field(default_factory=PilotThresholds)
    observations: list[PilotObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def state_matches_observations(self) -> PilotScorecardInput:
        if self.campaign_state == "not_started" and self.observations:
            raise ValueError("not_started_campaign_has_observations")
        return self


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def evaluate_pilot_scorecard(payload: PilotScorecardInput) -> dict[str, object]:
    rows = payload.observations
    if not rows:
        return {
            "schema_version": 1,
            "campaign_state": payload.campaign_state,
            "sample_size": 0,
            "metrics": {},
            "gates": {"minimum_sample": False},
            "verdict": "not_started",
        }
    clarification = [row for row in rows if row.clarification_needed]
    expected_nulls = [row for row in rows if row.expected_honest_null]
    actual_nulls = [row for row in rows if row.actual_honest_null]
    correct_nulls = [
        row for row in rows
        if row.expected_honest_null and row.actual_honest_null
    ]
    checked = sum(row.citations_checked for row in rows)
    supported = sum(row.citations_supported for row in rows)
    metrics = {
        "usefulness_rate": _rate(sum(row.useful for row in rows), len(rows)),
        "clarification_recovery_rate": _rate(
            sum(row.clarification_recovered is True for row in clarification),
            len(clarification),
        ),
        "citation_accuracy": _rate(supported, checked),
        "honest_null_precision": _rate(
            len(correct_nulls),
            len(actual_nulls),
        ),
        "honest_null_recall": _rate(
            len(correct_nulls),
            len(expected_nulls),
        ),
        "false_grounded_count": sum(row.false_grounded for row in rows),
        "authz_leakage_count": sum(row.authz_leakage for row in rows),
        "p95_latency_ms": round(_p95([row.latency_ms for row in rows]), 3),
        "average_provider_cost_usd": round(
            sum(row.provider_cost_usd for row in rows) / len(rows),
            6,
        ),
    }
    thresholds = payload.thresholds
    gates = {
        "minimum_sample": len(rows) >= thresholds.min_observations,
        "minimum_clarification_sample": len(clarification)
        >= thresholds.min_clarification_observations,
        "minimum_honest_null_sample": len(expected_nulls)
        >= thresholds.min_honest_null_observations,
        "minimum_citation_sample": checked >= thresholds.min_citations_checked,
        "usefulness_rate": metrics["usefulness_rate"] >= thresholds.usefulness_rate,
        "clarification_recovery_rate": metrics["clarification_recovery_rate"]
        >= thresholds.clarification_recovery_rate,
        "citation_accuracy": metrics["citation_accuracy"]
        >= thresholds.citation_accuracy,
        "honest_null_precision": metrics["honest_null_precision"]
        >= thresholds.honest_null_precision,
        "honest_null_recall": metrics["honest_null_recall"]
        >= thresholds.honest_null_recall,
        "false_grounded_count": metrics["false_grounded_count"]
        <= thresholds.false_grounded_count,
        "authz_leakage_count": metrics["authz_leakage_count"]
        <= thresholds.authz_leakage_count,
        "p95_latency_ms": metrics["p95_latency_ms"] <= thresholds.p95_latency_ms,
        "average_provider_cost_usd": metrics["average_provider_cost_usd"]
        <= thresholds.average_provider_cost_usd,
    }
    all_pass = all(gates.values())
    return {
        "schema_version": 1,
        "campaign_state": payload.campaign_state,
        "sample_size": len(rows),
        "metrics": metrics,
        "gates": gates,
        "verdict": (
            "go" if payload.campaign_state == "completed" and all_pass
            else "insufficient_sample" if not gates["minimum_sample"]
            else "no_go"
        ),
    }
