"""Four grouped genuine pytest/fileConfig controls; migration SQL is NOT_RUN."""

from __future__ import annotations

import io
import logging
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast

import pytest
from adapter import PacketError
from composition import HERE as REAL_PATH
from host import HostPort, OwnedBroker
from logging_seam import migration_logging_scope
from ports import PathPort
from pytest_seam import HERE, ROOT, installed_junit, pytest_scope


@contextmanager
def capture(faults: dict[str, str] | None = None) -> Iterator[tuple[OwnedBroker, HostPort, Path]]:
    with TemporaryDirectory(prefix=".closure-peer-", dir=REAL_PATH) as temporary:
        root = Path(temporary) / "capture"
        broker = OwnedBroker(root, faults)
        try:
            with HostPort(broker) as port:
                yield broker, port, root
            if broker.first_fault is None:
                assert broker.finish()["prototype_complete"]
        finally:
            broker.abandon()


def actual_pytest(port: PathPort, plugins: tuple[object, ...] = ()) -> int:
    with pytest_scope(port) as logical:
        return int(
            pytest.main(
                [
                    str(HERE / "plugin_target.py"),
                    "-c",
                    str(ROOT / "v2/apps/backend/pyproject.toml"),
                    "--confcutdir",
                    str(HERE),
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--junitxml",
                    logical,
                ],
                plugins=list(plugins),
            )
        )


@contextmanager
def legacy_handlers() -> Iterator[
    tuple[logging.Logger, list[logging.Handler], list[logging.Handler], list[logging.Handler]]
]:
    named = logging.getLogger("sqlalchemy.engine")
    root_before, named_before = logging.root.handlers, named.handlers
    extras: list[logging.Handler] = [
        logging.StreamHandler(io.StringIO()),
        logging.StreamHandler(io.StringIO()),
    ]
    logging.root.handlers = [*root_before, extras[0]]
    named.handlers = [*named_before, extras[1]]
    try:
        yield named, logging.root.handlers, named.handlers, extras
    finally:
        logging.root.handlers, named.handlers = root_before, named_before
        for handler in extras:
            handler.close()


def test_genuine_installed_pytest_plugin_whole_xml() -> None:
    module, code = installed_junit()
    old_os = vars(module)["os"]
    old_open = vars(module).get("open")
    with capture() as (broker, port, root):
        assert actual_pytest(port) == 0
        raw = port.read("plugins/report.xml")
        assert raw.startswith(b'<?xml version="1.0" encoding="utf-8"?>')
        xml = ET.fromstring(raw)
        cases = xml.findall(".//testcase")
        assert {case.attrib["name"] for case in cases} == {
            "test_original_off_scope_literal",
            "test_original_child_budget_body",
        }
        suite = xml.find("testsuite")
        assert suite is not None and suite.attrib["tests"] == "2"
        assert len(raw) <= 2048
        assert (root / "files/plugins/report.xml").read_bytes() == raw
        assert vars(module)["os"] is old_os and vars(module).get("open") is old_open
        assert module.LogXML.pytest_sessionfinish.__code__ is code
    # Capture helper closes its producer before broker completion in separate normal epoch.
    with TemporaryDirectory(prefix=".closure-peer-", dir=REAL_PATH) as temporary:
        broker = OwnedBroker(Path(temporary) / "capture")
        with HostPort(broker) as port:
            assert actual_pytest(port) == 0
        recovered = broker.finish()
        records = [
            record
            for record in recovered["records"]
            if record[0] == "source_cap_child" and record[1] == 1
        ]
        assert (
            len(records) == 2
        )  # One whole XML, plus the separately charged final manifest marker.
        assert records[0][3].startswith(b'<?xml version="1.0" encoding="utf-8"?>')
        assert records[1][3].startswith(b"BROKER-MANIFEST:")
        assert recovered["prototype_complete"]


def test_xml_oversize_unknown_empty_and_serialization_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from _pytest import junitxml

    class Oversize:
        def pytest_sessionstart(self, session: pytest.Session) -> None:
            session.config.stash[junitxml.xml_key].add_global_property("oversize", "x" * 2049)

    with capture() as (broker, port, root):
        with pytest.raises(ValueError, match="XML"):
            actual_pytest(port, (Oversize(),))
        assert not (root / "files/plugins/report.xml").exists()
        with pytest.raises(PacketError, match="sticky incomplete"):
            broker.finish()
    for mode in ("empty", "unknown", "serialize"):
        with capture() as (broker, port, root):
            original = LookupError("original serialization fault")
            with (
                pytest.raises(ValueError if mode != "serialize" else LookupError) as caught,
                pytest_scope(port) as logical,
            ):
                if mode == "unknown":
                    opener = cast(object, vars(junitxml)["open"])
                    if callable(opener):
                        opener(logical, "w", encoding="utf-8")
                elif mode == "serialize":

                    def fail(
                        *args: object, failure: LookupError = original, **kwargs: object
                    ) -> str:
                        raise failure

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            junitxml, "ET", SimpleNamespace(Element=ET.Element, tostring=fail)
                        )
                        plugin = junitxml.LogXML(logical, None)
                        plugin.pytest_sessionstart()
                        plugin.pytest_sessionfinish()
            if mode == "serialize":
                assert caught.value is original and port.first_fault is original
            assert not (root / "files/plugins/report.xml").exists()
            with pytest.raises(PacketError, match="sticky incomplete"):
                broker.finish()


