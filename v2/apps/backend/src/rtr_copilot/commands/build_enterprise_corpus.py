"""Inventory RtR sources and build/import a governed TheSkyWatch package."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.enterprise_corpus.inventory import build_inventory
from rtr_copilot.enterprise_corpus.theskywatch import SOURCE_KEY, emit_package
from rtr_copilot.governance.admin import AdminGovernanceService
from rtr_copilot.research.service import ResearchService


async def _activate(
    staging_name: str,
    out_root: Path,
    curator_id: uuid.UUID,
) -> dict[str, object]:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("enterprise_corpus_activation_local_only")
    subject = Subject(
        user_id=str(curator_id),
        issuer="tip027-local",
        sub=curator_id.hex,
        email=f"{curator_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        display_name="TIP-027 local curator",
        roles={Role.CURATOR, Role.ADMIN},
    )
    admin = AdminGovernanceService()
    sources = await admin.list_sources(
        subject, request_id="tip027-theskywatch:source-list",
    )
    source = next((item for item in sources if item.stable_key == SOURCE_KEY), None)
    if source is None:
        source = await admin.create_source(
            subject,
            stable_key=SOURCE_KEY,
            display_name="TheSkyWatch governed UAV registry",
            description=(
                "Checksum-bound TheSkyWatch entity and editorial snapshots; "
                "Research zone only"
            ),
            origin="refinery",
            owner_subject_id=curator_id,
            classification="public_internal",
            lifecycle="active",
            request_id="tip027-theskywatch:source-create",
        )
    elif (
        source.owner_subject_id != curator_id
        or source.classification != "public_internal"
        or source.lifecycle != "active"
    ):
        raise RuntimeError("theskywatch_research_source_drift")
    local_settings = settings.model_copy(update={
        "research_staging_root": out_root.resolve(),
    })
    imported = await ResearchService(local_settings).import_package(
        subject,
        staging_name,
        request_id="tip027-theskywatch:import",
    )
    return {
        "package_id": str(imported.package.package_id),
        "source_id": str(source.source_id),
        "record_count": imported.package.record_count,
        "tier_composition": imported.package.tier_composition,
        "state": imported.package.import_state,
        "result": "idempotent" if imported.idempotent else "imported",
    }


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    inventory = build_inventory(args.rtr_root, args.knowledge_root)
    result = emit_package(args.theskywatch_root, args.out)
    activation = (
        asyncio.run(_activate(result.staging_name, args.out, args.curator_id))
        if args.apply else None
    )
    return {
        "inventory": inventory.to_dict(),
        "theskywatch": {
            **result.__dict__,
            "package_root": str(result.package_root),
        },
        "activation": activation,
        "mode": "apply" if args.apply else "dry_run",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtr-root", required=True, type=Path)
    parser.add_argument("--knowledge-root", required=True, type=Path)
    parser.add_argument("--theskywatch-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--curator-id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if args.apply and (not args.approve or args.curator_id is None):
        parser.error("--apply requires --approve and --curator-id")
    print(json.dumps(
        _payload(args), ensure_ascii=False, sort_keys=True, default=str,
    ))


if __name__ == "__main__":
    main()
