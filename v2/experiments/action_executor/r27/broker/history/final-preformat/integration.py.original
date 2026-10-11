"""Pinned cooperative producer bridges. No file hooks or physical producer paths."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import logging
import math
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from types import CodeType, FunctionType
from typing import Protocol, TextIO, cast

from broker import Broker, ProducerPath
from rtr_copilot.auth.audit import AuditEvent, StructuredAuditSink, audit_logger

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
BASE = ROOT / "v2/experiments/action_executor/r25/contract.json"
BASE_SHA = "43e24fdef2e1acfd3f00b409e9fd5a46853c4105d4b3c71f329b93c6f1eccbcc"
PROBE = "v2/experiments/action_executor/latency_probe.py"
R19 = "v2/experiments/action_executor/r19/bounded.py"
R21 = "v2/experiments/action_executor/r21/run-http-qualification.sh"
FIXTURE_DEPENDENCIES = {
    "v2/apps/backend/src/rtr_copilot/sot/package.py": "320391cc732e568c1a9e57b8d0c59045e2a6756faa2341ff8516613661f06e24",
    "v2/apps/backend/src/rtr_copilot/sot/models.py": "de4d7d642629f4eb68de217ac6994777a5865dadeb0d8343e93846138a42f2a9",
}
Record = dict[str, str | int | float | bool | None]
_SCOPE_LOCK = threading.Lock()
_ORACLE_EXIT: ContextVar[BaseException | None] = ContextVar("r27_broker_source_oracle", default=None)


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("typed source object")
    return cast(dict[str, object], value)


def rows(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("typed source array")
    return cast(list[object], value)


def pins() -> dict[str, str]:
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError("immutable base contract drift")
    result = {}
    for family in rows(mapping(json.loads(raw))["families"]):
        for witness in rows(mapping(family)["witnesses"]):
            row = mapping(witness)
            name, sha = row["path"], row["sha256"]
            if not isinstance(name, str) or not isinstance(sha, str):
                raise ValueError("typed source pin")
            result[name] = sha
    result.update(FIXTURE_DEPENDENCIES)  # Prior sealed runtime direct dependency pins, not self-authorized bytes.
    return result


def source(name: str) -> tuple[str, ast.Module]:
    path = ROOT / name
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("source symlink")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pins()[name]:
        raise ValueError("source drift")
    # Shell/JSON copies are pinned bytes, not Python AST producers.
    return raw.decode(), ast.parse(raw) if name.endswith(".py") else ast.Module(body=[], type_ignores=[])


def function(name: str, arguments: tuple[str, ...], body: list[ast.stmt]) -> ast.FunctionDef:
    return ast.FunctionDef(name=name, args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg=name) for name in arguments], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=body, decorator_list=[], type_params=[])


class BrokerStream:
    encoding = "utf-8"
    errors = "strict"

    def __init__(self, broker: Broker, family: str) -> None:
        self.__broker, self.family = broker, family
        self.__thread, self.active = threading.get_ident(), True
        broker.path("streams").mkdir(exist_ok=True)
        self.__path = broker.path("streams/" + family + ".txt", family)
        self.__file = self.__path.open("ab")

    def guard(self) -> None:
        if not self.active or threading.get_ident() != self.__thread:
            self.__broker.invalidate()
            raise ValueError("stale/foreign scoped output capability")

    def write(self, value: str) -> int:
        try:
            self.guard()
            if not isinstance(value, str):
                raise TypeError("whole producer text write required")
            self.__file.write(value.encode())
            return len(value)
        except BaseException:
            self.__broker.invalidate()
            raise

    def flush(self) -> None:
        try:
            self.guard()
            self.__file.flush()
        except BaseException:
            self.__broker.invalidate()
            raise

    def close_scope(self) -> None:
        try:
            self.__file.close()
        except BaseException:
            self.__broker.invalidate()
            raise
        finally:
            self.active = False

    def fileno(self) -> int:
        self.guard()
        self.__broker.invalidate()
        raise ValueError("no native descriptor")


class RaisingHandler(logging.StreamHandler[BrokerStream]):
    def __init__(self, stream: BrokerStream, broker: Broker) -> None:
        self.__broker = broker
        super().__init__(stream)

    def handleError(self, record: logging.LogRecord) -> None:
        self.__broker.invalidate()
        error = sys.exception()
        if error is None:
            raise RuntimeError("logging error without original exception")
        raise error


@contextmanager
def output_scope(broker: Broker) -> Iterator[None]:
    """Only scoped stdout/logger streams; no global filesystem interception."""
    if not _SCOPE_LOCK.acquire(blocking=False):
        broker.invalidate()
        raise ValueError("exclusive nonreentrant output scope")
    stdout = sys.stdout
    old = (audit_logger.handlers, audit_logger.filters, audit_logger.level,
           audit_logger.propagate, audit_logger.disabled)
    old_cache: object = vars(audit_logger).get("_cache")
    cache_present = "_cache" in vars(audit_logger)
    oracle_token = _ORACLE_EXIT.set(None)
    out = err = None
    handler = None
    try:
        if not isinstance(old_cache, dict) or logging.root.manager.disable:
            broker.invalidate()
            raise ValueError("supported logger cache/manager state required")
        source("v2/apps/backend/src/rtr_copilot/auth/audit.py")
        from rtr_copilot.auth import audit as actual
        if (Path(actual.__file__).resolve() != ROOT / "v2/apps/backend/src/rtr_copilot/auth/audit.py"
                or actual.StructuredAuditSink is not StructuredAuditSink
                or actual.AuditEvent is not AuditEvent or actual.audit_logger is not audit_logger):
            raise ValueError("actual audit producer identity")
        out, err = BrokerStream(broker, "summary_stdout"), BrokerStream(broker, "load_stderr")
        handler = RaisingHandler(err, broker)
        sys.stdout = cast(TextIO, out)
        audit_logger.handlers, audit_logger.filters = [handler], []
        audit_logger.level = logging.INFO
        vars(audit_logger)["_cache"] = {}
        audit_logger.propagate, audit_logger.disabled = False, False
        yield
    except BaseException as error:
        if error is not _ORACLE_EXIT.get():
            broker.invalidate()
        raise
    finally:
        primary = sys.exception()
        cleanup = None
        try:
            sys.stdout = stdout
            audit_logger.handlers, audit_logger.filters, audit_logger.level, audit_logger.propagate, audit_logger.disabled = old
            if cache_present:
                vars(audit_logger)["_cache"] = old_cache
            else:
                vars(audit_logger).pop("_cache", None)
            for stream in (out, err):
                if stream is not None:
                    try:
                        stream.close_scope()
                    except BaseException as fault:
                        cleanup = cleanup or fault
            if handler is not None:
                try:
                    handler.close()
                except BaseException as fault:
                    cleanup = cleanup or fault
        finally:
            try:
                _ORACLE_EXIT.reset(oracle_token)
            finally:
                _SCOPE_LOCK.release()
        if cleanup is not None:
            broker.invalidate()
            if primary is not None:
                primary.add_note("broker scoped output cleanup failed; primary retained")
                raise primary from cleanup
            raise cleanup


class Producers:
    def __init__(self, broker: Broker) -> None:
        self.__broker = broker
        try:
            _, tree = source(PROBE)
            main = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "main")
            attempt = next(node for node in main.body if isinstance(node, ast.Try))
            retain = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == "retain")
            start = next(index for index, node in enumerate(attempt.body)
                         if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "cells")
            final = next(node for node in attempt.finalbody if isinstance(node, ast.Expr)
                         and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                         and node.value.func.attr == "write_text")
            quantile = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "quantile")
            summary = attempt.body[start:]
            namespace: dict[str, object] = {"json": json, "math": math}
            nodes: list[ast.stmt] = [quantile, function("summary", ("records", "root"), summary),
                                   function("final", ("records", "root"), [final])]
            exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), PROBE, "exec"), namespace)
            self.summary = cast(Callable[[list[Record], DriverRoot], None], namespace["summary"])
            self.final = cast(Callable[[list[Record], DriverRoot], None], namespace["final"])
            self.summary_code = cast(FunctionType, namespace["summary"]).__code__
            last = summary[-1]
            if not isinstance(last, ast.If) or not isinstance(last.body[0], ast.Raise):
                raise ValueError("exact source oracle shape")
            self.oracle_line = last.body[0].lineno
            self.retain_node = retain
            source("v2/apps/backend/src/rtr_copilot/auth/audit.py")
        except BaseException:
            broker.invalidate()
            raise

    def journal(self, records: list[Record], observations: object) -> Callable[[Record], None]:
        try:
            namespace: dict[str, object] = {"json": json, "records": records, "observations": observations}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[self.retain_node], type_ignores=[])), PROBE, "exec"), namespace)
            callback = cast(Callable[[Record], None], namespace["retain"])
        except BaseException:
            self.__broker.invalidate()
            raise

        def retain(record: Record) -> None:
            try:
                callback(record)
            except BaseException:
                self.__broker.invalidate()
                raise
        return retain

    def finish(self, records: list[Record], root: ProducerPath) -> None:
        primary = None
        routed = DriverRoot(self.__broker, root)
        try:
            self.summary(records, routed)
        except BaseException as error:
            primary = error
            trace = error.__traceback__
            while trace is not None and trace.tb_next is not None:
                trace = trace.tb_next
            oracle = (type(error) is SystemExit and error.code == 1 and trace is not None
                      and trace.tb_frame.f_code is self.summary_code and trace.tb_lineno == self.oracle_line)
            if not oracle:
                self.__broker.invalidate()
            else:
                _ORACLE_EXIT.set(error)
        try:
            self.final(records, routed)
        except BaseException as cleanup:
            self.__broker.invalidate()
            if primary is not None:
                raise primary from cleanup
            raise
        if primary is not None:
            raise primary

    def audit(self) -> None:
        try:
            StructuredAuditSink().emit(AuditEvent(actor_id="synthetic", action="broker.source",
                result="success", reason="local", request_id="r27-broker", timestamp=datetime(2026,1,1,tzinfo=UTC)))
        except BaseException:
            self.__broker.invalidate()
            raise


class DriverRoot:
    """Closed original filename-to-family routing; carries logical ports only."""

    def __init__(self, broker: Broker, root: ProducerPath) -> None:
        self.__broker, self.__root = broker, root

    def __truediv__(self, name: str) -> ProducerPath:
        try:
            families = {"latency-summary.json": "summary_stdout", "samples.json": "final_samples"}
            return self.__broker.path((self.__root / name).as_posix(), families[name])
        except BaseException:
            self.__broker.invalidate()
            raise


class FixtureCall(Protocol):
    def __call__(self, root: ProducerPath, *, curator_id: uuid.UUID, package_id: uuid.UUID) -> ProducerPath: ...


def signed_fixture(broker: Broker, root: ProducerPath) -> ProducerPath:
    try:
        name = "v2/apps/backend/tests/sot_fixtures.py"
        source(name)
        for dependency in ("v2/apps/backend/src/rtr_copilot/sot/package.py", "v2/apps/backend/src/rtr_copilot/sot/models.py"):
            source(dependency)
        spec = importlib.util.spec_from_file_location("r27_broker_fixture_source", ROOT / name)
        if spec is None or spec.loader is None:
            raise ValueError("fixture loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        build: object = getattr(module, "build_package")
        if not isinstance(build, FunctionType) or Path(build.__code__.co_filename).resolve() != ROOT / name:
            raise ValueError("full pinned fixture identity")
        return cast(FixtureCall, build)(root, curator_id=uuid.UUID(int=1), package_id=uuid.UUID(int=2))
    except BaseException:
        broker.invalidate()
        raise


def shell_outputs(broker: Broker) -> None:
    try:
        broker.path("launcher").mkdir(exist_ok=True)
        for name, logical in (("source-binding-e1.json", "binding.json"), ("contract.json", "contract.json")):
            raw, _ = source("v2/experiments/action_executor/r21/" + name)
            broker.path("launcher/" + logical, "frozen_copies").write_bytes(raw.encode())
        shell, _ = source(R21)
        line = next(line for line in shell.splitlines() if '"$evidence/executor-scope.txt"' in line)
        broker.path("launcher/scope.txt", "literal_scope").write_bytes(line.split("'", 2)[1].replace("\\n", "\n").encode())
        _, tree = source("v2/experiments/action_executor/r/run_phase_baseline.py")
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"
                    and "r-controls.json" in ast.unparse(node))
        namespace: dict[str, object] = {"json": json, "mode": "off"}
        value: object = eval(compile(ast.Expression(node.args[0]), "baseline#literal", "eval"), namespace)
        if not isinstance(value, str):
            raise ValueError("literal text")
        broker.path("launcher/controls.json", "literal_controls").write_text(value)
        broker.path("launcher/review.txt", "launch_review").write_text("local source control " + "a" * 64 + "\n")
        broker.path("launcher/returncodes.txt", "returncodes").write_text("local-control 0\n")
    except BaseException:
        broker.invalidate()
        raise


def cleanup_writer(broker: Broker) -> Callable[[dict[str, object], ProducerPath], float]:
    try:
        _, tree = source(R19)
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "begin_cleanup")
        def require(ok: object, message: str) -> None:
            if not ok:
                raise ValueError(message)
        namespace: dict[str, object] = {"json": json, "time": time, "math": math,
            "CAPS": {"kill_grace_seconds": 10}, "require": require}
        exec(compile(ast.Module(body=[node], type_ignores=[]), R19, "exec"), namespace)
        return cast(Callable[[dict[str, object], ProducerPath], float], namespace["begin_cleanup"])
    except BaseException:
        broker.invalidate()
        raise


def metadata_expressions(broker: Broker) -> dict[str, CodeType]:
    try:
        _, tree = source(R19)
        function_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "supervise")
        result = {}
        for node in ast.walk(function_node):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                name = ast.unparse(node.targets[0])
                if name in {"owner", "result"}:
                    result[name] = compile(ast.Expression(node.value), R19, "eval")
        if set(result) != {"owner", "result"}:
            raise ValueError("original metadata source shape")
        return result
    except BaseException:
        broker.invalidate()
        raise
