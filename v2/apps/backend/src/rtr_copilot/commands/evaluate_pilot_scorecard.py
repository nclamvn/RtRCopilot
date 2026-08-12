"""Validate and score a content-free bounded-pilot observation file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rtr_copilot.enterprise_corpus.pilot_scorecard import (
    PilotScorecardInput,
    evaluate_pilot_scorecard,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = PilotScorecardInput.model_validate_json(
        args.input.read_text(encoding="utf-8"),
    )
    result = evaluate_pilot_scorecard(source)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if result["verdict"] != "go":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
