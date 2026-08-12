"""Validate TIP-034 campaign provenance and evaluate the shared pilot scorecard."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from rtr_copilot.enterprise_corpus.pilot_campaign import (
    PilotCampaignLedger,
    PilotCampaignSpec,
    evaluate_pilot_campaign,
    validate_campaign_source,
)


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"pilot_campaign_json_object_required:{path.name}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--source-suite", type=Path, required=True)
    parser.add_argument("--acceptance-report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--definition-only",
        action="store_true",
        help="validate immutable scope without treating not_started as a failure",
    )
    args = parser.parse_args()

    campaign = PilotCampaignSpec.model_validate(_json(args.campaign))
    ledger = PilotCampaignLedger.model_validate(_json(args.ledger))
    source_bytes = args.source_suite.read_bytes()
    source_payload = json.loads(source_bytes)
    if not isinstance(source_payload, dict):
        raise ValueError("pilot_campaign_source_object_required")
    source_cases = validate_campaign_source(
        campaign,
        source_payload,
        source_digest=hashlib.sha256(source_bytes).hexdigest(),
    )
    reports = [_json(path) for path in args.acceptance_report]
    result = evaluate_pilot_campaign(campaign, ledger, source_cases, reports)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not args.definition_only and result["verdict"] != "go":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
