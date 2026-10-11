"""R11 paired saved-packet replay; nonadditive exposure, never SLA correction."""

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from overhead_observer import ObserverExposure, decoded_records

MAX_TOTAL = 256 * 1024**2
ON_FILES = (
    "observer-exposure.json",
    "phase-requests.jsonl",
    "pool-boundaries.json",
    "audit-transactions.jsonl",
    "samples.json",
    "samples.jsonl",
    "latency-summary.json",
    "r-controls.json",
    "r11-source-seal.json",
)
OFF_FILES = ("samples.json", "samples.jsonl", "latency-summary.json", "r-controls.json")


def union_ns(spans, lo=None, hi=None):
    known, merged, observed = [], [], False
    for start, end in spans:
        if start is None or end is None:
            continue
        if type(start) is not int or type(end) is not int or start < 0 or end < start:
            raise ValueError("invalid exposure clock")
        observed = True
        if lo is not None:
            start, end = max(lo, start), min(hi, end)
        if end >= start:
            known.append((start, end))
    if not known:
        return 0 if observed else None
    for start, end in sorted(known):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def mask_accounting(spans, lo, hi):
    """Two disjoint masks: observed coverage and unclassified envelope residual."""
    if type(lo) is not int or type(hi) is not int or lo < 0 or hi < lo:
        raise ValueError("invalid envelope")
    covered = union_ns(spans, lo, hi)
    if covered is None:
        return {
            "covered_ns": None,
            "unclassified_residual_ns": None,
            "envelope_ns": hi - lo,
            "conservation": "unobserved",
        }
    residual = hi - lo - covered
    assert residual >= 0 and covered + residual == hi - lo
    return {
        "covered_ns": covered,
        "unclassified_residual_ns": residual,
        "envelope_ns": hi - lo,
        "conservation": True,
    }


def quantile(values, q=0.95):
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid sample value")
    return sorted(values)[math.ceil(len(values) * q) - 1] if values else None


def identity(row):
    if (
        type(row["profile"]) is not int
        or row["profile"] not in (1, 10, 25, 50)
        or type(row["case"]) is not int
        or not 0 <= row["case"] < 100
        or row["operation"] not in ("admission", "submit", "status", "cancel")
    ):
        raise ValueError("sample identity")
    return f"tip054-latency-{row['profile']}-{row['case']}-{row['operation']}"


def phase_witnesses(rows, phase):
    """Positive reference-finalization coverage, not a handoff/CPU assertion."""
    names = ("phase.finish_phase", "phase.serialize", "phase.write", "phase.flush")
    selected = {name: [r for r in rows if r["label"] == name] for name in names}
    if len(selected[names[0]]) != len(phase["phases"]) or any(
        len(selected[name]) != 1 for name in names[1:]
    ):
        raise ValueError("missing/duplicate reference-finalization witness")
    witnesses = [r for values in selected.values() for r in values]
    if any(
        r["origin"] != "post_http_reference"
        or r["reference_closed"] is not True
        or r["error_type"] is not None
        or r["start_ns"] is None
        or r["end_ns"] is None
        or r["start_ns"] < phase["end_ns"]
        for r in witnesses
    ):
        raise ValueError("reference-finalization clock/origin/outcome")
    serial, write, flush = (selected[name][0] for name in names[1:])
    if (
        any(r["end_ns"] > serial["start_ns"] for r in selected[names[0]])
        or serial["end_ns"] > write["start_ns"]
        or write["end_ns"] > flush["start_ns"]
    ):
        raise ValueError("reference-finalization order")
    return {name: len(values) for name, values in selected.items()}


def load(root, names):
    result, seals, total = {}, {}, 0
    root = root.resolve()
    for name in names:
        path = root / name
        size = path.stat().st_size
        total += size
        if path.resolve() != path or size > ObserverExposure.MAX_BYTES or total > MAX_TOTAL:
            raise ValueError("input path/byte bound")
        raw = path.read_bytes()
        if len(raw) != size:
            raise ValueError("changing input length")
        result[name] = (
            [json.loads(line) for line in raw.splitlines() if line]
            if name.endswith(".jsonl")
            else json.loads(raw)
        )
        seals[name] = {"bytes": size, "sha256": hashlib.sha256(raw).hexdigest()}
    return result, seals


