"""New prototype tests plus hash-only traversal of explicitly linked prior inputs."""

import hashlib
import io
import json
import time
import unittest
from pathlib import Path

import adapter
import test_adapter

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[3]
BASE = "v2/experiments/action_executor/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    path = Path(name)
    adapter.need(not path.is_absolute() and ".." not in path.parts and name == path.as_posix(), "input path")
    adapter.need(not any((ROOT / Path(*path.parts[:i])).is_symlink()
                         for i in range(1, len(path.parts) + 1)), "input symlink")
    adapter.need((ROOT / path).stat().st_size <= 33554432, "input cap")
    return (ROOT / path).read_bytes()


def preserve():
    binding = json.loads((HERE / "input-binding.json").read_bytes())
    pins, pending, expanded = {}, list(binding["anchors"]), set()
    def add(items):
        for path, expected in items.items():
            adapter.need(path not in pins or pins[path] == expected, "conflicting pin")
            pins[path] = expected
    add(binding["anchors"])
    while pending:
        path = pending.pop()
        if path in expanded:
            continue
        expanded.add(path)
        data = read(path)
        adapter.need(digest(data) == pins[path], "anchor drift")
        if path.endswith(".sha256"):
            items = {}
            for line in data.decode().splitlines():
                value, name = line.split("  ", 1)
                adapter.need(name not in items, "duplicate seal entry")
                items[name] = value
            add(items)
        elif path.endswith("input-binding.json") or "/source-binding-e" in path:
            previous = json.loads(data)
            add(previous.get("files", {}))
            add(previous.get("direct", {}))
            for field in ("anchors", "links"):
                items = previous.get(field, {})
                add(items)
                pending.extend(items)
    prior_count, prior_bytes = len(pins), sum(len(read(p)) for p in pins)
    add(binding["direct"])
    total = 0
    for path, expected in pins.items():
        data = read(path)
        total += len(data)
        adapter.need(total <= 33554432 and digest(data) == expected, "input drift/cap")
    source = json.loads(read(BASE + "r18/source-binding-e3.json"))
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    for scope, paths in source["scopes"].items():
        dirs = ("src", "migrations") if scope == "product" else ("tests",)
        actual = []
        for directory in dirs:
            for path in (ROOT / "v2/apps/backend" / directory).rglob("*"):
                relative = path.relative_to(ROOT)
                if ignored.intersection(relative.parts) or path.suffix == ".pyc":
                    continue
                adapter.need(not path.is_symlink(), "source symlink")
                if path.is_file():
                    actual.append(relative.as_posix())
        actual += [p for p in paths if not any("/" + d + "/" in p for d in dirs)]
        adapter.need(sorted(actual) == paths, "inventory drift")
        adapter.need(digest("".join(pins[p] + "  " + p + "\n" for p in paths).encode())
                     == source["digests"][scope], "source digest")
    return {"prior_pins": prior_count, "prior_bytes": prior_bytes, "total_pins": len(pins),
            "input_bytes": total, "digests": source["digests"],
            "scope_counts": {key: len(value) for key, value in source["scopes"].items()}}


if __name__ == "__main__":
    before = preserve()
    files = ("adapter.py", "test_adapter.py", "checks.py", "input-binding.json")
    hashes_before = {p: digest((HERE / p).read_bytes()) for p in files}
    for path in files[:3]:
        compile((HERE / path).read_text(), path, "exec")
    contract_bytes = read(BASE + "r25/contract.json")
    test_adapter.CONTRACT_BYTES = contract_bytes
    test_adapter.CONTRACT = contract = json.loads(contract_bytes)
    adapter.limits(contract)
    sandboxes_before = sorted(p.name for p in HERE.glob(".r26-test-*"))
    stream = io.StringIO()
    started = time.monotonic()
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_adapter))
    elapsed = time.monotonic() - started
    after = preserve()
    hashes_after = {p: digest((HERE / p).read_bytes()) for p in files}
    sandboxes_after = sorted(p.name for p in HERE.glob(".r26-test-*"))
    normal = sum(n * (length + 11) for n, length in adapter.limits(contract).values())
    print(json.dumps({"before": before, "after": after, "source_before": hashes_before,
        "source_after": hashes_after, "tests_run": tests.testsRun, "failures": len(tests.failures),
        "errors": len(tests.errors), "skips": len(tests.skipped), "seconds": elapsed,
        "stdout": stream.getvalue(), "compiled_files": 3,
        "sandboxes_before": sandboxes_before, "sandboxes_after": sandboxes_after,
        "budget": {"normal": normal, "terminal": adapter.TERMINAL,
                   "controls": adapter.CONTROLS, "total": normal + adapter.TERMINAL + adapter.CONTROLS,
                   "cap": adapter.CAP, "actual_capture_admission": "HOLD"},
        "not_run": ["lint", "types", "power loss/process death", "hostile same UID/root",
                    "runtime/async/measured integration", "SQL/Docker/HTTP/external"]}, indent=2, sort_keys=True))
    adapter.need(tests.wasSuccessful() and before == after and hashes_before == hashes_after
                 and sandboxes_before == sandboxes_after, "tests/preservation/cleanup")
