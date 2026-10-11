"""Entire original unittest corruption body and source-exact private read validators."""

from __future__ import annotations

import ast
import importlib.util
import json
import posixpath
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, Protocol, cast

import bridge
import stage
from host import HostPort


class PortOwner(Protocol):
    port: HostPort


def absorbing[T](method: Callable[..., T]) -> Callable[..., T]:
    def wrapped(*args: object, **kwargs: object) -> T:
        owner = args[0]
        try:
            return method(*args, **kwargs)
        except BaseException as error:
            session = getattr(owner, "session", owner)
            port = cast(PortOwner, session).port
            port.capture_fault(error)
            raise

    return wrapped


class StagePath:
    def __init__(self, session: Session, name: str = "") -> None:
        self.session, self._name = session, name

    @absorbing
    def __truediv__(self, child: str) -> StagePath:
        if type(child) is not str or child.startswith("/"):
            raise ValueError("closed relative source path")
        name = posixpath.normpath(posixpath.join(self._name, child))
        if name == ".." or name.startswith("../"):
            raise ValueError("source path escape")
        return StagePath(self.session, "" if name == "." else name)

    @property
    def parent(self) -> StagePath:
        return StagePath(self.session, posixpath.dirname(self._name))

    @property
    def name(self) -> str:
        return posixpath.basename(self._name)

    @absorbing
    def with_name(self, name: str) -> StagePath:
        if "/" in name or name in {"", ".", ".."}:
            raise ValueError("single source filename")
        return self.parent / name

    def __fspath__(self) -> NoReturn:
        error = TypeError("opaque PRE source capability, no native fspath")
        self.session.port.capture_fault(error)
        raise error

    def target(self) -> str:
        return "tmp/control" + ("/" + self._name if self._name else "")

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self.session.port.mkdir(self.target(), parents, exist_ok)

    def write_bytes(self, raw: bytes) -> int:
        if self._name not in stage.BOUNDS or type(raw) is not bytes:
            error = ValueError("exact closed source payload")
            self.session.port.capture_fault(error)
            raise error
        self.session.attempts.append((self._name, raw))
        return self.session.port.write(self.target(), "ephemeral", raw, "w")

    @absorbing
    def write_text(self, text: str) -> int:
        if type(text) is not str:
            raise TypeError("source text")
        self.write_bytes(text.encode())
        return len(text)

    def read_bytes(self) -> bytes:
        if self._name not in stage.BOUNDS:
            error = ValueError("closed source read")
            self.session.port.capture_fault(error)
            raise error
        # An expected missing-file oracle is not a failed storage attempt. Original
        # analyze catches it; do not poison an otherwise valid capture epoch.
        if not self.session.port.stat(self.target()).exists:
            missing = FileNotFoundError(self._name)
            if self._name != "r21_http_e1/run/latency-summary.json":
                self.session.port.capture_fault(missing)
            raise missing
        return self.session.port.read(self.target())

    def unlink(self) -> None:
        self.session.port.delete(self.target())


class SourceCase(Protocol):
    root: StagePath

    def test_packet_summary_controls_oracle_and_corruption(self) -> None: ...


def functions(
    path: Path, names: set[str], namespace: dict[str, object]
) -> dict[str, Callable[..., object]]:
    nodes = [
        n
        for n in ast.parse(bridge.bounded(path)).body
        if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    if {n.name for n in nodes} != names:
        raise ValueError("exact source functions")
    exec(compile(ast.Module([cast(ast.stmt, n) for n in nodes], []), str(path), "exec"), namespace)
    return {n: cast(Callable[..., object], namespace[n]) for n in names}


class Session:
    @absorbing
    def __init__(self, port: HostPort) -> None:
        self.port = port
        self.attempts: list[tuple[str, bytes]] = []
        stage.guard()
        source = bridge.AREA / "r21/qualification.py"
        spec = importlib.util.spec_from_file_location("r27_stage_pure_r21", source)
        if spec is None or spec.loader is None:
            raise ValueError("source loader")
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)

        def constructor(path: object) -> StagePath:
            if not isinstance(path, StagePath) or path.session is not self:
                raise ValueError("private source Path requires this live capability")
            port.check()
            return path

        prior = SimpleNamespace(**vars(original.prior))
        r18 = SimpleNamespace(**vars(original.prior.r18))
        prior.r18 = r18
        prior_names: dict[str, object] = {**vars(original.prior), "Path": constructor}
        prior.load_json = functions(
            bridge.AREA / "r19/qualification.py", {"load_json"}, prior_names
        )["load_json"]
        child_names: dict[str, object] = {**vars(original.prior.r18), "Path": constructor}
        r18.child_record = functions(bridge.AREA / "r18/gate.py", {"child_record"}, child_names)[
            "child_record"
        ]
        gate_names: dict[str, object] = {**vars(original), "Path": constructor, "prior": prior}
        selected = functions(source, {"marker", "journal_rows", "packet", "analyze"}, gate_names)
        gate = SimpleNamespace(**{**vars(original), **selected, "prior": prior})
        test_path = bridge.AREA / "r21/test_r21_offline.py"
        cls = next(
            n for n in ast.parse(bridge.bounded(test_path)).body if isinstance(n, ast.ClassDef)
        )
        names = {"rows", "write_packet", "test_packet_summary_controls_oracle_and_corruption"}
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
        if {n.name for n in methods} != names:
            raise ValueError("exact original class methods")
        selected_class = ast.ClassDef(
            cls.name,
            cls.bases,
            cls.keywords,
            [cast(ast.stmt, n) for n in methods],
            cls.decorator_list,
            type_params=[],
        )
        ast.copy_location(selected_class, cls)
        namespace: dict[str, object] = {
            "gate": gate,
            "json": json,
            "unittest": unittest,
            "__name__": "r27_closed_original_case",
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module([selected_class], [])), str(test_path), "exec"
            ),
            namespace,
        )
        factory = cast(Callable[..., SourceCase], namespace[cls.name])
        self.case = factory("test_packet_summary_controls_oracle_and_corruption")
        self.case.root = StagePath(self)

    def run(self) -> None:
        try:
            stage.guard()
            self.case.test_packet_summary_controls_oracle_and_corruption()
        except BaseException as error:
            self.port.capture_fault(error)
            raise


def run_original_corruption(port: HostPort) -> Session:
    session = Session(port)
    session.run()
    if len(session.attempts) != 35 or sum(len(raw) for _, raw in session.attempts) != 733169:
        raise ValueError("source-case fixed whole write identity")
    return session
