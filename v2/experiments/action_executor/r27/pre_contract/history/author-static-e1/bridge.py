"""Source-exact synthetic packet diagnostic; mappings never admit original PRE."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import posixpath
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Protocol, cast

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
AREA = ROOT / "v2/experiments/action_executor"
PINS = {
    "r21/test_r21_offline.py": "d48f93fc7f420a26d546fd172f80d5d0a10a00cb8f2bd5b5fb384defce3c1dd4",
    "r21/qualification.py": "a0d233b2d64bc9cfc3a221b36d298f2b8be255969b52b832abf4df53228862ef",
    "r20/env_contract.py": "b347e161a7c3a255c4bb2efeda3eff2bd6df5e0f12f72739d3d204a46418859c",
    "r19/qualification.py": "77df7d23f11daccd49ee755ddea9f49ca0e2fec48907a46f95465761abc48b11",
    "r18/gate.py": "b44cf3781dc5afd307e4908c5801089167413d46dd53f4723012a40ee8d8f4a1",
    "r21/contract.json": "f27bc21a10b041ce369d7e69c500f2950b8b05e6b9f81685bd59dff1fbe3dc7c",
    "r21/run-http-qualification.sh": "4a2de34ec8fd9ea33a036f9770e2a9e40289c30ed164954624d0bff547dc43b1",
    "r19/bounded.py": "dacc9109adb89437817e58d5b537072f0063f1ce001b5151e5abc5c22fd376bb",
    "r21/test_r21_envelope.py": "879414b56aaed8af655dc48c6b40710788bb63e24d1022e18747a5ecef0a7903",
}
Mapping = Literal["natural_diagnostic", "ephemeral_diagnostic"]
Mode = Literal["full", "four", "one"]
FAMILIES = {
    "r21_http_e1/binding.json": "frozen_copies",
    "r21_http_e1/contract.json": "frozen_copies",
    "r21-campaign-launch.json": "launch_review",
    "r21_http_e1/run/samples.json": "final_samples",
    "r21_http_e1/run/samples.jsonl": "journal",
    "r21_http_e1/run/latency-summary.json": "summary_stdout",
    "r21_http_e1/run/r-controls.json": "literal_controls",
    "r21_http_e1/load.owner.json": "owner_process",
    "r21_http_e1/load.process.json": "owner_process",
}


def bounded(path: Path) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size > 262144:
        raise ValueError("bounded regular source")
    with path.open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError("source grew")
    return raw


def guard() -> None:
    for name, expected in PINS.items():
        if hashlib.sha256(bounded(AREA / name)).hexdigest() != expected:
            raise ValueError("source drift before diagnostic: " + name)


class Port(Protocol):
    def check(self) -> None: ...
    def capture_fault(self, error: BaseException) -> None: ...
    def write(self, name: str, family: str, raw: bytes, mode: Literal["w"]) -> int: ...
    def read(self, name: str) -> bytes: ...
    def mkdir(self, name: str, parents: bool = False, exist_ok: bool = False) -> None: ...
    def delete(self, name: str) -> None: ...


@dataclass
class Attempt:
    name: str
    raw: bytes
    family: str
    admitted: bool = False


class LogicalTempPath:
    def __init__(self, session: Session, name: str = "") -> None:
        self.session, self.name = session, name

    def __truediv__(self, child: str) -> LogicalTempPath:
        try:
            self.session.port.check()
            if type(child) is not str or child.startswith("/") or len(child) > 256:
                raise ValueError("closed logical child")
            name = posixpath.normpath(posixpath.join(self.name, child))
            if name == ".." or name.startswith("../"):
                raise ValueError("no namespace escape")
            return LogicalTempPath(self.session, "" if name == "." else name)
        except BaseException as error:
            self.session.port.capture_fault(error)
            raise

    def __fspath__(self) -> str:
        error = TypeError("diagnostic logical path has no native capability")
        self.session.port.capture_fault(error)
        raise error

    def target(self) -> str:
        self.session.port.check()
        return "tmp/control" + ("/" + self.name if self.name else "")

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        if self.name not in {"", "r21_http_e1", "r21_http_e1/run"}:
            error = ValueError("closed original packet directories")
            self.session.port.capture_fault(error)
            raise error
        self.session.port.mkdir(self.target(), parents, exist_ok)

    def write_bytes(self, raw: bytes) -> int:
        try:
            self.session.port.check()
            if type(raw) is not bytes or self.name not in FAMILIES:
                raise ValueError("closed whole packet byte write")
            family = (
                FAMILIES[self.name] if self.session.mapping == "natural_diagnostic" else "ephemeral"
            )
            attempt = Attempt(self.name, raw, family)
            self.session.attempts.append(attempt)
            count = self.session.port.write(self.target(), family, raw, "w")
            attempt.admitted = True
            return count
        except BaseException as error:
            self.session.port.capture_fault(error)
            raise

    def write_text(self, text: str) -> int:
        try:
            if type(text) is not str:
                raise TypeError("exact source UTF-8 text")
            self.write_bytes(text.encode())
            return len(text)
        except BaseException as error:
            self.session.port.capture_fault(error)
            raise

    def read_bytes(self) -> bytes:
        try:
            if self.name not in FAMILIES:
                raise ValueError("closed packet read")
            return self.session.port.read(self.target())
        except BaseException as error:
            self.session.port.capture_fault(error)
            raise

    def unlink(self) -> None:
        self.session.port.delete(self.target())


class Producer(Protocol):
    root: LogicalTempPath

    def rows(self) -> list[dict[str, object]]: ...
    def write_packet(
        self, rows: list[dict[str, object]] | None = None, code: int = 0
    ) -> LogicalTempPath: ...


class Session:
    def __init__(self, port: Port, mapping: Mapping = "natural_diagnostic") -> None:
        self.port, self.mapping = port, mapping
        self.attempts: list[Attempt] = []
        try:
            if mapping not in {"natural_diagnostic", "ephemeral_diagnostic"}:
                raise ValueError("diagnostic mapping is not a runtime grant")
            guard()
            qualification = AREA / "r21/qualification.py"
            spec = importlib.util.spec_from_file_location("r27_pre_pure_r21", qualification)
            if spec is None or spec.loader is None:
                raise ValueError("source loader")
            gate = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gate)  # Guarded stdlib-only chain; no source/snapshot dispatch.
            marker_tree = ast.parse(bounded(qualification))
            marker = next(
                n for n in marker_tree.body if isinstance(n, ast.FunctionDef) and n.name == "marker"
            )

            def logical_constructor(path: object) -> LogicalTempPath:
                if not isinstance(path, LogicalTempPath) or path.session is not self:
                    raise ValueError("marker reads only its original logical binding")
                return path

            marker_names: dict[str, object] = {
                "Path": logical_constructor,
                "digest": vars(gate)["digest"],
                "HERE": vars(gate)["HERE"],
            }
            exec(compile(ast.Module([marker], []), str(qualification), "exec"), marker_names)
            view = SimpleNamespace(
                **{
                    key: vars(gate)[key]
                    for key in ("HERE", "prior", "PROFILE", "LIMITS", "CONTROLS")
                },
                marker=marker_names["marker"],
            )
            path = AREA / "r21/test_r21_offline.py"
            tree = ast.parse(bounded(path))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
            methods = [
                n
                for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name in {"rows", "write_packet"}
            ]
            if len(methods) != 2:
                raise ValueError("exact two source methods")
            # Method nodes/bodies/line numbers are unmodified; only unittest base is unnecessary.
            selected = ast.ClassDef(cls.name, [], [], methods, [])
            ast.copy_location(selected, cls)
            names: dict[str, object] = {"gate": view, "json": json}
            exec(
                compile(ast.fix_missing_locations(ast.Module([selected], [])), str(path), "exec"),
                names,
            )
            self.producer = cast(type[Producer], names[cls.name])()
            self.producer.root = LogicalTempPath(self)
        except BaseException as error:
            port.capture_fault(error)
            raise

    def invoke(self, mode: Mode = "full") -> LogicalTempPath:
        try:
            guard()
            if mode not in {"full", "four", "one"}:
                raise ValueError("closed diagnostic rows parameter")
            rows = self.producer.rows()
            selected = rows if mode == "full" else rows[: 4 if mode == "four" else 1]
            return self.producer.write_packet(selected, 0 if mode == "full" else 1)
        except BaseException as error:
            self.port.capture_fault(error)
            raise


class MemoryPreview:
    """Bounded analysis memory only; not a qualifying storage or broker replacement."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.first_fault: BaseException | None = None
        self.total = 0

    def check(self) -> None:
        if self.first_fault is not None:
            raise self.first_fault

    def capture_fault(self, error: BaseException) -> None:
        if self.first_fault is None:
            self.first_fault = error

    def write(self, name: str, family: str, raw: bytes, mode: Literal["w"]) -> int:
        self.check()
        if len(raw) > 1048576 or self.total + len(raw) > 2097152:
            raise ValueError("bounded preview memory")
        self.total += len(raw)
        self.files[name] = raw
        return len(raw)

    def read(self, name: str) -> bytes:
        self.check()
        return self.files[name]

    def mkdir(self, name: str, parents: bool = False, exist_ok: bool = False) -> None:
        self.check()

    def delete(self, name: str) -> None:
        self.check()
        del self.files[name]


def preview(mode: Mode) -> Session:
    session = Session(MemoryPreview())
    session.invoke(mode)
    return session
