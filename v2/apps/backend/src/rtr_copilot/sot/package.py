import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from rtr_copilot.sot.models import (
    Finding,
    PackageEvidence,
    PackageManifest,
    PackageRecord,
    ParsedPackage,
    PublishAttestation,
    SourceFingerprint,
    ValidationReport,
)

VALIDATOR_VERSION = "sot-validator/1.0"
POLICY_VERSION = "sot-policy/1.0"
REQUIRED_MEMBERS = {
    "records.jsonl",
    "source_hashes.json",
    "publish_attestation.json",
}
OPTIONAL_MEMBERS = {"evidence.jsonl"}
ALLOWED_PROVENANCE = {
    "verified_primary",
    "verified_secondary",
    "approved_internal",
    "claim",
}
CLASSIFICATION_RANK = {
    "public_internal": 0,
    "internal": 1,
    "restricted": 2,
    "highly_restricted": 3,
}
LOCATOR_KEYS = {
    "page",
    "sheet",
    "cell",
    "slide",
    "shape",
    "paragraph",
    "table",
    "region",
    "bounding_box",
    "timecode_start",
    "timecode_end",
}
ATTESTATION_FUTURE_TOLERANCE = timedelta(minutes=5)
ALLOWED_FACT_STATES = {"approved", "verified", "claim"}
ALLOWED_VERIFICATION_STATES = {"verified", "approved", "claim"}


class PackageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def manifest_identity_sha(manifest: PackageManifest | dict[str, Any]) -> str:
    """Hash the manifest while breaking the attestation-signature hash cycle."""
    value = (
        manifest.model_dump(mode="json")
        if isinstance(manifest, PackageManifest)
        else json.loads(json.dumps(manifest))
    )
    for member in value["members"]:
        if member["path"] == "publish_attestation.json":
            member["sha256"] = "0" * 64
    return sha256_bytes(canonical_json(value))


def record_content_sha(record: PackageRecord) -> str:
    return sha256_bytes(canonical_json({
        "record_key": record.record_key,
        "version_ordinal": record.version_ordinal,
        "owner_id": record.owner_id,
        "classification": record.classification,
        "department_id": record.department_id,
        "project_id": record.project_id,
        "value": record.value,
        "searchable_text": record.searchable_text,
        "provenance_level": record.provenance_level,
        "confidence": record.confidence,
        "verification_state": record.verification_state,
        "fact_state": record.fact_state,
        "effective_from": record.effective_from,
        "effective_to": record.effective_to,
        "freshness_policy": record.freshness_policy,
        "freshness_due_at": record.freshness_due_at,
        "source_refs": sorted(record.source_refs),
        "evidence_keys": sorted(record.evidence_keys),
        "supersedes_record_key": record.supersedes_record_key,
        "acl": sorted(
            (
                item.model_dump(mode="json")
                for item in record.acl
            ),
            key=lambda item: canonical_json(item),
        ),
    }))


def evidence_content_sha(evidence: PackageEvidence) -> str:
    return sha256_bytes(canonical_json({
        "evidence_key": evidence.evidence_key,
        "record_key": evidence.record_key,
        "source_ref": evidence.source_ref,
        "source_document_id": evidence.source_document_id,
        "source_version_id": evidence.source_version_id,
        "source_blob_sha256": evidence.source_blob_sha256,
        "locator": evidence.locator,
        "quoted_text": evidence.quoted_text,
        "normalized_text": evidence.normalized_text,
        "source_label": evidence.source_label,
        "classification": evidence.classification,
    }))


def attestation_payload(attestation: PublishAttestation | dict[str, Any]) -> bytes:
    value = (
        attestation.model_dump(mode="json")
        if isinstance(attestation, PublishAttestation)
        else dict(attestation)
    )
    value.pop("signature", None)
    return canonical_json(value)


def sign_attestation(value: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), attestation_payload(value), hashlib.sha256).hexdigest()


def verify_attestation(
    package: ParsedPackage,
    *,
    secret: str,
    curator_id: str,
    now: datetime,
) -> None:
    attestation = package.attestation
    expected = sign_attestation(attestation.model_dump(mode="json"), secret)
    if not hmac.compare_digest(expected, attestation.signature):
        raise PackageError("attestation_signature_invalid")
    checks = {
        "attestation_package_mismatch": attestation.package_id != package.manifest.package_id,
        "attestation_revision_mismatch": attestation.revision != package.manifest.revision,
        "attestation_manifest_mismatch": (
            attestation.manifest_sha256 != package.manifest_sha256
        ),
        "attestation_payload_mismatch": (
            attestation.payload_sha256 != package.manifest.payload_sha256
        ),
        "attestation_validator_mismatch": (
            attestation.validator_version != VALIDATOR_VERSION
        ),
        "attestation_schema_mismatch": (
            attestation.schema_version != package.manifest.schema_version
        ),
        "attestation_policy_mismatch": attestation.policy_version != POLICY_VERSION,
        "attestation_curator_mismatch": str(attestation.curator_subject_id) != curator_id,
        "attestation_validated_in_future": (
            attestation.validated_at > now + ATTESTATION_FUTURE_TOLERANCE
        ),
        "attestation_expired": bool(
            attestation.expires_at and attestation.expires_at <= now
        ),
    }
    for code, failed in checks.items():
        if failed:
            raise PackageError(code)


