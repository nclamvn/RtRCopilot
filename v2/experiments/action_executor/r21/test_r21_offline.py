"""Six finite stdlib controls; no product imports, SQL, Docker or signals."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import qualification as gate


class R21Controls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-tmp-r21-controls-20261009-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = dict(
            POSTGRES_DSN=gate.DSN,
            INTEGRATION_DATABASE_DSN=gate.DSN,
            ACTION_WORKFLOW_DSN=gate.WORKFLOW,
            ACTION_EXECUTOR_ENABLED="true",
            RAG_EMBEDDING_PROVIDER="offline",
            RAG_PROVIDER_MODE="local",
            OPENAI_API_KEY="",
            ANTHROPIC_API_KEY="",
            LIMITS_RATE_RENDER_MAX="5000",
            LIMITS_RATE_DEFAULT_READ_MAX="5000",
            LIMITS_RATE_WINDOW_SECONDS="60",
            ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS="0.9",
        )

    def rows(self):
        return [
            dict(
                profile=p,
                case=c,
                operation=o,
                elapsed_ms=1.0,
                okay=True,
                http_status=gate.prior.STATUS[o],
                state=gate.prior.STATES[o],
                error_code=None,
            )
            for p, c, o in gate.prior.expected()
        ]

    def write_packet(self, rows=None, code=0):
        root = self.root / "r21_http_e1"
        (root / "run").mkdir(parents=True, exist_ok=True)
        (root / "binding.json").write_text('{"fixed":"source"}')
        (root / "contract.json").write_bytes((gate.HERE / "contract.json").read_bytes())
        marker = self.root / "r21-campaign-launch.json"
        marker.write_text(json.dumps(gate.marker(root / "binding.json")))
        rows = self.rows() if rows is None else rows
        (root / "run/samples.json").write_text(json.dumps(rows))
        (root / "run/samples.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        result = gate.prior.reconstruct(rows)
        (root / "run/latency-summary.json").write_text(
            json.dumps(
                dict(
                    status=result["status"],
                    cells=result["cells"],
                    profile=gate.PROFILE,
                    limits=gate.LIMITS,
                )
            )
        )
        (root / "run/r-controls.json").write_text(json.dumps(gate.CONTROLS))
        owner = {"group": 123, "token": "owned", "cleanup_deadline": None}
        (root / "load.owner.json").write_text(json.dumps(owner))
        (root / "load.process.json").write_text(
            json.dumps(
                dict(
                    owner=owner,
                    exit_code=code,
                    original_exit_code=code,
                    reason="completed",
                    group_drained=True,
                )
            )
        )
        return root

    def test_exact_caller_and_derived_envelopes_before_effects(self):
        gate.envelopes(self.env)
        for key in ("POSTGRES_DSN", "INTEGRATION_DATABASE_DSN", "ACTION_WORKFLOW_DSN"):
            for value in (
                None,
                "",
                "foreign",
                self.env[key] + "?sslmode=require",
                self.env[key] + "#x",
            ):
                with self.assertRaises(ValueError):
                    gate.envelopes(dict(self.env, **{key: value}))
            missing = dict(self.env)
            del missing[key]
            with self.assertRaises(ValueError):
                gate.envelopes(missing)
        pre = dict(
            self.env,
            ACTION_EXECUTOR_ENABLED="false",
            LIMITS_RATE_RENDER_MAX="30",
            LIMITS_RATE_DEFAULT_READ_MAX="120",
        )
        del pre["ACTION_WORKFLOW_DSN"]
        gate.environment(pre, "pre")
        with self.assertRaises(ValueError):
            gate.environment(dict(pre, ACTION_WORKFLOW_DSN=""), "pre")
        shell = (gate.HERE / "run-http-qualification.sh").read_text().split("\nmkdir -p", 1)[0]
        shell = shell.replace(
            'evidence="$raw/r21_${stage}_e1"', 'evidence="$CASE_ROOT/never-created"'
        )
        setup = 'python3() { return 0; }; command() { printf "%s\\n" "$REAL_PYTHON"; };\n'
        base = dict(
            R21_MAIN_ADMISSION="pre",
            R21_SOURCE_REVIEW="unused",
            R21_SOURCE_REVIEW_SHA256="unused",
            REAL_PYTHON=sys.executable,
            CASE_ROOT=str(self.root),
        )
        for supplied, expected in (
            ({}, False),
            ({"POSTGRES_DSN": gate.DSN}, False),
            (dict(self.env, INTEGRATION_DATABASE_DSN="foreign"), False),
            (dict(self.env, ACTION_WORKFLOW_DSN=gate.DSN), False),
            (self.env, True),
        ):
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    setup + shell + "\necho EFFECT_ENTERED\n",
                    str(gate.HERE / "run-http-qualification.sh"),
                    "pre",
                    "source-binding-e1.json",
                ],
                env={**base, **supplied},
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode == 0, expected, result.stderr)
            self.assertEqual("EFFECT_ENTERED" in result.stdout, expected)

    def test_linked_source_history_and_one_use_admission(self):
        path = self.root / "binding.json"
        path.write_text("{}")
        with (
            patch.object(gate, "snapshot", return_value={"different": True}),
            self.assertRaises(ValueError),
        ):
            gate.source(path)
        marker = self.root / "marker.json"
        gate.mark(marker, path)
        before = marker.read_bytes()
        with self.assertRaises(FileExistsError):
            gate.mark(marker, path)
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual(json.loads(before)["epoch"], "r21_http_e1")
        self.assertEqual(
            gate.R20_SHA, "9ee11e8257402c9038abcc8d07d5b4e3d9a09efa146a1e62b2f52702a65333ae"
        )
        old_marker = gate.prior.r18.content(gate.ROOT, gate.prior.RAW + "/campaign-launch.json")
        self.assertEqual(
            gate.digest(old_marker),
            "bd5d22631a2613859f0611a98778e69c4fbbe207f4b44254a46ac19c7f3f5c9b",
        )

    def test_original_rows_order_missing_and_quantile_conservation(self):
        rows = self.rows()
        full = gate.prior.reconstruct(rows)
        self.assertEqual(
            (full["observed"], full["missing_count"], len(full["cells"])), (1600, 0, 16)
        )
        self.assertEqual(gate.prior.quantile(list(range(1, 101)), 0.95), 95)
        partial = gate.prior.reconstruct(rows[:4])
        self.assertEqual(partial["observed"] + partial["missing_count"], 1600)
        for key, value in (
            ("profile", True),
            ("case", False),
            ("elapsed_ms", float("nan")),
            ("state", "wrong"),
        ):
            with self.assertRaises(ValueError):
                gate.prior.row_key(dict(rows[0], **{key: value}))
        for invalid in (
            rows + [rows[0]],
            [rows[1]],
            [rows[0], rows[0]],
            [rows[0], rows[3]],
            list(reversed(rows[:4])),
        ):
            with self.assertRaises(ValueError):
                gate.prior.reconstruct(invalid)
        slow = copy.deepcopy(rows)
        for row in slow:
            if row["operation"] == "admission":
                row["elapsed_ms"] = 501
        self.assertEqual(gate.prior.reconstruct(slow)["status"], "FAIL")

    def test_packet_summary_controls_oracle_and_corruption(self):
        root = self.write_packet()
        self.assertEqual(gate.packet(root)["status"], "PASS")
        for target, change in (
            ("run/latency-summary.json", lambda data: data["profile"].update(no_worker=False)),
            ("run/r-controls.json", lambda data: data.update(observer="on")),
            ("run/r-controls.json", lambda data: data.update(pre_ping=1)),
            ("run/latency-summary.json", lambda data: data["cells"][0].update(samples=100.0)),
            ("../r21-campaign-launch.json", lambda data: data.update(consumed=1)),
            ("load.process.json", lambda data: data.update(original_exit_code=1)),
            (
                "load.process.json",
                lambda data: data.update(exit_code=False, original_exit_code=False),
            ),
            ("load.owner.json", lambda data: data.update(token="foreign")),
        ):
            path = root / target
            saved = path.read_bytes()
            data = json.loads(saved)
            change(data)
            path.write_text(json.dumps(data))
            self.assertEqual(gate.analyze(root)["integrity"], "FAIL")
            path.write_bytes(saved)
        journal = root / "run/samples.jsonl"
        journal.write_bytes(journal.read_bytes().rstrip(b"\n"))
        invalid = gate.analyze(root)
        self.assertEqual(invalid["integrity"], "FAIL")
        self.assertNotIn("observed", invalid)
        root = self.write_packet(self.rows()[:4], code=1)
        self.assertEqual(gate.packet(root)["status"], "FAIL")
        (root / "run/latency-summary.json").unlink()
        result = gate.analyze(root)
        self.assertEqual(
            (result["integrity"], result["observed"], result["missing_count"]), ("FAIL", 4, 1596)
        )

    def test_supervisor_dispatch_and_shell_ownership_failclosed(self):
        supervisor = (gate.HERE.parent / "r19/bounded.py").read_text()
        self.assertIn('stage == "http" and label == "load"', supervisor)
        self.assertIn('owner["cleanup_deadline"] = deadline', supervisor)
        self.assertNotIn("bounded.py", gate.FILES)
        shell = (gate.HERE / "run-http-qualification.sh").read_text()
        stop = "stop_active() {" + shell.split("stop_active() {", 1)[1].split("\ncleanup() {", 1)[0]
        cleanup = "cleanup() {" + shell.split("cleanup() {", 1)[1].split("\ncapacity() {", 1)[0]
        setup = """set -euo pipefail
