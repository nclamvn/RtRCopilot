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
from urllib.parse import urlsplit

import httpx

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

DEFAULT_CASES = HERE / "real_world" / "cases.json"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def bounded_cases(
    campaign: dict[str, Any],
    max_cases: int | None,
    case_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Return a deterministic smoke slice or the complete release campaign."""
    cases = list(campaign["flattened_cases"])
    if case_ids:
        requested = tuple(dict.fromkeys(case_ids))
        by_id = {str(case["id"]): case for case in cases}
        missing = [case_id for case_id in requested if case_id not in by_id]
        if missing:
            raise ValueError(f"campaign_case_ids_unknown:{','.join(missing)}")
        cases = [by_id[case_id] for case_id in requested]
    if max_cases is None:
        return cases
    if max_cases < 1:
        raise ValueError("campaign_max_cases_must_be_positive")
    return cases[:max_cases]


async def evaluate(
    cases_path: Path,
    subject_id: uuid.UUID,
    *,
    expected_database: str,
    max_cases: int | None = None,
    case_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    # The DB-direct compatibility mode needs the application dependency graph;
    # keep those imports lazy so the browser-facing HTTP campaign only needs
    # httpx and can run from the host against the loopback-bound E2E web port.
    from sqlalchemy import text

    from rtr_copilot.db.engine import session_factory
    from rtr_copilot.rag.answering import AnswerService
    from rtr_copilot.rag.models import SearchFilters
    from rtr_copilot.repositories.identity_postgres import (
        PostgresSubjectRepository,
    )

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

    selected_cases = bounded_cases(campaign, max_cases, case_ids)
    for index, case in enumerate(selected_cases, start=1):
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
        "case_limit": max_cases,
        "selected_case_ids": list(case_ids),
        "full_campaign_size": len(campaign["flattened_cases"]),
        "thresholds": campaign["thresholds"],
        **summary,
        "results": rows,
    }


def validate_http_target(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("campaign_http_target_must_be_loopback_http")
    return base_url.rstrip("/")


async def evaluate_http(
    cases_path: Path,
    base_url: str,
    *,
    concurrency: int = 3,
    request_timeout: float = 150.0,
    max_cases: int | None = None,
    case_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run the semantic oracle through the real browser-facing HTTP session.

    Independent questions run concurrently behind a small bound. Turns inside
    one scenario remain strictly ordered and reuse the server-issued
    conversation id. The result intentionally stores no answer plaintext.
    """
    target = validate_http_target(base_url)
    campaign = load_campaign(cases_path)
    run_id = uuid.uuid4()
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 4)))
    selected_cases = bounded_cases(campaign, max_cases, case_ids)
    indexed: list[tuple[int, dict[str, Any]]] = list(enumerate(selected_cases, start=1))
    by_scenario: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    singles: list[tuple[int, dict[str, Any]]] = []
    for item in indexed:
        scenario_id = item[1].get("scenario_id")
        if scenario_id:
            by_scenario.setdefault(str(scenario_id), []).append(item)
        else:
            singles.append(item)

    async with httpx.AsyncClient(
        base_url=target,
        follow_redirects=True,
        timeout=httpx.Timeout(request_timeout),
    ) as client:
        login = await client.get("/api/auth/login")
        login.raise_for_status()

        async def execute(
            index: int,
            case: dict[str, Any],
            conversation_id: str | None,
        ) -> tuple[dict[str, Any], str | None]:
            payload: dict[str, Any] = {"question": str(case["question"])}
            if conversation_id is not None:
                payload["conversation_id"] = conversation_id
            latency_ms = 0.0
            try:
                async with semaphore:
                    started = time.perf_counter()
                    try:
                        response = await client.post(
                            "/api/ask/ask",
                            json=payload,
                            headers={
                                "x-request-id": (
                                    f"e2e-{run_id.hex[:10]}-{index:03d}"
                                ),
                            },
                        )
                    finally:
                        latency_ms = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                body = response.json()
                row = score_case(
                    case,
                    state=str(body.get("state", "error")),
                    answer=str(body.get("answer", "")),
                    citations=[
                        str(item.get("record_key", ""))
                        for item in body.get("citations", [])
                        if isinstance(item, dict)
                    ],
                    reason_code=(
                        str(body["reason_code"])
                        if body.get("reason_code") is not None
                        else None
                    ),
                    latency_ms=latency_ms,
                )
                row["answer_mode"] = body.get("answer_mode")
                issued_conversation = body.get("conversation_id")
                return row, (
                    str(issued_conversation)
                    if issued_conversation
                    else conversation_id
                )
            except Exception as exc:  # noqa: BLE001 — record every E2E failure
                row = score_case(
                    case,
                    state="error",
                    answer="",
                    citations=[],
                    reason_code=type(exc).__name__,
                    latency_ms=latency_ms,
                )
                row["answer_mode"] = None
                row["http_case_index"] = index
                if isinstance(exc, httpx.HTTPStatusError):
                    row["http_status"] = exc.response.status_code
                    try:
                        error_body = exc.response.json()
                    except ValueError:
                        error_body = {}
                    error = error_body.get("error", {})
                    if isinstance(error, dict) and isinstance(error.get("code"), str):
                        row["http_error_code"] = error["code"]
                return row, conversation_id

        async def execute_scenario(
            items: list[tuple[int, dict[str, Any]]],
        ) -> list[tuple[int, dict[str, Any]]]:
            conversation_id: str | None = None
            results: list[tuple[int, dict[str, Any]]] = []
            for index, case in sorted(
                items,
                key=lambda item: int(item[1].get("turn_index") or 0),
            ):
                row, conversation_id = await execute(index, case, conversation_id)
                results.append((index, row))
            return results

        async def execute_single(
            index: int,
            case: dict[str, Any],
        ) -> list[tuple[int, dict[str, Any]]]:
            row, _ = await execute(index, case, None)
            return [(index, row)]

        groups = await asyncio.gather(
            *(execute_single(index, case) for index, case in singles),
            *(execute_scenario(items) for items in by_scenario.values()),
        )

    ordered = [item for group in groups for item in group]
    rows = [row for _, row in sorted(ordered, key=lambda item: item[0])]
    thresholds = campaign.get("http_thresholds", campaign["thresholds"])
    summary = summarize(rows, thresholds)
    return {
        "schema_version": 1,
        "campaign": f"{campaign['campaign']} · HTTP E2E",
        "run_id": str(run_id),
        "computed_at": datetime.now(UTC).isoformat(),
        "subject_digest": hashlib.sha256(b"isolated-http-e2e").hexdigest(),
        "database_digest": None,
        "provider": "http-runtime",
        "ontology_digest": None,
        "case_limit": max_cases,
        "selected_case_ids": list(case_ids),
        "full_campaign_size": len(campaign["flattened_cases"]),
        "thresholds": thresholds,
        **summary,
        "results": rows,
    }


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--subject-id", type=uuid.UUID)
    parser.add_argument("--expected-database")
    parser.add_argument("--base-url")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--request-timeout", type=float, default=150.0)
    parser.add_argument(
        "--max-cases",
        type=int,
        help="deterministic smoke slice; omit only for an approved full campaign",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="run only this case id; repeat for a cost-bounded regression set",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    if args.base_url:
        if args.subject_id is not None or args.expected_database is not None:
            parser.error("--base-url cannot be combined with direct database options")
        result = await evaluate_http(
            args.cases,
            args.base_url,
            concurrency=args.concurrency,
            request_timeout=args.request_timeout,
            max_cases=args.max_cases,
            case_ids=tuple(args.case_id),
        )
    else:
        if args.subject_id is None or args.expected_database is None:
            parser.error("direct mode requires --subject-id and --expected-database")
        result = await evaluate(
            args.cases,
            args.subject_id,
            expected_database=args.expected_database,
            max_cases=args.max_cases,
            case_ids=tuple(args.case_id),
        )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passed"] or args.allow_failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