def test_genuine_fileconfig_formatter_registry_and_alias_restore() -> None:
    root_handlers = logging.root.handlers
    named = logging.getLogger("sqlalchemy.engine")
    named_handlers = named.handlers
    prior_root = logging.StreamHandler(io.StringIO())
    prior_named = logging.StreamHandler(io.StringIO())
    logging.root.handlers = [*root_handlers, prior_root]
    named.handlers = [*named_handlers, prior_named]
    root_alias, named_alias = logging.root.handlers, named.handlers
    root_filter, named_filter = logging.root.filters, named.filters
    root_cache, named_cache = vars(logging.root)["_cache"], vars(named)["_cache"]
    cache_contents = dict(root_cache), dict(named_cache)
    states = (
        logging.root.level,
        logging.root.propagate,
        logging.root.disabled,
        named.level,
        named.propagate,
        named.disabled,
    )
    filter_contents = tuple(root_filter), tuple(named_filter)
    registry, references = vars(logging)["_handlers"], vars(logging)["_handlerList"]
    old_stdout, old_stderr = sys.stdout, sys.stderr
    disable = logging.root.manager.disable
    try:
        with capture() as (broker, port, root):
            with migration_logging_scope(port) as console:
                assert type(console) is logging.StreamHandler
                assert console.formatter is not None
                logging.warning("root control")
                logging.getLogger("alembic").info("migration control")
                logging.getLogger("sqlalchemy.engine").info("suppressed by genuine ini")
                cold = logging.getLogger("r27-closure-cold")
                assert (
                    port.read("streams/migration.stderr")
                    == b"WARNI [root] root control\nINFO  [alembic] migration control\n"
                )
                logging.root.manager.disable = 99
            assert logging.getLogger("r27-closure-cold") is cold and cold.level == logging.NOTSET
            assert logging.root.handlers is root_alias and prior_root in root_alias
            assert named.handlers is named_alias and prior_named in named_alias
            assert logging.root.filters is root_filter and named.filters is named_filter
            assert (
                vars(logging.root)["_cache"] is root_cache and vars(named)["_cache"] is named_cache
            )
            assert (dict(root_cache), dict(named_cache)) == cache_contents
            assert (tuple(root_filter), tuple(named_filter)) == filter_contents
            assert (
                logging.root.level,
                logging.root.propagate,
                logging.root.disabled,
                named.level,
                named.propagate,
                named.disabled,
            ) == states
            assert (
                vars(logging)["_handlers"] is registry
                and vars(logging)["_handlerList"] is references
            )
            assert not vars(prior_root)["_closed"] and not vars(prior_named)["_closed"]
            assert logging.root.manager.disable == disable
            assert sys.stdout is old_stdout and sys.stderr is old_stderr
    finally:
        logging.root.handlers, named.handlers = root_handlers, named_handlers
        prior_root.close()
        prior_named.close()


def test_fileconfig_faults_primary_cleanup_and_shared_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from composition import logging_scope

    for mode in ("oversize", "native", "extra", "storage", "cleanup", "nested"):
        with (
            capture({"native_write": "raise"} if mode == "storage" else None) as (
                broker,
                port,
                root,
            ),
            legacy_handlers() as (named, root_alias, named_alias, extras),
        ):
            handlers = logging.root.handlers
            contents = list(root_alias), list(named_alias)
            states = (
                logging.root.level,
                logging.root.propagate,
                logging.root.disabled,
                named.level,
                named.propagate,
                named.disabled,
            )
            root_cache, named_cache = vars(logging.root)["_cache"], vars(named)["_cache"]
            cache_contents = dict(root_cache), dict(named_cache)
            filters = logging.root.filters, named.filters
            filter_contents = tuple(filters[0]), tuple(filters[1])
            registry, references = vars(logging)["_handlers"], vars(logging)["_handlerList"]
            stdout, stderr = sys.stdout, sys.stderr
            primary = LookupError("body primary")
            cleanup = OSError("fresh console close fault")
            with pytest.raises(Exception) as caught, migration_logging_scope(port) as console:
                if mode == "oversize":
                    with suppress(Exception):
                        logging.warning("x" * 513)
                elif mode == "native":
                    sys.stderr.write("unsupported raw traceback/warning")
                elif mode == "extra":
                    logging.root.addHandler(logging.StreamHandler())
                elif mode == "storage":
                    logging.warning("genuine emit storage fault")
                elif mode == "cleanup":

                    def fail_close(error: OSError = cleanup) -> None:
                        raise error

                    monkeypatch.setattr(console, "close", fail_close)
                    raise primary
                else:
                    with logging_scope(port):
                        pass
            if mode == "cleanup":
                assert caught.value is primary and caught.value.__cause__ is cleanup
            assert port.first_fault is not None
            assert logging.root.handlers is handlers
            assert logging.root.handlers is root_alias and named.handlers is named_alias
            assert (list(root_alias), list(named_alias)) == contents
            assert not any(vars(handler)["_closed"] for handler in extras)
            assert (
                vars(logging.root)["_cache"] is root_cache and vars(named)["_cache"] is named_cache
            )
            assert (dict(root_cache), dict(named_cache)) == cache_contents
            assert logging.root.filters is filters[0] and named.filters is filters[1]
            assert (tuple(filters[0]), tuple(filters[1])) == filter_contents
            assert (
                logging.root.level,
                logging.root.propagate,
                logging.root.disabled,
                named.level,
                named.propagate,
                named.disabled,
            ) == states
            assert (
                vars(logging)["_handlers"] is registry
                and vars(logging)["_handlerList"] is references
            )
            assert sys.stdout is stdout and sys.stderr is stderr
            if mode in {"oversize", "native", "extra", "cleanup", "nested"}:
                assert not (root / "files/streams/migration.stderr").exists()
            with pytest.raises(PacketError, match="sticky incomplete"):
                broker.finish()
