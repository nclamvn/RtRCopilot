"""Closed full-source driver/seed/storage/logger composition; not load admission."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import CodeType, SimpleNamespace
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, TextIO, cast
from uuid import UUID

from ports import PathPort, RichPath, Stat

if TYPE_CHECKING:
    from rtr_copilot.auth.models import Subject
    from rtr_copilot.config import Settings
    from rtr_copilot.context.models import SOTReference
    from rtr_copilot.sot.models import ParsedPackage
    from rtr_copilot.sot.service import SOTPublishService
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
PROBE = "v2/experiments/action_executor/latency_probe.py"
BASELINE = "v2/experiments/action_executor/r/run_phase_baseline.py"
CONTEXT = "v2/apps/backend/tests/test_context_memory_integration.py"
SETTINGS_HELPER = "v2/apps/backend/tests/test_tip054_baseline_integration.py"
BASE = ROOT / "v2/experiments/action_executor/r25/contract.json"
BASE_SHA = "43e24fdef2e1acfd3f00b409e9fd5a46853c4105d4b3c71f329b93c6f1eccbcc"
OLD_BINDING = ROOT / "v2/experiments/action_executor/r18/source-binding-e3.json"
OLD_SHA = "5bb847ef6bee176454cc14ae4bd35024b847aef8f969d7f12f0c877a87f7b0f5"
_LOCK = threading.Lock()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError("string-key source object")
    return cast(dict[str, object], value)


def rows(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("source array")
    return cast(list[object], value)


def bounded(path: Path, maximum: int = 262144) -> bytes:
    if (
        not path.is_file()
        or any(item.is_symlink() for item in (path, *path.parents))
        or path.stat().st_size > maximum
    ):
        raise ValueError("finite nonsymlink source")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("source grew beyond bound")
    return raw


def pins() -> dict[str, str]:
    raw = bounded(OLD_BINDING)
    base = bounded(BASE)
    if digest(raw) != OLD_SHA or digest(base) != BASE_SHA:
        raise ValueError("immutable source/base authority")
    result: dict[str, str] = {}
    for name, sha in mapping(mapping(json.loads(raw))["files"]).items():
        if not isinstance(sha, str):
            raise ValueError("source SHA")
        result[name] = sha
    for family in rows(mapping(json.loads(base))["families"]):
        for witness in rows(mapping(family)["witnesses"]):
            item = mapping(witness)
            witness_name, witness_sha = item["path"], item["sha256"]
            if not isinstance(witness_name, str) or not isinstance(witness_sha, str):
                raise ValueError("source witness")
            result[witness_name] = witness_sha
    return result


def source(name: str) -> bytes:
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("source namespace")
    raw = bounded(ROOT / name)
    if digest(raw) != pins()[name]:
        raise ValueError("actual pinned source drift: " + name)
    return raw


def function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    )


def compile_functions(
    name: str, names: tuple[str, ...], globals_: dict[str, object]
) -> dict[str, object]:
    tree = ast.parse(source(name))
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *(function(tree, name) for name in names),
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(ROOT / name), "exec"), globals_)
    return globals_


def actual_module(name: str, relative: str) -> object:
    source(relative)  # Validate BEFORE importing, not after executing changed bytes.
    module = __import__(name, fromlist=["__name__"])
    filename: object = vars(module).get("__file__")
    if not isinstance(filename, str) or Path(filename).resolve() != ROOT / relative:
        raise ValueError("actual module identity: " + name)
    return module


class DriverPort:
    """Closed original filename routes, not a generic path-to-family grant."""

    def __init__(self, port: PathPort) -> None:
        self.__port = port
        self.namespace = port.namespace
        self.__fault: BaseException | None = None

    @property
    def first_fault(self) -> BaseException | None:
        return self.__port.first_fault or self.__fault

    def capture_fault(self, error: BaseException) -> None:
        self.__fault = self.first_fault or error
        self.__port.capture_fault(error)

    def _deny(self, message: str) -> NoReturn:
        error = ValueError(message)
        self.capture_fault(error)
        raise error

    def family(self, name: str) -> str:
        table = {
            "run/samples.jsonl": "journal",
            "run/samples.json": "final_samples",
            "run/latency-summary.json": "summary_stdout",
            "run/r-controls.json": "literal_controls",
            "streams/load.stderr": "load_stderr",
            "streams/load.stdout": "summary_stdout",
        }
        if name in table:
            return table[name]
        if name == "tmp/seed" or name.startswith("tmp/seed/"):
            return "ephemeral"
        self._deny("unmapped real driver artifact")

    def path(self, name: str = "", family: str = "ephemeral") -> RichPath:
        return RichPath(self, name, family)

    def write(self, name: str, family: str, raw: bytes, mode: str) -> int:
        if mode not in {"w", "a", "x"}:
            self._deny("closed write mode")
        return self.__port.write(name, self.family(name), raw, cast(Literal["w", "a", "x"], mode))

    def read(self, name: str) -> bytes:
        return self.__port.read(name)

    def stat(self, name: str) -> Stat:
        return self.__port.stat(name)

    def listdir(self, name: str) -> tuple[str, ...]:
        return self.__port.listdir(name)

    def mkdir(self, name: str, parents: bool = False, exist_ok: bool = False) -> None:
        if name not in {"run", "tmp", "tmp/seed", "streams"} and not name.startswith("tmp/seed/"):
            self._deny("closed runtime directory")
        self.__port.mkdir(name, parents, exist_ok)

    def delete(self, name: str) -> None:
        if not name.startswith("tmp/seed/") and name != "tmp/seed":
            self._deny("only owned temporary cleanup")
        self.__port.delete(name)

    def flush(self) -> None:
        self.__port.flush()

    def record(self, family: str, raw: bytes) -> int:
        self._deny("driver cannot mint arbitrary packet-only endpoints")

    def invalidate(self) -> None:
        self.__port.invalidate()

    def generation(self, prefix: str = "") -> str:
        return self.__port.generation(prefix)

    def snapshot(self, prefix: str = "") -> PathPort:
        return self.__port.snapshot(prefix)

    def check(self) -> None:
        self.__port.check()
        if self.__fault is not None:
            raise self.__fault

    def owner_check(self) -> None:
        self.__port.owner_check()

    def file_open(self) -> str:
        return self.__port.file_open()

    def file_close(self, token: str) -> None:
        self.__port.file_close(token)


class RefreshingParser:
    """ONLY storage seam: a fresh genuine parser on one owner-frozen subtree per parse."""

    def __init__(self, root: RichPath) -> None:
        self.__root = root

    def parse(self, staging_name: str) -> ParsedPackage:
        from rtr_copilot.sot.package import PackageParser

        snapshot = self.__root.snapshot()
        return PackageParser(cast(Path, snapshot)).parse(staging_name)


class SeedCall(Protocol):
    async def __call__(
        self,
        root: RichPath,
        factory: async_sessionmaker[AsyncSession],
        owner: Subject,
        source: str,
        core: str,
    ) -> tuple[SOTReference, ...]: ...


class SeedBridge:
    def __init__(self, port: PathPort, database_dsn: str) -> None:
        self.port = port
        try:
            if database_dsn != (
                "postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/"
                "rtr_tip054_r27_real_local_e1"
            ):
                raise ValueError("exact future local source namespace, not execution authority")
            actual_module("rtr_copilot.config", "v2/apps/backend/src/rtr_copilot/config.py")
            actual_module(
                "rtr_copilot.sot.package", "v2/apps/backend/src/rtr_copilot/sot/package.py"
            )
            actual_module(
                "rtr_copilot.sot.service", "v2/apps/backend/src/rtr_copilot/sot/service.py"
            )
            from pydantic import SecretStr
            from rtr_copilot.config import Settings
            from rtr_copilot.context.models import SOTReference
            from rtr_copilot.sot.models import PackageManifest, PackageRecord, PublishAttestation
            from rtr_copilot.sot.package import (
                canonical_json,
                manifest_identity_sha,
                record_content_sha,
                sha256_bytes,
                sign_attestation,
            )
            from rtr_copilot.sot.service import SOTPublishService
            from sqlalchemy import text

            name = "v2/apps/backend/tests/sot_fixtures.py"
            source(name)
            spec = importlib.util.spec_from_file_location(
                "r27_real_original_sot_fixture", ROOT / name
            )
            if spec is None or spec.loader is None:
                raise ValueError("fixture source loader")
            fixture = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fixture)
            self.publisher_class = SOTPublishService
            self.fixture_build = fixture.build_package
            self.now = fixture.NOW
            self.secret = fixture.SECRET
            globals_: dict[str, object] = {
                "Settings": Settings,
                "SecretStr": SecretStr,
                "SECRET": self.secret,
                "DATABASE_DSN": database_dsn,
            }
            self.settings_call = cast(
                Callable[[Path], Settings],
                compile_functions(SETTINGS_HELPER, ("synthetic_settings",), globals_)[
                    "synthetic_settings"
                ],
            )
            helpers: dict[str, object] = {
                "json": json,
                "UUID": UUID,
                "text": text,
                "build_package": self.fixture_build,
                "NOW": self.now,
                "SOTReference": SOTReference,
                "PackageRecord": PackageRecord,
                "PackageManifest": PackageManifest,
                "PublishAttestation": PublishAttestation,
                "canonical_json": canonical_json,
                "record_content_sha": record_content_sha,
                "manifest_identity_sha": manifest_identity_sha,
                "sha256_bytes": sha256_bytes,
                "sign_attestation": sign_attestation,
                "synthetic_settings": self.settings,
                "SOTPublishService": self.publisher,
            }
            self.publish = cast(
                SeedCall,
                compile_functions(CONTEXT, ("annotate_package", "publish"), helpers)["publish"],
            )
        except BaseException as error:
            port.capture_fault(error)
            raise

    def settings(self, root: RichPath) -> Settings:
        try:
            if root.namespace != self.port.namespace:
                raise ValueError("same opaque seed namespace")
            # Ordinary logical namespace Path, NEVER broker artifact storage.
            return self.settings_call(Path(root.logical_path))
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def publisher(
        self,
        settings: Settings,
        *,
        factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
    ) -> SOTPublishService:
        try:
            return self._publisher(settings, factory=factory, clock=clock)
        except BaseException as error:
            self.port.capture_fault(error)
            raise

    def _publisher(
        self,
        settings: Settings,
        *,
        factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
    ) -> SOTPublishService:
        from rtr_copilot.sot.package import PackageParser

        root = self.port.path("tmp/seed", "ephemeral")
        if settings.sot_staging_root != Path(root.logical_path):
            self.port.invalidate()
            raise ValueError("original constructor's logical storage seam")
        actual = self.publisher_class(settings, factory=factory, clock=clock)
        if type(actual) is not self.publisher_class or actual.uow.factory is not factory:
            self.port.invalidate()
            raise ValueError("genuine publisher/factory identity")
        for name in ("stage", "validate", "publish"):
            if getattr(actual, name).__func__ is not getattr(self.publisher_class, name):
                self.port.invalidate()
                raise ValueError("full inherited publisher method identity")
        actual.parser = cast(PackageParser, RefreshingParser(root))
        return actual


class NativeDenied:
    encoding = "utf-8"
    errors = "strict"

    def __init__(self, port: PathPort) -> None:
        self.__port = port

    def write(self, text: str) -> int:
        error = ValueError("unframed native stderr unsupported; no line/chunk reframing")
        self.__port.capture_fault(error)
        raise error

    def flush(self) -> None:
        self.__port.flush()

    def fileno(self) -> int:
        error = ValueError("no native artifact descriptor")
        self.__port.capture_fault(error)
        raise error


class RenderedHandler(logging.Handler):
    def __init__(
        self,
        port: PathPort,
        formatter: logging.Formatter | None = None,
        terminator: str = "\n",
        family: str = "load_stderr",
    ) -> None:
        super().__init__()
        self.__port, self.__creator = port, threading.get_ident()
        self.active = True
        self.terminator, self.family = terminator, family
        self.setFormatter(formatter or logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not self.active or threading.get_ident() != self.__creator:
                raise ValueError("stale/foreign rendered record endpoint")
            raw = (self.format(record) + self.terminator).encode("utf-8")
            self.__port.write("streams/" + self.family, self.family, raw, "a")
            self.__port.flush()
        except BaseException as error:
            self.__port.capture_fault(error)
            raise


class OriginalStdout:
    encoding = "utf-8"
    errors = "strict"

    def __init__(self, port: PathPort, codes: tuple[CodeType, ...]) -> None:
        self.__port, self.__codes = port, codes
        self.__creator = threading.get_ident()
        self.active = True

    def write(self, text: str) -> int:
        try:
            if (
                not self.active
                or threading.get_ident() != self.__creator
                or sys._getframe(1).f_code not in self.__codes
            ):
                raise ValueError("only source-connected original stdout operation")
            self.__port.write("streams/load.stdout", "summary_stdout", text.encode(), "a")
            return len(text)
        except BaseException as error:
            self.__port.capture_fault(error)
            raise

    def flush(self) -> None:
        try:
            if not self.active or threading.get_ident() != self.__creator:
                raise ValueError("stale/foreign original stdout endpoint")
            self.__port.flush()
        except BaseException as error:
            self.__port.capture_fault(error)
            raise

    def fileno(self) -> int:
        error = ValueError("no original stdout artifact fd")
        self.__port.capture_fault(error)
        raise error


def source_oracle(port: PathPort, error: BaseException, codes: tuple[CodeType, ...]) -> bool:
    if type(error) is not SystemExit or error.code != 1 or port.first_fault is not None:
        return False
    tree = ast.parse(source(PROBE))
    line = next(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and ast.unparse(node) == "raise SystemExit(1)"
    )
    trace = error.__traceback__
    located = False
    while trace is not None:
        located |= (
            trace.tb_frame.f_code in codes
            and trace.tb_frame.f_code.co_filename == str(ROOT / PROBE)
            and trace.tb_lineno == line
        )
        trace = trace.tb_next
    if not located:
        return False
    summary = port.read("run/latency-summary.json")
    report = mapping(json.loads(summary))
    return (
        report.get("status") == "FAIL"
        and port.read("streams/load.stdout") == summary + b"\n"
        and port.stat("run/samples.json").exists
    )


@dataclass
class LoggerState:
    logger: logging.Logger
    handlers: list[logging.Handler]
    filters: object
    level: int
    propagate: bool
    disabled: bool
    cache: dict[int, bool]
    contents: dict[int, bool]

    @classmethod
    def take(cls, logger: logging.Logger) -> LoggerState:
        cache = cache_of(logger)
        return cls(
            logger,
            logger.handlers,
            logger.filters,
            logger.level,
            logger.propagate,
            logger.disabled,
            cache,
            dict(cache),
        )

    def restore(self) -> None:
        self.logger.handlers, self.logger.level = self.handlers, self.level
        vars(self.logger)["filters"] = self.filters
        self.logger.propagate, self.logger.disabled = self.propagate, self.disabled
        self.cache.clear()
        self.cache.update(self.contents)
        vars(self.logger)["_cache"] = self.cache


def assert_logging_routes() -> None:
    for logger in (
        logging.root,
        *(
            item
            for item in logging.root.manager.loggerDict.values()
            if isinstance(item, logging.Logger)
        ),
    ):
        if any(
            not isinstance(handler, RenderedHandler) or not handler.active
            for handler in logger.handlers
        ):
            raise ValueError("new explicit native logger handler unsupported before dispatch")


@contextmanager
def logging_scope(port: PathPort, stdout_codes: tuple[CodeType, ...] = ()) -> Iterator[None]:
    if not _LOCK.acquire(blocking=False):
        error = ValueError("exclusive creator logging composition")
        port.capture_fault(error)
        raise error
    manager = logging.root.manager
    old_stdout, old_stderr = sys.stdout, sys.stderr
    handlers: list[RenderedHandler] = []
    saved: list[LoggerState] = []
    stdout = OriginalStdout(port, stdout_codes)
    previous_get = vars(manager).get("getLogger")
    original_get = manager.getLogger
    creator = threading.get_ident()
    try:
        loggers = [
            logging.root,
            *(item for item in manager.loggerDict.values() if isinstance(item, logging.Logger)),
        ]
        saved = [LoggerState.take(logger) for logger in loggers]

        def get_logger(name: str) -> logging.Logger:
            try:
                if threading.get_ident() != creator:
                    raise ValueError("foreign logger creation during exclusive scope")
                logger = original_get(name)
                if all(state.logger is not logger for state in saved):
                    saved.append(LoggerState.take(logger))
                    vars(logger)["_cache"] = {}
                return logger
            except BaseException as error:
                port.capture_fault(error)
                raise

        vars(manager)["getLogger"] = get_logger
        port.mkdir("streams", exist_ok=True)
        for logger in loggers:
            bridged: list[logging.Handler] = []
            for original in logger.handlers:
                if not isinstance(original, logging.StreamHandler) or isinstance(
                    original, logging.FileHandler
                ):
                    raise ValueError("explicit unknown/nonstream logger handler unsupported")
                handler = RenderedHandler(port, original.formatter, original.terminator)
                handler.level, handler.filters = original.level, original.filters
                bridged.append(handler)
                handlers.append(handler)
            logger.handlers = bridged
            vars(logger)["_cache"] = {}
        if not logging.root.handlers:
            handler = RenderedHandler(port)
            handlers.append(handler)
            logging.root.handlers = [handler]
            level = logging.getLevelNamesMapping().get(os.environ.get("LOG_LEVEL", "INFO"))
            if not isinstance(level, int):
                raise ValueError("original basicConfig level")
            logging.root.level = level
        sys.stdout, sys.stderr = cast(TextIO, stdout), cast(TextIO, NativeDenied(port))
        yield
        if port.first_fault is not None:
            raise port.first_fault
    except BaseException as error:
        if not source_oracle(port, error, stdout_codes):
            port.capture_fault(error)
        raise
    finally:
        primary = sys.exception()
        cleanup: BaseException | None = None
        try:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            # Keep cold-import genuine Logger identities; restore their creation state.
            for state in saved:
                try:
                    state.restore()
                except BaseException as error:
                    cleanup = cleanup or error
            if previous_get is None:
                vars(manager).pop("getLogger", None)
            else:
                vars(manager)["getLogger"] = previous_get
            stdout.active = False
            for handler in handlers:
                handler.active = False
                try:
                    handler.close()
                except BaseException as error:
                    cleanup = cleanup or error
        finally:
            _LOCK.release()
        if cleanup is not None:
            port.capture_fault(cleanup)
            if primary is not None:
                raise primary from cleanup
            raise cleanup


class ClosedProgram:
    """Full original bytes/AST, explicit closed bindings; never authorizes execution."""

    def __init__(self, port: PathPort) -> None:
        self.port = DriverPort(port)
        self.__executing = False
        try:
            self.raw = {name: source(name) for name in (PROBE, BASELINE)}
            self.code: dict[str, CodeType] = {}
            self.proof: dict[str, object] = {}
            for name, raw in self.raw.items():
                tree = ast.parse(raw)
                original = ast.dump(tree, include_attributes=True)
                anchor = next(
                    index
                    for index, node in enumerate(tree.body)
                    if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "root"
                )
                bindings = ast.parse(
                    "Path = _r27_path\ntempfile = _r27_tempfile\n"
                    "publish = _r27_publish\nrunpy = _r27_runpy\n_r27_ready()\n"
                ).body
                tree.body[anchor:anchor] = bindings
                restored = ast.Module(
                    body=[node for node in tree.body if node not in bindings],
                    type_ignores=tree.type_ignores,
                )
                if ast.dump(restored, include_attributes=True) != original:
                    raise ValueError("full original algorithm AST conservation")
                self.code[name] = compile(ast.fix_missing_locations(tree), str(ROOT / name), "exec")
                self.proof[name] = {
                    "source_sha256": digest(raw),
                    "original_ast_sha256": digest(original.encode()),
                    "algorithm_ast_unchanged": True,
                    "added_bindings": ["Path", "tempfile", "publish", "runpy"],
                    "added_readiness_call": "_r27_ready() before original root/effects",
                }
            main = function(ast.parse(self.raw[PROBE]), "main")
            if not isinstance(main, ast.AsyncFunctionDef):
                raise ValueError("full async original driver")
        except BaseException as error:
            port.capture_fault(error)
            raise

    def bindings(self) -> dict[str, object]:
        """Actual closed full-program namespace; creating it performs no imports/effects."""

        async def publish(
            root: RichPath,
            factory: async_sessionmaker[AsyncSession],
            owner: Subject,
            source_name: str,
            core: str,
        ) -> tuple[SOTReference, ...]:
            bridge = SeedBridge(self.port, os.environ["POSTGRES_DSN"])
            return await bridge.publish(root, factory, owner, source_name, core)

        return {
            "_r27_path": self.path,
            "_r27_tempfile": SimpleNamespace(TemporaryDirectory=self.temporary),
            "_r27_publish": publish,
            "_r27_runpy": SimpleNamespace(run_path=self.run_path),
            "_r27_ready": assert_logging_routes,
        }

    def run_path(self, filename: str, run_name: str = "__main__") -> dict[str, object]:
        """Nested original runpy endpoint, called only inside the guarded full entry."""
        if not self.__executing or filename != "/work/latency_probe.py" or run_name != "__main__":
            error = PermissionError(
                "closed nested source entry requires active admitted dispatcher"
            )
            self.port.capture_fault(error)
            raise error
        namespace = {"__name__": run_name, "__file__": str(ROOT / PROBE), **self.bindings()}
        exec(self.code[PROBE], namespace)
        if self.port.first_fault is not None:
            raise self.port.first_fault
        return namespace

    def _execute_original(self) -> None:
        """Fully wired entry, never called by this batch's DENY dispatcher."""
        self.dispatch()  # Every entry denies BEFORE imports/effects, including direct calls.
        old_argv, old_path = sys.argv, list(sys.path)
        codes = tuple(code for root in self.code.values() for code in code_objects(root))
        self.__executing = True
        try:
            sys.argv = [str(ROOT / BASELINE), self.port.path("run").logical_path, "off"]
            with logging_scope(self.port, codes):
                exec(
                    self.code[BASELINE],
                    {"__name__": "__main__", "__file__": str(ROOT / BASELINE), **self.bindings()},
                )
            if self.port.first_fault is not None:
                raise self.port.first_fault
        except BaseException as error:
            primary = self.port.first_fault or error
            if not source_oracle(self.port, primary, codes):
                self.port.capture_fault(primary)
            if primary is error:
                raise
            raise primary from error
        finally:
            self.__executing = False
            sys.argv = old_argv
            sys.path[:] = old_path

    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("httpx", "fastapi", "redis", "sqlalchemy", "asyncpg")
            if importlib.util.find_spec(name) is None
        )

    def path(self, value: object) -> RichPath:
        if isinstance(value, RichPath) and value.namespace == self.port.namespace:
            return value
        expected = self.port.path("run").logical_path
        if value == expected:
            return self.port.path("run")
        self.port.invalidate()
        raise ValueError("only declared opaque original driver root/temp")

    @contextmanager
    def temporary(self, *, prefix: str) -> Iterator[RichPath]:
        if prefix != "tip054-latency-source-":
            self.port.invalidate()
            raise ValueError("exact source temporary operation")
        root = self.port.path("tmp/seed", "ephemeral")
        root.mkdir(parents=True)
        try:
            yield root
        finally:
            primary = sys.exception()

            def remove(path: RichPath) -> None:
                for entry in path.iterdir():
                    if entry.is_dir():
                        remove(entry)
                    else:
                        entry.unlink()
                path.unlink()

            try:
                remove(root)
            except BaseException as error:
                self.port.capture_fault(error)
                if primary is not None:
                    raise primary from error
                raise

    def dispatch(self) -> None:
        missing = self.dependencies()
        if missing:
            raise RuntimeError("DENY before imports/SQL/HTTP: missing " + ",".join(missing))
        raise PermissionError("DENY: full runtime/effect/Linux/capacity authority not established")


def code_objects(root: CodeType) -> Iterator[CodeType]:
    yield root
    for value in root.co_consts:
        if isinstance(value, CodeType):
            yield from code_objects(value)


def cache_of(logger: logging.Logger) -> dict[int, bool]:
    value: object = vars(logger).get("_cache")
    if not isinstance(value, dict) or any(
        type(key) is not int or type(item) is not bool for key, item in value.items()
    ):
        raise ValueError("original logger cache shape")
    return cast(dict[int, bool], value)
