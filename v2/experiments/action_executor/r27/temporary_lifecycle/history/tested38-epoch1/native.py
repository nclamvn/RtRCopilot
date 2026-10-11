"""Creator-owned real native filesystem. Opaque descriptors never export OS FDs."""

from __future__ import annotations

import ast
import errno
import json
import os
import posixpath
import stat
import threading
import uuid
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import NoReturn, TypedDict, cast

import adapter
import bridge
import policy
import writer

Record = tuple[str, int, int, bytes]


def bind(function: object, namespace: dict[str, object]) -> Callable[..., object]:
    original = cast(FunctionType, function)
    value = FunctionType(
        original.__code__, namespace, original.__name__, original.__defaults__
    )
    value.__kwdefaults__ = original.__kwdefaults__
    return value


def limits(contract: object) -> dict[tuple[int, int], tuple[int, int]]:
    if contract != policy.wanted():
        raise adapter.PacketError("exact owned lifecycle codec policy")
    result = {(i, 1): (1, 0) for i in range(1, 21)}
    result[(19, 2)] = (1, 0)
    for family, variant, count, maximum in policy.DOMAINS.values():
        result[(adapter.IDS.index(family) + 1, variant)] = (count, maximum)
    if (
        sum(n * (size + 11) for n, size in result.values())
        + adapter.TERMINAL
        + adapter.CONTROLS
        > adapter.CAP
    ):
        raise adapter.PacketError("coarse codec cap")
    return result


def semantic(owner: adapter.Writer, family: str, role: str) -> int:
    domain = policy.DOMAINS.get(role)
    if domain is None or domain[0] != family:
        owner.flags |= 1
        error = adapter.PacketError("owned lifecycle semantic role")
        setattr(owner, "_first_semantic_fault", error)
        raise error
    return domain[1]


CODEC_GLOBALS: dict[str, object] = {
    **vars(adapter),
    "limits": limits,
    "semantic": semantic,
}


class PacketWriter(adapter.Writer):
    pass


def install_codec() -> None:
    policy.guard()
    tree = ast.parse(bridge.bounded(policy.REFERENCE / "adapter.py"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Writer"
    )
    method = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "emit"
    )
    changes = 0
    for node in ast.walk(method):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "subtype" for t in node.targets
        ):
            node.value = ast.copy_location(
                ast.parse("semantic(self, family, variant)", mode="eval").body,
                node.value,
            )
            changes += 1
    if changes != 1:
        raise adapter.PacketError("one pinned semantic AST delta")
    namespace = dict(CODEC_GLOBALS)
    exec(
        compile(
            ast.fix_missing_locations(ast.Module([method], [])),
            str(policy.REFERENCE / "adapter.py"),
            "exec",
        ),
        namespace,
    )
    for name, implementation in {
        "__init__": bind(adapter.Writer.__init__, CODEC_GLOBALS),
        "emit": namespace["emit"],
    }.items():
        setattr(PacketWriter, name, implementation)


install_codec()
PACKET_RECOVER = bind(adapter.recover, CODEC_GLOBALS)


@dataclass(frozen=True)
class Descriptor:
    epoch: str
    serial: int


@dataclass
class NativeFD:
    fd: int
    name: str
    directory: bool
    dev: int
    ino: int
    mode: int
    flags: int


class Frame(TypedDict):
    family: str
    variant: int
    seq: int
    role: str
    path: str
    mode: str
    requested: int


class Namespace(SimpleNamespace):
    def __init__(self, owner: Owner, **values: object) -> None:
        super().__init__(_owner=owner, **values)

    def __getattr__(self, name: str) -> NoReturn:
        cast(Owner, self._owner).fail(
            PermissionError("unsupported private source attribute: " + name)
        )


class Recovery(TypedDict):
    stage: str
    charge: int
    physical_attempt_bytes: int
    records: list[Record]
    events: list[dict[str, object]]
    artifacts: dict[str, dict[str, object]]
    actual_capture_admission: str


