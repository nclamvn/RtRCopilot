"""Local source-subset/file/pipe controls, not full application or measured routing."""

import asyncio
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

from integration import Capture, backend, pipe_fixture
from source_subset import owner_probe, retain_function

HERE = Path(__file__).absolute().parent


class LocalControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".r27-test-", dir=HERE)
        self.root, self.captures = Path(self.tmp.name), []
        self.globals = (sys.stdout, sys.stderr, tuple(logging.getLogger().handlers))

    def tearDown(self):
        for capture in self.captures:
            if capture.writer:
                capture.writer.abandon()
        self.tmp.cleanup()
        self.assertEqual((sys.stdout, sys.stderr, tuple(logging.getLogger().handlers)), self.globals)

    def capture(self, name="epoch", **kwargs):
        capture = Capture(self.root / name, enabled=True, **kwargs)
        self.captures.append(capture)
        return capture

    def rejects(self, capture):
        module = backend(); raw = (HERE.parent / "r25/contract.json").read_bytes()
        with self.assertRaises((module.PacketError, OSError)):
            module.recover(capture.writer.path, json.loads(raw), raw, bytes(range(16)))

    def test_default_off_real_original_stream(self):
        off = Capture(self.root / "must-not-exist")
        self.assertFalse(off.enabled)
        records = []
        row = {"profile": 1, "case": 0, "okay": False, "error_code": "raw é"}
        with (self.root / "original.jsonl").open("w") as stream:
            retain, method_hash = retain_function(records, stream)
            self.assertIsNone(retain(row))
        self.assertIs(records[0], row)
        self.assertEqual((self.root / "original.jsonl").read_bytes(),
                         (json.dumps(row, separators=(",", ":")) + "\n").encode())
        self.assertEqual(method_hash, "4b544a4071af672b5cd8a0555ccbc4a34b0c11cfc7a53eac124b504296655902")
        self.assertFalse((self.root / "must-not-exist").exists())

    def test_actual_retain_virtual_copy_and_raw_pipe_routing(self):
        capture = self.capture()
        records = []
        row = {"profile": 1, "case": 0, "okay": True, "state": "queued"}
        self.assertIsNone(capture.journal(records)(row))
        capture.copy_records(records)
        capture.record("ephemeral", b"packet-only file endpoint\x00\xff")
        pipe = asyncio.run(pipe_fixture(capture))
        self.assertEqual(pipe["returncode"], 0)
        self.assertTrue(pipe["joined"])
        recovered = capture.finish_local()
        journal = [r[3] for r in recovered["records"] if r[0] == "journal"]
        self.assertEqual(journal, [(json.dumps(row, separators=(",", ":")) + "\n").encode()])
        self.assertEqual([r[3] for r in recovered["records"] if r[0] == "final_samples"],
                         [json.dumps(records, indent=2).encode()])
        self.assertEqual([r[3] for r in recovered["records"] if r[0] == "summary_stdout"],
                         pipe["outputs"]["summary_stdout"])
        self.assertEqual([r[3] for r in recovered["records"] if r[0] == "load_stderr"],
                         pipe["outputs"]["load_stderr"])
        self.assertEqual(recovered["actual_capture_admission"], "HOLD")
        self.assertIn("local fixture", recovered["scope"])

    def test_raw_journal_errors_flush_and_append_before_failure(self):
        for index, mode in enumerate(("serialize", "flush", "oversize")):
            capture = self.capture(str(index)); records = []
            sentinel = RuntimeError("unchanged flush failure")
            retain = capture.journal(records, sentinel if mode == "flush" else None)
            row = {"bad": object()} if mode == "serialize" else {"raw": "x" * 600} if mode == "oversize" else {"raw": "ok"}
            with self.assertRaises(BaseException) as caught:
                retain(row)
            self.assertIs(records[0], row)  # Actual source appends before serialize/write/flush.
            if mode == "flush": self.assertIs(caught.exception, sentinel)
            with self.assertRaises((capture.module.PacketError, OSError)):
                capture.finish_local()  # Even a caller-caught fault cannot qualify.
            capture.writer.abandon(); self.rejects(capture)
        for name, action in (("copy", lambda c: c.copy_records([object()])),
                             ("family", lambda c: c.record([], b"raw"))):
            capture = self.capture(name)
            with self.assertRaises((TypeError, capture.module.PacketError)):
                action(capture)
            with self.assertRaises(capture.module.PacketError):
                capture.finish_local()
            capture.writer.abandon(); self.rejects(capture)

    def test_error_cleanup_identity_and_unconnected_measurement_gate(self):
        capture = self.capture(faults={"invalidate": "raise"})
        class Original(BaseException): pass
        original = Original("keep original object")
        with self.assertRaises(Original) as caught:
            with capture:
                raise original
        self.assertIs(caught.exception, original)
        self.assertIsInstance(original.__cause__, OSError)
        self.assertFalse(capture.writer.closed)
        self.rejects(capture)
        capture.writer.abandon()
        self.rejects(capture)
        gate = self.capture("global-gate")
        with self.assertRaises(gate.module.PacketError): gate.finish_measured()
        with self.assertRaises(gate.module.PacketError): gate.finish_local()
        gate.writer.abandon(); self.rejects(gate)

    def test_real_pipe_whole_record_rejection_and_partial_output(self):
        for mode in ("oversize", "partial"):
            capture = self.capture(mode)
            with self.assertRaises((ValueError, asyncio.IncompleteReadError)):
                asyncio.run(pipe_fixture(capture, mode))
            with self.assertRaises(capture.module.PacketError): capture.finish_local()
            capture.writer.abandon(); self.rejects(capture)


