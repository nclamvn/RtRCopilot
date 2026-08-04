#!/usr/bin/env python3
"""Emit an honest TIP-024 evaluation ledger from explicit observations only."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "apps" / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from rtr_copilot.pilot.questions import load_pilot_questions  # noqa: E402


def build_ledger(observations: dict[str, Any] | None = None) -> dict[str, Any]:
    observations = observations or {}
    results: list[dict[str, Any]] = []
    for case in load_pilot_questions():
        observation = observations.get(case.question_id)
        if isinstance(observation, dict) and observation.get("actual") in {
            "grounded", "honest_null", "denied", "blocked_caveat",
        }:
            actual = str(observation["actual"])
            results.append({
                "question_id": case.question_id,
                "status": "measured",
                "expected": case.expected,
                "actual": actual,
                "pass": actual == case.expected,
                "evidence": observation.get("evidence"),
                "untestable_reason": None,
            })
        else:
            results.append({
                "question_id": case.question_id,
                "status": "untestable",
                "expected": case.expected,
                "actual": None,
                "pass": None,
                "evidence": None,
                "untestable_reason": "requires_authenticated_live_pilot_observation",
            })
    measured = sum(item["status"] == "measured" for item in results)
    passed = sum(item["pass"] is True for item in results)
    return {
        "schema_version": 1,
        "campaign": "TIP-024",
        "computed_at": datetime.now(UTC).isoformat(),
        "provider_result_claimed": False,
        "summary": {
            "total": len(results),
            "measured": measured,
            "untestable": len(results) - measured,
            "passed": passed,
            "failed": measured - passed,
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    observations = (
        json.loads(args.observations.read_text(encoding="utf-8"))
        if args.observations else None
    )
    ledger = build_ledger(observations)
    payload = json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 1 if ledger["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
