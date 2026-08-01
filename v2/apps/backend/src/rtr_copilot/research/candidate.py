"""Build the draft candidate claim package an approved graduation submits.

The output is a normal TIP-006 staging package: it enters the publish gate as
``provenance_level='claim'`` / ``fact_state='claim'`` and lives or dies by the
existing validation, attestation and activation checks — graduation adds no
bypass (AC-09). Full lineage back to the research evidence rides in the record
value payload, the source fingerprints and the verbatim evidence spans.
"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rtr_copilot.governance.models import (
    GraduationProposal,
    ResearchPackage,
    ResearchRecord,
    ResearchSource,
)
from rtr_copilot.research.models import CandidateClaim
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

CLASSIFICATION_RANK = {
    "public_internal": 0,
    "internal": 1,
    "restricted": 2,
    "highly_restricted": 3,
}
RANK_CLASSIFICATION = {rank: name for name, rank in CLASSIFICATION_RANK.items()}

GraduationEvidence = tuple[ResearchRecord, ResearchPackage, ResearchSource]


def _evidence_classification(claim: CandidateClaim, source: ResearchSource) -> str:
    return RANK_CLASSIFICATION[max(
        CLASSIFICATION_RANK[claim.classification],
        CLASSIFICATION_RANK[source.classification],
    )]


def build_candidate_package(
    staging_root: Path,
    *,
    proposal: GraduationProposal,
    claim: CandidateClaim,
    evidence: list[GraduationEvidence],
    decider_id: uuid.UUID,
    signing_secret: str,
    now: datetime,
) -> str:
    """Write the candidate staging package and return its staging name."""
    staging_name = f"graduation-{proposal.proposal_id.hex}"
    package_root = staging_root / staging_name
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)
    package_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rtr-graduation:{proposal.proposal_id}",
    )
    owner_id = claim.owner_subject_id or proposal.proposer_subject_id
    packages = {package.package_id: package for _, package, _ in evidence}
    source_refs = sorted({
        f"research:{package.fingerprint}" for package in packages.values()
    })
    source_hashes = {
        f"research:{package.fingerprint}": {
            "sha256": package.fingerprint,
            "classification": source.classification,
        }
        for _, package, source in evidence
    }
    evidence_rows: list[dict[str, Any]] = []
    evidence_checksums: list[str] = []
    for record_index, (record, package, source) in enumerate(evidence, 1):
        for span_index, span in enumerate(record.evidence_spans, 1):
            evidence_checksums.append(span.checksum)
            row: dict[str, Any] = {
                "evidence_key": (
                    f"{proposal.target_record_key}.r{record_index}.e{span_index}"
                ),
                "record_key": proposal.target_record_key,
                "source_ref": f"research:{package.fingerprint}",
                "source_document_id": None,
                "source_version_id": None,
                "source_blob_sha256": package.fingerprint,
                "locator": {
                    "region": f"{span.source_url}#{json.dumps(span.locator, sort_keys=True)}",
                },
                "quoted_text": span.quoted_text,
                "normalized_text": span.quoted_text,
                "evidence_sha256": "0" * 64,
                "source_label": f"Research {source.stable_key} ({record.record_key})",
                "classification": _evidence_classification(claim, source),
            }
            row["evidence_sha256"] = evidence_content_sha(
                PackageEvidence.model_validate(row),
            )
            evidence_rows.append(row)
    lineage = {
        "proposal_id": str(proposal.proposal_id),
        "research_record_ids": [
            str(record.research_record_id) for record, _, _ in evidence
        ],
        "packages": [
            {
                "fingerprint": package.fingerprint,
                "payload_sha256": package.payload_sha256,
                "captured_at": package.captured_at.isoformat(),
                "scope": package.snapshot_scope,
                "adapter_version": package.adapter_version,
            }
            for package in packages.values()
        ],
        "evidence_checksums": evidence_checksums,
    }
    record_row: dict[str, Any] = {
        "record_key": proposal.target_record_key,
        "version_ordinal": claim.version_ordinal,
        "owner_id": str(owner_id),
        "classification": claim.classification,
        "department_id": None,
        "project_id": None,
        "value": {
            "claim_text": claim.claim_text,
            "value": claim.value,
            "lineage": lineage,
        },
        "searchable_text": claim.claim_text,
        "provenance_level": "claim",
        "confidence": claim.confidence,
        "verification_state": "claim",
        "fact_state": "claim",
        "effective_from": now.isoformat(),
        "effective_to": None,
        "freshness_policy": {},
        "freshness_due_at": None,
        "evidence_keys": [row["evidence_key"] for row in evidence_rows],
        "source_refs": source_refs,
        "content_sha256": "0" * 64,
        "supersedes_record_key": None,
        "acl": [{
            "principal_type": "user",
            "principal_id": str(owner_id),
            "action": "view",
            "effect": "allow",
        }],
    }
    record_row["content_sha256"] = record_content_sha(
        PackageRecord.model_validate(record_row),
    )
    files = {
        "records.jsonl": canonical_json(record_row) + b"\n",
        "evidence.jsonl": b"".join(
            canonical_json(row) + b"\n" for row in evidence_rows
        ),
        "source_hashes.json": canonical_json(source_hashes),
    }
    for name, content in files.items():
        (package_root / name).write_bytes(content)
    payload_sha = sha256_bytes(canonical_json([
        {"path": name, "sha256": sha256_bytes(content)}
        for name, content in sorted(files.items())
    ]))
    attestation: dict[str, Any] = {
        "package_id": str(package_id),
        "revision": 1,
        "manifest_sha256": "0" * 64,
        "payload_sha256": payload_sha,
        "validator_version": VALIDATOR_VERSION,
        "schema_version": "1.0",
        "policy_version": POLICY_VERSION,
        "validated_at": now.isoformat(),
        "curator_subject_id": str(decider_id),
        "decision": "approved",
        "expires_at": None,
        "signature": "0" * 64,
    }
    attestation_path = package_root / "publish_attestation.json"
    attestation_path.write_bytes(canonical_json(attestation))
    members = [
        {
            "path": name,
            "byte_size": (package_root / name).stat().st_size,
            "sha256": sha256_bytes((package_root / name).read_bytes()),
        }
        for name in sorted((*files, "publish_attestation.json"))
    ]
    manifest_data = {
        "schema_version": "1.0",
        "package_id": str(package_id),
        "source_key": f"graduation.{proposal.proposal_id.hex}",
        "revision": 1,
        "trust_zone": "sot",
        "producer": "rtr-graduation-gate",
        "generated_at": now.isoformat(),
        "payload_sha256": payload_sha,
        "members": members,
    }
    manifest = PackageManifest.model_validate(manifest_data)
    attestation["manifest_sha256"] = manifest_identity_sha(manifest)
    attestation["signature"] = sign_attestation(
        PublishAttestation.model_validate(attestation).model_dump(mode="json"),
        signing_secret,
    )
    attestation_bytes = canonical_json(attestation)
    attestation_path.write_bytes(attestation_bytes)
    for member in members:
        if member["path"] == "publish_attestation.json":
            member["byte_size"] = len(attestation_bytes)
            member["sha256"] = sha256_bytes(attestation_bytes)
    (package_root / "manifest.json").write_bytes(canonical_json(manifest_data))
    return staging_name