class AsyncControls(unittest.IsolatedAsyncioTestCase):
    async def test_exact_terminal_body_result_error_owner_and_repeated_cancel(self):
        probe = owner_probe(); result = object()
        async def normal(): return result
        self.assertIs(await probe.join_terminal(normal()), result)
        self.assertIsNone(probe.terminal_task)
        error = RuntimeError("same terminal error")
        async def failing(): raise error
        with self.assertRaises(RuntimeError) as caught: await probe.join_terminal(failing())
        self.assertIs(caught.exception, error)
        self.assertTrue(probe.poisoned)
        operation = normal()
        with self.assertRaises(RuntimeError):
            await asyncio.create_task(probe.join_terminal(operation))
        self.assertIsNone(operation.cr_frame)
        entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        holder = {}
        async def owner():
            owned = owner_probe(); holder["probe"] = owned
            async def terminal():
                entered.set(); await release.wait(); completed.set(); return result
            return await owned.join_terminal(terminal())
        task = asyncio.create_task(owner()); await entered.wait()
        task.cancel("first"); await asyncio.sleep(0)
        task.cancel("second"); await asyncio.sleep(0)
        self.assertFalse(task.done()); release.set()
        with self.assertRaises(asyncio.CancelledError) as cancelled: await task
        self.assertEqual(str(cancelled.exception), "first")
        self.assertTrue(completed.is_set())
        self.assertIsNone(holder["probe"].terminal_task)

    async def test_cancelled_real_child_join_and_source_restoration(self):
        with tempfile.TemporaryDirectory(prefix=".r27-test-", dir=HERE) as name:
            with Capture(Path(name) / "epoch", enabled=True) as capture:
                started = asyncio.Event()
                task = asyncio.create_task(pipe_fixture(capture, "delay", started))
                await started.wait()
                task.cancel("original cancellation"); await asyncio.sleep(0)
                task.cancel("again"); await asyncio.sleep(0)
                with self.assertRaises(asyncio.CancelledError) as caught: await task
                self.assertEqual(str(caught.exception), "original cancellation")
                self.assertEqual([t for t in asyncio.all_tasks() if t is not asyncio.current_task()], [])
                with self.assertRaises(capture.module.PacketError): capture.finish_local()
