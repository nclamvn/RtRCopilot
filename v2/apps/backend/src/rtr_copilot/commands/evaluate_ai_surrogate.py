"""Evaluate the segregated TIP-035.12 AI-surrogate operator campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rtr_copilot.enterprise_corpus.ai_surrogate import (
    AISurrogatePlan,
    AISurrogateUIResult,
    evaluate_ai_surrogate,
    file_digest,
)
from rtr_copilot.enterprise_corpus.pilot_campaign import PilotCampaignSpec


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    content = path.read_bytes()
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"ai_surrogate_json_object_required:{path.name}")
    return payload, content


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-suite", type=Path, required=True)
    parser.add_argument("--technical-report", type=Path, required=True)
    parser.add_argument("--ui-result", type=Path, required=True)
    parser.add_argument("--human-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    plan_payload, plan_bytes = _load(args.plan)
    manifest_payload, _ = _load(args.manifest)
    source_payload, source_bytes = _load(args.source_suite)
    technical_report, _ = _load(args.technical_report)
    ui_payload, _ = _load(args.ui_result)
    _, human_ledger_bytes = _load(args.human_ledger)
    result = evaluate_ai_surrogate(
        plan=AISurrogatePlan.model_validate(plan_payload),
        plan_digest=file_digest(plan_bytes),
        manifest=PilotCampaignSpec.model_validate(manifest_payload),
        source_payload=source_payload,
        source_digest=file_digest(source_bytes),
        technical_report=technical_report,
        ui_result=AISurrogateUIResult.model_validate(ui_payload),
        human_ledger_digest=file_digest(human_ledger_bytes),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
