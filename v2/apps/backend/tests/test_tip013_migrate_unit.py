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

import copy
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVAL = Path(__file__).resolve().parents[3] / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from migrate.curation_overlay import (  # noqa: E402
    EXCLUDE,
    HELD_CLAIM,
    HELD_DERIVED,
    IRREDUCIBLE,
    IRREDUCIBLE_GAP,
    PROMOTE_INTERIM_SPEC_DUP,
    PROMOTE_VERIFIED_PRIMARY,
    READY_SOFT,
    READY_STRATEGIC,
    READY_STRICT,
    STRATEGIC_DOC,
    UNIT_FIX,
    CurationOverlay,
    OverlayDecision,
    final_disposition,
)
from migrate.kernel_adapter import (  # noqa: E402
    build_source_note,
    classify,
    convert_registry,
    emit_packages,
    leader_only_sources,
    write_package,
)  # noqa: E402
from migrate.run_migration import expectation_errors  # noqa: E402

from rtr_copilot.sot.models import PackageRecord  # noqa: E402
from rtr_copilot.sot.package import (  # noqa: E402
    PackageParser,
    record_content_sha,
    validate_package,
)  # noqa: E402

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def test_external_publish_count_gate_requires_exact_approved_scope() -> None:
    report = {
        "adapter_summary": {"total_facts": 259},
        "final_tier_totals": {"strict": 8, "soft": 205, "strategic": 6},
    }
    assert expectation_errors(report, expect_total=259, expect_ready=219) == []
    assert expectation_errors(report, expect_total=259, expect_ready=218) == [
        "ready record count mismatch: expected=218 actual=219",
    ]
    assert expectation_errors(report, expect_total=42, expect_ready=219) == [
        "source fact count mismatch: expected=42 actual=259",
    ]


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


# --------------------------------------------------------------------------- #
# TIP-013B · Homeowner curation-decision OVERLAY (DRY-RUN; kernel never modified)
# --------------------------------------------------------------------------- #


def _overlay_registry() -> dict[str, Any]:
    """A deep copy of the synthetic registry with one extra strategic-doc
    kernel_ref, so the overlay's four decisions all have a target."""
    reg = copy.deepcopy(_registry())
    reg["l3_facts"]["kernel_refs"].append({
        "id": "L3R.STRAT",
        "content": "RtR strategic doctrine statement grounded on a staged doc.",
        "domain": "company",
        "tier": "L3",
        "kernel_ref": "CEO_STRATEGIC_STANCE_2026-07-01",
        "source_path": "/Users/os/RtR/KnowledgeBase/Factsheet.docx",
    })
    return reg


def _test_overlay() -> CurationOverlay:
    """An overlay keyed to the synthetic ids: decision 1a on the kernel_ref
    ``L3R.K.1``, 1b on ``SPEC.DRIFT``, 3 on ``L3R.STRAT``, 4 on ``SPEC.FLAG``.
    Decision 2 (claim-with-span) is a built-in RULE and needs no keying; it fires
    on ``L3F.1`` (an l3 claim with an ``evidence_span``)."""
    return CurationOverlay(
        promote_verified_primary=frozenset({"L3R.K.1"}),
        unit_fix={"SPEC.DRIFT": ("lb", "kg")},
        strategic_doc=frozenset({"L3R.STRAT"}),
        exclude=frozenset({"SPEC.FLAG"}),
    )


def _overlay_outcomes(reg: dict[str, Any]) -> dict[str, Any]:
    result = convert_registry(reg, overlay=_test_overlay())
    return {o.fact_id: o for o in result.outcomes}


