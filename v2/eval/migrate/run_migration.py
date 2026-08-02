#!/usr/bin/env python3
"""TIP-013 Phase B (D-013-05 kickoff) · migration DRESS REHEARSAL runner (DRY-RUN).

Reads the READ-ONLY real kernel registry snapshot, converts every fact to a V2
SOT package record with the conservative adapter, emits the ready records as
staged packages, and drives those packages through the EXACT dry-run path of the
onboarding tool (``OnboardBatch.validate_all`` -> ``PackageParser`` +
``validate_package``, the pure no-DB validators).  It then writes a per-fact
readiness JSON and prints a human summary.

There is NO ``--apply`` here and no code path that activates anything, writes to a
production database, or contacts Postgres/Redis/S3.  The tool refuses to do
anything but validate.  This is a de-risking measurement, not a migration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from migrate.curation_overlay import CurationOverlay  # noqa: E402
from migrate.kernel_adapter import (  # noqa: E402
    CURATOR_ID,
    ConversionResult,
    convert_registry,
    emit_packages,
    load_registry,
    summarize,
)

DEFAULT_KERNEL_ROOT = Path("/home/claude/kernel-real/registry")
DEFAULT_OUT_ROOT = Path("/tmp/rtr-migration-dryrun/staging")
DRY_RUN_NOW = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)


def _dry_run_settings(out_root: Path) -> Any:
    """A Settings object pointed at the emitted staging dir.

    All connection fields are placeholders: the dry-run validators never open a
    socket.  Built via ``model_validate`` so no real ``.env``/environment is read.
    """
    from rtr_copilot.config import Settings

    raw: dict[str, Any] = {
        "postgres_dsn": "postgresql://dryrun:dryrun@127.0.0.1:5432/dryrun",
        "redis_url": "redis://127.0.0.1:6380/0",
        "s3_endpoint": "http://127.0.0.1:9002",
        "s3_access_key": "dryrun-access",
        "s3_secret_key": "dryrun-secret-key",
        "s3_bucket": "rtr-dryrun",
        "sot_staging_root": str(out_root),
        "sot_allow_claim_as_approved": False,
    }
    return Settings.model_validate(raw)


def run_dry_run(
    result: ConversionResult,
    staged: dict[str, str],
    out_root: Path,
) -> dict[str, Any]:
    """Drive the emitted packages through the tool's dry-run validators.

    Returns the tool's per-package plan AND per-record gate findings, and
    reconciles any gate rejection back onto the affected fact (a fact the adapter
    called ``ready`` that the gate rejects is downgraded to ``rejected`` with the
    typed code -- honesty over an inflated ready count)."""
    from rtr_copilot.commands.onboard_batch import BatchManifest, OnboardBatch, SotItem
    from rtr_copilot.sot.package import PackageParser, validate_package

    settings = _dry_run_settings(out_root)
    manifest = BatchManifest(
        batch_id="tip013-phaseB-migration-dryrun",
        curator_subject_id=CURATOR_ID,
        sot_items=[
            SotItem(staging_name=staged[source_key], expected_source_key=source_key)
            for source_key in sorted(staged)
        ],
    )
    onboard = OnboardBatch(settings, clock=lambda: DRY_RUN_NOW)
    plan = onboard.validate_all(manifest)

    parser = PackageParser(out_root)
    rejected: dict[str, str] = {}
    per_package: list[dict[str, Any]] = []
    for source_key in sorted(staged):
        staging_name = staged[source_key]
        parsed = parser.parse(staging_name)
        report = validate_package(parsed, now=DRY_RUN_NOW, allow_claim_as_approved=False)
        per_package.append(
            {
                "source_key": source_key,
                "staging_name": staging_name,
                "records": report.record_count,
                "evidence": report.evidence_count,
                "valid": report.valid,
                "findings": [
                    {"code": finding.code, "subject": finding.subject}
                    for finding in report.findings
                ],
                "deterministic_checksum": report.deterministic_checksum,
            },
        )
        for finding in report.findings:
            rejected[finding.subject] = finding.code

    # Reconcile gate rejections back onto the fact outcomes.
    reconciled: list[dict[str, Any]] = []
    for outcome in result.outcomes:
        item = outcome.to_json()
        if outcome.status == "ready" and outcome.fact_id in rejected:
            item["status"] = "rejected"
            item["reject_code"] = rejected[outcome.fact_id]
        reconciled.append(item)

    return {
        "tool_plan": [item.model_dump(mode="json") for item in plan],
        "per_package_gate": per_package,
        "reconciled_outcomes": reconciled,
    }


def _final_status_totals(reconciled: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for item in reconciled:
        totals[item["status"]] = totals.get(item["status"], 0) + 1
    return dict(sorted(totals.items()))


_TIER_ORDER = ("strict", "soft", "strategic", "curate", "claim", "excluded")
_READY_TIERS = ("strict", "soft", "strategic")


def _final_tier_totals(reconciled: list[dict[str, Any]]) -> dict[str, int]:
    """Confidence-tier split (strict/soft/strategic/curate/claim/excluded),
    gate-reconciled: a ready fact the gate rejected is counted under ``rejected``
    instead of its tier."""
    totals: dict[str, int] = {}
    for item in reconciled:
        key = "rejected" if item["status"] == "rejected" else item["confidence_tier"]
        totals[key] = totals.get(key, 0) + 1
    ordered = {tier: totals[tier] for tier in _TIER_ORDER if tier in totals}
    if "rejected" in totals:
        ordered["rejected"] = totals["rejected"]
    return ordered


def build_report(
    kernel_root: Path,
    out_root: Path,
    *,
    overlay: CurationOverlay | None = None,
    signing_secret: str | None = None,
) -> dict[str, Any]:
    registry = load_registry(kernel_root)
    result = convert_registry(registry, overlay=overlay)
    staged = emit_packages(result, out_root, signing_secret=signing_secret)
    summary = summarize(result)
    dry_run = run_dry_run(result, staged, out_root)
    return {
        "generated_by": "eval/migrate/run_migration.py",
        "mode": "DRY_RUN_ONLY",
        "curation_overlay": "applied" if overlay is not None else "none",
        "kernel_root": str(kernel_root),
        "staging_root": str(out_root),
        "curator_subject_id": str(CURATOR_ID),
        "staged_packages": staged,
        "adapter_summary": summary,
        "dry_run": {
            "tool_plan": dry_run["tool_plan"],
            "per_package_gate": dry_run["per_package_gate"],
        },
        "final_status_totals": _final_status_totals(dry_run["reconciled_outcomes"]),
        "final_tier_totals": _final_tier_totals(dry_run["reconciled_outcomes"]),
        "outcomes": dry_run["reconciled_outcomes"],
    }


def build_manifest(staged: dict[str, str]) -> dict[str, Any]:
    """Build the ``onboard_batch.BatchManifest`` JSON for the emitted packages.

    One SOT item per source key, each pinned to its ``expected_source_key`` so
    the onboarding tool fail-closes on any staging/source-key drift.  The curator
    is the deterministic migration curator the attestations were signed for; the
    real ``--apply`` binds this same id to the seeded curator subject and the
    publish gate independently re-verifies the signature."""
    return {
        "batch_id": "tip013b-curated-real-kernel",
        "curator_subject_id": str(CURATOR_ID),
        "sot_items": [
            {"staging_name": staged[source_key], "expected_source_key": source_key}
            for source_key in sorted(staged)
        ],
    }


def _print_summary(report: dict[str, Any]) -> None:
    summary = report["adapter_summary"]
    print("=" * 72)
    print("TIP-013 Phase B · kernel -> V2 SOT migration DRY-RUN (nothing activated)")
    print("=" * 72)
    print(f"kernel_root : {report['kernel_root']}")
    print(f"staging_root: {report['staging_root']}")
    print(f"total facts : {summary['total_facts']}")
    print(f"curation    : {report['curation_overlay']}")
    print(f"final status: {report['final_status_totals']}")
    tiers = report["final_tier_totals"]
    ready = sum(tiers.get(tier, 0) for tier in _READY_TIERS)
    print(f"final tiers : {tiers}  (strict+soft+strategic = {ready} ready)")
    print("by file (confidence tier):")
    for file_key, counts in summary["by_file_tier"].items():
        print(f"  {file_key:<14} {counts}")
    print(f"classification split (tier): {summary['classification_split']}")
    print(f"kernel provenance split    : {summary['kernel_provenance_split']}")
    print(f"curate gap histogram       : {summary['curate_gap_histogram']}")
    print(f"source-hash coverage       : {summary['source_hash_coverage']}")
    print("dry-run per-package gate:")
    for pkg in report["dry_run"]["per_package_gate"]:
        print(
            f"  {pkg['source_key']:<14} records={pkg['records']} "
            f"valid={pkg['valid']} findings={len(pkg['findings'])}",
        )
    print("=" * 72)
    print("NOTHING WAS ACTIVATED. No --apply, no DB writes.")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_migration",
        description=(
            "Kernel -> V2 SOT migration dress rehearsal (DRY-RUN ONLY; there is no "
            "--apply and nothing is ever activated)."
        ),
    )
    parser.add_argument(
        "--kernel-root",
        type=Path,
        default=DEFAULT_KERNEL_ROOT,
        help="read-only kernel registry snapshot dir",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="output staging dir for emitted packages",
    )
    parser.add_argument("--report-json", type=Path, help="write the readiness JSON here")
    parser.add_argument(
        "--curated",
        action="store_true",
        help=(
            "apply the Homeowner's 4 approved TIP-013B curation decisions as a "
            "DRY-RUN overlay (unit fix, promotions, strategic tier, exclusion); the "
            "read-only kernel snapshot is NOT modified and nothing is activated"
        ),
    )
    parser.add_argument(
        "--emit",
        action="store_true",
        help=(
            "EMIT the ready packages signed with the REAL SOT_SIGNING_SECRET (from "
            "the env var named by --signing-secret-env) and write the onboarding "
            "manifest to --manifest-out.  This still does NOT activate anything -- "
            "it only produces the signed on-disk packages the curator-gated "
            "onboarding tool (scripts/onboard-batch.sh --apply --approve) consumes"
        ),
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        help="write the onboarding BatchManifest JSON here (implies --emit)",
    )
    parser.add_argument(
        "--signing-secret-env",
        default="SOT_SIGNING_SECRET",
        help="env var holding the real signing secret for --emit (>=32 chars)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import os

    args = _build_arg_parser().parse_args(argv)
    overlay = CurationOverlay() if args.curated else None
    emit = bool(args.emit or args.manifest_out)
    signing_secret: str | None = None
    if emit:
        signing_secret = os.environ.get(args.signing_secret_env, "")
        if not signing_secret or len(signing_secret) < 32:
            print(
                f"ERROR: --emit requires env {args.signing_secret_env} set to a "
                "real signing secret of at least 32 characters (the SAME secret "
                "the running api uses); refusing to emit unverifiable packages.",
                file=sys.stderr,
            )
            return 2
    report = build_report(
        args.kernel_root, args.out, overlay=overlay, signing_secret=signing_secret,
    )
    if emit:
        report["mode"] = "EMIT_SIGNED_PACKAGES"
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if emit and args.manifest_out:
        manifest = build_manifest(report["staged_packages"])
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _print_summary(report)
    if emit:
        print("=" * 72)
        print("EMITTED SIGNED PACKAGES (real SOT_SIGNING_SECRET). Nothing activated")
        print("yet — run scripts/onboard-batch.sh --apply --approve to activate.")
        if args.manifest_out:
            print(f"manifest: {args.manifest_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
