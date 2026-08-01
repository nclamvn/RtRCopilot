"""Refinery package contract for the research trust zone (TIP-010 Task 3).

Mirrors the TIP-006 SOT adapter discipline (rooted parser, checksum-verified
members, typed fail-closed errors) and reuses the TIP-005 quarantine
primitives for archive safety. ANY contract violation rejects the entire
package; there is no partial acceptance path.

Two validation stages exist on purpose:

- ``stage()`` verifies package identity (paths, member set, member checksums,
  payload checksum, declared fingerprint). A package that fails here never
  reaches the registry because its declared identity cannot be trusted.
- ``StagedResearchPackage.load_records()`` verifies the per-record contract
  (tier, verbatim evidence spans with checksums, content checksums). A
  package that fails here is registered and persisted as ``rejected``.
"""

import hashlib
import json
import stat
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import Field, ValidationError

from rtr_copilot.governance.models import ResearchTier, StrictModel
from rtr_copilot.ingestion.errors import IngestionFailure
from rtr_copilot.ingestion.validators import _validate_entry_name
from rtr_copilot.sot.package import canonical_json, sha256_bytes

RESEARCH_ADAPTER_VERSION = "research-adapter/1.0"
REQUIRED_MEMBERS = frozenset({"records.jsonl"})
CAPTURE_FUTURE_TOLERANCE = timedelta(minutes=5)
VALID_TIERS = frozenset({"P", "S", "H", "X"})
ZIP_MAGIC = b"PK\x03\x04"


class ResearchPackageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ResearchManifestMember(StrictModel):
    path: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResearchManifest(StrictModel):
    """Snapshot manifest: capture time, scope and adapter version are mandatory."""

    schema_version: str = Field(min_length=1, max_length=16)
    source_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    scope: str = Field(min_length=1, max_length=512)
    adapter_version: str = Field(pattern=r"^[a-z0-9._-]{1,64}$")
    record_count: int = Field(ge=0)
    members: list[ResearchManifestMember] = Field(min_length=1, max_length=16)