def test_overlay_approved_decision_set_is_exactly_the_named_facts() -> None:
    """Guard the audit trail: the shipped overlay promotes/excludes EXACTLY the
    facts the Homeowner named (decisions 1a, 1b, 3, 4) -- no drift."""
    assert sorted(PROMOTE_VERIFIED_PRIMARY) == [
        "L3R.2.005", "L3R.2.013", "L3R.2.027", "L3R.3.030", "L3R.K.006",
    ]
    assert sorted(UNIT_FIX) == [
        "SPEC.HERA.MTOW", "SPEC.HERA.WEIGHT.EMPTY", "SPEC.HERA.WEIGHT.TAKEOFF",
    ]
    assert all(v == ("lb", "kg") for v in UNIT_FIX.values())
    assert sorted(STRATEGIC_DOC) == [
        "L3R.2.023", "L3R.2.024", "L3R.2.025", "L3R.2.026", "L3R.2.032", "L3R.K.004",
    ]
    assert sorted(EXCLUDE) == ["L3R.K.005"]


def test_overlay_decision1a_promotes_named_kernel_ref_to_soft() -> None:
    """Decision 1a: a named kernel_ref inherits verified_primary -> soft-ready with
    the double-check marker and a note that cites the kernel record it inherits."""
    reg = _overlay_registry()
    # Baseline (no overlay) the kernel_ref is curate/provenance_missing...
    base = {o.fact_id: o for o in convert_registry(reg).outcomes}["L3R.K.1"]
    assert base.status == "needs_curation" and base.confidence_tier == "curate"
    # ...with the overlay it is soft-ready, honestly grounded on HC-042.
    ov = _overlay_outcomes(reg)["L3R.K.1"]
    assert ov.status == "ready"
    assert ov.confidence_tier == "soft"
    assert ov.v2_provenance == "verified_primary"
    assert ov.needs_double_check is True
    assert ov.source_note is not None and "inherits: HC-042" in ov.source_note


def test_overlay_decision1b_unit_fix_yields_kg_and_strict(tmp_path: Path) -> None:
    """Decision 1b: lb -> kg clears the drift and the fact flips to strict (verbatim
    span + row locator), NO caveat.  The emitted record carries unit ``kg``."""
    reg = _overlay_registry()
    # Baseline: SPEC.DRIFT is curate with a unit_drift gap.
    base = {o.fact_id: o for o in convert_registry(reg).outcomes}["SPEC.DRIFT"]
    assert base.status == "needs_curation" and base.primary_gap == "unit_drift"
    # Overlay: strict-ready, no caveat, no gaps.
    result = convert_registry(reg, overlay=_test_overlay())
    drift = {o.fact_id: o for o in result.outcomes}["SPEC.DRIFT"]
    assert drift.status == "ready"
    assert drift.confidence_tier == "strict"
    assert drift.needs_double_check is False
    assert "unit_drift" not in drift.gaps
    rec = next(r for r in result.ready if r.fact_id == "SPEC.DRIFT")
    assert rec.record["value"]["unit"] == "kg"
    assert "confidence_signal" not in rec.record["value"]  # strict stays clean


def test_overlay_decision2_promotes_claim_with_span_to_soft_caveat() -> None:
    """Decision 2 (RULE): an l3 claim that carries a real evidence_span is promoted
    to soft-ready grounded on that span, WITH the double-check caveat.  The kernel
    provenance was ``claim`` -> emitted as ``approved_internal`` (never masquerading
    verified), and the audit records the origin as claim."""
    reg = _overlay_registry()
    base = {o.fact_id: o for o in convert_registry(reg).outcomes}["L3F.1"]
    assert base.confidence_tier == "claim"  # untouched without the overlay
    result = convert_registry(reg, overlay=_test_overlay())
    l3 = {o.fact_id: o for o in result.outcomes}["L3F.1"]
    assert l3.status == "ready"
    assert l3.confidence_tier == "soft"
    assert l3.v2_provenance == "approved_internal"
    assert l3.needs_double_check is True
    # grounded on the REAL evidence_span text (Sony ILX-LR1 quote)
    assert l3.source_note is not None and "Sony ILX-LR1" in l3.source_note
    rec = next(r for r in result.ready if r.fact_id == "L3F.1")
    signal = rec.record["value"]["confidence_signal"]
    assert signal["tier"] == "soft"
    assert signal["curation"] == {
        "decision": "D2-claim-with-span-promoted",
        "origin_provenance": "claim",
    }


