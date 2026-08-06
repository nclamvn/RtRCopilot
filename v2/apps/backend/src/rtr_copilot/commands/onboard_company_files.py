"""Validate, ingest and activate one approved TIP-027 company-file batch."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from rtr_copilot.enterprise_corpus.company_files import CompanyCorpusActivator
from rtr_copilot.enterprise_corpus.file_campaign import (
    EnterpriseFileCampaign,
    enterprise_manifest_fingerprint,
    load_enterprise_file_manifest,
    plan_enterprise_files,
)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    manifest = load_enterprise_file_manifest(args.manifest)
    planned = plan_enterprise_files(manifest, args.company_root)
    fingerprint = enterprise_manifest_fingerprint(manifest)
    if not args.apply:
        return {
            "mode": "dry_run",
            "manifest_fingerprint": fingerprint,
            "file_count": len(planned),
            "byte_size": sum(item.byte_size for item in planned),
            "owner_boundary": manifest.owner_boundary,
        }
    outcomes = await EnterpriseFileCampaign().apply(planned)
    activation = await CompanyCorpusActivator().activate_planned(
        planned,
        fingerprint=fingerprint,
        logical_prefix="tip027",
        approved_by=args.approved_by,
        request_id=f"tip027-company-files:{fingerprint[:16]}",
    )
    return {
        "mode": "apply",
        "manifest_fingerprint": fingerprint,
        "file_count": len(planned),
        "byte_size": sum(item.byte_size for item in planned),
        "owner_boundary": manifest.owner_boundary,
        "outcomes": outcomes,
        "activation": activation.to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--company-root", required=True, type=Path)
    parser.add_argument("--approved-by", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if args.apply and (not args.approve or args.approved_by is None):
        parser.error("--apply requires --approve and --approved-by")
    print(json.dumps(
        asyncio.run(_run(args)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
