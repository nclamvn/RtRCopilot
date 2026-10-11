"""Frozen serial38 entry; admit source, contract and old pins before new effects."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import cast

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]
PREVIOUS = HERE.parent / "pre_stage"
PRIOR_PINS = {
    "checks.py": "91f6931b33b6ea9990e5a73b722db5f43bc49957c3662cb70ddcb9afe57743ef",
    "input-binding.json": "48f3cb9aa429b18a00d380ff4a3d6a1171693965754ba0352bd8dc379b901d22",
    "manifest.json": "d7696313a6863848cd495affcd85c8ce99f74172253799dd433b14bb4791cac5",
    "candidate.json": "0cebd82ab5a036d92d445edfa6b02d68bf15625d721bb7a08206b959328b86a4",
    "COMPLETION.md": "e5ff08ee303c8624e95f73b9058012045ead1f0b9b3da6c6ab133916f7e48c29",
}
PYTHON = Path(
    "/Users/os/.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/lib/python3.12"
)
PYTEST = ROOT / "v2/apps/backend/.venv/lib/python3.12/site-packages/_pytest"
DEPENDENCY_PINS = {
    str(
        PYTHON / "tempfile.py"
    ): "2eea4401f4f29d0d3647ed6fc8bcf6aa1daf879c8aa407a8ea310edac9dfc317",
    str(
        PYTHON / "shutil.py"
    ): "f9f0102a9ed087271f914d74b07866464d3e716afe9ee10760a5eb90f7db0f33",
    str(
        PYTHON / "weakref.py"
    ): "56f8d313fb74019e53eb9287400702fbce788b7fe30e097b0b6e06296f3f080c",
    str(
        PYTHON / "unittest/case.py"
    ): "45bac6d80a4fc3a0dea8340a80681e30b263f017b4a5002cb8f489a632e0f987",
    str(
        PYTHON / "unittest/result.py"
    ): "5db286bdd3821d64150377e554d7edbdd58db7bb8b950772f977e9ec1d535617",
    str(
        PYTEST / "tmpdir.py"
    ): "236918c090160c1f6b935e162ff44ab273a700221d5f40ac15892be75e4503ee",
    str(
        PYTEST / "pathlib.py"
    ): "8127808359baaa711775862b32bfbe0a7e5c16a2e8c9923d60ddd45f031b66fa",
    str(
        PYTEST / "junitxml.py"
    ): "51ea93fb20122b8aa5f2c412b9cf946b6daf719cde470f6ca2c50430bed4135d",
    str(
        HERE.parent / "real_path/adapter.py"
    ): "0f2a92fe0574fafc70acedc966b113928676cd78cc4ff7e6a83cb349074f63a2",
    str(
        HERE.parent / "real_path/writer.py"
    ): "e2b7738807dced6bd7ed20d9f1662de648e09a1317db45ed193bb2db4c6ddeba",
}
TESTS = (
    HERE.parent / "real_path/test_core.py",
    HERE.parent / "real_path/test_runtime_path.py",
    HERE.parent / "runtime_closure/test_native.py",
    HERE.parent / "runtime_closure/test_plugin_seams.py",
    HERE.parent / "runtime_closure/test_acceptance.py",
    HERE.parent / "pre_contract/test_pre_contract.py",
    PREVIOUS / "test_stage.py",
    HERE / "test_lifecycle.py",
)
NEW_TESTS = {
    "test_genuine_setup_body_cleanup_private_pytest",
    "test_genuine_probe_fallback_collision_permissions_finalizer",
    "test_absorbing_short_write_genuine_cleanup_failure",
    "test_preadmitted_partial_xml_stream_failure_native_retention",
    "test_typed_recovery_tamper_and_pre_effect_domain_guards",
}


def bounded(path: Path) -> bytes:
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or path.stat().st_size > 33554432
    ):
        raise ValueError("bounded nonsymlink pin")
    with path.open("rb") as stream:
        raw = stream.read(33554433)
    if len(raw) > 33554432:
        raise ValueError("pin grew")
    return raw


def digest(path: Path) -> str:
    return hashlib.sha256(bounded(path)).hexdigest()


def mapping(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(k) is not str for k in value):
        raise ValueError("exact string mapping")
    return cast(dict[str, object], value)


def environment(*, before_effects: bool = True) -> None:
    if sys.version_info[:3] != (3, 12, 11) or sys.platform != "darwin":
        raise ValueError("only pinned Python3.12.11 actual local Darwin lifecycle")
    if (
        os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1"
        or not sys.dont_write_bytecode
    ):
        raise ValueError("plugin autoload/bytecode must be OFF before imports")
    if any(
        os.environ.get(name)
        for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DEBUG")
    ):
        raise ValueError("no implicit pytest options, plugins or native debug writer")
    if before_effects and any(
        name in sys.modules for name in ("native", "genuine", "flows", "test_lifecycle")
    ):
        raise ValueError("new composition imported before checked admission")


def reference() -> ModuleType:
    for name, expected in DEPENDENCY_PINS.items():
        if digest(Path(name)) != expected:
            raise ValueError(
                "genuine installed/old source drift before imports: " + name
            )
    for name, expected in PRIOR_PINS.items():
        if digest(PREVIOUS / name) != expected:
            raise ValueError("frozen preceding stage drift: " + name)
    spec = importlib.util.spec_from_file_location(
        "r27_lifecycle_previous_checks", PREVIOUS / "checks.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("preceding pinned loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inventory() -> dict[str, str]:
    paths = [
        *HERE.glob("*.py"),
        *(HERE / n for n in ("SCOPE.md", "contract.json", "pytest.ini")),
        *(HERE / "history/previous-publication").glob("*.original"),
    ]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def histories() -> dict[str, str]:
    paths = [
        p
        for p in (HERE / "history").rglob("*")
        if p.is_file() and "previous-publication" not in p.parts
    ]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def manifest() -> dict[str, object]:
    # This module has no effectful import; guard reads canonical source/contract only.
    import policy

    source = policy.guard()
    import shutil

    if getattr(shutil, "_use_fd_functions") is not True:
        raise ValueError("actual host must select genuine safe-fd rmtree")
    contract, _ = policy.contract()
    return {
        "schema": "r27-local-genuine-lifecycle-evidence-v1",
        "stage": "LOCAL_NATIVE_LIFECYCLE",
        "contract": contract,
        "source_pins": source,
        "outer_scenarios": {"preceding_unchanged": 33, "new": 5, "total": 38},
        "nested_pytest": {
            "source_cases": 2,
            "expected_exit": 1,
            "intentional_failures": 1,
            "outer_coverage_contribution": 0,
        },
        "original_source_case": "R21Controls.test_packet_summary_controls_oracle_and_corruption",
        "original_source_whole_writes": 35,
        "original_source_payload_bytes": 733169,
        "payload_ceiling": 1329440,
        "conservative_physical_packet_metadata_maximum": 2725881,
        "metadata_reserve": 65536,
        "selected_fixed_control_descriptors": 4,
        "host_selected_safe_fd_rmtree": True,
        "disabled_implicit_diagnostic_writers": ["faulthandler", "pastebin"],
        "selected_shared_producer_transient_descriptors": 12,
        "descriptor_claim": "selected domain, not process-wide FD or syscall bound",
        "no_refund": True,
        "measurement": "NONE: original elapsed_ms=1.0 oracle inputs remain synthetic",
        "original_PRE": "DENY",
        "qualified_original_PRE": False,
        "executor": "OFF",
        "overall_status": "NOT_READY",
        "unqualified": [
            "default pytest user/lock/PID/garbage/atexit lifecycle",
            "arbitrary native child or file writer",
            "complete six-suite/launcher PRE",
            "other platforms and unknown plugin/error routes",
        ],
    }


def material() -> dict[str, object]:
    environment()
    old = mapping(reference().preservation())
    declared = manifest()
    return {
        "direct": inventory(),
        "initial_failure_history": histories(),
        "preceding_stage_pins": PRIOR_PINS,
        "previous_preservation": old,
        "dependencies": {
            name: pin
            for name, pin in mapping(declared["source_pins"]).items()
            if not Path(name).is_relative_to(HERE)
        },
        "manifest": declared,
    }


def preservation(*, before_effects: bool = True) -> dict[str, object]:
    environment(before_effects=before_effects)
    binding = mapping(json.loads(bounded(HERE / "input-binding.json")))
    if binding.get("schema") != "r27-genuine-lifecycle-frozen-binding-v1":
        raise ValueError("lifecycle frozen binding schema")
    if (
        binding.get("direct") != inventory()
        or binding.get("initial_failure_history") != histories()
    ):
        raise ValueError(
            "exact source/history admission before composition imports/effects"
        )
    if binding.get("preceding_stage_pins") != PRIOR_PINS:
        raise ValueError("exact preceding contract pins")
    if binding.get("dependencies") != DEPENDENCY_PINS:
        raise ValueError("exact installed/old source dependencies")
    for name, expected in DEPENDENCY_PINS.items():
        if not Path(name).is_absolute() or digest(Path(name)) != expected:
            raise ValueError(
                "genuine installed/old source admission before imports: " + name
            )
    old = mapping(reference().preservation())
    if binding.get("previous_preservation") != old:
        raise ValueError("entire unchanged preceding preservation")
    candidate = mapping(json.loads(bounded(HERE / "candidate.json")))
    if (
        candidate.get("binding_sha256") != digest(HERE / "input-binding.json")
        or candidate.get("manifest_sha256") != digest(HERE / "manifest.json")
        or candidate.get("executor") != "OFF"
        or candidate.get("overall_status") != "NOT_READY"
        or candidate.get("original_PRE") != "DENY"
    ):
        raise ValueError("candidate/binding/manifest authority closure")
    if json.loads(bounded(HERE / "manifest.json")) != manifest():
        raise ValueError("exact source/contract-bound lifecycle manifest")
    return {
        "previous": old,
        "new_direct_pins": len(mapping(binding["direct"])),
        "initial_failure_history_pins": len(
            mapping(binding["initial_failure_history"])
        ),
        "unique_new_direct_history_pins": len(
            set(mapping(binding["direct"]))
            | set(mapping(binding["initial_failure_history"]))
        ),
        "frozen_entry": True,
    }


def sources() -> dict[str, str]:
    return {
        **inventory(),
        **histories(),
        **{
            p.relative_to(ROOT).as_posix(): digest(p)
            for p in (
                HERE / n
                for n in ("input-binding.json", "manifest.json", "candidate.json")
            )
        },
    }


def scratch() -> list[str]:
    homes = (
        HERE,
        PREVIOUS,
        HERE.parent / "real_path",
        HERE.parent / "runtime_closure",
        HERE.parent / "pre_contract",
    )
    return sorted(
        str(p.relative_to(ROOT))
        for home in homes
        for p in home.iterdir()
        if p.is_dir()
        and p.name.startswith(
            (
                ".closure-",
                ".real-path-",
                "peer-control-",
                ".lifecycle-",
                "codex-tmp-r27",
            )
        )
    )


def caches() -> list[str]:
    homes = (
        HERE,
        PREVIOUS,
        HERE.parent / "real_path",
        HERE.parent / "runtime_closure",
        HERE.parent / "pre_contract",
    )
    found = {p for home in homes for p in home.rglob("__pycache__") if p.is_dir()}
    for home in (*homes, ROOT, ROOT / "v2/apps/backend"):
        for name in (".pytest_cache", ".ruff_cache", ".mypy_cache"):
            path = home / name
            if path.exists():
                found.add(path)
    return sorted(str(p.relative_to(ROOT)) for p in found)


class Collector:
    def __init__(self) -> None:
        self.collected: list[str] = []
        self.calls: set[str] = set()
        self.failed = self.errors = self.skipped = 0

    def pytest_collection_modifyitems(self, items: list[object]) -> None:
        expected = {
            (str(p), n.name)
            for p in TESTS
            for n in ast.parse(bounded(p)).body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        }
        found = {(str(getattr(i, "path")), str(getattr(i, "name"))) for i in items}
        old = sum(p != str(TESTS[-1]) for p, _ in expected)
        new = {name for path, name in expected if path == str(TESTS[-1])}
        if (
            len(items) != 38
            or len(expected) != 38
            or old != 33
            or new != NEW_TESTS
            or found != expected
        ):
            raise ValueError("exact unchanged33 + five new outer identities")
        self.collected = [
            str(getattr(i, "path")) + "::" + str(getattr(i, "name")) for i in items
        ]

    def pytest_runtest_logreport(self, report: object) -> None:
        if getattr(report, "when") == "call":
            nodeid = str(getattr(report, "nodeid"))
            if nodeid in self.calls:
                raise ValueError("no duplicate outer coverage")
            self.calls.add(nodeid)
            self.failed += int(getattr(report, "failed"))
        elif getattr(report, "failed"):
            self.errors += 1
        self.skipped += int(getattr(report, "skipped"))


def main() -> None:
    before, original, initial = preservation(), sources(), scratch()
    cache_before = caches()
    import pytest

    collector, output = Collector(), io.StringIO()
    started = time.monotonic()
    for path in HERE.glob("*.py"):
        compile(bounded(path), str(path), "exec")
    with redirect_stdout(output), redirect_stderr(output):
        code = pytest.main(
            [
                "-c",
                str(HERE / "pytest.ini"),
                "--noconftest",
                "--assert=plain",
                "-q",
                "--color=no",
                "-p",
                "no:cacheprovider",
                "-p",
                "no:capture",
                "-p",
                "no:tmpdir",
                "-p",
                "no:junitxml",
                "-p",
                "no:logging",
                "-p",
                "no:legacypath",
                "-p",
                "no:faulthandler",
                "-p",
                "no:pastebin",
                *(str(p) for p in TESTS),
            ],
            plugins=[collector],
        )
    after = preservation(before_effects=False)
    changed, final = sources(), scratch()
    cache_after = caches()
    result = {
        "before": before,
        "after": after,
        "source_before": original,
        "source_after": changed,
        "scratch_before": initial,
        "scratch_after": final,
        "cache_before": cache_before,
        "cache_after": cache_after,
        "collected": collector.collected,
        "unique_outer_scenarios": len(collector.calls),
        "failed": collector.failed,
        "errors": collector.errors,
        "skipped": collector.skipped,
        "pytest_exit": int(code),
        "stdout": output.getvalue(),
        "seconds": time.monotonic() - started,
        "compiled_new_modules": len(list(HERE.glob("*.py"))),
        "nested_intentional_failure_is_outer_coverage": False,
        "original_PRE": "DENY/NOT_RUN",
        "executor": "OFF",
        "overall_status": "NOT_READY",
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    if (
        int(code)
        or len(collector.calls) != 38
        or collector.failed
        or collector.errors
        or collector.skipped
        or before != after
        or original != changed
        or initial != final
        or cache_before != cache_after
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--material"]:
        print(json.dumps(material(), sort_keys=True, indent=2))
    elif sys.argv[1:] == ["--preflight"]:
        preservation()
        import policy

        try:
            policy.deny_original_pre()
        except PermissionError as error:
            print(
                json.dumps(
                    {
                        "execution_admission": "DENY",
                        "effects": "NOT_RUN",
                        "reason": str(error),
                    },
                    sort_keys=True,
                )
            )
            raise SystemExit(2) from None
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("no arguments, --material or --preflight only")