def test_overlay_non_promoted_claim_stays_claim() -> None:
    """A claim that is NOT an l3 claim-with-span (e.g. a specs claim) is untouched by
    the overlay -- it stays ``claim`` and is never auto-promoted."""
    outcomes = _overlay_outcomes(_overlay_registry())
    assert outcomes["SPEC.CLAIM_NOSPAN"].confidence_tier == "claim"
    assert outcomes["SPEC.CLAIM_NOSPAN"].status == "needs_curation"
    assert outcomes["SPEC.CLAIM_FULL"].confidence_tier == "claim"


def test_overlay_decision3_strategic_tier_carries_caveat() -> None:
    """Decision 3: a strategic-doc kernel_ref becomes the ``strategic`` tier
    (ready-with-caveat), grounded on the staged doc named in its kernel_ref."""
    result = convert_registry(_overlay_registry(), overlay=_test_overlay())
    strat = {o.fact_id: o for o in result.outcomes}["L3R.STRAT"]
    assert strat.status == "ready"
    assert strat.confidence_tier == "strategic"
    assert strat.v2_provenance == "approved_internal"
    assert strat.needs_double_check is True
    assert strat.source_note is not None
    assert "strategic-doc: CEO_STRATEGIC_STANCE_2026-07-01" in strat.source_note
    rec = next(r for r in result.ready if r.fact_id == "L3R.STRAT")
    signal = rec.record["value"]["confidence_signal"]
    assert signal["tier"] == "strategic"
    assert signal["curation"]["decision"] == "D3-strategic-doc"
    assert rec.record["confidence"] == 0.6


def test_overlay_decision4_excludes_fact_entirely(tmp_path: Path) -> None:
    """Decision 4: the excluded fact is emitted in NO tier and NO package."""
    reg = _overlay_registry()
    result = convert_registry(reg, overlay=_test_overlay())
    outcomes = {o.fact_id: o for o in result.outcomes}
    excluded = outcomes["SPEC.FLAG"]
    assert excluded.status == "excluded"
    assert excluded.confidence_tier == "excluded"
    assert "SPEC.FLAG" not in {r.fact_id for r in result.ready}
    staged = emit_packages(result, tmp_path)
    parser = PackageParser(tmp_path)
    for staging_name in staged.values():
        parsed = parser.parse(staging_name)
        assert "SPEC.FLAG" not in {r.record_key for r in parsed.records}


def test_overlay_emitted_packages_pass_the_real_gate(tmp_path: Path) -> None:
    """Every overlay-promoted package (soft, strategic, promoted-claim) still PASSES
    the real publish gate -- approved_internal without evidence is a valid record."""
    result = convert_registry(_overlay_registry(), overlay=_test_overlay())
    staged = emit_packages(result, tmp_path)
    parser = PackageParser(tmp_path)
    for source_key, staging_name in staged.items():
        parsed = parser.parse(staging_name)
        report = validate_package(parsed, now=NOW, allow_claim_as_approved=False)
        assert report.valid, (source_key, [f.code for f in report.findings])


def test_overlay_is_byte_deterministic(tmp_path: Path) -> None:
    """The overlay conversion + emission is byte-for-byte reproducible."""
    reg = _overlay_registry()
    staged_a = emit_packages(convert_registry(reg, overlay=_test_overlay()), tmp_path / "a")
    staged_b = emit_packages(convert_registry(reg, overlay=_test_overlay()), tmp_path / "b")
    assert staged_a == staged_b
    for name in staged_a.values():
        for member in ("manifest.json", "records.jsonl", "source_hashes.json",
                       "publish_attestation.json"):
            a = (tmp_path / "a" / name / member).read_bytes()
            b = (tmp_path / "b" / name / member).read_bytes()
            assert a == b


