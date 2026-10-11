"""New prototype tests plus hash-only traversal of explicitly linked prior inputs."""

import hashlib
import io
import json
import time
import unittest
from pathlib import Path

import adapter
import test_integration

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
    files = ("adapter.py", "source_subset.py", "pipe_source.py", "integration.py",
             "test_integration.py", "checks.py", "derivation.json", "routing.json", "input-binding.json")
    hashes_before = {p: digest((HERE / p).read_bytes()) for p in files}
    derivation = json.loads((HERE / "derivation.json").read_bytes())
    base = read(derivation["base_path"])
    expected = base.replace(
        b"Isolated synchronous file prototype. Actual campaign capture remains HOLD.",
        b"R27 derived isolated file adapter. Actual campaign capture remains HOLD."
    ).replace(b"outside r26", b"outside r27").replace(b"R26OWN01", b"R27OWN01").replace(b"R26SEAL1", b"R27SEAL1")
    adapter.need(digest(base) == derivation["base_sha256"]
                 and expected == (HERE / "adapter.py").read_bytes()
                 and digest(expected) == derivation["derived_sha256"], "derivation drift")
    for path in files[:6]:
        compile((HERE / path).read_text(), path, "exec")
    sandboxes_before = sorted(p.name for p in HERE.glob(".r27-test-*"))
    stream = io.StringIO()
    started = time.monotonic()
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_integration))
    elapsed = time.monotonic() - started
    after = preserve()
    hashes_after = {p: digest((HERE / p).read_bytes()) for p in files}
    sandboxes_after = sorted(p.name for p in HERE.glob(".r27-test-*"))
    print(json.dumps({"before": before, "after": after, "source_before": hashes_before,
        "source_after": hashes_after, "tests_run": tests.testsRun, "failures": len(tests.failures),
        "errors": len(tests.errors), "skips": len(tests.skipped), "seconds": elapsed,
        "stdout": stream.getvalue(), "compiled_files": 6,
        "sandboxes_before": sandboxes_before, "sandboxes_after": sandboxes_after,
        "actual_capture_admission": "HOLD",
        "not_run": ["lint/types (unavailable)", "full app/SQL/lease integration",
                    "arbitrary/hanging child safety", "power loss/process death",
                    "hostile same UID/root", "Docker/HTTP/measured/external"]},
        indent=2, sort_keys=True))
    adapter.need(tests.wasSuccessful() and before == after and hashes_before == hashes_after
                 and sandboxes_before == sandboxes_after, "tests/preservation/cleanup")

