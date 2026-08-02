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
    assert ok.gaps == ()
    assert ok.v2_provenance == "verified_primary"
    assert ok.classification == "internal"
    assert ok.tier == "staff"


def test_ready_package_passes_the_real_gate(tmp_path: Path) -> None:
    result = convert_registry(_registry())
    staged = emit_packages(result, tmp_path)
    assert set(staged) == {"rtr.specs"}
    parser = PackageParser(tmp_path)
    parsed = parser.parse(staged["rtr.specs"])
    report = validate_package(parsed, now=NOW, allow_claim_as_approved=False)
    assert report.valid, [finding.code for finding in report.findings]
    assert report.record_count == 1  # only SPEC.OK is ready
    assert {record.record_key for record in parsed.records} == {"SPEC.OK"}


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
    assert outcomes["BOM.X"].tier == "leader"
    assert outcomes["BOM.X"].classification == "restricted"
    assert outcomes["BOM.X"].status == "needs_curation"  # verified but no span


def test_evidence_and_record_sha_are_stable() -> None:
    first = convert_registry(_registry()).ready
    second = convert_registry(_registry()).ready
    assert [item.fact_id for item in first] == [item.fact_id for item in second] == [
        "SPEC.OK",
    ]
    assert first[0].evidence["evidence_sha256"] == second[0].evidence["evidence_sha256"]
    assert first[0].record["content_sha256"] == second[0].record["content_sha256"]
    # a real, non-zero digest was computed (not the placeholder)
    assert first[0].record["content_sha256"] != "0" * 64
    assert first[0].evidence["evidence_sha256"] != "0" * 64


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
