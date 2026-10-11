"""Own offline model controls and read-only expansion of explicitly linked seals."""

import hashlib
import io
import json
import time
import unittest
from pathlib import Path

import model
import test_model

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE = "v2/experiments/action_executor/"


def read(name):
    path = Path(name)
    model.require(not path.is_absolute() and ".." not in path.parts
                  and name == path.as_posix(), "noncanonical input")
    model.require(not any((ROOT / Path(*path.parts[:i])).is_symlink()
                          for i in range(1, len(path.parts) + 1)), "input symlink")
    model.require((ROOT / path).stat().st_size <= 32 * 1024 * 1024, "single input cap")
    return (ROOT / path).read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def preserve():
    binding = json.loads((HERE / "input-binding.json").read_bytes())
    pins, pending, expanded = {}, list(binding["anchors"]), set()

    def add(items):
        for path, expected in items.items():
            model.require(path not in pins or pins[path] == expected, "conflicting pin")
            pins[path] = expected

    add(binding["anchors"])
    while pending:
        path = pending.pop()
        if path in expanded:
            continue
        expanded.add(path)
        data = read(path)
        model.require(digest(data) == pins[path], "anchor changed")
        if path.endswith(".sha256"):
            items = {}
            for line in data.decode().splitlines():
                value, name = line.split("  ", 1)
                model.require(name not in items, "duplicate sealed path")
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
        model.require(total <= 32 * 1024 * 1024 and digest(data) == expected, "input drift/cap")
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
                model.require(not path.is_symlink(), "source symlink")
                if path.is_file():
                    actual.append(relative.as_posix())
        actual += [p for p in paths if not any("/" + d + "/" in p for d in dirs)]
        model.require(sorted(actual) == paths, "source inventory changed")
        model.require(digest("".join(pins[p] + "  " + p + "\n" for p in paths).encode())
                      == source["digests"][scope], "source recipe changed")
    return {"prior_pins": prior_count, "prior_bytes": prior_bytes, "total_pins": len(pins),
            "input_bytes": total, "digests": source["digests"],
            "scope_counts": {key: len(value) for key, value in source["scopes"].items()}}


if __name__ == "__main__":
    before = preserve()
    source_before = {p: digest((HERE / p).read_bytes())
                     for p in ("model.py", "test_model.py", "checks.py", "contract.json", "input-binding.json")}
    for path in ("model.py", "test_model.py", "checks.py"):
        compile((HERE / path).read_text(), path, "exec")
    contract = json.loads((HERE / "contract.json").read_bytes())
    prior = json.loads(read(BASE + "r24/ledger.json"))["producers"]
    model.require([f["id"] for f in contract["families"]] == [f["id"] for f in prior],
                  "source producer mapping")
    for proposed, original in zip(contract["families"], prior):
        projected = [proposed["witnesses"], proposed["current_classification"],
                     proposed["current_source_max_bytes"]]
        expected = [original["witnesses"], original["classification"], original["max_bytes"]]
        model.require(json.dumps(projected, sort_keys=True, allow_nan=False)
                      == json.dumps(expected, sort_keys=True, allow_nan=False),
                      "model choices promoted to source bounds")
    test_model.CONTRACT = contract
    stream = io.StringIO()
    started = time.monotonic()
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_model))
    elapsed = time.monotonic() - started
    after = preserve()
    source_after = {p: digest((HERE / p).read_bytes()) for p in source_before}
    print(json.dumps({"before": before, "after": after, "source_before": source_before,
                      "source_after": source_after, "model_budget": model.budget(contract),
                      "tests_run": tests.testsRun, "failures": len(tests.failures),
                      "errors": len(tests.errors), "skips": len(tests.skipped),
                      "seconds": elapsed, "stdout": stream.getvalue(), "compiled_files": 3,
                      "not_run": ["lint", "types", "runtime/async/durability", "SQL", "Docker",
                                  "HTTP/load", "external/native/provider"]}, indent=2, sort_keys=True))
    model.require(tests.wasSuccessful() and before == after and source_before == source_after,
                  "controls or preservation failed")
