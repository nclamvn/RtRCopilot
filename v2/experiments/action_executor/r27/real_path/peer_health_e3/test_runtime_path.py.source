"""Six grouped actual safe controls; no SQL/HTTP/native campaign execution."""

from __future__ import annotations

import ast
import json
import logging
import sys
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import pytest
from adapter import PacketError
from composition import (
    HERE,
    PROBE,
    ROOT,
    ClosedProgram,
    DriverPort,
    RefreshingParser,
    RenderedHandler,
    SeedBridge,
    actual_module,
    assert_logging_routes,
    code_objects,
    logging_scope,
    source,
)
from controller import DSN, Controller, full_ast_proof
from host import HostPort, OwnedBroker
from ports import RichPath
from routing import ledger


def test_full_driver_bindings_and_prerequisite_deny() -> None:
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            program = ClosedProgram(port)
            assert set(program.bindings()) == {
                "_r27_path",
                "_r27_tempfile",
                "_r27_publish",
                "_r27_runpy",
                "_r27_ready",
            }
            assert all(
                proof["algorithm_ast_unchanged"]
                for proof in (cast(dict[str, object], item) for item in program.proof.values())
            )
            assert "httpx" in program.dependencies()
            with pytest.raises(RuntimeError, match="before imports/SQL/HTTP"):
                program.dispatch()
            with pytest.raises(RuntimeError, match="before imports/SQL/HTTP"):
                program._execute_original()
            assert len(cast(list[object], ledger()["families"])) == 20
            assert full_ast_proof()["group_execution"] == "NOT_RUN"
        assert broker.finish()["prototype_complete"]

    for kind in ("cache", "native", "new-handler"):
        with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
            broker = OwnedBroker(Path(temporary) / "capture")
            with HostPort(broker) as port:
                root_handlers = logging.root.handlers
                cache = vars(logging.root)["_cache"]
                logging.root.handlers = []
                try:
                    if kind == "cache":
                        vars(logging.root)["_cache"] = object()
                    with pytest.raises(ValueError), logging_scope(port):
                        if kind == "native":
                            sys.stderr.write("unframed control")
                        elif kind == "new-handler":
                            logging.getLogger("r27-local-explicit").addHandler(
                                logging.StreamHandler()
                            )
                            assert_logging_routes()
                finally:
                    logging.root.handlers = root_handlers
                    vars(logging.root)["_cache"] = cache
            with pytest.raises(PacketError, match="sticky incomplete"):
                broker.finish()
            broker.abandon()


def test_original_fixture_parser_and_constructor_storage_only() -> None:
    from rtr_copilot.sot.package import (
        PackageError,
        PackageParser,
        sign_attestation,
        verify_attestation,
    )
    from rtr_copilot.sot.service import SOTPublishService
    from sqlalchemy.ext.asyncio import async_sessionmaker

    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            driver = DriverPort(port)
            seed = SeedBridge(driver, DSN)
            root = driver.path("tmp/seed")
            root.mkdir(parents=True)
            build = cast(Callable[[Path], Path], seed.fixture_build)
            package = cast(RichPath, build(cast(Path, root)))
            parsed = RefreshingParser(root).parse(package.name)
            assert len(parsed.records) == 1
            curator = str(parsed.attestation.curator_subject_id)
            verify_attestation(parsed, secret=seed.secret, curator_id=curator, now=seed.now)
            bad_signature = parsed.model_copy(
                update={
                    "attestation": parsed.attestation.model_copy(update={"signature": "0" * 64})
                }
            )
            with pytest.raises(PackageError, match="attestation_signature_invalid"):
                verify_attestation(
                    bad_signature, secret=seed.secret, curator_id=curator, now=seed.now
                )
            expired = parsed.attestation.model_copy(update={"expires_at": seed.now})
            expired.signature = sign_attestation(expired.model_dump(mode="json"), seed.secret)
            with pytest.raises(PackageError, match="attestation_expired"):
                verify_attestation(
                    parsed.model_copy(update={"attestation": expired}),
                    secret=seed.secret,
                    curator_id=curator,
                    now=seed.now,
                )
            with pytest.raises(PackageError, match="attestation_curator_mismatch"):
                verify_attestation(parsed, secret=seed.secret, curator_id="wrong", now=seed.now)
            factory = async_sessionmaker(expire_on_commit=False)
            settings = seed.settings(root)
            original = SOTPublishService(settings, factory=factory, clock=lambda: seed.now)
            assert type(original.parser) is PackageParser
            service = seed.publisher(settings, factory=factory, clock=lambda: seed.now)
            assert type(service) is SOTPublishService and service.uow.factory is factory
            for name in ("stage", "validate", "publish"):
                assert getattr(service, name).__func__ is getattr(SOTPublishService, name)
            assert type(cast(object, service.parser)) is RefreshingParser
            assert service.parser.parse(package.name).manifest == parsed.manifest
            assert str(settings.sot_staging_root) == root.logical_path
        assert broker.finish()["prototype_complete"]


