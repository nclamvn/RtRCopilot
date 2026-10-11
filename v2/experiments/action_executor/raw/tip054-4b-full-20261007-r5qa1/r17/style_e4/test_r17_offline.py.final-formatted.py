"""Exactly eight unique offline controls, stdlib unittest and pytest compatible."""

import asyncio
import copy
import json
import math
import tempfile
import unittest
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import diagnostic as core
import gate
from observer import Lifecycle, Observation, TerminalTasks


def complete():
    planned = core.schedule()
    rows = []
    for item in planned:
        leases, sql, row_sql = (3, 4, 2) if item["lane"] == "legacy" else (1, 3, 1)
        rows.append(
            dict(
                item,
                outcome="success",
                latency_ms=1.0,
                equal=True,
                checkout=leases,
                checkin=leases,
                sql=sql,
                row_sql=row_sql,
                receipt_sql=1,
                hold_ms=[0.1] * leases,
                cleanup_equal=True,
                detail_mode=item["mode"] == "D",
                detail_events=0,
            )
        )
    starts = [dict(id=item["id"], launch_offset_ms=float(n)) for n, item in enumerate(planned)]
    return planned, rows, starts


def events_for(rows):
    events = []
    span = 0
    record = 0

    def emit(tag, kind, **fields):
        events.append(
            dict(attempt=tag, kind=kind, ns=(len(events) + 1) * 10, seq=len(events), **fields)
        )

    for row in rows:
        if row["mode"] != "D" or row["outcome"] == "missing":
            continue
        tag = row["id"]
        first = len(events)
        for lease in range(row["checkout"]):
            record += 1
            identity = dict(
                record=record, generation=None, created_by=None, origin="unknown_pre_observation"
            )
            span += 1
            emit(tag, "acquisition_begin", span=span)
            emit(tag, "checkout", **identity, held_ledger=1)
            emit(tag, "acquisition_end", span=span, **identity, held_ledger=1)
            for _ in range(row["sql"] - row["checkout"] + 1 if lease == 0 else 1):
                span += 1
                emit(tag, "query_begin", span=span, classification="other")
                emit(tag, "query_end", span=span, classification="other")
            span += 1
            emit(tag, "session_terminal_close_begin", span=span)
            emit(
                tag,
                "checkin_callback",
                **identity,
                owned_checkout=True,
                availability="not_yet_pool_return",
                held_ledger=0,
            )
            emit(tag, "pool_return_complete", **identity, held_ledger=0)
            emit(tag, "session_terminal_close_end", span=span)
        row["detail_events"] = len(events) - first
    return events


