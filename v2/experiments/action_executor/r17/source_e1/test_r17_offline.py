"""Exactly eight unique offline controls, stdlib unittest and pytest compatible."""

import asyncio
import copy
import json
import math
import tempfile
import unittest
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import patch

import diagnostic as core
from observer import Lifecycle, Observation


def complete():
    planned = core.schedule()
    rows = [dict(item, outcome="success", latency_ms=1.0) for item in planned]
    starts = [dict(id=item["id"], launch_offset_ms=float(n)) for n, item in enumerate(planned)]
    return planned, rows, starts


class OfflineControls(unittest.TestCase):
    def test_ids_time_order_and_finite_values(self):
        planned = core.schedule()
        self.assertEqual(len({row["id"] for row in planned}), 800)
        self.assertEqual([planned[n*100]["mode"] + "-" + planned[n*100]["lane"]
                          for n in range(8)], list(core.ORDER))
        for lane in ("legacy", "new"):
            for mode in ("D", "M"):
                positions = [n+1 for n, label in enumerate(core.ORDER) if label == mode + "-" + lane]
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
        instance.detailed = lambda: (_ for _ in ()).throw(AssertionError("minimal installed detail"))
        with instance.watching("M"):
            self.assertEqual(instance.installed, [])
            self.assertEqual(instance.row("x", "M")["detail_events"], 0)
            self.assertFalse(instance.row("x", "M")["detail_mode"])
        self.assertEqual(state, ["baseline_begin", "baseline_end"])
        with self.assertRaisesRegex(RuntimeError, "original"):
            with instance.watching("M"):
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
            now[0] += .210
            if len(sleeps) == 3:
                done.set()
        asyncio.run(core.sample_lag(collector, 1, done, lambda: now[0], sleep))
        self.assertEqual(sleeps, [.010, .010, .010])
        self.assertEqual(len(collector.lag), 2)
        self.assertTrue(all(abs(row["lag_ms"] - 200) < .001 for row in collector.lag))
        with patch.object(core, "LAG_SAMPLES", 2):
            collector.lag_sample(1, 1, 2)
            self.assertEqual(len(collector.lag), 2)
            self.assertIn("lag_cap", collector.faults)

    def test_complete_summary_error_missing_populations(self):
        planned, rows, starts = complete()
        rows[0].update(outcome="timeout", latency_ms=900.)
        rows[1].update(outcome="error", latency_ms=800.)
        rows[2].update(outcome="missing", latency_ms=None)
        rows[3].update(outcome="missing", latency_ms=None)
        starts = [row for row in starts if row["id"] != rows[3]["id"]]
        summary = core.analyze(planned, rows, starts, [], [])
        cell = summary["cells"][0]
        self.assertEqual((cell["scheduled"], cell["observed"], cell["errors"], cell["missing"]),
                         (100, 98, 2, 2))
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
        events = [dict(attempt=tag, kind="acquisition_begin", ns=10, seq=0, span=1),
                  dict(attempt=tag, kind="acquisition_error", ns=1000010, seq=1, span=1)]
        expected = core.analyze(planned, rows, starts, events, [])
        self.assertEqual(expected, core.analyze(planned, list(reversed(rows)), starts, events, []))
        self.assertEqual(expected["cells"][0]["intervals"]["acquisition"]["max_ms"], 1)
        corruptions = []
        bad = copy.deepcopy(rows); bad[0]["lane"] = "new"; corruptions.append((planned, bad, starts, events, []))
        bad = copy.deepcopy(rows); bad[0]["latency_ms"] = math.nan; corruptions.append((planned, bad, starts, events, []))
        corruptions.append((planned, rows + [rows[0]], starts, events, []))
        corruptions.append((planned, rows, starts + [starts[0]], events, []))
        bad = copy.deepcopy(events); bad[1]["ns"] = 1; corruptions.append((planned, rows, starts, bad, []))
        bad = copy.deepcopy(events); bad[0]["attempt"] = rows[200]["id"]; corruptions.append((planned, rows, starts, bad, []))
        bad = copy.deepcopy(events); bad[1]["span"] = 2; corruptions.append((planned, rows, starts, bad, []))
        corruptions.append((planned, rows, starts, events, [dict(cell=3, ns=1, lag_ms=0)]))
        for inputs in corruptions:
            with self.assertRaises(ValueError):
                core.analyze(*inputs)


if __name__ == "__main__":
    unittest.main()
