"""Eight fixed stdlib methods; variants are assertions, not extra test selections."""

import copy
import json
import unittest
from unittest.mock import patch

import analyzer as a


class OfflineAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.payloads = a.load_inputs()
        cls.data = a.parse(cls.payloads)

    def fresh(self):
        return copy.deepcopy(self.data)

    def test_01_real_population_and_pins(self):
        rows = a.validate(*self.fresh())
        self.assertEqual((len(rows), sum(len(row["hold_ms"]) for row in rows)), (800, 1600))
        self.assertEqual((self.manifest["input_file_count"], self.manifest["total_input_bytes"]),
                         (14, 564033))
        self.assertEqual(set(row["id"] for row in rows), set(row["id"] for row in a.expected_schedule()))
        original_read = a.Path.read_bytes
        def corrupted_read(path):
            payload = original_read(path)
            return payload + b" " if path.name == "outcomes.jsonl" else payload
        with patch.object(a.Path, "read_bytes", corrupted_read), self.assertRaisesRegex(ValueError, "binding"):
            a.load_inputs()
        with patch.object(a.Path, "read_bytes", return_value=b"{}"), self.assertRaisesRegex(ValueError, "manifest"):
            a.load_inputs()
        with self.assertRaisesRegex(ValueError, "path"):
            a.bounded_path(a.ROOT, "../outside")
        with self.assertRaisesRegex(ValueError, "path"):
            a.bounded_path(a.ROOT, "/absolute")
        data = self.fresh()
        data[2][0]["sql"] = 3
        with self.assertRaisesRegex(ValueError, "count"):
            a.validate(*data)

    def test_02_nearest_rank_and_ties(self):
        self.assertEqual(a.nearest([]), dict(p50_ms=None, p95_ms=None, p99_ms=None, max_ms=None))
        self.assertEqual(set(a.nearest([3]).values()), {3})
        self.assertEqual(a.nearest([2, 1, 2, 1])["p50_ms"], 1)
        self.assertEqual(a.nearest(list(range(1, 101))),
                         dict(p50_ms=50, p95_ms=95, p99_ms=99, max_ms=100))

    def test_03_duplicate_and_missing_ids(self):
        for index in (0, 1, 2):
            for mutation in ("duplicate", "missing"):
                data = self.fresh()
                if mutation == "duplicate":
                    data[index].append(copy.deepcopy(data[index][0]))
                else:
                    data[index].pop()
                with self.subTest(index=index, mutation=mutation), self.assertRaises(ValueError):
                    a.validate(*data)
        data = self.fresh()
        data[1][0]["id"] = "unknown"
        with self.assertRaises(ValueError):
            a.validate(*data)

    def test_04_finite_and_hold_faults(self):
        for key in ("latency_ms", "start_offset_ms", "slot_wait_ms"):
            for value in (float("nan"), float("inf"), -1, True):
                data = self.fresh()
                data[2][0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    a.validate(*data)
        for holds in ([], [1], [float("nan"), 1, 1], [-1, 1, 1], [100, 100, 100]):
            data = self.fresh()
            data[2][0]["hold_ms"] = holds
            with self.subTest(holds=holds), self.assertRaises(ValueError):
                a.validate(*data)
        data = self.fresh()
        data[1][0]["launch_offset_ms"] = float("inf")
        with self.assertRaises(ValueError):
            a.validate(*data)

    def test_05_summary_mismatch(self):
        for key, value in (("p95_ms", 140.988001), ("observed", 99),
                           ("receipt_population", {"0": 33, "2": 34, "100": 33})):
            data = self.fresh()
            data[3]["cells"][4][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "summary cell"):
                a.validate(*data)
        data = self.fresh()
        data[3]["relative_fixture_observations"][2]["new_minus_legacy_p95_percent"] = 0
        with self.assertRaisesRegex(ValueError, "relative"):
            a.validate(*data)

    def test_06_cohort_coverage_and_bins(self):
        rows = a.validate(*self.fresh())
        cells = a.cohorts(rows)
        self.assertEqual(len(cells), 8)
        for cell in cells:
            self.assertEqual(cell["full"]["count"], 100)
            self.assertEqual([group["count"] for group in cell["receipt_count"]], [34, 33, 33])
            for field in ("receipt_count", "ordinal_quartile", "launch_wave_proxy", "service_start_bin"):
                self.assertEqual(sum(group["count"] for group in cell[field]), 100)
                self.assertEqual(sum(group["hold_samples"] for group in cell[field]),
                                 300 if cell["lane"] == "legacy" else 100)
            self.assertEqual([group["count"] for group in cell["ordinal_quartile"]], [25] * 4)
            self.assertEqual(len(cell["launch_wave_proxy"]), 100 // cell["concurrency"])
        self.assertEqual([a.time_bin(value, 0, 100) for value in (0, 25, 50, 75, 100)], [0, 1, 2, 3, 3])
        self.assertEqual(a.time_bin(7, 7, 7), 0)

    def test_07_matched_arithmetic_and_pairs(self):
        rows = a.validate(*self.fresh())
        pairs = a.pairs(rows)
        self.assertEqual(len(pairs), 400)
        self.assertEqual(len({(row["concurrency"], row["ordinal"]) for row in pairs}), 400)
        for row in rows:
            self.assertAlmostEqual(row["hold_sum_ms"], sum(row["hold_ms"]), places=5)
            self.assertAlmostEqual(row["unclassified_remainder_ms"],
                                   row["latency_ms"] - sum(row["hold_ms"]), places=5)
        for row in pairs:
            for key in a.METRICS:
                self.assertAlmostEqual(row["new_minus_legacy_" + key],
                                       row["new_" + key] - row["legacy_" + key], places=5)
        cell = next(cell for cell in a.cohorts(rows) if cell["concurrency"] == 25 and cell["lane"] == "new")
        self.assertEqual(cell["full"]["metrics"]["latency_ms"]["p95_ms"], 304.490083)

    def test_08_deterministic_bytes(self):
        first = a.outputs(a.validate(*self.fresh()))
        second = a.outputs(a.validate(*self.fresh()))
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"cohort-summary.json", "c25-tail.csv", "ordinal-pairs.csv"})
        self.assertLess(sum(map(len, first.values())), a.CAP)
        self.assertEqual(len(first["c25-tail.csv"].splitlines()), 31)
        self.assertEqual(len(first["ordinal-pairs.csv"].splitlines()), 401)
        self.assertEqual(json.loads(first["cohort-summary.json"])["population"]["requests"], 800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
