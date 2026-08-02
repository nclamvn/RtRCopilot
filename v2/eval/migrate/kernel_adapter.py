"""TIP-013 Phase B (D-013-05 kickoff) · kernel -> V2 SOT package adapter (DRY-RUN).

Reads a POINT-IN-TIME, READ-ONLY snapshot of the real RtR kernel fact registry
and converts each fact into a V2 SOT package record, so a migration DRESS
REHEARSAL can measure -- WITHOUT activating anything -- how many real facts
convert cleanly and would pass the existing publish gate, and exactly what
curation the rest still need.

Absolute discipline
-------------------
This module NEVER activates data, NEVER writes to a production database, and
NEVER exercises the publish ``--apply`` path.  It only *emits staged packages*
(the on-disk layout the onboarding tool consumes) and lets the caller run them
through the SAME pure, no-DB validators the tool uses in dry-run.  The real
kernel copy under ``kernel-real/`` is treated as a read-only input snapshot; the
adapter opens the YAML files for reading only and writes exclusively into the
caller-supplied output directory.

Honesty over completeness
-------------------------
Where a fact lacks something a *grounded* V2 package requires -- an honest
provenance mapping, a resolvable evidence span, a value, or a source -- the
adapter refuses to fabricate it and marks the fact ``needs_curation`` with the
precise missing field.  Every conservative mapping (see the module constants and
the docstrings below) pushes a doubtful fact toward ``needs_curation``, never
toward a falsely-"ready" claim.  The wire format is reused verbatim from
``rtr_copilot.sot`` (the same primitives ``tests/sot_fixtures.py`` builds on), so
an emitted package is checked by the REAL parser/validator, not a private copy.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

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

# --------------------------------------------------------------------------- #
# Conservative mapping tables (every assumption is documented for the Homeowner)
# --------------------------------------------------------------------------- #

#: kernel ``provenance_level`` -> (v2 provenance_level, verification_state,
#: fact_state).  Only these four kernel levels have an HONEST V2 equivalent.  A
#: kernel ``claim`` maps to a V2 ``claim`` record (never verified/approved) so the
#: publish gate's ``claim_masquerades_as_approved`` guard stays meaningful.
PROVENANCE_MAP: dict[str, tuple[str, str, str]] = {
    "verified_primary": ("verified_primary", "verified", "verified"),
    "verified_secondary": ("verified_secondary", "verified", "verified"),
    "approved_internal": ("approved_internal", "approved", "approved"),
    "claim": ("claim", "claim", "claim"),
}

#: kernel provenance levels with NO honest V2 mapping.  ``flagged``/``placeholder``
#: mean the number is unverified/unresolved; ``legacy`` means a superseded value.
#: The V2 contract has no such state, so the adapter refuses to invent one and
#: routes the fact to ``needs_curation`` (the curator must resolve the flag first).
UNMAPPABLE_PROVENANCE: frozenset[str] = frozenset({"flagged", "placeholder", "legacy"})

#: Weight/distance unit families used by the unit-drift detector.  Drift = the
#: recorded ``unit`` token is absent from the verbatim source quote while a
#: *conflicting* unit from the same family IS present (e.g. ``unit: lb`` but the
#: source says "9 kg" -- a real atomizer bug flagged in the kernel notes).
_WEIGHT_UNITS: tuple[str, ...] = ("kg", "lb", "lbs", "g")
_DIST_UNITS: tuple[str, ...] = ("km", "cm", "mm", "m")

#: Priority order for the single "primary gap" reported per fact (most blocking
#: first).  A fact may carry several gaps; the worklist groups on the primary one.
_GAP_PRIORITY: tuple[str, ...] = (
    "missing_source",
    "provenance_missing",
    "provenance_unmappable",
    "missing_value",
    "unit_drift",
    "no_evidence_span",
    "evidence_locator_unmappable",
)

#: The kernel fact files that hold publishable scalar/text facts (the ~259).
#: ``entities.yaml`` is an entity registry (provinces/organizations), NOT a set of
#: publishable facts, and is deliberately OUT OF SCOPE for this fact->record
#: adapter -- see the readiness report for the rationale.
FACT_FILES: tuple[tuple[str, str], ...] = (
    ("specs", "facts"),
    ("capabilities", "capabilities"),
    ("prices", "facts"),
    ("boms", "facts"),
    ("l3_facts", "facts"),
    ("l3_facts", "kernel_refs"),
    ("derived_costs", "facts"),
)

# Deterministic synthetic principals + timestamps for the rehearsal.  These are
# NOT real subjects; the real --apply binds the manifest curator to an
# authenticated session and re-signs each attestation.  Fixed so re-running the
# adapter is byte-for-byte reproducible.
_NS = uuid.UUID("b6e1f2a4-3c5d-4e6f-8a90-1b2c3d4e5f60")
OWNER_ID = uuid.uuid5(_NS, "rtr-migration-owner")
CURATOR_ID = uuid.uuid5(_NS, "rtr-migration-curator")
MIGRATION_EFFECTIVE = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)  # kernel snapshot day
MIGRATION_FRESH_DUE = datetime(2027, 7, 28, 0, 0, tzinfo=UTC)
# Dry-run signing secret.  The dry-run validators do NOT verify the attestation
# signature (only the apply gate does), but we sign deterministically so the
# emitted package is fully self-consistent and could be re-signed for --apply.
ADAPTER_SECRET = "tip013-phaseB-dryrun-adapter-signing-secret-32b"
PRODUCER = "kernel-adapter/0.1 (TIP-013 Phase B dry-run)"


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FactOutcome:
    """Per-fact readiness verdict from the adapter's conservative conversion."""

    fact_id: str
    file: str
    classification: str
    tier: str  # "staff" | "leader"
    kernel_provenance: str
    status: str  # "ready" | "needs_curation" | "rejected"
    v2_provenance: str | None
    gaps: tuple[str, ...]
    primary_gap: str | None
    reject_code: str | None
    denied_from_packs: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "file": self.file,
            "classification": self.classification,
            "tier": self.tier,
            "kernel_provenance": self.kernel_provenance,
            "status": self.status,
            "v2_provenance": self.v2_provenance,
            "gaps": list(self.gaps),
            "primary_gap": self.primary_gap,
            "reject_code": self.reject_code,
            "denied_from_packs": self.denied_from_packs,
        }