def test_overlay_does_not_mutate_the_kernel_snapshot() -> None:
    """DRY-RUN discipline: applying the overlay must not modify the input registry
    (the read-only kernel snapshot) -- the unit stays ``lb`` and the claim stays
    ``claim`` on the source dicts; transforms live only on the emitted copies."""
    reg = _overlay_registry()
    before = copy.deepcopy(reg)
    convert_registry(reg, overlay=_test_overlay())
    assert reg == before
    drift = next(f for f in reg["specs"]["facts"] if f["id"] == "SPEC.DRIFT")
    assert drift["unit"] == "lb"  # untouched on the snapshot
    l3 = next(f for f in reg["l3_facts"]["facts"] if f["id"] == "L3F.1")
    assert l3["provenance_level"] == "claim"  # untouched on the snapshot


def test_overlay_decision_apply_to_fact_returns_a_copy() -> None:
    """``OverlayDecision.apply_to_fact`` never mutates its argument."""
    fact = {"id": "X", "unit": "lb", "provenance_level": "claim", "value": 1}
    decision = OverlayDecision(fix_unit=("lb", "kg"), set_provenance="verified_primary")
    out = decision.apply_to_fact(fact)
    assert out is not fact
    assert out["unit"] == "kg" and out["provenance_level"] == "verified_primary"
    assert fact["unit"] == "lb" and fact["provenance_level"] == "claim"  # original intact
    # a no-op decision returns the same object untouched
    assert OverlayDecision().apply_to_fact(fact) is fact


# --------------------------------------------------------------------------- #
# TIP-013B FINAL completion (wave 2): 67-cap promote, 20 cascade, MTOW.HC001 dup,
# explicit holds/derived/irreducible dispositions.  All hermetic (synthetic reg).
# --------------------------------------------------------------------------- #


def _final_registry() -> dict[str, Any]:
    """A deep copy of the synthetic registry with a ``capabilities`` file and the
    kernel_refs / interim spec the wave-2 decisions target."""
    reg = copy.deepcopy(_registry())
    reg["capabilities"] = {
        "capabilities": [
            {
                # claim + a real evidence reference -> Decision 1B promotes to soft.
                "id": "HC-TEST",
                "name": "Promotable capability",
                "description": "A capability claim carrying a documentary evidence ref.",
                "evidence": "brochure XPO26, KB v1.0 sheet 02, DCMA submission",
                "source": {"file": "source_canonical/Matrix.xlsx", "sheet": "01", "row": 2},
                "provenance_level": "claim",
            },
            {
                # claim WITHOUT an evidence reference -> stays claim (not promoted).
                "id": "HC-NOEV",
                "name": "Un-sourced capability",
                "description": "A capability claim with no evidence reference.",
                "evidence": "",
                "source": {"file": "source_canonical/Matrix.xlsx", "sheet": "01", "row": 3},
                "provenance_level": "claim",
            },
            {
                # already verified -> soft via the native path (also a promoted cap).
                "id": "HC-VERIFIED",
                "name": "Verified capability",
                "description": "An already-verified capability.",
                "source": {"file": "source_canonical/Matrix.xlsx", "sheet": "01", "row": 4},
                "provenance_level": "verified_primary",
            },
        ],
    }
    reg["l3_facts"]["kernel_refs"].extend([
        {
            # curate kernel_ref whose kernel_ref names the promoted HC-TEST -> cascade.
            "id": "L3R.CASCADE",
            "content": "L3 wording that duplicates the HC-TEST capability.",
            "domain": "product",
            "tier": "L3",
            "kernel_ref": "HC-TEST + RENAME-01",
            "source_path": "/Users/os/RtR/x.xlsx",
        },
        {
            # curate kernel_ref naming a NON-promoted cap (HC-NOEV) -> stays curate.
            "id": "L3R.NOCASCADE",
            "content": "L3 wording pointing at an un-promoted capability.",
            "domain": "product",
            "tier": "L3",
            "kernel_ref": "HC-NOEV",
            "source_path": "/Users/os/RtR/x.xlsx",
        },
    ])
    reg["specs"]["facts"].append({
        # interim spec (status INT, no raw_text) that duplicates the verified SPEC.OK.
        "id": "SPEC.DUP",
        "key": "Flight time per Matrix HC-TEST",
        "claim": 56,
        "unit": "minutes",
        "status": "INT",
        "source": {
            "file": "source_canonical/Matrix.xlsx", "sheet": "01", "row": 2, "ref_id": "HC-TEST",
        },
        "provenance_level": "claim",
    })
    return reg


