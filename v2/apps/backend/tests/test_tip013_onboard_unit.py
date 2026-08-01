"""TIP-013 Phase A · onboarding tool — hermetic unit tests (no infra).

These exercise the two-phase, fail-closed *validation* gate and the dry-run /
approval discipline entirely on the filesystem: no database, no Redis. They
prove a clean batch would pass every gate, a defective SOT item (bad provenance
or a classification downgrade), a curator mismatch, or a malformed research item
rejects the WHOLE batch, and that --apply without --approve refuses to activate
anything.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from research_fixtures import build_research_package, research_record_row
from sot_fixtures import NOW, SECRET, build_package

from rtr_copilot.commands.onboard_batch import (
    BatchManifest,
    OnboardBatch,
    load_manifest,
)
from rtr_copilot.config import get_settings


def _settings(sot_root: Path, research_root: Path) -> Any:
    return get_settings().model_copy(update={
        "sot_staging_root": sot_root,
        "research_staging_root": research_root,
        "sot_signing_secret": SecretStr(SECRET),
    })


def _tool(sot_root: Path, research_root: Path) -> OnboardBatch:
    return OnboardBatch(_settings(sot_root, research_root), clock=lambda: NOW)


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    sot_root = tmp_path / "sot"
    research_root = tmp_path / "research"
    sot_root.mkdir()
    research_root.mkdir()
    return sot_root, research_root


def test_load_manifest_json_roundtrip(tmp_path: Path) -> None:
    curator = uuid.uuid4()
    data = {
        "batch_id": "b1",
        "curator_subject_id": str(curator),
        "sot_items": [{"staging_name": "package-x"}],
        "research_items": [{"staging_name": "research-y", "source_key": "refinery.z"}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    manifest = load_manifest(path)
    assert manifest.batch_id == "b1"
    assert manifest.curator_subject_id == curator
    assert manifest.sot_items[0].staging_name == "package-x"
    assert manifest.research_items[0].source_key == "refinery.z"


async def test_clean_batch_dry_run_validates(tmp_path: Path) -> None:
    sot_root, research_root = _roots(tmp_path)
    curator = uuid.uuid4()
    package_root = build_package(
        sot_root,
        curator_id=curator,
        owner_id=curator,
        source_key="rtr.clean",
        record_key="CLEAN.001",
    )
    research_name = build_research_package(
        research_root,
        source_key="refinery.clean",
        records=[research_record_row(text="synthetic clean insight")],
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "clean",
        "curator_subject_id": str(curator),
        "sot_items": [{"staging_name": package_root.name}],
        "research_items": [
            {"staging_name": research_name, "source_key": "refinery.clean"},
        ],
    })
    report = await _tool(sot_root, research_root).run(
        manifest, apply=False, approved=False,
    )
    assert report.status == "validated"
    assert report.activated_count == 0
    assert all(item.ok for item in report.items)
    assert {item.state for item in report.items} == {"planned_valid"}


async def test_defective_provenance_rejects_whole_batch(tmp_path: Path) -> None:
    sot_root, research_root = _roots(tmp_path)
    curator = uuid.uuid4()
    good = build_package(
        sot_root,
        curator_id=curator,
        owner_id=curator,
        source_key="rtr.good",
        record_key="GOOD.001",
    )
    # Well-formed package (checksums valid) but the record is a claim asserting an
    # approved verification state — the policy validator must reject it.
    bad = build_package(
        sot_root,
        curator_id=curator,
        owner_id=curator,
        source_key="rtr.bad",
        record_key="BAD.001",
        provenance_level="claim",
        verification_state="approved",
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "defective",
        "curator_subject_id": str(curator),
        "sot_items": [
            {"staging_name": good.name},
            {"staging_name": bad.name},
        ],
    })
    report = await _tool(sot_root, research_root).run(
        manifest, apply=False, approved=False,
    )
    assert report.status == "rejected"
    assert report.activated_count == 0
    bad_item = next(item for item in report.items if item.ref == bad.name)
    assert bad_item.reason_code == "claim_masquerades_as_approved"
    good_item = next(item for item in report.items if item.ref == good.name)
    assert good_item.ok


async def test_defective_classification_downgrade_rejects(tmp_path: Path) -> None:
    sot_root, research_root = _roots(tmp_path)
    curator = uuid.uuid4()
    bad = build_package(
        sot_root,
        curator_id=curator,
        owner_id=curator,
        source_key="rtr.downgrade",
        record_key="DOWN.001",
        classification="internal",
        source_classification="restricted",
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "downgrade",
        "curator_subject_id": str(curator),
        "sot_items": [{"staging_name": bad.name}],
    })
    report = await _tool(sot_root, research_root).run(
        manifest, apply=False, approved=False,
    )
    assert report.status == "rejected"
    assert report.items[0].reason_code == "classification_downgrade"


async def test_curator_mismatch_is_rejected_before_any_gate(tmp_path: Path) -> None:
    sot_root, research_root = _roots(tmp_path)
    signer = uuid.uuid4()
    package_root = build_package(
        sot_root,
        curator_id=signer,
        owner_id=signer,
        source_key="rtr.mismatch",
        record_key="MISMATCH.001",
    )
    # Manifest names a DIFFERENT curator than the one who signed the attestation.
    manifest = BatchManifest.model_validate({
        "batch_id": "mismatch",
        "curator_subject_id": str(uuid.uuid4()),
        "sot_items": [{"staging_name": package_root.name}],
    })
    report = await _tool(sot_root, research_root).run(
        manifest, apply=False, approved=False,
    )
    assert report.status == "rejected"
    assert report.items[0].reason_code == "attestation_curator_mismatch"


async def test_apply_without_approval_refuses(tmp_path: Path) -> None:
    sot_root, research_root = _roots(tmp_path)
    curator = uuid.uuid4()
    package_root = build_package(
        sot_root,
        curator_id=curator,
        owner_id=curator,
        source_key="rtr.noapprove",
        record_key="NOAPPROVE.001",
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "noapprove",
        "curator_subject_id": str(curator),
        "sot_items": [{"staging_name": package_root.name}],
    })
    report = await _tool(sot_root, research_root).run(
        manifest, apply=True, approved=False,
    )
    assert report.status == "approval_required"
    assert report.activated_count == 0


async def test_malformed_research_rejects(tmp_path: Path) -> None:
    sot_root, research_root = _roots(tmp_path)
    curator = uuid.uuid4()
    # A research staging name that does not exist -> package_missing, fail-closed.
    manifest = BatchManifest.model_validate({
        "batch_id": "badresearch",
        "curator_subject_id": str(curator),
        "research_items": [
            {"staging_name": "research-missing", "source_key": "refinery.x"},
        ],
    })
    report = await _tool(sot_root, research_root).run(
        manifest, apply=False, approved=False,
    )
    assert report.status == "rejected"
    assert report.items[0].reason_code == "package_missing"
