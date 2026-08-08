#!/usr/bin/env python3
"""Run TIP-024.6's read-only adversarial gate against the active SOT corpus.

The command performs retrieval only: it creates no conversations, messages,
answer runs or gaps. It exits non-zero if a target record is not ranked first,
if a known cross-product distractor survives, or if an unknown product retrieves
evidence. A real subject id is required so production ACLs remain in force.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "apps" / "backend"
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))

from rtr_copilot.auth.models import Subject  # noqa: E402
from rtr_copilot.rag.models import SearchFilters  # noqa: E402
from rtr_copilot.rag.retrieval import RetrievalService  # noqa: E402
from rtr_copilot.repositories.identity_postgres import (  # noqa: E402
    PostgresSubjectRepository,
)

CASES = HERE / "quality" / "tip0246_adversarial.json"


async def load_subject(subject_id: uuid.UUID) -> Subject:
    subject = await PostgresSubjectRepository().get_by_user_id(subject_id)
    if subject is None:
        raise SystemExit(f"subject not found: {subject_id}")
    return subject


async def evaluate(subject_id: uuid.UUID) -> dict[str, Any]:
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    subject = await load_subject(subject_id)
    retrieval = RetrievalService()
    rows: list[dict[str, Any]] = []
    for case in spec["cases"]:
        hits = await retrieval.search(
            subject,
            case["question"],
            filters=SearchFilters(),
            request_id=f"tip0246-eval-{case['id'].lower()}",
            top_k=12,
        )
        record_keys = [hit.citation.record_key for hit in hits]
        expected_empty = bool(case.get("expected_empty"))
        top_ok = (
            not record_keys
            if expected_empty
            else bool(record_keys and record_keys[0] in case["expected_top"])
        )
        forbidden_found = sorted(set(record_keys) & set(case["forbidden"]))
        rows.append({
            "id": case["id"],
            "question": case["question"],
            "top": record_keys[0] if record_keys else None,
            "record_keys": record_keys,
            "top_ok": top_ok,
            "forbidden_found": forbidden_found,
            "passed": top_ok and not forbidden_found,
        })
    passed = sum(bool(row["passed"]) for row in rows)
    return {
        "suite": "TIP-024.6 active-corpus adversarial retrieval",
        "subject_id": str(subject_id),
        "passed": passed,
        "total": len(rows),
        "false_grounded_risk_count": len(rows) - passed,
        "cases": rows,
    }


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject-id", type=uuid.UUID, required=True)
    args = parser.parse_args()
    result = await evaluate(args.subject_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["false_grounded_risk_count"] == 0 else 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
