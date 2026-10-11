"""Pinned original output producer blocks, never the driver/main/request workload."""

import ast
import hashlib
import importlib
import importlib.util
import json
import math
import sys
from pathlib import Path

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


def read_source(name):
    path = ROOT / name
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("source symlink")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCES[name]:
        raise ValueError("producer source drift")
    return raw.decode(), ast.parse(raw)


def function(name, arguments, body):
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


def prepared():
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
    nodes = [
        quantile,
        function("source_summary", ("records", "root"), summary),
        function("source_final", ("records", "root"), [final]),
    ]
    namespace = {"json": json, "math": math}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
            driver + "#output-producers",
            "exec",
        ),
        namespace,
    )
    witnesses = {
        name: hashlib.sha256(ast.get_source_segment(text, node).encode()).hexdigest()
        for name, node in (("retain", retain), ("final_samples", final))
    }
    witnesses["summary_nodes"] = hashlib.sha256(
        "".join(ast.get_source_segment(text, node) for node in summary).encode()
    ).hexdigest()
    return retain, namespace, witnesses


class DriverOutputs:
    def __init__(self, capture):
        self.capture = capture
        self.retain_node, self.namespace, self.witnesses = prepared()

    def journal(self, records, observations):
        namespace = {"json": json, "records": records, "observations": observations}
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[self.retain_node], type_ignores=[])),
                "latency_probe.py#retain",
                "exec",
            ),
            namespace,
        )
        original = namespace["retain"]

        def retain(record):
            try:
                return original(record)
            except BaseException:
                self.capture.invalidate()
                raise

        return retain

    def finish(self, records, root):
        original = None
        try:
            try:
                self.namespace["source_summary"](records, root)
            except BaseException as error:
                original = error
            try:
                # Exact final producer block, also attempted after a primary oracle failure.
                self.namespace["source_final"](records, root)
            except BaseException as cleanup:
                if original is not None:
                    raise original from cleanup
                raise
            if original is not None:
                raise original
        except BaseException:
            self.capture.invalidate()
            raise


def audit_producer(capture):
    name = "v2/apps/backend/src/rtr_copilot/auth/audit.py"
    read_source(name)
    module = importlib.import_module("rtr_copilot.auth.audit")
    if Path(module.__file__).resolve() != ROOT / name:
        raise ValueError("audit module identity")
    capture.attach_logger(module.audit_logger)
    sink = module.StructuredAuditSink()

    def emit(**fields):
        try:
            event = module.AuditEvent(**fields)
            sink.emit(event)
            return event
        except BaseException:
            capture.invalidate()
            raise

    return emit, module.audit_logger


def fixture_producer(capture):
    name = "v2/apps/backend/tests/sot_fixtures.py"
    read_source(name)
    for dependency in (
        "v2/apps/backend/src/rtr_copilot/sot/package.py",
        "v2/apps/backend/src/rtr_copilot/sot/models.py",
    ):
        read_source(dependency)
    spec = importlib.util.spec_from_file_location("r27_retention_fixture_source", ROOT / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if Path(module.build_package.__code__.co_filename).resolve() != ROOT / name:
        raise ValueError("fixture function identity")
    for dependency in ("rtr_copilot.sot.package", "rtr_copilot.sot.models"):
        path = Path(sys.modules[dependency].__file__).resolve().relative_to(ROOT).as_posix()
        read_source(path)

    def build(*args, **kwargs):
        try:
            return module.build_package(*args, **kwargs)
        except BaseException:
            capture.invalidate()
            raise

    return build, module


def request_class():
    name = "v2/apps/backend/src/rtr_copilot/actions/request_connection.py"
    read_source(name)
    module = importlib.import_module("rtr_copilot.actions.request_connection")
    if Path(module.__file__).resolve() != ROOT / name:
        raise ValueError("request class identity")
    return module.RequestConnection