class PackageParser:
    def __init__(
        self,
        staging_root: Path,
        *,
        max_member_bytes: int = 20_000_000,
        max_package_bytes: int = 100_000_000,
        max_lines: int = 100_000,
        max_line_bytes: int = 1_000_000,
    ) -> None:
        self.root = staging_root.resolve()
        self.max_member_bytes = max_member_bytes
        self.max_package_bytes = max_package_bytes
        self.max_lines = max_lines
        self.max_line_bytes = max_line_bytes

    def _safe_file(self, package_root: Path, member: str) -> Path:
        pure = PurePosixPath(member)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise PackageError("member_path_unsafe")
        path = package_root / member
        if path.is_symlink():
            raise PackageError("member_symlink_forbidden")
        resolved = path.resolve()
        if package_root not in resolved.parents or not resolved.is_file():
            raise PackageError("member_missing")
        if resolved.stat().st_size > self.max_member_bytes:
            raise PackageError("member_oversized")
        return resolved

    def _json_lines(self, path: Path, model: type[Any]) -> list[Any]:
        result: list[Any] = []
        with path.open("rb") as stream:
            for line_number, line in enumerate(stream, 1):
                if line_number > self.max_lines:
                    raise PackageError("line_count_exceeded")
                if len(line) > self.max_line_bytes:
                    raise PackageError("line_oversized")
                if not line.strip():
                    continue
                try:
                    result.append(model.model_validate_json(line))
                except (ValidationError, ValueError):
                    raise PackageError("member_schema_invalid") from None
        return result

    def parse(self, staging_name: str) -> ParsedPackage:
        pure = PurePosixPath(staging_name)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise PackageError("package_path_unsafe")
        package_root = (self.root / staging_name).resolve()
        if self.root not in package_root.parents or package_root.is_symlink():
            raise PackageError("package_path_unsafe")
        manifest_path = self._safe_file(package_root, "manifest.json")
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = PackageManifest.model_validate_json(manifest_bytes)
        except ValidationError:
            raise PackageError("manifest_schema_invalid") from None
        if manifest.schema_version.split(".", 1)[0] != "1":
            raise PackageError("schema_major_unsupported")
        names = [member.path for member in manifest.members]
        if len(names) != len(set(names)):
            raise PackageError("duplicate_member")
        if not REQUIRED_MEMBERS.issubset(names) or (
            set(names) - REQUIRED_MEMBERS - OPTIONAL_MEMBERS
        ):
            raise PackageError("manifest_member_set_invalid")
        actual_names = {path.name for path in package_root.iterdir()}
        if actual_names != {"manifest.json", *names}:
            raise PackageError("unlisted_package_member")
        total = len(manifest_bytes)
        paths: dict[str, Path] = {}
        for member in manifest.members:
            path = self._safe_file(package_root, member.path)
            payload = path.read_bytes()
            total += len(payload)
            if member.byte_size != len(payload) or member.sha256 != sha256_bytes(payload):
                raise PackageError("member_checksum_mismatch")
            paths[member.path] = path
        if total > self.max_package_bytes:
            raise PackageError("package_oversized")
        payload_sha = sha256_bytes(
            canonical_json([
                {"path": item.path, "sha256": item.sha256}
                for item in sorted(manifest.members, key=lambda item: item.path)
                if item.path != "publish_attestation.json"
            ]),
        )
        if manifest.payload_sha256 != payload_sha:
            raise PackageError("payload_checksum_mismatch")
        records = self._json_lines(paths["records.jsonl"], PackageRecord)
        evidence = (
            self._json_lines(paths["evidence.jsonl"], PackageEvidence)
            if "evidence.jsonl" in paths
            else []
        )
        try:
            raw_sources = json.loads(paths["source_hashes.json"].read_text())
            if not isinstance(raw_sources, dict):
                raise PackageError("member_schema_invalid")
            sources = {
                str(key): SourceFingerprint.model_validate(value)
                for key, value in raw_sources.items()
            }
            attestation = PublishAttestation.model_validate_json(
                paths["publish_attestation.json"].read_bytes(),
            )
        except (ValidationError, ValueError, json.JSONDecodeError):
            raise PackageError("member_schema_invalid") from None
        return ParsedPackage(
            root_name=staging_name,
            manifest=manifest,
            manifest_sha256=manifest_identity_sha(manifest),
            records=records,
            evidence=evidence,
            source_hashes=sources,
            attestation=attestation,
        )


def freshness_state(record: PackageRecord, now: datetime) -> str:
    if record.effective_to and record.effective_to <= now:
        return "expired"
    if record.freshness_due_at is None:
        return "unknown"
    return "stale" if record.freshness_due_at <= now else "current"


