"""Exactly six stdlib admission controls; no product imports or runtime tests."""

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
import gate


class AdmissionControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-tmp-r18-controls-20261009-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.packet = gate.manifest(gate.HERE / "qualification.json")

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def reject_manifest(self, packet):
        with self.assertRaises(ValueError):
            gate.manifest(self.write("mutant.json", packet))

    def test_manifest_schema_caps_and_malformed_rejection(self):
        self.assertEqual(len(gate.combined_selectors(self.packet)), 52)
        for key, value in (("schema", "unknown"), ("fixture", {}), ("caps", {})):
            mutant = copy.deepcopy(self.packet)
            mutant[key] = value
            self.reject_manifest(mutant)
        mutant = copy.deepcopy(self.packet)
        mutant["unknown"] = True
        self.reject_manifest(mutant)
        oversized = self.root / "oversized.json"
        oversized.write_bytes(b" " * (gate.CAPS["manifest_bytes"] + 1))
        with self.assertRaises(ValueError):
            gate.manifest(oversized)
        malformed = self.root / "malformed.json"
        malformed.write_text("{")
        with self.assertRaises(ValueError):
            gate.manifest(malformed)
        evidence = self.root / "evidence"
        evidence.mkdir()
        (evidence / "retained.raw").write_bytes(b"abcd")
        with patch.dict(gate.CAPS, {"pre_evidence_bytes": 3}):
            with self.assertRaises(ValueError):
                gate.evidence_cap(evidence, "pre")
        self.assertEqual((evidence / "retained.raw").read_bytes(), b"abcd")

    def test_source_paths_hashes_scope_and_drift_rejection(self):
        (self.root / "source.txt").write_text("owned")
        self.assertEqual(gate.content(self.root, "source.txt"), b"owned")
        for path in ("../source.txt", "/source.txt", "./source.txt", "missing.txt"):
            with self.assertRaises(ValueError):
                gate.content(self.root, path)
        (self.root / "alias").symlink_to(self.root / "source.txt")
        with self.assertRaises(ValueError):
            gate.content(self.root, "alias")
        def toy_inventory(root):
            return {"product": ["source.txt"], "tests": []}, {
                "source.txt": gate.digest(gate.content(root, "source.txt"))
            }

        with patch.object(gate, "inventories", side_effect=toy_inventory):
            saved = gate.snapshot(self.root)
        for mutate in ("hash", "path", "scope", "recipe"):
            mutant = copy.deepcopy(saved)
            if mutate == "hash":
                mutant["files"][next(iter(mutant["files"]))] = "0" * 64
            elif mutate == "path":
                mutant["files"]["../escape"] = "0" * 64
            elif mutate == "scope":
                mutant["scopes"]["product"].pop()
            else:
                mutant["recipe"] = "borrow historical 4a0b"
            with patch.object(gate, "snapshot", return_value=saved):
                with self.assertRaises(ValueError):
                    gate.binding(self.write("binding.json", mutant))
        with patch.object(gate, "inventories", side_effect=toy_inventory):
            with patch.object(gate, "SOURCE_NAMES", ()):
                path = self.write("binding.json", saved)
                self.assertEqual(gate.binding(path, self.root), saved)
                (self.root / "source.txt").write_text("changed")
                with self.assertRaises(ValueError):
                    gate.binding(path, self.root)

    def test_exact_old_plus_added_selection_and_collection(self):
        expected = [gate.normalized_nodeid(node) for node in gate.combined_selectors(self.packet)]
        path = self.root / "collection.txt"
        path.write_text("\n".join(expected) + "\n52 tests collected\n")
        self.assertEqual(gate.collection(path, self.packet), expected)
        self.assertEqual(len(expected[:33]), 33)
        for observed in (expected[:-1], expected + [expected[0]], expected[1:] + expected[:1]):
            path.write_text("\n".join(observed))
            with self.assertRaises(ValueError):
                gate.collection(path, self.packet)
        uncontrolled = list(expected)
        uncontrolled[-1] = "test_r18_offline.py" + uncontrolled[-1]
        path.write_text("\n".join(uncontrolled))
        with self.assertRaises(ValueError):
            gate.collection(path, self.packet)
        mutant = copy.deepcopy(self.packet)
        mutant["groups"]["new_sql"][0] = mutant["groups"]["old_sql"][0]
        self.reject_manifest(mutant)

    def test_exact_xml_identity_and_zero_skip_conservation(self):
        import xml.etree.ElementTree as ET

        selectors = self.packet["groups"]["offline"]
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", tests="6", failures="0", errors="0", skipped="0")
        for node in selectors:
            classname, name = gate.xml_identity(node)
            ET.SubElement(suite, "testcase", classname=classname, name=name)
        path = self.root / "result.xml"
        ET.ElementTree(root).write(path)
        self.assertEqual(len(gate.junit(path, selectors)), 6)
        first = suite[0]
        correct = first.attrib["classname"]
        first.set("classname", "test_r18_offline.AdmissionControls")
        ET.ElementTree(root).write(path)
        with self.assertRaises(ValueError):
            gate.junit(path, selectors)
        first.set("classname", correct)
        ET.SubElement(first, "skipped")
        ET.ElementTree(root).write(path)
        with self.assertRaises(ValueError):
            gate.junit(path, selectors)
        first.remove(first[0])
        suite.set("failures", "1")
        ET.ElementTree(root).write(path)
        with self.assertRaises(ValueError):
            gate.junit(path, selectors)
        self.assertEqual(gate.xml_identity("tests/a.py::test_value[x.y]"),
                         ("tests.a", "test_value[x.y]"))

    def test_owned_stage_epoch_and_process_group_contract(self):
        gate.stage_contract("pre", "pre_e1")
        gate.stage_contract("sql", "sql_e1", gate.DATABASES[0], True)
        for args in (("load", "load_e1"), ("pre", "pre_e0"),
                     ("pre", "pre_e1", gate.DATABASES[0], True),
                     ("sql", "sql_e1", "postgres", True),
                     ("sql", "sql_e1", gate.DATABASES[0], False)):
            with self.assertRaises(ValueError):
                gate.stage_contract(*args)
        proc = self.root / "proc"
        entry = proc / "100"
        entry.mkdir(parents=True)
        fields = ["S", "1", "100"] + ["0"] * 16 + ["123"]
        (entry / "stat").write_text("100 (python child) " + " ".join(fields))
        (entry / "environ").write_bytes(b"R18_OWNED_CHILD=owned\0")
        owner = {"group": 100, "token": "owned"}
        self.assertEqual(bounded.group_members(owner, proc), [100])
        (entry / "environ").write_bytes(b"R18_OWNED_CHILD=foreign\0")
        with self.assertRaises(ValueError):
            bounded.group_members(owner, proc)
        (entry / "stat").write_text("100 (python child) " + " ".join(["S", "1", "101"] + fields[3:]))
        self.assertEqual(bounded.group_members(owner, proc), [])
        signals = []
        with patch.object(bounded, "signal_owned", side_effect=lambda item, sig: signals.append(sig)):
            with patch.object(bounded, "group_members", side_effect=[[100], [100], [], []]):
                bounded.drain(owner, grace=0)
        self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL])
        with patch.object(bounded, "group_members", return_value=[]):
            with patch.object(bounded.os, "killpg") as kill:
                bounded.signal_owned(owner, signal.SIGTERM)
                kill.assert_not_called()
        # Real POSIX children on the host; only the Linux /proc enumeration is
        # replaced by the exact Popen object this control creates and joins.
        for fault in ("deadline", "evidence_cap", "interrupted"):
            target = self.root / fault
            target.mkdir()
            children = []
            handlers = {}
            popen = subprocess.Popen

            def launch(*args, **kwargs):
                child = popen(*args, **kwargs)
                children.append((child, kwargs["env"]["R18_OWNED_CHILD"]))
                self.assertTrue(kwargs["start_new_session"])
                self.assertEqual(bounded.os.getpgid(child.pid), child.pid)
                return child

            def owned(item):
                child, token = children[0]
                self.assertEqual((item["group"], item["token"]), (child.pid, token))
                return [child.pid] if child.poll() is None else []

            def register(number, handler):
                previous = handlers.get(number)
                handlers[number] = handler
                return previous

            def cap_check(*args):
                if fault == "interrupted" and (target / "probe.stdout.txt").stat().st_size > 2000:
                    handlers[signal.SIGTERM](signal.SIGTERM, None)
                return gate.evidence_cap(*args)

            script = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            script += "print('x'*2000,flush=True); time.sleep(10)"
            output_cap = 1000 if fault == "evidence_cap" else 100000
            with patch.dict(gate.CAPS, {"child_seconds": 0.2, "kill_grace_seconds": 0.05,
                                      "pre_evidence_bytes": output_cap}):
                with patch.object(bounded.subprocess, "Popen", side_effect=launch):
                    with patch.object(bounded, "process", return_value={"start": "offline"}):
                        with patch.object(bounded, "group_members", side_effect=owned):
                            with patch.object(bounded.signal, "signal", side_effect=register):
                                with patch.object(bounded, "evidence_cap", side_effect=cap_check):
                                    code = bounded.supervise(target, "pre", "probe", [sys.executable, "-c", script])
            result = json.loads((target / "probe.process.json").read_bytes())
            self.assertEqual((code, result["reason"], result["group_drained"]), (124, fault, True))
            self.assertIsNotNone(children[0][0].poll())
            self.assertEqual(result["original_exit_code"], -signal.SIGKILL)
            self.assertGreater((target / "probe.stdout.txt").stat().st_size, 2000)

    def test_pending_ledger_and_immutable_http_contract(self):
        self.assertEqual(len(self.packet["ledger"]), 11)
        self.assertEqual(self.packet["scope"]["serving_executor"], "OFF")
        self.assertEqual(self.packet["http"]["allowance_consumed"], 0)
        for key, value in (("p95_admission_ms", 501), ("profiles", [25]),
                           ("observer", "R17_M"), ("synthetic_executor_flag", False),
                           ("serving_executor_flag", True), ("status", "PASS")):
            mutant = copy.deepcopy(self.packet)
            mutant["http"][key] = value
            self.reject_manifest(mutant)
        mutant = copy.deepcopy(self.packet)
        mutant["ledger"]["EXE-009"] = "PASS_from_R17"
        self.reject_manifest(mutant)
        mutant = copy.deepcopy(self.packet)
        mutant["scope"]["stages"].append("http")
        self.reject_manifest(mutant)


if __name__ == "__main__":
    unittest.main(verbosity=2)
