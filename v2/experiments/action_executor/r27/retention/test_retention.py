"""Real isolated producer/files/log/pipe controls; never an HTTP/SQL campaign."""

import asyncio
import builtins
import io
import json
import logging
import os
import sys
import tempfile
import threading
import unittest
import uuid
from array import array
from pathlib import Path
from pipes import finite_child
from unittest.mock import patch

import adapter
from envelope import METADATA, Capture, recover
from producers import DriverOutputs, audit_producer, fixture_producer

HERE = Path(__file__).absolute().parent


class Controls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".retention-test-", dir=HERE)
        self.root = Path(self.temporary.name)
        self.captures = []
        self.before = (builtins.open, io.open, os.mkdir, sys.stdout, sys.stderr)

    def tearDown(self):
        for capture in self.captures:
            capture.abandon()
        self.temporary.cleanup()
        self.assertEqual((builtins.open, io.open, os.mkdir, sys.stdout, sys.stderr), self.before)

    def capture(self, name="epoch", **kwargs):
        result = Capture(self.root / name, enabled=True, **kwargs)
        self.captures.append(result)
        return result

    def incomplete(self, capture):
        with self.assertRaises((adapter.PacketError, OSError, ValueError)):
            capture.finish()
        with self.assertRaises((adapter.PacketError, OSError, ValueError, KeyError)):
            recover(capture.root)

    def test_off_and_source_journal_summary_final_physical_copies(self):
        off = Capture(self.root / "off")
        with off:
            self.assertFalse(off.enabled)
        self.assertFalse((self.root / "off").exists())
        capture = self.capture()
        driver = DriverOutputs(capture)
        journal = capture.register("run/samples.jsonl", "journal")
        final = capture.register("run/samples.json", "final_samples")
        summary = capture.register("run/latency-summary.json", "summary_stdout")
        rows = []
        with capture:
            with journal.open("x") as stream:
                retain = driver.journal(rows, stream)
                for profile in (1, 10, 25, 50):
                    for number in range(100):
                        for operation in ("admission", "submit", "status", "cancel"):
                            retain(
                                {
                                    "profile": profile,
                                    "case": number,
                                    "operation": operation,
                                    "elapsed_ms": 1.25,
                                    "okay": True,
                                    "state": "queued",
                                }
                            )
            driver.finish(rows, journal.parent)
        result = capture.finish()
        self.assertEqual(len(rows), 1600)
        self.assertEqual(
            journal.read_bytes(),
            b"".join((json.dumps(row, separators=(",", ":")) + "\n").encode() for row in rows),
        )
        self.assertEqual(final.read_bytes(), json.dumps(rows, indent=2).encode())
        stdout = [r[3] for r in result["records"] if r[0] == "summary_stdout"]
        self.assertEqual(stdout, [summary.read_bytes(), summary.read_bytes(), b"\n"])
        self.assertEqual(result["native_files"], 3)
        self.assertGreater(result["charge"], result["all_live_file_bytes"])
        self.assertEqual(result["measurement_admission"], "HOLD")

    def test_full_signed_fixture_and_actual_audit_logging_restoration(self):
        capture = self.capture()
        build, fixture = fixture_producer(capture)
        emit, logger = audit_producer(capture)
        logger._cache[logging.INFO] = False
        original_cache = logger._cache
        cache_before = dict(logger._cache)
        state = (logger.handlers, logger.filters, logger.level, logger.propagate, logger.disabled)
        package_id = uuid.UUID(int=1)
        directory = "package-" + str(package_id)
        names = (
            "records.jsonl",
            "evidence.jsonl",
            "source_hashes.json",
            "publish_attestation.json",
            "manifest.json",
        )
        for name in names:
            capture.register(directory + "/" + name, "ephemeral", defer_parents=True)
        with capture:
            package = build(
                capture.native,
                package_id=package_id,
                curator_id=uuid.UUID(int=2),
                owner_id=uuid.UUID(int=3),
            )
            event = emit(
                actor_id="synthetic",
                action="retention",
                result="allowed",
                reason="local",
                request_id="r27-retention",
                timestamp=fixture.NOW,
            )
            emit(
                actor_id="synthetic",
                action="retention",
                result="allowed",
                reason="local",
                request_id="r27-retention",
                timestamp=fixture.NOW,
            )
        self.assertEqual(
            (logger.handlers, logger.filters, logger.level, logger.propagate, logger.disabled),
            state,
        )
        result = capture.finish()
        self.assertIs(logger._cache, original_cache)
        self.assertEqual(logger._cache, cache_before)
        records = [r[3] for r in result["records"] if r[0] == "ephemeral"]
        self.assertEqual(len(records), 6)  # Five native files, attestation written twice.
        self.assertEqual(result["native_files"], 5)
        self.assertEqual(set(p.name for p in package.iterdir()), set(names))
        self.assertNotEqual(records[3], records[4])
        self.assertEqual(
            json.loads((package / "publish_attestation.json").read_bytes())["signature"],
            json.loads(records[4])["signature"],
        )
        stderr = [r[3] for r in result["records"] if r[0] == "load_stderr"]
        self.assertEqual(
            stderr,
            [(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n").encode()] * 2,
        )
        self.assertEqual(result["physical_attempt_bytes"], sum(map(len, records)))

    def test_caught_source_serialization_model_and_logging_faults_sticky(self):
        for name in ("journal", "fixture", "audit", "logging"):
            capture = self.capture(name)
            driver = DriverOutputs(capture)
            build, fixture = fixture_producer(capture)
            emit, logger = audit_producer(capture)
            target = capture.register("row.jsonl", "journal")
            capture.register(
                "package-" + str(uuid.UUID(int=1)) + "/records.jsonl",
                "ephemeral",
                defer_parents=True,
            )
            with capture, self.assertRaises((TypeError, ValueError, adapter.PacketError)):
                if name == "journal":
                    rows = []
                    with target.open("x") as stream:
                        driver.journal(rows, stream)({"raw": object()})
                elif name == "fixture":
                    build(capture.native, package_id=uuid.UUID(int=1), text=object())
                elif name == "audit":
                    emit(
                        actor_id="a",
                        action=object(),
                        result="r",
                        reason="r",
                        request_id="r",
                        timestamp=fixture.NOW,
                    )
                else:
                    emit(
                        actor_id="a",
                        action="a",
                        result="r",
                        reason="x" * 600,
                        request_id="r",
                        timestamp=fixture.NOW,
                    )
            self.incomplete(capture)
            if name == "journal":
                self.assertEqual(len(rows), 1)
        for fault in (False, True):
            capture = self.capture("oracle-" + str(fault))
            driver = DriverOutputs(capture)
            final = capture.register("run/samples.json", "final_samples")
            summary = capture.register("run/latency-summary.json", "summary_stdout")
            rows = [
                {
                    "profile": 1,
                    "case": 0,
                    "operation": "admission",
                    "elapsed_ms": 1.0,
                    "okay": False,
                }
            ]
            original_write = capture.write_native
            final_error = OSError("final output I/O failure")

            def write(
                relative,
                raw,
                file,
                truncate,
                original_write=original_write,
                final_error=final_error,
                fault=fault,
            ):
                if fault and relative == "run/samples.json":
                    raise final_error
                return original_write(relative, raw, file, truncate)

            with (
                self.assertRaises(SystemExit) as caught,
                capture,
                patch.object(capture, "write_native", side_effect=write),
            ):
                driver.finish(rows, final.parent)
            self.assertEqual(caught.exception.code, 1)
            self.assertIs(caught.exception, capture._oracle_exit)
            self.assertEqual(json.loads(summary.read_bytes())["status"], "FAIL")
            if fault:
                self.assertIs(caught.exception.__cause__, final_error)
                self.incomplete(capture)
            else:
                self.assertEqual(json.loads(final.read_bytes()), rows)
                self.assertTrue(capture.finish()["prototype_complete"])
        arbitrary = self.capture("arbitrary-exit")
        with self.assertRaises(SystemExit), arbitrary:
            raise SystemExit(1)
        self.incomplete(arbitrary)

    def test_shared_prewrite_budget_overwrites_and_all_copies(self):
        empty = self.capture("empty-overwrite")
        path = empty.register("raw", "journal")
        with empty:
            path.write_text("first")
            path.write_text("")
        empty_result = empty.finish()
        self.assertEqual(path.read_bytes(), b"")
        self.assertEqual(empty_result["physical_attempt_bytes"], 5)
        self.assertEqual(
            [r[3] for r in empty_result["records"] if r[0] == "journal"], [b"first", b""]
        )
        binary = self.capture("binary")
        binary_path = binary.register("view", "journal")
        view = memoryview(array("I", [16909060]))
        with binary, binary_path.open("wb") as stream:
            self.assertEqual(stream.write(view), view.nbytes)
        binary.finish()
        self.assertEqual(binary_path.read_bytes(), view.tobytes())
        capture = self.capture()
        final = capture.register("final", "final_samples")
        journal = capture.register("journal", "journal")
        ephemeral = capture.register("temporary", "ephemeral")
        with capture:
            final.write_bytes(b"f" * 2097152)
            for number in range(16):
                ephemeral.write_bytes(bytes([number]) * 65536)
            with journal.open("wb") as stream:
                for _ in range(3200):
                    stream.write(b"j" * 512)
        self.assertEqual(ephemeral.stat().st_size, 65536)
        self.assertGreater(
            capture.physical,
            sum(p.stat().st_size for p in capture.native.rglob("*") if p.is_file()),
        )
        old_size = (capture.root / "packet/packet.bin").stat().st_size
        with self.assertRaises(adapter.PacketError):
            for _ in range(4096):
                capture.record("load_stderr", b"x" * 512)
        stopped_size = (capture.root / "packet/packet.bin").stat().st_size
        self.assertGreater(stopped_size, old_size)
        self.assertLessEqual(capture.charge, adapter.CAP)
        with self.assertRaises(adapter.PacketError):
            capture.record("load_stderr", b"more")
        self.assertEqual((capture.root / "packet/packet.bin").stat().st_size, stopped_size)
        self.incomplete(capture)

    def test_real_write_flush_cleanup_fault_and_original_identity(self):
        capture = self.capture(faults={"packet_write": "short"})
        target = capture.register("raw", "journal")
        with capture, self.assertRaises(OSError):
            target.write_text("raw")
        self.incomplete(capture)
        cleanup = self.capture("cleanup")
        first = cleanup.register("first", "journal")
        second = cleanup.register("second", "journal")

        class Original(BaseException):
            pass

        original = Original("original identity")
        flush_error = OSError("actual flush seam")

        class Proxy:
            def __init__(self, file):
                self.file = file

            def flush(self):
                raise flush_error

            def close(self):
                self.file.close()

        with self.assertRaises(Original) as caught, cleanup:
            one = first.open("w")
            two = second.open("w")
            one.write("one")
            two.write("two")
            one.file = Proxy(one.file)
            raise original
        self.assertIs(caught.exception, original)
        self.assertIs(original.__cause__, flush_error)
        self.assertTrue(one.closed and two.closed)
        self.incomplete(cleanup)

    def test_exclusive_hooks_foreign_threads_unsafe_and_bypass(self):
        for index, (kind, foreign) in enumerate(
            (
                ("file-write", True),
                ("file-flush", True),
                ("stderr-write", True),
                ("stderr-flush", True),
                ("record", True),
                ("close", True),
                ("finish-stream", True),
                ("file-write", False),
                ("file-flush", False),
                ("stderr-write", False),
                ("stderr-flush", False),
            )
        ):
            cached = self.capture("cached-" + str(index))
            path = cached.register("raw", "journal")
            failures = []

            def attempt(handle, endpoint, cached=cached, kind=kind, failures=failures):
                try:
                    if kind == "file-write":
                        handle.write("foreign")
                    elif kind == "file-flush":
                        handle.flush()
                    elif kind == "stderr-write":
                        endpoint.write("foreign")
                    elif kind == "stderr-flush":
                        endpoint.flush()
                    elif kind == "close":
                        handle.close()
                    elif kind == "finish-stream":
                        endpoint.finish()
                    else:
                        cached.record("journal", b"foreign")
                except BaseException as error:
                    failures.append(error)

            with cached:
                handle = path.open("w")
                handle.write("original")
                endpoint = cached.stderr
                charge = cached.charge
                if foreign:
                    thread = threading.Thread(target=attempt, args=(handle, endpoint))
                    thread.start()
                    thread.join()
            if not foreign:
                attempt(handle, endpoint)
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], adapter.PacketError)
            self.assertEqual(cached.charge, charge)
            self.assertEqual(path.read_bytes(), b"original")
            self.incomplete(cached)
        failed_enter = self.capture("failed-enter")
        emit, logger = audit_producer(failed_enter)
        sentinel = OSError("handler setup fault")
        with (
            patch.object(logging, "StreamHandler", side_effect=sentinel),
            self.assertRaises(OSError) as caught,
            failed_enter,
        ):
            pass
        self.assertIs(caught.exception, sentinel)
        self.assertFalse(failed_enter.active)
        self.assertEqual((builtins.open, io.open, os.mkdir, sys.stdout, sys.stderr), self.before)
        capture, competing = self.capture(), self.capture("competing")
        path = capture.register("raw", "journal")
        with capture:
            with self.assertRaises(adapter.PacketError), competing:
                pass
            failures = []

            def foreign():
                try:
                    path.write_text("foreign")
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=foreign)
            thread.start()
            thread.join()
            self.assertEqual(len(failures), 1)
        self.incomplete(capture)
        for name, mode in (
            ("extra", "file"),
            ("directory", "directory"),
            ("mutation", "registered"),
        ):
            owned = self.capture(name)
            target = owned.register("raw", "journal")
            with owned:
                target.write_text("original")
            if mode == "file":
                (owned.native / "unrouted").write_bytes(b"bypass")
            elif mode == "directory":
                (owned.native / "unrouted").mkdir()
            else:
                target.write_text("changed via cached/native path")
            self.incomplete(owned)
        bad = self.capture("unsafe")
        with self.assertRaises(adapter.PacketError):
            bad.register("../foreign", "journal")
        bad.abandon()

    def test_strict_recovery_missing_extra_corrupt_and_identity(self):
        for name in (
            "missing",
            "extra",
            "raw",
            "manifest",
            "symlink",
            "oversize",
            "large-manifest",
        ):
            capture = self.capture(name)
            path = capture.register("raw", "journal")
            with capture:
                path.write_text("exact")
            capture.finish()
            if name == "missing":
                path.unlink()
            elif name == "extra":
                (capture.root / "extra").write_text("bypass")
            elif name == "raw":
                path.write_text("tampered")
            elif name == "manifest":
                (capture.root / "manifest.json").write_text("{}")
            elif name == "oversize":
                with path.open("r+b") as stream:
                    stream.truncate(adapter.CAP + 1)
            elif name == "large-manifest":
                with (capture.root / "manifest.json").open("r+b") as stream:
                    stream.truncate(METADATA + 1)
            else:
                path.unlink()
                path.symlink_to(self.root / "foreign")
            with self.assertRaises((adapter.PacketError, OSError, ValueError, KeyError)):
                recover(capture.root)


