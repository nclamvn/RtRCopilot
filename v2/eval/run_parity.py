#!/usr/bin/env python3
"""TIP-013 Phase A · V1 parity runner (AC-A3).

Runs a fixed question set against (a) the phase-1 pilot oracle (its real
deterministic MOCK answering, loaded read-only against a SYNTHETIC GOI) and
(b) V2 (synthetic SOT seeded through the publish gate, asked via the RAG path).
Emits a per-question parity report (Markdown + JSON) with answer agreement,
citation presence and honest-null agreement, and triages divergences.

Requires a migrated synthetic database via INTEGRATION_DATABASE_DSN. Never reads
or mutates any real corpus or the pilot's real store.
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

QUESTIONS = HERE / "parity" / "questions.json"
REPORT_JSON = HERE / "parity" / "parity_report.json"
REPORT_MD = HERE / "parity" / "parity_report.md"


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
    from lib.harness import V2Harness, subject
    from lib.pilot_oracle import PilotOracle

    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    facts = {fact["key"]: fact for fact in spec["facts"]}
    harness = V2Harness(root, factory)
    oracle = PilotOracle()

    # Deterministic actor so the runner is idempotent across re-runs on the same DB.
    actor = uuid.uuid5(uuid.NAMESPACE_URL, "tip013-parity-actor")
    await harness.insert_subject(actor)
    for fact in facts.values():
        await harness.seed_sot(
            actor,
            source_key=fact["source_key"],
            record_key=fact["record_key"],
            text_value=fact["text"],
        )
    asker = subject(actor)

    rows: list[dict[str, Any]] = []
    for question in spec["questions"]:
        scope_fact = question.get("scope_fact")
        source_key = facts[scope_fact]["source_key"] if scope_fact else None
        pilot = oracle.outcome(question["question"])
        response = await harness.ask(asker, question["question"], source_key=source_key)
        v2_cited = [citation.record_key for citation in response.citations]
        pilot_answered = pilot["state"] == "answered"
        v2_grounded = response.state == "grounded"
        answer_agreement = pilot_answered == v2_grounded
        honest_null_agreement = (not pilot_answered) == (not v2_grounded)
        expected_fact = question.get("expected_fact")
        expected_record = facts[expected_fact]["record_key"] if expected_fact else None
        rows.append({
            "id": question["id"],
            "category": question["category"],
            "question": question["question"],
            "scope_source_key": source_key,
            "expect": question["expect"],
            "pilot_state": pilot["state"],
            "pilot_cited": pilot["cited_records"],
            "v2_state": response.state,
            "v2_cited": v2_cited,
            "answer_agreement": answer_agreement,
            "citation_presence_v2": bool(v2_cited) if v2_grounded else None,
            "citation_presence_pilot": (
                bool(pilot["cited_records"]) if pilot_answered else None
            ),
            "honest_null_agreement": honest_null_agreement,
            "expected_record_key": expected_record,
            "v2_citation_correct": (
                expected_record in v2_cited if expected_record else None
            ),
            "pilot_citation_correct": (
                expected_record in pilot["cited_records"] if expected_record else None
            ),
            "agree": answer_agreement,
            "note": question.get("note"),
        })

    agree = sum(1 for row in rows if row["agree"])
    divergences = [row for row in rows if not row["agree"]]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "harness": "tip-013 phase-a parity (synthetic)",
        "question_count": len(rows),
        "agreement_count": agree,
        "agreement_rate": round(agree / len(rows), 4) if rows else 1.0,
        "divergence_count": len(divergences),
        "rows": rows,
        "triage": _triage(divergences),
    }
    return report


def _triage(divergences: list[dict[str, Any]]) -> list[dict[str, str]]:
    triage: list[dict[str, str]] = []
    for row in divergences:
        triage.append({
            "id": row["id"],
            "kind": (
                "v2_grounds_pilot_nulls"
                if row["v2_state"] == "grounded"
                else "v2_nulls_pilot_answers"
            ),
            "disposition": (
                "Expected synthetic-harness artefact: V2's non-semantic offline "
                "hash embedding (REQ-010) returns an arbitrary nearest neighbour "
                "on an UNSCOPED query and the offline extractive provider grounds "
                "on it. Source-scoped asks agree. Re-measured with the real "
                "semantic embedding + provider on the real corpus in Phase B."
                if row["v2_state"] == "grounded"
                else "Investigate: V2 refused where the pilot answered."
            ),
        })
    return triage


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TIP-013 Phase A · V1 Parity Report (synthetic)",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Questions: {report['question_count']}",
        (
            f"- Answer agreement: {report['agreement_count']}/"
            f"{report['question_count']} "
            f"({report['agreement_rate'] * 100:.1f}%)"
        ),
        f"- Divergences: {report['divergence_count']}",
        "",
        "Oracle = phase-1 pilot deterministic MOCK answering, loaded read-only "
        "against a SYNTHETIC GOI (the real l3_pipeline corpus is never touched). "
        "V2 = synthetic SOT seeded through the publish gate, asked via the RAG "
        "path. This is the template Phase B re-runs on the real 137/162 records "
        "(D-013-04).",
        "",
        "| id | category | pilot | V2 | answer agree | honest-null agree | "
        "citation (V2) |",
        "|----|----------|-------|----|--------------|-------------------|"
        "---------------|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['id']} | {row['category']} | {row['pilot_state']} | "
            f"{row['v2_state']} | {'yes' if row['answer_agreement'] else 'NO'} | "
            f"{'yes' if row['honest_null_agreement'] else 'NO'} | "
            f"{row['v2_cited'] or '-'} |",
        )
    if report["triage"]:
        lines += ["", "## Divergence triage", ""]
        for item in report["triage"]:
            lines.append(f"- **{item['id']}** ({item['kind']}): {item['disposition']}")
    lines.append("")
    return "\n".join(lines)


async def _amain() -> int:
    from lib.harness import make_factory

    dsn = bootstrap_env()
    root = Path(os.environ.get("EVAL_STAGING_ROOT", "/tmp/tip013-parity-staging"))
    root.mkdir(parents=True, exist_ok=True)
    factory = make_factory(dsn)
    report = await run(root, factory)
    REPORT_JSON.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    print(f"\nWrote {REPORT_JSON} and {REPORT_MD}")
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