class RefineryEvidence(StrictModel):
    source_url: str = Field(min_length=1, max_length=2048)
    locator: dict[str, Any]
    quoted_text: str = Field(min_length=1, max_length=200_000)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class RefineryRecord(StrictModel):
    record_key: str = Field(min_length=1, max_length=256)
    version_ordinal: int = Field(gt=0)
    tier: ResearchTier
    content: dict[str, Any]
    searchable_text: str = Field(min_length=1, max_length=200_000)
    evidence: list[RefineryEvidence] = Field(min_length=1, max_length=1000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def evidence_checksum(quoted_text: str) -> str:
    """Checksum over the verbatim quote; any drift breaks the evidence chain."""
    return hashlib.sha256(quoted_text.encode()).hexdigest()


def research_record_sha(record: RefineryRecord) -> str:
    return sha256_bytes(canonical_json({
        "record_key": record.record_key,
        "version_ordinal": record.version_ordinal,
        "tier": record.tier,
        "content": record.content,
        "searchable_text": record.searchable_text,
        "evidence": [
            {
                "source_url": span.source_url,
                "locator": span.locator,
                "quoted_text": span.quoted_text,
                "checksum": span.checksum,
            }
            for span in record.evidence
        ],
    }))


def research_payload_sha(members: list[ResearchManifestMember]) -> str:
    return sha256_bytes(canonical_json([
        {"path": member.path, "sha256": member.sha256}
        for member in sorted(members, key=lambda item: item.path)
    ]))


def research_fingerprint(
    *,
    source_key: str,
    scope: str,
    captured_at: datetime,
    adapter_version: str,
    payload_sha256: str,
) -> str:
    """Content-bound package identity: recomputable from manifest facts alone."""
    return sha256_bytes(canonical_json({
        "source_key": source_key,
        "scope": scope,
        "captured_at": captured_at.isoformat(),
        "adapter_version": adapter_version,
        "payload_sha256": payload_sha256,
    }))


class StagedResearchPackage(StrictModel):
    """Identity-verified package whose record payload is still unvalidated."""

    staging_name: str
    manifest: ResearchManifest
    members: dict[str, bytes]

    def load_records(
        self,
        *,
        max_lines: int = 100_000,
        max_line_bytes: int = 1_000_000,
    ) -> list[RefineryRecord]:
        records: list[RefineryRecord] = []
        seen_keys: set[str] = set()
        for line_number, line in enumerate(
            self.members["records.jsonl"].splitlines(), 1,
        ):
            if line_number > max_lines:
                raise ResearchPackageError("line_count_exceeded")
            if len(line) > max_line_bytes:
                raise ResearchPackageError("line_oversized")
            if not line.strip():
                continue
            records.append(_parse_record_line(line))
            if records[-1].record_key in seen_keys:
                raise ResearchPackageError("duplicate_record_key")
            seen_keys.add(records[-1].record_key)
        if not records:
            raise ResearchPackageError("record_set_empty")
        if len(records) != self.manifest.record_count:
            raise ResearchPackageError("record_count_mismatch")
        return records


def _parse_record_line(line: bytes) -> RefineryRecord:
    try:
        raw = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        raise ResearchPackageError("record_schema_invalid") from None
    if not isinstance(raw, dict):
        raise ResearchPackageError("record_schema_invalid")
    zone_label = raw.pop("zone_label", "research")
    if zone_label != "research":
        raise ResearchPackageError("zone_label_forged")
    if "tier" not in raw:
        raise ResearchPackageError("record_tier_missing")
    if raw["tier"] not in VALID_TIERS:
        raise ResearchPackageError("record_tier_invalid")
    evidence = raw.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ResearchPackageError("record_evidence_missing")
    try:
        record = RefineryRecord.model_validate(raw)
    except ValidationError:
        raise ResearchPackageError("record_schema_invalid") from None
    for span in record.evidence:
        if span.checksum != evidence_checksum(span.quoted_text):
            raise ResearchPackageError("evidence_checksum_mismatch")
    if record.content_sha256 != research_record_sha(record):
        raise ResearchPackageError("record_checksum_mismatch")
    return record


class ResearchPackageParser:
    """Rooted, traversal-safe reader for staged Refinery packages.

    Accepts either a flat staging directory or a ``.zip`` archive inside the
    research staging root; archive entries pass the TIP-005 quarantine rules
    (safe names, no symlinks, no encryption, entry/expansion/ratio budgets)
    before a single byte of package content is interpreted.
    """

    def __init__(
        self,
        staging_root: Path,
        *,
        max_member_bytes: int = 20_000_000,
        max_package_bytes: int = 100_000_000,
        max_archive_entries: int = 64,
        max_compression_ratio: int = 100,
    ) -> None:
        self.root = staging_root.resolve()
        self.max_member_bytes = max_member_bytes
        self.max_package_bytes = max_package_bytes
        self.max_archive_entries = max_archive_entries
        self.max_compression_ratio = max_compression_ratio

    def stage(self, staging_name: str, *, now: datetime) -> StagedResearchPackage:
        pure = PurePosixPath(staging_name)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise ResearchPackageError("package_path_unsafe")
        path = self.root / staging_name
        if path.is_symlink():
            raise ResearchPackageError("package_path_unsafe")
        resolved = path.resolve()
        if self.root not in resolved.parents:
            raise ResearchPackageError("package_path_unsafe")
        if resolved.is_file():
            files = self._read_archive(resolved)
        elif resolved.is_dir():
            files = self._read_directory(resolved)
        else:
            raise ResearchPackageError("package_missing")
        manifest = self._verify_manifest(files, now=now)
        return StagedResearchPackage(
            staging_name=staging_name,
            manifest=manifest,
            members={
                name: content
                for name, content in files.items()
                if name != "manifest.json"
            },
        )

    def _read_directory(self, package_root: Path) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        total = 0
        for entry in sorted(package_root.iterdir()):
            if entry.is_symlink():
                raise ResearchPackageError("member_symlink_forbidden")
            if not entry.is_file():
                raise ResearchPackageError("unlisted_package_member")
            size = entry.stat().st_size
            if size > self.max_member_bytes:
                raise ResearchPackageError("member_oversized")
            total += size
            if total > self.max_package_bytes:
                raise ResearchPackageError("package_oversized")
            files[entry.name] = entry.read_bytes()
        return files

    def _read_archive(self, archive_path: Path) -> dict[str, bytes]:
        if archive_path.suffix.lower() != ".zip":
            raise ResearchPackageError("malformed_archive")
        with archive_path.open("rb") as stream:
            if stream.read(4) != ZIP_MAGIC:
                raise ResearchPackageError("malformed_archive")
        if archive_path.stat().st_size > self.max_package_bytes:
            raise ResearchPackageError("package_oversized")
        files: dict[str, bytes] = {}
        expanded = 0
        try:
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if len(entries) > self.max_archive_entries:
                    raise ResearchPackageError("archive_budget_exceeded")
                for entry in entries:
                    try:
                        canonical = _validate_entry_name(entry.filename)
                    except IngestionFailure:
                        raise ResearchPackageError("archive_path_unsafe") from None
                    if canonical in files:
                        raise ResearchPackageError("archive_path_unsafe")
                    if stat.S_ISLNK(entry.external_attr >> 16):
                        raise ResearchPackageError("archive_path_unsafe")
                    if entry.flag_bits & 0x1:
                        raise ResearchPackageError("archive_entry_unsupported")
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    expanded += entry.file_size
                    if (
                        entry.file_size > self.max_member_bytes
                        or expanded > self.max_package_bytes
                        or ratio > self.max_compression_ratio
                    ):
                        raise ResearchPackageError("archive_budget_exceeded")
                    files[entry.filename] = archive.read(entry)
        except (OSError, zipfile.BadZipFile):
            raise ResearchPackageError("malformed_archive") from None
        return files

    def _verify_manifest(
        self,
        files: dict[str, bytes],
        *,
        now: datetime,
    ) -> ResearchManifest:
        manifest_bytes = files.get("manifest.json")
        if manifest_bytes is None:
            raise ResearchPackageError("manifest_missing")
        try:
            manifest = ResearchManifest.model_validate_json(manifest_bytes)
        except ValidationError:
            raise ResearchPackageError("manifest_schema_invalid") from None
        if manifest.schema_version.split(".", 1)[0] != "1":
            raise ResearchPackageError("schema_major_unsupported")
        if manifest.captured_at > now + CAPTURE_FUTURE_TOLERANCE:
            raise ResearchPackageError("captured_at_in_future")
        names = [member.path for member in manifest.members]
        if len(names) != len(set(names)):
            raise ResearchPackageError("duplicate_member")
        if set(names) != set(REQUIRED_MEMBERS):
            raise ResearchPackageError("manifest_member_set_invalid")
        if not {"manifest.json", *names} <= set(files):
            raise ResearchPackageError("member_missing")
        if set(files) != {"manifest.json", *names}:
            raise ResearchPackageError("unlisted_package_member")
        total = len(manifest_bytes)
        for member in manifest.members:
            payload = files[member.path]
            total += len(payload)
            if len(payload) > self.max_member_bytes:
                raise ResearchPackageError("member_oversized")
            if member.byte_size != len(payload) or member.sha256 != sha256_bytes(payload):
                raise ResearchPackageError("member_checksum_mismatch")
        if total > self.max_package_bytes:
            raise ResearchPackageError("package_oversized")
        if manifest.payload_sha256 != research_payload_sha(manifest.members):
            raise ResearchPackageError("payload_checksum_mismatch")
        expected = research_fingerprint(
            source_key=manifest.source_key,
            scope=manifest.scope,
            captured_at=manifest.captured_at,
            adapter_version=manifest.adapter_version,
            payload_sha256=manifest.payload_sha256,
        )
        if manifest.fingerprint != expected:
            raise ResearchPackageError("fingerprint_mismatch")
        return manifest
