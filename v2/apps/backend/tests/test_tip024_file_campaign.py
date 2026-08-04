import hashlib
from pathlib import Path

import pytest

from rtr_copilot.pilot.file_campaign import (
    PilotFileManifest,
    manifest_fingerprint,
    plan_files,
)


def _manifest(root: Path) -> PilotFileManifest:
    extensions = [
        ("pdf", "application/pdf"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("png", "image/png"),
    ]
    entries = []
    for index in range(30):
        suffix, mime = extensions[index % len(extensions)]
        path = root / f"file-{index:02d}.{suffix}"
        payload = (f"pilot-{index}-".encode() * 200)[:1_200]
        path.write_bytes(payload)
        entries.append({
            "manifest_key": f"file-{index:02d}",
            "path": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mime_type": mime,
            "classification": "internal",
            "source_zone": "private_context",
            "owner_subject_id": "11111111-1111-4111-8111-111111111111",
        })
    return PilotFileManifest.model_validate({
        "schema_version": 1, "campaign": "TIP-024",
        "root_label": "KnowledgeBase", "entries": entries,
    })


def test_manifest_plan_is_checksum_bound_and_deterministic(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    assert len(plan_files(manifest, tmp_path)) == 30
    assert manifest_fingerprint(manifest) == manifest_fingerprint(manifest)
    (tmp_path / "file-00.pdf").write_bytes(b"drift" * 300)
    with pytest.raises(ValueError, match="pilot_file_checksum_drift:file-00"):
        plan_files(manifest, tmp_path)


def test_manifest_rejects_path_escape_and_missing_family(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path).model_dump(mode="json")
    manifest["entries"][0]["path"] = "../escape.pdf"
    with pytest.raises(ValueError, match="pilot_file_path_invalid"):
        PilotFileManifest.model_validate(manifest)
    manifest = _manifest(tmp_path).model_dump(mode="json")
    for entry in manifest["entries"]:
        entry["mime_type"] = "application/pdf"
    with pytest.raises(ValueError, match="pilot_file_families_incomplete"):
        PilotFileManifest.model_validate(manifest)
