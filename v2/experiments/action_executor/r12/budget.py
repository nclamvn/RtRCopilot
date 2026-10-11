"""One bounded R11 trace budget replay; no SDK/product/helper imports."""

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

BASE = "v2/experiments/action_executor/"
RAW = BASE + "raw/tip054-4b-full-20261007-r5qa1/r11_on_r1/run/"
INPUTS = (
    (
        RAW + "observer-exposure.json",
        109793011,
        "aaf62099410770c770a6c736cc11f0629dac738688f2767fae96c1a5f34f2151",
    ),
    (
        RAW + "samples.json",
        269964,
        "92fa9918945e05eb7c02d1baa3d57ee367d0e6d3caefe67b25b3d1af88d89b9c",
    ),
    (
        RAW + "latency-summary.json",
        4884,
        "98e7851ddee8f863345cdf1e5c54cf5511ef6b66e0e6c6fe58d20e8eafedd6de",
    ),
    (
        RAW + "pool-boundaries.json",
        18826217,
        "42e30537f07064e320dd7ac170d3677f4011e9205e5c87c0b268d71a977b416e",
    ),
    (
        RAW + "phase-requests.jsonl",
        12696211,
        "4c784bb1f5952eba6029bdd39373a46e6b418347708fc10ec10526459ea80d69",
    ),
    (
        RAW + "phase-observer-summary.json",
        441,
        "ae1e4d85896a5419af8cdf8f213e71a54dfb3836da777ada8c244b2cdb462ebc",
    ),
    (
        RAW + "audit-observer-summary.json",
        471,
        "55f94f58ec6bcce1d8eda440cc3e35595608269ba96bc66c25aea21c85739007",
    ),
    (
        BASE + "r11/overhead_observer.py",
        21168,
        "e64795c23bb5ef848c4472ff2e444cbf1628cea5bd44b5d633f1cf2fad4c0cdf",
    ),
    (
        BASE + "r9/pool_boundary_observer.py",
        19708,
        "1029c26e9ec2b50002835435e67262becfc0c6b320fcb183945e931ede8fd914",
    ),
    (
        BASE + "r/phase_profiler.py",
        14193,
        "2441a038959ecac8dde2edc60b7b90c9f1f7b975615626c14106662697ef26db",
    ),
    (
        BASE + "r/r2/audit_tail_observer.py",
        11299,
        "4597119a3a68784a9b780190c04dbbb95d2ab04893f36cdd77270a220c00da95",
    ),
)
MAX_INPUT = 256 * 1024**2
MAX_OUTPUT = 5 * 1024**2
OMITTED = {"R9.WeakIds.get", "R9.request", "R9.resource", "R9.begin", "R9.finish"}


def seal(root):
    result, total = {}, 0
    for name, size, expected in INPUTS:
        path = root / name
        if path.is_symlink() or path.resolve() != path or path.stat().st_size != size:
            raise ValueError("fixed input path/size mismatch")
        total += size
        if total > MAX_INPUT:
            raise ValueError("aggregate input cap")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024**2), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("fixed input digest mismatch")
        result[name] = {"bytes": size, "sha256": expected}
    return result


def read(root, name):
    raw = (root / (RAW + name)).read_bytes()
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in raw.splitlines() if line]
    return json.loads(raw)


def request_id(sample):
    return f"tip054-latency-{sample['profile']}-{sample['case']}-{sample['operation']}"


def p(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1] if values else None


