"""Host sole-writer for pinned cooperative producers; never an OS-wide sandbox."""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, NoReturn, Self, TypedDict, cast

import adapter

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
BASE = ROOT / "v2/experiments/action_executor/r25/contract.json"
BASE_SHA = "43e24fdef2e1acfd3f00b409e9fd5a46853c4105d4b3c71f329b93c6f1eccbcc"
BOUNDARY_SHA = "66dff0f467b9cc7e7c4cd982580ba9101ee69e95d6be5f9c04c0a9ee439554f2"
SCOPE_SHA = "7dc21bff55537e5e1101ead159bb86f1aa3b4eef3e687939a7d1af774f97c0a9"
METADATA = 16384
PREFIX = b"BROKER-MANIFEST:"
MARKER_BYTES = len(PREFIX) + 64 + 11
EPOCH = b"R27BROKERLOCAL01"
Mode = Literal["w", "a"]


class Entry(TypedDict):
    family: str
    segments: list[list[int | str]]
    exists: bool


class Recovery(TypedDict):
    prototype_complete: bool
    records: list[tuple[str, int, int, bytes]]
    stored_bytes: int
    actual_capture_admission: str
    power_loss_proved: bool
    charge: int
    physical_attempt_bytes: int
    native_files: int
    platform_audit: str


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(k) is not str for k in value):
        raise adapter.PacketError("string-key object")
    return cast(dict[str, object], value)


def integer(value: object) -> int:
    if type(value) is not int:
        raise adapter.PacketError("exact integer")
    return value


def logical(name: str, *, root: bool = False) -> str:
    if type(name) is not str or (not name and not root):
        raise adapter.PacketError("logical name")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or (name and path.as_posix() != name):
        raise adapter.PacketError("canonical relative capability")
    return name


