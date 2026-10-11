"""Five pure offline controls against retained data; no application imports."""

import copy
import unittest

import analyzer as a


class DiagnosisControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = a.loads(a.safe(a.RAW + "/run/samples.json").read_bytes())
        cls.log = a.safe(a.RAW + "/load.stderr.txt").read_text()

    def test_exact_quantiles_and_population_conservation(self):
        seen, missing, cells = a.reconstruct(self.rows)
        summary = a.loads(a.safe(a.RAW + "/run/latency-summary.json").read_bytes())
        self.assertTrue(a.exact(cells, summary["cells"]))
        self.assertEqual((len(seen), len(missing), sum(c["pass"] for c in cells)), (1440, 160, 10))
        self.assertEqual(a.quantile(list(range(1, 101)), .95), 95)
        self.assertEqual(a.quantile(list(range(1, 21)), .95), 19)
        self.assertEqual(a.quantile([], .95), None)

    def test_rows_types_duplicates_order_and_unknown_descendants(self):
        for name, value in (("profile", True), ("case", False), ("elapsed_ms", float("nan")),
                            ("http_status", True), ("state", "draft"), ("error_code", "unknown")):
            changed = copy.deepcopy(self.rows)
            changed[0][name] = value
            with self.assertRaises(ValueError):
                a.reconstruct(changed)
        for rows in (self.rows + [self.rows[0]], self.rows[1:], list(reversed(self.rows))):
            with self.assertRaises(ValueError):
                a.reconstruct(rows)

    def test_full_log_identity_ambiguity_and_timer_rejection(self):
        logs, counts = a.request_logs(self.log)
        self.assertEqual((len(logs), counts["seed_audit_events"]), (1440, 3))
        seen, _, _ = a.reconstruct(self.rows)
        self.assertEqual(set(logs), set(seen))
        self.assertTrue(all(logs[key]["status"] == row["http_status"] for key, row in seen.items()))
        request = next(line for line in self.log.splitlines() if '"event": "request"' in line)
        with self.assertRaises(ValueError):
            a.request_logs(self.log + "\n" + request)
        for bad in (request.replace("1-0-admission", "1-00-admission"),
                    request.replace("276.37", "NaN"),
                    request.replace('"status": 201', '"status": true')):
            with self.assertRaises(ValueError):
                a.request_logs(bad)

    def test_strict_json_aliases_and_duplicate_fields(self):
        self.assertFalse(a.exact({"value": True}, {"value": 1}))
        self.assertFalse(a.exact({"value": 100}, {"value": 100.0}))
        for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                a.loads(data)
        with self.assertRaises(ValueError):
            a.exact({"value": float("nan")}, {})

    def test_binding_drift_and_path_escape_fail_loud(self):
        for path in ("../foreign", "/etc/passwd", "v2//foreign", "./v2/foreign"):
            with self.assertRaises(ValueError):
                a.safe(path)
        with self.assertRaises(ValueError):
            a.verify({"direct": {a.RAW + "/run/samples.json": "0" * 64}, "links": {}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
