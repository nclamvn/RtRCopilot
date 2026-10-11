"""Exactly six stdlib controls. No product imports, runtime, SQL or process signals."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import env_contract as gate


class EnvironmentControls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-tmp-r20-controls-20261009-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = dict(
            POSTGRES_DSN=gate.DSN,
            INTEGRATION_DATABASE_DSN=gate.DSN,
            ACTION_EXECUTOR_ENABLED="false",
            RAG_EMBEDDING_PROVIDER="offline",
            RAG_PROVIDER_MODE="local",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            LIMITS_RATE_RENDER_MAX="30",
            LIMITS_RATE_DEFAULT_READ_MAX="120",
            LIMITS_RATE_WINDOW_SECONDS="60",
            ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS="0.9",
        )

    def test_exact_domain_environment_and_import_order(self):
        self.assertEqual(gate.environment(self.env), gate.DATABASE)
        source = (gate.HERE / "test_r20_bootstrap.py").read_text()
        self.assertLess(
            source.index("environment(os.environ)"), source.index("from pydantic import")
        )
        positive = source.split("async def test_same_", 1)[1]
        self.assertLess(
            positive.index("environment(os.environ)"), positive.index("from sqlalchemy")
        )
        self.assertIn("context_dsn == DATABASE_DSN == DSN", positive)

    def test_missing_mismatch_and_unsafe_rejected_before_effects(self):
        effects = []
        for key in ("POSTGRES_DSN", "INTEGRATION_DATABASE_DSN"):
            for bad in (
                None,
                "",
                " " + gate.DSN,
                gate.DSN + "?sslmode=require",
                gate.DSN.replace("tip054-pg", "example.com"),
                gate.DSN.replace(gate.DATABASE, "postgres"),
                gate.DSN.replace("rtr_app", "postgres"),
            ):
                env = dict(self.env, **{key: bad})
                with self.assertRaises(ValueError):
                    gate.environment(env)
                    effects.extend(("spawn", "CREATE", "marker"))
            env = dict(self.env)
            del env[key]
            with self.assertRaises(ValueError):
                gate.environment(env)
        for bad in ("", None, False, "postgresql://engine"):
            with self.assertRaises(ValueError):
                gate.environment(dict(self.env, ACTION_WORKFLOW_DSN=bad))
        self.assertEqual(effects, [])
        source = (gate.HERE / "run-bootstrap-closure.sh").read_text()
        prelude = source.split("\nmkdir -p", 1)[0]
        # Explicit fake filesystem seam; the real environment guard and script logic remain.
        prelude = prelude.replace(
            'evidence="$repo/v2/experiments/action_executor/raw/$fixture/r19/r20_bootstrap_e1"',
            'evidence="$CASE_ROOT/never-created"',
        )
        setup = 'python3() { return 0; }; command() { printf "%s\\n" "$REAL_PYTHON"; };\n'
        base = dict(
            R20_MAIN_ADMISSION="bootstrap",
            R20_SOURCE_REVIEW="unused",
            R20_SOURCE_REVIEW_SHA256="unused",
            REAL_PYTHON=sys.executable,
            CASE_ROOT=str(self.root),
        )
        for supplied, admitted in (
            ({}, False),
            ({"POSTGRES_DSN": gate.DSN}, False),
            ({"POSTGRES_DSN": gate.DSN, "INTEGRATION_DATABASE_DSN": "foreign"}, False),
            ({"POSTGRES_DSN": gate.DSN, "INTEGRATION_DATABASE_DSN": gate.DSN}, True),
        ):
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    setup + prelude + "\necho EFFECT_ENTERED\n",
                    str(gate.HERE / "run-bootstrap-closure.sh"),
                    "source-binding-e1.json",
                ],
                env={**base, **supplied},
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode == 0, admitted, result.stderr)
            self.assertEqual("EFFECT_ENTERED" in result.stdout, admitted)

    def test_protected_source_raw_marker_and_drift_rejection(self):
        # Full actual transitive source/raw gates are also run before/after by the harness.
        path = self.root / "source.json"
        expected = {"files": {"new": "pinned"}}
        path.write_text(json.dumps({"files": {"new": "drift"}}))
        with patch.object(gate, "snapshot", return_value=expected), self.assertRaises(ValueError):
            gate.source(path)
        self.assertEqual(
            gate.BINDING_SHA, "ebab6389b79674cd6a90110227ed02f9dce019c45b2ee299091ca337bebb21f4"
        )
        marker = gate.prior.r18.content(gate.ROOT, gate.prior.RAW + "/campaign-launch.json")
        self.assertTrue(json.loads(marker)["consumed"])
        self.assertEqual(
            gate.digest(marker), "bd5d22631a2613859f0611a98778e69c4fbbe207f4b44254a46ac19c7f3f5c9b"
        )

    def test_exact_selection_records_and_zero_skip_conservation(self):
        expected = [gate.prior.r18.normalized_nodeid(node) for node in gate.selectors()]
        self.assertEqual(len(expected), len(set(expected)))
        self.assertEqual(len(expected), 8)
        collection = self.root / "collection.txt"
        collection.write_text("\n".join(expected))
        gate.collection(collection)
        collection.write_text("\n".join(expected[:-1]))
        with self.assertRaises(ValueError):
            gate.collection(collection)
        tree = ET.Element("testsuites")
        suite = ET.SubElement(tree, "testsuite", tests="8", failures="0", errors="0", skipped="0")
        for node in gate.selectors():
            classname, name = gate.prior.r18.xml_identity(node)
            ET.SubElement(suite, "testcase", classname=classname, name=name)
        result = self.root / "result.xml"
        ET.ElementTree(tree).write(result)
        gate.prior.r18.junit(result, gate.selectors())
        ET.SubElement(suite[0], "skipped")
        ET.ElementTree(tree).write(result)
        with self.assertRaises(ValueError):
            gate.prior.r18.junit(result, gate.selectors())

    def test_owned_fixture_budget_cap_and_cleanup_contract(self):
        packet = gate.manifest()
        self.assertEqual(
            (packet["child_seconds"], packet["cleanup_seconds"], packet["raw_bytes"]),
            (120, 10, 10485760),
        )
        self.assertEqual(packet["supervisor_stage"], "pre")
        self.assertEqual(packet["evidence"], "/evidence/r19/r20_bootstrap_e1")
        source = (gate.HERE / "run-bootstrap-closure.sh").read_text()
        self.assertIn("/work/r19/bounded.py", source)
        self.assertNotIn("bounded.py load", source)
        self.assertIn("uncertain_create", source)
        self.assertIn('[[ -z "$active_pid" ]]', source)
        self.assertLess(source.index("environment >"), source.index("create_domain"))
        self.assertIn('drained "$evidence/', source)
        with self.assertRaises(ValueError):
            gate.prior.r18.safe_path(self.root, "../foreign")
        stop = (
            "stop_active() {" + source.split("stop_active() {", 1)[1].split("\ncleanup() {", 1)[0]
        )
        cleanup = "cleanup() {" + source.split("cleanup() {", 1)[1].split("\ncapacity() {", 1)[0]
        finish = "finish() {" + source.split("finish() {", 1)[1].split("\ntrap finish", 1)[0]
        for stop_code, proof_code, uncertain, expected_drop in (
            (1, 0, "", False),
            (0, 1, "", False),
            (0, 0, "unknown", False),
            (0, 0, "", True),
        ):
            setup = """set -euo pipefail
