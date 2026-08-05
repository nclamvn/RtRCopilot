#!/usr/bin/env python3
"""TIP-026 full AnswerService campaign against a disposable database clone."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "apps" / "backend"
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib.operational_acceptance import (  # noqa: E402
    load_campaign,
    score_case,
    summarize,
    validate_database_target,
)
from rtr_copilot.db.engine import session_factory  # noqa: E402
from rtr_copilot.rag.answering import AnswerService  # noqa: E402
from rtr_copilot.rag.models import SearchFilters  # noqa: E402
from rtr_copilot.repositories.identity_postgres import (  # noqa: E402
    PostgresSubjectRepository,
)

DEFAULT_CASES = HERE / "real_world" / "cases.json"


async def evaluate(
    cases_path: Path,
    subject_id: uuid.UUID,
    *,
    expected_database: str,
) -> dict[str, Any]:
    async with session_factory()() as session:
        actual_database = str(await session.scalar(text("SELECT current_database()")))
    validate_database_target(actual_database, expected_database)
    campaign = load_campaign(cases_path)
    subject = await PostgresSubjectRepository().get_by_user_id(subject_id)
    if subject is None:
        raise SystemExit(f"subject not found: {subject_id}")
    service = AnswerService()
    run_id = uuid.uuid4()
    conversation_ids: dict[str, uuid.UUID] = {}
    rows: list[dict[str, Any]] = []

    for index, case in enumerate(campaign["flattened_cases"], start=1):
        scenario_id = case.get("scenario_id")
        conversation_key = str(scenario_id or case["id"])
        conversation_id = conversation_ids.setdefault(
            conversation_key,
            uuid.uuid5(run_id, conversation_key),
        )
        started = time.perf_counter()
        try:
            response = await service.ask(
                subject,
                str(case["question"]),
                filters=SearchFilters(),
                require_verified=True,
                conversation_id=conversation_id,
                request_id=f"tip026-{run_id.hex[:8]}-{index:03d}",
            )
            latency_ms = (time.perf_counter() - started) * 1000
            row = score_case(
                case,
                state=response.state,
                answer=response.answer,
                citations=[item.record_key for item in response.citations],
                reason_code=response.reason_code,
                latency_ms=latency_ms,
            )
            row["answer_mode"] = response.answer_mode
        except Exception as exc:  # noqa: BLE001 — campaign must record every failure
            latency_ms = (time.perf_counter() - started) * 1000
            row = score_case(
                case,
                state="error",
                answer="",
                citations=[],
                reason_code=type(exc).__name__,
                latency_ms=latency_ms,
            )
            row["answer_mode"] = None
        rows.append(row)

    summary = summarize(rows, campaign["thresholds"])
    subject_digest = hashlib.sha256(str(subject_id).encode()).hexdigest()
    return {
        "schema_version": 1,
        "campaign": campaign["campaign"],
        "run_id": str(run_id),
        "computed_at": datetime.now(UTC).isoformat(),
        "subject_digest": subject_digest,
        "database_digest": hashlib.sha256(actual_database.encode()).hexdigest(),
        "provider": service.provider.name,
        "ontology_digest": service.ontology.digest,
        "thresholds": campaign["thresholds"],
        **summary,
        "results": rows,
    }


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--subject-id", type=uuid.UUID, required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    result = await evaluate(
        args.cases,
        args.subject_id,
        expected_database=args.expected_database,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passed"] or args.allow_failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