evidence=$1
container_evidence=/evidence/r19/r21_http_e1
r21_dir=unused
active_pid=123
active_label=load
owned_databases=(rtr_tip054_r21_local_e1 rtr_tip054_r21_engine_e1)
owned_count=2
uncertain_database=$4
stop_code=$2
proof_code=$3
exec_runner() { return "$stop_code"; }
python3() { return "$proof_code"; }
kill() { return 1; }
wait() { return 0; }
pg_sql() { printf '%s\\n' "$*" >> "$evidence/drops"; }
absence() { echo 0; }
"""
        for stop_code, proof_code, uncertain, expected in (
            (1, 0, "", False),
            (0, 1, "", False),
            (0, 0, "unknown", False),
            (0, 0, "", True),
        ):
            drop = self.root / "drops"
            drop.unlink(missing_ok=True)
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    setup
                    + stop
                    + "\n"
                    + cleanup
                    + '\nif ! stop_active; then echo "HELD:$active_pid:$owned_count"; '
                    "exit 1; fi\ncleanup\n",
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
            self.assertEqual(result.returncode, 0 if expected else 1, result.stderr)
            self.assertEqual(drop.exists(), expected)
            if expected:
                self.assertEqual(
                    [line.split("DROP DATABASE ")[1] for line in drop.read_text().splitlines()],
                    ['"rtr_tip054_r21_engine_e1";', '"rtr_tip054_r21_local_e1";'],
                )
            elif stop_code or proof_code:
                self.assertIn("HELD:123:2", result.stdout)
        with self.assertRaises(ValueError):
            gate.prior.r18.safe_path(self.root, "../foreign")

    def test_fixture_db_closure_and_readiness_scope(self):
        packet = gate.contract()
        self.assertEqual(
            (packet["candidate"], packet["serving_executor"], packet["tip054_5"]),
            ("NOT_READY", "OFF", "BLOCKED"),
        )
        expected = [gate.prior.r18.normalized_nodeid(node) for node in gate.selectors()]
        self.assertEqual(len(set(expected)), 7)
        collection = self.root / "collection.txt"
        collection.write_text("\n".join(expected))
        gate.collection(collection)
        collection.write_text("\n".join(expected[:-1]))
        with self.assertRaises(ValueError):
            gate.collection(collection)
        tree = ET.Element("testsuites")
        suite = ET.SubElement(tree, "testsuite", tests="7", failures="0", errors="0", skipped="0")
        for node in gate.selectors():
            classname, name = gate.prior.r18.xml_identity(node)
            ET.SubElement(suite, "testcase", classname=classname, name=name)
        xml = self.root / "result.xml"
        ET.ElementTree(tree).write(xml)
        gate.prior.r18.junit(xml, gate.selectors())
        ET.SubElement(suite[0], "skipped")
        ET.ElementTree(tree).write(xml)
        with self.assertRaises(ValueError):
            gate.prior.r18.junit(xml, gate.selectors())
        shell = (gate.HERE / "run-http-qualification.sh").read_text()
        for forbidden in (
            "ALTER ROLE",
            "FLUSH",
            "--force",
            "pg_monitor.py",
            "phase_profiler",
            "preseed",
        ):
            self.assertNotIn(forbidden, shell)
        self.assertLess(
            shell.index('env -i "${base_env[@]}" "${load_env[@]}"'), shell.index("\nmkdir -p")
        )
        self.assertLess(shell.index('mark "$marker"'), shell.index("active_pid=$!"))
        self.assertIn("action_step_attempts", shell)
        self.assertIn("PGCONNECT_TIMEOUT=5", shell)


if __name__ == "__main__":
    unittest.main(verbosity=2)
