"""Manifest-bound onboarding for approved RtR company documents."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.models import StrictModel
from rtr_copilot.pilot.file_campaign import (
    PilotFileCampaign,
    PilotFileEntry,
    PlannedFile,
    plan_file_entries,
)


class EnterpriseFileManifest(StrictModel):
    """A bounded, checksum-locked company-file admission batch."""

    schema_version: Literal[1] = 1
    campaign: Literal["TIP-027"] = "TIP-027"
    root_label: str = Field(min_length=1, max_length=160)
    owner_boundary: str = Field(min_length=1, max_length=240)
    entries: list[PilotFileEntry] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def entries_are_unique(self) -> EnterpriseFileManifest:
        keys = [entry.manifest_key for entry in self.entries]
        paths = [entry.path for entry in self.entries]
        checksums = [entry.sha256 for entry in self.entries]
        if len(keys) != len(set(keys)) or len(paths) != len(set(paths)):
            raise ValueError("enterprise_file_manifest_duplicate")
        if len(checksums) != len(set(checksums)):
            raise ValueError("enterprise_file_manifest_duplicate_content")
        return self


def load_enterprise_file_manifest(path: Path) -> EnterpriseFileManifest:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("yaml_dependency_unavailable") from error
    return EnterpriseFileManifest.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")),
    )


def enterprise_manifest_fingerprint(manifest: EnterpriseFileManifest) -> str:
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def plan_enterprise_files(
    manifest: EnterpriseFileManifest,
    company_root: Path,
) -> list[PlannedFile]:
    return plan_file_entries(manifest.entries, company_root)


class EnterpriseFileCampaign(PilotFileCampaign):
    """Reuse the hardened ingestion pipeline under a distinct TIP-027 lineage."""

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        super().__init__(
            uow=uow,
            campaign_key="tip027",
            campaign_label="TIP-027 Company Corpus",
        )


__all__ = [
    "EnterpriseFileCampaign",
    "EnterpriseFileManifest",
    "enterprise_manifest_fingerprint",
    "load_enterprise_file_manifest",
    "plan_enterprise_files",
]