def _final_overlay() -> CurationOverlay:
    """The default rules (D1B cap-rule + D2B cascade are built-in, keyless) plus the
    synthetic interim-spec-dup mapping so ``SPEC.DUP`` exercises Decision 3B."""
    return CurationOverlay(promote_interim_spec_dup={"SPEC.DUP": "SPEC.OK"})


def _final_outcomes() -> dict[str, Any]:
    result = convert_registry(_final_registry(), overlay=_final_overlay())
    return {o.fact_id: o for o in result.outcomes}


def test_promoted_capability_ids_selects_claim_with_evidence_and_verified() -> None:
    """The promoted-capability set (which drives the cascade) is exactly the caps a
    decision promotes: claim-with-evidence (D1B) + already-verified — never a claim
    that lacks an evidence reference."""
    overlay = _final_overlay()
    caps = _final_registry()["capabilities"]["capabilities"]
    assert overlay.promoted_capability_ids(caps) == frozenset({"HC-TEST", "HC-VERIFIED"})


def test_decision1B_capability_claim_with_evidence_is_soft() -> None:
    """Decision 1B (RULE): a capabilities claim with a non-empty evidence reference
    is promoted to soft-ready (approved_internal, never masquerading verified) with
    the double-check caveat and a source note built from the REAL evidence ref."""
    reg = _final_registry()
    base = {o.fact_id: o for o in convert_registry(reg).outcomes}["HC-TEST"]
    assert base.confidence_tier == "claim"  # untouched without the overlay
    ov = _final_outcomes()["HC-TEST"]
    assert ov.status == "ready"
    assert ov.confidence_tier == "soft"
    assert ov.v2_provenance == "approved_internal"
    assert ov.needs_double_check is True
    assert ov.source_note is not None
    assert "evidence: brochure XPO26" in ov.source_note  # grounded on the real ref
    ready = convert_registry(reg, overlay=_final_overlay()).ready
    rec = next(r for r in ready if r.fact_id == "HC-TEST")
    assert rec.record["value"]["confidence_signal"]["curation"] == {
        "decision": "D1B-capability-claim-promoted",
        "origin_provenance": "claim",
    }


def test_decision1B_capability_without_evidence_stays_claim() -> None:
    """A capabilities claim with NO evidence reference is NOT promoted — it stays a
    claim (never fabricated into soft)."""
    outcomes = _final_outcomes()
    assert outcomes["HC-NOEV"].confidence_tier == "claim"
    assert outcomes["HC-NOEV"].status == "needs_curation"
    # a verified capability is soft via the native path (unchanged).
    assert outcomes["HC-VERIFIED"].confidence_tier == "soft"


def test_decision2B_cascade_promotes_kernel_ref_pointing_to_promoted_cap() -> None:
    """Decision 2B: a curate kernel_ref (provenance_missing) whose kernel_ref names a
    now-promoted capability inherits soft + caveat, its note citing the cap."""
    reg = _final_registry()
    base = {o.fact_id: o for o in convert_registry(reg).outcomes}["L3R.CASCADE"]
    assert base.status == "needs_curation" and base.confidence_tier == "curate"
    ov = _final_outcomes()["L3R.CASCADE"]
    assert ov.status == "ready"
    assert ov.confidence_tier == "soft"
    assert ov.v2_provenance == "approved_internal"
    assert ov.needs_double_check is True
    assert ov.source_note is not None
    assert "cascade-from promoted capability: HC-TEST + RENAME-01" in ov.source_note


def test_decision2B_cascade_does_not_fire_for_unpromoted_cap() -> None:
    """The cascade is a genuine dependency: a kernel_ref naming a cap that is NOT
    promoted (claim without evidence) stays curate — nothing is fabricated."""
    ov = _final_outcomes()["L3R.NOCASCADE"]
    assert ov.status == "needs_curation"
    assert ov.confidence_tier == "curate"
    assert ov.primary_gap == "provenance_missing"


