#!/usr/bin/env python3
"""Read-only enterprise query-intelligence gate over registry + active corpus."""

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

from rtr_copilot.rag.models import SearchFilters  # noqa: E402
from rtr_copilot.rag.ontology import load_ontology  # noqa: E402
from rtr_copilot.rag.query_understanding import (  # noqa: E402
    OfflineRewriter,
    plan_query,
)
from rtr_copilot.rag.retrieval import RetrievalService  # noqa: E402
from rtr_copilot.repositories.identity_postgres import (  # noqa: E402
    PostgresSubjectRepository,
)

CASES = HERE / "quality" / "tip0247_enterprise_query.json"


async def evaluate(subject_id: uuid.UUID) -> dict[str, Any]:
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    ontology = load_ontology()
    subject = await PostgresSubjectRepository().get_by_user_id(subject_id)
    if subject is None:
        raise SystemExit(f"subject not found: {subject_id}")
    retrieval = RetrievalService()
    rows: list[dict[str, Any]] = []

    async def retrieve(question: str) -> tuple[Any, list[str]]:
        plan = await plan_query(
            question,
            OfflineRewriter(),
            registry=ontology,
        )
        hits = (
            await retrieval.search(
                subject,
                plan.retrieval_query,
                filters=SearchFilters(),
                request_id="tip0247-" + uuid.uuid4().hex,
                top_k=12,
                query_entities=plan.entities,
                query_intent=plan.intent,
            )
            if plan.resolution_state != "clarification_required"
            else []
        )
        return plan, [hit.citation.record_key for hit in hits]

    for case in spec["known_definitions"]:
        plan, record_keys = await retrieve(case["question"])
        passed = (
            plan.resolution_state == "resolved"
            and plan.entities == (case["entity"],)
            and bool(record_keys)
            and record_keys[0] in case["expected_top"]
        )
        rows.append({
            "kind": "known_definition",
            "question": case["question"],
            "state": plan.resolution_state,
            "entity_count": len(plan.entities),
            "top": record_keys[0] if record_keys else None,
            "passed": passed,
        })

    # Registry-wide invariant: every approved alias must resolve to exactly the
    # same stable entity id as its canonical name. No corpus content is needed.
    for entity in ontology.entities:
        canonical_plan = await plan_query(
            entity.canonical_name,
            OfflineRewriter(),
            registry=ontology,
        )
        for alias in entity.aliases:
            alias_plan = await plan_query(alias, OfflineRewriter(), registry=ontology)
            passed = (
                canonical_plan.resolution_state == "resolved"
                and alias_plan.resolution_state == "resolved"
                and alias_plan.entity_ids == canonical_plan.entity_ids == (entity.entity_id,)
            )
            rows.append({
                "kind": "alias_invariance",
                "entity_id_digest": __import__("hashlib").sha256(
                    entity.entity_id.encode(),
                ).hexdigest(),
                "alias_digest": __import__("hashlib").sha256(alias.encode()).hexdigest(),
                "passed": passed,
            })

    for case in spec["ambiguous"]:
        plan, record_keys = await retrieve(case["question"])
        candidates = sorted(item.canonical_name for item in plan.candidates)
        rows.append({
            "kind": "ambiguity",
            "question": case["question"],
            "state": plan.resolution_state,
            "candidate_count": len(candidates),
            "retrieved_count": len(record_keys),
            "passed": (
                plan.resolution_state == "clarification_required"
                and candidates == sorted(case["expected_candidates"])
                and not record_keys
            ),
        })

    for case in spec["unknown"]:
        plan, record_keys = await retrieve(case["question"])
        rows.append({
            "kind": "unknown",
            "question": case["question"],
            "state": plan.resolution_state,
            "top": record_keys[0] if record_keys else None,
            "passed": plan.resolution_state == "open" and not record_keys,
        })

    passed = sum(bool(row["passed"]) for row in rows)
    return {
        "suite": "TIP-024.7 enterprise query intelligence",
        "ontology_digest": ontology.digest,
        "cases": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "false_grounded_risk_count": len(rows) - passed,
        "results": rows,
    }


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject-id", type=uuid.UUID, required=True)
    args = parser.parse_args()
    result = await evaluate(args.subject_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
