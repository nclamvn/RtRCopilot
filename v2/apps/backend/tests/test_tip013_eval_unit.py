"""TIP-013 Phase A · eval/parity building blocks — hermetic unit tests.

No database, no Redis. Proves:

* the pilot oracle loads the REAL phase-1 answering logic against a SYNTHETIC GOI
  (never the real corpus) and yields the three answer shapes; and
* the pure scorer computes the AC-A4 metrics AND has teeth — an injected leak,
  a wrong citation and a wrong state each move the score.
"""

import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[3] / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from lib.pilot_oracle import PilotOracle  # noqa: E402
from lib.scoring import CaseResult, score  # noqa: E402


def test_pilot_oracle_answers_synthetic_facts_and_nulls() -> None:
    oracle = PilotOracle()
    assert oracle.record_ids == ["HERA-END", "OMNI-DEF", "RTR-OVERVIEW", "VEGA-PAY"]

    hera = oracle.outcome("What is the HERA flight endurance?")
    assert hera["state"] == "answered"
    assert "HERA-END" in hera["cited_records"]

    omni = oracle.outcome("What is OmniSight used for?")
    assert omni["state"] == "answered"
    assert "OMNI-DEF" in omni["cited_records"]

    warranty = oracle.outcome("What is the warranty period for the maintenance contract?")
    assert warranty["state"] == "null"
    assert warranty["cited_records"] == []

    patents = oracle.outcome("How many patents does RtR hold?")
    assert patents["state"] == "null"


def test_scorer_clean_run_passes() -> None:
    results = [
        CaseResult("E1", "fact_lookup", "grounded", "grounded",
                   answer_text="HERA endurance is 55 minutes. [C1]",
                   cited_record_keys=["EVAL-HERA"], expected_record_key="EVAL-HERA"),
        CaseResult("E3", "honest_null", "null", "honest_null",
                   answer_text="no evidence"),
        CaseResult("E4", "acl_restricted", "null", "honest_null",
                   answer_text="no evidence", forbidden_texts=["CLASSIFIED-ROTOR-BLUEPRINT"]),
    ]
    report = score(results)
    assert report.leak_count == 0
    assert report.grounded_rate == 1.0
    assert report.honest_null_quality == 1.0
    assert report.citation_accuracy == 1.0
    assert report.passed()


def test_scorer_detects_leak() -> None:
    results = [
        CaseResult("E4", "acl_restricted", "null", "grounded",
                   answer_text="CLASSIFIED-ROTOR-BLUEPRINT restricted detail. [C1]",
                   cited_record_keys=["EVAL-ACL"],
                   forbidden_texts=["CLASSIFIED-ROTOR-BLUEPRINT"]),
    ]
    report = score(results)
    assert report.leak_count == 1
    assert not report.passed()
    assert report.leaks and "E4" in report.leaks[0]


def test_scorer_detects_wrong_citation_and_state() -> None:
    results = [
        CaseResult("E1", "fact_lookup", "grounded", "grounded",
                   answer_text="wrong fact [C1]",
                   cited_record_keys=["OTHER-REC"], expected_record_key="EVAL-HERA"),
        CaseResult("E3", "honest_null", "null", "grounded",
                   answer_text="should have refused [C1]"),
    ]
    report = score(results)
    assert report.citation_accuracy == 0.0
    assert report.honest_null_quality == 0.0
    assert report.state_mismatches
    assert report.citation_misses
    assert not report.passed()
