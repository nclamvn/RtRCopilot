"""Validate or locally activate the TIP-024 representative file manifest."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from rtr_copilot.pilot.file_campaign import (
    MIME_FAMILY,
    PilotFileCampaign,
    load_file_manifest,
    manifest_fingerprint,
    plan_files,
)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    manifest = load_file_manifest(args.manifest)
    planned = plan_files(manifest, args.knowledge_root)
    outcomes = await PilotFileCampaign().apply(planned) if args.apply else []
    families: dict[str, int] = {}
    for item in planned:
        family = MIME_FAMILY[item.entry.mime_type]
        families[family] = families.get(family, 0) + 1
    return {
        "campaign": "TIP-024",
        "computed_at": datetime.now(UTC).isoformat(),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "file_count": len(planned),
        "byte_size": sum(item.byte_size for item in planned),
        "families": dict(sorted(families.items())),
        "apply": bool(args.apply),
        "approved": bool(args.approve),
        "production_boundary": "local_dev_only",
        "outcomes": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--knowledge-root", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.approve:
        parser.error("--apply requires --approve")
    report = asyncio.run(_run(args))
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