class Owner:
    def __init__(
        self, root: Path, faults: dict[str, tuple[str, bool]] | None = None
    ) -> None:
        self.source = policy.guard()
        self.root = adapter.safe(root)
        self.thread = threading.get_ident()
        self.epoch = uuid.uuid4().hex
        self.virtual = "/r27-owned/" + self.epoch
        self.closed = False
        self.first_fault: BaseException | None = None
        self.faults = dict(faults or {})
        self.events: list[dict[str, object]] = []
        self.frames: list[Frame] = []
        self.raw_records: list[Record] = []
        self.artifacts: dict[str, dict[str, object]] = {}
        self.directories: set[str] = {""}
        self.lifetime_dirs: set[str] = {""}
        self.fds: dict[Descriptor, NativeFD] = {}
        self.serial = self.attempts = self.discovery = self.collisions = 0
        self.finalizers: list[object] = []
        self.finalized_objects: list[object] = []
        self.synthetic_root: str | None = None
        self.synthetic_calls: dict[str, int] = {}
        self.observations: dict[str, dict[str, object]] = {}
        self.generation: dict[str, int] = {}
        self.permission_controls: set[str] = set()
        self.cleanup_errors: list[str] = []
        self.source_outcomes: list[dict[str, object]] = []
        self.cleanup_phase = False
        self.warning_count = 0
        self.selected_fd_peak = 4
        self.captures: dict[str, dict[str, object]] = {}
        self.buffers: dict[str, list[bytes]] = {}
        self.capture_fds: dict[str, Descriptor] = {}
        self.physical = 0
        self.charge = policy.META + adapter.TERMINAL + adapter.CONTROLS
        self.files = self.root / "files"
        self.meta_fd = -1
        created = False
        try:
            self.root.mkdir(mode=0o700)
            created = True
            self.files.mkdir(mode=0o700)
            info = self.files.stat()
            self.root_identity = [
                info.st_dev,
                info.st_ino,
                info.st_mode,
                getattr(info, "st_flags", 0),
            ]
            self.meta_fd = os.open(
                self.root / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            contract, raw = policy.contract()
            constructor_fault = self.faults.pop("constructor_packet", None)
            self.packet = PacketWriter(
                self.root / "packet",
                contract,
                raw,
                policy.EPOCH,
                {"owner_write": "raise"}
                if constructor_fault == ("storage", False)
                else None,
            )
        except BaseException as error:
            if self.meta_fd != -1:
                os.close(self.meta_fd)
            if created:
                try:
                    for path in (
                        self.root / "packet/packet.bin",
                        self.root / "packet/owner.bin",
                        self.root / "manifest.json",
                    ):
                        if path.exists() and not path.is_symlink() and path.is_file():
                            path.unlink()
                    for path in (self.root / "packet", self.files, self.root):
                        if path.exists():
                            path.rmdir()
                except BaseException as cleanup_error:
                    error.add_note("owned constructor cleanup: " + str(cleanup_error))
            raise
        self.os = self.os_namespace()

    def fail(self, error: BaseException) -> NoReturn:
        if self.first_fault is None:
            self.first_fault = error
        self.packet.flags |= 1
        raise error

    def guard(self, *, cleanup: bool = False) -> None:
        if threading.get_ident() != self.thread or self.closed:
            raise adapter.PacketError("creator/live lifecycle epoch")
        if self.packet.flags and self.first_fault is None:
            self.first_fault = getattr(
                self.packet,
                "_first_semantic_fault",
                adapter.PacketError("private codec already failed"),
            )
        if self.first_fault is not None and not cleanup:
            raise self.first_fault

    def name(self, path: object, directory: Descriptor | None = None) -> str:
        self.guard(cleanup=True)
        if isinstance(path, CapPath):
            if path.owner is not self:
                self.fail(adapter.PacketError("foreign path epoch"))
            value = path.name_value
        elif type(path) is str:
            text = path
            if text.startswith(self.virtual + "/"):
                value = text[len(self.virtual) + 1 :]
            elif text == self.virtual:
                value = ""
            elif text in {"/tmp", "/var/tmp", "/usr/tmp"}:
                value = "candidates/" + text.strip("/").replace("/", "-")
            elif directory is not None and "/" not in text:
                value = posixpath.join(self.fd(directory).name, text)
            else:
                self.fail(adapter.PacketError("unowned native alias/path"))
        else:
            self.fail(adapter.PacketError("closed native path type"))
        if (
            value.startswith("/")
            or ".." in value.split("/")
            or posixpath.normpath(value or ".") != (value or ".")
            or len(value.encode()) > 256
            or len(value.split("/")) > 8
        ):
            self.fail(adapter.PacketError("finite canonical native name"))
        return value

    def path(self, value: object) -> CapPath:
        return CapPath(self, self.name(value))

    def target(self, name: str, *, follow: bool = False) -> Path:
        self.name(self.virtual + ("/" + name if name else ""))
        target = self.files / name
        for parent in target.parents:
            if parent == self.files.parent:
                break
            if parent.is_symlink():
                self.fail(adapter.PacketError("symlink parent traversal"))
        if target.is_symlink():
            item = self.artifacts.get(name)
            if (
                item is None
                or item.get("kind") != "link"
                or os.readlink(target) != item["target"]
            ):
                self.fail(adapter.PacketError("unowned native symlink"))
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), cast(str, item["target"]))
            )
            if resolved.startswith("../") or resolved not in self.lifetime_dirs:
                self.fail(adapter.PacketError("external symlink target"))
            if follow:
                return self.files / resolved
        return target

    def metadata(self) -> dict[str, object]:
        return {
            "schema": "r27-owned-lifecycle-files-v1",
            "stage": "LOCAL_NATIVE_LIFECYCLE",
            "source": self.source,
            "contract_sha256": writer.digest(policy.contract()[1]),
            "artifacts": self.artifacts,
            "directories": sorted(self.directories),
            "lifetime_dirs": sorted(self.lifetime_dirs),
            "frames": self.frames,
            "events": self.events,
            "physical": self.physical,
            "charge": self.charge,
            "attempts": self.attempts,
            "observations": self.observations,
            "synthetic_root": self.synthetic_root,
            "synthetic_calls": self.synthetic_calls,
            "cleanup_errors": self.cleanup_errors,
            "source_outcomes": self.source_outcomes,
            "captures": self.captures,
            "root_identity": self.root_identity,
            "warning_count": self.warning_count,
            "selected_fd_peak": self.selected_fd_peak,
            "finalizers_drained": all(not getattr(f, "alive") for f in self.finalizers),
        }

    def check_metadata(self, *, cleanup: bool = False) -> None:
        if (
            len(self.artifacts) > 32
            or len(self.lifetime_dirs) > 48
            or len(self.events) > 192
            or len(self.fds) > 12
            or len(policy.canonical(self.failure_snapshot()))
            + (
                0
                if cleanup and (self.cleanup_phase or self.first_fault is not None)
                else 4096
            )
            > policy.META
        ):
            self.fail(adapter.PacketError("pre-I/O metadata/close reserve domain"))

    def failure_snapshot(
        self, pending: tuple[str, bytes] | None = None
    ) -> dict[str, object]:
        """Bind complete owned raw files, never a second escaped-text payload."""
        snapshot = self.metadata()
        captures: dict[str, dict[str, object]] = {}
        outputs: dict[str, object] = {}
        for name, item in self.captures.items():
            raw = b"".join(self.buffers[name])
            projected = dict(item)
            if pending is not None and pending[0] == name:
                raw += pending[1]
                projected["bytes"] = len(raw)
                projected["parts"] = [
                    *cast(list[int], item["parts"]),
                    len(pending[1]),
                ]
            accepted = cast(int, item.get("accepted_bytes", len(raw)))
            returned = cast(int, item.get("returned", 0))
            if pending is not None:
                # The prospective failure snapshot assumes all already-admitted
                # files complete. Actual short/error returns remain explicit.
                returned = len(raw)
                projected.update(
                    returned=returned, sha256=writer.digest(raw), completed=True
                )
            captures[name] = projected
            outputs[name] = {
                "name": name,
                "role": item["role"],
                "requested": {"bytes": len(raw), "sha256": writer.digest(raw)},
                "native": {
                    "bytes": returned,
                    "sha256": writer.digest(raw[:returned]),
                    "completed": projected["completed"],
                },
                "source_accepted": {
                    "bytes": accepted,
                    "sha256": writer.digest(raw[:accepted]),
                },
            }
        snapshot["captures"] = captures
        snapshot["failure"] = {
            "first": str(self.first_fault),
            "outputs": outputs,
        }
        return snapshot

    def headroom(self) -> int:
        dirs = sum(
            n.startswith(("candidates/", "pytest-base/", "controls/"))
            for n in self.directories
        )
        files = sum(
            bool(a["exists"])
            and n.startswith(("candidates/", "pytest-base/", "controls/"))
            for n, a in self.artifacts.items()
        )
        return 9 * dirs + 2 * files + 2 * len(self.capture_fds) + len(self.fds) + 8

    def admit_fd(self) -> None:
        peak = 4 + len(self.fds) + 1
        if peak > 16:
            self.fail(
                adapter.PacketError(
                    "sixteen selected owner FDs including fixed control/transient slots"
                )
            )
        self.selected_fd_peak = max(self.selected_fd_peak, peak)

    def tick(self, *, cleanup: bool = False, cost: int = 1) -> None:
        self.guard(cleanup=cleanup)
        reserve = (
            0
            if cleanup and (self.cleanup_phase or self.first_fault is not None)
            else self.headroom()
        )
        if self.attempts + cost + reserve > 512 or len(self.events) + reserve + 1 > 192:
            self.fail(adapter.PacketError("finite operation/event/cleanup reserve"))
        self.attempts += cost

    def event(
        self,
        op: str,
        name: str,
        action: Callable[[], object],
        *,
        args: object = None,
        cleanup: bool = False,
        recoverable: bool = False,
        frame: Frame | None = None,
    ) -> object:
        self.tick(cleanup=cleanup)
        value: dict[str, object] = {
            "op": op,
            "path": name,
            "args": args,
            "ordinal": self.attempts,
            "result": None,
            "error": "!" * 1024,
        }
        if frame is not None:
            value["frame"] = list((frame["family"], frame["variant"], frame["seq"]))
        self.events.append(value)
        fault = None
        try:
            self.check_metadata(cleanup=cleanup)
            value["error"] = None
            fault = self.faults.pop(op, None)
            if fault is not None and fault[0] != "short":
                value["injected"] = True
                value["control"] = list(fault)
                classes = {
                    "permission": PermissionError,
                    "collision": FileExistsError,
                    "missing": FileNotFoundError,
                }
                numbers = {
                    "permission": errno.EACCES,
                    "collision": errno.EEXIST,
                    "missing": errno.ENOENT,
                }
                error = classes.get(fault[0], OSError)(
                    numbers.get(fault[0], errno.EIO), "injected " + op
                )
                if not fault[1]:
                    self.first_fault = self.first_fault or error
                    self.packet.flags |= 1
                raise error
            if fault is not None:
                value["short_control"] = True
                value["injected"] = True
                value["control"] = list(fault)
            result = action()
            value["result"] = (
                result
                if isinstance(result, (str, int, bool, list, dict, type(None)))
                else "native-object"
            )
            return result
        except BaseException as error:
            text = str(error)
            value["error"] = {"type": type(error).__name__, "text": text}
            if len(text.encode()) > 1024:
                self.first_fault = self.first_fault or error
                self.packet.flags |= 1
                raise
            declared = (
                value.get("injected") is True and fault is not None and fault[1]
            ) or (
                recoverable
                and (
                    isinstance(error, FileExistsError)
                    and op in {"mkdir", "open"}
                    or isinstance(error, FileNotFoundError)
                    and op in {"unlink", "rmdir"}
                    or isinstance(error, PermissionError)
                    and name in self.permission_controls
                )
            )
            value["recoverable"] = declared
            if not declared:
                self.first_fault = self.first_fault or error
                self.packet.flags |= 1
                if cleanup:
                    self.cleanup_errors.append(str(error))
            raise

    def observe(
        self,
        kind: str,
        name: str,
        action: Callable[[], os.stat_result],
        *,
        token: int | None = None,
    ) -> os.stat_result:
        self.tick(cleanup=True)
        key = next(
            (
                k
                for k, v in self.observations.items()
                if (v["kind"], v["path"], v["generation"], v.get("token"))
                == (kind, name, self.generation.get(name, 0), token)
            ),
            str(len(self.observations)),
        )
        item = self.observations.setdefault(
            key,
            {
                "kind": kind,
                "path": name,
                "generation": self.generation.get(name, 0),
                "count": 0,
                "first": self.attempts,
                "last": self.attempts,
                "result": None,
            },
        )
        if token is not None:
            item["token"] = token
        item["count"] = cast(int, item["count"]) + 1
        cast(list[int], item.setdefault("ordinals", [])).append(self.attempts)
        item["last"] = self.attempts
        self.check_metadata()
        try:
            info = action()
            result = [
                info.st_dev,
                info.st_ino,
                info.st_mode,
                None if stat.S_ISDIR(info.st_mode) else info.st_size,
                getattr(info, "st_flags", 0),
            ]
            if item["result"] not in (None, result):
                self.fail(
                    adapter.PacketError(
                        "native observation identity changed without owned action"
                    )
                )
            item["result"] = result
            return info
        except FileNotFoundError as error:
            item["error"] = {"type": "FileNotFoundError", "text": str(error)}
            self.check_metadata()
            raise
        except BaseException as error:
            item["error"] = {"type": type(error).__name__, "text": str(error)}
            self.fail(error)

    def bump(self, name: str) -> None:
        self.generation[name] = self.generation.get(name, 0) + 1

    def register(self, name: str, kind: str) -> None:
        if name not in self.artifacts:
            self.artifacts[name] = {"kind": kind, "exists": False}
        elif self.artifacts[name]["kind"] != kind:
            self.fail(adapter.PacketError("immutable native role kind"))
        self.check_metadata()

    def raw(
        self, role: str, name: str, raw: bytes, mode: str, *, physical: bool = True
    ) -> Frame:
        self.guard()
        if type(raw) is not bytes or role not in policy.DOMAINS:
            self.fail(adapter.PacketError("exact raw owned domain"))
        family, variant, _, maximum = policy.DOMAINS[role]
        if len(raw) > maximum:
            self.fail(adapter.PacketError("whole native payload maximum"))
        if role == "synthetic_input":
            if self.synthetic_root is None:
                self.fail(adapter.PacketError("original setup root required"))
            relative = name.removeprefix(self.synthetic_root + "/")
            bound = policy.SYNTHETIC.get(relative)
            if (
                bound is None
                or len(raw) > bound[1]
                or self.synthetic_calls.get(relative, 0) >= bound[0]
            ):
                self.fail(adapter.PacketError("original whole source path/count"))
            self.synthetic_calls[relative] = self.synthetic_calls.get(relative, 0) + 1
        seq = self.packet.next.get((adapter.IDS.index(family) + 1, variant), 0)
        frame: Frame = {
            "family": family,
            "variant": variant,
            "seq": seq,
            "role": role,
            "path": name,
            "mode": mode,
            "requested": len(raw),
        }
        self.register(name, "link" if role == "owned_link" else "file")
        self.frames.append(frame)
        self.check_metadata()
        amount = 0 if name in self.captures else 2 * len(raw) + 11
        if self.charge + amount + 91 > adapter.CAP:
            self.fail(adapter.PacketError("same shared prewrite cap"))
        self.charge += amount
        if physical:
            self.physical += len(raw)
        try:
            self.packet.emit(family, role, raw)
            self.raw_records.append((family, variant, seq, raw))
        except BaseException as error:
            self.fail(error)
        return frame

    def reserve_capture(self, name: str, role: str) -> None:
        self.guard()
        self.admit_fd()
        if name in self.captures or role not in {"stream", "pytest_xml", "warning"}:
            self.fail(adapter.PacketError("unique declared output obligation"))
        family, variant, count, maximum = policy.DOMAINS[role]
        if (
            sum(v["role"] == role for v in self.captures.values()) >= count
            or len(self.fds) >= 12
        ):
            self.fail(adapter.PacketError("pre-admitted output slot count/fd"))
        self.register(name, "file")
        amount = 2 * maximum + 11
        if self.charge + amount + 91 > adapter.CAP:
            self.fail(adapter.PacketError("pre-admitted output whole-cap reservation"))
        self.charge += amount
        self.captures[name] = {
            "role": role,
            "maximum": maximum,
            "reservation": amount,
            "bytes": 0,
            "parts": [],
            "completed": False,
            "packet_key": None,
        }
        self.buffers[name] = []

        def action() -> object:
            fd = os.open(
                self.target(name),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            self.serial += 1
            token = Descriptor(self.epoch, self.serial)
            self.fds[token] = NativeFD(
                fd, name, False, -1, -1, 0, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            )
            info = os.fstat(fd)
            self.fds[token] = NativeFD(
                fd,
                name,
                False,
                info.st_dev,
                info.st_ino,
                info.st_mode,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            )
            self.capture_fds[name] = token
            self.artifacts[name]["exists"] = True
            self.bump(name)
            return {
                "token": token.serial,
                "dev": info.st_dev,
                "ino": info.st_ino,
                "mode": info.st_mode,
                "directory": False,
            }

        self.event("capture_open", name, action, args=[family, variant, maximum])

    def capture(self, name: str, raw: bytes) -> None:
        self.guard(cleanup=True)
        if name not in self.capture_fds or type(raw) is not bytes:
            self.fail(adapter.PacketError("pre-admitted live output buffer"))
        item = self.captures[name]
        if cast(int, item["bytes"]) + len(raw) > cast(int, item["maximum"]):
            self.fail(
                adapter.PacketError(
                    "whole output buffer ceiling before transport write"
                )
            )
        if (
            len(policy.canonical(self.failure_snapshot((name, raw)))) + 4096
            > policy.META
        ):
            self.fail(
                adapter.PacketError("prospective failure output metadata reserve")
            )
        self.buffers[name].append(raw)
        item["bytes"] = cast(int, item["bytes"]) + len(raw)
        cast(list[int], item["parts"]).append(len(raw))
        self.check_metadata()

    def finalize_capture(self, name: str) -> None:
        if name not in self.capture_fds:
            return
        raw = b"".join(self.buffers[name])
        item = self.captures[name]
        token = self.capture_fds[name]
        fd = self.fd(token)
        frame = None
        if self.first_fault is None:
            frame = self.raw(cast(str, item["role"]), name, raw, "w", physical=False)
            item["packet_key"] = [frame["family"], frame["variant"], frame["seq"]]
        self.physical += len(raw)

        def action() -> object:
            returned = os.write(fd.fd, raw)
            self.bump(name)
            item["returned"] = returned
            item["sha256"] = writer.digest(raw)
            if returned != len(raw):
                self.fail(OSError("actual short pre-admitted output write"))
            item["completed"] = True
            return returned

        primary: BaseException | None = None
        try:
            self.event(
                "capture_write",
                name,
                action,
                args=token.serial,
                cleanup=True,
                frame=frame,
            )
        except BaseException as error:
            primary = error
        try:
            self.close(token)
            del self.capture_fds[name]
        except BaseException as error:
            self.cleanup_errors.append(str(error))
            primary = primary or error
        if primary is not None:
            raise primary

    def reserve_outputs(self) -> None:
        for name, role in (
            ("reports/stdout.txt", "stream"),
            ("reports/stderr.txt", "stream"),
            ("reports/result.xml", "pytest_xml"),
        ):
            self.reserve_capture(name, role)

    def role(self, name: str) -> str:
        if self.synthetic_root and name.startswith(self.synthetic_root + "/"):
            return "synthetic_input"
        if name in {"reports/stdout.txt", "reports/stderr.txt"}:
            return "stream"
        if name.startswith("reports/warning-"):
            return "warning"
        if name == "reports/result.xml":
            return "pytest_xml"
        if name.startswith(("candidates/", "pytest-base/", "controls/")):
            return "native_small"
        self.fail(adapter.PacketError("undeclared native output role"))

    def fd(self, token: object) -> NativeFD:
        if (
            not isinstance(token, Descriptor)
            or type(token.serial) is not int
            or token.epoch != self.epoch
            or not any(k is token for k in self.fds)
        ):
            self.fail(adapter.PacketError("opaque live owned descriptor"))
        return self.fds[token]

    def native_arg(
        self, name: str, directory: Descriptor | None
    ) -> tuple[str | Path, dict[str, int]]:
        self.target(name)
        if directory is None:
            return self.target(name), {}
        fd = self.fd(directory)
        if not fd.directory or posixpath.dirname(name) != fd.name:
            self.fail(adapter.PacketError("exact descriptor-relative child"))
        return posixpath.basename(name), {"dir_fd": fd.fd}

    def open(
        self,
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: Descriptor | None = None,
        empty: bool = True,
        frame: Frame | None = None,
    ) -> Descriptor:
        name = self.name(path, dir_fd)
        cleanup_open = not (flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR))
        self.guard(cleanup=cleanup_open)
        self.admit_fd()
        if (
            len(self.fds) >= 12
            or type(flags) is not int
            or flags
            & ~(
                os.O_RDWR
                | os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_TRUNC
                | os.O_NONBLOCK
                | os.O_NOFOLLOW
            )
        ):
            self.fail(adapter.PacketError("finite native open flags/fd"))
        creating = bool(flags & os.O_CREAT)
        if creating and name.startswith("candidates/") and empty:
            self.discovery += 1
            if self.discovery > 32:
                self.fail(adapter.PacketError("finite genuine discovery attempts"))
        if creating and empty:
            frame = self.raw("native_small", name, b"", "create")
        self.target(name, follow=not creating)
        native_arg, native_kw = self.native_arg(name, dir_fd)

        def action() -> object:
            descriptor = os.open(
                native_arg,
                flags | (os.O_NOFOLLOW if creating else 0),
                mode,
                **native_kw,
            )
            self.serial += 1
            token = Descriptor(self.epoch, self.serial)
            self.fds[token] = NativeFD(descriptor, name, False, -1, -1, 0, flags)
            self.events[-1]["opened_token"] = token.serial
            if creating:
                self.artifacts[name]["exists"] = True
                self.bump(name)
            if self.faults.pop("open_fstat", None) == ("storage", False):
                self.events[-1]["fstat_control"] = (
                    "injected before actual fstat; actual open already succeeded"
                )
                raise OSError(errno.EIO, "injected open_fstat")
            info = os.fstat(descriptor)
            self.fds[token] = NativeFD(
                descriptor,
                name,
                stat.S_ISDIR(info.st_mode),
                info.st_dev,
                info.st_ino,
                info.st_mode,
                flags,
            )
            return {
                "token": self.serial,
                "dev": info.st_dev,
                "ino": info.st_ino,
                "mode": info.st_mode,
                "directory": stat.S_ISDIR(info.st_mode),
            }

        self.event(
            "open",
            name,
            action,
            args=[flags, mode],
            cleanup=cleanup_open,
            recoverable=creating and empty,
            frame=frame,
        )
        return next(token for token in self.fds if token.serial == self.serial)

    def write(self, token: object, raw: bytes, *, frame: Frame | None = None) -> int:
        fd = self.fd(token)
        if fd.directory or type(raw) is not bytes:
            self.fail(adapter.PacketError("exact file write capability"))
        if frame is None:
            frame = self.raw("native_small", fd.name, raw, "a")
        short = self.faults.get("write") == ("short", False)
        native_raw = raw[:1] if short else raw

        def action() -> object:
            self.events[-1]["native_requested"] = len(native_raw)
            return os.write(fd.fd, native_raw)

        returned = cast(
            int,
            self.event(
                "write",
                fd.name,
                action,
                args=cast(Descriptor, token).serial,
                frame=frame,
            ),
        )
        self.bump(fd.name)
        if returned != len(raw):
            error = (
                OSError(
                    "injected native-input truncation: source="
                    + str(len(raw))
                    + " native="
                    + str(len(native_raw))
                    + " returned="
                    + str(returned)
                )
                if short
                else OSError("actual short native write")
            )
            self.first_fault = self.first_fault or error
            self.packet.flags |= 1
        return returned

    def close(self, token: object) -> None:
        fd = self.fd(token)
        self.event(
            "close",
            fd.name,
            lambda: os.close(fd.fd),
            args=cast(Descriptor, token).serial,
            cleanup=True,
        )
        del self.fds[cast(Descriptor, token)]

    def whole(self, name: str, raw: bytes, *, role: str | None = None) -> int:
        self.guard()
        self.name(self.virtual + "/" + name)
        self.admit_fd()
        if len(self.fds) >= 12:
            self.fail(
                adapter.PacketError(
                    "whole transaction descriptor plus four fixed control FDs"
                )
            )
        frame = self.raw(role or self.role(name), name, raw, "w")
        steps: dict[str, object] = {}

        def action() -> object:
            fd = os.open(
                self.target(name),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            self.serial += 1
            token = Descriptor(self.epoch, self.serial)
            self.fds[token] = NativeFD(
                fd, name, False, -1, -1, 0, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            )
            steps["descriptor"] = token.serial
            primary: BaseException | None = None
            returned = 0
            phase = "fstat"
            self.artifacts[name]["exists"] = True
            try:
                info = os.fstat(fd)
                steps["opened"] = [info.st_dev, info.st_ino, info.st_mode]
                self.fds[token] = NativeFD(
                    fd,
                    name,
                    False,
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                )
                phase = "write"
                steps["requested"] = len(raw)
                returned = os.write(fd, raw)
                steps["written"] = returned
                self.bump(name)
                if returned != len(raw):
                    raise OSError("actual short whole native write")
            except BaseException as error:
                primary = error
                steps["primary_error"] = {
                    "phase": phase,
                    "type": type(error).__name__,
                    "text": str(error),
                }
                self.first_fault = self.first_fault or error
                self.packet.flags |= 1
            try:
                os.close(fd)
                steps["closed"] = True
                del self.fds[token]
            except BaseException as error:
                steps["close_error"] = {
                    "type": type(error).__name__,
                    "text": str(error),
                }
                self.cleanup_errors.append(str(error))
                primary = primary or error
            if primary is not None:
                raise primary
            return returned

        return cast(int, self.event("whole", name, action, args=steps, frame=frame))

    def mkdir(self, path: object, mode: int = 0o777, *, exist_ok: bool = False) -> None:
        name = self.name(path)
        self.guard()
        if (
            type(mode) is not int
            or mode not in {0o700, 0o777}
            or type(exist_ok) is not bool
        ):
            self.fail(adapter.PacketError("exact directory mode/exist_ok domain"))
        if name not in self.lifetime_dirs:
            self.lifetime_dirs.add(name)
        self.check_metadata()

        def action() -> object:
            try:
                self.target(name).mkdir(mode=mode)
            except FileExistsError:
                if not exist_ok:
                    raise
            self.directories.add(name)
            self.bump(name)
            info = self.target(name).stat()
            return [
                info.st_dev,
                info.st_ino,
                info.st_mode,
                getattr(info, "st_flags", 0),
            ]

        self.event("mkdir", name, action, args=[mode, exist_ok], recoverable=True)
        if (
            posixpath.basename(name).startswith("codex-tmp-r21-controls-")
            and self.target(name).is_dir()
        ):
            self.synthetic_root = name

    def unlink(self, path: object, *, dir_fd: Descriptor | None = None) -> None:
        name = self.name(path, dir_fd)
        native_arg, native_kw = self.native_arg(name, dir_fd)

        def action() -> object:
            os.unlink(native_arg, **native_kw)
            if name in self.artifacts:
                self.artifacts[name]["exists"] = False
            self.bump(name)
            return None

        self.event("unlink", name, action, cleanup=True, recoverable=True)

    def rmdir(self, path: object, *, dir_fd: Descriptor | None = None) -> None:
        name = self.name(path, dir_fd)
        if not name or name not in self.lifetime_dirs:
            self.fail(adapter.PacketError("closed directory removal"))
        native_arg, native_kw = self.native_arg(name, dir_fd)

        def action() -> object:
            os.rmdir(native_arg, **native_kw)
            self.directories.discard(name)
            self.bump(name)
            return None

        self.event("rmdir", name, action, cleanup=True, recoverable=True)

    def change(
        self, op: str, path: object, value: int, *, follow_symlinks: bool = True
    ) -> None:
        name = self.name(path)
        native_mode = self.info(path, follow_symlinks=follow_symlinks).st_mode
        if type(value) is not int or type(follow_symlinks) is not bool:
            self.fail(adapter.PacketError("exact permission/follow scalar domain"))
        if op not in {"chmod", "chflags"} or value not in {
            0,
            0o400,
            0o500,
            0o600,
            0o700,
            native_mode | stat.S_IRUSR | stat.S_IWUSR,
        }:
            self.fail(adapter.PacketError("closed permission control"))
        function = os.chmod if op == "chmod" else os.chflags

        def action() -> object:
            function(self.target(name), value, follow_symlinks=follow_symlinks)
            self.bump(name)
            info = os.stat(self.target(name), follow_symlinks=follow_symlinks)
            if op == "chmod" and stat.S_IMODE(info.st_mode) in {0o400, 0o500}:
                self.permission_controls.add(name)
            return [
                info.st_dev,
                info.st_ino,
                info.st_mode,
                getattr(info, "st_flags", 0),
            ]

        self.event(op, name, action, args=[value, follow_symlinks], cleanup=True)

    def symlink(self, path: object, target: object) -> None:
        name, destination = self.name(path), self.name(target)
        if (
            not name.startswith("pytest-base/")
            or not name.endswith("current")
            or destination not in self.lifetime_dirs
        ):
            self.fail(adapter.PacketError("only owned pytest current links"))
        relative = posixpath.relpath(destination, posixpath.dirname(name))
        frame = self.raw("owned_link", name, relative.encode(), "symlink")
        self.artifacts[name]["target"] = relative

        def action() -> object:
            os.symlink(relative, self.target(name))
            self.artifacts[name]["exists"] = True
            self.bump(name)
            info = self.target(name).lstat()
            return {
                "logical_target": str(target),
                "native_target": relative,
                "identity": [
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                    getattr(info, "st_flags", 0),
                ],
            }

        self.event("symlink", name, action, args=str(target), frame=frame)

    def info(
        self,
        path: object,
        *,
        dir_fd: Descriptor | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        name = self.name(path, dir_fd)
        native_arg, native_kw = self.native_arg(name, dir_fd)
        return self.observe(
            "stat" if follow_symlinks else "lstat",
            name,
            lambda: os.stat(native_arg, follow_symlinks=follow_symlinks, **native_kw),
        )

    def fstat(self, token: object) -> os.stat_result:
        fd = self.fd(token)
        info = self.observe(
            "fstat",
            fd.name,
            lambda: os.fstat(fd.fd),
            token=cast(Descriptor, token).serial,
        )
        if fd.dev != -1 and (info.st_dev, info.st_ino) != (fd.dev, fd.ino):
            self.fail(adapter.PacketError("owned descriptor inode changed"))
        return info

    def scandir(self, path: object) -> Scan:
        self.admit_fd()
        if len(self.fds) >= 12:
            self.fail(
                adapter.PacketError("owned scandir transient plus four fixed FDs")
            )
        native_arg: int | Path
        if isinstance(path, Descriptor):
            fd = self.fd(path)
            name, native_arg = fd.name, fd.fd
        else:
            name = self.name(path)
            native_arg = self.target(name)

        def action() -> object:
            with os.scandir(native_arg) as entries:
                values = list(entries)
            if len(values) > 32:
                self.fail(adapter.PacketError("finite owned scandir"))
            known = self.lifetime_dirs | set(self.artifacts)
            if any(posixpath.join(name, e.name) not in known for e in values):
                self.fail(adapter.PacketError("unowned native member"))
            return values

        entries = cast(
            list[os.DirEntry[str]], self.event("scandir", name, action, cleanup=True)
        )
        self.events[-1]["result"] = [e.name for e in entries]
        return Scan([Entry(self, name, e) for e in entries])

    def audit(self, event: str, *args: object) -> None:
        if event not in {"tempfile.mkdtemp", "shutil.rmtree"}:
            self.fail(adapter.PacketError("closed genuine audit code point"))
        if event == "tempfile.mkdtemp":
            self.collisions += 1
            if self.collisions > 32:
                self.fail(
                    adapter.PacketError("finite genuine mkdir/collision attempts")
                )
        self.event(
            "audit",
            self.name(args[0]),
            lambda: None,
            args=event,
            cleanup=event == "shutil.rmtree",
        )

    def warning(
        self, message: object, category: object = UserWarning, **kwargs: object
    ) -> None:
        text = str(message)
        if self.warning_count >= 4:
            self.fail(
                adapter.PacketError("four whole nominal/terminal callback messages")
            )
        self.warning_count += 1
        self.event(
            "warning",
            "",
            lambda: None,
            args=[getattr(category, "__name__", str(category)), text],
            cleanup=True,
        )
        if len(text.encode()) > 1024:
            self.fail(
                ValueError(
                    "whole warning text ceiling; retained error event, no truncation"
                )
            )
        if self.first_fault is None:
            self.whole(
                "reports/warning-"
                + str(sum(f["role"] == "warning" for f in self.frames))
                + ".txt",
                text.encode(),
                role="warning",
            )
        cast(Callable[..., None], warnings.warn)(message, category, **kwargs)

    def os_namespace(self) -> SimpleNamespace:
        path = SimpleNamespace(
            **{
                n: getattr(posixpath, n)
                for n in (
                    "join",
                    "dirname",
                    "basename",
                    "normpath",
                    "normcase",
                    "isabs",
                    "splitdrive",
                    "samestat",
                )
            }
        )
        path.join = lambda *parts: posixpath.join(
            *(str(self.path(p)) if isinstance(p, CapPath) else p for p in parts)
        )
        path.abspath = lambda p: str(self.path(p))
        path.isdir = lambda p: self.path(p).is_dir()
        path.islink = lambda p: self.path(p).is_symlink()
        path.exists = lambda p: self.path(p).exists()
        path.isjunction = lambda p: False
        path.expanduser = lambda p: p
        path.expandvars = lambda p: p

        def chmod(p: object, m: int, *, follow_symlinks: bool = True) -> None:
            self.change("chmod", p, m, follow_symlinks=follow_symlinks)

        def chflags(p: object, m: int, *, follow_symlinks: bool = True) -> None:
            self.change("chflags", p, m, follow_symlinks=follow_symlinks)

        result = Namespace(
            self,
            **{
                n: getattr(os, n)
                for n in (
                    "name",
                    "O_RDONLY",
                    "O_RDWR",
                    "O_WRONLY",
                    "O_CREAT",
                    "O_EXCL",
                    "O_TRUNC",
                    "O_NONBLOCK",
                    "O_NOFOLLOW",
                    "getpid",
                    "fsencode",
                    "fsdecode",
                    "PathLike",
                    "sep",
                    "altsep",
                    "curdir",
                    "pardir",
                )
            },
        )
        result.__dict__.update(
            path=path,
            open=self.open,
            write=self.write,
            close=self.close,
            mkdir=self.mkdir,
            unlink=self.unlink,
            remove=self.unlink,
            rmdir=self.rmdir,
            lstat=lambda p, **k: self.info(p, follow_symlinks=False, **k),
            stat=self.info,
            fstat=self.fstat,
            scandir=self.scandir,
            chmod=chmod,
            chflags=chflags,
            getcwd=lambda: self.virtual + "/candidates/cwd",
            getenv=lambda key: self.virtual + "/candidates/TMPDIR"
            if key == "TMPDIR"
            else None,
            environ={"TMPDIR": self.virtual + "/candidates/TMPDIR"},
        )
        result.supports_follow_symlinks = {result.stat, chmod, chflags}
        result.supports_dir_fd = {result.open, result.stat, result.unlink, result.rmdir}
        result.supports_fd = {result.scandir}
        return result

    def prepare(self) -> None:
        for name in (
            "reports",
            "candidates",
            "candidates/TMPDIR",
            "candidates/tmp",
            "candidates/var-tmp",
            "candidates/usr-tmp",
            "candidates/cwd",
            "controls",
            "pytest-base",
        ):
            self.mkdir(CapPath(self, name), 0o700)

    def drain(self) -> None:
        for name in list(self.capture_fds):
            try:
                self.finalize_capture(name)
            except BaseException as error:
                self.cleanup_errors.append(str(error))
        for token in list(self.fds):
            try:
                self.close(token)
            except BaseException as error:
                self.cleanup_errors.append(str(error))
                self.close(token)
        for finalizer in self.finalizers:
            if getattr(finalizer, "alive"):
                try:
                    cast(Callable[[], object], finalizer)()
                except BaseException as error:
                    self.cleanup_errors.append(str(error))
                    self.first_fault = self.first_fault or error
                    self.packet.flags |= 1
        self.finalized_objects.clear()

    def finish(self) -> Recovery:
        self.guard()
        if (
            self.fds
            or any(getattr(f, "alive") for f in self.finalizers)
            or policy.guard() != self.source
        ):
            self.fail(adapter.PacketError("joined descriptors/finalizers/source epoch"))
        manifest = self.metadata()
        raw = policy.canonical(manifest)
        self.check_metadata()
        closure: Record = (
            "source_cap_child",
            1,
            0,
            b"BROKER-MANIFEST:" + writer.digest(raw).encode(),
        )
        try:
            expected, live, identities, _ = roles(
                manifest, [*self.raw_records, closure]
            )
            conserve(self.root, expected, live, identities)
        except BaseException as error:
            self.fail(error)
        if self.charge + 91 > adapter.CAP:
            self.fail(adapter.PacketError("closure capacity"))
        if os.write(self.meta_fd, raw) != len(raw):
            self.fail(OSError("short lifecycle metadata write"))
        os.fsync(self.meta_fd)
        os.close(self.meta_fd)
        self.meta_fd = -1
        self.charge += 91
        self.packet.emit(
            "source_cap_child",
            "closure",
            b"BROKER-MANIFEST:" + writer.digest(raw).encode(),
        )
        for family in adapter.IDS:
            self.packet.close_family(family)
        self.packet.finish()
        self.closed = True
        return recover(self.root)

    def abandon(self) -> None:
        primary: BaseException | None = None
        try:
            self.drain()
            if self.meta_fd != -1:
                raw = policy.canonical(self.failure_snapshot())
                if len(raw) > policy.META:
                    self.fail(adapter.PacketError("failure metadata whole ceiling"))
                if os.write(self.meta_fd, raw) != len(raw):
                    self.fail(OSError("short failure metadata native write"))
        except BaseException as error:
            primary = error
            self.first_fault = self.first_fault or error
            self.cleanup_errors.append(str(error))
        finally:
            try:
                if self.meta_fd != -1:
                    try:
                        os.close(self.meta_fd)
                    finally:
                        self.meta_fd = -1
            except BaseException as error:
                primary = primary or error
                self.cleanup_errors.append(str(error))
            finally:
                try:
                    self.packet.abandon()
                finally:
                    self.closed = True
        if primary is not None:
            raise primary


class Entry:
    def __init__(self, owner: Owner, parent: str, entry: os.DirEntry[str]) -> None:
        self.owner, self.entry = owner, entry
        self.name = entry.name
        self.path = owner.virtual + "/" + posixpath.join(parent, entry.name)

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        actual = self.entry.is_dir(follow_symlinks=follow_symlinks)
        if actual != stat.S_ISDIR(self.stat(follow_symlinks=follow_symlinks).st_mode):
            self.owner.fail(
                adapter.PacketError("actual DirEntry predicate/stat conservation")
            )
        return actual

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        name = self.owner.name(self.path)
        self.owner.target(name, follow=follow_symlinks)
        return self.owner.observe(
            "entry_stat", name, lambda: self.entry.stat(follow_symlinks=follow_symlinks)
        )


class Scan:
    def __init__(self, entries: list[Entry]) -> None:
        self.entries = entries

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries)

    def __enter__(self) -> Scan:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class CapPath:
    def __init__(self, owner: Owner, name: str) -> None:
        self.owner, self.name_value = (
            owner,
            owner.name(owner.virtual + ("/" + name if name else "")),
        )

    def __str__(self) -> str:
        return self.owner.virtual + ("/" + self.name_value if self.name_value else "")

    def __fspath__(self) -> NoReturn:
        self.owner.fail(TypeError("no native pathname export"))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, CapPath)
            and self.owner is other.owner
            and self.name_value == other.name_value
        )

    def __truediv__(self, child: str) -> CapPath:
        if type(child) is not str or child.startswith("/"):
            self.owner.fail(adapter.PacketError("closed relative child"))
        name = posixpath.normpath(posixpath.join(self.name_value, child))
        return self.owner.path(self.owner.virtual + "/" + name)

    def joinpath(self, child: str) -> CapPath:
        return self / child

    @property
    def parent(self) -> CapPath:
        return CapPath(self.owner, posixpath.dirname(self.name_value))

    @property
    def parents(self) -> tuple[CapPath, ...]:
        values: list[CapPath] = []
        parent = self.parent
        while parent.name_value:
            values.append(parent)
            parent = parent.parent
        return tuple(values)

    @property
    def name(self) -> str:
        return posixpath.basename(self.name_value)

    def with_name(self, name: str) -> CapPath:
        return self.parent / name

    def resolve(self, strict: bool = False) -> CapPath:
        if self.is_symlink():
            entry = self.owner.artifacts[self.name_value]
            name = posixpath.normpath(
                posixpath.join(
                    posixpath.dirname(self.name_value), cast(str, entry["target"])
                )
            )
            result = CapPath(self.owner, name)
        else:
            result = self
        if strict and not result.exists():
            raise FileNotFoundError(str(result))
        return result

    def exists(self) -> bool:
        try:
            self.owner.info(self)
        except FileNotFoundError:
            return False
        return True

    def is_dir(self) -> bool:
        try:
            return stat.S_ISDIR(self.owner.info(self).st_mode)
        except FileNotFoundError:
            return False

    def is_file(self) -> bool:
        try:
            return stat.S_ISREG(self.owner.info(self).st_mode)
        except FileNotFoundError:
            return False

    def is_symlink(self) -> bool:
        try:
            return stat.S_ISLNK(self.owner.info(self, follow_symlinks=False).st_mode)
        except FileNotFoundError:
            return False

    def stat(self) -> os.stat_result:
        return self.owner.info(self)

    def mkdir(
        self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if parents:
            for parent in reversed(self.parents):
                if not parent.exists():
                    parent.mkdir(mode=mode, exist_ok=True)
        self.owner.mkdir(self, mode, exist_ok=exist_ok)

    def unlink(self, missing_ok: bool = False) -> None:
        if missing_ok and not self.exists() and not self.is_symlink():
            return
        self.owner.unlink(self)

    def rmdir(self) -> None:
        self.owner.rmdir(self)

    def symlink_to(self, target: object) -> None:
        self.owner.symlink(self, target)

    def iterdir(self) -> Iterator[CapPath]:
        return iter([self / e.name for e in self.owner.scandir(self)])

    def read_bytes(self) -> bytes:
        self.owner.guard()
        self.owner.admit_fd()
        if len(self.owner.fds) >= 12:
            self.owner.fail(
                adapter.PacketError("owned bounded-read transient plus four fixed FDs")
            )
        if self.name_value not in self.owner.artifacts:
            self.owner.fail(adapter.PacketError("only previously owned artifact reads"))
        info = self.owner.info(self)
        target = self.owner.target(self.name_value, follow=True)
        if not target.exists():
            raise FileNotFoundError(str(self))
        item = next(
            v
            for v in self.owner.observations.values()
            if v["path"] == self.name_value
            and v["kind"] == "stat"
            and v["generation"] == self.owner.generation.get(self.name_value, 0)
        )
        reads = cast(list[list[int]], item.setdefault("reads", []))
        reads.append([self.owner.attempts, info.st_size, len(self.owner.fds)])
        self.owner.check_metadata()
        try:
            if self.owner.faults.get("source_read") == ("storage", False):
                self.owner.event(
                    "source_read",
                    self.name_value,
                    lambda: None,
                    args="injected before native bounded-read transaction",
                )
            raw = cast(bytes, writer.bounded_read(target, info.st_size))
            if len(raw) != info.st_size:
                self.owner.fail(
                    adapter.PacketError("bounded source read/observed actual size")
                )
            return raw
        except BaseException as error:
            self.owner.fail(error)

    def write_bytes(self, raw: bytes) -> int:
        return self.owner.whole(self.name_value, raw)

    def write_text(self, text: str, encoding: str = "utf-8") -> int:
        if type(text) is not str or encoding != "utf-8":
            self.owner.fail(TypeError("whole UTF8 source input"))
        self.write_bytes(text.encode())
        return len(text)


def relative(value: object) -> str:
    if type(value) is not str:
        raise adapter.PacketError("exact relative native name")
    name = value
    if (
        name.startswith("/")
        or ".." in name.split("/")
        or posixpath.normpath(name or ".") != (name or ".")
        or len(name.encode()) > 256
        or len(name.split("/")) > 8
    ):
        raise adapter.PacketError("canonical recovery native name")
    return name


def roles(
    manifest: dict[str, object], records: list[Record]
) -> tuple[dict[str, bytes], set[str], dict[str, list[int]], int]:
    frames = cast(list[Frame], manifest["frames"])
    events = cast(list[dict[str, object]], manifest["events"])
    observations = cast(dict[str, dict[str, object]], manifest["observations"])
    artifacts = cast(dict[str, dict[str, object]], manifest["artifacts"])
    captures = cast(dict[str, dict[str, object]], manifest["captures"])
    raw_lifetime = cast(list[str], manifest["lifetime_dirs"])
    raw_live = cast(list[str], manifest["directories"])
    lifetime = {relative(n) for n in raw_lifetime}
    if len(lifetime) != len(raw_lifetime) or len(set(raw_live)) != len(raw_live):
        raise adapter.PacketError("no duplicate directory history/list members")
    if (
        len(frames) > 70
        or len(events) > 192
        or len(artifacts) > 32
        or len(lifetime) > 48
        or manifest.get("finalizers_drained") is not True
        or manifest.get("cleanup_errors") != []
    ):
        raise adapter.PacketError("finite joined lifecycle domains")
    payloads = {(f, v, s): p for f, v, s, p in records[:-1]}
    keys = [(f["family"], f["variant"], f["seq"]) for f in frames]
    if (
        len(payloads) != len(records) - 1
        or len(set(keys)) != len(keys)
        or set(keys) != set(payloads)
    ):
        raise adapter.PacketError("every raw record exactly one owner")
    synthetic = manifest.get("synthetic_root")
    if synthetic is not None and (
        relative(synthetic) not in lifetime
        or not cast(str, synthetic).startswith("candidates/")
        or not posixpath.basename(cast(str, synthetic)).startswith(
            "codex-tmp-r21-controls-20261009-"
        )
    ):
        raise adapter.PacketError("genuine setup root identity")
    counts: dict[str, int] = {}
    calls: dict[str, int] = {}
    for frame, record_key in zip(frames, keys, strict=True):
        for scalar in ("variant", "seq", "requested"):
            writer.integer(frame[scalar])
        name, role, mode = relative(frame["path"]), frame["role"], frame["mode"]
        domain = policy.DOMAINS.get(role)
        if (
            domain is None
            or role == "closure"
            or domain[:2] != record_key[:2]
            or frame["requested"] != len(payloads[record_key])
            or len(payloads[record_key]) > domain[3]
        ):
            raise adapter.PacketError("typed raw role, wire subtype and size")
        counts[role] = counts.get(role, 0) + 1
        if counts[role] > domain[2] or frame["seq"] < 0 or frame["seq"] >= domain[2]:
            raise adapter.PacketError("semantic role sequence/count")
        if role == "synthetic_input":
            if (
                synthetic is None
                or not name.startswith(cast(str, synthetic) + "/")
                or mode != "w"
            ):
                raise adapter.PacketError("synthetic source root/mode")
            child = name[len(cast(str, synthetic)) + 1 :]
            bound = policy.SYNTHETIC.get(child)
            calls[child] = calls.get(child, 0) + 1
            if (
                bound is None
                or calls[child] > bound[0]
                or len(payloads[record_key]) > bound[1]
            ):
                raise adapter.PacketError("closed nine-path/count/whole envelope")
        elif role == "native_small":
            if not name.startswith(
                ("candidates/", "pytest-base/", "controls/")
            ) or mode not in {"create", "a", "w"}:
                raise adapter.PacketError("closed native small route/mode")
        elif role == "owned_link":
            if (
                not name.startswith("pytest-base/")
                or not name.endswith("current")
                or mode != "symlink"
            ):
                raise adapter.PacketError("only pytest current symlink role")
        elif role == "stream":
            if name not in {"reports/stdout.txt", "reports/stderr.txt"} or mode != "w":
                raise adapter.PacketError("exact whole stream role")
        elif role == "pytest_xml":
            if name != "reports/result.xml" or mode != "w":
                raise adapter.PacketError("exact genuine XML role")
        elif role == "warning":
            if not name.startswith("reports/warning-") or mode != "w":
                raise adapter.PacketError("whole warning role")
    if calls != manifest.get("synthetic_calls"):
        raise adapter.PacketError(
            "synthetic per-path calls independently reconstructed"
        )
    expected: dict[str, bytes] = {}
    live = {""}
    identity = {"": cast(list[int], manifest["root_identity"])}
    generations: dict[str, int] = {}
    snapshots: dict[tuple[str, int], list[int] | None] = {("", 0): identity[""]}
    sizes: dict[tuple[str, int], int | None] = {("", 0): None}
    changes: dict[str, list[int]] = {}
    occupied: set[int] = set()
    descriptors: dict[int, dict[str, object]] = {}
    descriptor_history: dict[int, dict[str, object]] = {}
    retained: set[tuple[str, int, int]] = set()
    permission_controls: set[str] = set()
    attempted_dirs = {""}
    ordinal = 0
    selected_peak = 4
    discovery = collisions = 0
    warning_texts: list[bytes] = []

    def bump(name: str) -> None:
        generations[name] = generations.get(name, 0) + 1
        snapshots[(name, generations[name])] = identity.get(name)
        sizes[(name, generations[name])] = (
            len(expected[name]) if name in expected else None
        )
        changes.setdefault(name, []).append(ordinal)

    def native_identity(
        name: str, value: object, kind: str, *, existing: bool = False
    ) -> list[int]:
        items = cast(list[int], value)
        if (
            len(items) != 4
            or any(type(x) is not int for x in items)
            or items[0] < 0
            or items[1] <= 0
            or not (
                stat.S_ISDIR(items[2])
                if kind == "directory"
                else stat.S_ISLNK(items[2])
                if kind == "link"
                else stat.S_ISREG(items[2])
            )
        ):
            raise adapter.PacketError("actual native identity/type")
        if existing and name in identity and items[:2] != identity[name][:2]:
            raise adapter.PacketError("inode conserved across owned overwrite")
        identity[name] = list(items)
        return items

    native_identity("", manifest["root_identity"], "directory")
    for synthetic_count in cast(
        dict[str, object], manifest["synthetic_calls"]
    ).values():
        writer.integer(synthetic_count)
    writer.integer(manifest["warning_count"])

    for event in events:
        current = writer.integer(event["ordinal"])
        if current <= ordinal or current > 512:
            raise adapter.PacketError("monotonic bounded bridge event ordinal")
        ordinal = current
        occupied.add(current)
        name = relative(event["path"])
        op, result, error = event["op"], event["result"], event["error"]
        if op in {"open", "capture_open", "whole", "scandir"}:
            selected_peak = max(selected_peak, 5 + len(descriptors))
        key = (
            cast(tuple[str, int, int], tuple(cast(list[object], event["frame"])))
            if isinstance(event.get("frame"), list)
            else None
        )
        if key is not None and (
            key not in payloads or frames[keys.index(key)]["path"] != name
        ):
            raise adapter.PacketError("raw event path ownership")
        if op == "mkdir":
            attempted_dirs.add(name)
        if op == "audit" and event["args"] == "tempfile.mkdtemp":
            collisions += 1
        if (
            op == "open"
            and key is not None
            and frames[keys.index(key)]["mode"] == "create"
            and name.startswith("candidates/")
        ):
            discovery += 1
        if discovery > 32 or collisions > 32:
            raise adapter.PacketError("finite genuine discovery/collision replay")
        if error is not None:
            values = writer.mapping(error)
            injected = event.get("injected") is True and event.get("control") in (
                ["permission", True],
                ["collision", True],
                ["missing", True],
            )
            declared = injected or (
                values["type"] == "FileExistsError"
                and op in {"open", "mkdir"}
                or values["type"] == "FileNotFoundError"
                and op in {"unlink", "rmdir"}
                and name not in expected
                and name not in live
                or values["type"] == "PermissionError"
                and name in permission_controls
                and op in {"unlink", "rmdir", "open", "scandir"}
            )
            if (
                event.get("recoverable") is not True
                or not declared
                or len(cast(str, values["text"]).encode()) > 1024
            ):
                raise adapter.PacketError(
                    "only declared source-handler failures may seal"
                )
            if key is not None:
                frame = frames[keys.index(key)]
                if (
                    op != "open"
                    or payloads[key] != b""
                    or frame["mode"] != "create"
                    or key in retained
                ):
                    raise adapter.PacketError(
                        "failed pre-created empty probe input, no mutation"
                    )
                retained.add(key)
            continue
        if op == "mkdir":
            if posixpath.dirname(name) not in live:
                raise adapter.PacketError("mkdir live parent")
            existing = name in live
            if existing and cast(list[object], event["args"])[1] is not True:
                raise adapter.PacketError(
                    "successful repeated mkdir requires exact exist_ok"
                )
            native_identity(name, result, "directory", existing=existing)
            requested = cast(list[object], event["args"])[0]
            if not existing and stat.S_IMODE(identity[name][2]) & ~writer.integer(
                requested
            ):
                raise adapter.PacketError("native requested directory permissions")
            live.add(name)
            bump(name)
        elif op in {"open", "capture_open"}:
            values = writer.mapping(result)
            token = writer.integer(values["token"])
            if (
                token in descriptor_history
                or len(descriptors) >= 12
                or posixpath.dirname(name) not in live
            ):
                raise adapter.PacketError(
                    "owned descriptor generation/parent/control reserve"
                )
            directory = values["directory"] is True
            ident = [
                writer.integer(values["dev"]),
                writer.integer(values["ino"]),
                writer.integer(values["mode"]),
                0,
            ]
            native_identity(
                name,
                ident,
                "directory" if directory else "file",
                existing=name in identity,
            )
            flags = (
                writer.integer(cast(list[object], event["args"])[0])
                if op == "open"
                else os.O_WRONLY | os.O_CREAT | os.O_EXCL
            )
            descriptors[token] = {
                "path": name,
                "identity": ident,
                "directory": directory,
                "flags": flags,
                "start": current,
                "end": None,
            }
            descriptor_history[token] = descriptors[token]
            if flags & os.O_CREAT:
                if flags & os.O_TRUNC or name not in expected:
                    expected[name] = b""
                bump(name)
                if key is not None:
                    if (
                        payloads[key] != b""
                        or frames[keys.index(key)]["mode"] != "create"
                        or key in retained
                    ):
                        raise adapter.PacketError("one native empty-create frame")
                    retained.add(key)
            if op == "capture_open":
                if name not in captures or captures[name]["role"] not in {
                    "stream",
                    "pytest_xml",
                }:
                    raise adapter.PacketError(
                        "only pre-admitted exact output obligation"
                    )
        elif op in {"write", "capture_write"}:
            token = writer.integer(event["args"])
            if (
                key is None
                or token not in descriptors
                or descriptors[token]["path"] != name
                or descriptors[token]["directory"] is not False
                or not cast(int, descriptors[token]["flags"])
                & (os.O_WRONLY | os.O_RDWR)
                or writer.integer(result) != len(payloads[key])
                or (
                    op == "write"
                    and event.get("native_requested") != len(payloads[key])
                )
                or key in retained
                or name not in expected
            ):
                raise adapter.PacketError(
                    "requested/returned raw bytes and exact writable FD/path"
                )
            if (
                identity[name][:2]
                != cast(list[int], descriptors[token]["identity"])[:2]
            ):
                raise adapter.PacketError("write descriptor inode conservation")
            expected[name] += payloads[key]
            bump(name)
            retained.add(key)
            if op == "capture_write" and captures[name].get("packet_key") != list(key):
                raise adapter.PacketError("finalized pre-admitted output frame owner")
        elif op == "whole":
            steps = writer.mapping(event["args"])
            if (
                len(descriptors) >= 12
                or key is None
                or key in retained
                or frames[keys.index(key)]["mode"] != "w"
                or posixpath.dirname(name) not in live
                or steps.get("closed") is not True
                or writer.integer(steps["requested"]) != len(payloads[key])
                or writer.integer(steps["written"]) != len(payloads[key])
                or writer.integer(result) != len(payloads[key])
                or writer.integer(steps["descriptor"]) in descriptor_history
            ):
                raise adapter.PacketError("whole actual open/write/close transaction")
            descriptor_history[writer.integer(steps["descriptor"])] = {
                "path": name,
                "start": current,
                "end": current,
                "identity": steps["opened"],
            }
            opened = cast(list[int], steps["opened"])
            native_identity(name, [*opened, 0], "file", existing=name in identity)
            expected[name] = payloads[key]
            bump(name)
            retained.add(key)
        elif op == "close":
            token = writer.integer(event["args"])
            if token not in descriptors or descriptors[token]["path"] != name:
                raise adapter.PacketError("exact descriptor finally close")
            descriptors[token]["end"] = current
            del descriptors[token]
        elif op == "symlink":
            values = writer.mapping(result)
            target = cast(str, values["native_target"])
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), target)
            )
            if (
                key is None
                or key in retained
                or name in expected
                or posixpath.dirname(name) not in live
                or resolved not in lifetime
                or resolved not in live
                or payloads[key] != target.encode()
                or target != posixpath.relpath(resolved, posixpath.dirname(name))
            ):
                raise adapter.PacketError("raw owned relative target/live destination")
            native_identity(name, values["identity"], "link")
            expected[name] = payloads[key]
            bump(name)
            retained.add(key)
        elif op == "unlink":
            if name not in expected:
                raise adapter.PacketError("unlink live artifact")
            del expected[name]
            del identity[name]
            bump(name)
        elif op == "rmdir":
            if (
                not name
                or name not in live
                or any(n.startswith(name + "/") for n in (*live, *expected))
            ):
                raise adapter.PacketError("rmdir after every child tombstone")
            live.remove(name)
            del identity[name]
            bump(name)
        elif op in {"chmod", "chflags"}:
            if name not in identity:
                raise adapter.PacketError("permission change owned live inode")
            old = identity[name]
            values = cast(list[int], result)
            requested = cast(list[object], event["args"])[0]
            if (
                len(values) != 4
                or values[:2] != old[:2]
                or stat.S_IFMT(values[2]) != stat.S_IFMT(old[2])
                or (
                    op == "chmod"
                    and stat.S_IMODE(values[2])
                    != stat.S_IMODE(writer.integer(requested))
                )
                or (op == "chflags" and (values[3] != requested or values[2] != old[2]))
            ):
                raise adapter.PacketError("actual permission/flags and inode replay")
            identity[name] = list(values)
            if op == "chmod" and stat.S_IMODE(values[2]) in {0o400, 0o500}:
                permission_controls.add(name)
            bump(name)
        elif op == "scandir":
            members = [
                posixpath.basename(n)
                for n in (*live, *expected)
                if n and posixpath.dirname(n) == name
            ]
            if (
                len(descriptors) >= 12
                or name not in live
                or sorted(cast(list[str], result)) != sorted(members)
                or len(members) > 32
            ):
                raise adapter.PacketError("actual owned directory member snapshot")
        elif op == "audit":
            if event["args"] not in {"tempfile.mkdtemp", "shutil.rmtree"}:
                raise adapter.PacketError("closed genuine audit source point")
        elif op == "warning":
            values = cast(list[str], event["args"])
            if name or len(values) != 2 or len(values[1].encode()) > 1024:
                raise adapter.PacketError("whole warning text retained")
            warning_texts.append(values[1].encode())
        else:
            raise adapter.PacketError("unknown native route")
    if (
        descriptors
        or retained != set(payloads)
        or live != {relative(n) for n in cast(list[str], manifest["directories"])}
        or lifetime != attempted_dirs
    ):
        raise adapter.PacketError(
            "joined descriptor/frame/directory lifetime conservation"
        )
    warning_payloads = [
        payloads[k] for k, f in zip(keys, frames, strict=True) if f["role"] == "warning"
    ]
    if (
        len(warning_texts) > 4
        or manifest.get("warning_count") != len(warning_texts)
        or warning_texts != warning_payloads
    ):
        raise adapter.PacketError(
            "every whole nominal warning bound to its typed source event"
        )
    observation_calls = 0
    for observation in observations.values():
        name = relative(observation["path"])
        first, last, count = (
            writer.integer(observation[n]) for n in ("first", "last", "count")
        )
        generation = writer.integer(observation["generation"])
        positions = cast(list[int], observation["ordinals"])
        for position in positions:
            writer.integer(position)
        if (
            count < 1
            or not 0 < first <= last <= writer.integer(manifest["attempts"])
            or observation["kind"] not in {"stat", "lstat", "entry_stat", "fstat"}
        ):
            raise adapter.PacketError("bounded source observation ordinals")
        if (
            len(positions) != count
            or positions != sorted(set(positions))
            or positions[0] != first
            or positions[-1] != last
            or any(
                p in occupied
                or p < 1
                or p > writer.integer(manifest["attempts"])
                or sum(c < p for c in changes.get(name, [])) != generation
                for p in positions
            )
        ):
            raise adapter.PacketError(
                "exact observation ordinal ownership and live generation"
            )
        occupied.update(positions)
        for read in cast(list[list[int]], observation.get("reads", [])):
            for read_scalar in read:
                writer.integer(read_scalar)
            if (
                len(read) != 3
                or read[0] not in positions
                or read[1] != sizes.get((name, generation))
                or read[2] < 0
                or read[2] >= 12
            ):
                raise adapter.PacketError(
                    "bounded native source read/transient descriptor admission"
                )
            active = sum(
                cast(int, d["start"]) < read[0] < cast(int, d["end"])
                for d in descriptor_history.values()
            )
            if active != read[2]:
                raise adapter.PacketError(
                    "source-read transient shares exact live descriptor domain"
                )
            selected_peak = max(selected_peak, 5 + active)
        observation_calls += count
        value = observation["result"]
        state = snapshots.get((name, generation))
        if value is None:
            if (
                writer.mapping(observation["error"])["type"] != "FileNotFoundError"
                or state is not None
            ):
                raise adapter.PacketError("actual known missing observation")
            continue
        values = cast(list[object], value)
        if len(values) != 5:
            raise adapter.PacketError("exact source stat tuple")
        for index in (0, 1, 2, 4):
            writer.integer(values[index])
        expected_size = sizes.get((name, generation))
        if (
            state is not None
            and stat.S_ISLNK(state[2])
            and observation["kind"] == "stat"
        ):
            link = artifacts[name]
            target = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), cast(str, link["target"]))
            )
            candidates = [
                v
                for (p, _), v in snapshots.items()
                if p == target and v is not None and v[:2] == values[:2]
            ]
            state = candidates[0] if candidates else None
            expected_size = None  # Only live owned directory-current links admitted.
        if values[3] is not None:
            writer.integer(values[3])
        if (
            state is None
            or values[:3] != state[:3]
            or values[4] != state[3]
            or values[3] != expected_size
        ):
            raise adapter.PacketError(
                "source stat/DirEntry identity, generation, size and permissions"
            )
        if observation["kind"] == "fstat":
            token = writer.integer(observation["token"])
            if (
                token not in descriptor_history
                or descriptor_history[token]["path"] != name
                or cast(list[int], descriptor_history[token]["identity"])[:2]
                != values[:2]
                or first <= cast(int, descriptor_history[token]["start"])
                or last >= cast(int, descriptor_history[token]["end"])
            ):
                raise adapter.PacketError(
                    "observation bound to live exact native descriptor"
                )
    if (
        writer.integer(manifest["attempts"]) != len(events) + observation_calls
        or occupied != set(range(1, writer.integer(manifest["attempts"]) + 1))
        or writer.integer(manifest["attempts"]) > 512
    ):
        raise adapter.PacketError("every admitted bridge attempt retained")
    if (
        writer.integer(manifest["selected_fd_peak"]) != selected_peak
        or selected_peak > 16
    ):
        raise adapter.PacketError(
            "selected native descriptor admission peak and fixed-four conservation"
        )
    if set(artifacts) != {f["path"] for f in frames} | set(captures):
        raise adapter.PacketError("exact lifetime artifact names")
    reservation = 0
    for name, item in captures.items():
        role = cast(str, item["role"])
        if role not in {"stream", "pytest_xml"} or name not in artifacts:
            raise adapter.PacketError("exact pre-admitted capture role")
        maximum = policy.DOMAINS[role][3]
        key = cast(tuple[str, int, int], tuple(cast(list[object], item["packet_key"])))
        if (
            item["maximum"] != maximum
            or item["reservation"] != 2 * maximum + 11
            or item["completed"] is not True
            or key not in payloads
            or item["bytes"] != len(payloads[key])
            or item["returned"] != len(payloads[key])
            or item["sha256"] != writer.digest(payloads[key])
            or sum(cast(list[int], item["parts"])) != len(payloads[key])
        ):
            raise adapter.PacketError("nonrefunded output obligation/raw conservation")
        reservation += cast(int, item["reservation"])
    for name, item in artifacts.items():
        if (
            item["exists"] != (name in expected)
            or item["kind"] not in {"file", "link"}
            or (
                item["kind"] == "link"
                and name in expected
                and cast(str, item["target"]).encode() != expected[name]
            )
        ):
            raise adapter.PacketError("native file/link existence replay")
    physical = sum(map(len, payloads.values()))
    charge = (
        2
        * sum(
            len(payloads[k])
            for k, f in zip(keys, frames, strict=True)
            if f["path"] not in captures
        )
        + 11 * sum(f["path"] not in captures for f in frames)
        + reservation
        + policy.META
        + adapter.TERMINAL
        + adapter.CONTROLS
        + 91
    )
    if (
        manifest["physical"] != physical
        or writer.integer(manifest["charge"]) + 91 != charge
        or charge > adapter.CAP
    ):
        raise adapter.PacketError("shared no-refund reservation/native/raw accounting")
    return expected, live, identity, charge


