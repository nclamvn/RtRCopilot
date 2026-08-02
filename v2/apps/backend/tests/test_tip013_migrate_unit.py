"""TIP-013 Phase B · kernel -> V2 SOT adapter — hermetic unit tests.

No database, no Redis, no real kernel snapshot on disk: every case runs against a
tiny in-memory synthetic registry.  Proves the conservative-mapping contract that
the migration dress rehearsal depends on:

* a complete verified fact converts and PASSES the REAL publish gate;
* a provenance gap (flagged/missing), a missing value, an unmappable evidence
  span/locator and a unit drift each route the fact to ``needs_curation`` -- the
  adapter never fabricates the missing field;
* classification follows the leader-only allowlist doctrine (buy-price = leader,
  everything else = staff);
* evidence/record shas and emitted package bytes are deterministic; and
* the gate has TEETH -- a mis-mapped claim (claim provenance, verified state) is
  rejected with ``claim_masquerades_as_approved``, the safeguard that stops a bad
  real ``--apply``.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVAL = Path(__file__).resolve().parents[3] / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from migrate.kernel_adapter import (  # noqa: E402
    build_source_note,
    classify,
    convert_registry,
    emit_packages,
    leader_only_sources,
    write_package,
)  # noqa: E402

from rtr_copilot.sot.models import PackageRecord  # noqa: E402
from rtr_copilot.sot.package import (  # noqa: E402
    PackageParser,
    record_content_sha,
    validate_package,
)  # noqa: E402

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def _registry() -> dict[str, Any]:
    return {
        "specs": {
            "facts": [
                {
                    "id": "SPEC.OK",
                    "key": "Flight time",
                    "value": 56,
                    "unit": "minutes",
                    "status": "VERIFIED",
                    "source": {
                        "file": "source_canonical/HERA.xlsx",
                        "row": 12,
                        "raw_text": "56 minutes",
                    },
                    "provenance_level": "verified_primary",
                },
                {
                    "id": "SPEC.DRIFT",
                    "key": "Weight",
                    "value": 9,
                    "unit": "lb",
                    "status": "VERIFIED",
                    "source": {
                        "file": "source_canonical/HERA.xlsx",
                        "row": 6,
                        "raw_text": "Aircraft weight: 9 kg",
                    },
                    "provenance_level": "verified_primary",
                },
                {
                    "id": "SPEC.FLAG",
                    "key": "Payload bays",
                    "claim": None,
                    "unit": "bay",
                    "status": "CONFLICT",
                    "source": {
                        "file": "source_canonical/HERA.xlsx",
                        "row": 11,
                        "raw_text": "three payload mounting points",
                    },
                    "provenance_level": "flagged",
                },
                {
                    "id": "SPEC.CLAIM_NOSPAN",
                    "key": "Edge AI",
                    "claim": 105,
                    "unit": "TOPS",
                    "status": "INT",
                    "source": {"file": "source_canonical/Adv.xlsx"},
                    "provenance_level": "claim",
                },
                {
                    # verified_primary + value + source, but NO verbatim span ->
                    # relaxed policy: soft-ready with a source note + flag.
                    "id": "SPEC.SOFT",
                    "key": "Comm channels",
                    "value": 5,
                    "unit": "channel",
                    "status": "VERIFIED",
                    "source": {"file": "source_canonical/HERA.xlsx", "row": 20},
                    "provenance_level": "verified_primary",
                },
                {
                    # verified_primary but NO source at all -> stays curate
                    # (missing_source); the adapter fabricates nothing.
                    "id": "SPEC.NOSRC",
                    "key": "Derived ratio",
                    "value": 0.15,
                    "unit": "fraction",
                    "status": "VERIFIED",
                    "provenance_level": "verified_primary",
                },
                {
                    # a claim that IS fully grounded (span + locator) must STILL
                    # never auto-ready as a fact -- claim tier, not strict.
                    "id": "SPEC.CLAIM_FULL",
                    "key": "Edge TOPS claimed",
                    "claim": 105,
                    "unit": "TOPS",
                    "status": "INT",
                    "source": {
                        "file": "source_canonical/HERA.xlsx",
                        "row": 21,
                        "raw_text": "Edge AI compute: 105 TOPS",
                    },
                    "provenance_level": "claim",
                },
            ],
        },
        "boms": {
            "facts": [
                {
                    "id": "BOM.X",
                    "key": "airframe",
                    "cost_usd": 35000,
                    "unit": "1 unit",
                    "vendor": "RtR",
                    "source": {"file": "_governance/cost.xlsx", "sheet": "01", "row": 5},
                    "provenance_level": "verified_primary",
                },
            ],
        },
        "l3_facts": {
            "facts": [
                {
                    "id": "L3F.1",
                    "content": "HeraSight LR camera Sony ILX-LR1 61MP.",
                    "domain": "product",
                    "tier": "L3",
                    "source_path": "/Users/os/RtR/x.xlsx",
                    "evidence_span": '"RGB Camera | Sony ILX-LR1 full frame, 61M pixels"',
                    "provenance_level": "claim",
                },
            ],
            "kernel_refs": [
                {
                    "id": "L3R.K.1",
                    "content": "HERA ingress protection is IP54.",
                    "domain": "product",
                    "tier": "L3",
                    "kernel_ref": "HC-042",
                    "source_path": "/Users/os/RtR/kernel/registry/capabilities.yaml",
                },
            ],
        },
        "leader_allowlist": {
            "l2_cost": {
                "source": "registry/boms.yaml",
                "scope": "leader_only",
                "include_all": True,
            },
            "deny": [{"what": "registry/boms.yaml BOM.* buy price"}],
        },
        "source_hashes": {"sources": {"HERA.xlsx": {"sha256": "b304070906b25afc"}}},
    }


def _outcomes_by_id(registry: dict[str, Any]) -> dict[str, Any]:
    result = convert_registry(registry)
    return {outcome.fact_id: outcome for outcome in result.outcomes}


def test_complete_verified_fact_is_ready() -> None:
    outcomes = _outcomes_by_id(_registry())
    ok = outcomes["SPEC.OK"]
    assert ok.status == "ready"
    assert ok.confidence_tier == "strict"  # verbatim span + locator -> strict
    assert ok.gaps == ()
    assert ok.v2_provenance == "verified_primary"
    assert ok.classification == "internal"
    assert ok.tier == "staff"
    # strict facts carry NO double-check marker (unchanged behavior)
    assert ok.needs_double_check is False
    assert ok.source_note is None


def test_strict_record_value_has_no_confidence_signal(tmp_path: Path) -> None:
    """A strict record is byte-for-byte the same shape as before: its ``value``
    payload carries NO ``confidence_signal`` marker (the relaxed policy leaves
    strict untouched), and it DOES carry a real evidence span."""
    result = convert_registry(_registry())
    strict = next(item for item in result.ready if item.fact_id == "SPEC.OK")
    assert strict.confidence_tier == "strict"
    assert strict.evidence is not None
    assert "confidence_signal" not in strict.record["value"]
    assert strict.record["evidence_keys"] == ["SPEC.OK.e1"]
    assert strict.record["confidence"] == 0.9


def test_every_emitted_package_passes_the_real_gate(tmp_path: Path) -> None:
    result = convert_registry(_registry())
    staged = emit_packages(result, tmp_path)
    # relaxed policy: strict rtr.specs (mixed strict+soft) AND soft-only rtr.boms
    assert set(staged) == {"rtr.specs", "rtr.boms"}
    parser = PackageParser(tmp_path)
    for source_key, staging_name in staged.items():
        parsed = parser.parse(staging_name)
        report = validate_package(parsed, now=NOW, allow_claim_as_approved=False)
        assert report.valid, (source_key, [f.code for f in report.findings])
    # rtr.specs = SPEC.OK (strict, has evidence) + SPEC.SOFT (soft, no evidence)
    specs = parser.parse(staged["rtr.specs"])
    assert {r.record_key for r in specs.records} == {"SPEC.OK", "SPEC.SOFT"}
    assert {e.record_key for e in specs.evidence} == {"SPEC.OK"}
    # rtr.boms = BOM.X (soft, restricted) with NO evidence member
    boms = parser.parse(staged["rtr.boms"])
    assert {r.record_key for r in boms.records} == {"BOM.X"}
    assert boms.evidence == []


def test_flagged_provenance_needs_curation_not_fabricated() -> None:
    outcomes = _outcomes_by_id(_registry())
    flagged = outcomes["SPEC.FLAG"]
    assert flagged.status == "needs_curation"
    assert flagged.primary_gap == "provenance_unmappable"
    assert "missing_value" in flagged.gaps  # claim: null carries no value
    assert flagged.v2_provenance is None  # nothing invented


def test_missing_provenance_needs_curation() -> None:
    outcomes = _outcomes_by_id(_registry())
    ref = outcomes["L3R.K.1"]
    assert ref.status == "needs_curation"
    assert ref.primary_gap == "provenance_missing"


def test_claim_without_span_needs_curation() -> None:
    outcomes = _outcomes_by_id(_registry())
    claim = outcomes["SPEC.CLAIM_NOSPAN"]
    assert claim.status == "needs_curation"
    assert claim.primary_gap == "no_evidence_span"


def test_verbatim_span_without_locator_needs_curation() -> None:
    outcomes = _outcomes_by_id(_registry())
    l3 = outcomes["L3F.1"]
    assert l3.status == "needs_curation"
    assert l3.primary_gap == "evidence_locator_unmappable"


def test_unit_drift_detected() -> None:
    outcomes = _outcomes_by_id(_registry())
    drift = outcomes["SPEC.DRIFT"]
    assert drift.status == "needs_curation"
    assert drift.primary_gap == "unit_drift"


def test_classification_leader_vs_staff() -> None:
    registry = _registry()
    leader_files = leader_only_sources(registry["leader_allowlist"])
    assert leader_files == frozenset({"boms"})
    assert classify("boms", leader_files) == ("restricted", "leader")
    assert classify("specs", leader_files) == ("internal", "staff")
    outcomes = _outcomes_by_id(registry)
    # classification (leader vs staff) is UNCHANGED by the relaxed policy...
    assert outcomes["BOM.X"].tier == "leader"
    assert outcomes["BOM.X"].classification == "restricted"
    # ...but the buy-price fact is now soft-ready (was needs_curation under strict)
    assert outcomes["BOM.X"].status == "ready"
    assert outcomes["BOM.X"].confidence_tier == "soft"
    assert outcomes["BOM.X"].needs_double_check is True


def test_evidence_and_record_sha_are_stable() -> None:
    first = convert_registry(_registry()).ready
    second = convert_registry(_registry()).ready
    assert [i.fact_id for i in first] == [i.fact_id for i in second]
    assert {i.fact_id for i in first} == {"SPEC.OK", "SPEC.SOFT", "BOM.X"}
    by_id = {i.fact_id: i for i in first}
    by_id2 = {i.fact_id: i for i in second}
    # strict record: real evidence + record digests, stable across runs
    strict, strict2 = by_id["SPEC.OK"], by_id2["SPEC.OK"]
    assert strict.evidence is not None and strict2.evidence is not None
    assert strict.evidence["evidence_sha256"] == strict2.evidence["evidence_sha256"]
    assert strict.record["content_sha256"] == strict2.record["content_sha256"]
    # a real, non-zero digest was computed (not the placeholder)
    assert strict.record["content_sha256"] != "0" * 64
    assert strict.evidence["evidence_sha256"] != "0" * 64
    # soft record: no evidence, but its record digest is deterministic too
    soft, soft2 = by_id["SPEC.SOFT"], by_id2["SPEC.SOFT"]
    assert soft.evidence is None
    assert soft.record["content_sha256"] == soft2.record["content_sha256"]
    assert soft.record["content_sha256"] != "0" * 64


def test_emitted_packages_are_byte_identical(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    staged_a = emit_packages(convert_registry(_registry()), root_a)
    staged_b = emit_packages(convert_registry(_registry()), root_b)
    assert staged_a == staged_b
    name = staged_a["rtr.specs"]
    for member in ("manifest.json", "records.jsonl", "evidence.jsonl",
                   "source_hashes.json", "publish_attestation.json"):
        assert (root_a / name / member).read_bytes() == (root_b / name / member).read_bytes()


def test_gate_rejects_a_masquerading_claim(tmp_path: Path) -> None:
    """Safeguard: if a claim were mis-mapped to a verified state, the gate stops
    it. This is the control that protects the real --apply."""
    result = convert_registry(_registry())
    ready = next(item for item in result.ready if item.fact_id == "SPEC.OK")
    record = dict(ready.record)
    record["provenance_level"] = "claim"
    record["verification_state"] = "verified"  # the forbidden mis-map
    record["content_sha256"] = "0" * 64
    record["content_sha256"] = record_content_sha(PackageRecord.model_validate(record))
    ready.record = record
    staged_name = write_package(tmp_path, "rtr.masquerade", [ready])
    parsed = PackageParser(tmp_path).parse(staged_name)
    report = validate_package(parsed, now=NOW, allow_claim_as_approved=False)
    assert not report.valid
    assert "claim_masquerades_as_approved" in {finding.code for finding in report.findings}


# --------------------------------------------------------------------------- #
# TIP-013B relaxed-ready policy: soft tier, source note + double-check marker
# --------------------------------------------------------------------------- #


def test_verified_primary_without_span_is_soft_ready() -> None:
    """AC-1: a verified_primary fact WITH a source but no verbatim span becomes
    soft-ready with a deterministic source note + needs_double_check marker."""
    result = convert_registry(_registry())
    outcomes = {o.fact_id: o for o in result.outcomes}
    soft = outcomes["SPEC.SOFT"]
    assert soft.status == "ready"
    assert soft.confidence_tier == "soft"
    assert soft.needs_double_check is True
    assert soft.v2_provenance == "verified_primary"
    # honest source note built from real metadata: file basename + row (no quote,
    # since the kernel carries none -- nothing is invented)
    assert soft.source_note == "HERA.xlsx · row 20"


def test_soft_marker_rides_on_record_value_for_part_b() -> None:
    """The double-check marker + source note ride in the record's ``value`` payload
    (an existing field), so Part B reads them from the answer's citation metadata
    with no schema/gate change.  The soft record carries NO evidence entry."""
    result = convert_registry(_registry())
    soft = next(item for item in result.ready if item.fact_id == "SPEC.SOFT")
    assert soft.evidence is None
    assert soft.record["evidence_keys"] == []
    signal = soft.record["value"]["confidence_signal"]
    assert signal == {
        "tier": "soft",
        "needs_double_check": True,
        "source_note": "HERA.xlsx · row 20",
    }
    # the actual fact value is preserved alongside the marker
    assert soft.record["value"]["value"] == 5
    assert soft.record["confidence"] == 0.7


def test_soft_only_package_is_valid_without_evidence(tmp_path: Path) -> None:
    """A package of only soft records (no evidence.jsonl member) still passes the
    real gate -- evidence is an optional member."""
    result = convert_registry(_registry())
    staged = emit_packages(result, tmp_path)
    parser = PackageParser(tmp_path)
    boms = parser.parse(staged["rtr.boms"])
    report = validate_package(boms, now=NOW, allow_claim_as_approved=False)
    assert report.valid, [f.code for f in report.findings]
    assert report.evidence_count == 0
    assert report.record_count == 1


def test_missing_source_stays_curate_not_soft() -> None:
    """A verified_primary fact with NO source stays needs_curation (missing_source)
    -- it must NOT be promoted to soft, and no source is fabricated."""
    outcomes = _outcomes_by_id(_registry())
    nosrc = outcomes["SPEC.NOSRC"]
    assert nosrc.status == "needs_curation"
    assert nosrc.confidence_tier == "curate"
    assert nosrc.primary_gap == "missing_source"
    assert nosrc.needs_double_check is False
    assert nosrc.source_note is None
    assert "SPEC.NOSRC" not in {item.fact_id for item in convert_registry(_registry()).ready}


def test_grounded_claim_never_auto_ready() -> None:
    """A claim that HAS a verbatim span + locator is still never auto-ready as a
    fact: it lands in the ``claim`` bucket (needs curator promotion), not strict."""
    outcomes = _outcomes_by_id(_registry())
    claim = outcomes["SPEC.CLAIM_FULL"]
    assert claim.status == "needs_curation"
    assert claim.confidence_tier == "claim"
    assert claim.needs_double_check is False
    ready_ids = {item.fact_id for item in convert_registry(_registry()).ready}
    assert "SPEC.CLAIM_FULL" not in ready_ids
    # the plain claim-without-span is also a claim, not curate-by-gap
    assert outcomes["SPEC.CLAIM_NOSPAN"].confidence_tier == "claim"


def test_source_note_is_deterministic_and_truncates_safely() -> None:
    """The source note is a pure function of the fact and truncates a long, multi
    line verbatim quote to ~120 chars with an ellipsis (never crashes on odd
    input, never mangles a date embedded in a non-path file ref)."""
    long_quote = "word " * 60  # 300 chars, whitespace-heavy
    fact = {
        "id": "X",
        "key": "k",
        "value": 1,
        "source": {"file": "a/b/Report_v1_0.xlsx", "row": 3, "raw_text": long_quote},
        "provenance_level": "verified_primary",
    }
    note1 = build_source_note(fact)
    note2 = build_source_note(fact)
    assert note1 == note2  # deterministic
    assert note1.startswith('Report_v1_0.xlsx · row 3 · "')
    quoted = note1.split(' · "', 1)[1][:-1]
    assert len(quoted) <= 121  # 120 + ellipsis
    assert quoted.endswith("…")
    # a non-path file ref with an embedded date is NOT mangled to a basename
    chat_fact = {
        "id": "Y",
        "key": "k",
        "value": 2,
        "source": {"file": "chat team RtR 14/06"},
        "provenance_level": "verified_primary",
    }
    assert build_source_note(chat_fact) == "chat team RtR 14/06"
    # sheet/cell fall back cleanly when there is no row
    cell_fact = {
        "id": "Z",
        "key": "k",
        "value": 3,
        "source": {"file": "p/Pricing.xlsx", "sheet": "01_MSRP", "cell": "C6"},
        "provenance_level": "verified_primary",
    }
    assert build_source_note(cell_fact) == "Pricing.xlsx · sheet 01_MSRP!C6"


def test_derived_from_verified_maps_to_soft_secondary() -> None:
    """Relaxed policy: derived_from_verified (withheld as unmappable in the strict
    rehearsal) now maps to verified_secondary and rides as a soft-ready record."""
    registry = _registry()
    registry["l3_facts"]["facts"].append({
        "id": "L3F.DERIVED",
        "content": "Composed fact derived from verified primaries.",
        "domain": "product",
        "tier": "L3",
        "source_path": "(tổng hợp trong kernel)",
        "evidence_span": "derived summary text",
        "provenance_level": "derived_from_verified",
    })
    outcomes = {o.fact_id: o for o in convert_registry(registry).outcomes}
    dfv = outcomes["L3F.DERIVED"]
    assert dfv.status == "ready"
    assert dfv.confidence_tier == "soft"
    assert dfv.v2_provenance == "verified_secondary"
    assert dfv.needs_double_check is True
