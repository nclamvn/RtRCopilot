import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sot_fixtures import NOW, SECRET, build_package

from rtr_copilot.sot.kernel_guard import probe_kernel_read_only
from rtr_copilot.sot.models import ParsedPackage
from rtr_copilot.sot.package import (
    PackageError,
    PackageParser,
    freshness_state,
    sign_attestation,
    validate_package,
    verify_attestation,
)


def test_package_is_deterministic_valid_and_attested(tmp_path: Path) -> None:
    package_root = build_package(tmp_path)
    parsed = PackageParser(tmp_path).parse(package_root.name)
    first = validate_package(parsed, now=NOW)
    second = validate_package(parsed, now=NOW)
    assert first.valid
    assert first.deterministic_checksum == second.deterministic_checksum
    verify_attestation(
        parsed,
        secret=SECRET,
        curator_id=str(parsed.attestation.curator_subject_id),
        now=NOW,
    )
    assert freshness_state(parsed.records[0], NOW) == "current"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("extra", "unlisted_package_member"),
        ("checksum", "member_checksum_mismatch"),
        ("symlink", "member_symlink_forbidden"),
    ],
)
def test_package_boundary_rejects_unsafe_members(
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    package_root = build_package(tmp_path)
    if mutation == "extra":
        (package_root / "extra.txt").write_text("unexpected")
    elif mutation == "checksum":
        (package_root / "records.jsonl").write_text("{}\n")
    else:
        target = package_root / "source_hashes.json"
        target.unlink()
        target.symlink_to("/etc/hosts")
    with pytest.raises(PackageError, match=code):
        PackageParser(tmp_path).parse(package_root.name)


def test_validator_rejects_claim_masquerade_without_mutating_files(
    tmp_path: Path,
) -> None:
    package_root = build_package(tmp_path)
    parsed = PackageParser(tmp_path).parse(package_root.name)
    record = parsed.records[0].model_copy(
        update={"provenance_level": "claim", "verification_state": "approved"},
    )
    invalid = parsed.model_copy(update={"records": [record]})
    report = validate_package(invalid, now=NOW)
    assert "claim_masquerades_as_approved" in {
        item.code for item in report.findings
    }


def test_attestation_tamper_is_rejected(tmp_path: Path) -> None:
    package_root = build_package(tmp_path)
    parsed = PackageParser(tmp_path).parse(package_root.name)
    tampered = parsed.model_copy(update={
        "attestation": parsed.attestation.model_copy(
            update={"signature": "f" * 64},
        ),
    })
    with pytest.raises(PackageError, match="attestation_signature_invalid"):
        verify_attestation(
            tampered,
            secret=SECRET,
            curator_id=str(parsed.attestation.curator_subject_id),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda package: package.model_copy(update={
                "records": [package.records[0].model_copy(
                    update={"provenance_level": ""},
                )],
            }),
            "provenance_missing",
        ),
        (
            lambda package: package.model_copy(update={
                "records": [package.records[0], package.records[0]],
            }),
            "duplicate_record_key",
        ),
        (
            lambda package: package.model_copy(update={
                "records": [package.records[0].model_copy(update={"acl": []})],
            }),
            "acl_missing",
        ),
        (
            lambda package: package.model_copy(update={
                "evidence": [package.evidence[0].model_copy(
                    update={"locator": {}},
                )],
            }),
            "evidence_locator_invalid",
        ),
        (
            lambda package: package.model_copy(update={
                "records": [package.records[0].model_copy(
                    update={"fact_state": "conflict"},
                )],
            }),
            "fact_state_unpublishable",
        ),
        (
            lambda package: package.model_copy(update={
                "records": [package.records[0].model_copy(
                    update={"fact_state": "invented"},
                )],
            }),
            "fact_state_unsupported",
        ),
        (
            lambda package: package.model_copy(update={
                "records": [package.records[0].model_copy(
                    update={"verification_state": "invented"},
                )],
            }),
            "verification_state_unsupported",
        ),
        (
            lambda package: package.model_copy(update={
                "source_hashes": {
                    key: value.model_copy(update={"classification": "restricted"})
                    for key, value in package.source_hashes.items()
                },
            }),
            "classification_downgrade",
        ),
    ],
)
def test_validation_findings_are_stable(
    tmp_path: Path,
    mutation: Callable[[ParsedPackage], ParsedPackage],
    code: str,
) -> None:
    package_root = build_package(tmp_path)
    parsed = PackageParser(tmp_path).parse(package_root.name)
    invalid = mutation(parsed)
    report = validate_package(invalid, now=NOW)
    assert code in {item.code for item in report.findings}


@pytest.mark.parametrize("field", ["fact_state", "verification_state"])
def test_unknown_publish_state_is_rejected_by_typed_schema(
    tmp_path: Path,
    field: str,
) -> None:
    package_root = build_package(tmp_path)
    record = PackageParser(tmp_path).parse(package_root.name).records[0]
    payload = record.model_dump(mode="json")
    payload[field] = "invented"
    with pytest.raises(ValidationError):
        type(record).model_validate(payload)


def test_expired_attestation_and_all_freshness_states(tmp_path: Path) -> None:
    package_root = build_package(tmp_path)
    parsed = PackageParser(tmp_path).parse(package_root.name)
    with pytest.raises(PackageError, match="attestation_expired"):
        verify_attestation(
            parsed,
            secret=SECRET,
            curator_id=str(parsed.attestation.curator_subject_id),
            now=NOW + timedelta(days=2),
        )
    future = parsed.attestation.model_copy(
        update={"validated_at": NOW + timedelta(minutes=6)},
    )
    future = future.model_copy(update={
        "signature": sign_attestation(future.model_dump(mode="json"), SECRET),
    })
    with pytest.raises(PackageError, match="attestation_validated_in_future"):
        verify_attestation(
            parsed.model_copy(update={"attestation": future}),
            secret=SECRET,
            curator_id=str(future.curator_subject_id),
            now=NOW,
        )
    record = parsed.records[0]
    assert freshness_state(record, NOW + timedelta(days=366)) == "stale"
    assert freshness_state(
        record.model_copy(update={"freshness_due_at": None}),
        NOW,
    ) == "unknown"
    assert freshness_state(
        record.model_copy(update={"effective_to": NOW - timedelta(seconds=1)}),
        NOW,
    ) == "expired"


def test_kernel_guard_blocks_and_never_writes(tmp_path: Path) -> None:
    records = tmp_path / "registry" / "records.jsonl"
    records.parent.mkdir()
    records.write_text(json.dumps({"record_key": "L3F.ENT.002"}) + "\n")
    result = probe_kernel_read_only(
        tmp_path,
        "L3F.ENT.002",
        now=NOW + timedelta(days=30),
    )
    assert result["decision"] == "blocked"
    assert result["read_only"] is True
    assert "provenance_missing" in result["reason_codes"]
    assert result["before_fingerprint"] == result["after_fingerprint"]


def test_live_kernel_l3f_ent_002_is_blocked_read_only() -> None:
    root = Path("/Users/os/RtR/kernel")
    if not root.exists():
        pytest.skip("kernel checkout not present")
    result = probe_kernel_read_only(root, "L3F.ENT.002", now=NOW)
    assert result["decision"] == "blocked"
    assert result["read_only"] is True