def ceil_ratio(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def budget(root, before):
    checks = {"B1_fixed_inputs_caps": sum(item["bytes"] for item in before.values()) <= MAX_INPUT}
    packet = read(root, "observer-exposure.json")
    label_counts = Counter(packet["labels"][row[1]] for row in packet["records"])
    origins = Counter(packet["origins"][row[8]] for row in packet["records"])
    retained = len(packet["records"])
    loss = packet["integrity"]["dropped"]
    omitted = sum(label_counts[name] for name in OMITTED)
    outer = sum(n for name, n in label_counts.items() if name.startswith("R9.recording"))
    reference = sum(n for name, n in label_counts.items() if name.startswith(("phase.", "audit.")))
    checks["B2_capped_partition_unknowns"] = (
        retained == 800000
        and loss == 17506
        and omitted + outer + reference == retained
        and not any(value for name, value in packet["integrity"].items() if name != "dropped")
    )
    raw_partition = {
        "retained": retained,
        "omitted_nested_helpers": omitted,
        "recording_callbacks": outer,
        "reference": reference,
        "labels": dict(sorted(label_counts.items())),
        "origins": dict(origins),
        "censorship": packet["censorship"],
        "unknown_loss": loss,
        "loss_label_request_assignment": None,
        "complete": False,
    }
    del packet
    samples = read(root, "samples.json")
    summary = read(root, "latency-summary.json")
    cells = []
    for concurrency in (1, 10, 25, 50):
        for operation in ("admission", "submit", "status", "cancel"):
            rows = [
                s for s in samples if s["profile"] == concurrency and s["operation"] == operation
            ]
            values = [s["elapsed_ms"] for s in rows]
            cell = {
                "concurrency": concurrency,
                "operation": operation,
                "samples": len(rows),
                "failures": sum(not r["okay"] for r in rows),
                "p50_ms": p(values, 0.5),
                "p95_ms": p(values, 0.95),
                "p99_ms": p(values, 0.99),
                "p95_limit_ms": 500 if operation == "admission" else 1000,
            }
            cell["pass"] = (
                len(rows) == 100
                and cell["failures"] == 0
                and cell["p95_ms"] <= cell["p95_limit_ms"]
            )
            cells.append(cell)
    failed = [request_id(s) for s in samples if not s["okay"]]
    observed = len(samples)
    checks["B3_all_samples_failures_oracles"] = (
        observed == 1394
        and len({request_id(s) for s in samples}) == observed
        and len(failed) == 121
        and 1600 - observed == 206
        and cells == summary["cells"]
    )
    pool = read(root, "pool-boundaries.json")
    events, ticks = len(pool["events"]), len(pool["ticks"])
    names = Counter(e["name"] for e in pool["events"])
    checks["B4_original_R9_reference_complete"] = (
        events == 49345 and ticks == 1625 and not any(pool["integrity"].values())
    )
    del pool
    phases = read(root, "phase-requests.jsonl")
    phase_summary = read(root, "phase-observer-summary.json")
    phase_calls = sum(len(r["phases"]) for r in phases)
    checks["B5_original_phase_reference_complete"] = (
        len(phases) == phase_summary["requests"] == observed
        and phase_calls == 15842
        and not phase_summary["dropped_events"]
        and not phase_summary["late_events"]
        and not phase_summary["sql_without_end"]
    )
    phase_max = {
        operation: max(len(r["phases"]) for r in phases if r["operation"] == operation)
        for operation in ("admission", "submit", "status", "cancel")
    }
    del phases
    audit = read(root, "audit-observer-summary.json")
    checks["B6_original_audit_reference_complete"] = (
        audit["transactions"] == 4266
        and audit["metrics_complete"]
        and sum(audit["terminal_kinds"].values()) == audit["transactions"]
    )
    eligible_old = retained + loss
    trace_selection_upper = eligible_old - omitted
    # The 206 missing calls and all newly changed scheduling outcomes are unknown.
    projected = ceil_ratio(trace_selection_upper * 1600, observed)
    byte_model = ceil_ratio(trace_selection_upper * 1600 * INPUTS[0][1], observed * retained)
    rough_source_subtotal = (
        6 * events + ticks + phase_calls + 3 * observed + 4 * audit["transactions"]
    )
    checks["B7_bounds_distinct_from_projection"] = (
        trace_selection_upper == 333585
        and projected == 382881
        and byte_model < 128 * 1024**2
        and rough_source_subtotal == 334783
    )
    models = {
        "old_trace_selection_upper_rows": trace_selection_upper,
        "bound_scope": (
            "ONLY old eligible callback trace; subtracts known retained omitted rows; "
            "not new workload bound"
        ),
        "conditional_1600_rate_rows": projected,
        "conditional_1600_byte_model": byte_model,
        "conditional_double_rate_rows": ceil_ratio(trace_selection_upper * 3200, observed),
        "source_accounting_subtotal": rough_source_subtotal,
        "source_subtotal_limit": (
            "6E is coarse, queue.get has7 calls; false predicates/no-event calls "
            "and duplicate emits excluded; NOT upper bound"
        ),
        "source_selected_reference_count": phase_calls + 3 * observed + 4 * audit["transactions"],
        "future_full_1600_guarantee": False,
        "unknown_missing_calls": 206,
        "omitted_helpers_cost": "UNMEASURED_SEPARATELY_NOT_ZERO",
        "no_overhead_gain_SLA_correction_or_product_cause": True,
    }
    after = seal(root)
    checks["B8_after_seal_exclusive_output"] = before == after
    if not all(checks.values()) or len(checks) != 8:
        raise ValueError("budget primitive control failed")
    return {
        "status": "BUDGET_ONLY_NOT_COMPLETE_MEASUREMENT",
        "primitive_checks": checks,
        "inputs_before_after_equal": True,
        "input_bytes": sum(x["bytes"] for x in before.values()),
        "raw_partition": raw_partition,
        "original_reference": {
            "events": events,
            "ticks": ticks,
            "event_names": dict(names),
            "phase_calls": phase_calls,
            "max_phases_by_operation": phase_max,
            "audit": audit,
        },
        "models": models,
        "sample_population": {
            "observed": observed,
            "failed_ids": sorted(failed),
            "errors_by_operation": dict(Counter(s["operation"] for s in samples if not s["okay"])),
            "missing": 1600 - observed,
            "cells": cells,
        },
    }


def main():
    own = Path(__file__).resolve().parent
    if len(sys.argv) != 2:
        raise SystemExit("usage: budget.py NEW-r12-output-dir")
    output = Path(sys.argv[1]).absolute()
    if output.exists() or output.resolve() != output or output.parent != own:
        raise ValueError("fresh direct R12 output required")
    root = own.parents[3]
    before = seal(root)  # Pin every selected file before parsing any JSON.
    output.mkdir()
    try:
        result = budget(root, before)
        packets = {"inputs.json": before, "summary.json": result}
        encoded = {
            name: (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
            for name, value in packets.items()
        }
        if sum(map(len, encoded.values())) > MAX_OUTPUT:
            raise ValueError("budget output cap")
        for name, raw in encoded.items():
            with (output / name).open("xb") as stream:
                stream.write(raw)
        print(
            json.dumps(
                {
                    "status": "PASS_8_BUDGET_CHECKS",
                    "output": str(output),
                    "files": {
                        name: hashlib.sha256(raw).hexdigest() for name, raw in encoded.items()
                    },
                },
                sort_keys=True,
            )
        )
    except BaseException as error:
        with (output / "failure.json").open("x") as stream:
            json.dump(
                {"error_type": type(error).__name__, "message": str(error), "retry": False}, stream
            )
        raise


if __name__ == "__main__":
    main()
