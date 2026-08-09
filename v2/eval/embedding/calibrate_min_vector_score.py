#!/usr/bin/env python3
"""TIP-014RE · Calibrate ``RAG_MIN_VECTOR_SCORE`` for the active adapter.

Verdict law: the vector-score floor must be chosen from MEASURED score
distributions BEFORE any acceptance campaign, never tuned after seeing
campaign results. This harness embeds every campaign question with the
configured adapter and reports, per case:

* best cosine score against chunks of the expected (oracle) records, and
* best cosine score against every other active chunk (the distractor field),

then prints percentile summaries and a suggested floor: the largest value
that keeps every oracle best-score above the floor, capped below the median
distractor score. The suggestion is advisory — the Homeowner/Contractor
pre-commit the final value in ``.env.demo`` before the campaign.

Read-only; run inside the api container after ``reembed_corpus``:

    docker compose exec api python /app/eval/embedding/calibrate_min_vector_score.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.rag.adapters import OpenAIEmbedding, build_embedding_adapter
from rtr_copilot.rag.relevance import profile_query

CASES = Path(__file__).resolve().parents[1] / "real_world" / "cases.json"


def _oracle_keys(case: dict) -> set[str]:
    keys: set[str] = set()
    for group in case.get("expected_record_groups") or []:
        keys.update(group)
    return keys


async def _run() -> int:
    settings = get_settings()
    adapter = build_embedding_adapter(settings)
    print(
        f"adapter model={adapter.model} dimension={adapter.dimension} "
        f"current_floor={settings.rag_min_vector_score}",
        file=sys.stderr,
    )
    cases = [
        case for case in json.loads(CASES.read_text())["cases"]
        if _oracle_keys(case) and case.get("expect") == "grounded"
    ]
    uow = UnitOfWork(None)
    oracle_bests: list[float] = []
    distractor_bests: list[float] = []
    rows_out: list[dict] = []
    async with uow.factory() as session:
        for case in cases:
            question = case["question"]
            terms = " ".join(profile_query(question).terms)
            if isinstance(adapter, OpenAIEmbedding):
                vector = await adapter.aembed(terms)
            else:
                vector = adapter.embed(terms)
            record = await session.execute(text("""
                WITH scored AS (
                  SELECT c.record_key,
                    greatest(0, 1-(c.embedding <=> CAST(:vector AS vector))) score
                  FROM chunks c
                  JOIN active_search_generations g
                    ON g.generation_id = c.generation_id
                  WHERE c.lifecycle = 'active'
                )
                SELECT
                  max(score) FILTER (WHERE record_key = ANY(:oracle)) oracle_best,
                  max(score) FILTER (WHERE NOT record_key = ANY(:oracle))
                    distractor_best
                FROM scored
            """), {
                "vector": json.dumps(vector),
                "oracle": list(_oracle_keys(case)),
            })
            oracle_best, distractor_best = record.one()
            if oracle_best is None:
                print(
                    f"WARN {case['id']}: oracle records have no active chunks",
                    file=sys.stderr,
                )
                continue
            oracle_bests.append(float(oracle_best))
            distractor_bests.append(float(distractor_best or 0.0))
            rows_out.append({
                "case_id": case["id"],
                "oracle_best": round(float(oracle_best), 4),
                "distractor_best": round(float(distractor_best or 0.0), 4),
            })

    def pct(values: list[float], q: float) -> float:
        ranked = sorted(values)
        index = max(0, min(len(ranked) - 1, round(q * (len(ranked) - 1))))
        return round(ranked[index], 4)

    floor_candidate = min(oracle_bests) if oracle_bests else 0.0
    suggested = round(
        min(
            max(0.0, floor_candidate - 0.02),
            statistics.median(distractor_bests) if distractor_bests else 1.0,
        ),
        4,
    )
    print(json.dumps({
        "cases_measured": len(rows_out),
        "oracle_best": {
            "min": pct(oracle_bests, 0.0),
            "p05": pct(oracle_bests, 0.05),
            "p50": pct(oracle_bests, 0.5),
            "max": pct(oracle_bests, 1.0),
        },
        "distractor_best": {
            "min": pct(distractor_bests, 0.0),
            "p50": pct(distractor_bests, 0.5),
            "p95": pct(distractor_bests, 0.95),
            "max": pct(distractor_bests, 1.0),
        },
        "suggested_min_vector_score": suggested,
        "rows": rows_out,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
