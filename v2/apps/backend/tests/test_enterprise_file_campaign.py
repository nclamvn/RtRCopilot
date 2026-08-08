import hashlib
from pathlib import Path

import pytest

from rtr_copilot.enterprise_corpus.file_campaign import (
    EnterpriseFileCampaign,
    EnterpriseFileManifest,
    enterprise_manifest_fingerprint,
    plan_enterprise_files,
)
from rtr_copilot.pilot.file_campaign import PilotFileCampaign


def _entry(path: Path, *, key: str, owner: str) -> dict[str, object]:
    payload = (f"enterprise-{key}-".encode() * 200)[:1_500]
    path.write_bytes(payload)
    return {
        "manifest_key": key,
        "path": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mime_type": "application/pdf",
        "classification": "internal",
        "source_zone": "private_context",
        "owner_subject_id": owner,
    }


def test_enterprise_manifest_is_bounded_checksum_locked_and_deterministic(
    tmp_path: Path,
) -> None:
    owner = "11111111-1111-4111-8111-111111111111"
    manifest = EnterpriseFileManifest.model_validate({
        "schema_version": 1,
        "campaign": "TIP-027",
        "root_label": "RtR",
        "owner_boundary": "Approved internal documents",
        "entries": [
            _entry(tmp_path / "project.pdf", key="project.approved", owner=owner),
            _entry(tmp_path / "process.pdf", key="process.approved", owner=owner),
        ],
    })

    planned = plan_enterprise_files(manifest, tmp_path)
    assert [item.entry.manifest_key for item in planned] == [
        "project.approved",
        "process.approved",
    ]
    assert enterprise_manifest_fingerprint(manifest) == (
        enterprise_manifest_fingerprint(manifest)
    )

    campaign = EnterpriseFileCampaign()
    assert campaign._logical_name("project.approved") == "tip027.project.approved"
    assert campaign._source_id("internal", planned[0].entry.owner_subject_id) != (
        PilotFileCampaign()._source_id(
            "internal",
            planned[0].entry.owner_subject_id,
        )
    )


def test_enterprise_manifest_rejects_duplicate_content(tmp_path: Path) -> None:
    owner = "11111111-1111-4111-8111-111111111111"
    first = _entry(tmp_path / "first.pdf", key="first.approved", owner=owner)
    second = dict(first)
    second["manifest_key"] = "second.approved"
    second["path"] = "second.pdf"
    (tmp_path / "second.pdf").write_bytes((tmp_path / "first.pdf").read_bytes())

    with pytest.raises(ValueError, match="enterprise_file_manifest_duplicate_content"):
        EnterpriseFileManifest.model_validate({
            "schema_version": 1,
            "campaign": "TIP-027",
            "root_label": "RtR",
            "owner_boundary": "Approved internal documents",
            "entries": [first, second],
        })