evidence=$1
container_evidence=/evidence/r19/r20_bootstrap_e1
r20_dir=unused
active_pid=123
active_label=probe
owned_database=rtr_tip054_r20_local_e1
stop_code=$2
proof_code=$3
uncertain_create=$4
exec_runner() { return "$stop_code"; }
python3() { return "$proof_code"; }
kill() { return 1; }
wait() { return 0; }
pg_sql() { printf '%s\\n' "$*" >> "$evidence/drops"; }
absence() { echo 0; }
source_check() { printf 'STATE:%s:%s\\n' "$active_pid" "$owned_database"; }
fixture_check() { return 0; }
capacity() { return 0; }
"""
            drop = self.root / "drops"
            drop.unlink(missing_ok=True)
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    setup + stop + "\n" + cleanup + "\n" + finish + "\ntrue; finish\n",
                    "control",
                    str(self.root),
                    str(stop_code),
                    str(proof_code),
                    uncertain,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(drop.exists(), expected_drop, result.stderr)
            self.assertEqual(result.returncode, 0 if expected_drop else 1, result.stderr)
            if expected_drop:
                self.assertIn('DROP DATABASE "rtr_tip054_r20_local_e1";', drop.read_text())
                self.assertEqual(len(drop.read_text().splitlines()), 1)
            if stop_code or proof_code:
                self.assertIn(
                    "STATE:123:rtr_tip054_r20_local_e1",
                    (self.root / "source-after.txt").read_text(),
                )

    def test_seed_only_scope_and_truthful_readiness_ledger(self):
        packet = gate.manifest()
        self.assertEqual(
            (packet["candidate"], packet["executor"], packet["tip054_5"]),
            ("NOT_READY", "OFF", "BLOCKED"),
        )
        source = (gate.HERE / "run-bootstrap-closure.sh").read_text()
        for forbidden in (
            "runpy",
            "latency_probe.py",
            "ALTER ROLE",
            "FLUSH",
            "campaign-launch",
            "ACTION_EXECUTOR_ENABLED=true",
            "CREATE DATABASE.*engine",
        ):
            self.assertNotIn(forbidden, source)
        mutant = copy.deepcopy(packet)
        mutant["groups"]["positive"].append(mutant["groups"]["negative"][0])
        path = self.root / "mutant.json"
        path.write_text(json.dumps(mutant))
        with self.assertRaises(ValueError):
            gate.manifest(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