def witnesses() -> dict[str, str]:
    files = [
        *HERE.glob("*.py"),
        *HERE.glob("*.pyi"),
        HERE / "SCOPE.md",
        HERE / "boundary.json",
        BASE,
    ]
    result = {}
    for path in files:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
            raise adapter.PacketError("source witness")
        result[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    if result[BASE.relative_to(ROOT).as_posix()] != BASE_SHA:
        raise adapter.PacketError("base contract drift")
    if (
        result[(HERE / "boundary.json").relative_to(ROOT).as_posix()] != BOUNDARY_SHA
        or result[(HERE / "SCOPE.md").relative_to(ROOT).as_posix()] != SCOPE_SHA
    ):
        raise adapter.PacketError("exact approved boundary/scope drift")
    boundary = mapping(json.loads((HERE / "boundary.json").read_bytes()))
    if boundary["decision"] != "APPROVED_LOCAL_IMPLEMENTATION":
        raise adapter.PacketError("approved local boundary required")
    return result


class Broker:
    """Private owner state; producers receive ProducerPath/ProducerFile only."""

    def __init__(self, root: Path, faults: dict[str, str] | None = None) -> None:
        self._owner = threading.get_ident()
        self._mutex = threading.RLock()
        self._token = uuid.uuid4().hex
        self._finished = False
        self._faults = dict(faults or {})
        self._source = witnesses()
        self._contract_bytes = BASE.read_bytes()
        self._contract: object = json.loads(self._contract_bytes)
        self._root = adapter.safe(root)
        self._root.mkdir(mode=0o700)
        self._native = self._root / "files"
        self._native.mkdir()
        self._writer = adapter.Writer(
            self._root / "packet", self._contract, self._contract_bytes, EPOCH, self._faults
        )
        self._entries: dict[str, Entry] = {}
        self._directories: set[str] = {""}
        self._handles: list[ProducerFile] = []
        self._tombstones: list[list[str | int]] = []
        self._sealing = False
        self._physical = 0
        self._charge = adapter.TERMINAL + adapter.CONTROLS + METADATA

    @property
    def charge(self) -> int:
        return self._charge

    def invalidate(self) -> None:
        if not self._finished and not self._writer.closed and not self._writer.finished:
            self._writer.flags |= 1

    def fail(self, reason: str) -> NoReturn:
        self.invalidate()
        raise adapter.PacketError(reason)

    def _guard(self, token: str | None = None) -> None:
        if (
            threading.get_ident() != self._owner
            or self._finished
            or self._writer.closed
            or self._writer.finished
            or (token is not None and token != self._token)
        ):
            self.fail("creator/active capability epoch")
        if self._writer.flags:
            raise adapter.PacketError("sticky incomplete epoch")

    def _trip(self, name: str) -> None:
        if self._faults.pop(name, None) == "raise":
            raise OSError("injected " + name)

    def _target(self, name: str) -> Path:
        target = self._native / logical(name)
        if any(p.is_symlink() for p in (target, *target.parents)):
            self.fail("owned symlink")
        return target

    def _manifest(
        self,
        entries: dict[str, Entry],
        directories: set[str],
        tombstones: list[list[str | int]],
        *,
        ceiling: bool = False,
    ) -> dict[str, object]:
        return {
            "schema": "r27-broker-files-v1",
            "files": entries,
            "directories": sorted(directories),
            "tombstones": tombstones,
            "physical": adapter.CAP if ceiling else self._physical,
            "charge": adapter.CAP if ceiling else self._charge,
            "source_hashes": self._source,
            "platform_audit": "SEPARATE_DISCLOSED_OUTSIDE_QUALIFYING_PACKET",
        }

    def _metadata(
        self,
        entries: dict[str, Entry],
        directories: set[str],
        tombstones: list[list[str | int]] | None = None,
    ) -> None:
        deleted = self._tombstones if tombstones is None else tombstones
        if (
            len(entries) > 32
            or len(directories) > 64
            or len(deleted) > 64
            or len(canonical(self._manifest(entries, directories, deleted, ceiling=True)))
            > METADATA
        ):
            self.fail("pre-I/O finite metadata domain")

    def _domain(self, family: str, raw: bytes) -> None:
        if type(family) is not str or family not in adapter.IDS or type(raw) is not bytes:
            self.fail("whole exact raw family payload")
        code = adapter.IDS.index(family) + 1
        count, maximum = self._writer.rules[(code, 1)]
        reserved = 1 if family == "source_cap_child" and not self._sealing else 0
        if (
            code in self._writer.receipts
            or self._writer.next.get((code, 1), 0) >= count - reserved
            or len(raw) > maximum
        ):
            self.fail("whole record/count domain; never split")

    def _reserve(self, amount: int) -> None:
        remaining_marker = 0 if self._sealing else MARKER_BYTES
        if (
            type(amount) is not int
            or amount < 0
            or self._charge + amount + remaining_marker > adapter.CAP
        ):
            self.fail("combined prewrite cap")
        self._charge += amount

    def record(self, family: str, raw: bytes) -> int:
        with self._mutex:
            try:
                self._guard()
                self._domain(family, raw)
                self._reserve(len(raw) + 11)
                return self._writer.emit(family, "data", raw)
            except BaseException:
                self.invalidate()
                raise

    def path(self, name: str = "", family: str = "ephemeral") -> ProducerPath:
        try:
            self._guard()
            logical(name, root=True)
            if type(family) is not str or family not in adapter.IDS:
                self.fail("path family")
            return ProducerPath(self, self._token, name, family)
        except BaseException:
            self.invalidate()
            raise

    def _write(
        self, path: ProducerPath, raw: bytes, mode: Mode, *, exclusive: bool = False
    ) -> None:
        with self._mutex:
            try:
                self._guard(path._token)
                name = logical(path._name)
                self._domain(path._family, raw)
                old = self._entries.get(name)
                if old and old["family"] != path._family:
                    self.fail("immutable artifact family")
                exists = old is not None and old["exists"]
                if exclusive and exists:
                    raise FileExistsError(name)
                parent = Path(name).parent.as_posix()
                if ("" if parent == "." else parent) not in self._directories:
                    raise FileNotFoundError("logical parent")
                seq = self._writer.next.get((adapter.IDS.index(path._family) + 1, 1), 0)
                entry: Entry = {
                    "family": path._family,
                    "segments": [list(s) for s in old["segments"]] if old else [],
                    "exists": True,
                }
                if not exists:
                    mode = "w"
                segments = entry["segments"]
                if (
                    mode == "a"
                    and segments
                    and segments[-1][2] == "a"
                    and integer(segments[-1][1]) == seq
                ):
                    segments[-1][1] = seq + 1
                else:
                    segments.append([seq, seq + 1, mode])
                proposed = dict(self._entries)
                proposed[name] = entry
                self._metadata(proposed, self._directories)
                target = self._target(name)
                self._reserve(len(raw) * 2 + 11)
                self._physical += len(raw)
                self._writer.emit(path._family, "data", raw)
                self._entries = proposed
                self._trip("native_open")
                # No destructive open before domain, aggregate AND metadata admission.
                with target.open(("x" if exclusive else mode) + "b", buffering=0) as file:
                    action = self._faults.pop("native_write", None)
                    if action == "raise":
                        raise OSError("injected native write")
                    if action == "short":
                        file.write(raw[:1])
                        raise OSError("injected short native write")
                    if file.write(raw) != len(raw):
                        raise OSError("short native write")
                    self._trip("native_flush")
                    file.flush()
                    self._trip("native_fsync")
                    os.fsync(file.fileno())
            except BaseException:
                self.invalidate()
                raise

    def _mkdir(self, path: ProducerPath, parents: bool, exist_ok: bool) -> None:
        with self._mutex:
            try:
                self._guard(path._token)
                name = logical(path._name, root=True)
                if name in self._directories:
                    if not exist_ok:
                        raise FileExistsError(name)
                    return
                parent = Path(name).parent.as_posix()
                if not parents and ("" if parent == "." else parent) not in self._directories:
                    raise FileNotFoundError(parent)
                added = {name}
                if parents:
                    added |= {p.as_posix() for p in Path(name).parents if p.as_posix() != "."}
                directories = self._directories | added
                self._metadata(self._entries, directories)
                self._target(name).mkdir(parents=parents, exist_ok=exist_ok)
                self._directories = directories
            except BaseException:
                self.invalidate()
                raise

    def _read(self, path: ProducerPath) -> bytes:
        try:
            self._guard(path._token)
            entry = self._entries.get(path._name)
            if entry is None or not entry["exists"]:
                raise FileNotFoundError(path._name)
            return bounded_read(self._target(path._name), adapter.CAP)
        except BaseException:
            self.invalidate()
            raise

    def _delete(self, path: ProducerPath) -> None:
        with self._mutex:
            try:
                self._guard(path._token)
                old = self._entries.get(path._name)
                if old is None or not old["exists"]:
                    raise FileNotFoundError(path._name)
                changed: Entry = {
                    "family": old["family"],
                    "segments": old["segments"],
                    "exists": False,
                }
                proposed = dict(self._entries)
                proposed[path._name] = changed
                tombstones: list[list[str | int]] = [
                    *self._tombstones,
                    [path._name, sum(self._writer.counts)],
                ]
                self._metadata(proposed, self._directories, tombstones)
                self._trip("native_delete")
                self._target(path._name).unlink()
                self._entries = proposed
                self._tombstones = tombstones
            except BaseException:
                self.invalidate()
                raise

    def _flush(self, token: str) -> None:
        try:
            self._guard(token)
            self._trip("flush")
            self._writer.packet.flush()
        except BaseException:
            self.invalidate()
            raise

    def finish(self) -> Recovery:
        self._guard()
        if any(not handle.closed for handle in self._handles):
            self.fail("unclosed producer port")
        try:
            if witnesses() != self._source:
                self.fail("source drift")
            manifest = self._manifest(self._entries, self._directories, self._tombstones)
            if set(p.name for p in self._root.iterdir()) != {"packet", "files"} or any(
                p.is_symlink() for p in self._root.rglob("*")
            ):
                self.fail("precommit owned layout")
            records = self._payloads()
            physical, _ = check_native(self._root, manifest, records, final_marker=False)
            normal = sum(len(record[3]) + 11 for record in records)
            if (
                physical != self._physical
                or self._charge
                != normal + physical + adapter.TERMINAL + adapter.CONTROLS + METADATA
            ):
                self.fail("precommit shared accounting")
            raw = canonical(manifest)
            if len(raw) > METADATA:
                self.fail("metadata reserve")
            marker = PREFIX + digest(raw).encode()
            self._sealing = True
            self._domain("source_cap_child", marker)
            if self._charge + MARKER_BYTES > adapter.CAP:
                self.fail("final marker capacity before manifest I/O")
            self._trip("manifest")
            with (self._root / "manifest.json").open("xb", buffering=0) as file:
                if file.write(raw) != len(raw):
                    raise OSError("short manifest")
                file.flush()
                os.fsync(file.fileno())
            self.record("source_cap_child", marker)
            for family in adapter.IDS:
                self._writer.close_family(family)
            self._writer.finish()
            self._finished = True
            return recover(self._root)
        except BaseException:
            self.invalidate()
            raise

    def _payloads(self) -> list[adapter.Record]:
        self._writer.packet.flush()
        raw = bounded_read(self._root / "packet/packet.bin", adapter.CAP)
        for code, (count, size) in enumerate(
            zip(self._writer.counts, self._writer.sizes, strict=True), 1
        ):
            raw += adapter.CLOSE.pack(b"C", code, count, size, int(count == 0), b"\n")
        raw += adapter.FINAL.pack(
            b"T", 0, 0, (1 << 20) - 1, sum(self._writer.counts), self._writer.normal, b"\n"
        )
        return adapter.parse(raw, self._writer.rules)

    def abandon(self) -> None:
        if threading.get_ident() != self._owner:
            self.fail("foreign abandon")
        self._writer.abandon()


@dataclass(frozen=True)
class Stat:
    st_size: int


class ProducerPath:
    """Logical capability, not os.PathLike; no physical path/descriptor export."""

    def __init__(self, broker: Broker, token: str, name: str, family: str) -> None:
        self._broker, self._token, self._name, self._family = broker, token, name, family

    def __truediv__(self, name: str) -> ProducerPath:
        try:
            self._broker._guard(self._token)
            return ProducerPath(
                self._broker, self._token, logical(str(Path(self._name) / name)), self._family
            )
        except BaseException:
            self._broker.invalidate()
            raise

    @property
    def parent(self) -> ProducerPath:
        name = Path(self._name).parent.as_posix()
        return ProducerPath(self._broker, self._token, "" if name == "." else name, self._family)

    @property
    def name(self) -> str:
        return Path(self._name).name

    def as_posix(self) -> str:
        return self._name

    def __fspath__(self) -> NoReturn:
        self._broker.fail("opaque capability cannot become native OS path")

    def fileno(self) -> NoReturn:
        self._broker.fail("no raw file descriptor")

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self._broker._mkdir(self, parents, exist_ok)

    def write_bytes(self, raw: object) -> int:
        try:
            if not isinstance(raw, bytes | bytearray | memoryview):
                raise TypeError("exact binary payload, not bytes(integer)")
            value = bytes(raw)
            self._broker._write(self, value, "w")
            return len(value)
        except BaseException:
            self._broker.invalidate()
            raise

    def write_text(
        self,
        text: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        with self.open("w", encoding=encoding, errors=errors, newline=newline) as file:
            return file.write(text)

    def read_bytes(self) -> bytes:
        return self._broker._read(self)

    def read_text(self, encoding: str = "utf-8") -> str:
        try:
            if encoding != "utf-8":
                self._broker.fail("supported UTF-8 read")
            return self.read_bytes().decode(encoding)
        except BaseException:
            self._broker.invalidate()
            raise

    def stat(self) -> Stat:
        return Stat(len(self.read_bytes()))

    def exists(self) -> bool:
        self._broker._guard(self._token)
        entry = self._broker._entries.get(self._name)
        return self._name in self._broker._directories or (entry is not None and entry["exists"])

    def is_file(self) -> bool:
        return self.exists() and self._name in self._broker._entries

    def is_dir(self) -> bool:
        self._broker._guard(self._token)
        return self._name in self._broker._directories

    def unlink(self) -> None:
        self._broker._delete(self)

    def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> ProducerFile:
        try:
            self._broker._guard(self._token)
            if len(self._broker._handles) >= 32:
                self._broker.fail("finite active producer port count")
            if (
                mode not in ("r", "rb", "w", "wb", "x", "xb", "a", "ab")
                or buffering != -1
                or encoding not in (None, "utf-8")
                or errors not in (None, "strict")
                or newline not in (None, "\n")
            ):
                self._broker.fail("supported opaque file API")
            handle = ProducerFile(self, mode)
            self._broker._handles.append(handle)
            return handle
        except BaseException:
            self._broker.invalidate()
            raise


class ProducerFile:
    def __init__(self, path: ProducerPath, mode: str) -> None:
        self._path, self._mode, self._started, self.closed = path, mode, False, False

    def _guard(self) -> None:
        self._path._broker._guard(self._path._token)
        if self.closed:
            self._path._broker.fail("closed port")

    def write(self, value: object) -> int:
        try:
            self._guard()
            if self._mode[0] == "r":
                raise io.UnsupportedOperation("read-only port")
            if "b" in self._mode:
                if not isinstance(value, bytes | bytearray | memoryview):
                    raise TypeError("binary payload")
                raw, result = bytes(value), len(bytes(value))
            else:
                if type(value) is not str:
                    raise TypeError("text payload")
                raw, result = value.encode("utf-8"), len(value)
            self._path._broker._write(
                self._path,
                raw,
                "a" if self._started or self._mode[0] == "a" else "w",
                exclusive=not self._started and self._mode[0] == "x",
            )
            self._started = True
            return result
        except BaseException:
            self._path._broker.invalidate()
            raise

    def read(self) -> str | bytes:
        try:
            self._guard()
            if self._mode[0] != "r":
                raise io.UnsupportedOperation("write-only port")
            raw = self._path.read_bytes()
            return raw if "b" in self._mode else raw.decode()
        except BaseException:
            self._path._broker.invalidate()
            raise

    def flush(self) -> None:
        self._guard()
        self._path._broker._flush(self._path._token)

    def close(self) -> None:
        self._path._broker._guard(self._path._token)
        if self.closed:
            return
        try:
            if not self._started and self._mode[0] != "r":
                self.write(b"" if "b" in self._mode else "")
            self.flush()
        finally:
            self.closed = True
            if self in self._path._broker._handles:
                self._path._broker._handles.remove(self)

    def fileno(self) -> NoReturn:
        self._path._broker.fail("no raw file descriptor")

    def __enter__(self) -> Self:
        self._guard()
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
                raise original from cleanup
            raise
        return False


def bounded_read(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise adapter.PacketError("bounded regular file")
    with path.open("rb") as file:
        raw = file.read(maximum + 1)
        if len(raw) > maximum or len(raw) != os.fstat(file.fileno()).st_size:
            raise adapter.PacketError("changed/oversize file")
        return raw


def recover(root: Path) -> Recovery:
    root = adapter.safe(root)
    if set(p.name for p in root.iterdir()) != {"packet", "files", "manifest.json"} or any(
        p.is_symlink() for p in root.rglob("*")
    ):
        raise adapter.PacketError("owned layout")
    raw = bounded_read(root / "manifest.json", METADATA)
    manifest = mapping(json.loads(raw))
    if (
        canonical(manifest) != raw
        or manifest.get("schema") != "r27-broker-files-v1"
        or manifest.get("source_hashes") != witnesses()
        or manifest.get("platform_audit") != "SEPARATE_DISCLOSED_OUTSIDE_QUALIFYING_PACKET"
    ):
        raise adapter.PacketError("metadata/source/approved boundary")
    result = adapter.recover(
        root / "packet", json.loads(BASE.read_bytes()), BASE.read_bytes(), EPOCH
    )
    if [r[3] for r in result["records"] if r[0] == "source_cap_child"][-1:] != [
        PREFIX + digest(raw).encode()
    ]:
        raise adapter.PacketError("manifest packet binding")
    physical, native_count = check_native(root, manifest, result["records"])
    normal = sum(len(r[3]) + 11 for r in result["records"])
    charge = normal + physical + adapter.TERMINAL + adapter.CONTROLS + METADATA
    stored = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    if (
        integer(manifest["physical"]) != physical
        or integer(manifest["charge"]) + len(PREFIX) + 64 + 11 != charge
        or charge > adapter.CAP
        or stored > charge
    ):
        raise adapter.PacketError("shared physical cap")
    return {
        **result,
        "charge": charge,
        "physical_attempt_bytes": physical,
        "native_files": native_count,
        "platform_audit": "SEPARATE_DISCLOSED_OUTSIDE_QUALIFYING_PACKET",
    }


def check_native(
    root: Path,
    manifest: dict[str, object],
    records_input: list[adapter.Record],
    *,
    final_marker: bool = True,
) -> tuple[int, int]:
    records = {
        (family, seq): payload for family, variant, seq, payload in records_input if variant == 1
    }
    positions = {
        (family, seq): index + 1
        for index, (family, variant, seq, _) in enumerate(records_input)
        if variant == 1
    }
    deleted: dict[str, list[int]] = {}
    tombstones = manifest["tombstones"]
    if not isinstance(tombstones, list) or len(tombstones) > 64:
        raise adapter.PacketError("finite deletion history")
    previous = 0
    for tombstone in tombstones:
        if not isinstance(tombstone, list) or len(tombstone) != 2 or type(tombstone[0]) is not str:
            raise adapter.PacketError("typed deletion history")
        name, after = logical(tombstone[0]), integer(tombstone[1])
        if (
            after < previous
            or after < 1
            or after > len(records_input) - int(final_marker)
            or after in deleted.get(name, [])
        ):
            raise adapter.PacketError("ordered deletion history")
        previous = after
        deleted.setdefault(name, []).append(after)
    expected: dict[str, bytes] = {}
    physical, used = 0, set[tuple[str, int]]()
    for name, value in mapping(manifest["files"]).items():
        logical(name)
        entry = mapping(value)
        family, segments, exists = entry["family"], entry["segments"], entry["exists"]
        if (
            type(family) is not str
            or family not in adapter.IDS
            or not isinstance(segments, list)
            or type(exists) is not bool
        ):
            raise adapter.PacketError("native shape")
        content = b""
        timeline: list[tuple[int, int, str, bytes]] = []
        for segment in segments:
            if not isinstance(segment, list) or len(segment) != 3:
                raise adapter.PacketError("segment shape")
            start, stop, mode = integer(segment[0]), integer(segment[1]), segment[2]
            if start < 0 or stop <= start or mode not in ("w", "a"):
                raise adapter.PacketError("segment domain")
            for sequence in range(start, stop):
                key = (family, sequence)
                if key in used or key not in records:
                    raise adapter.PacketError("duplicate/missing raw sidecar payload")
                used.add(key)
                physical += len(records[key])
                timeline.append((positions[key], 0, cast(str, mode), records[key]))
        timeline += [(index, 1, "delete", b"") for index in deleted.pop(name, [])]
        live = False
        for _, _, action, payload in sorted(timeline):
            if action == "delete":
                if not live:
                    raise adapter.PacketError("delete absent artifact")
                live, content = False, b""
            else:
                if action == "w":
                    content = b""
                elif not live:
                    raise adapter.PacketError("append absent artifact")
                live = True
                content += payload
        if live is not exists:
            raise adapter.PacketError("deletion/write final-state conservation")
        if exists:
            expected[name] = content
    if deleted:
        raise adapter.PacketError("unknown deletion artifact")
    directories = manifest["directories"]
    if not isinstance(directories, list) or any(type(d) is not str for d in directories):
        raise adapter.PacketError("directories")
    declared = set(cast(list[str], directories))
    for directory in declared:
        logical(directory, root=True)
    actual_files, actual_dirs = set[str](), {""}
    for path in (root / "files").rglob("*"):
        name = path.relative_to(root / "files").as_posix()
        if path.is_file():
            actual_files.add(name)
            if name not in expected or bounded_read(path, len(expected[name])) != expected[name]:
                raise adapter.PacketError("native extra/corrupt bytes")
        elif path.is_dir():
            actual_dirs.add(name)
        else:
            raise adapter.PacketError("nonregular native path")
    if actual_files != set(expected) or actual_dirs != declared:
        raise adapter.PacketError("missing/extra native layout")
    return physical, len(expected)
