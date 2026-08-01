#!/usr/bin/env python3
"""TIP-013 Phase A · representative evaluation runner + scorer (AC-A4).

Seeds each synthetic eval case through the REAL publish/import gates, asks V2,
and scores the run with the pure scorer: grounded-rate, honest-null-quality,
leak-count (must be 0) and citation-accuracy. Writes a committed baseline result.

Covers fact-lookup, honest-null, cross-version/freshness, ACL-restricted (V2 MUST
refuse — a leak is P0), verification gating, and research-vs-SOT labelling.
Real-corpus re-baseline is Phase B (D-013-05). Requires INTEGRATION_DATABASE_DSN.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

EVAL_SET = HERE / "quality" / "eval_set.json"
RESULT_JSON = HERE / "quality" / "baseline_result.json"
RESULT_MD = HERE / "quality" / "baseline_result.md"


def bootstrap_env() -> str:
    dsn = os.environ.get("INTEGRATION_DATABASE_DSN")
    if not dsn:
        raise SystemExit(
            "INTEGRATION_DATABASE_DSN is required (a migrated SYNTHETIC database).",
        )
    os.environ.setdefault("POSTGRES_DSN", dsn)
    os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/0")
    os.environ.setdefault("S3_ENDPOINT", "http://127.0.0.1:9002")
    os.environ.setdefault("S3_ACCESS_KEY", "local")
    os.environ.setdefault("S3_SECRET_KEY", "local-secret")
    os.environ.setdefault("S3_BUCKET", "rtr-test")
    return dsn


async def run(root: Path, factory: Any) -> dict[str, Any]:
    from lib.harness import Role, V2Harness, subject
    from lib.scoring import CaseResult, score

    spec = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    harness = V2Harness(root, factory)
    # Deterministic owner so the runner is idempotent across re-runs on the same DB.
    owner = uuid.uuid5(uuid.NAMESPACE_URL, "tip013-eval-owner")
    await harness.insert_subject(owner)
    owner_subject = subject(owner)
    curator_subject = subject(owner, Role.CURATOR)

    results: list[CaseResult] = []
    side_checks: list[dict[str, Any]] = []

    for case in spec["cases"]:
        fixture = case["fixture"]
        kind = fixture["kind"]
        asker = owner_subject
        source_key: str | None = None
        require_verified = bool(case.get("require_verified", True))

        if kind == "sot":
            await harness.seed_sot(
                owner,
                source_key=fixture["source_key"],
                record_key=fixture["record_key"],
                text_value=fixture["text"],
                classification=fixture.get("classification", "internal"),
                provenance_level=fixture.get("provenance_level", "approved_internal"),
                verification_state=fixture.get("verification_state", "approved"),
                fact_state=fixture.get("fact_state", "approved"),
            )
            if fixture.get("deny_asker"):
                denied = uuid.uuid5(uuid.NAMESPACE_URL, f"tip013-denied:{fixture['source_key']}")
                await harness.insert_subject(denied)
                await harness.deny_view(fixture["source_key"], denied, owner)
                asker = subject(denied)
            source_key = fixture["source_key"] if case.get("scope") == "self" else None
        elif kind == "sot_versioned":
            await harness.seed_sot(
                owner,
                source_key=fixture["source_key"],
                record_key=fixture["record_key"],
                text_value=fixture["rev1_text"],
            )
            await harness.seed_sot(
                owner,
                source_key=fixture["source_key"],
                record_key=fixture["record_key"],
                text_value=fixture["rev2_text"],
                revision=2,
                ordinal=2,
                supersedes=True,
            )
            source_key = fixture["source_key"] if case.get("scope") == "self" else None
        elif kind == "research":
            research_source = await harness.create_research_source(
                owner,
                stable_key=f"refinery.tip013.{case['id'].lower()}",
            )
            await harness.import_research(
                curator_subject,
                research_source,
                record_key=fixture["record_key"],
                text_value=fixture["text"],
            )
            hits = await harness.research_search(curator_subject, fixture["text"])
            side_checks.append({
                "case_id": case["id"],
                "research_hits": len(hits),
                "all_labeled_research": all(h["zone_label"] == "research" for h in hits),
                "beacon_in_research": any(
                    "RESEARCH-ONLY-BEACON" in h["snippet"] for h in hits
                ),
            })
            # Scope the SOT ask to the research namespace: the SOT index has nothing
            # there, so the research zone can never masquerade as an SOT answer.
            source_key = research_source
        else:  # pragma: no cover - defensive
            raise SystemExit(f"unknown fixture kind: {kind}")

        response = await harness.ask(
            asker,
            case["question"],
            source_key=source_key,
            require_verified=require_verified,
        )
        results.append(CaseResult(
            case_id=case["id"],
            category=case["category"],
            expect=case["expect"],
            got_state=response.state,
            answer_text=response.answer,
            cited_record_keys=[c.record_key for c in response.citations],
            expected_record_key=case.get("expected_record_key"),
            forbidden_texts=case.get("forbidden_texts", []),
        ))

    report = score(results)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "harness": "tip-013 phase-a quality eval (synthetic)",
        "metrics": report.to_dict(),
        "cases": [
            {
                "id": r.case_id,
                "category": r.category,
                "expect": r.expect,
                "got_state": r.got_state,
                "cited_record_keys": r.cited_record_keys,
                "expected_record_key": r.expected_record_key,
                "answer_preview": r.answer_text[:80],
            }
            for r in results
        ],
        "side_checks": side_checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# TIP-013 Phase A · Answer-Quality Baseline (synthetic)",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Grounded rate: {metrics['grounded_rate'] * 100:.1f}% "
        f"({metrics['grounded_expected']} grounded-expected cases)",
        f"- Honest-null quality: {metrics['honest_null_quality'] * 100:.1f}% "
        f"({metrics['null_expected']} null-expected cases)",
        f"- **Leak count: {metrics['leak_count']}** (MUST be 0; any leak is a P0)",
        f"- Citation accuracy: {metrics['citation_accuracy'] * 100:.1f}%",
        f"- Baseline passed: {'YES' if metrics['passed'] else 'NO'}",
        "",
        "Real-corpus re-baseline is Phase B (D-013-05).",
        "",
        "| id | category | expect | got | cited | correct-citation |",
        "|----|----------|--------|-----|-------|------------------|",
    ]
    for case in report["cases"]:
        correct = (
            "-"
            if case["expected_record_key"] is None
            else ("yes" if case["expected_record_key"] in case["cited_record_keys"] else "NO")
        )
        lines.append(
            f"| {case['id']} | {case['category']} | {case['expect']} | "
            f"{case['got_state']} | {case['cited_record_keys'] or '-'} | {correct} |",
        )
    if metrics["leaks"]:
        lines += ["", "## LEAKS (P0)", ""] + [f"- {leak}" for leak in metrics["leaks"]]
    if report["side_checks"]:
        lines += ["", "## Research-zone side checks", ""]
        for check in report["side_checks"]:
            lines.append(
                f"- {check['case_id']}: research_hits={check['research_hits']}, "
                f"all_labeled_research={check['all_labeled_research']}, "
                f"beacon_in_research={check['beacon_in_research']}",
            )
    lines.append("")
    return "\n".join(lines)


async def _amain() -> int:
    from lib.harness import make_factory

    dsn = bootstrap_env()
    root = Path(os.environ.get("EVAL_STAGING_ROOT", "/tmp/tip013-eval-staging"))
    root.mkdir(parents=True, exist_ok=True)
    factory = make_factory(dsn)
    report = await run(root, factory)
    RESULT_JSON.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    RESULT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    print(f"\nWrote {RESULT_JSON} and {RESULT_MD}")
    return 0 if report["metrics"]["leak_count"] == 0 else 1


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
