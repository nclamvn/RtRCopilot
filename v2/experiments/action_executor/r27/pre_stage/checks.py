"""Supported frozen verification entry: validates bindings before stage imports/effects."""

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
from typing import cast

import bridge
import pytest
import stage
import writer

HERE = stage.HERE
PREVIOUS = HERE.parent / "pre_contract"
PRIOR_PINS = {
    "checks.py": "25f0b34a5e58c889691049da91512c08421252a2ed981001bba27184f34434ac",
    "input-binding.json": "1e7dfca6f0dc4bb89f80d94b4926ff28ae48faf35e7bb7da9241e5218bc1c770",
    "candidate.json": "09eb6fd832c0eb6a23068c9ac873ca450ddba887aa24a9167402fc693e183d4d",
    "manifest.json": "3b99972f22fd0533a563da6d1a8ca74961b38ce0729bab83ec1f501fa48d3d63",
}


def digest(path: Path) -> str:
    return hashlib.sha256(bridge.bounded(path)).hexdigest()


def reference() -> ModuleType:
    for name, expected in PRIOR_PINS.items():
        if digest(PREVIOUS / name) != expected:
            raise ValueError("frozen preceding stage drift")
    spec = importlib.util.spec_from_file_location(
        "r27_stage_previous_checks", PREVIOUS / "checks.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("pinned preceding loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inventory() -> dict[str, str]:
    paths = [
        *HERE.glob("*.py"),
        HERE / "SCOPE.md",
        HERE / "contract.json",
        *(HERE / "history/previous-publication").glob("*.original"),
    ]
    return {p.relative_to(stage.ROOT).as_posix(): digest(p) for p in sorted(paths)}


def manifest() -> dict[str, object]:
    return {
        "schema": "r27-local-pre-closure-evidence-v1",
        "original_method_bodies": "UNCHANGED",
        "source_case": "R21Controls.test_packet_summary_controls_oracle_and_corruption",
        "whole_writes": 35,
        "payload_bytes": 733169,
        "final_live_before_cleanup": 4050,
        "actual_charge_with_closure": 1532954,
        "closed_domain_max_charge": 2469496,
        "coarse_packet_codec_ceiling": 8241689,
        "metadata_reserve": stage.METADATA,
        "source_mkdir_calls": 2,
        "owned_rmdir_calls": 4,
        "file_tombstones": 9,
        "AST_deltas": [
            "Writer.emit subtype expression -> semantic(self,family,variant)",
            "Broker._write emit variant literal -> synthetic_input",
        ],
        "factory_authority": (
            "diagnostic constructor/current witnesses; frozen checks entry required"
        ),
        "qualified_original_PRE": False,
        "original_PRE": "DENY",
        "executor": "OFF",
        "measurement": "NONE: synthetic elapsed_ms=1.0 oracle controls",
        "unqualified": [
            "native tempfile/probe/fallback/rmtree",
            "pytest basetemp/current symlink",
            "shell/native child outputs",
            "unknown plugin/platform/error routes",
        ],
        "source_pins": stage.guard(),
    }


def preservation() -> dict[str, object]:
    prior = writer.mapping(reference().preservation())
    binding = writer.mapping(json.loads(bridge.bounded(HERE / "input-binding.json")))
    direct = writer.mapping(binding["direct"])
    if direct != inventory():
        raise ValueError("frozen new implementation binding before imports/effects")
    candidate = writer.mapping(json.loads(bridge.bounded(HERE / "candidate.json")))
    if candidate.get("binding_sha256") != digest(HERE / "input-binding.json") or candidate.get(
        "manifest_sha256"
    ) != digest(HERE / "manifest.json"):
        raise ValueError("candidate/binding/evidence closure")
    if json.loads(bridge.bounded(HERE / "manifest.json")) != manifest():
        raise ValueError("source-bound actual policy/evidence manifest")
    return {"previous": prior, "new_direct_pins": len(direct), "frozen_entry": True}


def scratch() -> list[str]:
    return sorted(
        str(p.relative_to(stage.ROOT))
        for home in (HERE, stage.REFERENCE, PREVIOUS, HERE.parent / "runtime_closure")
        for p in home.iterdir()
        if p.is_dir() and p.name.startswith((".closure-", ".real-path-", "peer-control-"))
    )


class Collector:
    def __init__(self, tests: tuple[Path, ...]) -> None:
        self.tests = tests
        self.collected: list[str] = []
        self.calls: set[str] = set()
        self.failed = self.errors = self.skipped = 0

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        expected = {
            (p.name, n.name)
            for p in self.tests
            for n in ast.parse(bridge.bounded(p)).body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        }
        if (
            len(items) != 33
            or len(expected) != 33
            or {(Path(i.path).name, i.name) for i in items} != expected
        ):
            raise ValueError("exact preceding28 plus five new outer identities")
        self.collected = [str(i.path) + "::" + i.name for i in items]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call":
            self.calls.add(report.nodeid)
            self.failed += int(report.failed)
        elif report.failed:
            self.errors += 1
        self.skipped += int(report.skipped)


def main() -> None:
    before, sources, initial = preservation(), inventory(), scratch()
    # New runtime modules are imported only by pytest after frozen binding checks.
    tests = (*cast(tuple[Path, ...], reference().TESTS), HERE / "test_stage.py")
    collector, output = Collector(tests), io.StringIO()
    started = time.monotonic()
    for p in HERE.glob("*.py"):
        compile(bridge.bounded(p), str(p), "exec")
    with (
        tempfile.TemporaryDirectory(prefix=".closure-stage-pytest-", dir=HERE) as name,
        redirect_stdout(output),
        redirect_stderr(output),
    ):
        code = pytest.main(
            [
                "-c",
                str(stage.ROOT / "v2/apps/backend/pyproject.toml"),
                "--confcutdir=" + str(HERE.parent),
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp=" + str(Path(name) / "pytest"),
                *(str(p) for p in tests),
            ],
            plugins=[collector],
        )
    after, new_sources, final = preservation(), inventory(), scratch()
    result = {
        "before": before,
        "after": after,
        "source_before": sources,
        "source_after": new_sources,
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
        "new_modules_compiled": 5,
        "original_PRE": "DENY/NOT_RUN",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if (
        int(code)
        or len(collector.calls) != 33
        or before != after
        or sources != new_sources
        or initial != final
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--material"]:
        previous = reference().preservation()
        print(
            json.dumps(
                {"direct": inventory(), "manifest": manifest(), "previous": previous},
                sort_keys=True,
            )
        )
    elif sys.argv[1:] == ["--preflight"]:
        preservation()
        try:
            stage.dispatch_original_pre()
        except PermissionError as error:
            print(
                json.dumps(
                    {"execution_admission": "DENY", "effects": "NOT_RUN", "reason": str(error)}
                )
            )
            raise SystemExit(2) from None
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("no arguments, --material or --preflight")
