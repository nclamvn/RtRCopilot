"""Creator-owned broker port and immutable, generation-checked parser snapshots."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from ports import Mode, PathPort, RichPath, Stat, name_checked
from writer import Broker

SNAPSHOT_CAP = 2097152


class OwnedBroker(Broker):
    def __init__(self, root: Path, faults: dict[str, str] | None = None) -> None:
        super().__init__(root, faults)
        self.first_fault: BaseException | None = None
        self._fault_lock = threading.Lock()

    def capture_fault(self, error: BaseException) -> None:
        with self._fault_lock:
            if self.first_fault is None:
                self.first_fault = error
        self.invalidate()


class HostPort:
    def __init__(self, broker: OwnedBroker) -> None:
        self._broker = broker
        self._owner = threading.get_ident()
        self.namespace = uuid.uuid4().hex
        self._lease = broker.begin_operation()
        self._files: set[str] = set()
        self.closed = False

    @property
    def first_fault(self) -> BaseException | None:
        return self._broker.first_fault

    def check(self) -> None:
        self.owner_check()
        if self.first_fault is not None:
            raise self.first_fault
        self._broker._guard()

    def owner_check(self) -> None:
        if self.closed or threading.get_ident() != self._owner:
            error = ValueError("creator/live producer port")
            self._broker.capture_fault(error)
            raise error

    def _call[T](self, action: Callable[[], T]) -> T:
        try:
            self.check()
            return action()
        except BaseException as error:
            self._broker.capture_fault(error)
            raise

    def invalidate(self) -> None:
        self._broker.invalidate()

    def capture_fault(self, error: BaseException) -> None:
        self._broker.capture_fault(error)

    def path(self, name: str = "", family: str = "ephemeral") -> RichPath:
        return self._call(lambda: RichPath(self, name, family))

    def write(self, name: str, family: str, raw: bytes, mode: Mode) -> int:
        def perform() -> int:
            name_checked(name)
            if mode not in {"w", "a", "x"} or type(raw) is not bytes:
                raise ValueError("whole admitted write")
            path = self._broker.path(name, family)
            self._broker._write(path, raw, "a" if mode == "a" else "w", exclusive=mode == "x")
            return len(raw)

        return self._call(perform)

    def read(self, name: str) -> bytes:
        return self._call(lambda: self._broker.path(name_checked(name)).read_bytes())

    def stat(self, name: str) -> Stat:
        def perform() -> Stat:
            name_checked(name)
            if name in self._broker._directories:
                target = self._broker._native if not name else self._broker._target(name)
                if not target.is_dir() or target.is_symlink():
                    raise ValueError("native directory drift")
                return Stat(True, True, 0)
            entry = self._broker._entries.get(name)
            if entry is None or not entry["exists"]:
                return Stat(False, False, 0)
            target = self._broker._target(name)
            if not target.is_file():
                raise ValueError("native file drift")
            return Stat(True, False, target.stat().st_size)

        return self._call(perform)

    def listdir(self, name: str) -> tuple[str, ...]:
        def perform() -> tuple[str, ...]:
            state = self.stat(name)
            if not state.exists or not state.is_dir:
                raise NotADirectoryError(name)
            prefix = name + "/" if name else ""
            names = {
                key[len(prefix) :].split("/", 1)[0]
                for key in (
                    *self._broker._directories,
                    *(key for key, entry in self._broker._entries.items() if entry["exists"]),
                )
                if key.startswith(prefix) and key != name
            }
            target = self._broker._native if not name else self._broker._target(name)
            if {p.name for p in target.iterdir()} != names:
                raise ValueError("native member inventory drift")
            return tuple(sorted(names))

        return self._call(perform)

    def mkdir(self, name: str, parents: bool = False, exist_ok: bool = False) -> None:
        self._call(lambda: self._broker.path(name_checked(name)).mkdir(parents, exist_ok))

    def delete(self, name: str) -> None:
        def perform() -> None:
            if not name_checked(name):
                raise ValueError("never delete epoch root")
            if name in self._broker._directories:
                if self.listdir(name):
                    raise OSError("directory not empty")
                directories = self._broker._directories - {name}
                self._broker._metadata(self._broker._entries, directories)
                self._broker._target(name).rmdir()
                self._broker._directories = directories
            else:
                self._broker.path(name).unlink()

        self._call(perform)

    def flush(self) -> None:
        self._call(lambda: self._broker._flush(self._broker._token))

    def record(self, family: str, raw: bytes) -> int:
        return self._call(lambda: self._broker.record(family, raw))

    def _snapshot_data(self, prefix: str) -> tuple[dict[str, bytes], tuple[str, ...]]:
        name_checked(prefix)

        def in_scope(name: str) -> bool:
            return name == prefix or name.startswith(prefix + "/") or not prefix

        directories = tuple(sorted(n for n in self._broker._directories if in_scope(n)))
        files: dict[str, bytes] = {}
        total = 0
        for name, entry in self._broker._entries.items():
            if entry["exists"] and in_scope(name):
                if self.stat(name).size > SNAPSHOT_CAP - total:
                    raise ValueError("finite parser snapshot before read")
                raw = self.read(name)
                total += len(raw)
                if total > SNAPSHOT_CAP:
                    raise ValueError("finite parser snapshot")
                files[name] = raw
        return files, directories

    def generation(self, prefix: str = "") -> str:
        def perform() -> str:
            files, directories = self._snapshot_data(prefix)
            metadata = [
                directories,
                [(name, hashlib.sha256(raw).hexdigest()) for name, raw in sorted(files.items())],
            ]
            return hashlib.sha256(json.dumps(metadata, separators=(",", ":")).encode()).hexdigest()

        return self._call(perform)

    def snapshot(self, prefix: str = "") -> PathPort:
        def perform() -> SnapshotPort:
            files, directories = self._snapshot_data(prefix)
            return SnapshotPort(self, prefix, self.generation(prefix), files, directories)

        return self._call(perform)

    def file_open(self) -> str:
        def perform() -> str:
            if len(self._files) >= 32:
                raise ValueError("active logical handles")
            token = uuid.uuid4().hex
            self._files.add(token)
            return token

        return self._call(perform)

    def file_close(self, token: str) -> None:
        if self.closed or threading.get_ident() != self._owner or token not in self._files:
            self._broker.capture_fault(ValueError("owned logical handle release"))
            raise ValueError("owned logical handle release")
        self._files.remove(token)

    def close(self) -> None:
        if not self.closed:
            if threading.get_ident() != self._owner or self._files:
                error = ValueError("unclosed/foreign producer port")
                self._broker.capture_fault(error)
                raise error
            self.closed = True
            self._broker.end_operation(self._lease)

    def __enter__(self) -> HostPort:
        self.check()
        return self

    def __exit__(self, kind: object, error: BaseException | None, trace: object) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            if error is None:
                raise
            if error is cleanup:
                raise
            raise error from cleanup


class SnapshotPort:
    def __init__(
        self,
        parent: PathPort,
        prefix: str,
        version: str,
        files: dict[str, bytes],
        directories: tuple[str, ...],
    ) -> None:
        self._parent, self._prefix, self._version = parent, prefix, version
        self._files, self._directories = dict(files), directories
        self.namespace = parent.namespace

    @property
    def first_fault(self) -> BaseException | None:
        return self._parent.first_fault

    def check(self) -> None:
        self._parent.check()
        if self._parent.generation(self._prefix) != self._version:
            error = ValueError("stale parser snapshot")
            self.capture_fault(error)
            raise error

    def owner_check(self) -> None:
        self._parent.owner_check()

    def path(self, name: str = "", family: str = "ephemeral") -> RichPath:
        self.check()
        return RichPath(self, name, family)

    def read(self, name: str) -> bytes:
        try:
            self.check()
            return self._files[name_checked(name)]
        except BaseException as error:
            self.capture_fault(error)
            raise

    def stat(self, name: str) -> Stat:
        self.check()
        name_checked(name)
        return Stat(
            name in self._directories or name in self._files,
            name in self._directories,
            len(self._files.get(name, b"")),
        )

    def listdir(self, name: str) -> tuple[str, ...]:
        self.check()
        if name not in self._directories:
            raise NotADirectoryError(name)
        prefix = name + "/" if name else ""
        return tuple(
            sorted(
                {
                    key[len(prefix) :].split("/", 1)[0]
                    for key in (*self._directories, *self._files)
                    if key.startswith(prefix) and key != name
                }
            )
        )

    def invalidate(self) -> None:
        self._parent.invalidate()

    def capture_fault(self, error: BaseException) -> None:
        self._parent.capture_fault(error)

    def _deny(self) -> None:
        self.invalidate()
        raise ValueError("immutable parser snapshot")

    def write(self, name: str, family: str, raw: bytes, mode: Mode) -> int:
        self._deny()
        raise AssertionError("unreachable")

    def mkdir(self, name: str, parents: bool = False, exist_ok: bool = False) -> None:
        self._deny()

    def delete(self, name: str) -> None:
        self._deny()

    def flush(self) -> None:
        self.check()

    def record(self, family: str, raw: bytes) -> int:
        self._deny()
        raise AssertionError("unreachable")

    def generation(self, prefix: str = "") -> str:
        self.check()
        return self._version

    def snapshot(self, prefix: str = "") -> PathPort:
        self.check()
        return self

    def file_open(self) -> str:
        self.check()
        return self._parent.file_open()

    def file_close(self, token: str) -> None:
        self._parent.file_close(token)
