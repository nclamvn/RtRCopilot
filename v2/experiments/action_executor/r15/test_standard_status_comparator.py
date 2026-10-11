"""One fixed status-domain comparison, not HTTP/native or whole-candidate readiness."""

import asyncio
import json
import math
import os
import time
import uuid
from contextlib import AsyncExitStack, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_action_execution_adversarial as adversarial
import test_action_standard_status_factory_integration as controls
import test_action_status_fusion_integration as r14
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_api import bounded
from rtr_copilot.db import engine as runtime
from rtr_copilot.db.uow import UnitOfWork

# Fixture objects only; importing no test function into this module's collection.
factory = controls.factory
oracle = controls.oracle
execution_config = controls.execution_config
local_boundaries = controls.local_boundaries
pytestmark = adversarial.pytestmark
TAG: ContextVar[str | None] = ContextVar("r15_status_attempt", default=None)
CAP = 10 * 1024 * 1024


class Observation:
    """Transparent aggregate events; physical checkin follows record ownership."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine.sync_engine
        self.rows: dict[str, dict[str, Any]] = {}
        self.held: dict[int, tuple[str, int]] = {}
        self.integrity: list[str] = []

    def row(self, tag: str) -> dict[str, Any]:
        return self.rows.setdefault(
            tag,
            {"sql": 0, "checkout": 0, "checkin": 0, "hold_ms": [], "row_sql": 0, "receipt_sql": 0},
        )

    @contextmanager
    def watching(self) -> Any:
        def checkout(dbapi: Any, record: Any, proxy: Any) -> None:
            tag = TAG.get()
            if tag is None:
                return
            identity = id(record)
            if identity in self.held:
                self.integrity.append("duplicate_checkout")
            self.held[identity] = (tag, time.perf_counter_ns())
            self.row(tag)["checkout"] += 1

        def checkin(dbapi: Any, record: Any) -> None:
            owned = self.held.pop(id(record), None)
            if owned is not None:
                tag, start = owned
                row = self.row(tag)
                row["checkin"] += 1
                row["hold_ms"].append((time.perf_counter_ns() - start) / 1e6)

        def before(connection: Any, cursor: Any, statement: str, *args: Any) -> None:
            tag = TAG.get()
            if tag is not None:
                row = self.row(tag)
                row["sql"] += 1
                row["row_sql"] += int("SELECT e.*,r.plan_id" in statement)
                row["receipt_sql"] += int("FROM action_execution_receipts c" in statement)

        event.listen(self.engine, "checkout", checkout)
        event.listen(self.engine, "checkin", checkin)
        event.listen(self.engine, "before_cursor_execute", before)
        try:
            yield self
        finally:
            event.remove(self.engine, "checkout", checkout)
            event.remove(self.engine, "checkin", checkin)
            event.remove(self.engine, "before_cursor_execute", before)


async def seed_receipts(factory: Any, run: Any, count: int) -> None:
    async with factory() as session, session.begin():
        for ordinal in range(count):
            values = {
                "aid": uuid.uuid4(),
                "run": run,
                "step": f"r15_{ordinal}",
                "token": uuid.uuid4(),
                "source": f"r15:{run}:{ordinal}",
                "digest": "a" * 64,
                "rid": uuid.uuid4(),
                "instant": datetime(2026, 1, 1, tzinfo=UTC),
            }
            await session.execute(
                text("""
                INSERT INTO action_step_attempts(attempt_id,run_id,step_key,attempt,epoch,
                  owner_token,source_key,input_digest,charged_calls)
                VALUES(:aid,:run,:step,1,1,:token,:source,:digest,1)
            """),
                values,
            )
            await session.execute(
                text("""
                INSERT INTO action_execution_receipts(receipt_id,run_id,attempt_id,step_key,
                  attempt,kind,output_digest,reused_source,occurred_at)
                VALUES(:rid,:run,:aid,:step,1,'read_verified',:digest,false,:instant)
            """),
                values,
            )


def percentiles(values: list[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    return {
        key: (ordered[max(0, math.ceil(len(ordered) * quantile) - 1)] if ordered else None)
        for key, quantile in (("p50_ms", 0.50), ("p95_ms", 0.95), ("p99_ms", 0.99), ("max_ms", 1.0))
    }


@pytest.mark.asyncio
async def test_one_fixed_800_status_domain_comparison(
    factory: Any,
    oracle: Any,
    tmp_path: Path,
    execution_config: Any,
    local_boundaries: Any,
) -> None:
    destination = Path(os.environ["R15_COMPARISON_EVIDENCE"])
    assert destination.is_dir() and destination.name == "compare_e1"
    assert str(runtime.runtime_engine().url.database) == "rtr_tip054_r15_local_e1"
    assert execution_config.action_executor_operation_timeout_seconds == 0.9
    base = runtime.runtime_engine()
    legacy_factory = async_sessionmaker(base, expire_on_commit=False)
    legacy = ExecutionService(UnitOfWork(legacy_factory))
    legacy.settings = execution_config
    new = ExecutionService()
    new.settings = execution_config
    assert type(new) is type(legacy) is ExecutionService
    assert legacy._status_read_factory() is None
    selected = new._status_read_factory()
    assert selected is not None and selected.kw["bind"].pool is base.pool
    actors, runs, expected = [], [], []
    for receipt_count in (0, 2, 100):
        _, actor, _, _, _, view = await adversarial.submitted(factory, tmp_path, execution_config)
        await seed_receipts(factory, view.run_id, receipt_count)
        actors.append(actor)
        runs.append(view.run_id)
        value = await new.status(actor, view.run_id)
        assert len(value.receipts) == receipt_count
        expected.append(value.model_dump(mode="json"))
    observer = Observation(base)
    controls_observed = {}
    with observer.watching():
        for lane, service, sql, leases in (("legacy", legacy, 4, 3), ("new", new, 3, 1)):
            token = TAG.set(f"control_{lane}")
            try:
                assert (await service.status(actors[0], runs[0])).model_dump(
                    mode="json"
                ) == expected[0]
            finally:
                TAG.reset(token)
            row = observer.row(f"control_{lane}")
            assert row["sql"] == sql and row["checkout"] == row["checkin"] == leases
            assert row["row_sql"] == (2 if lane == "legacy" else 1)
            assert row["receipt_sql"] == 1
            assert not observer.held and base.pool.checkedout() == 0
            controls_observed[lane] = dict(row)
    # Simultaneously hold every permitted slot, exactly once and outside timing.
    async with AsyncExitStack() as warm:
        for _ in range(10):
            await warm.enter_async_context(base.connect())
        assert base.pool.checkedout() == 10
    assert base.pool.checkedout() == 0
    warm_pool = {
        "size": base.pool.size(),
        "checkedin": base.pool.checkedin(),
        "overflow": base.pool.overflow(),
        "checkedout": base.pool.checkedout(),
    }
    before_metadata = [await r14.immutable_snapshot(oracle, run) for run in runs]
    schedule = []
    for cell, concurrency in enumerate((1, 10, 25, 50)):
        for lane in ("legacy", "new") if cell % 2 == 0 else ("new", "legacy"):
            for ordinal in range(100):
                schedule.append(
                    {
                        "id": f"c{concurrency}_{lane}_{ordinal:03d}",
                        "concurrency": concurrency,
                        "lane": lane,
                        "ordinal": ordinal,
                        "receipt_count": (0, 2, 100)[ordinal % 3],
                    }
                )
    schedule_path = destination / "schedule.json"
    schedule_path.write_text(json.dumps(schedule, indent=2) + "\n")
    raw_path = destination / "outcomes.jsonl"
    journal_path = destination / "started.jsonl"
    assert not raw_path.exists() and not journal_path.exists()
    started_ids: set[str] = set()
    outcomes: dict[str, dict[str, Any]] = {}
    stopped: list[str] = []
    campaign_start = time.perf_counter_ns()
    deadline = time.monotonic() + 180

    def retain(row: dict[str, Any], *, final_missing: bool = False) -> None:
        encoded = json.dumps(row, sort_keys=True) + "\n"
        # Reserve ample room for all unstarted/missing IDs and final summaries.
        overhead = schedule_path.stat().st_size + journal_path.stat().st_size
        ceiling = CAP - 65536 - overhead if final_missing else CAP - 1024 * 1024 - overhead
        if raw_path.stat().st_size + len(encoded.encode()) > ceiling:
            stopped.append("raw_cap")
            return
        raw.write(encoded)
        raw.flush()
        outcomes[row["id"]] = row

    async def attempt(item: dict[str, Any], slots: Any) -> None:
        queued = time.perf_counter_ns()
        async with slots:
            if stopped:
                return
            if time.monotonic() >= deadline:
                stopped.append("campaign_deadline")
                return
            service = legacy if item["lane"] == "legacy" else new
            launch = time.perf_counter_ns()
            journal_entry = (
                json.dumps({"id": item["id"], "launch_offset_ms": (launch - campaign_start) / 1e6})
                + "\n"
            )
            if (
                sum(path.stat().st_size for path in (schedule_path, raw_path, journal_path))
                + len(journal_entry.encode())
                > CAP - 1024 * 1024
            ):
                stopped.append("journal_cap")
                return
            journal.write(journal_entry)
            journal.flush()
            started_ids.add(item["id"])
            start = time.perf_counter_ns()
            token = TAG.set(item["id"])
            row = dict(
                item,
                outcome="error",
                equal=False,
                slot_wait_ms=(start - queued) / 1e6,
                start_offset_ms=(start - campaign_start) / 1e6,
            )
            try:
                value = await bounded(
                    SimpleNamespace(state=SimpleNamespace(request_id=item["id"])),
                    actors[item["ordinal"] % 3],
                    service,
                    service.status(actors[item["ordinal"] % 3], runs[item["ordinal"] % 3]),
                )
                row["latency_ms"] = (time.perf_counter_ns() - start) / 1e6
                if hasattr(value, "model_dump"):
                    row["equal"] = value.model_dump(mode="json") == expected[item["ordinal"] % 3]
                    row["outcome"] = "success" if row["equal"] else "dto_mismatch"
                else:
                    body = json.loads(value.body)
                    row["status"] = value.status_code
                    row["error_code"] = body.get("error", {}).get("code")
                    row["outcome"] = (
                        "timeout" if row["error_code"] == "action_operation_timeout" else "error"
                    )
            except asyncio.CancelledError:
                row["latency_ms"] = (time.perf_counter_ns() - start) / 1e6
                row["outcome"] = "cancelled"
                raise
            except Exception as error:
                row.setdefault("latency_ms", (time.perf_counter_ns() - start) / 1e6)
                row["exception_type"] = type(error).__name__
            finally:
                row.setdefault("latency_ms", (time.perf_counter_ns() - start) / 1e6)
                TAG.reset(token)
                row.update(observer.row(item["id"]))
                row["cleanup_equal"] = row["checkout"] == row["checkin"]
                if row["outcome"] == "dto_mismatch":
                    stopped.append("correctness_integrity")
                if not row["cleanup_equal"]:
                    stopped.append("cleanup_failure")
                if row["outcome"] == "success":
                    sql, leases, row_sql = (4, 3, 2) if item["lane"] == "legacy" else (3, 1, 1)
                    if (
                        row["sql"],
                        row["checkout"],
                        row["checkin"],
                        row["row_sql"],
                        row["receipt_sql"],
                    ) != (sql, leases, leases, row_sql, 1):
                        stopped.append("application_count_integrity")
                if observer.integrity:
                    stopped.append("observer_integrity")
                retain(row)

    with raw_path.open("x") as raw, journal_path.open("x") as journal, observer.watching():
        try:
            async with asyncio.timeout(180):
                for concurrency in (1, 10, 25, 50):
                    lanes = ("legacy", "new") if concurrency in (1, 25) else ("new", "legacy")
                    for lane in lanes:
                        if stopped:
                            break
                        slots = asyncio.Semaphore(concurrency)
                        items = [
                            item
                            for item in schedule
                            if item["concurrency"] == concurrency and item["lane"] == lane
                        ]
                        tasks = [asyncio.create_task(attempt(item, slots)) for item in items]
                        try:
                            await asyncio.gather(*tasks)
                        finally:
                            for task in tasks:
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                        if observer.held or base.pool.checkedout():
                            stopped.append("cell_leak")
        except TimeoutError:
            stopped.append("campaign_deadline")
        finally:
            for item in schedule:
                if item["id"] not in outcomes:
                    retain(dict(item, outcome="missing", equal=False), final_missing=True)
    cells = []
    for concurrency in (1, 10, 25, 50):
        for lane in ("legacy", "new"):
            rows = [
                row
                for row in outcomes.values()
                if row["concurrency"] == concurrency and row["lane"] == lane
            ]
            observed = [row for row in rows if "latency_ms" in row]
            cells.append(
                dict(
                    concurrency=concurrency,
                    lane=lane,
                    scheduled=100,
                    observed=len(observed),
                    missing=100 - len(observed),
                    errors=sum(row["outcome"] != "success" for row in observed),
                    timeouts=sum(row["outcome"] == "timeout" for row in observed),
                    receipt_population={
                        str(n): sum(row["receipt_count"] == n for row in rows) for n in (0, 2, 100)
                    },
                    **percentiles([row["latency_ms"] for row in observed]),
                )
            )
    after_metadata = [await r14.immutable_snapshot(oracle, run) for run in runs]
    relative = []
    for concurrency in (1, 10, 25, 50):
        old = next(
            cell
            for cell in cells
            if cell["concurrency"] == concurrency and cell["lane"] == "legacy"
        )
        candidate = next(
            cell for cell in cells if cell["concurrency"] == concurrency and cell["lane"] == "new"
        )
        relative.append(
            {
                "concurrency": concurrency,
                "new_minus_legacy_p95_percent": (
                    (candidate["p95_ms"] / old["p95_ms"] - 1) * 100
                    if old["p95_ms"] and candidate["p95_ms"] is not None
                    else None
                ),
            }
        )
    summary = {
        "scheduled": 800,
        "started": len(started_ids),
        "not_started": 800 - len(started_ids),
        "started_missing_outcome": sorted(
            identity
            for identity in started_ids
            if identity not in outcomes or outcomes[identity]["outcome"] == "missing"
        ),
        "retained": len(outcomes),
        "cells": cells,
        "relative_fixture_observations": relative,
        "metadata_unchanged": before_metadata == after_metadata,
        "stopped": stopped,
        "integrity": observer.integrity,
        "controls_outside_timing": controls_observed,
        "pool_after_warm": warm_pool,
        "warm_scope": (
            "10 simultaneously held; pool5+5 retains5 idle/closes overflow; "
            "later overflow creation is timed"
        ),
        "scope": "bounded domain; not HTTP/native/whole-candidate certification",
        "application_sql_excludes": [
            "BEGIN",
            "initialization",
            "pre_ping",
            "rollback",
            "isolation_reset",
        ],
        "percentiles": "nearest rank; all observed incl errors; no invented missing latency",
        "journal": (
            "flushed before service timer; common observer/journal perturbation, not corrected SLA"
        ),
        "pool_checkedout": base.pool.checkedout(),
        "held_records": len(observer.held),
    }
    (destination / "comparison-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    assert len(outcomes) == len(started_ids) == 800 and not stopped and not observer.integrity
    assert not observer.held and base.pool.checkedout() == 0
    assert before_metadata == after_metadata
    assert new.uow.factory is factory and legacy.uow.factory is legacy_factory
    assert selected.kw["bind"].pool is base.pool and not base.get_execution_options()
    assert (
        sum(
            path.stat().st_size
            for path in (
                schedule_path,
                raw_path,
                journal_path,
                destination / "comparison-summary.json",
            )
        )
        <= CAP
    )
    for cell in cells:
        assert (
            cell["observed"] == 100 and cell["errors"] == cell["timeouts"] == cell["missing"] == 0
        )
        assert cell["receipt_population"] == {"0": 34, "2": 33, "100": 33}
        assert cell["p95_ms"] <= 1000
    for row in outcomes.values():
        sql, leases = (4, 3) if row["lane"] == "legacy" else (3, 1)
        assert row["sql"] == sql and row["checkout"] == row["checkin"] == leases
        assert row["row_sql"] == (2 if row["lane"] == "legacy" else 1)
        assert row["receipt_sql"] == 1 and row["cleanup_equal"]
