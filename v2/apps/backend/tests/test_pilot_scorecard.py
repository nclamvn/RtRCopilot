import pytest
from pydantic import ValidationError

from rtr_copilot.enterprise_corpus.pilot_scorecard import (
    PilotObservation,
    PilotScorecardInput,
    PilotThresholds,
    evaluate_pilot_scorecard,
)


def observation(index: int, **overrides: object) -> PilotObservation:
    values: dict[str, object] = {
        "observation_id": f"observation-{index:03d}",
        "useful": True,
        "citations_checked": 2,
        "citations_supported": 2,
        "latency_ms": 1000,
        "provider_cost_usd": 0.02,
    }
    values.update(overrides)
    return PilotObservation.model_validate(values)


def test_empty_scorecard_is_truthfully_not_started() -> None:
    result = evaluate_pilot_scorecard(PilotScorecardInput(
        schema_version=1,
        campaign_state="not_started",
    ))
    assert result["verdict"] == "not_started"
    assert result["sample_size"] == 0


def test_completed_scorecard_passes_all_release_gates() -> None:
    rows = [observation(index) for index in range(20)]
    for index in range(3):
        rows[index] = observation(
            index,
            clarification_needed=True,
            clarification_recovered=True,
            expected_honest_null=True,
            actual_honest_null=True,
            citations_checked=0,
            citations_supported=0,
        )
    result = evaluate_pilot_scorecard(PilotScorecardInput(
        schema_version=1,
        campaign_state="completed",
        observations=rows,
    ))
    assert result["verdict"] == "go"
    assert all(result["gates"].values())


def test_safety_or_latency_failure_blocks_pilot() -> None:
    rows = [observation(index) for index in range(20)]
    for index in range(3):
        rows[index] = observation(
            index,
            clarification_needed=True,
            clarification_recovered=True,
            expected_honest_null=True,
            actual_honest_null=True,
            false_grounded=index == 0,
            latency_ms=30_000 if index < 2 else 1000,
        )
    result = evaluate_pilot_scorecard(PilotScorecardInput(
        schema_version=1,
        campaign_state="completed",
        thresholds=PilotThresholds(),
        observations=rows,
    ))
    assert result["verdict"] == "no_go"
    assert result["gates"]["false_grounded_count"] is False
    assert result["gates"]["p95_latency_ms"] is False


def test_honest_null_precision_and_recall_cannot_be_gamed() -> None:
    rows = [observation(index) for index in range(20)]
    for index in range(3):
        rows[index] = observation(
            index,
            clarification_needed=True,
            clarification_recovered=True,
            expected_honest_null=True,
            actual_honest_null=index != 0,
        )
    rows[3] = observation(3, actual_honest_null=True)
    result = evaluate_pilot_scorecard(PilotScorecardInput(
        schema_version=1,
        campaign_state="completed",
        observations=rows,
    ))
    assert result["metrics"]["honest_null_precision"] == pytest.approx(2 / 3)
    assert result["metrics"]["honest_null_recall"] == pytest.approx(2 / 3)
    assert result["verdict"] == "no_go"


def test_easy_only_sample_cannot_release_pilot() -> None:
    rows = [observation(index) for index in range(20)]
    result = evaluate_pilot_scorecard(PilotScorecardInput(
        schema_version=1,
        campaign_state="completed",
        observations=rows,
    ))
    assert result["gates"]["minimum_clarification_sample"] is False
    assert result["gates"]["minimum_honest_null_sample"] is False
    assert result["verdict"] == "no_go"


def test_observation_counts_and_clarification_are_consistent() -> None:
    with pytest.raises(ValidationError, match="supported_citations_exceed_checked"):
        observation(1, citations_checked=1, citations_supported=2)
    with pytest.raises(ValidationError, match="clarification_outcome_required"):
        observation(2, clarification_needed=True)