def test_decision3B_interim_spec_duplicate_of_verified_is_promoted() -> None:
    """Decision 3B: an interim spec (INT, no raw_text) that duplicates an already
    VERIFIED spec is promoted to soft + caveat, its note naming the verified spec;
    the 7 other interim specs are unaffected (they stay claim)."""
    # Audit the shipped exception set: exactly the MTOW HC-001 matrix figure, mapped
    # to the verified spec it duplicates -- no drift.
    assert PROMOTE_INTERIM_SPEC_DUP == {"SPEC.HERA.MTOW.HC001": "SPEC.HERA.MTOW"}
    reg = _final_registry()
    base = {o.fact_id: o for o in convert_registry(reg).outcomes}["SPEC.DUP"]
    assert base.confidence_tier == "claim"  # untouched without the overlay
    ov = _final_outcomes()["SPEC.DUP"]
    assert ov.status == "ready"
    assert ov.confidence_tier == "soft"
    assert ov.v2_provenance == "approved_internal"
    assert ov.needs_double_check is True
    assert ov.source_note is not None
    assert "duplicates verified spec: SPEC.OK" in ov.source_note
    # a non-duplicate interim spec (not in the mapping) stays claim.
    assert _final_outcomes()["SPEC.CLAIM_NOSPAN"].confidence_tier == "claim"


def test_final_wave_emitted_packages_pass_the_real_gate(tmp_path: Path) -> None:
    """Every wave-2 promoted package (cap softs, cascade softs, interim-dup soft)
    still PASSES the real publish gate — approved_internal without evidence is valid
    and none masquerades as verified."""
    result = convert_registry(_final_registry(), overlay=_final_overlay())
    staged = emit_packages(result, tmp_path)
    assert "rtr.capabilities" in staged
    parser = PackageParser(tmp_path)
    for source_key, staging_name in staged.items():
        parsed = parser.parse(staging_name)
        report = validate_package(parsed, now=NOW, allow_claim_as_approved=False)
        assert report.valid, (source_key, [f.code for f in report.findings])


def test_final_wave_is_byte_deterministic(tmp_path: Path) -> None:
    """The full wave-2 conversion + emission is byte-for-byte reproducible."""
    reg = _final_registry()
    staged_a = emit_packages(convert_registry(reg, overlay=_final_overlay()), tmp_path / "a")
    staged_b = emit_packages(convert_registry(reg, overlay=_final_overlay()), tmp_path / "b")
    assert staged_a == staged_b
    for name in staged_a.values():
        for member in ("manifest.json", "records.jsonl", "source_hashes.json",
                       "publish_attestation.json"):
            a = (tmp_path / "a" / name / member).read_bytes()
            b = (tmp_path / "b" / name / member).read_bytes()
            assert a == b


def test_final_wave_does_not_mutate_the_kernel_snapshot() -> None:
    """DRY-RUN discipline: the wave-2 rules never modify the input registry — the
    capability claim, the kernel_ref and the interim spec are untouched on the
    source dicts (transforms live only on the emitted copies)."""
    reg = _final_registry()
    before = copy.deepcopy(reg)
    convert_registry(reg, overlay=_final_overlay())
    assert reg == before
    cap = next(c for c in reg["capabilities"]["capabilities"] if c["id"] == "HC-TEST")
    assert cap["provenance_level"] == "claim"  # untouched on the snapshot