def conserve(
    root: Path,
    expected: dict[str, bytes],
    live: set[str],
    identities: dict[str, list[int]],
) -> None:
    native_root = root / "files"
    info = native_root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or [info.st_dev, info.st_ino, info.st_mode, getattr(info, "st_flags", 0)]
        != identities[""]
    ):
        raise adapter.PacketError("owned native root identity before traversal")
    actual_files: set[str] = set()
    actual_dirs = {""}
    for parent, dirs, files in os.walk(native_root, followlinks=False):
        for leaf in [*dirs, *files]:
            path = Path(parent) / leaf
            name = path.relative_to(root / "files").as_posix()
            info = path.lstat()
            identity = [
                info.st_dev,
                info.st_ino,
                info.st_mode,
                getattr(info, "st_flags", 0),
            ]
            if name not in identities or identity != identities[name]:
                raise adapter.PacketError(
                    "final actual inode/permission/flags conservation"
                )
            if stat.S_ISDIR(info.st_mode):
                actual_dirs.add(name)
            elif stat.S_ISLNK(info.st_mode):
                actual_files.add(name)
                if os.readlink(path).encode() != expected.get(name):
                    raise adapter.PacketError("native symlink raw bytes")
            elif stat.S_ISREG(info.st_mode):
                actual_files.add(name)
                if (
                    name not in expected
                    or writer.bounded_read(path, len(expected[name])) != expected[name]
                ):
                    raise adapter.PacketError("native regular file raw bytes")
            else:
                raise adapter.PacketError("nonregular native object")
    info = (root / "files").stat()
    if (
        [info.st_dev, info.st_ino, info.st_mode, getattr(info, "st_flags", 0)]
        != identities[""]
        or actual_files != set(expected)
        or actual_dirs != live
    ):
        raise adapter.PacketError("final missing/extra native objects")


