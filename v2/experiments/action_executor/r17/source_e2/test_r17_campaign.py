"""ONE separately collected finite campaign; never selected by pre/SQL correctness."""

import asyncio
import json
import os
import time
from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_action_execution_adversarial as adversarial
import test_action_standard_status_factory_integration as controls
import test_action_status_fusion_integration as fusion
from test_standard_status_comparator import TAG, seed_receipts

from rtr_copilot.actions.execution_api import bounded

from diagnostic import Collector, Output, flush_detail, join_observation, reconstruct, sample_lag, schedule
from observer import Observation
from test_r17_sql import services

factory = controls.factory
oracle = controls.oracle
execution_config = controls.execution_config
local_boundaries = controls.local_boundaries
pytestmark = adversarial.pytestmark


@pytest.mark.asyncio
async def test_one_fixed_800_checkout_lifecycle_campaign(
        factory, oracle, tmp_path: Path, execution_config, local_boundaries):
    destination = Path(os.environ["R17_EVIDENCE"])
    assert destination.is_dir() and destination.name == "compare_e1"
    base, legacy, new = services(execution_config)
    selected = new._status_read_factory()
    actors, runs, expected = [], [], []
    for count in (0, 2, 100):
        _, actor, _, _, _, view = await adversarial.submitted(factory, tmp_path, execution_config)
        await seed_receipts(factory, view.run_id, count)
        value = await new.status(actor, view.run_id)
        assert len(value.receipts) == count
        actors.append(actor); runs.append(view.run_id); expected.append(value.model_dump(mode="json"))
    # Once only; no cell rewarm. Overflow creation in later cells is timed.
    async with AsyncExitStack() as warm:
        for _ in range(10):
            await warm.enter_async_context(base.connect())
        assert base.pool.checkedout() == 10
    assert base.pool.checkedout() == 0 and base.pool.checkedin() == 5
    warm_pool = dict(checkedin=base.pool.checkedin(), checkedout=base.pool.checkedout(),
                     overflow=base.pool.overflow(), size=base.pool.size())
    before = [await fusion.immutable_snapshot(oracle, run) for run in runs]
    collector = Collector()
    observer = Observation(base, collector)
    planned = schedule()
    output = Output(destination)
    started, outcomes = [], {}
    stops = []
    first = time.perf_counter_ns()
    deadline = time.monotonic() + 180
    cursors = dict(events=0, lag=0)

    def stop(code):
        if code not in stops and len(stops) < 24:
            stops.append(code)

    def retain(name, value, reserve=False):
        if output.append(name, value, reserve=reserve):
            return True
        stop("output_cap")
        return False

    async def attempt(item, slots):
        queued = time.perf_counter_ns()
        async with slots:
            if stops or collector.faults:
                return
            if time.monotonic() >= deadline:
                stop("campaign_deadline")
                return
            launch = time.perf_counter_ns()
            journal = dict(id=item["id"], launch_offset_ms=(launch - first) / 1e6)
            if not retain("started.jsonl", journal):
                return
            started.append(journal)
            # Common external journal flush remains before the service timer in BOTH modes.
            start = time.perf_counter_ns()
            token = TAG.set(item["id"])
            row = dict(item, outcome="error", equal=False, slot_wait_ms=(start - queued) / 1e6,
                       start_offset_ms=(start - first) / 1e6)
            service = legacy if item["lane"] == "legacy" else new
            try:
                value = await bounded(SimpleNamespace(state=SimpleNamespace(request_id=item["id"])),
                                      actors[item["ordinal"] % 3], service,
                                      service.status(actors[item["ordinal"] % 3], runs[item["ordinal"] % 3]))
                row["latency_ms"] = (time.perf_counter_ns() - start) / 1e6
                if hasattr(value, "model_dump"):
                    row["equal"] = value.model_dump(mode="json") == expected[item["ordinal"] % 3]
                    row["outcome"] = "success" if row["equal"] else "dto_mismatch"
                else:
                    body = json.loads(value.body)
                    row["status"] = value.status_code
                    row["error_code"] = body.get("error", {}).get("code")
                    row["outcome"] = "timeout" if row["error_code"] == "action_operation_timeout" else "error"
            except asyncio.CancelledError:
                row["outcome"] = "cancelled"
                raise
            except Exception as error:
                row["exception_type"] = type(error).__name__[:80]
            finally:
                row.setdefault("latency_ms", (time.perf_counter_ns() - start) / 1e6)
                TAG.reset(token)
                if row["outcome"] == "dto_mismatch":
                    stop("correctness_integrity")
                outcomes[item["id"]] = row

    try:
        for item in planned:
            assert retain("schedule.jsonl", item)
        try:
            async with asyncio.timeout(180):
                for cell in range(1, 9):
                    if stops or collector.faults:
                        break
                    items = [item for item in planned if item["cell"] == cell]
                    mode = items[0]["mode"]
                    done = asyncio.Event()
                    try:
                        with observer.watching(mode):
                            sampler = asyncio.create_task(sample_lag(collector, cell, done)) if mode == "D" else None
                            slots = asyncio.Semaphore(25)
                            tasks = [asyncio.create_task(attempt(item, slots)) for item in items]
                            try:
                                await asyncio.gather(*tasks)
                            finally:
                                # Original service latency is already retained. Drain only
                                # observation cleanup, including shielded legacy close children.
                                await join_observation(tasks, lambda: observer.drain(mode), done, sampler)
                    finally:
                        # Also reached when the campaign deadline cancelled the active cell.
                        flush_detail(output, collector, cursors)
                        for item in items:
                            row = outcomes.get(item["id"])
                            if row is None:
                                continue
                            row.update(observer.row(item["id"], mode))
                            row["cleanup_equal"] = row["checkout"] == row["checkin"]
                            if not row["cleanup_equal"]:
                                stop("cleanup_failure")
                            if row["outcome"] == "success":
                                sql, leases, row_sql = (4, 3, 2) if item["lane"] == "legacy" else (3, 1, 1)
                                if (row["sql"], row["checkout"], row["checkin"], row["row_sql"], row["receipt_sql"]) != (sql, leases, leases, row_sql, 1):
                                    stop("application_count_integrity")
                        if observer.aggregate.integrity:
                            stop("observer_integrity")
                    if observer.aggregate.held or observer.lifecycle.held or base.pool.checkedout():
                        stop("cell_leak")
                    if [await fusion.immutable_snapshot(oracle, run) for run in runs] != before:
                        stop("metadata_integrity")
        except TimeoutError:
            stop("campaign_deadline")
        finally:
            retention = flush_detail(output, collector, cursors)
            assert retain("detail-retention.jsonl", retention, reserve=True), "retention reserve exhausted"
            # Preserve every actual outcome even after a cap fault, then explicit missing.
            for item in planned:
                row = outcomes.get(item["id"])
                if row is None:
                    row = dict(item, outcome="missing", equal=False, latency_ms=None,
                               started=item["id"] in {entry["id"] for entry in started})
                    outcomes[item["id"]] = row
                assert retain("outcomes.jsonl", row, reserve=True), "reserved outcome capacity exhausted"
        after = [await fusion.immutable_snapshot(oracle, run) for run in runs]
        # No summary field can depend on unretained in-memory event/lag buffers.
        summary = reconstruct(destination)
        summary.update(stopped=stops, collector_faults=collector.faults,
                       aggregate_integrity=observer.aggregate.integrity,
                       metadata_unchanged=before == after, pool_after_warm=warm_pool,
                       pool_checkedout=base.pool.checkedout(), held_records=len(observer.aggregate.held),
                       detailed_held=len(observer.lifecycle.held),
                       wall_elapsed_ms=(time.perf_counter_ns() - first) / 1e6,
                       timed_campaign_limit_seconds=180,
                       terminal_join_limit="joined original shielded cleanup may extend wall closure",
                       warm_scope="10 simultaneous once; 5 idle; later overflow creation timed",
                       output_bytes_before_summary=output.used,
                       detail_boundaries="process-local synchronous Pool.connect and record.__connect; async terminal; generic cursor",
                       exposure="D listeners/wrappers/10ms lag only in cells 1,2,7,8; M R15 aggregates only",
                       unresolved="queue/pre-ping/driver/server/scheduling/DTO composites remain; not root-cause or readiness")
        summary["gate"] = summary["gate"] and not stops and not collector.faults and before == after
        assert retain("comparison-summary.jsonl", summary, reserve=True)
    finally:
        output.close()
    assert new.uow.factory is factory and selected.kw["bind"].pool is base.pool
    assert not observer.installed and not base.get_execution_options()
    assert summary["gate"] and len(started) == 800 and not summary["unmatched_spans"]
    assert not observer.aggregate.held and not observer.lifecycle.held and base.pool.checkedout() == 0
