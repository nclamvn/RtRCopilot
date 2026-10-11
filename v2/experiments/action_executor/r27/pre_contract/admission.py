"""Complete known scratch accounting and unconditional original PRE predispatch denial."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, cast

import bridge

ROOT = bridge.ROOT
CONTRACT = ROOT / "v2/experiments/action_executor/r25/contract.json"
CONTRACT_SHA = "43e24fdef2e1acfd3f00b409e9fd5a46853c4105d4b3c71f329b93c6f1eccbcc"
EXTERNAL_PINS = {
    (
        "/Users/os/.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/"
        "lib/python3.12/tempfile.py"
    ): "2eea4401f4f29d0d3647ed6fc8bcf6aa1daf879c8aa407a8ea310edac9dfc317",
    str(
        ROOT / "v2/apps/backend/.venv/lib/python3.12/site-packages/_pytest/tmpdir.py"
    ): "236918c090160c1f6b935e162ff44ab273a700221d5f40ac15892be75e4503ee",
    str(
        ROOT / "v2/apps/backend/.venv/lib/python3.12/site-packages/_pytest/pathlib.py"
    ): "8127808359baaa711775862b32bfbe0a7e5c16a2e8c9923d60ddd45f031b66fa",
}


def guard() -> None:
    bridge.guard()
    for name, expected in EXTERNAL_PINS.items():
        if hashlib.sha256(bridge.bounded(Path(name))).hexdigest() != expected:
            raise ValueError("native temp producer source drift")


def packet_lifetime() -> dict[str, object]:
    """Pure original packet calls plus source-bound mutation expressions; no suite run."""
    session = bridge.preview("full")
    first = [(a.name, len(a.raw), hashlib.sha256(a.raw).hexdigest()) for a in session.attempts]
    root = bridge.LogicalTempPath(session) / "r21_http_e1"
    source = bridge.AREA / "r21/test_r21_offline.py"
    tree = ast.parse(bridge.bounded(source))
    method = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.name == "test_packet_summary_controls_oracle_and_corruption"
    )
    loop = next(n for n in method.body if isinstance(n, ast.For))
    changes = cast(
        tuple[tuple[str, Callable[[dict[str, object]], object]], ...],
        eval(compile(ast.Expression(loop.iter), str(source), "eval"), {}),
    )
    for target, change in changes:
        path = root / target
        saved = path.read_bytes()
        data = cast(dict[str, object], json.loads(saved))
        change(data)
        path.write_text(json.dumps(data))
        path.write_bytes(saved)
    journal = root / "run/samples.jsonl"
    journal.write_bytes(journal.read_bytes().rstrip(b"\n"))
    session.invoke("four")
    (root / "run/latency-summary.json").unlink()
    port = cast(bridge.MemoryPreview, session.port)
    return {
        "scope": "unchanged packet producer; original mutation expressions; not six test execution",
        "first_packet": first,
        "whole_write_attempts": len(session.attempts),
        "lifetime_payload_bytes": sum(len(a.raw) for a in session.attempts),
        "final_live_payload_bytes": sum(len(raw) for raw in port.files.values()),
        "largest_whole_write": max(len(a.raw) for a in session.attempts),
        "mutation_restore_writes": len(changes) * 2,
        "journal_truncating_overwrite": 1,
        "summary_deletion": 1,
        "names_lifetime": sorted({a.name for a in session.attempts}),
        "original_default_UTF8_bytes": True,
        "marker_namespace_note": (
            "marker stores binding/contract hashes, not path text; identical binding bytes "
            "produce identical marker bytes here; generalized path-bearing records may differ"
        ),
    }


def manifest() -> dict[str, object]:
    guard()
    if hashlib.sha256(bridge.bounded(CONTRACT)).hexdigest() != CONTRACT_SHA:
        raise ValueError("unchanged adopted diagnostic codec contract")
    packets = {}
    for mode in ("full", "four", "one"):
        session = bridge.preview(mode)
        packets[mode] = {
            a.name: {"bytes": len(a.raw), "sha256": hashlib.sha256(a.raw).hexdigest()}
            for a in session.attempts
        }
    return {
        "schema": "r27-pre-contract-diagnostic-v1",
        "source_pins": bridge.PINS,
        "packets": packets,
        "packet_lifetime": packet_lifetime(),
        "known_six_suite_lower_bound": {
            "successful_explicit_writes": 43,
            "distinct_lifetime_files": 14,
            "temporary_directory_roots": 6,
            "failed_exclusive_open_attempts": 1,
            "explicit_summary_delete": 1,
            "missing_drop_unlink_attempts": 4,
            "final_files_subject_to_temp_cleanup": 13,
            "breakdown": (
                "corruption35; linked binding+marker2; fake shell drop appends2; collection/XML4"
            ),
            "complete_platform_upper_bound": False,
        },
        "launcher_lower_bound": {"nominal_files": 125, "source_cap_producer": 75, "closure": 1},
        "original_cap": (
            "current file stat sum inside epoch; TMPDIR and basetemp are inside while live; "
            ".02s polls/postchecks may miss overwritten/deleted payloads; "
            "no lifetime/no-refund proof"
        ),
        "strengthened_contract": (
            "same10MiB; packet+physical prewrite/attempt accounting; deletion never refunds; "
            "32 lifetime files/PRE32 records,20families,16KiB metadata unchanged"
        ),
        "diagnostic_mapping_only": dict(bridge.FAMILIES),
        "unsupported_routes": [
            "six genuine tempfile constructors/probe4-byte write+unlink/rmtree failure paths",
            "given-basetemp pytest mkdir/rm_rf/native numbered tmp_path/current symlink; "
            "not default .lock branch",
            "original native fake-shell printf drops and arbitrary subprocess stdout/stderr",
            "all original PRE launcher Docker/Linux supervisor/control/check/native outputs",
            "unknown pytest/platform/plugin warning/exception/temp failure writes",
        ],
        "synthetic_settings": (
            "constructor is not itself a filesystem writer; envelope creates no seed"
        ),
        "family_adoption": "NONE: scratch inputs are not genuine measurement journal/final_samples",
        "execution_admission": "DENY",
        "next_material_decision": (
            "stage-specific PRE synthetic-input variant within same shared10MiB/no-refund; "
            "source-derived whole-write/file/metadata bounds "
            "plus every deleted/native scratch route; "
            "NOT adopted, no count-only grant or uncapped second plane"
        ),
    }


def dispatch_pre(_: object = None) -> NoReturn:
    guard()
    raise PermissionError(
        "PRE DENY before root/child/marker: uncovered scratch and finite-domain conflicts"
    )