class AsyncControls(unittest.IsolatedAsyncioTestCase):
    async def test_unframed_pipes_full_terminal_class_and_repeated_cancellation(self):
        with tempfile.TemporaryDirectory(prefix=".retention-test-", dir=HERE) as name:
            captures = []
            try:
                normal = Capture(Path(name) / "normal", enabled=True)
                captures.append(normal)
                result = await finite_child(normal)
                packet = normal.finish()
                for family, raw in result["outputs"].items():
                    self.assertEqual([r[3] for r in packet["records"] if r[0] == family], [raw])
                self.assertTrue(result["joined"] and result["full_class"])
                excess = Capture(Path(name) / "excess", enabled=True)
                captures.append(excess)
                with self.assertRaises(ValueError):
                    await finite_child(excess, "excess")
                with self.assertRaises(adapter.PacketError):
                    excess.finish()
                cancelled = Capture(Path(name) / "cancel", enabled=True)
                captures.append(cancelled)
                started = asyncio.Event()
                task = asyncio.create_task(finite_child(cancelled, "delay", started))
                await started.wait()
                task.cancel("original cancellation")
                await asyncio.sleep(0)
                task.cancel("again")
                await asyncio.sleep(0)
                with self.assertRaises(asyncio.CancelledError) as caught:
                    await task
                self.assertEqual(str(caught.exception), "original cancellation")
                self.assertEqual(
                    [t for t in asyncio.all_tasks() if t is not asyncio.current_task()], []
                )
                with self.assertRaises(adapter.PacketError):
                    cancelled.finish()
            finally:
                for capture in captures:
                    capture.abandon()
