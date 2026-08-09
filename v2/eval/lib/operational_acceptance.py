"""Pure validation and scoring for TIP-026 operational acceptance runs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

VALID_EXPECTATIONS = {"grounded", "honest_null"}
CAMPAIGN_DATABASE_PREFIX = "rtr_tip026_"


def folded(value: str) -> str:
    """Case/diacritic/punctuation-insensitive text used only by the test oracle."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def _oracle_tokens(value: str) -> list[str]:
    return [
        str(int(token)) if token.isdigit() else token
        for token in folded(value).split()
    ]


def term_present(term: str, answer: str) -> bool:
    """Formatting-tolerant lexical oracle, never used by product runtime."""
    normalized_term = folded(term)
    normalized_answer = folded(answer)
    if normalized_term in normalized_answer:
        return True
    if normalized_term.isdigit():
        return normalized_term in re.sub(r"\D", "", answer)
    # Business specifications are routinely rendered with typographic spacing
    # or locale punctuation (``50.4V`` vs ``50,4 V``, ``61MP`` vs ``61 MP``).
    # When the oracle contains both a number and a unit, compare an alphanumeric
    # compact form so presentation does not become a factual failure.
    # TIP-030: the same locale tolerance applies to alphabetic oracles —
    # "Vietnam" must match the Vietnamese spaced form "Việt Nam" (folded:
    # "viet nam") and "U.S.-aligned" any punctuation variant. Compact-compare
    # any oracle whose alphanumeric core is >= 4 chars; short tokens stay
    # strict so trivial collisions cannot manufacture a pass.
    if len(re.sub(r"[^a-z0-9]", "", normalized_term)) >= 4:
        compact_term = re.sub(r"[^a-z0-9]", "", normalized_term)
        compact_answer = re.sub(r"[^a-z0-9]", "", normalized_answer)
        if compact_term and compact_term in compact_answer:
            return True
    expected = _oracle_tokens(term)
    actual = iter(_oracle_tokens(answer))
    return all(any(item == token for item in actual) for token in expected)


def validate_database_target(actual: str, expected: str) -> None:
    """Refuse to run a write-realistic campaign outside its disposable clone."""
    if not expected.startswith(CAMPAIGN_DATABASE_PREFIX):
        raise ValueError("campaign_database_prefix_invalid")
    if actual != expected:
        raise ValueError("campaign_database_target_mismatch")