def test_final_disposition_is_total_and_reasoned() -> None:
    """The classifier that proves nothing is in limbo is TOTAL: every confidence
    tier maps to a terminal bucket with a decision + one-line reason, and the
    held/derived/irreducible buckets carry the right decision for the right file."""
    strict = final_disposition(
        file_key="specs", fact_id="SPEC.HERA.MTOW", confidence_tier="strict",
        kernel_provenance="verified_primary", primary_gap=None,
    )
    assert strict[0] == READY_STRICT
    strategic = final_disposition(
        file_key="l3_facts", fact_id="L3R.2.023", confidence_tier="strategic",
        kernel_provenance="approved_internal", primary_gap=None,
    )
    assert strategic[0] == READY_STRATEGIC
    cap_soft = final_disposition(
        file_key="capabilities", fact_id="HC-001", confidence_tier="soft",
        kernel_provenance="approved_internal", primary_gap=None,
    )
    assert cap_soft[0] == READY_SOFT and cap_soft[1] == "D1B-capability-claim-promoted"
    dup_soft = final_disposition(
        file_key="specs", fact_id="SPEC.HERA.MTOW.HC001", confidence_tier="soft",
        kernel_provenance="approved_internal", primary_gap=None,
    )
    assert dup_soft[0] == READY_SOFT and "duplicate" in dup_soft[1]
    # holds: boms/prices claim -> cost/price hold; specs claim -> interim-spec hold
    assert final_disposition(
        file_key="boms", fact_id="BOM.X", confidence_tier="claim",
        kernel_provenance="claim", primary_gap=None,
    )[0] == HELD_CLAIM
    assert final_disposition(
        file_key="specs", fact_id="SPEC.HERA.EDGE_AI.TOPS", confidence_tier="claim",
        kernel_provenance="claim", primary_gap=None,
    )[1] == "D3-hold-interim-spec"
    # derived: claim derived AND curate derived -> derived-held
    assert final_disposition(
        file_key="derived_costs", fact_id="DERIVED.ALMO.MARGIN.HERA_VN",
        confidence_tier="claim", kernel_provenance="claim", primary_gap=None,
    )[0] == HELD_DERIVED
    dv_curate = final_disposition(
        file_key="derived_costs", fact_id="DERIVED.HERA.BUNDLE_GAP_US",
        confidence_tier="curate", kernel_provenance="flagged", primary_gap="missing_source",
    )
    assert dv_curate[0] == HELD_DERIVED and "source" in dv_curate[2]
    # irreducible: a non-derived curate names its missing field
    irr = final_disposition(
        file_key="prices", fact_id="PRICE.VEGA.MSRP.VN", confidence_tier="curate",
        kernel_provenance="placeholder", primary_gap="provenance_unmappable",
    )
    assert irr[0] == IRREDUCIBLE
    assert IRREDUCIBLE_GAP["PRICE.VEGA.MSRP.VN"] in irr[2]


def test_final_disposition_reconciles_the_real_run_to_259() -> None:
    """Against the REAL curated conversion, every one of the 259 outcomes lands in a
    terminal bucket and the totals reconcile to 259 (219 ready / 30 claim-held /
    6 derived-held / excluded 1 / irreducible 3) — nothing is in limbo.  Skips
    cleanly when the read-only kernel snapshot is absent, so CI stays hermetic."""
    import pytest
    from migrate.kernel_adapter import load_registry

    kernel_root = Path("/home/claude/kernel-real/registry")
    if not kernel_root.exists():
        pytest.skip("real kernel snapshot not present (hermetic CI)")

    result = convert_registry(load_registry(kernel_root), overlay=CurationOverlay())
    buckets: dict[str, int] = {}
    for o in result.outcomes:
        bucket, _ref, _reason = final_disposition(
            file_key=o.file, fact_id=o.fact_id, confidence_tier=o.confidence_tier,
            kernel_provenance=o.kernel_provenance, primary_gap=o.primary_gap,
        )
        buckets[bucket] = buckets.get(bucket, 0) + 1
    assert sum(buckets.values()) == 259
    ready = (
        buckets.get(READY_STRICT, 0)
        + buckets.get(READY_SOFT, 0)
        + buckets.get(READY_STRATEGIC, 0)
    )
    assert ready == 219
    assert buckets.get(HELD_CLAIM, 0) == 30
    assert buckets.get(HELD_DERIVED, 0) == 6
    assert buckets.get(IRREDUCIBLE, 0) == 3
    assert buckets.get("excluded", 0) == 1