def analyze(on, off):
    packet = on["observer-exposure.json"]
    records = decoded_records(packet)
    if not records or any(packet["integrity"].values()):
        raise ValueError("NEW actual-run exposure integrity")
    if (
        not on["r11-source-seal.json"]["unchanged"]
        or on["r11-source-seal.json"]["diagnostic_faults"]
    ):
        raise ValueError("source/finalization integrity")
    grouped = defaultdict(list)
    for row in records:
        if row["request_id"] is not None:
            grouped[row["request_id"]].append(row)
    phases = {r["request_id"]: r for r in on["phase-requests.jsonl"]}
    if len(phases) != len(on["phase-requests.jsonl"]):
        raise ValueError("duplicate phase request")
    orphaned = set(grouped) - set(phases)
    if orphaned:
        raise ValueError("observer request absent recorded HTTP population")
    transactions = defaultdict(list)
    for tx in on["audit-transactions.jsonl"]:
        transactions[tx["request_id"]].append(tx)
    output, cells = [], []
    for mode, data in (("ON", on), ("OFF", off)):
        samples = data["samples.json"]
        if samples != data["samples.jsonl"] or len(samples) > 1600:
            raise ValueError("sample representation/count")
        ids = [identity(r) for r in samples]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate sample identity")
        if mode == "ON" and set(ids) != set(phases):
            raise ValueError("HTTP phase/sample population mismatch")
        for sample in sorted(samples, key=identity):
            key = identity(sample)
            row = {
                "population": mode,
                "request_id": key,
                "sample": sample,
                "observer_exposure": None,
                "internal_scope": "unobserved",
            }
            if mode == "ON":
                phase = phases[key]
                lo, hi = phase["start_ns"], phase["end_ns"]
                if type(lo) is not int or type(hi) is not int or hi <= lo:
                    raise ValueError("recorded HTTP window")
                selected = grouped[key]
                witnesses = phase_witnesses(selected, phase)
                labels = {}
                for label in sorted({r["label"] for r in selected}):
                    spans = [(r["start_ns"], r["end_ns"]) for r in selected if r["label"] == label]
                    labels[label] = {
                        "n": len(spans),
                        "known_union_ns": union_ns(spans),
                        "HTTP_clipped_union_ns": union_ns(spans, lo, hi),
                    }
                spans = [(r["start_ns"], r["end_ns"]) for r in selected]
                pre = [(r["prepare_start_ns"], r["prepare_end_ns"]) for r in selected]
                post = [(r["finish_start_ns"], r["finish_end_ns"]) for r in selected]
                row.update(
                    {
                        "internal_scope": "observed_wall_not_CPU_or_cause",
                        "observer_exposure": {
                            "records": len(selected),
                            "labels": labels,
                            "all_known_union_ns": union_ns(spans),
                            "HTTP_clipped_union_ns": union_ns(spans, lo, hi),
                            "expected_postHTTP_union_ns": union_ns(
                                [
                                    (r["start_ns"], r["end_ns"])
                                    for r in selected
                                    if r["origin"] == "post_http_reference"
                                ]
                            ),
                            "partial_NEW_prepare_finish_union_ns": union_ns(pre + post),
                            "HTTP_mask": mask_accounting(spans, lo, hi),
                            "positive_finalization_witnesses": witnesses,
                            "censored": sum(
                                r["start_ns"] is None or r["end_ns"] is None for r in selected
                            ),
                        },
                        "any_commit_ack": any(
                            t["terminal_kind"] == "commit_ack" for t in transactions[key]
                        ),
                        "audited_commit_ack": any(
                            t["terminal_kind"] == "commit_ack" and t["append_spans"]
                            for t in transactions[key]
                        ),
                    }
                )
            output.append(row)
        for profile in (1, 10, 25, 50):
            for operation in ("admission", "submit", "status", "cancel"):
                selected = [
                    r for r in samples if r["profile"] == profile and r["operation"] == operation
                ]
                values = [r["elapsed_ms"] for r in selected]
                calculated = {
                    "concurrency": profile,
                    "operation": operation,
                    "samples": len(selected),
                    "failures": sum(not r["okay"] for r in selected),
                    "p50_ms": quantile(values, 0.5),
                    "p95_ms": quantile(values),
                    "p99_ms": quantile(values, 0.99),
                    "p95_limit_ms": 500 if operation == "admission" else 1000,
                }
                calculated["pass"] = (
                    len(selected) == 100
                    and calculated["failures"] == 0
                    and calculated["p95_ms"] <= calculated["p95_limit_ms"]
                )
                old = next(
                    r
                    for r in data["latency-summary.json"]["cells"]
                    if r["concurrency"] == profile and r["operation"] == operation
                )
                if calculated != old:
                    raise ValueError("original32-cell oracle mismatch")
                cohort = [
                    r
                    for r in output
                    if r["population"] == mode
                    and r["sample"]["profile"] == profile
                    and r["sample"]["operation"] == operation
                ]
                measured = [
                    r["observer_exposure"]["HTTP_clipped_union_ns"]
                    for r in cohort
                    if r["observer_exposure"] is not None
                    and r["observer_exposure"]["HTTP_clipped_union_ns"] is not None
                ]
                cells.append(
                    {
                        "population": mode,
                        **calculated,
                        "failed_ids": [identity(r) for r in selected if not r["okay"]],
                        "tail_ge_p95_ids": [
                            identity(r) for r in selected if r["elapsed_ms"] >= calculated["p95_ms"]
                        ],
                        "known_observer_request_n": len(measured),
                        "known_observer_clipped_p95_ns": quantile(measured),
                    }
                )
    summary = {
        "status": "DIAGNOSTIC_ONLY_NOT_RELEASE",
        "records": len(records),
        "cells": cells,
        "populations": {
            mode: {
                "n": len(data["samples.json"]),
                "errors": sum(not r["okay"] for r in data["samples.json"]),
                "missing": 1600 - len(data["samples.json"]),
            }
            for mode, data in (("ON", on), ("OFF", off))
        },
        "unassigned_origins": dict(
            Counter(r["origin"] for r in records if r["request_id"] is None)
        ),
        "whole_population_known_union_ns": union_ns(
            [(r["start_ns"], r["end_ns"]) for r in records]
        ),
        "assigned_known_union_ns": union_ns(
            [(r["start_ns"], r["end_ns"]) for r in records if r["request_id"] is not None]
        ),
        "unassigned_known_union_ns": union_ns(
            [(r["start_ns"], r["end_ns"]) for r in records if r["request_id"] is None]
        ),
        "whole_HTTP_mask": mask_accounting(
            [(r["start_ns"], r["end_ns"]) for r in records],
            min(r["start_ns"] for r in phases.values()),
            max(r["end_ns"] for r in phases.values()),
        ),
        "exclusive_label_exposure": (
            "UNRESOLVED: no exclusive-child or CPU inference; reported label unions overlap."
        ),
        "standalone_assigned_records": 0,
        "integrity": packet["integrity"],
        "censorship": packet["censorship"],
        "limits": [
            "Observer-only spans nest; union is nonadditive wall coverage, "
            "not CPU or isolated overhead.",
            "PostHTTP exposure occurs before unchanged reference flush/return; "
            "OFF has no exposure clocks.",
            "NEW prepare/finish clocks omit outer dispatch/clock/final-assignment work; "
            "not complete collector overhead.",
            "No SLA correction, old bare-cost allocation, physical ownership bridge "
            "or causal gain from serial pair.",
        ],
    }
    return output, summary


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: analyze.py ON-run-dir OFF-run-dir NEW-analysis-dir")
    on_root, off_root, output = map(Path, sys.argv[1:])
    if output.exists() or output.resolve() != output.absolute() or output == output.parent:
        raise ValueError("NEW nonsymlink analysis output required")
    on, on_seals = load(on_root, ON_FILES)
    off, off_seals = load(off_root, OFF_FILES)
    rows, summary = analyze(on, off)
    _, on_after = load(on_root, ON_FILES)
    _, off_after = load(off_root, OFF_FILES)
    if (on_seals, off_seals) != (on_after, off_after):
        raise ValueError("input changed during paired replay")
    packets = {
        "requests.jsonl": "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for r in rows
        ),
        "failed.jsonl": "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for r in rows
            if not r["sample"]["okay"]
        ),
        "summary.json": json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        "provenance.json": json.dumps(
            {
                "ON": on_seals,
                "OFF": off_seals,
                "before_after_equal": True,
                "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
        + "\n",
    }
    if sum(len(value.encode()) for value in packets.values()) > ObserverExposure.MAX_BYTES:
        raise ValueError("NEW paired output cap")
    output.mkdir()
    for name, value in packets.items():
        with (output / name).open("x") as stream:
            stream.write(value)
    print(
        json.dumps(
            {
                "requests": len(rows),
                "files": {
                    name: hashlib.sha256(value.encode()).hexdigest()
                    for name, value in packets.items()
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