def load_campaign(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("campaign_schema_version_invalid")
    if not isinstance(payload.get("thresholds"), dict):
        raise ValueError("campaign_thresholds_missing")

    ids: set[str] = set()
    flattened: list[dict[str, Any]] = []
    for raw in payload.get("cases", []):
        flattened.append({**raw, "scenario_id": None})
    for scenario in payload.get("scenarios", []):
        scenario_id = str(scenario.get("id", ""))
        domain = str(scenario.get("domain", "conversation"))
        for turn_index, raw in enumerate(scenario.get("turns", []), start=1):
            flattened.append({
                **raw,
                "domain": domain,
                "scenario_id": scenario_id,
                "turn_index": turn_index,
            })

    if not flattened:
        raise ValueError("campaign_cases_missing")
    for case in flattened:
        case_id = str(case.get("id", ""))
        if not case_id or case_id in ids:
            raise ValueError("campaign_case_id_invalid_or_duplicate")
        ids.add(case_id)
        if case.get("expect") not in VALID_EXPECTATIONS:
            raise ValueError(f"campaign_expectation_invalid:{case_id}")
        if not str(case.get("question", "")).strip():
            raise ValueError(f"campaign_question_missing:{case_id}")
        if not str(case.get("domain", "")).strip():
            raise ValueError(f"campaign_domain_missing:{case_id}")
        if not isinstance(case.get("shapes"), list) or not case["shapes"]:
            raise ValueError(f"campaign_shapes_missing:{case_id}")
        groups = case.get("expected_record_groups", [])
        if case["expect"] == "grounded" and (
            not isinstance(groups, list)
            or not groups
            or any(not isinstance(group, list) or not group for group in groups)
        ):
            raise ValueError(f"campaign_citation_oracle_missing:{case_id}")
        term_groups = case.get("required_term_groups", [])
        if (
            not isinstance(term_groups, list)
            or any(not isinstance(group, list) or not group for group in term_groups)
        ):
            raise ValueError(f"campaign_term_group_oracle_invalid:{case_id}")

    return {**payload, "flattened_cases": flattened}


def score_case(
    case: dict[str, Any],
    *,
    state: str,
    answer: str,
    citations: list[str],
    reason_code: str | None,
    latency_ms: float,
) -> dict[str, Any]:
    expected = str(case["expect"])
    citation_set = set(citations)
    groups = [set(group) for group in case.get("expected_record_groups", [])]
    citation_ok = expected == "honest_null" or all(
        bool(group & citation_set) for group in groups
    )
    missing_terms = [
        term
        for term in case.get("required_terms", [])
        if not term_present(str(term), answer)
    ]
    missing_term_groups = [
        [str(term) for term in group]
        for group in case.get("required_term_groups", [])
        if not any(term_present(str(term), answer) for term in group)
    ]
    terms_ok = expected == "honest_null" or (
        not missing_terms and not missing_term_groups
    )
    allowed_reasons = set(case.get("allowed_reason_codes", []))
    reason_ok = not allowed_reasons or reason_code in allowed_reasons
    state_ok = state == expected
    passed = state_ok and citation_ok and terms_ok and reason_ok
    # A grounded answer is not automatically false-grounded merely because it
    # is incomplete or cites a different approved record than the campaign's
    # preferred oracle. Keep those failures visible through ``terms_ok`` and
    # ``citation_ok`` while reserving this safety metric for answers that are
    # materially unsupported: an answer where silence was expected, an answer
    # without citations, or an answer that misses both the evidence oracle and
    # the required factual content.
    false_grounded = state == "grounded" and (
        expected == "honest_null"
        or not citations
        or (not citation_ok and not terms_ok)
    )
    failures: list[str] = []
    if not state_ok:
        failures.append("unexpected_state")
    if not citation_ok:
        failures.append("citation_miss")
    if not terms_ok:
        failures.append("required_term_miss")
    if not reason_ok:
        failures.append("reason_code_miss")
    if false_grounded:
        failures.append("false_grounded")
    question = str(case["question"])
    return {
        "id": case["id"],
        "domain": case["domain"],
        "shapes": case["shapes"],
        "scenario_id": case.get("scenario_id"),
        "turn_index": case.get("turn_index"),
        "question_digest": hashlib.sha256(question.encode()).hexdigest(),
        "expected_state": expected,
        "actual_state": state,
        "reason_code": reason_code,
        "citations": citations,
        "citation_ok": citation_ok,
        "missing_term_digests": [
            hashlib.sha256(str(term).encode()).hexdigest()[:16]
            for term in missing_terms
        ] + [
            hashlib.sha256("|".join(group).encode()).hexdigest()[:16]
            for group in missing_term_groups
        ],
        "terms_ok": terms_ok,
        "false_grounded": false_grounded,
        "failures": failures,
        "latency_ms": round(latency_ms, 3),
        "passed": passed,
    }


def _rate(rows: list[dict[str, Any]]) -> float:
    return sum(bool(row["passed"]) for row in rows) / len(rows) if rows else 1.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def summarize(
    rows: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    grounded = [row for row in rows if row["expected_state"] == "grounded"]
    nulls = [row for row in rows if row["expected_state"] == "honest_null"]
    follow_ups = [row for row in rows if "follow_up" in row["shapes"]]
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[row["domain"]].append(row)
        for shape in row["shapes"]:
            by_shape[shape].append(row)

    citation_accuracy = (
        sum(bool(row["citation_ok"]) for row in grounded) / len(grounded)
        if grounded else 1.0
    )
    metrics = {
        "total": len(rows),
        "passed": sum(bool(row["passed"]) for row in rows),
        "failed": sum(not bool(row["passed"]) for row in rows),
        "overall_pass_rate": _rate(rows),
        "grounded_expected": len(grounded),
        "grounded_success_rate": _rate(grounded),
        "citation_accuracy": citation_accuracy,
        "honest_null_expected": len(nulls),
        "honest_null_precision": _rate(nulls),
        "false_grounded_count": sum(bool(row["false_grounded"]) for row in rows),
        "follow_up_pass_rate": _rate(follow_ups),
        "p50_latency_ms": _percentile([float(row["latency_ms"]) for row in rows], 0.5),
        "p95_latency_ms": _percentile([float(row["latency_ms"]) for row in rows], 0.95),
        "domains": {
            key: {
                "total": len(items),
                "passed": sum(bool(item["passed"]) for item in items),
                "pass_rate": _rate(items),
            }
            for key, items in sorted(by_domain.items())
        },
        "shapes": {
            key: {
                "total": len(items),
                "passed": sum(bool(item["passed"]) for item in items),
                "pass_rate": _rate(items),
            }
            for key, items in sorted(by_shape.items())
        },
    }
    min_domain = min(
        (item["pass_rate"] for item in metrics["domains"].values()),
        default=1.0,
    )
    gates = {
        "overall_pass_rate": metrics["overall_pass_rate"] >= float(thresholds["overall_pass_rate"]),
        "grounded_success_rate": metrics["grounded_success_rate"]
        >= float(thresholds["grounded_success_rate"]),
        "citation_accuracy": metrics["citation_accuracy"] >= float(thresholds["citation_accuracy"]),
        "honest_null_precision": metrics["honest_null_precision"]
        >= float(thresholds["honest_null_precision"]),
        "false_grounded_count": metrics["false_grounded_count"]
        <= int(thresholds["false_grounded_count"]),
        "minimum_domain_pass_rate": min_domain >= float(thresholds["minimum_domain_pass_rate"]),
        "follow_up_pass_rate": metrics["follow_up_pass_rate"]
        >= float(thresholds["follow_up_pass_rate"]),
        "p95_latency_ms": metrics["p95_latency_ms"] <= float(thresholds["p95_latency_ms"]),
    }
    return {
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
    }


__all__ = [
    "folded",
    "load_campaign",
    "score_case",
    "summarize",
    "term_present",
    "validate_database_target",
]
