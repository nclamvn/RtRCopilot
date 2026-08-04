"""Build a checksum-bound TIP-024 Research package from a refinery dataset."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.governance.admin import AdminGovernanceService
from rtr_copilot.pilot.research_adapter import SOURCE_KEY, emit_package
from rtr_copilot.research.service import ResearchService


async def _activate(
    staging_name: str,
    out_root: Path,
    curator_id: uuid.UUID,
) -> dict[str, object]:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("pilot_activation_local_only")
    subject = Subject(
        user_id=str(curator_id), issuer="tip024-local", sub=curator_id.hex,
        email=f"{curator_id.hex}@rtrobotics.com", canonical_domain="rtrobotics.com",
        display_name="TIP-024 local curator", roles={Role.CURATOR, Role.ADMIN},
    )
    admin = AdminGovernanceService()
    sources = await admin.list_sources(
        subject, request_id="tip024-research:source-list",
    )
    source = next((item for item in sources if item.stable_key == SOURCE_KEY), None)
    if source is None:
        source = await admin.create_source(
            subject,
            stable_key=SOURCE_KEY,
            display_name="Vietnam strategic technology · TIP-024",
            description=(
                "Checksum-bound CNCL refinery package; local pilot Research zone only"
            ),
            origin="refinery",
            owner_subject_id=curator_id,
            classification="internal",
            lifecycle="active",
            request_id="tip024-research:source-create",
        )
    elif (
        source.owner_subject_id != curator_id
        or source.classification != "internal"
        or source.lifecycle != "active"
    ):
        raise RuntimeError("pilot_research_source_drift")
    local_settings = settings.model_copy(update={
        "research_staging_root": out_root.resolve(),
    })
    imported = await ResearchService(local_settings).import_package(
        subject, staging_name, request_id="tip024-research:import",
    )
    return {
        "package_id": str(imported.package.package_id),
        "source_id": str(source.source_id),
        "record_count": imported.package.record_count,
        "state": imported.package.import_state,
        "result": "idempotent" if imported.idempotent else "imported",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--curator-id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if args.apply and (not args.approve or args.curator_id is None):
        parser.error("--apply requires --approve and --curator-id")
    result = emit_package(args.dataset_root, args.out)
    activation = (
        asyncio.run(_activate(result.staging_name, args.out, args.curator_id))
        if args.apply else None
    )
    print(json.dumps({
        **result.__dict__,
        "package_root": str(result.package_root),
        "activation": activation,
        "production_boundary": "local_dev_only",
    }, ensure_ascii=False, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
