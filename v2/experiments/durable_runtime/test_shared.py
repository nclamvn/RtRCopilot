import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from shared import MANIFEST_SHA256, connection, execute, initialize, make_case, oracle, partial_cases, snapshot
from driver import digest_tree, quantiles, validate


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = self.tmp.name

    def test_source_success_dedup_and_receipt(self):
        case = make_case("success")
        initialize([case], self.state)
        first = execute(case, self.state)
        second = execute(case, self.state)
        self.assertEqual(first, second)
        self.assertEqual(first["spent"], 1)
        self.assertTrue(oracle(case, self.state, first)["pass"])

    def test_false_success_rejected(self):
        case = make_case("forged")
        initialize([case], self.state)
        forged = {"status": "succeeded", "receipt_id": "fake", "spent": 0}
        self.assertFalse(oracle(case, self.state, forged)["pass"])

    def test_parent_budget_shared_not_reset(self):
        cases = [make_case(str(i), parent_id="common", budget_limit=1) for i in range(2)]
        initialize(cases, self.state)
        self.assertEqual(execute(cases[0], self.state)["status"], "succeeded")
        self.assertEqual(execute(cases[1], self.state)["status"], "blocked")
        initialize(cases, self.state)
        self.assertEqual(snapshot(cases[0], self.state)["spent"], 1)

    def test_drift_blocks_before_work(self):
        for scenario in ("approval_drift", "input_drift", "schema_drift", "acl_drift", "stale_owner", "incompatible_version", "unpriced", "budget_exhausted"):
            case = make_case(scenario, scenario)
            initialize([case], self.state)
            outcome = execute(case, self.state)
            self.assertTrue(oracle(case, self.state, outcome)["pass"], scenario)
            self.assertEqual(outcome["spent"], 0)

    def test_actual_final_fence_advance(self):
        case = make_case("old-owner")
        initialize([case], self.state)
        def advance(_):
            with connection(self.state) as conn:
                conn.execute("UPDATE requests SET fence=2 WHERE id=?", (case["id"],))
                conn.execute("UPDATE ownership SET fence=2 WHERE effect_key=?", (case["effect_key"],))
                conn.commit()
        with patch("shared.time.sleep", advance):
            old = execute(case, self.state)
        self.assertEqual(old["status"], "blocked")
        self.assertIsNone(snapshot(case, self.state)["effect"])
        new = execute({**case, "fence": 2}, self.state)
        self.assertEqual(new["status"], "succeeded")
        self.assertEqual(new["spent"], 2)

    def test_actual_final_authorization_revoke(self):
        case = make_case("revoked")
        initialize([case], self.state)
        def revoke(_):
            with connection(self.state) as conn:
                conn.execute("UPDATE requests SET allowed=0 WHERE id=?", (case["id"],))
                conn.commit()
        with patch("shared.time.sleep", revoke):
            outcome = execute(case, self.state)
        self.assertEqual(outcome["status"], "blocked")
        self.assertIsNone(snapshot(case, self.state)["effect"])

    def test_honest_partial_and_ambiguous(self):
        for scenario in ("cancel_partial", "ambiguous", "timeout"):
            case = make_case(scenario, scenario)
            initialize([case], self.state)
            outcome = execute(case, self.state)
            self.assertTrue(oracle(case, self.state, outcome)["pass"])

    def test_unsupported_ambiguous_never_blindly_repeats(self):
        case = make_case("unknown", "ambiguous")
        initialize([case], self.state)
        execute(case, self.state)
        execute(case, self.state)
        self.assertEqual(snapshot(case, self.state)["unsupported_effect_count"], 1)
        self.assertIsNone(snapshot(case, self.state)["effect"])

    def test_concurrent_unsupported_source_cannot_repeat(self):
        case = make_case("unknown-concurrent", "ambiguous")
        initialize([case], self.state)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: execute(case, self.state), range(2)))
        self.assertEqual(snapshot(case, self.state)["unsupported_effect_count"], 1)
        self.assertTrue(all(o["status"] == "needs_review" for o in outcomes))

    def test_partial_two_steps_share_parent(self):
        case = make_case("partial", native_partial=True)
        initialize([case], self.state)
        first, second = partial_cases(case)
        execute(first, self.state)
        self.assertIsNotNone(snapshot(first, self.state)["effect"])
        self.assertIsNone(snapshot(second, self.state)["effect"])
        self.assertEqual(snapshot(second, self.state)["spent"], 1)

    def test_quantiles_finite_nearest_rank(self):
        self.assertEqual(quantiles(list(range(100))), {"n": 100, "p50": 49, "p95": 94, "p99": 98})
        self.assertEqual(quantiles([])["p95"], None)

    def test_validator_missing_trials_and_digest(self):
        root = Path(self.state)
        (root / "index.json").write_text(json.dumps({"manifest_sha256": "wrong", "engines": ["direct"], "trials": []}))
        (root / "provenance.json").write_text(json.dumps({"source_hashes": {}}))
        (root / "digests.json").write_text(json.dumps(digest_tree(root)))
        verdict = validate(root)
        self.assertFalse(verdict["pass"])
        self.assertIn("missing_or_extra_trials:direct", verdict["errors"])
        (root / "index.json").write_text("{}")
        self.assertFalse(validate(root)["pass"])

    def test_digest_covers_sqlite_snapshot(self):
        case = make_case("snapshot")
        initialize([case], self.state)
        before = digest_tree(Path(self.state))
        execute(case, self.state)
        after = digest_tree(Path(self.state))
        self.assertNotEqual(before, after)

    def test_validator_rejects_false_success_with_recomputed_digests(self):
        root = Path(self.state)
        trial = root / "direct-false-success"
        trial.mkdir()
        case = make_case("forged-final")
        initialize([case], str(trial / "state"))
        (trial / "requests.json").write_text(json.dumps([case]))
        record = {"id": case["id"], "result": {"status": "succeeded", "receipt_id": "forged", "spent": 0}, "elapsed_ms": 1}
        (trial / "records-0.json").write_text(json.dumps([record]))
        summary = {"pass": True, "scenario": "success", "attempts": [{"timeout": False, "returncode": 0}], "latency_ms": quantiles([1])}
        (trial / "summary.json").write_text(json.dumps(summary))
        (root / "index.json").write_text(json.dumps({"manifest_sha256": MANIFEST_SHA256, "engines": ["direct", "dbos", "temporal"], "trials": [{"path": trial.name, "pass": True}]}))
        (root / "provenance.json").write_text(json.dumps({"source_hashes": {}}))
        (root / "digests.json").write_text(json.dumps(digest_tree(root)))
        verdict = validate(root)
        self.assertFalse(verdict["pass"])
        self.assertIn("false_success_or_summary_mismatch:direct-false-success", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