def recover(root: Path) -> Recovery:
    policy.guard()
    root = adapter.safe(root)
    if set(p.name for p in root.iterdir()) != {"files", "packet", "manifest.json"}:
        raise adapter.PacketError("owned lifecycle layout")
    raw = writer.bounded_read(root / "manifest.json", policy.META)
    manifest = writer.mapping(json.loads(raw))
    if (
        policy.canonical(manifest) != raw
        or manifest.get("stage") != "LOCAL_NATIVE_LIFECYCLE"
        or manifest.get("source") != policy.guard()
        or manifest.get("contract_sha256") != writer.digest(policy.contract()[1])
    ):
        raise adapter.PacketError("lifecycle stage/source/contract")
    packet = writer.mapping(
        PACKET_RECOVER(
            root / "packet", policy.wanted(), policy.contract()[1], policy.EPOCH
        )
    )
    records = cast(list[Record], packet["records"])
    if (
        not records
        or records[-1][0:3] != ("source_cap_child", 1, 0)
        or records[-1][3] != b"BROKER-MANIFEST:" + writer.digest(raw).encode()
    ):
        raise adapter.PacketError("owned metadata closure marker")
    expected, live, identities, charge = roles(manifest, records)
    conserve(root, expected, live, identities)
    return {
        "stage": "LOCAL_NATIVE_LIFECYCLE",
        "charge": charge,
        "physical_attempt_bytes": writer.integer(manifest["physical"]),
        "records": records,
        "events": cast(list[dict[str, object]], manifest["events"]),
        "artifacts": cast(dict[str, dict[str, object]], manifest["artifacts"]),
        "actual_capture_admission": "HOLD",
    }