def test_parser_rejects_real_corrupt_and_unsafe_members() -> None:
    from rtr_copilot.sot.models import PackageRecord
    from rtr_copilot.sot.package import PackageError, PackageParser

    for mutation in ("corrupt", "extra", "missing", "unsafe"):
        with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
            broker = OwnedBroker(Path(temporary) / "capture")
            with HostPort(broker) as port:
                driver = DriverPort(port)
                seed = SeedBridge(driver, DSN)
                root = driver.path("tmp/seed")
                root.mkdir(parents=True)
                build = cast(Callable[[Path], Path], seed.fixture_build)
                package = cast(RichPath, build(cast(Path, root)))
                actual = PackageParser(cast(Path, root.snapshot()))
                assert actual.max_lines == 100_000 and actual.max_line_bytes == 1_000_000
                # Explicit lower-bound parameter controls, never changed production defaults.
                if mutation == "corrupt":
                    with pytest.raises(PackageError, match="line_count_exceeded"):
                        PackageParser(cast(Path, root.snapshot()), max_lines=0)._json_lines(
                            cast(Path, package / "records.jsonl"), PackageRecord
                        )
                    with pytest.raises(PackageError, match="line_oversized"):
                        PackageParser(cast(Path, root.snapshot()), max_line_bytes=1)._json_lines(
                            cast(Path, package / "records.jsonl"), PackageRecord
                        )
                if mutation == "corrupt":
                    (package / "records.jsonl").write_bytes(b"{}\n")
                    with pytest.raises(PackageError, match="member_schema_invalid"):
                        PackageParser(cast(Path, root.snapshot()))._json_lines(
                            cast(Path, package / "records.jsonl"), PackageRecord
                        )
                elif mutation == "extra":
                    (package / "extra").write_bytes(b"extra")
                elif mutation == "missing":
                    (package / "records.jsonl").unlink()
                with pytest.raises(PackageError):
                    RefreshingParser(root).parse(
                        "../outside" if mutation == "unsafe" else package.name
                    )
            assert broker.finish()["prototype_complete"]


def test_whole_logging_and_cold_identity_restoration() -> None:
    logger = logging.getLogger("r27-local-existing")
    old_handlers, old_filters = logger.handlers, logger.filters
    old_cache = vars(logger)["_cache"]
    old_stdout, old_stderr = sys.stdout, sys.stderr
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            # Pytest capture handlers are not original runtime handlers; isolate this control.
            root_handlers = logging.root.handlers
            logging.root.handlers = []
            try:
                with logging_scope(port):
                    cold = logging.getLogger("r27-local-cold")
                    cold.info("whole %s", "record")
                    logging.getLogger("httpx").info("HTTP-style rendered control")
                    actual_module(
                        "rtr_copilot.auth.audit", "v2/apps/backend/src/rtr_copilot/auth/audit.py"
                    )
                    from rtr_copilot.auth.audit import AuditEvent, StructuredAuditSink

                    event = AuditEvent(
                        actor_id=None,
                        action="local",
                        result="control",
                        reason="whole",
                        request_id="local-control",
                        timestamp=datetime(2026, 10, 10, tzinfo=UTC),
                    )
                    StructuredAuditSink().emit(event)
                    assert (
                        port.read("streams/load_stderr")
                        == b"whole record\nHTTP-style rendered control\n"
                        + json.dumps(event.model_dump(mode="json"), sort_keys=True).encode()
                        + b"\n"
                    )
                assert logging.getLogger("r27-local-cold") is cold
                assert cold.handlers == [] and cold.level == logging.NOTSET
            finally:
                logging.root.handlers = root_handlers
            assert logger.handlers is old_handlers and logger.filters is old_filters
            assert vars(logger)["_cache"] is old_cache
            assert sys.stdout is old_stdout and sys.stderr is old_stderr
        assert broker.finish()["prototype_complete"]