class OfflineControls(unittest.TestCase):
    def test_ids_time_order_and_finite_values(self):
        planned = core.schedule()
        self.assertEqual(len({row["id"] for row in planned}), 800)
        self.assertEqual(
            [planned[n * 100]["mode"] + "-" + planned[n * 100]["lane"] for n in range(8)],
            list(core.ORDER),
        )
        for lane in ("legacy", "new"):
            for mode in ("D", "M"):
                positions = [
                    n + 1 for n, label in enumerate(core.ORDER) if label == mode + "-" + lane
                ]
                self.assertEqual(sum(positions), 9)
        stamps = iter((100, 101, 102, 101))
        collector = core.Collector(clock=lambda: next(stamps))
        collector.emit("a", "one")
        collector.emit("a", "two")
        collector.emit("a", "backward")
        self.assertEqual([e["ns"] for e in collector.events], [1, 2])
        self.assertEqual(collector.faults, ["clock_integrity"])
        for value in (math.inf, math.nan, -1):
            with self.assertRaises(ValueError):
                core.percentiles([value])
        self.assertIsNone(core.percentiles([])["p95_ms"])

    def test_collector_caps_stop_and_original_failure_retention(self):
        collector = core.Collector()
        for _ in range(129):
            collector.emit("a", "tick")
        self.assertEqual(len(collector.events), 128)
        self.assertIn("attempt_event_cap", collector.faults)
        original = RuntimeError("do not expose this original content")
        try:
            raise original
        except RuntimeError as caught:
            collector.end("a", "operation", 1, caught)
            self.assertIs(caught, original)
        self.assertNotIn("do not expose", json.dumps(collector.events))
        with patch.object(core, "CAMPAIGN_EVENTS", 2):
            limited = core.Collector()
            for tag in ("a", "b", "c"):
                limited.emit(tag, "tick")
            self.assertEqual(len(limited.events), 2)
            self.assertIn("campaign_event_cap", limited.faults)
        # TemporaryDirectory is small test evidence only and always removed on exit.
        with tempfile.TemporaryDirectory(prefix="codex-tmp-r17-offline-20261009-") as directory:
            output = core.Output(directory)
            with patch.object(core, "OUTPUT_CAP", 80), patch.object(core, "RESERVE", 40):
                self.assertTrue(output.append("x.jsonl", {"x": 1}))
                self.assertFalse(output.append("x.jsonl", {"x": "a" * 50}))
                self.assertTrue(output.append("x.jsonl", {"x": "a" * 30}, reserve=True))
                self.assertLessEqual(output.used, 80)
            output.close()
        # Deadline cancellation still joins terminal observation then flushes raw.
        with tempfile.TemporaryDirectory(prefix="codex-tmp-r17-deadline-20261009-") as directory:
            output = core.Output(directory)
            delayed = core.Collector()
            cursors = dict(events=0, lag=0)

            async def deadline():
                done = asyncio.Event()
                terminals = TerminalTasks()

                async def close_child():
                    terminals.observe()
                    delayed.emit("a", "terminal_child_begin")
                    await asyncio.sleep(0.005)
                    delayed.emit("a", "terminal_child_end")

                async def service():
                    child = asyncio.create_task(close_child())
                    await asyncio.shield(child)

                try:
                    async with asyncio.timeout(0.001):
                        tasks = [asyncio.create_task(service())]
                        try:
                            await asyncio.gather(*tasks)
                        finally:
                            await core.join_observation(tasks, terminals.drain, done, None)
                except TimeoutError:
                    pass
                finally:
                    retention = core.flush_detail(output, delayed, cursors)
                return retention

            retention = asyncio.run(deadline())
            output.close()
            retained = [
                json.loads(line)
                for line in (Path(directory) / "events.jsonl").read_text().splitlines()
            ]
            self.assertEqual(retained, delayed.events)
            self.assertEqual(retention["missing_events"], 0)
            self.assertEqual(
                [row["kind"] for row in retained], ["terminal_child_begin", "terminal_child_end"]
            )
        with tempfile.TemporaryDirectory(prefix="codex-tmp-r17-truncation-20261009-") as directory:
            output = core.Output(directory)
            with patch.object(core, "OUTPUT_CAP", 1), patch.object(core, "RESERVE", 0):
                retention = core.flush_detail(output, delayed, dict(events=0, lag=0))
            self.assertEqual((retention["retained_events"], retention["missing_events"]), (0, 2))
            self.assertIn("detail_output_cap", retention["faults"])
            output.close()

    def test_child_cleanup_held_record_ownership(self):
        tag = ContextVar("offline", default=None)
        collector = core.Collector()
        pool = SimpleNamespace(checkedout=lambda: 1, checkedin=lambda: 0, overflow=lambda: 0)
        ledger = Lifecycle(collector, pool, tag.get)
        record = object()

        async def exercise():
            token = tag.set("parent")
            ledger.checkout(None, record, None)
            tag.reset(token)

            async def child():
                self.assertIsNone(tag.get())
                ledger.checkin(None, record)

            await asyncio.create_task(child())

        asyncio.run(exercise())
        self.assertEqual(collector.events[-1]["attempt"], "parent")
        self.assertTrue(collector.events[-1]["owned_checkout"])
        self.assertFalse(ledger.held)
        self.assertEqual(ledger.returning.pop(record), "parent")

        async def cancelled_drain():
            terminals = TerminalTasks()
            release = asyncio.Event()
            finished = []

            async def child():
                terminals.observe()
                await release.wait()
                finished.append("original close settled")

            # Child has not yet run when drain starts; its first turn is observed.
            close = asyncio.create_task(child())
            joined = asyncio.create_task(terminals.drain())
            await asyncio.sleep(0)
            joined.cancel()
            await asyncio.sleep(0)
            joined.cancel()
            self.assertFalse(close.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await joined
            self.assertEqual(finished, ["original close settled"])
            self.assertTrue(close.done())
            self.assertFalse(terminals.tasks)

        asyncio.run(cancelled_drain())

    def test_connection_generation_and_ledger_semantics(self):
        collector = core.Collector()
        pool = SimpleNamespace(checkedout=lambda: 1, checkedin=lambda: 4, overflow=lambda: 0)
        ledger = Lifecycle(collector, pool, lambda: "a")
        record = object()
        ledger.checkout(None, record, None)
        self.assertIsNone(collector.events[-1]["generation"])
        self.assertEqual(collector.events[-1]["origin"], "unknown_pre_observation")
        ledger.checkin(None, record)
        self.assertEqual(collector.events[-1]["held_ledger"], 0)
        self.assertEqual(collector.events[-1]["pool_checkedout"], 1)
        self.assertEqual(collector.events[-1]["availability"], "not_yet_pool_return")
        ledger.created(record)
        first = ledger.identity(record)
        ledger.invalidate(None, record, None)
        ledger.created(record)
        second = ledger.identity(record)
        self.assertEqual(first["record"], second["record"])
        self.assertGreater(second["generation"], first["generation"])
        failed_record = object()
        ledger.checkin(None, failed_record)
        self.assertFalse(collector.events[-1]["owned_checkout"])
        self.assertIsNone(collector.events[-1]["generation"])
        self.assertFalse(collector.faults)

    def test_minimal_detailed_fields_and_transparent_restoration(self):
        # Actual observer's minimal context has no dependency on detailed imports.
        instance = Observation.__new__(Observation)
        instance.collector = core.Collector()
        instance.installed = []
        baseline = {"sql": 3, "checkout": 1, "checkin": 1, "hold_ms": [1.0]}
        state = []

        @contextmanager
        def watching():
            state.append("baseline_begin")
            try:
                yield
            finally:
                state.append("baseline_end")

        instance.aggregate = SimpleNamespace(watching=watching, row=lambda tag: baseline)
        instance.detailed = lambda: (_ for _ in ()).throw(
            AssertionError("minimal installed detail")
        )
        with instance.watching("M"):
            self.assertEqual(instance.installed, [])
            self.assertEqual(instance.row("x", "M")["detail_events"], 0)
            self.assertFalse(instance.row("x", "M")["detail_mode"])
        self.assertEqual(state, ["baseline_begin", "baseline_end"])
        with self.assertRaisesRegex(RuntimeError, "original"), instance.watching("M"):
            raise RuntimeError("original")
        self.assertEqual(state[-1], "baseline_end")
        instance.collector.emit("x", "detail")
        self.assertTrue(instance.row("x", "D")["detail_mode"])
        self.assertEqual(instance.row("x", "D")["detail_events"], 1)
        self.assertEqual(baseline, instance.aggregate.row("x"))

    def test_lag_bounds_and_no_catchup(self):
        collector = core.Collector()
        now = [0.0]
        done = asyncio.Event()
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)
            now[0] += 0.210
            if len(sleeps) == 3:
                done.set()

        asyncio.run(core.sample_lag(collector, 1, done, lambda: now[0], sleep))
        self.assertEqual(sleeps, [0.010, 0.010, 0.010])
        self.assertEqual(len(collector.lag), 2)
        self.assertTrue(all(abs(row["lag_ms"] - 200) < 0.001 for row in collector.lag))
        with patch.object(core, "LAG_SAMPLES", 2):
            collector.lag_sample(1, 1, 2)
            self.assertEqual(len(collector.lag), 2)
            self.assertIn("lag_cap", collector.faults)

    def test_complete_summary_error_missing_populations(self):
        planned, rows, starts = complete()
        rows[0].update(outcome="timeout", latency_ms=900.0)
        rows[1].update(outcome="error", latency_ms=800.0)
        rows[2].update(outcome="missing", latency_ms=None)
        rows[3].update(outcome="missing", latency_ms=None)
        starts = [row for row in starts if row["id"] != rows[3]["id"]]
        summary = core.analyze(planned, rows, starts, events_for(rows), [])
        cell = summary["cells"][0]
        self.assertEqual(
            (cell["scheduled"], cell["observed"], cell["errors"], cell["missing"]), (100, 98, 2, 2)
        )
        self.assertEqual(cell["receipt_population"], {"0": 34, "2": 33, "100": 33})
        self.assertEqual(cell["latency"]["max_ms"], 900)
        self.assertEqual(cell["success_only"]["max_ms"], 1)
        self.assertEqual(summary["started_missing"], [rows[2]["id"]])
        self.assertEqual(summary["not_started"], [rows[3]["id"]])
        self.assertEqual(len(summary["cohorts"]), 16)
        self.assertFalse(summary["gate"])

    def test_deterministic_analysis_and_validation_corruption(self):
        planned, rows, starts = complete()
        tag = rows[0]["id"]
        ordinary = events_for(rows)
        events = [
            dict(attempt=tag, kind="acquisition_begin", ns=10, seq=0, span=999999),
            dict(attempt=tag, kind="acquisition_error", ns=1000010, seq=1, span=999999),
        ]
        events.extend(dict(row, ns=row["ns"] + 1000010, seq=row["seq"] + 2) for row in ordinary)
        rows[0]["detail_events"] += 2
        expected = core.analyze(planned, rows, starts, events, [])
        self.assertEqual(expected, core.analyze(planned, list(reversed(rows)), starts, events, []))
        self.assertEqual(expected["cells"][0]["intervals"]["acquisition"]["max_ms"], 1)
        corruptions = []
        bad = copy.deepcopy(rows)
        bad[0]["lane"] = "new"
        corruptions.append((planned, bad, starts, events, []))
        bad = copy.deepcopy(rows)
        bad[0]["latency_ms"] = math.nan
        corruptions.append((planned, bad, starts, events, []))
        corruptions.append((planned, rows + [rows[0]], starts, events, []))
        corruptions.append((planned, rows, starts + [starts[0]], events, []))
        bad = copy.deepcopy(events)
        bad[1]["ns"] = 1
        corruptions.append((planned, rows, starts, bad, []))
        bad = copy.deepcopy(events)
        bad[0]["attempt"] = rows[200]["id"]
        corruptions.append((planned, rows, starts, bad, []))
        bad = copy.deepcopy(events)
        bad[1]["span"] = 2
        corruptions.append((planned, rows, starts, bad, []))
        corruptions.append((planned, rows, starts, events, [dict(cell=3, ns=1, lag_ms=0)]))
        for inputs in corruptions:
            with self.assertRaises(ValueError):
                core.analyze(*inputs)
        for kind, field, value in (
            ("checkin_callback", "attempt", rows[1]["id"]),
            ("checkout", "held_ledger", 99),
            ("checkout", "generation", 77),
            ("pool_return_complete", "record", 99999),
        ):
            bad = copy.deepcopy(events)
            next(row for row in bad if row["kind"] == kind)[field] = value
            with self.assertRaises(ValueError):
                core.analyze(planned, rows, starts, bad, [])
        missing = events[:-1]
        with self.assertRaises(ValueError):
            core.analyze(planned, rows, starts, missing, [])
        counts = {row["id"]: row["detail_events"] for row in rows if row["mode"] == "D"}
        retention = dict(
            buffered_events=len(events),
            retained_events=len(missing),
            missing_events=1,
            buffered_lag=0,
            retained_lag=0,
            missing_lag=0,
            attempt_event_counts=counts,
            dropped_event_counts={},
            faults=["detail_output_cap"],
        )
        truncated = core.analyze(planned, rows, starts, missing, [], retention)
        self.assertFalse(truncated["gate"])
        self.assertEqual(sum(value["missing"] for value in truncated["terminal_pairs"].values()), 1)
        # Actual retained R15 external XML has empty classname, not a guessed module.
        self.assertEqual(
            gate.xml_identity(
                "/work/r12/test_minimal_observer_builder_integration.py::test_external"
            ),
            ("", "test_external"),
        )
        self.assertEqual(
            gate.xml_identity("/work/r17/test_r17_offline.py::OfflineControls::test_x"),
            (".OfflineControls", "test_x"),
        )
        # Harness pins backend -c for isolated files too; pre_e1's uncontrolled
        # campaign filename root must remain rejected, not silently accepted.
        campaign = "::test_one_fixed_800_checkout_lifecycle_campaign"
        campaign_xml = ("", "test_one_fixed_800_checkout_lifecycle_campaign")
        with patch.object(gate, "collected", return_value=[campaign]):
            self.assertEqual(gate.expected_group("unused", "campaign"), [campaign])
        self.assertEqual(gate.xml_identity(campaign), campaign_xml)
        for wrong in (
            ["test_r17_campaign.py" + campaign],
            ["other/" + campaign],
            [campaign + "_wrong"],
            [campaign, campaign],
        ):
            with (
                patch.object(gate, "collected", return_value=wrong),
                self.assertRaises(AssertionError),
            ):
                gate.expected_group("unused", "campaign")
        with tempfile.TemporaryDirectory(prefix="codex-tmp-r17-xml-20261009-") as directory:
            output = core.Output(directory)
            # Output is not used for XML; source fixtures are tiny bounded test data.
            path = Path(directory) / "result.xml"
            import xml.etree.ElementTree as ET

            suite = ET.Element("testsuite", tests="1", failures="0", errors="0", skipped="0")
            ET.SubElement(suite, "testcase", classname="", name="test_external")
            ET.ElementTree(suite).write(path)
            gate.junit(
                path, 1, ["/work/r12/test_minimal_observer_builder_integration.py::test_external"]
            )
            with self.assertRaises(AssertionError):
                gate.junit(
                    path, 1, ["/work/r12/test_minimal_observer_builder_integration.py::test_wrong"]
                )
            case = suite.find("testcase")
            case.set("classname", campaign_xml[0])
            case.set("name", campaign_xml[1])
            ET.ElementTree(suite).write(path)
            gate.junit(path, 1, [campaign])
            case.set("classname", "test_r17_campaign")
            ET.ElementTree(suite).write(path)
            with self.assertRaises(AssertionError):
                gate.junit(path, 1, [campaign])
            output.close()


if __name__ == "__main__":
    unittest.main()
