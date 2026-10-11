"""One serial28 entry: frozen23 regressions + five PRE diagnostic groups."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType

import admission
import bridge
import pytest
from writer import mapping

HERE, ROOT = bridge.HERE, bridge.ROOT
REFERENCE = HERE.parent / "runtime_closure"
REFERENCE_BINDING = "798b0ee3f6e0abad42d10d4c5ef140a4123c5215fbae9e49b55366964ad6bffc"
REFERENCE_CHECKS = "1a3d421cc8deebfb95ad298752e0b488093b807fbebf6ff96331606c7912b004"
TESTS = (
    HERE.parent / "real_path/test_core.py",
    HERE.parent / "real_path/test_runtime_path.py",
    REFERENCE / "test_native.py",
    REFERENCE / "test_plugin_seams.py",
    REFERENCE / "test_acceptance.py",
    HERE / "test_pre_contract.py",
)


def digest(path: Path) -> str:
    if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size > 33554432:
        raise ValueError("bounded nonsymlink pin")
    with path.open("rb") as stream:
        raw = stream.read(33554433)
    if len(raw) > 33554432:
        raise ValueError("pin grew")
    return hashlib.sha256(raw).hexdigest()


def reference() -> ModuleType:
    if (
        digest(REFERENCE / "input-binding.json") != REFERENCE_BINDING
        or digest(REFERENCE / "checks.py") != REFERENCE_CHECKS
    ):
        raise ValueError("frozen closure drift before import")
    spec = importlib.util.spec_from_file_location("r27_pre_frozen_closure", REFERENCE / "checks.py")
    if spec is None or spec.loader is None:
        raise ValueError("source loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preservation() -> dict[str, object]:
    prior: object = reference().preservation()
    packet = mapping(json.loads((HERE / "input-binding.json").read_bytes()))
    for field in ("direct", "dependencies"):
        for name, wanted in mapping(packet[field]).items():
            path = Path(name) if field == "dependencies" else ROOT / name
            if field == "direct" and (
                Path(name).is_absolute()
                or ".." in Path(name).parts
                or Path(name).as_posix() != name
            ):
                raise ValueError("canonical pin")
            if digest(path) != wanted:
                raise ValueError("pin drift: " + name)
    return {
        "prior": mapping(prior),
        "direct": len(mapping(packet["direct"])),
        "dependencies": len(mapping(packet["dependencies"])),
    }


def sources() -> dict[str, str]:
    return {
        p.name: digest(p)
        for p in [
            *HERE.glob("*.py"),
            *(
                HERE / n
                for n in ("SCOPE.md", "candidate.json", "input-binding.json", "manifest.json")
            ),
        ]
    }


def scratch() -> list[str]:
    return sorted(
        str(p.relative_to(ROOT))
        for home in (HERE, REFERENCE, HERE.parent / "real_path")
        for p in home.iterdir()
        if p.is_dir() and p.name.startswith((".closure-", ".real-path-", "peer-control-"))
    )


class Collector:
    def __init__(self) -> None:
        self.collected: list[str] = []
        self.calls: set[str] = set()
        self.failed = self.errors = self.skipped = 0

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        expected = {
            (p.name, n.name)
            for p in TESTS
            for n in ast.parse(bridge.bounded(p)).body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        }
        if (
            len(items) != 28
            or len(expected) != 28
            or {(Path(i.path).name, i.name) for i in items} != expected
        ):
            raise ValueError("exact23+5 outer identities")
        self.collected = [str(i.path) + "::" + i.name for i in items]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call":
            self.calls.add(report.nodeid)
            self.failed += int(report.failed)
        elif report.failed:
            self.errors += 1
        self.skipped += int(report.skipped)


def main() -> None:
    before, old, initial = preservation(), sources(), scratch()
    for p in HERE.glob("*.py"):
        compile(bridge.bounded(p).decode(), str(p), "exec")
    collector, output = Collector(), io.StringIO()
    started = time.monotonic()
    with (
        tempfile.TemporaryDirectory(prefix=".closure-pre-pytest-", dir=HERE) as name,
        redirect_stdout(output),
        redirect_stderr(output),
    ):
        code = pytest.main(
            [
                "-c",
                str(ROOT / "v2/apps/backend/pyproject.toml"),
                "--confcutdir=" + str(HERE.parent),
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp=" + str(Path(name) / "pytest"),
                *(str(p) for p in TESTS),
            ],
            plugins=[collector],
        )
    after, new, final = preservation(), sources(), scratch()
    result = {
        "before": before,
        "after": after,
        "source_before": old,
        "source_after": new,
        "scratch_before": initial,
        "scratch_after": final,
        "collected": collector.collected,
        "unique_outer_scenarios": len(collector.calls),
        "failed": collector.failed,
        "errors": collector.errors,
        "skipped": collector.skipped,
        "pytest_exit": int(code),
        "stdout": output.getvalue(),
        "seconds": time.monotonic() - started,
        "compiled_new_modules": len(list(HERE.glob("*.py"))),
        "original_PRE": "DENY/NOT_RUN",
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    if int(code) or len(collector.calls) != 28 or before != after or old != new or initial != final:
        raise SystemExit(1)


def preflight() -> None:
    result = preservation()
    source = mapping(json.loads((HERE / "candidate.json").read_bytes()))
    for name, wanted in mapping(source["sources"]).items():
        if digest(ROOT / name) != wanted:
            raise ValueError("candidate source drift")
    try:
        admission.dispatch_pre(source)
    except PermissionError as error:
        print(
            json.dumps(
                {
                    "source_matches": True,
                    "execution_admission": "DENY",
                    "effects": "NOT_RUN",
                    "reason": str(error),
                    "preservation": result,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(2) from None
    raise AssertionError("dispatch must never grant PRE")


if __name__ == "__main__":
    if sys.argv[1:] == ["--preflight"]:
        preflight()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("no arguments or --preflight only")
