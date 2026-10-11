"""Finite read-only wait sampler: no pg_stat_activity.query or parameters."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import asyncpg

root = Path(sys.argv[1])
assert str(root).startswith("/evidence/")


async def main():
    samples, errors = 0, 0
    connection = await asyncpg.connect(
        os.environ["POSTGRES_DSN"],
        timeout=5,
        server_settings={
            "default_transaction_read_only": "on",
            "statement_timeout": "250ms",
            "application_name": "tip054-r-readonly-monitor",
        },
    )
    started = time.perf_counter_ns()
    with (root / "pg-waits.jsonl").open("x") as stream:
        try:
            while (
                samples < 3600
                and time.perf_counter_ns() - started < 180e9
                and not (root / "monitor.stop").exists()
            ):
                tick = time.perf_counter_ns()
                try:
                    rows = await connection.fetch("""
                        SELECT pid,wait_event_type,wait_event,pg_blocking_pids(pid) AS blockers
                        FROM pg_stat_activity WHERE datname=current_database()
                          AND pid<>pg_backend_pid() AND usename=current_user
                    """)
                    locks = await connection.fetch("""
                        SELECT l.pid,l.locktype,l.mode,l.relation,l.granted FROM pg_locks l
                        JOIN pg_stat_activity a USING(pid)
                        WHERE a.datname=current_database() AND a.usename=current_user
                          AND a.pid<>pg_backend_pid()
                          AND (NOT l.granted OR a.wait_event_type='Lock')
                    """)
                    record = {
                        "tick_ns": tick,
                        "end_ns": time.perf_counter_ns(),
                        "activity": [dict(r) for r in rows],
                        "locks": [dict(r) for r in locks],
                    }
                except Exception as exc:
                    errors += 1
                    record = {
                        "tick_ns": tick,
                        "end_ns": time.perf_counter_ns(),
                        "error_type": type(exc).__name__,
                    }
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
                stream.flush()
                samples += 1
                await asyncio.sleep(max(0, 0.05 - (time.perf_counter_ns() - tick) / 1e9))
        finally:
            await connection.close(timeout=5)
    (root / "pg-monitor-summary.json").write_text(
        json.dumps(
            {
                "samples": samples,
                "errors": errors,
                "wall_ms": (time.perf_counter_ns() - started) / 1e6,
                "tick_target_ms": 50,
                "limit_seconds": 180,
                "limit_ticks": 3600,
                "read_only": True,
                "limits": (
                    "Finite sampled waits only; first/last observation spans are not exact "
                    "continuous duration. Gaps and unsampled short waits do not prove zero "
                    "lock wait. Diagnostic connection separate from unchanged application pool."
                ),
            },
            indent=2,
        )
    )


asyncio.run(main())