def test_original_oracle_and_caught_logger_fault_identity() -> None:
    tree = ast.parse(source(PROBE))
    main = next(
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    # Exact genuine source writer/oracle block; static local control cell, NOT HTTP observations.
    block = next(node for node in ast.walk(main) if isinstance(node, ast.Try))
    start = next(
        index
        for index, node in enumerate(block.body)
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "report"
    )
    statements = block.body[start:]
    final = next(
        node
        for node in block.finalbody
        if isinstance(node, ast.Expr) and "samples.json" in ast.unparse(node)
    )
    module = ast.Module(body=[final, *statements], type_ignores=[])
    code = compile(ast.fix_missing_locations(module), str(ROOT / PROBE), "exec")
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            driver = DriverPort(port)
            root = driver.path("run")
            root.mkdir()
            previous = logging.root.handlers
            logging.root.handlers = []
            try:
                with (
                    pytest.raises(SystemExit) as captured,
                    logging_scope(driver, tuple(code_objects(code))),
                ):
                    exec(
                        code,
                        {"root": root, "json": json, "records": [], "cells": [{"pass": False}]},
                    )
                assert captured.value.code == 1 and driver.first_fault is None
            finally:
                logging.root.handlers = previous
        assert broker.finish()["prototype_complete"]
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            prior = logging.root.handlers
            logging.root.handlers = []
            try:
                with (
                    pytest.raises(SystemExit) as unknown,
                    logging_scope(port, tuple(code_objects(code))),
                ):
                    raise SystemExit(1)  # NOT the source-bound original oracle point.
                assert port.first_fault is unknown.value
            finally:
                logging.root.handlers = prior
        with pytest.raises(PacketError, match="sticky incomplete"):
            broker.finish()
        broker.abandon()
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            root_handlers = logging.root.handlers
            logging.root.handlers = []
            original = ValueError("formatter primary")

            class FaultFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    raise original

            try:
                with pytest.raises(ValueError) as caught, logging_scope(port):
                    handler = cast(RenderedHandler, logging.root.handlers[0])
                    handler.setFormatter(FaultFormatter())
                    with suppress(Exception):
                        logging.info("caught by original request-style except Exception")
                assert caught.value is original and port.first_fault is original
            finally:
                logging.root.handlers = root_handlers
        with pytest.raises(PacketError, match="sticky incomplete"):
            broker.finish()
        broker.abandon()


def test_actual_controller_copy_literal_marker_and_deadline() -> None:
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            controller = Controller(port)
            controller.copy_sources()
            assert port.read("controller/binding.json") == source(
                "v2/experiments/action_executor/r21/source-binding-e1.json"
            )
            assert b"observer OFF" in controller.scope_literal()
            controller.returncode("syntax", 0)
            controller.marker_control("a" * 64)
            owner: dict[str, object] = {"cleanup_deadline": None}
            first = controller.cleanup_deadline(owner)
            assert controller.cleanup_deadline(owner) == first
            assert json.loads(port.read("owner/load.owner.json"))["cleanup_deadline"] == first
            with pytest.raises(PermissionError):
                controller.dispatch(("/usr/bin/docker", "exec"))
            assert controller.prepared()["effects"] == "DENY_THIS_BATCH"
        assert broker.finish()["prototype_complete"]
    with TemporaryDirectory(prefix="peer-control-", dir=HERE) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            controller = Controller(port)
            controller.marker_control("b" * 64)
            before = broker.charge
            with pytest.raises(FileExistsError):
                controller.marker_control("b" * 64)
            assert broker.charge == before
        with pytest.raises(PacketError, match="sticky incomplete"):
            broker.finish()
        broker.abandon()
