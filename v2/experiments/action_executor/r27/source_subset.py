"""Hash-bound execution of three exact source functions, not product module import."""

import ast
import asyncio
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).absolute().parents[4]
REQUEST = "v2/apps/backend/src/rtr_copilot/actions/request_connection.py"
DRIVER = "v2/experiments/action_executor/latency_probe.py"
EXPECTED = {
    REQUEST: "c56d7b09a9845cfe23e4f580849f355c32a40366fd6abc22260f8e85210b93d0",
    DRIVER: "e94a79a6b0f1695a23db07bfb5f12d5e5746f898893de9cf11cbb6527d6d4ad2",
}
METHODS = {
    "check_owner": "7aae58c2755684b8ee240acf3fb7652ba613fd40a0cf6a9b138c41f5be56eff5",
    "join_terminal": "d68df5f17d64c6f13c0bd8502b5bb9a7573d397971994e85e18b8d993b25370e",
}


def selected(path):
    data = (ROOT / path).read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED[path]:
        raise ValueError("source subset fingerprint drift")
    return data.decode(), ast.parse(data)


def owner_probe():
    text, tree = selected(REQUEST)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RequestConnection")
    methods = [n for n in owner.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in METHODS]
    if {n.name for n in methods} != set(METHODS):
        raise ValueError("subset method set")
    for node in methods:
        if hashlib.sha256(ast.get_source_segment(text, node).encode()).hexdigest() != METHODS[node.name]:
            raise ValueError("subset method changed")
    cls = ast.ClassDef(name="TerminalSubset", bases=[], keywords=[], body=methods,
                       decorator_list=[], type_params=[])
    body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls]
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace = {"asyncio": asyncio}
    exec(compile(module, REQUEST + "#terminal-subset", "exec"), namespace)
    probe = namespace["TerminalSubset"]()
    probe.task, probe.terminal_task, probe.poisoned = asyncio.current_task(), None, False
    return probe


def retain_function(records, observations):
    text, tree = selected(DRIVER)
    main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    retain = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "retain")
    method_sha = hashlib.sha256(ast.get_source_segment(text, retain).encode()).hexdigest()
    if method_sha != "4b544a4071af672b5cd8a0555ccbc4a34b0c11cfc7a53eac124b504296655902":
        raise ValueError("retain method changed")
    # Full driver hash protects this nested AST and its exact append/write/flush order.
    namespace = {"records": records, "observations": observations, "json": json}
    module = ast.fix_missing_locations(ast.Module(body=[retain], type_ignores=[]))
    exec(compile(module, DRIVER + "#retain-subset", "exec"), namespace)
    return namespace["retain"], method_sha
