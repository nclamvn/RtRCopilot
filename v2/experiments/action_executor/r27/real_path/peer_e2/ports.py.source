"""Opaque synchronous producer paths; no native storage pathname or descriptor."""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, Protocol

Mode = Literal["w", "a", "x"]


@dataclass(frozen=True)
class Stat:
    exists: bool
    is_dir: bool
    size: int

    @property
    def st_size(self) -> int:
        return self.size


class PathPort(Protocol):
    namespace: str

    @property
    def first_fault(self) -> BaseException | None: ...

    def path(self, name: str = "", family: str = "ephemeral") -> RichPath: ...
    def write(self, name: str, family: str, raw: bytes, mode: Mode) -> int: ...
    def read(self, name: str) -> bytes: ...
    def stat(self, name: str) -> Stat: ...
    def listdir(self, name: str) -> tuple[str, ...]: ...
    def mkdir(self, name: str, parents: bool = False, exist_ok: bool = False) -> None: ...
    def delete(self, name: str) -> None: ...
    def flush(self) -> None: ...
    def record(self, family: str, raw: bytes) -> int: ...
    def invalidate(self) -> None: ...
    def capture_fault(self, error: BaseException) -> None: ...
    def generation(self, prefix: str = "") -> str: ...
    def snapshot(self, prefix: str = "") -> PathPort: ...
    def check(self) -> None: ...
    def owner_check(self) -> None: ...
    def file_open(self) -> str: ...
    def file_close(self, token: str) -> None: ...


def name_checked(name: str) -> str:
    if type(name) is not str or len(name) > 256:
        raise ValueError("bounded logical pathname")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or (name and p.as_posix() != name):
        raise ValueError("canonical logical pathname")
    return name


class RichPath:
    def __init__(self, port: PathPort, name: str, family: str) -> None:
        self._port = port
        try:
            self._name = name_checked(name)
            if type(family) is not str:
                raise TypeError("family string")
            self._family = family
        except BaseException as error:
            port.capture_fault(error)
            raise

    @property
    def namespace(self) -> str:
        return self._port.namespace

    @property
    def logical_path(self) -> str:
        return "/evidence/r27-logical/" + self._port.namespace + "/" + self._name

    def __str__(self) -> str:
        return self.logical_path

    def __fspath__(self) -> str:
        self._port.invalidate()
        raise TypeError("logical producer path cannot export native capability")

    def __hash__(self) -> int:
        return hash((self._port.namespace, self._name))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, RichPath)
            and self._port.namespace == other._port.namespace
            and self._name == other._name
        )

    def __truediv__(self, child: str) -> RichPath:
        try:
            name_checked(child)
            if not child:
                raise ValueError("nonempty child")
            return self._port.path("/".join(filter(None, (self._name, child))), self._family)
        except BaseException as error:
            self._port.capture_fault(error)
            raise

    @property
    def name(self) -> str:
        return PurePosixPath(self._name).name if self._name else ""

    @property
    def parent(self) -> RichPath:
        p = PurePosixPath(self._name).parent.as_posix()
        return self._port.path("" if p == "." else p, self._family)

    @property
    def parents(self) -> tuple[RichPath, ...]:
        result: list[RichPath] = []
        p = self
        while p._name:
            p = p.parent
            result.append(p)
        return tuple(result)

    def resolve(self, strict: bool = False) -> RichPath:
        if strict and not self.exists():
            raise FileNotFoundError(self.logical_path)
        return self

    def relative_to(self, other: RichPath) -> PurePosixPath:
        if self._port.namespace != other._port.namespace:
            raise ValueError("foreign namespace")
        return PurePosixPath(self._name).relative_to(PurePosixPath(other._name))

    def is_symlink(self) -> bool:
        self._port.stat(self._name)  # Owner validates native layout; facade has no symlinks.
        return False

    def exists(self) -> bool:
        return self._port.stat(self._name).exists

    def is_dir(self) -> bool:
        state = self._port.stat(self._name)
        return state.exists and state.is_dir

    def is_file(self) -> bool:
        state = self._port.stat(self._name)
        return state.exists and not state.is_dir

    def stat(self) -> Stat:
        state = self._port.stat(self._name)
        if not state.exists:
            raise FileNotFoundError(self.logical_path)
        return state

    def iterdir(self) -> Iterator[RichPath]:
        return iter(tuple(self / name for name in self._port.listdir(self._name)))

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self._port.mkdir(self._name, parents, exist_ok)

    def unlink(self, missing_ok: bool = False) -> None:
        if missing_ok and not self.exists():
            return
        self._port.delete(self._name)

    def rmdir(self) -> None:
        self._port.delete(self._name)

    def write_bytes(self, value: bytes | bytearray | memoryview) -> int:
        try:
            if not isinstance(value, bytes | bytearray | memoryview):
                raise TypeError("bytes-like payload required")
            return self._port.write(self._name, self._family, bytes(value), "w")
        except BaseException as error:
            self._port.capture_fault(error)
            raise

    def write_text(self, text: str, encoding: str = "utf-8", errors: str = "strict") -> int:
        try:
            if type(text) is not str or encoding != "utf-8" or errors != "strict":
                raise TypeError("exact UTF-8 text endpoint")
            self._port.write(self._name, self._family, text.encode(), "w")
            return len(text)
        except BaseException as error:
            self._port.capture_fault(error)
            raise

    def read_bytes(self) -> bytes:
        return self._port.read(self._name)

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        try:
            if encoding != "utf-8" or errors != "strict":
                raise ValueError("exact UTF-8 read endpoint")
            return self.read_bytes().decode()
        except BaseException as error:
            self._port.capture_fault(error)
            raise

    def open(self, mode: str = "r", encoding: str = "utf-8") -> PortFile:
        try:
            if mode not in {"r", "rb", "w", "wb", "x", "xb", "a", "ab"}:
                raise ValueError("unsupported mode")
            if encoding != "utf-8":
                raise ValueError("exact encoding")
            return PortFile(self, mode)
        except BaseException as error:
            self._port.capture_fault(error)
            raise

    def snapshot(self) -> RichPath:
        return self._port.snapshot(self._name).path(self._name, self._family)


