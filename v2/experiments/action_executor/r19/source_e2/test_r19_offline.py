"""Six stdlib-only admission groups; no product imports, SQL or HTTP workload."""

import copy
import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bounded
import qualification as gate


class OfflineControls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-tmp-r19-controls-20261009-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "http_e1"
        self.root.mkdir()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def rows(self):
        return [
            dict(
                profile=p,
                case=c,
                operation=o,
                elapsed_ms=10,
                http_status=gate.STATUS[o],
                okay=True,
                state=gate.STATES[o],
                error_code=None,
            )
            for p, c, o in gate.expected()
        ]

    def retained(self, rows, code=0):
        binding = self.write("binding.json", {"source": "synthetic offline only"})
        (self.root / "contract.json").write_bytes((gate.HERE / "contract.json").read_bytes())
        marker = self.root.parent / "campaign-launch.json"
        if not marker.exists():
            gate.mark(marker, binding)
        result = gate.reconstruct(rows)
        self.write("run/samples.json", rows)
        (self.root / "run/samples.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows)
        )
        self.write(
            "run/latency-summary.json", {"cells": result["cells"], "status": result["status"]}
        )
        self.write(
            "run/r-controls.json",
            {
                "observer": "off",
                "pool_size": 5,
                "max_overflow": 5,
                "pre_ping": True,
                "operation_timeout_seconds": 0.9,
                "old_load_helper": "/work/latency_probe.py",
                "provider": False,
                "worker": False,
                "authority_override": "Existing current synthetic subject dependency ONLY",
            },
        )
        owner = {"group": 123, "token": "synthetic", "supervisor": 456, "supervisor_start": "789"}
        self.write("load.owner.json", owner)
        self.write(
            "load.process.json",
            {
                "owner": owner,
                "exit_code": code,
                "original_exit_code": code,
                "reason": "completed",
                "group_drained": True,
            },
        )
        return result

    def test_contract_source_and_one_shot_admission(self):
        packet = gate.contract()
        self.assertEqual(len(gate.expected()), 1600)
        for key, value in (
            ("profiles", [True, 10, 25, 50]),
            ("observer", "M"),
            ("serving_executor_flag", True),
            ("seconds", 191),
        ):
            mutant = copy.deepcopy(packet)
            mutant["http"][key] = value
            with self.assertRaises(ValueError):
                gate.contract(self.write("bad-contract.json", mutant))
        for relative in ("../escape", "/escape", "./escape", "missing"):
            with self.assertRaises(ValueError):
                gate.r18.content(self.root, relative)
        binding = self.write("binding.json", {"source": "offline"})
        marker = self.root / "launch.json"
        self.assertTrue(gate.mark(marker, binding)["consumed"])
        with self.assertRaises(ValueError):
            gate.mark(marker, binding)
        original = {"files": {}, "scopes": {}, "digests": {}}
        with patch.object(gate, "snapshot", return_value=original), self.assertRaises(ValueError):
            gate.source(binding)

    def test_raw_schema_identity_and_corruption(self):
        rows = self.rows()
        self.assertEqual(gate.reconstruct(rows)["observed"], 1600)
        for key, value in (
            ("profile", True),
            ("case", False),
            ("elapsed_ms", float("nan")),
            ("elapsed_ms", True),
            ("state", "spent"),
            ("okay", 1),
        ):
            mutant = copy.deepcopy(rows)
            mutant[0][key] = value
            with self.assertRaises(ValueError):
                gate.reconstruct(mutant)
        with self.assertRaises(ValueError):
            gate.reconstruct(rows[:-1] + [rows[0]])
        self.retained(rows)
        (self.root / "run/samples.jsonl").write_text('{"partial":')
        self.assertEqual(gate.analyze(self.root)["integrity"], "FAIL")
        self.retained(rows)
        self.write("run/samples.json", rows[1:] + rows[:1])
        self.assertEqual(gate.analyze(self.root)["integrity"], "FAIL")
        # Completion order is not global case order.
        concurrent = []
        for profile in gate.PROFILES:
            for operation in gate.OPERATIONS:
                concurrent.extend(
                    row
                    for row in rows
                    if row["profile"] == profile and row["operation"] == operation
                )
        self.assertEqual(gate.reconstruct(concurrent)["status"], "PASS")
        with self.assertRaises(ValueError):
            gate.reconstruct([rows[1], rows[0]])

    def test_cell_quantile_and_missing_conservation(self):
        self.assertEqual(gate.quantile(list(range(1, 101)), 0.95), 95)
        rows = self.rows()
        for row in rows:
            row["elapsed_ms"] = 500 if row["operation"] == "admission" else 1000
        self.assertEqual(gate.reconstruct(rows)["status"], "PASS")
        rows[0]["elapsed_ms"] = 501
        # One high value does not move nearest-rank p95.
        self.assertEqual(gate.reconstruct(rows)["status"], "PASS")
        for row in rows[:24:4]:
            row["elapsed_ms"] = 501
        self.assertEqual(gate.reconstruct(rows)["status"], "FAIL")
        result = gate.reconstruct(rows[:-1])
        self.assertEqual((result["observed"], result["missing_count"]), (1599, 1))
        self.assertEqual(result["missing"], [[50, 99, "cancel"]])
        self.assertEqual(result["cells"][-1]["samples"], 99)
        rows = self.rows()
        rows[2] = dict(
            profile=1,
            case=0,
            operation="status",
            elapsed_ms=901,
            okay=False,
            exception_type="TimeoutError",
        )
        result = gate.reconstruct(rows)
        self.assertEqual(
            (result["observed"], result["failed"], result["missing_count"]), (1600, 1, 0)
        )
        self.assertFalse(result["cells"][2]["pass"])
        # Status failure still precedes the unchanged helper's cancel request.
        rows = self.rows()[4:]
        result = gate.reconstruct(rows)
        self.assertEqual(result["observed"] + result["missing_count"], 1600)

    def test_oracle_abort_and_original_summary_agreement(self):
        rows = self.rows()
        self.retained(rows)
        self.assertEqual(gate.analyze(self.root)["status"], "PASS")
        self.retained(rows, code=1)
        self.assertEqual(gate.analyze(self.root)["integrity"], "FAIL")
        self.retained(rows)
        (self.root / "run/latency-summary.json").unlink()
        self.assertEqual(gate.analyze(self.root)["integrity"], "FAIL")
        rows[0]["elapsed_ms"] = 900
        for row in rows[:24:4]:
            row["elapsed_ms"] = 900
        self.retained(rows, code=1)
        result = gate.analyze(self.root)
        self.assertEqual(
            (result["integrity"], result["status"], result["oracle_complete_pass"]),
            ("PASS", "FAIL", False),
        )
        summary = gate.load_json(self.root / "run/latency-summary.json")
        summary["cells"][0]["p95_ms"] = 0
        self.write("run/latency-summary.json", summary)
        self.assertEqual(gate.analyze(self.root)["integrity"], "FAIL")
        self.retained(self.rows())
        process = gate.load_json(self.root / "load.process.json")
        for key, value in (("reason", "deadline"), ("group_drained", False)):
            changed = dict(process, **{key: value})
            self.write("load.process.json", changed)
            self.assertEqual(gate.analyze(self.root)["integrity"], "FAIL")

    def test_owned_process_deadline_cap_and_shell_failclosed(self):
        self.assertEqual(bounded.child_budget("http", "load"), 190)
        self.assertEqual(bounded.child_budget("http", "migration"), 120)
        self.assertEqual(bounded.child_budget("pre", "offline"), 120)
        (self.root / "raw").write_bytes(b"abcd")
        with patch.dict(gate.CAPS, {"http_evidence_bytes": 3}), self.assertRaises(ValueError):
            bounded.evidence_cap(self.root, "http")
        self.assertEqual((self.root / "raw").read_bytes(), b"abcd")
        proc = self.root / "proc"
        entry = proc / "100"
        entry.mkdir(parents=True)
        fields = ["S", "1", "100"] + ["0"] * 16 + ["123"]
        (entry / "stat").write_text("100 (python child) " + " ".join(fields))
        (entry / "environ").write_bytes(b"R19_OWNED_CHILD=owned\0")
        owner = {"group": 100, "token": "owned"}
        self.assertEqual(bounded.group_members(owner, proc), [100])
        (entry / "environ").write_bytes(b"R19_OWNED_CHILD=foreign\0")
        with self.assertRaises(ValueError):
            bounded.group_members(owner, proc)
        source = (gate.HERE / "run-http-qualification.sh").read_text()
        stop_body = (
            "stop_active() {" + source.split("stop_active() {", 1)[1].split("\ncleanup() {", 1)[0]
        )
        setup = """set -euo pipefail
evidence=$1
container_evidence=/evidence/r19/control
active_pid=123
active_label=probe
r19_dir=$3
exec_runner() { return "$2"; }
wait() { return 0; }
kill() { return 1; }
"""
        # Use a fixed injected return independent of exec_runner's actual argv.
        setup = setup.replace('return "$2"', 'return "$stop_code"') + "stop_code=$2\n"
        decision = """
if ! stop_active; then
 printf 'HOLD:%s:%s\\n' "$active_pid" "$active_label"
else
 printf 'CLEANUP_ENTERED:%s:%s\\n' "$active_pid" "$active_label"
fi
"""
        for stop_code, drained in ((1, True), (0, False), (0, True)):
            owner = {"group": 123, "token": "owned"}
            self.write("probe.owner.json", owner)
            self.write(
                "probe.process.json", {"group_drained": drained, "owner": owner, "exit_code": 0}
            )
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    setup + stop_body + decision,
                    "control",
                    str(self.root),
                    str(stop_code),
                    str(gate.HERE),
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            expected = "HOLD:123:probe" if stop_code or not drained else "CLEANUP_ENTERED::"
            self.assertIn(expected, result.stdout)
        checked_body = (
            "checked() {" + source.split("checked() {", 1)[1].split("\npytest_common=", 1)[0]
        )
        setup_checked = (
            setup
            + """
active_pid=''
r19_dir=unused
binding=unused
stage=pre
check_source() { return 0; }
python3() { return 0; }
kill() { return 0; }
"""
        )
        result = subprocess.run(
            [
                "/bin/bash",
                "-c",
                setup_checked
                + checked_body
                + "\nif checked guard /unused; then echo UNSAFE; else echo HELD:$active_label; fi",
                "control",
                str(self.root),
                "0",
                str(gate.HERE),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        self.assertIn("HELD:guard", result.stdout)
        self.assertNotIn("UNSAFE", result.stdout)
        cleanup_body = "cleanup() {" + source.split("cleanup() {", 1)[1].split("\nfinish() {", 1)[0]
        cleanup_setup = """set -euo pipefail
evidence=$1
active_pid=''
uncertain_database=''
owned_databases=()
owned_count=0
docker_path=stub_docker
pg=synthetic
stub_docker() { return 1; }
absence() { echo 0; }
"""
        for own in (False, True):
            admission = ""
            if own:
                admission = "owned_databases=(rtr_tip054_r19_local_e1); owned_count=1\n"
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    cleanup_setup
                    + cleanup_body
                    + admission
                    + "\nif ! cleanup; then echo HELD:$owned_count; "
                    "else echo CLEAN:$owned_count; fi",
                    "control",
                    str(self.root),
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            self.assertIn("HELD:1" if own else "CLEAN:0", result.stdout)
        self.supervisor_faults()

    def supervisor_faults(self):
        # Real owned POSIX children. Replace Linux enumeration with only our exact Popen object.
        for fault in ("deadline", "evidence_cap", "interrupted", "shared_deadline"):
            target = self.root / fault
            target.mkdir()
            children, handlers, deadlines = [], {}, []
            popen, real_drain = subprocess.Popen, bounded.drain

            def launch(*args, popen=popen, children=children, **kwargs):
                child = popen(*args, **kwargs)
                children.append((child, kwargs["env"]["R19_OWNED_CHILD"]))
                self.assertTrue(kwargs["start_new_session"])
                self.assertEqual(bounded.os.getpgid(child.pid), child.pid)
                return child

            def owned(item, children=children):
                child, token = children[0]
                self.assertEqual((item["group"], item["token"]), (child.pid, token))
                return [child.pid] if child.poll() is None else []

            def register(number, handler, handlers=handlers):
                old = handlers.get(number)
                handlers[number] = handler
                return old

            def cap_check(*args, fault=fault, target=target, handlers=handlers):
                if fault == "interrupted" and (target / "load.stdout.txt").stat().st_size > 2000:
                    handlers[signal.SIGTERM](signal.SIGTERM, None)
                return gate.cap(*args)

            def fault_drain(
                item, *, deadline, fault=fault, deadlines=deadlines, real_drain=real_drain
            ):
                if fault == "shared_deadline":
                    deadlines.append(deadline)
                    if len(deadlines) == 1:
                        raise OSError("injected first drain failure")
                return real_drain(item, deadline=deadline)

            script = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            script += "print('x'*2000,flush=True); time.sleep(10)"
            with (
                patch.dict(
                    gate.CAPS,
                    {
                        "http_seconds": 0.2,
                        "kill_grace_seconds": 0.05,
                        "http_evidence_bytes": 1000 if fault == "evidence_cap" else 100000,
                    },
                ),
                patch.object(bounded.subprocess, "Popen", side_effect=launch),
                patch.object(bounded, "process", return_value={"start": "offline"}),
                patch.object(bounded, "group_members", side_effect=owned),
                patch.object(bounded.signal, "signal", side_effect=register),
                patch.object(bounded, "evidence_cap", side_effect=cap_check),
                patch.object(bounded, "drain", side_effect=fault_drain),
            ):
                if fault == "shared_deadline":
                    with self.assertRaisesRegex(OSError, "injected first drain failure"):
                        bounded.supervise(target, "http", "load", [sys.executable, "-c", script])
                    self.assertEqual(len(deadlines), 2)
                    self.assertEqual(deadlines[0], deadlines[1])
                else:
                    self.assertEqual(
                        bounded.supervise(target, "http", "load", [sys.executable, "-c", script]),
                        124,
                    )
            result = gate.load_json(target / "load.process.json")
            self.assertTrue(result["group_drained"])
            self.assertEqual(result["reason"], "deadline" if fault == "shared_deadline" else fault)
            self.assertEqual(result["original_exit_code"], -signal.SIGKILL)
            self.assertIsNotNone(children[0][0].poll())
            self.assertGreater((target / "load.stdout.txt").stat().st_size, 2000)

    def test_fixture_db_cleanup_and_readiness_ledger(self):
        packet = gate.contract()
        self.assertEqual(packet["candidate"], "NOT_READY")
        self.assertEqual(packet["serving_executor"], "OFF")
        self.assertEqual(packet["tip054_5"], "BLOCKED")
        self.assertEqual(packet["http"]["observer"], "OFF_not_R17_M")
        for target in gate.DATABASES:
            self.assertEqual(gate.database(target), target)
        for target in ("postgres", "rtr_tip054_r18_local_e1", "../db"):
            with self.assertRaises(ValueError):
                gate.database(target)
        gate.stage("http", "http_e1")
        for args in (("http", "http_e2"), ("on", "on_e1"), ("native", "native_e1")):
            with self.assertRaises(ValueError):
                gate.stage(*args)
        source = (gate.HERE / "run-http-qualification.sh").read_text()
        self.assertNotIn("ALTER ROLE", source)
        self.assertNotIn("FLUSH", source)
        self.assertIn('/work/r/run_phase_baseline.py "$container_evidence/run" off', source)
        self.assertNotIn("phase_profiler", source)
        self.assertIn("uncertain_database", source)
        baseline = gate.load_json(gate.HERE.parent / "r12/preflight_e1/fixture-preflight.json")
        self.assertEqual(len(baseline["containers"]), 4)
        self.assertTrue(baseline["network"]["Internal"])
        keys = {
            "Memory",
            "NanoCpus",
            "PidsLimit",
            "ReadonlyRootfs",
            "CapDrop",
            "SecurityOpt",
            "Tmpfs",
        }
        self.assertTrue(all(set(row["Caps"]) == keys for row in baseline["containers"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