@dataclass
class _ReadyRecord:
    """A fully-built, gate-eligible record + evidence for a ready fact."""

    fact_id: str
    file: str
    source_key: str
    classification: str
    record: dict[str, Any]
    evidence: dict[str, Any]
    source_ref: str
    source_fingerprint: dict[str, str]


@dataclass
class ConversionResult:
    outcomes: list[FactOutcome] = field(default_factory=list)
    ready: list[_ReadyRecord] = field(default_factory=list)
    #: distinct source files referenced -> whether a kernel source-hash matched.
    source_hash_coverage: dict[str, bool] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Registry loading (READ-ONLY)
# --------------------------------------------------------------------------- #


def load_registry(root: Path) -> dict[str, Any]:
    """Load the read-only kernel snapshot.  Never writes; never mutates inputs."""
    data: dict[str, Any] = {}
    for name in (
        "specs",
        "capabilities",
        "prices",
        "boms",
        "l3_facts",
        "derived_costs",
        "leader_allowlist",
        "source_hashes",
    ):
        path = root / f"{name}.yaml"
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                data[name] = yaml.safe_load(stream)
        else:
            data[name] = None
    return data


def iter_facts(registry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Yield (file_key, fact) for every publishable fact, stable-ordered."""
    out: list[tuple[str, dict[str, Any]]] = []
    for file_key, list_key in FACT_FILES:
        doc = registry.get(file_key)
        if not isinstance(doc, dict):
            continue
        items = doc.get(list_key)
        if not isinstance(items, list):
            continue
        for fact in items:
            if isinstance(fact, dict) and fact.get("id"):
                out.append((file_key, fact))
    return out


# --------------------------------------------------------------------------- #
# Classification (from leader_allowlist doctrine)
# --------------------------------------------------------------------------- #


def leader_only_sources(allowlist: Any) -> frozenset[str]:
    """Kernel files whose facts are LEADER-ONLY per the allowlist.

    The doctrine (leader_allowlist.yaml header) is: staff see the SELL price +
    discounts + positioning; ONLY leaders see the BUY price (component cost +
    supplier name).  Machine-readably that is exactly the section carrying
    ``scope: leader_only`` -- the ``l2_cost`` block sourced from
    ``registry/boms.yaml``.  Sell-prices and positioning are also enumerated in
    the allowlist, but only because the leader pack is a SUPERSET of the staff
    pack; they are staff-visible, so they map to ``internal``, not ``restricted``.
    """
    sources: set[str] = set()
    if isinstance(allowlist, dict):
        for section in allowlist.values():
            if isinstance(section, dict) and section.get("scope") == "leader_only":
                src = section.get("source")
                if isinstance(src, str):
                    # e.g. "registry/boms.yaml" -> file key "boms"
                    sources.add(Path(src).stem)
    return frozenset(sources)


def classify(file_key: str, leader_files: frozenset[str]) -> tuple[str, str]:
    """Return (v2 classification, tier label)."""
    if file_key in leader_files:
        return "restricted", "leader"
    return "internal", "staff"


def denied_ids(allowlist: Any) -> frozenset[str]:
    """Fact-id prefixes/ids the allowlist explicitly excludes from ALL packs.

    Used only to annotate the report (these are unverified/flagged numbers the
    curator has already fenced off); they also fail the provenance mapping, so
    they land in ``needs_curation`` regardless.
    """
    prefixes: set[str] = set()
    if not isinstance(allowlist, dict):
        return frozenset()
    for entry in allowlist.get("deny", []) or []:
        text = str(entry.get("what", "")) if isinstance(entry, dict) else ""
        for token in ("BASE_BUILD_COST", "ALMO.MARGIN", "BUNDLE_GAP", "BOM."):
            if token in text:
                prefixes.add(token)
    return frozenset(prefixes)


def _is_denied(fact_id: str, denied: frozenset[str]) -> bool:
    return any(fact_id.startswith(prefix) or prefix in fact_id for prefix in denied)


# --------------------------------------------------------------------------- #
# Field extraction / mapping helpers
# --------------------------------------------------------------------------- #


def kernel_provenance_of(fact: dict[str, Any]) -> str:
    value = fact.get("provenance_level")
    return str(value) if value else ""


def source_ref_of(fact: dict[str, Any]) -> str | None:
    src = fact.get("source")
    if isinstance(src, dict):
        file_name = src.get("file")
        if file_name:
            return str(file_name)
    source_path = fact.get("source_path")
    if source_path:
        return str(source_path)
    return None


def extract_value(fact: dict[str, Any]) -> Any | None:
    """Faithful value: verified facts keep ``value``; claims were renamed to
    ``claim`` in the kernel; BOM component facts carry the number in ``cost_usd``;
    L3/capabilities carry prose in ``content``/``description``.  ``None`` means
    there is genuinely no value to publish (e.g. ``claim: null`` placeholders)."""
    if fact.get("value") is not None:
        return fact["value"]
    if fact.get("claim") is not None:
        return fact["claim"]
    if fact.get("cost_usd") is not None:
        return fact["cost_usd"]
    content = fact.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    description = fact.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return None


def extract_evidence_text(fact: dict[str, Any]) -> str | None:
    """A VERBATIM quotable span.  ``source.raw_text`` (specs) and
    ``evidence_span`` (L3) are verbatim source quotes; the capabilities
    ``evidence`` field is a list of source NAMES, not a quote, so it is NOT
    accepted as an evidence span."""
    src = fact.get("source")
    if isinstance(src, dict):
        raw = src.get("raw_text")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    span = fact.get("evidence_span")
    if isinstance(span, str) and span.strip():
        return span.strip()
    return None


def build_locator(fact: dict[str, Any]) -> dict[str, Any] | None:
    """Map the kernel source descriptor to a VALID V2 evidence locator.

    Only exact, non-distorting mappings are used: ``sheet``/``cell`` pass
    through; positive-integer ``page``/``paragraph``/``slide`` pass through.  A
    spreadsheet ``row`` (not a V2 locator key) is carried LOSSLESSLY in the
    free-form ``region`` span as ``"row:<n>"`` rather than coerced into a numeric
    page/paragraph position.  Keys with no faithful mapping (``section``,
    ``table`` as free text, ``col``, ``url``, ``note``, file-only) are dropped;
    if nothing usable remains, returns ``None`` (the caller marks the fact
    ``evidence_locator_unmappable``)."""
    src = fact.get("source")
    if not isinstance(src, dict):
        return None
    loc: dict[str, Any] = {}
    if isinstance(src.get("sheet"), str) and src["sheet"].strip():
        loc["sheet"] = src["sheet"]
    if isinstance(src.get("cell"), str) and src["cell"].strip():
        loc["cell"] = src["cell"]
    for key in ("page", "paragraph", "slide"):
        val = src.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 1:
            loc[key] = val
    row = src.get("row")
    if isinstance(row, int) and not isinstance(row, bool) and row >= 1:
        loc["region"] = f"row:{row}"
    return loc or None


def detect_unit_drift(fact: dict[str, Any]) -> bool:
    """True when the recorded unit conflicts with the verbatim source quote."""
    unit = fact.get("unit")
    src = fact.get("source")
    raw = src.get("raw_text") if isinstance(src, dict) else None
    if not isinstance(unit, str) or not isinstance(raw, str) or not raw.strip():
        return False
    token = unit.strip().lower().split()[0].split("(")[0].strip()
    if not token:
        return False
    text = raw.lower()
    if token in text:
        return False
    for family in (_WEIGHT_UNITS, _DIST_UNITS):
        if token in family and any(other != token and other in text for other in family):
            return True
    return False


# --------------------------------------------------------------------------- #
# Source fingerprints
# --------------------------------------------------------------------------- #


def kernel_source_hash(registry: dict[str, Any], source_ref: str) -> str | None:
    """The kernel's stored (truncated) drift hash for a source file, matched by
    basename, or ``None`` if the kernel never recorded one."""
    doc = registry.get("source_hashes")
    if not isinstance(doc, dict):
        return None
    sources = doc.get("sources")
    if not isinstance(sources, dict):
        return None
    base = Path(source_ref).name
    entry = sources.get(base)
    if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
        return str(entry["sha256"])
    return None


def source_fingerprint_sha(source_ref: str, kernel_hash: str | None) -> str:
    """A DETERMINISTIC migration fingerprint over the kernel's recorded source
    identity.

    This is NOT the true content hash of the source blob: the real source tree is
    unavailable in the rehearsal (we hold only the registry snapshot).  At the
    real ``--apply`` the adapter MUST recompute this from the actual source blob
    so the fingerprint attests to real bytes.  Documented as a deviation for the
    Homeowner.  We DELIBERATELY leave ``evidence.source_blob_sha256`` unset so the
    validator never compares an invented blob hash."""
    return sha256_bytes(
        canonical_json({"source_ref": source_ref, "kernel_source_hash": kernel_hash}),
    )


# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #


def _searchable_text(fact: dict[str, Any], value: Any) -> str:
    label = fact.get("key") or fact.get("name") or fact.get("id") or ""
    unit = fact.get("unit") or ""
    text = f"{label}: {value} {unit}".strip()
    return text[:200_000]


def _record_value(fact: dict[str, Any], value: Any) -> Any:
    unit = fact.get("unit")
    label = fact.get("key") or fact.get("name")
    if isinstance(value, str) and (label is None) and ("content" in fact):
        return {"statement": value[:180_000]}
    payload: dict[str, Any] = {"value": value}
    if label is not None:
        payload["label"] = str(label)
    if unit is not None:
        payload["unit"] = str(unit)
    return payload


def convert_fact(
    file_key: str,
    fact: dict[str, Any],
    *,
    registry: dict[str, Any],
    leader_files: frozenset[str],
    denied: frozenset[str],
) -> tuple[FactOutcome, _ReadyRecord | None]:
    fact_id = str(fact["id"])
    classification, tier = classify(file_key, leader_files)
    kernel_prov = kernel_provenance_of(fact)
    is_denied = _is_denied(fact_id, denied) and file_key in {"derived_costs", "boms"}

    gaps: list[str] = []

    # 1. provenance
    v2_prov: str | None = None
    prov_triple: tuple[str, str, str] | None = None
    if not kernel_prov:
        gaps.append("provenance_missing")
    elif kernel_prov in UNMAPPABLE_PROVENANCE:
        gaps.append("provenance_unmappable")
    elif kernel_prov in PROVENANCE_MAP:
        prov_triple = PROVENANCE_MAP[kernel_prov]
        v2_prov = prov_triple[0]
    else:
        gaps.append("provenance_unmappable")

    # 2. value
    value = extract_value(fact)
    if value is None:
        gaps.append("missing_value")

    # 3. source
    source_ref = source_ref_of(fact)
    if source_ref is None:
        gaps.append("missing_source")

    # 4. evidence span + locator
    evidence_text = extract_evidence_text(fact)
    locator = build_locator(fact)
    if evidence_text is None:
        gaps.append("no_evidence_span")
    elif locator is None:
        gaps.append("evidence_locator_unmappable")

    # 5. unit drift
    if detect_unit_drift(fact):
        gaps.append("unit_drift")

    if gaps:
        primary = next((code for code in _GAP_PRIORITY if code in gaps), gaps[0])
        outcome = FactOutcome(
            fact_id=fact_id,
            file=file_key,
            classification=classification,
            tier=tier,
            kernel_provenance=kernel_prov or "(none)",
            status="needs_curation",
            v2_provenance=v2_prov,
            gaps=tuple(gaps),
            primary_gap=primary,
            reject_code=None,
            denied_from_packs=is_denied,
        )
        return outcome, None

    # No gaps -> build a fully-grounded, gate-eligible record + evidence.
    assert prov_triple is not None and source_ref is not None
    assert evidence_text is not None and locator is not None
    v2_provenance, verification_state, fact_state = prov_triple
    confidence = 0.9 if verification_state in {"verified", "approved"} else 0.5
    source_key = f"rtr.{file_key}"
    khash = kernel_source_hash(registry, source_ref)
    fp_sha = source_fingerprint_sha(source_ref, khash)

    evidence_key = f"{fact_id}.e1"
    evidence_data: dict[str, Any] = {
        "evidence_key": evidence_key,
        "record_key": fact_id,
        "source_ref": source_ref,
        "source_document_id": None,
        "source_version_id": None,
        "source_blob_sha256": None,
        "locator": locator,
        "quoted_text": evidence_text[:180_000],
        "normalized_text": evidence_text[:180_000],
        "evidence_sha256": "0" * 64,
        "source_label": f"{Path(source_ref).name} · kernel {file_key}",
        "classification": classification,
    }
    evidence_data["evidence_sha256"] = evidence_content_sha(
        PackageEvidence.model_validate(evidence_data),
    )

    record_data: dict[str, Any] = {
        "record_key": fact_id,
        "version_ordinal": 1,
        "owner_id": str(OWNER_ID),
        "classification": classification,
        "department_id": None,
        "project_id": None,
        "value": _record_value(fact, value),
        "searchable_text": _searchable_text(fact, value),
        "provenance_level": v2_provenance,
        "confidence": confidence,
        "verification_state": verification_state,
        "fact_state": fact_state,
        "effective_from": MIGRATION_EFFECTIVE.isoformat(),
        "effective_to": None,
        "freshness_policy": {"maximum_age_days": 365},
        "freshness_due_at": MIGRATION_FRESH_DUE.isoformat(),
        "evidence_keys": [evidence_key],
        "source_refs": [source_ref],
        "content_sha256": "0" * 64,
        "supersedes_record_key": None,
        "acl": [
            {
                "principal_type": "user",
                "principal_id": str(OWNER_ID),
                "action": "view",
                "effect": "allow",
            },
        ],
    }
    record_data["content_sha256"] = record_content_sha(
        PackageRecord.model_validate(record_data),
    )

    outcome = FactOutcome(
        fact_id=fact_id,
        file=file_key,
        classification=classification,
        tier=tier,
        kernel_provenance=kernel_prov,
        status="ready",
        v2_provenance=v2_provenance,
        gaps=(),
        primary_gap=None,
        reject_code=None,
        denied_from_packs=is_denied,
    )
    ready = _ReadyRecord(
        fact_id=fact_id,
        file=file_key,
        source_key=source_key,
        classification=classification,
        record=record_data,
        evidence=evidence_data,
        source_ref=source_ref,
        source_fingerprint={"sha256": fp_sha, "classification": classification},
    )
    return outcome, ready


def convert_registry(registry: dict[str, Any]) -> ConversionResult:
    allowlist = registry.get("leader_allowlist")
    leader_files = leader_only_sources(allowlist)
    denied = denied_ids(allowlist)
    result = ConversionResult()
    for file_key, fact in iter_facts(registry):
        outcome, ready = convert_fact(
            file_key,
            fact,
            registry=registry,
            leader_files=leader_files,
            denied=denied,
        )
        result.outcomes.append(outcome)
        if ready is not None:
            result.ready.append(ready)
            matched = kernel_source_hash(registry, ready.source_ref) is not None
            result.source_hash_coverage[ready.source_ref] = matched
    return result


# --------------------------------------------------------------------------- #
# Package emission (staged layout the onboarding tool consumes)
# --------------------------------------------------------------------------- #


def _write_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def write_package(
    out_root: Path,
    source_key: str,
    ready: list[_ReadyRecord],
    *,
    revision: int = 1,
) -> str:
    """Write ONE staged SOT package (all ready records for a source key).

    Mirrors the exact wire layout of ``tests/sot_fixtures.build_package`` -- the
    same members, canonical-json encoding and manifest/attestation construction --
    but for N records.  Returns the staging directory name.
    """
    package_id = uuid.uuid5(_NS, f"package:{source_key}:{revision}")
    staging_name = f"package-{package_id}"
    package_root = out_root / staging_name
    package_root.mkdir(parents=True, exist_ok=True)

    record_rows = [dict(item.record) for item in ready]
    evidence_rows = [dict(item.evidence) for item in ready]
    source_hashes: dict[str, dict[str, str]] = {}
    for item in ready:
        source_hashes[item.source_ref] = item.source_fingerprint

    files: dict[str, bytes] = {
        "records.jsonl": b"".join(canonical_json(row) + b"\n" for row in record_rows),
        "evidence.jsonl": b"".join(canonical_json(row) + b"\n" for row in evidence_rows),
        "source_hashes.json": canonical_json(source_hashes),
    }
    for name, content in files.items():
        _write_bytes(package_root / name, content)

    payload_sha = sha256_bytes(
        canonical_json(
            [
                {"path": name, "sha256": sha256_bytes(content)}
                for name, content in sorted(files.items())
            ],
        ),
    )
    attestation: dict[str, Any] = {
        "package_id": str(package_id),
        "revision": revision,
        "manifest_sha256": "0" * 64,
        "payload_sha256": payload_sha,
        "validator_version": VALIDATOR_VERSION,
        "schema_version": "1.0",
        "policy_version": POLICY_VERSION,
        "validated_at": MIGRATION_EFFECTIVE.isoformat(),
        "curator_subject_id": str(CURATOR_ID),
        "decision": "approved",
        "expires_at": None,
        "signature": "0" * 64,
    }
    _write_bytes(package_root / "publish_attestation.json", canonical_json(attestation))

    members = [
        {
            "path": name,
            "byte_size": (package_root / name).stat().st_size,
            "sha256": sha256_bytes((package_root / name).read_bytes()),
        }
        for name in sorted((*files, "publish_attestation.json"))
    ]
    manifest_data: dict[str, Any] = {
        "schema_version": "1.0",
        "package_id": str(package_id),
        "source_key": source_key,
        "revision": revision,
        "trust_zone": "sot",
        "producer": PRODUCER,
        "generated_at": MIGRATION_EFFECTIVE.isoformat(),
        "payload_sha256": payload_sha,
        "members": members,
    }
    manifest = PackageManifest.model_validate(manifest_data)
    attestation["manifest_sha256"] = manifest_identity_sha(manifest)
    attestation["signature"] = sign_attestation(
        PublishAttestation.model_validate(attestation).model_dump(mode="json"),
        ADAPTER_SECRET,
    )
    attestation_bytes = canonical_json(attestation)
    _write_bytes(package_root / "publish_attestation.json", attestation_bytes)
    for member in members:
        if member["path"] == "publish_attestation.json":
            member["byte_size"] = len(attestation_bytes)
            member["sha256"] = sha256_bytes(attestation_bytes)
    _write_bytes(package_root / "manifest.json", canonical_json(manifest_data))
    return staging_name


def emit_packages(result: ConversionResult, out_root: Path) -> dict[str, str]:
    """Emit one package per source key that has ready records.  Deterministic
    ordering.  Returns {source_key: staging_name}."""
    out_root.mkdir(parents=True, exist_ok=True)
    by_key: dict[str, list[_ReadyRecord]] = {}
    for item in result.ready:
        by_key.setdefault(item.source_key, []).append(item)
    staged: dict[str, str] = {}
    for source_key in sorted(by_key):
        rows = sorted(by_key[source_key], key=lambda item: item.fact_id)
        staged[source_key] = write_package(out_root, source_key, rows)
    return staged


# --------------------------------------------------------------------------- #
# Summary (drives the readiness report)
# --------------------------------------------------------------------------- #


def summarize(result: ConversionResult) -> dict[str, Any]:
    by_file: dict[str, Counter[str]] = {}
    gap_hist: Counter[str] = Counter()
    tier_hist: Counter[str] = Counter()
    prov_hist: Counter[str] = Counter()
    status_hist: Counter[str] = Counter()
    for outcome in result.outcomes:
        by_file.setdefault(outcome.file, Counter())[outcome.status] += 1
        status_hist[outcome.status] += 1
        tier_hist[outcome.tier] += 1
        prov_hist[outcome.kernel_provenance] += 1
        if outcome.primary_gap:
            gap_hist[outcome.primary_gap] += 1
    matched = sum(1 for hit in result.source_hash_coverage.values() if hit)
    return {
        "total_facts": len(result.outcomes),
        "status_totals": dict(sorted(status_hist.items())),
        "by_file": {
            file_key: dict(sorted(counter.items()))
            for file_key, counter in sorted(by_file.items())
        },
        "classification_split": dict(sorted(tier_hist.items())),
        "kernel_provenance_split": dict(sorted(prov_hist.items())),
        "gap_histogram": dict(sorted(gap_hist.items(), key=lambda kv: (-kv[1], kv[0]))),
        "source_hash_coverage": {
            "distinct_ready_sources": len(result.source_hash_coverage),
            "matched_kernel_hash": matched,
        },
        "ready_fact_ids": sorted(item.fact_id for item in result.ready),
    }
