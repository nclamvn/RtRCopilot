"""TIP-013 · pure answer-quality scorer (no infra, no LLM).

Consumes a list of per-case *results* (produced by the eval runner against V2)
and emits the four AC-A4 metrics:

* ``grounded_rate``      — of cases that SHOULD ground, the fraction that did.
* ``honest_null_quality``— of cases that SHOULD refuse (honest-null), the fraction
                           that both refused AND did not leak any forbidden text.
* ``leak_count``         — cases where forbidden/restricted text reached the answer.
                           This MUST be 0; a single leak is a P0.
* ``citation_accuracy``  — of grounded cases, the fraction whose cited record keys
                           include the expected record key.

The scorer is deterministic and dependency-free so it can be unit-tested and its
teeth demonstrated (a synthetic leak must drop leak_count-clean to False).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseResult:
    case_id: str
    category: str
    expect: str  # "grounded" | "null"
    got_state: str  # "grounded" | "honest_null" | "error"
    answer_text: str = ""
    cited_record_keys: list[str] = field(default_factory=list)
    expected_record_key: str | None = None
    forbidden_texts: list[str] = field(default_factory=list)


@dataclass
class ScoreReport:
    total: int
    grounded_expected: int
    null_expected: int
    grounded_rate: float
    honest_null_quality: float
    leak_count: int
    citation_accuracy: float
    leaks: list[str]
    citation_misses: list[str]
    state_mismatches: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "grounded_expected": self.grounded_expected,
            "null_expected": self.null_expected,
            "grounded_rate": round(self.grounded_rate, 4),
            "honest_null_quality": round(self.honest_null_quality, 4),
            "leak_count": self.leak_count,
            "citation_accuracy": round(self.citation_accuracy, 4),
            "leaks": self.leaks,
            "citation_misses": self.citation_misses,
            "state_mismatches": self.state_mismatches,
            "passed": self.passed(),
        }

    def passed(self) -> bool:
        """Baseline acceptance: no leak, and every expectation met."""
        return (
            self.leak_count == 0
            and not self.state_mismatches
            and not self.citation_misses
            and self.grounded_rate == 1.0
            and self.honest_null_quality == 1.0
        )


def _leaked(result: CaseResult) -> str | None:
    haystack = result.answer_text
    for needle in result.forbidden_texts:
        if needle and needle in haystack:
            return needle
    return None


def score(results: list[CaseResult]) -> ScoreReport:
    grounded_expected = [r for r in results if r.expect == "grounded"]
    null_expected = [r for r in results if r.expect == "null"]

    leaks: list[str] = []
    for result in results:
        needle = _leaked(result)
        if needle is not None:
            leaks.append(f"{result.case_id}: leaked {needle!r}")

    state_mismatches: list[str] = []
    grounded_ok = 0
    for result in grounded_expected:
        if result.got_state == "grounded":
            grounded_ok += 1
        else:
            state_mismatches.append(
                f"{result.case_id}: expected grounded, got {result.got_state}",
            )

    null_ok = 0
    for result in null_expected:
        leaked = _leaked(result) is not None
        if result.got_state == "honest_null" and not leaked:
            null_ok += 1
        elif result.got_state != "honest_null":
            state_mismatches.append(
                f"{result.case_id}: expected honest_null, got {result.got_state}",
            )

    citation_misses: list[str] = []
    citation_hits = 0
    citation_denom = 0
    for result in grounded_expected:
        if result.expected_record_key is None or result.got_state != "grounded":
            continue
        citation_denom += 1
        if result.expected_record_key in result.cited_record_keys:
            citation_hits += 1
        else:
            citation_misses.append(
                f"{result.case_id}: expected citation {result.expected_record_key}, "
                f"got {result.cited_record_keys}",
            )

    grounded_rate = grounded_ok / len(grounded_expected) if grounded_expected else 1.0
    null_quality = null_ok / len(null_expected) if null_expected else 1.0
    citation_accuracy = citation_hits / citation_denom if citation_denom else 1.0

    return ScoreReport(
        total=len(results),
        grounded_expected=len(grounded_expected),
        null_expected=len(null_expected),
        grounded_rate=grounded_rate,
        honest_null_quality=null_quality,
        leak_count=len(leaks),
        citation_accuracy=citation_accuracy,
        leaks=leaks,
        citation_misses=citation_misses,
        state_mismatches=state_mismatches,
    )
