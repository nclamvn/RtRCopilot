"""Pinned original output producer blocks, never the driver/main/request workload."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Protocol, TypedDict, cast

from envelope import Capture
from rtr_copilot.actions.request_connection import RequestConnection
from rtr_copilot.auth.audit import AuditEvent, StructuredAuditSink

ROOT = Path(__file__).absolute().parent.parents[4]
SOURCES = {
    "v2/experiments/action_executor/latency_probe.py": (
        "e94a79a6b0f1695a23db07bfb5f12d5e5746f898893de9cf11cbb6527d6d4ad2"
    ),
    "v2/apps/backend/tests/sot_fixtures.py": (
        "524e0f00a30b13b0d8844070556f0713ee9e4b7e22e72ac6b16bf9c8e8ccaacd"
    ),
    "v2/apps/backend/src/rtr_copilot/auth/audit.py": (
        "13e3da023c2b886725c6fa0270789c6297b58647dbcd8949ef5ad7474fe0fa8e"
    ),
    "v2/apps/backend/src/rtr_copilot/sot/package.py": (
        "320391cc732e568c1a9e57b8d0c59045e2a6756faa2341ff8516613661f06e24"
    ),
    "v2/apps/backend/src/rtr_copilot/sot/models.py": (
        "de4d7d642629f4eb68de217ac6994777a5865dadeb0d8343e93846138a42f2a9"
    ),
    "v2/apps/backend/src/rtr_copilot/actions/request_connection.py": (
        "c56d7b09a9845cfe23e4f580849f355c32a40366fd6abc22260f8e85210b93d0"
    ),
}


def read_source(name: str) -> tuple[str, ast.Module]:
    path = ROOT / name
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("source symlink")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCES[name]:
        raise ValueError("producer source drift")
    return raw.decode(), ast.parse(raw)


def function(name: str, arguments: tuple[str, ...], body: list[ast.stmt]) -> ast.FunctionDef:
    return ast.FunctionDef(
        name=name,
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=arg) for arg in arguments],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=body,
        decorator_list=[],
        type_params=[],
    )


def prepared() -> tuple[ast.FunctionDef, dict[str, object], Witnesses]:
    driver = next(iter(SOURCES))
    text, tree = read_source(driver)
    main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    retain = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "retain")
    attempt = next(n for n in main.body if isinstance(n, ast.Try))
    start = next(
        i
        for i, n in enumerate(attempt.body)
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == "cells"
    )
    summary = attempt.body[start:]  # Original cells/report/write/print/FAIL oracle.
    final = next(
        n
        for n in attempt.finalbody
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "write_text"
    )
    quantile = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "quantile")
    nodes: list[ast.stmt] = [
        quantile,
        function("source_summary", ("records", "root"), summary),
        function("source_final", ("records", "root"), [final]),
    ]
    namespace: dict[str, object] = {"json": json, "math": math}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
            driver + "#output-producers",
            "exec",
        ),
        namespace,
    )
    witnesses: Witnesses = {
        "oracle_line": 0,
        "summary_nodes": "",
        "retain": hashlib.sha256(segment(text, retain).encode()).hexdigest(),
        "final_samples": hashlib.sha256(segment(text, final).encode()).hexdigest(),
    }
    witnesses["summary_nodes"] = hashlib.sha256(
        "".join(segment(text, node) for node in summary).encode()
    ).hexdigest()
    oracle = summary[-1]
    if not isinstance(oracle, ast.If) or not isinstance(oracle.body[0], ast.Raise):
        raise ValueError("source oracle shape")
    witnesses["oracle_line"] = oracle.body[0].lineno
    return retain, namespace, witnesses


class DriverOutputs:
    def __init__(self, capture: Capture) -> None:
        self.capture = capture
        try:
            self.retain_node, self.namespace, self.witnesses = prepared()
            self.summary = as_output(self.namespace["source_summary"])
            self.final = as_output(self.namespace["source_final"])
        except BaseException:
            capture.invalidate()
            raise

    def _journal(self, records: list[object], observations: object) -> Retain:
        namespace: dict[str, object] = {
            "json": json,
            "records": records,
            "observations": observations,
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[self.retain_node], type_ignores=[])),
                "latency_probe.py#retain",
                "exec",
            ),
            namespace,
        )
        original = as_retain(namespace["retain"])

        def retain(record: object) -> None:
            try:
                original(record)
            except BaseException:
                self.capture.invalidate()
                raise

        return retain

    def journal(self, records: list[object], observations: object) -> Retain:
        try:
            return self._journal(records, observations)
        except BaseException:
            self.capture.invalidate()
            raise

    def finish(self, records: list[object], root: Path) -> None:
        original = None
        try:
            try:
                self.summary(records, root)
            except BaseException as error:
                original = error
                terminal = error.__traceback__
                while terminal is not None and terminal.tb_next is not None:
                    terminal = terminal.tb_next
                if (
                    type(error) is SystemExit
                    and error.code == 1
                    and terminal is not None
                    and terminal.tb_frame.f_code
                    is cast(FunctionType, self.namespace["source_summary"]).__code__
                    and terminal.tb_lineno == self.witnesses["oracle_line"]
                ):
                    self.capture._oracle_exit = error
            try:
                # Exact final producer block, also attempted after a primary oracle failure.
                self.final(records, root)
            except BaseException as cleanup:
                self.capture.invalidate()
                if original is not None:
                    raise original from cleanup
                raise
            if original is not None:
                raise original
        except BaseException as error:
            if error is not self.capture._oracle_exit:
                self.capture.invalidate()
            raise


def _audit_producer(capture: Capture) -> tuple[AuditEmit, logging.Logger]:
    name = "v2/apps/backend/src/rtr_copilot/auth/audit.py"
    read_source(name)
    module = importlib.import_module("rtr_copilot.auth.audit")
    if module_path(module).resolve() != ROOT / name:
        raise ValueError("audit module identity")
    logger: object = attribute(module, "audit_logger")
    if (
        not isinstance(logger, logging.Logger)
        or attribute(module, "AuditEvent") is not AuditEvent
        or attribute(module, "StructuredAuditSink") is not StructuredAuditSink
    ):
        raise ValueError("audit actual identities")
    capture.attach_logger(logger)
    sink = StructuredAuditSink()

    def emit(**fields: object) -> AuditEvent:
        try:
            event = cast(AuditConstructor, AuditEvent)(**fields)
            sink.emit(event)
            return event
        except BaseException:
            capture.invalidate()
            raise

    return emit, logger


def _fixture_producer(capture: Capture) -> tuple[Build, FixtureModule]:
    name = "v2/apps/backend/tests/sot_fixtures.py"
    read_source(name)
    for dependency in (
        "v2/apps/backend/src/rtr_copilot/sot/package.py",
        "v2/apps/backend/src/rtr_copilot/sot/models.py",
    ):
        read_source(dependency)
    spec = importlib.util.spec_from_file_location("r27_retention_fixture_source", ROOT / name)
    if spec is None or spec.loader is None:
        raise ValueError("fixture loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original: object = attribute(module, "build_package")
    if (
        not isinstance(original, FunctionType)
        or Path(original.__code__.co_filename).resolve() != ROOT / name
    ):
        raise ValueError("fixture function identity")
    for dependency in ("rtr_copilot.sot.package", "rtr_copilot.sot.models"):
        path = module_path(sys.modules[dependency]).resolve().relative_to(ROOT).as_posix()
        read_source(path)

    def build(root: Path, **kwargs: object) -> Path:
        try:
            return cast(Build, original)(root, **kwargs)
        except BaseException:
            capture.invalidate()
            raise

    if not isinstance(attribute(module, "NOW"), datetime):
        raise ValueError("fixture clock")
    return build, cast(FixtureModule, module)


def _request_class() -> type[RequestConnection]:
    name = "v2/apps/backend/src/rtr_copilot/actions/request_connection.py"
    read_source(name)
    module = importlib.import_module("rtr_copilot.actions.request_connection")
    if module_path(module).resolve() != ROOT / name:
        raise ValueError("request class identity")
    if attribute(module, "RequestConnection") is not RequestConnection:
        raise ValueError("request class identity")
    return RequestConnection


class Witnesses(TypedDict):
    retain: str
    final_samples: str
    summary_nodes: str
    oracle_line: int


class Retain(Protocol):
    def __call__(self, record: object) -> None: ...


class Output(Protocol):
    def __call__(self, records: list[object], root: Path) -> None: ...


class Build(Protocol):
    def __call__(self, root: Path, **kwargs: object) -> Path: ...


class AuditConstructor(Protocol):
    def __call__(self, **fields: object) -> AuditEvent: ...


class AuditEmit(AuditConstructor, Protocol):
    pass


class FixtureModule(Protocol):
    NOW: datetime
    build_package: Build


def segment(text: str, node: ast.AST) -> str:
    result = ast.get_source_segment(text, node)
    if result is None:
        raise ValueError("source segment absent")
    return result


def as_retain(value: object) -> Retain:
    if not isinstance(value, FunctionType) or value.__code__.co_argcount != 1:
        raise ValueError("compiled retain interface")
    return cast(Retain, value)


def as_output(value: object) -> Output:
    if not isinstance(value, FunctionType) or value.__code__.co_argcount != 2:
        raise ValueError("compiled output interface")
    return cast(Output, value)


def module_path(module: ModuleType) -> Path:
    if module.__file__ is None:
        raise ValueError("file-backed module required")
    return Path(module.__file__)


def attribute(module: ModuleType, name: str) -> object:
    value: object = vars(module)[name]
    return value


def audit_producer(capture: Capture) -> tuple[AuditEmit, logging.Logger]:
    try:
        return _audit_producer(capture)
    except BaseException:
        capture.invalidate()
        raise


def fixture_producer(capture: Capture) -> tuple[Build, FixtureModule]:
    try:
        return _fixture_producer(capture)
    except BaseException:
        capture.invalidate()
        raise


def request_class(capture: Capture) -> type[RequestConnection]:
    try:
        return _request_class()
    except BaseException:
        capture.invalidate()
        raise
