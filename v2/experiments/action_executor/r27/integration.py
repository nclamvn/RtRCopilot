"""Default-OFF isolated real routing; global measured-source routing remains HOLD."""

import asyncio
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

from source_subset import owner_probe, retain_function

HERE = Path(__file__).absolute().parent
API_FAMILIES = {"journal", "final_samples", "summary_stdout", "load_stderr", "ephemeral", "source_cap_child"}


def backend():
    derivation = json.loads((HERE / "derivation.json").read_bytes())
    path = HERE / "adapter.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != derivation["derived_sha256"]:
        raise ValueError("derived adapter changed")
    spec = importlib.util.spec_from_file_location("r27_owned_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JournalEndpoint:
    def __init__(self, capture, flush_error=None):
        self.capture, self.flush_error = capture, flush_error

    def write(self, text):
        try:
            self.capture.record("journal", text.encode())
            return len(text)
        except BaseException:
            self.capture.invalidate()
            raise

    def flush(self):
        try:
            if self.flush_error is not None:
                raise self.flush_error
            self.capture.writer.packet.flush()
        except BaseException:
            self.capture.invalidate()
            raise


class Capture:
    def __init__(self, path=None, *, enabled=False, faults=None):
        if type(enabled) is not bool:
            raise ValueError("explicit boolean local opt-in")
        self.enabled, self.writer = enabled, None
        self.module = backend() if enabled else None
        if enabled:
            raw = (HERE.parent / "r25/contract.json").read_bytes()
            self.writer = self.module.Writer(path, json.loads(raw), raw, bytes(range(16)), faults)
            try:
                self.record("source_cap_child", b'{"scope":"isolated-local-source-subsets","global_capture":"HOLD"}')
            except BaseException as original:
                try:
                    self.writer.abandon()
                except BaseException as cleanup:
                    original.add_note("local capture constructor cleanup raised " + type(cleanup).__name__)
                    raise original from cleanup
                raise

    def __enter__(self):
        return self

    def __exit__(self, kind, original, traceback):
        if self.writer:
            try:
                self.writer.abandon()
            except BaseException as cleanup:
                if original is not None:
                    original.add_note("local capture cleanup raised " + type(cleanup).__name__)
                    raise original from cleanup
                raise
        return False

    def record(self, family, payload):
        if not self.enabled:
            return None
        if type(family) is not str or family not in API_FAMILIES:
            self.writer._fail("family not connected to local endpoint")
        return self.writer.emit(family, "data", payload)

    def invalidate(self):
        # Post-commit misuse cannot change the immutable committed epoch.
        if self.writer and not self.writer.finished and not self.writer.closed:
            self.writer.flags |= 1

    def journal(self, records, flush_error=None):
        if not self.enabled:
            raise ValueError("OFF requires original owned stream, not a capture endpoint")
        original = retain_function(records, JournalEndpoint(self, flush_error))[0]
        def dispatch(record):
            try:
                return original(record)
            except BaseException:
                self.invalidate()
                raise
        return dispatch

    def copy_records(self, records):
        # Explicit local copy endpoint; not the old driver's finalization path.
        try:
            self.record("final_samples", json.dumps(records, indent=2).encode())
        except BaseException:
            self.invalidate()
            raise

    def finish_local(self):
        if not self.enabled:
            return {"captured": False, "global_capture": "HOLD"}
        for family in self.module.IDS:
            self.writer.close_family(family)
        self.writer.finish()
        raw = (HERE.parent / "r25/contract.json").read_bytes()
        result = self.module.recover(self.writer.path, json.loads(raw), raw, bytes(range(16)))
        result["scope"] = "isolated local fixture only; zero receipts are not original producer routing"
        return result

    def finish_measured(self):
        if self.writer:
            self.writer._fail("unconnected original channels; measurement HOLD")
        raise ValueError("measurement not admitted")


async def pipe_fixture(capture, mode="ok", started=None):
    if mode not in {"ok", "delay", "oversize", "partial"}:
        raise ValueError("fixed finite child modes")
    outputs = {"summary_stdout": [], "load_stderr": []}

    async def drain(reader, family, maximum):
        consumed = 0
        while True:
            try:
                head = await reader.readexactly(4)
            except asyncio.IncompleteReadError as error:
                if error.partial:
                    raise
                return
            length = struct.unpack(">I", head)[0]
            if length > maximum:
                # Known fixture emits <1024 bytes/stream. Drain rejection, never split to evade domains.
                while data := await reader.read(1024):
                    consumed += len(data)
                    if consumed > 4096:
                        raise ValueError("fixed fixture drain bound exceeded")
                raise ValueError("unsupported whole pipe record; incomplete")
            payload = await reader.readexactly(length)
            consumed += length + 4
            if consumed > 4096 or len(outputs[family]) >= 4:
                raise ValueError("fixed fixture count/accumulator bound")
            outputs[family].append(payload)

    async def joined():
        # Spawn itself belongs to the shielded, joined terminal operation, not an orphanable prelude.
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-B", str(HERE / "pipe_source.py"), mode,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=HERE, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
        if started is not None:
            started.set()
        values = await asyncio.gather(drain(process.stdout, "summary_stdout", 16384),
                                      drain(process.stderr, "load_stderr", 512), process.wait(),
                                      return_exceptions=True)
        for value in values:
            if isinstance(value, BaseException):
                raise value
        if process.returncode != 0:
            raise RuntimeError("fixed local child failed")
        return {"outputs": outputs, "returncode": process.returncode}

    probe = owner_probe()
    try:
        result = await probe.join_terminal(joined())
        for family, records in result["outputs"].items():
            for payload in records:
                capture.record(family, payload)
        return {**result, "joined": probe.terminal_task is None, "source_subset": True}
    except BaseException:
        # Exact terminal method already joined both readers and child before forwarding failure/cancel.
        if capture.writer:
            capture.invalidate()
        raise
