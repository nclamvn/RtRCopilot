"""Pinned genuine bodies, rebound only in private producer namespaces."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
import weakref
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType
from typing import cast

import bridge
import native
import policy
import source_run


def selected(path: Path, names: set[str], namespace: dict[str, object]) -> None:
    tree = ast.parse(bridge.bounded(path))
    nodes = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names
    ]
    if {n.name for n in nodes} != names:
        raise ValueError("exact selected genuine source bodies")
    module = ast.Module(
        [ast.ImportFrom("__future__", [ast.alias("annotations")], 0), *nodes], []
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)


class XMLSink(io.StringIO):
    def __init__(self, owner: native.Owner) -> None:
        super().__init__()
        self.owner = owner
        self.parts = owner.buffers["reports/result.xml"]

    def write(self, text: str) -> int:
        raw = text.encode()
        self.owner.capture("reports/result.xml", raw)
        if len(self.parts) == 2 and self.owner.faults.get("xml_source") == (
            "after_first",
            False,
        ):
            self.owner.event(
                "xml_source",
                "reports/result.xml",
                lambda: None,
                args="second genuine XML write producer-error control",
            )
        returned = super().write(text)
        item = self.owner.captures["reports/result.xml"]
        item["accepted_bytes"] = cast(int, item.get("accepted_bytes", 0)) + len(raw)
        return returned

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if kind is not None and self.owner.first_fault is None:
            self.owner.first_fault = error
            self.owner.packet.flags |= 1
        try:
            self.owner.finalize_capture("reports/result.xml")
        except BaseException as cleanup_error:
            self.owner.cleanup_errors.append(str(cleanup_error))
            if kind is None:
                raise
        super().__exit__(kind, error, trace)


class Composition:
    def __init__(self, owner: native.Owner) -> None:
        policy.guard()
        self.owner = owner
        private_sys = SimpleNamespace(
            platform=sys.platform,
            version_info=sys.version_info,
            getfilesystemencoding=sys.getfilesystemencoding,
            audit=owner.audit,
        )
        shutil_ns: dict[str, object] = {
            **vars(shutil),
            "os": owner.os,
            "sys": private_sys,
        }
        selected(policy.PYTHON / "shutil.py", {"rmtree", "_rmtree_safe_fd"}, shutil_ns)
        shutil_ns["_use_fd_functions"] = getattr(shutil, "_use_fd_functions")
        original_rmtree = cast(Callable[..., object], shutil_ns["rmtree"])

        def cleanup(*args: object, **kwargs: object) -> object:
            prior = owner.cleanup_phase
            owner.cleanup_phase = True
            try:
                return original_rmtree(*args, **kwargs)
            finally:
                owner.cleanup_phase = prior

        self.shutil = native.Namespace(owner, rmtree=cleanup)

        def finalize(*args: object, **kwargs: object) -> object:
            owner.guard()
            owner.finalized_objects.append(args[0])
            result = cast(Callable[..., object], weakref.finalize)(*args, **kwargs)
            owner.finalizers.append(result)
            owner.check_metadata()
            return result

        temp_ns: dict[str, object] = {
            **vars(tempfile),
            "_os": owner.os,
            "_sys": private_sys,
            "_shutil": self.shutil,
            "_weakref": SimpleNamespace(finalize=finalize),
            "_warnings": SimpleNamespace(warn=owner.warning),
            "tempdir": None,
            "_name_sequence": None,
        }

        def bytes_denied() -> object:
            owner.fail(
                PermissionError("bytes tempfile candidate discovery is unqualified")
            )

        temp_ns["gettempdirb"] = bytes_denied
        selected(
            policy.PYTHON / "tempfile.py",
            {
                "_infer_return_type",
                "_sanitize_params",
                "_get_candidate_names",
                "_candidate_tempdir_list",
                "_get_default_tempdir",
                "_gettempdir",
                "gettempdir",
                "gettempprefix",
                "mkdtemp",
                "_dont_follow_symlinks",
                "_resetperms",
                "TemporaryDirectory",
            },
            temp_ns,
        )
        self.tempfile = native.Namespace(
            owner,
            **{
                n: temp_ns[n]
                for n in ("TemporaryDirectory", "mkdtemp", "gettempdir", "_resetperms")
            },
        )
        import _pytest.pathlib as installed_pathlib

        path_ns: dict[str, object] = {
            **vars(installed_pathlib),
            "os": owner.os,
            "Path": owner.path,
            "shutil": self.shutil,
            "warnings": SimpleNamespace(warn=owner.warning),
        }
        selected(
            policy.PYTEST / "pathlib.py",
            {
                "on_rm_rf_error",
                "ensure_extended_length_path",
                "rm_rf",
                "find_prefixed",
                "extract_suffixes",
                "find_suffixes",
                "parse_num",
                "_force_symlink",
                "make_numbered_dir",
                "cleanup_dead_symlinks",
            },
            path_ns,
        )
        self.pathlib = SimpleNamespace(
            **{
                n: path_ns[n]
                for n in (
                    "rm_rf",
                    "make_numbered_dir",
                    "cleanup_dead_symlinks",
                    "on_rm_rf_error",
                )
            }
        )

    def case(self) -> unittest.TestCase:
        source = bridge.AREA / "r21/qualification.py"
        spec = importlib.util.spec_from_file_location(
            "r27_lifecycle_readonly_r21", source
        )
        if spec is None or spec.loader is None:
            raise ValueError("genuine original validator loader")
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        prior = SimpleNamespace(**vars(original.prior))
        r18 = SimpleNamespace(**vars(original.prior.r18))
        prior.r18 = r18
        prior.load_json = source_run.functions(
            bridge.AREA / "r19/qualification.py",
            {"load_json"},
            {**vars(original.prior), "Path": self.owner.path},
        )["load_json"]
        r18.child_record = source_run.functions(
            bridge.AREA / "r18/gate.py",
            {"child_record"},
            {**vars(original.prior.r18), "Path": self.owner.path},
        )["child_record"]
        gate_ns = {**vars(original), "Path": self.owner.path, "prior": prior}
        methods = source_run.functions(
            source, {"marker", "journal_rows", "packet", "analyze"}, gate_ns
        )
        gate = SimpleNamespace(**{**vars(original), **methods, "prior": prior})
        path = bridge.AREA / "r21/test_r21_offline.py"
        cls = next(
            n
            for n in ast.parse(bridge.bounded(path)).body
            if isinstance(n, ast.ClassDef)
        )
        keep = {
            "setUp",
            "rows",
            "write_packet",
            "test_packet_summary_controls_oracle_and_corruption",
        }
        cls.body = [
            n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in keep
        ]
        if {n.name for n in cls.body if isinstance(n, ast.FunctionDef)} != keep:
            raise ValueError("unchanged setup/body/cleanup source selection")
        namespace: dict[str, object] = {
            "unittest": unittest,
            "tempfile": self.tempfile,
            "Path": self.owner.path,
            "gate": gate,
            "json": json,
            "__name__": "r27_lifecycle_original_case",
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module([cls], [])), str(path), "exec"
            ),
            namespace,
        )
        factory = cast(Callable[..., unittest.TestCase], namespace[cls.name])
        return factory("test_packet_summary_controls_oracle_and_corruption")

    def plugins(self) -> tuple[ModuleType, ModuleType, list[XMLSink]]:
        import _pytest.tmpdir as installed_tmpdir
        import _pytest.junitxml as installed_junit

        temp_ns: dict[str, object] = {
            **vars(installed_tmpdir),
            "os": self.owner.os,
            "Path": self.owner.path,
            "tempfile": self.tempfile,
            "rmtree": self.shutil.rmtree,
            "rm_rf": self.pathlib.rm_rf,
            "make_numbered_dir": self.pathlib.make_numbered_dir,
            "cleanup_dead_symlinks": self.pathlib.cleanup_dead_symlinks,
        }

        def deny(*args: object, **kwargs: object) -> object:
            self.owner.fail(
                PermissionError(
                    "default pytest lock/garbage lifecycle remains unqualified"
                )
            )

        temp_ns["make_numbered_dir_with_cleanup"] = deny
        selected(
            policy.PYTEST / "tmpdir.py",
            {
                "TempPathFactory",
                "pytest_configure",
                "pytest_addoption",
                "tmp_path_factory",
                "_mk_tmp",
                "tmp_path",
                "pytest_sessionfinish",
                "pytest_runtest_makereport",
            },
            temp_ns,
        )
        tmp_plugin = ModuleType("r27_private_tmpdir")
        tmp_plugin.__dict__.update(
            {
                n: temp_ns[n]
                for n in (
                    "pytest_configure",
                    "pytest_addoption",
                    "tmp_path_factory",
                    "tmp_path",
                    "pytest_sessionfinish",
                    "pytest_runtest_makereport",
                )
            }
        )
        configure = cast(Callable[..., object], temp_ns["pytest_configure"])

        def configured(config: object) -> object:
            option = getattr(config, "option")
            if getattr(option, "basetemp") is not None:
                self.owner.fail(
                    PermissionError("general CLI basetemp validation is unqualified")
                )
            option.basetemp = str(native.CapPath(self.owner, "pytest-base"))
            return configure(config)

        tmp_plugin.__dict__["pytest_configure"] = configured
        sinks: list[XMLSink] = []

        def opener(path: object, mode: str, *, encoding: str) -> XMLSink:
            if (
                self.owner.name(path) != "reports/result.xml"
                or mode != "w"
                or encoding != "utf-8"
                or sinks
            ):
                self.owner.fail(
                    PermissionError("one declared genuine JUnit whole output")
                )
            sink = XMLSink(self.owner)
            sinks.append(sink)
            return sink

        junit_os = SimpleNamespace(**vars(self.owner.os))
        junit_os.makedirs = lambda p, exist_ok=False: self.owner.path(p).mkdir(
            parents=True, exist_ok=exist_ok
        )
        junit_ns: dict[str, object] = {
            **vars(installed_junit),
            "os": junit_os,
            "open": opener,
        }
        selected(
            policy.PYTEST / "junitxml.py",
            {"LogXML", "pytest_addoption", "pytest_configure", "pytest_unconfigure"},
            junit_ns,
        )
        junit_plugin = ModuleType("r27_private_junitxml")
        junit_plugin.__dict__.update(
            {
                n: junit_ns[n]
                for n in ("pytest_addoption", "pytest_configure", "pytest_unconfigure")
            }
        )
        xml_configure = cast(Callable[..., object], junit_ns["pytest_configure"])

        def configured_xml(config: object) -> object:
            option = getattr(config, "option")
            if getattr(option, "xmlpath") is not None:
                self.owner.fail(
                    PermissionError(
                        "general CLI JUnit filename validation is unqualified"
                    )
                )
            option.xmlpath = str(native.CapPath(self.owner, "reports/result.xml"))
            return xml_configure(config)

        junit_plugin.__dict__["pytest_configure"] = configured_xml
        return tmp_plugin, junit_plugin, sinks
