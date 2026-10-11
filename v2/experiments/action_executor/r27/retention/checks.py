"""New prototype tests plus hash-only traversal of explicitly linked prior inputs."""

import hashlib
import io
import json
import time
import unittest
from pathlib import Path

import adapter
import test_retention

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
BASE = "v2/experiments/action_executor/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    path = Path(name)
    adapter.need(
        not path.is_absolute() and ".." not in path.parts and name == path.as_posix(), "input path"
    )
    adapter.need(
        not any((ROOT / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)),
        "input symlink",
    )
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
        adapter.need(
            digest("".join(pins[p] + "  " + p + "\n" for p in paths).encode())
            == source["digests"][scope],
            "source digest",
        )
    return {
        "prior_pins": prior_count,
        "prior_bytes": prior_bytes,
        "total_pins": len(pins),
        "input_bytes": total,
        "digests": source["digests"],
        "scope_counts": {key: len(value) for key, value in source["scopes"].items()},
    }


if __name__ == "__main__":
    before = preserve()
    files = (
        "adapter.py",
        "envelope.py",
        "producers.py",
        "pipes.py",
        "raw_child.py",
        "test_retention.py",
        "checks.py",
        "routing.json",
        "input-binding.json",
    )
    source_before = {name: digest((HERE / name).read_bytes()) for name in files}
    base = read(BASE + "r27/adapter.py")
    expected = (
        base.replace(b"R27 derived isolated", b"R27 retention derived isolated")
        .replace(b"outside r27", b"outside retention")
        .replace(b"R27OWN01", b"R27OWNR1")
        .replace(b"R27SEAL1", b"R27SEAR1")
    )
    adapter.need(expected == (HERE / "adapter.py").read_bytes(), "derived source mismatch")
    for name in files[:7]:
        compile((HERE / name).read_text(), name, "exec")
    sandbox_before = sorted(path.name for path in HERE.glob(".retention-test-*"))
    stream = io.StringIO()
    start = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_retention)
    )
    elapsed = time.monotonic() - start
    after = preserve()
    source_after = {name: digest((HERE / name).read_bytes()) for name in files}
    sandbox_after = sorted(path.name for path in HERE.glob(".retention-test-*"))
    print(
        json.dumps(
            {
                "before": before,
                "after": after,
                "source_before": source_before,
                "source_after": source_after,
                "tests_run": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skips": len(result.skipped),
                "stdout": stream.getvalue(),
                "seconds": elapsed,
                "compiled_files": 7,
                "sandboxes_before": sandbox_before,
                "sandboxes_after": sandbox_after,
                "measurement_admission": "HOLD",
                "scope": (
                    "Real isolated Python producers/files/copies/logging/"
                    "unframed finite pipes; not full campaign"
                ),
                "not_run": [
                    "SQL/Docker/HTTP/load",
                    "native/cached fd/outer/Bash exclusivity",
                    "physical lease proof",
                    "hostile same UID/root",
                    "power-loss proof",
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    adapter.need(
        result.wasSuccessful()
        and before == after
        and source_before == source_after
        and sandbox_before == sandbox_after,
        "tests/preservation/cleanup",
    )
