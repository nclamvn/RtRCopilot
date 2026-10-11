"""Exclusive isolated Python retention; uncontrolled/native runtime routes remain HOLD."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import locale
import logging
import os
import sys
import threading
from pathlib import Path
from types import TracebackType
from typing import IO, Literal, NoReturn, Protocol, Self, cast

import adapter
from schemas import Files, OffResult, RecoveryResult, WriteStream, integer, mapping, native_files

HERE = Path(__file__).absolute().parent
CONTRACT_BYTES = (HERE.parents[1] / "r25/contract.json").read_bytes()
CONTRACT = json.loads(CONTRACT_BYTES)
EPOCH = bytes(range(16))
METADATA = 16384
PREFIX = b"RETENTION-MANIFEST:"
_ORIGINAL_OPEN, _ORIGINAL_IO_OPEN, _ORIGINAL_MKDIR = builtins.open, io.open, os.mkdir
_HOOK_LOCK = threading.Lock()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class NativeEndpoint:
    def __init__(
        self, capture: Capture, relative: str, file: WriteStream, text: bool, truncate: bool
    ) -> None:
        self.capture, self.relative, self.file = capture, relative, file
        self.text, self.truncate, self.closed = text, truncate, False

    def write(self, value: object) -> int:
        try:
            self.capture.guard(context=True)
            if self.closed:
                raise ValueError("closed owned file")
            raw = value.encode("utf-8") if self.text and type(value) is str else value
            if not self.text and isinstance(raw, bytearray | memoryview):
                raw = bytes(raw)
            if type(raw) is not bytes:
                raise TypeError("exact text/bytes producer payload")
            self.capture.write_native(self.relative, raw, self.file, self.truncate)
            self.truncate = False
            return len(cast(str, value)) if self.text else len(raw)
        except BaseException:
            self.capture.invalidate()
            raise

    def flush(self) -> None:
        try:
            self.capture.guard(context=True)
            if self.closed:
                self.capture.fail("closed native endpoint")
            self.file.flush()
            self.capture.writer.packet.flush()
        except BaseException:
            self.capture.invalidate()
            raise

    def close(self) -> None:
        self.capture.guard(context=True)
        if self.closed:
            return
        original = None
        try:
            self.flush()
        except BaseException as error:
            original = error
        try:
            self.file.close()
        except BaseException as cleanup:
            self.capture.invalidate()
            if original is not None:
                raise original from cleanup
            raise
        finally:
            self.closed = True
        if original is not None:
            raise original

    def fileno(self) -> NoReturn:
        self.capture.fail("unrouted native descriptor access")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        original: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            self.close()
        except BaseException as cleanup:
            if original is not None:
                original.add_note("retention file cleanup failed")
                raise original from cleanup
            raise
        return False


class StreamEndpoint:
    def __init__(self, capture: Capture, family: str) -> None:
        self.capture, self.family = capture, family
        self.buffer, self.closed = self, False
        self.encoding, self.errors = "utf-8", "strict"

    def write(self, value: object) -> int:
        try:
            self.capture.guard(context=True)
            raw = value.encode("utf-8") if type(value) is str else value
            if type(raw) is not bytes or self.closed:
                raise TypeError("active exact stream bytes/text")
            maximum = self.capture.writer.rules[(adapter.IDS.index(self.family) + 1, 1)][1]
            if len(raw) > maximum:
                self.capture.fail("whole stream exceeds domain; do not split")
            # One original producer write/emit call, not arbitrary read chunks.
            self.capture.record(self.family, raw)
            return len(value) if isinstance(value, str | bytes) else 0
        except BaseException:
            self.capture.invalidate()
            raise

    def flush(self) -> None:
        try:
            self.capture.guard(context=True)
            if self.closed:
                self.capture.fail("closed stream endpoint")
            self.capture.writer.packet.flush()
        except BaseException:
            self.capture.invalidate()
            raise

    def finish(self) -> None:
        self.capture.guard(context=True)
        if not self.closed:
            self.closed = True

    def fileno(self) -> NoReturn:
        self.capture.fail("unrouted stream descriptor access")

    def isatty(self) -> bool:
        return False


class Capture:
    def __init__(
        self,
        root: Path | None = None,
        *,
        enabled: bool = False,
        faults: dict[str, str] | None = None,
    ) -> None:
        if type(enabled) is not bool:
            raise ValueError("boolean explicit isolated opt-in")
        self.enabled, self.active, self.done = enabled, False, False
        self._writer: adapter.Writer | None = None
        self.owner_thread = threading.get_ident()
        self._oracle_exit: BaseException | None = None
        self.hooks_used = False
        self.mutex = threading.RLock()
        self.files: Files = {}
        self.handles: list[NativeEndpoint] = []
        self.loggers: list[tuple[logging.Logger]] = []
        self.physical, self.charge = 0, adapter.TERMINAL + adapter.CONTROLS + METADATA
        if not enabled:
            return
        if root is None:
            raise adapter.PacketError("enabled root required")
        self.root = adapter.safe(root)
        self.root.mkdir(mode=0o700)
        self.native = self.root / "files"
        self.native.mkdir()
        self._writer = adapter.Writer(self.root / "packet", CONTRACT, CONTRACT_BYTES, EPOCH, faults)

    @property
    def writer(self) -> adapter.Writer:
        if self._writer is None:
            raise adapter.PacketError("OFF has no writer")
        return self._writer

    def invalidate(self) -> None:
        if self._writer and not self._writer.finished and not self._writer.closed:
            self.writer.flags |= 1

    def fail(self, message: str) -> NoReturn:
        self.invalidate()
        raise adapter.PacketError(message)

    def guard(self, *, context: bool = False) -> None:
        if (
            threading.get_ident() != self.owner_thread
            or self.done
            or (self._writer is not None and (self._writer.finished or self._writer.closed))
            or (context and not self.active)
        ):
            self.fail("cached endpoint/epoch owner or active context mismatch")

    def reserve(self, size: int) -> None:
        if type(size) is not int or size < 0 or self.charge + size > adapter.CAP:
            self.fail("combined prewrite budget")
        self.charge += size  # No refund after failure, overwrite or deletion.

    def record(self, family: str, raw: bytes, physical: int = 0) -> int:
        with self.mutex:
            try:
                self.guard()  # Explicit non-hook finite-child route, creator thread only.
                if self.done:
                    raise adapter.PacketError("immutable committed local epoch")
                if type(raw) is not bytes:
                    raise TypeError("raw bytes")
                self.reserve(len(raw) + 11 + physical)
                sequence = self.writer.emit(family, "data", raw)
                self.physical += physical
                return sequence
            except BaseException:
                self.invalidate()
                raise

    def register(self, relative: str, family: str, *, defer_parents: bool = False) -> Path:
        try:
            self.guard()
            name = Path(relative)
            if (
                type(relative) is not str
                or name.is_absolute()
                or ".." in name.parts
                or name.as_posix() != relative
                or not name.parts
                or relative in self.files
                or type(family) is not str
                or family not in adapter.IDS
                or len(self.files) >= 32
            ):
                self.fail("registered canonical unique owned path/family")
            target = self.native / name
            if any(p.is_symlink() for p in (target, *target.parents)):
                self.fail("symlink")
            if not defer_parents:
                target.parent.mkdir(parents=True, exist_ok=True)
            self.files[relative] = {"family": family, "segments": []}
            return target
        except BaseException:
            self.invalidate()
            raise

    def write_native(self, relative: str, raw: bytes, file: WriteStream, truncate: bool) -> None:
        with self.mutex:
            self.guard(context=True)
            entry = self.files[relative]
            seq = self.record(entry["family"], raw, len(raw))
            segments = entry["segments"]
            mode = "w" if truncate else "a"
            if segments and mode == "a" and segments[-1][2] == "a" and segments[-1][1] == seq:
                segments[-1][1] = integer(segments[-1][1]) + 1
            else:
                segments.append([seq, seq + 1, mode])
            if len(canonical(self.files)) > METADATA - 2048:
                self.fail("finite native manifest domain")
            try:
                if file.write(raw) != len(raw):
                    raise OSError("short native write")
            except BaseException:
                self.invalidate()
                raise

    def routed_open(
        self,
        path: str | os.PathLike[str],
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: object = None,
    ) -> NativeEndpoint | IO[str] | IO[bytes]:
        try:
            if not self.active or threading.get_ident() != self.thread:
                self.fail("foreign/reentrant hook caller")
            target = Path(path).absolute()
            if any(p.is_symlink() for p in (target, *target.parents)):
                self.fail("unsafe file")
            name = target.relative_to(self.native).as_posix()
            if name not in self.files or opener is not None or not closefd or buffering != -1:
                self.fail("unrouted file API")
            if mode in ("r", "rb"):
                return cast(
                    IO[str] | IO[bytes],
                    _ORIGINAL_IO_OPEN(
                        target, mode, encoding=encoding, errors=errors, newline=newline
                    ),
                )
            if encoding == "locale" and locale.getencoding().lower().replace("_", "-") == "utf-8":
                encoding = "utf-8"
            if (
                mode not in ("x", "xb", "w", "wb", "a", "ab")
                or encoding not in (None, "utf-8")
                or errors not in (None, "strict")
                or newline not in (None, "\n")
            ):
                self.fail("unsupported encoding/newline/mode")
            file = _ORIGINAL_IO_OPEN(target, mode[0] + "b", buffering=0)
            handle = NativeEndpoint(self, name, file, "b" not in mode, mode[0] in "wx")
            self.handles.append(handle)
            return handle
        except BaseException:
            self.invalidate()
            raise

    def routed_mkdir(
        self, path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        try:
            target = Path(path).absolute()
            allowed = {self.native / parent for name in self.files for parent in Path(name).parents}
            if (
                dir_fd is not None
                or target not in allowed
                or threading.get_ident() != self.thread
                or any(p.is_symlink() for p in (target, *target.parents))
            ):
                self.fail("unrouted directory creation")
            return _ORIGINAL_MKDIR(target, mode)
        except BaseException:
            self.invalidate()
            raise

    def attach_logger(self, logger: logging.Logger) -> None:
        if (
            self.active
            or not isinstance(logger, logging.Logger)
            or any(old[0] is logger for old in self.loggers)
        ):
            self.fail("explicit unique logger before hooks")
        self.loggers.append((logger,))

    def restore(self) -> None:
        old_open, old_io, old_mkdir, old_stdout, old_stderr = self.previous
        cast(HookNamespace, builtins).open = old_open
        cast(HookNamespace, io).open = old_io
        cast(HookNamespace, os).mkdir = old_mkdir
        sys.stdout, sys.stderr = old_stdout, old_stderr
        for logger, handlers, filters, level, propagate, disabled, cache in self.logger_states:
            logger.handlers = handlers
            cast(LoggerSlots, logger).filters = filters
            logger.level, logger.propagate, logger.disabled = (
                level,
                propagate,
                disabled,
            )
            cast(LoggerSlots, logger)._cache = cache
        error = None
        for handler in self.new_handlers:
            try:
                handler.close()
            except BaseException as cleanup:
                if error is None:
                    error = cleanup
            finally:
                cast(HandlerSlot, handler).stream = None
        self.active = False
        _HOOK_LOCK.release()
        if error is not None:
            raise error

    def __enter__(self) -> Self:
        if not self.enabled:
            return self
        self.guard()
        if self.active or self.done or self.hooks_used or not _HOOK_LOCK.acquire(blocking=False):
            self.fail("exclusive non-reentrant hook owner")
        self.hooks_used = True
        self.thread, self.active = threading.get_ident(), True
        self.previous = (builtins.open, io.open, os.mkdir, sys.stdout, sys.stderr)
        self.logger_states: list[
            tuple[logging.Logger, list[logging.Handler], object, int, bool, bool, dict[int, bool]]
        ] = []
        self.new_handlers: list[logging.StreamHandler[StreamEndpoint]] = []
        self.stdout, self.stderr = (
            StreamEndpoint(self, "summary_stdout"),
            StreamEndpoint(self, "load_stderr"),
        )
        cast(HookNamespace, builtins).open = self.routed_open
        cast(HookNamespace, io).open = self.routed_open
        cast(HookNamespace, os).mkdir = self.routed_mkdir
        cast(HookNamespace, sys).stdout = self.stdout
        cast(HookNamespace, sys).stderr = self.stderr
        try:
            if logging.root.manager.disable != 0:
                self.fail("unsupported manager-level logging disable")
            for (logger,) in self.loggers:
                self.logger_states.append(
                    (
                        logger,
                        logger.handlers,
                        logger.filters,
                        logger.level,
                        logger.propagate,
                        logger.disabled,
                        logger_cache(logger),
                    )
                )
                handler = CaptureHandler(self, self.stderr)
                self.new_handlers.append(handler)
                handler.setFormatter(logging.Formatter("%(message)s"))

                logger.handlers, logger.filters = [handler], []
                cast(LoggerSlots, logger)._cache = {}
                logger.level, logger.propagate, logger.disabled = logging.INFO, False, False
        except BaseException as original:
            self.invalidate()
            try:
                self.restore()
            except BaseException as cleanup:
                raise original from cleanup
            raise
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        original: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if not self.enabled:
            return False
        self.guard(context=True)
        error = None
        try:
            for action in [handle.close for handle in self.handles] + [
                self.stdout.finish,
                self.stderr.finish,
            ]:
                try:
                    action()
                except BaseException as cleanup:
                    self.invalidate()
                    if error is None:
                        error = cleanup
                    else:
                        error.add_note("additional owned cleanup failed: " + type(cleanup).__name__)
        finally:
            try:
                self.restore()
            except BaseException as cleanup:
                self.invalidate()
                if error is None:
                    error = cleanup
        if original is not None:
            if error is not None or original is not self._oracle_exit:
                self.invalidate()
            if error is not None:
                original.add_note("retention stream cleanup failed")
                raise original from error
            return False
        if error is not None:
            raise error
        return False

    def finish(self) -> RecoveryResult | OffResult:
        self.guard()
        if self.active:
            self.fail("cannot seal active Python routing")
        if not self.enabled:
            return {"captured": False, "measurement_admission": "HOLD"}
        try:
            expected = rebuild(self.writer_payloads(), self.files)
            check_files(self.native, expected)
            manifest = {
                "schema": "r27-native-v1",
                "retention_adoption": "APPROVED_ISOLATED_ONLY",
                "files": self.files,
                "charge": self.charge,
                "physical": self.physical,
                "source_hashes": source_hashes(),
                "measurement_admission": "HOLD",
            }
            raw = canonical(manifest)
            if len(raw) > METADATA:
                self.fail("metadata reserve")
            with _ORIGINAL_IO_OPEN(self.root / "manifest.json", "xb", buffering=0) as file:
                if file.write(raw) != len(raw):
                    raise OSError("short manifest")
                file.flush()
                os.fsync(file.fileno())
            self.record("source_cap_child", PREFIX + sha(raw).encode())
            for family in adapter.IDS:
                self.writer.close_family(family)
            self.writer.finish()
            self.done = True
            return recover(self.root)
        except BaseException:
            self.invalidate()
            raise

    def writer_payloads(self) -> list[adapter.Record]:
        self.writer.packet.flush()
        raw = (self.root / "packet/packet.bin").read_bytes()
        # Before receipts: append a synthetic grammar trailer only for internal raw reconstruction.
        counts, sizes = self.writer.counts, self.writer.sizes
        for code, (count, size) in enumerate(zip(counts, sizes, strict=True), 1):
            raw += adapter.CLOSE.pack(b"C", code, count, size, int(count == 0), b"\n")
        raw += adapter.FINAL.pack(b"T", 0, 0, (1 << 20) - 1, sum(counts), self.writer.normal, b"\n")
        return adapter.parse(raw, self.writer.rules)

    def abandon(self) -> None:
        if threading.get_ident() != self.owner_thread:
            self.fail("foreign cleanup owner")
        if self._writer:
            self._writer.abandon()


def source_hashes() -> dict[str, str]:
    from producers import SOURCES, read_source

    for name in SOURCES:
        read_source(name)
    return dict(SOURCES)


def rebuild(records: list[adapter.Record], files: Files) -> dict[str, bytes]:
    by_key = {(family, seq): raw for family, variant, seq, raw in records if variant == 1}
    expected, used = {}, set()
    for name, entry in files.items():
        raw = b""
        for segment in entry["segments"]:
            start, stop, mode = integer(segment[0]), integer(segment[1]), segment[2]
            if (
                type(start) is not int
                or type(stop) is not int
                or start < 0
                or stop <= start
                or mode not in ("w", "a")
            ):
                raise adapter.PacketError("native segment")
            if mode == "w":
                raw = b""
            for seq in range(start, stop):
                key = (entry["family"], seq)
                if key in used or key not in by_key:
                    raise adapter.PacketError("missing/duplicate native record")
                used.add(key)
                raw += by_key[key]
        expected[name] = raw
    return expected


def check_files(root: Path, expected: dict[str, bytes]) -> None:
    actual = set()
    directories = {Path(name).parent.as_posix() for name in expected}
    directories |= {
        p.as_posix() for name in expected for p in Path(name).parents if p.as_posix() != "."
    }
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_relative_to(root):
            raise adapter.PacketError("native symlink")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            actual.add(name)
            if name not in expected or bounded_read(path, len(expected[name])) != expected[name]:
                raise adapter.PacketError("native bypass/corruption")
        elif path.is_dir() and path.relative_to(root).as_posix() not in directories:
            raise adapter.PacketError("extra native directory")
    if actual != set(expected):
        raise adapter.PacketError("missing native file")


def recover(root: Path) -> RecoveryResult:
    root = adapter.safe(root)
    if set(p.name for p in root.iterdir()) != {"packet", "files", "manifest.json"}:
        raise adapter.PacketError("outer bypass/missing file")
    if any(p.is_symlink() for p in root.rglob("*")):
        raise adapter.PacketError("symlink")
    raw = bounded_read(root / "manifest.json", METADATA)
    if len(raw) > METADATA:
        raise adapter.PacketError("metadata cap")
    manifest = mapping(json.loads(raw))
    if (
        manifest.get("schema") != "r27-native-v1"
        or manifest.get("retention_adoption") != "APPROVED_ISOLATED_ONLY"
        or manifest.get("measurement_admission") != "HOLD"
    ):
        raise adapter.PacketError("scoped retention grant/qualification metadata")
    if canonical(manifest) != raw or manifest["source_hashes"] != source_hashes():
        raise adapter.PacketError("metadata/source drift")
    result = adapter.recover(root / "packet", CONTRACT, CONTRACT_BYTES, EPOCH)
    markers = [r[3] for r in result["records"] if r[0] == "source_cap_child"]
    if markers != [PREFIX + sha(raw).encode()]:
        raise adapter.PacketError("unbound native metadata")
    files = native_files(manifest["files"])
    expected = rebuild(result["records"], files)
    check_files(root / "files", expected)
    physical = sum(
        len(record[3])
        for record in result["records"]
        if any(
            entry["family"] == record[0]
            and any(
                integer(segment[0]) <= record[2] < integer(segment[1])
                for segment in entry["segments"]
            )
            for entry in files.values()
        )
    )
    normal = sum(len(r[3]) + 11 for r in result["records"])
    charge = normal + physical + adapter.TERMINAL + adapter.CONTROLS + METADATA
    stored = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    # Manifest charge was sealed just before its own fixed-size packet marker.
    if (
        type(manifest["charge"]) is not int
        or type(manifest["physical"]) is not int
        or manifest["physical"] != physical
        or integer(manifest["charge"]) + len(PREFIX) + 64 + 11 != charge
        or charge > adapter.CAP
        or stored > charge
    ):
        raise adapter.PacketError("shared aggregate proof")
    return {
        **result,
        "charge": charge,
        "physical_attempt_bytes": physical,
        "all_live_file_bytes": stored,
        "native_files": len(expected),
        "measurement_admission": "HOLD",
    }


def bounded_read(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise adapter.PacketError("bounded regular file read")
    with _ORIGINAL_IO_OPEN(path, "rb") as file:
        raw = file.read(maximum + 1)
        if len(raw) > maximum or len(raw) != os.fstat(file.fileno()).st_size:
            raise adapter.PacketError("changed/oversize file")
        return raw


def logger_cache(logger: logging.Logger) -> dict[int, bool]:
    value: object = cast(LoggerSlots, logger)._cache
    if not isinstance(value, dict) or any(
        type(k) is not int or type(v) is not bool for k, v in value.items()
    ):
        raise adapter.PacketError("unsupported logger cache")
    return cast(dict[int, bool], value)


class CaptureHandler(logging.StreamHandler[StreamEndpoint]):
    def __init__(self, capture: Capture, stream: StreamEndpoint) -> None:
        super().__init__(stream)
        self.capture = capture

    def handleError(self, record: logging.LogRecord) -> NoReturn:
        self.capture.invalidate()
        error = sys.exc_info()[1]
        if error is None:
            raise adapter.PacketError("logging error without exception")
        raise error


class HookNamespace(Protocol):
    """Mutable namespace slots only; installed callables validate their own API."""

    open: object
    mkdir: object
    stdout: object
    stderr: object


class LoggerSlots(Protocol):
    filters: object
    _cache: object


class HandlerSlot(Protocol):
    stream: StreamEndpoint | None
