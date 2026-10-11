"""Offline numeric summary; optional actual chain verification AFTER timed load."""

import asyncio
import json
import math
import sys
from collections import Counter
from pathlib import Path


def stats(values):
    values = sorted(values)
    return (
        {
            "samples": len(values),
            "p50": values[math.ceil(len(values) * 0.5) - 1],
            "p95": values[math.ceil(len(values) * 0.95) - 1],
            "max": values[-1],
        }
        if values
        else {"samples": 0}
    )


async def chain():
    from sqlalchemy import text

    from rtr_copilot.db.engine import runtime_engine, session_factory
    from rtr_copilot.repositories.audit import AuditRepository

    try:
        async with session_factory()() as session:
            role = await session.scalar(text("SELECT current_user"))
            assert role == "rtr_app"
            valid, count, head = await AuditRepository().verify(session)
        return {
            "role": role,
            "valid": valid,
            "event_count": count,
            "head_sha256": head,
            "timing": "AFTER all timed HTTP observations, fresh process/engine",
        }
    finally:
        await runtime_engine().dispose()


root = Path(sys.argv[1])
records = [
    json.loads(line) for line in (root / "audit-transactions.jsonl").read_text().splitlines()
]
summary = json.loads((root / "audit-observer-summary.json").read_text())
cells = []
for profile in (1, 10, 25, 50):
    for operation in ("admission", "submit", "status", "cancel"):
        rows = [r for r in records if r["profile"] == profile and r["operation"] == operation]
        granted = [r for r in rows if r["first_audit_grant_ns"] is not None]
        cells.append(
            {
                "profile": profile,
                "operation": operation,
                "transactions": len(rows),
                "granted_transactions": len(granted),
                "terminal_kinds": dict(Counter(r["terminal_kind"] for r in granted)),
                "grant_to_terminal_ms": stats(
                    [
                        r["grant_to_terminal_ms"]
                        for r in granted
                        if r["grant_to_terminal_ms"] is not None
                    ]
                ),
                "postgrant_sql_started": stats([r["postgrant_sql_started"] for r in granted]),
                "reentrant_grants": stats([r["reentrant_grants"] for r in granted]),
                "append_ms": stats(
                    [
                        (a["end_ns"] - a["start_ns"]) / 1e6
                        for r in granted
                        for a in r["append_spans"]
                    ]
                ),
                "audit_acquisition_envelope_ms": stats(
                    [
                        (a["end_ns"] - a["start_ns"]) / 1e6
                        for r in rows
                        for a in r["audit_attempts"]
                        if a["end_ns"] is not None
                    ]
                ),
            }
        )
cost = json.loads((root / "audit-recorder-cost.json").read_text())
result = {
    "observer": summary,
    "cells": cells,
    "observer_serialize_ms": stats([c["serialize_ms"] for c in cost]),
    "observer_append_flush_ms": stats([c["append_flush_ms"] for c in cost]),
    "limits": "Client observations, not physical server release/pure wait; not additive p95s",
}
if "--verify-chain" in sys.argv[2:]:
    result["actual_chain_after_timing"] = asyncio.run(chain())
result["status"] = (
    "PASS"
    if summary["metrics_complete"]
    and summary["audit_granted_transactions"] > 0
    and result.get("actual_chain_after_timing", {}).get("valid", True)
    else "FAIL"
)
(root / "audit-tail-summary.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "PASS" else 1)
