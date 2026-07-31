import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rtr_copilot.sot.models import (
    PackageEvidence,
    PackageManifest,
    PackageRecord,
    PublishAttestation,
)
from rtr_copilot.sot.package import (
    POLICY_VERSION,
    VALIDATOR_VERSION,
    canonical_json,
    evidence_content_sha,
    manifest_identity_sha,
    record_content_sha,
    sha256_bytes,
    sign_attestation,
)

SECRET = "test-only-dedicated-sot-signing-secret-32bytes"
NOW = datetime(2026, 7, 31, 1, 0, tzinfo=UTC)


def build_package(
    root: Path,
    *,
    curator_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    package_id: uuid.UUID | None = None,
    source_key: str = "rtr.specs",
    revision: int = 1,
    record_key: str = "L3F.ENT.002",
    ordinal: int = 1,
    supersedes: bool = False,
    classification: str = "internal",
    acl_effect: str = "allow",
    text: str = "Approved internal capability statement.",
    additional_records: list[tuple[str, str]] | None = None,
) -> Path:
    curator_id = curator_id or uuid.uuid4()
    owner_id = owner_id or curator_id
    package_id = package_id or uuid.uuid4()
    package_root = root / f"package-{package_id}"
    package_root.mkdir(parents=True)
    source_ref = "specs/company.yaml"
    evidence_data: dict[str, Any] = {
        "evidence_key": f"{record_key}.e1",
        "record_key": record_key,
        "source_ref": source_ref,
        "source_document_id": None,
        "source_version_id": None,
        "source_blob_sha256": "a" * 64,
        "locator": {"paragraph": 2},
        "quoted_text": text,
        "normalized_text": text,
        "evidence_sha256": "0" * 64,
        "source_label": "Company specification",
        "classification": classification,
    }
    evidence = PackageEvidence.model_validate(evidence_data)
    evidence_data["evidence_sha256"] = evidence_content_sha(evidence)
    record_data: dict[str, Any] = {
        "record_key": record_key,
        "version_ordinal": ordinal,
        "owner_id": str(owner_id),
        "classification": classification,
        "department_id": None,
        "project_id": None,
        "value": {"capability": text},
        "searchable_text": text,
        "provenance_level": "approved_internal",
        "confidence": 0.95,
        "verification_state": "approved",
        "fact_state": "approved",
        "effective_from": NOW.isoformat(),
        "effective_to": None,
        "freshness_policy": {"maximum_age_days": 365},
        "freshness_due_at": (NOW + timedelta(days=365)).isoformat(),
        "evidence_keys": [evidence_data["evidence_key"]],
        "source_refs": [source_ref],
        "content_sha256": "0" * 64,
        "supersedes_record_key": record_key if supersedes else None,
        "acl": [{
            "principal_type": "user",
            "principal_id": str(owner_id),
            "action": "view",
            "effect": acl_effect,
        }],
    }
    record = PackageRecord.model_validate(record_data)
    record_data["content_sha256"] = record_content_sha(record)
    record_rows = [record_data]
    evidence_rows = [evidence_data]
    for extra_key, extra_text in additional_records or []:
        extra_evidence_data = {
            **evidence_data,
            "evidence_key": f"{extra_key}.e1",
            "record_key": extra_key,
            "quoted_text": extra_text,
            "normalized_text": extra_text,
            "evidence_sha256": "0" * 64,
        }
        extra_evidence = PackageEvidence.model_validate(extra_evidence_data)
        extra_evidence_data["evidence_sha256"] = evidence_content_sha(
            extra_evidence,
        )
        extra_record_data = {
            **record_data,
            "record_key": extra_key,
            "version_ordinal": ordinal,
            "value": {"capability": extra_text},
            "searchable_text": extra_text,
            "evidence_keys": [extra_evidence_data["evidence_key"]],
            "content_sha256": "0" * 64,
            "supersedes_record_key": None,
        }
        extra_record = PackageRecord.model_validate(extra_record_data)
        extra_record_data["content_sha256"] = record_content_sha(extra_record)
        record_rows.append(extra_record_data)
        evidence_rows.append(extra_evidence_data)
    files = {
        "records.jsonl": b"".join(
            canonical_json(item) + b"\n" for item in record_rows
        ),
        "evidence.jsonl": b"".join(
            canonical_json(item) + b"\n" for item in evidence_rows
        ),
        "source_hashes.json": canonical_json({
            source_ref: {"sha256": "a" * 64, "classification": classification},
        }),
    }
    for name, content in files.items():
        (package_root / name).write_bytes(content)
    payload_sha = sha256_bytes(canonical_json([
        {"path": name, "sha256": sha256_bytes(content)}
        for name, content in sorted(files.items())
    ]))
    attestation: dict[str, Any] = {
        "package_id": str(package_id),
        "revision": revision,
        "manifest_sha256": "0" * 64,
        "payload_sha256": payload_sha,
        "validator_version": VALIDATOR_VERSION,
        "schema_version": "1.0",
        "policy_version": POLICY_VERSION,
        "validated_at": NOW.isoformat(),
        "curator_subject_id": str(curator_id),
        "decision": "approved",
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "signature": "0" * 64,
    }
    (package_root / "publish_attestation.json").write_bytes(canonical_json(attestation))
    members = [
        {
            "path": name,
            "byte_size": path.stat().st_size,
            "sha256": sha256_bytes(path.read_bytes()),
        }
        for name in sorted((*files, "publish_attestation.json"))
        if (path := package_root / name)
    ]
    manifest_data = {
        "schema_version": "1.0",
        "package_id": str(package_id),
        "source_key": source_key,
        "revision": revision,
        "trust_zone": "sot",
        "producer": "test-fixture",
        "generated_at": NOW.isoformat(),
        "payload_sha256": payload_sha,
        "members": members,
    }
    manifest = PackageManifest.model_validate(manifest_data)
    attestation["manifest_sha256"] = manifest_identity_sha(manifest)
    attestation["signature"] = sign_attestation(
        PublishAttestation.model_validate(attestation).model_dump(mode="json"),
        SECRET,
    )
    attestation_bytes = canonical_json(attestation)
    (package_root / "publish_attestation.json").write_bytes(attestation_bytes)
    for member in members:
        if member["path"] == "publish_attestation.json":
            member["byte_size"] = len(attestation_bytes)
            member["sha256"] = sha256_bytes(attestation_bytes)
    (package_root / "manifest.json").write_bytes(canonical_json(manifest_data))
    return package_root