def validate_package(
    package: ParsedPackage,
    *,
    now: datetime,
    allow_claim_as_approved: bool = False,
    max_findings: int = 100,
) -> ValidationReport:
    findings: list[Finding] = []

    def add(code: str, subject: str) -> None:
        if len(findings) < max_findings:
            findings.append(Finding(code=code, subject=subject[:256]))

    record_keys: set[str] = set()
    evidence_keys: set[str] = set()
    evidence_by_key: dict[str, PackageEvidence] = {}
    for evidence in package.evidence:
        if evidence.evidence_key in evidence_keys:
            add("duplicate_evidence_key", evidence.evidence_key)
        evidence_keys.add(evidence.evidence_key)
        evidence_by_key[evidence.evidence_key] = evidence
        if evidence.source_ref not in package.source_hashes:
            add("source_fingerprint_missing", evidence.evidence_key)
        if not evidence.locator or not set(evidence.locator).issubset(LOCATOR_KEYS):
            add("evidence_locator_invalid", evidence.evidence_key)
        numeric_positions = {
            key: value
            for key, value in evidence.locator.items()
            if key in {"page", "slide", "paragraph", "table"}
        }
        if any(
            not isinstance(value, int) or value < 1
            for value in numeric_positions.values()
        ):
            add("evidence_locator_invalid", evidence.evidence_key)
        if (
            evidence.source_blob_sha256
            and evidence.source_ref in package.source_hashes
            and evidence.source_blob_sha256
            != package.source_hashes[evidence.source_ref].sha256
        ):
            add("source_fingerprint_mismatch", evidence.evidence_key)
        if evidence.evidence_sha256 != evidence_content_sha(evidence):
            add("evidence_checksum_invalid", evidence.evidence_key)
    intervals: dict[str, list[tuple[datetime, datetime | None]]] = {}
    for record in package.records:
        if record.record_key in record_keys:
            add("duplicate_record_key", record.record_key)
        record_keys.add(record.record_key)
        intervals.setdefault(record.record_key, []).append(
            (record.effective_from, record.effective_to),
        )
        if record.provenance_level not in ALLOWED_PROVENANCE:
            add("provenance_unknown", record.record_key)
        if not record.provenance_level:
            add("provenance_missing", record.record_key)
        if record.fact_state in {"flagged", "placeholder", "unspecified", "conflict"}:
            add("fact_state_unpublishable", record.record_key)
        elif record.fact_state not in ALLOWED_FACT_STATES:
            add("fact_state_unsupported", record.record_key)
        if record.verification_state not in ALLOWED_VERIFICATION_STATES:
            add("verification_state_unsupported", record.record_key)
        if (
            record.provenance_level == "claim"
            and record.verification_state in {"approved", "verified"}
            and not allow_claim_as_approved
        ):
            add("claim_masquerades_as_approved", record.record_key)
        if record.effective_to and record.effective_to <= record.effective_from:
            add("validity_interval_invalid", record.record_key)
        if not record.acl:
            add("acl_missing", record.record_key)
        if record.content_sha256 != record_content_sha(record):
            add("record_checksum_invalid", record.record_key)
        for source_ref in record.source_refs:
            source = package.source_hashes.get(source_ref)
            if source is None:
                add("source_fingerprint_missing", record.record_key)
            elif CLASSIFICATION_RANK[record.classification] < CLASSIFICATION_RANK[
                source.classification
            ]:
                add("classification_downgrade", record.record_key)
        for evidence_key in record.evidence_keys:
            linked_evidence = evidence_by_key.get(evidence_key)
            if linked_evidence is None or linked_evidence.record_key != record.record_key:
                add("evidence_unresolved", record.record_key)
                continue
            source = package.source_hashes.get(linked_evidence.source_ref)
            required_rank = CLASSIFICATION_RANK[record.classification]
            if source:
                required_rank = max(
                    required_rank,
                    CLASSIFICATION_RANK[source.classification],
                )
            if CLASSIFICATION_RANK[linked_evidence.classification] < required_rank:
                add("classification_downgrade", linked_evidence.evidence_key)
        if isinstance(record.value, dict) and any(
            any(token in str(key).lower() for token in ("password", "secret", "token"))
            for key in record.value
        ):
            add("dlp_sensitive_key", record.record_key)
        freshness_state(record, now)
    for key in evidence_keys:
        if evidence_by_key[key].record_key not in record_keys:
            add("evidence_record_unresolved", key)
    checksum = sha256_bytes(canonical_json({
        "manifest": package.manifest_sha256,
        "records": sorted(record.content_sha256 for record in package.records),
        "evidence": sorted(item.evidence_sha256 for item in package.evidence),
        "sources": {
            key: value.model_dump(mode="json")
            for key, value in sorted(package.source_hashes.items())
        },
        "validator": VALIDATOR_VERSION,
        "policy": POLICY_VERSION,
    }))
    return ValidationReport(
        valid=not findings,
        validator_version=VALIDATOR_VERSION,
        policy_version=POLICY_VERSION,
        findings=findings,
        record_count=len(package.records),
        evidence_count=len(package.evidence),
        source_count=len(package.source_hashes),
        deterministic_checksum=checksum,
    )


def fingerprint_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def signing_secret_from_env() -> str:
    return os.environ.get("SOT_SIGNING_SECRET", "")
