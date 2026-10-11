#!/usr/bin/env python3
"""Adversarial tests against strict independent verifier on disposable copies."""
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
import research

ORIGINAL = research.ROOT

class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rtr_research_verify_")
        research.ROOT = Path(self.temp.name) / "research"
        shutil.copytree(ORIGINAL, research.ROOT, ignore=shutil.ignore_patterns("__pycache__"))
    def tearDown(self):
        research.ROOT = ORIGINAL
        self.temp.cleanup()
    def run_verify(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return research.verify()
    def mutate_claim(self, field, value):
        path = research.ROOT / "claims.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        rows[0][field] = value
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    def test_clean_positive_control(self):
        self.assertEqual(self.run_verify(), 0)
    def test_raw_snapshot_tamper(self):
        path = research.ROOT / "snapshots" / "mcp-authorization.html"
        path.write_bytes(path.read_bytes() + b"tamper")
        self.assertEqual(self.run_verify(), 2)
    def test_normalized_view_tamper(self):
        path = research.ROOT / "read_views" / "mcp-authorization.txt"
        path.write_text(path.read_text() + "tamper")
        self.assertEqual(self.run_verify(), 2)
    def test_invented_span(self):
        self.mutate_claim("evidence_span", "INVENTED RESEARCH EVIDENCE NOT IN THE RAW SNAPSHOT")
        self.assertEqual(self.run_verify(), 2)
    def test_false_independent_origin(self):
        path = research.ROOT / "claims.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        rows[0]["capture"]["source"] = "MCP-mirror-false-independent-source"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual(self.run_verify(), 2)
    def test_missing_scope(self):
        self.mutate_claim("scope", "proven-performance")
        self.assertEqual(self.run_verify(), 2)
    def test_inferred_claim(self):
        self.mutate_claim("extraction", "inferred")
        self.assertEqual(self.run_verify(), 2)
    def test_page_claim_budget(self):
        path = research.ROOT / "claims.jsonl"
        rows = path.read_text().splitlines()
        path.write_text("\n".join(rows + [rows[0]]) + "\n")
        self.assertEqual(self.run_verify(), 2)
    def test_exact_but_overlong_quote(self):
        raw = (research.ROOT / "snapshots" / "mcp-authorization.html").read_text()
        self.mutate_claim("evidence_span", re.search(r"(?:\S+\s+){30}\S+", raw).group())
        self.assertEqual(self.run_verify(), 2)
    def test_hidden_denominator(self):
        path = research.ROOT / "domain.yaml"
        path.write_text(path.read_text().replace("estimate: 24", "estimate: 2400"))
        self.assertEqual(self.run_verify(), 2)
    def test_engine_tamper(self):
        path = research.ROOT / "vendor" / "refinery.py"
        path.write_bytes(path.read_bytes() + b"\n# tamper\n")
        self.assertEqual(self.run_verify(), 2)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(VerificationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    research.dump(ORIGINAL / "output" / "independent-negative-tests.json", {"tests":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"passed":result.wasSuccessful(),"tests_include":"positive control; raw/view tamper; invented span; false source independence; missing scope; inference; claim budget; exact overlong quotation; denominator; engine integrity"})
    raise SystemExit(0 if result.wasSuccessful() else 1)