class PortFile:
    def __init__(self, path: RichPath, mode: str) -> None:
        self._path, self._mode = path, mode
        self._wrote, self.closed = False, False
        self._token = path._port.file_open()
        try:
            self._reader = io.BytesIO(path.read_bytes()) if mode.startswith("r") else None
        except BaseException:
            path._port.file_close(self._token)
            raise

    def _guard(self) -> None:
        self._path._port.check()
        if self.closed:
            self._path._port.invalidate()
            raise ValueError("closed logical handle")

    def fileno(self) -> int:
        self._path._port.invalidate()
        raise TypeError("no native file descriptor")

    def write(self, value: str | bytes | bytearray | memoryview) -> int:
        try:
            self._guard()
            if self._reader is not None:
                raise io.UnsupportedOperation("read-only port")
            binary = "b" in self._mode
            if binary:
                if not isinstance(value, bytes | bytearray | memoryview):
                    raise TypeError("binary whole payload")
                raw, count = bytes(value), memoryview(value).nbytes
            else:
                if type(value) is not str:
                    raise TypeError("text whole payload")
                raw, count = value.encode(), len(value)
            mode: Mode = (
                "a"
                if self._wrote or self._mode.startswith("a")
                else ("x" if self._mode.startswith("x") else "w")
            )
            self._path._port.write(self._path._name, self._path._family, raw, mode)
            self._wrote = True
            return count
        except BaseException as error:
            self._path._port.capture_fault(error)
            raise

    def read(self, size: int = -1) -> bytes | str:
        try:
            self._guard()
            if self._reader is None:
                raise io.UnsupportedOperation("write-only port")
            raw = self._reader.read(size)
            return raw if "b" in self._mode else raw.decode()
        except BaseException as error:
            self._path._port.capture_fault(error)
            raise

    def __iter__(self) -> Iterator[bytes]:
        self._guard()
        if self._reader is None or "b" not in self._mode:
            error = io.UnsupportedOperation("binary line iteration only")
            self._path._port.capture_fault(error)
            raise error
        return self

    def __next__(self) -> bytes:
        try:
            self._guard()
            if self._reader is None or "b" not in self._mode:
                raise io.UnsupportedOperation("binary line iteration only")
            line = self._reader.readline()
        except BaseException as error:
            self._path._port.capture_fault(error)
            raise
        if not line:
            raise StopIteration
        return line

    def flush(self) -> None:
        self._guard()
        if self._reader is None:
            self._path._port.flush()

    def close(self) -> None:
        if not self.closed:
            self._path._port.owner_check()
            try:
                if self._reader is None:
                    if not self._wrote:
                        self.write(b"" if "b" in self._mode else "")
                    self.flush()
                else:
                    self._reader.close()
            finally:
                self.closed = True
                self._path._port.file_close(self._token)

    def __enter__(self) -> PortFile:
        self._guard()
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: object
    ) -> None:
        try:
            self.close()
        except BaseException as cleanup:
            if error is None:
                raise
            if error is cleanup:
                raise
            raise error from cleanup
