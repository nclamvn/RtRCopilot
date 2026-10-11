"""Offline R diagnostic accounting; never sum independently ranked percentiles."""

import json
import math
import sys
from collections import Counter
from pathlib import Path

root, off_id, on_id = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
off, on = root / off_id, root / on_id
assert not (root / (off_id + "_" + on_id + "_pair-summary.json")).exists()


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def stats(values):
    if not values:
        return {"samples": 0}
    values = sorted(values)
    return {
        "samples": len(values),
        "min": values[0],
        "p50": values[math.ceil(len(values) * 0.5) - 1],
        "p95": values[math.ceil(len(values) * 0.95) - 1],
        "max": values[-1],
        "sum": sum(values),
    }


requests, waits = lines(on / "phase-requests.jsonl"), lines(on / "pg-waits.jsonl")
cells = []
for profile in (1, 10, 25, 50):
    for operation in ("admission", "submit", "status", "cancel"):
        subset = [r for r in requests if r["profile"] == profile and r["operation"] == operation]
        phase_names = sorted({p["name"] for r in subset for p in r["phases"]})
        perphase = []
        for name in phase_names:
            rows = []
            for request in subset:
                spans = [p for p in request["phases"] if p["name"] == name and "inclusive_ms" in p]
                if spans:
                    rows.append(
                        {
                            "calls": len(spans),
                            **{
                                key: sum(p[key] for p in spans)
                                for key in (
                                    "inclusive_ms",
                                    "exclusive_ms",
                                    "inclusive_sql_started",
                                    "exclusive_sql_started",
                                    "inclusive_sql_ms",
                                    "exclusive_sql_ms",
                                )
                            },
                        }
                    )
            perphase.append(
                {
                    "name": name,
                    **{
                        key: stats([r[key] for r in rows])
                        for key in (
                            "calls",
                            "inclusive_ms",
                            "exclusive_ms",
                            "inclusive_sql_started",
                            "exclusive_sql_started",
                            "inclusive_sql_ms",
                            "exclusive_sql_ms",
                        )
                    },
                }
            )
        pool = {}
        for kind in ("connect", "_do_get", "_create_connection"):
            durations, counts, failures = [], [], Counter()
            for request in subset:
                events = [p for p in request["pool"] if p["kind"] == kind]
                counts.append(len(events))
                durations.append(
                    sum(
                        (p["end_ns"] - p["start_ns"]) / 1e6
                        for p in events
                        if p["end_ns"] is not None
                    )
                )
                failures.update(p["error_type"] for p in events if p["error_type"] is not None)
            pool[kind] = {
                "attempt_count": stats(counts),
                "per_request_total_ms": stats(durations),
                "failed_types": dict(failures),
            }
        statement_classes = Counter(s["statement_class"] for r in subset for s in r["sql"])
        lock_envelopes = [
            s
            for r in subset
            for s in r["sql"]
            if s["statement_class"]
            in {"advisory_exclusive", "advisory_shared", "row_share", "row_update"}
        ]
        correlated = []
        for request in subset:
            for sql in request["sql"]:
                if sql["pid"] is None:
                    continue
                hits = [
                    w["tick_ns"]
                    for w in waits
                    if sql["start_ns"] <= w["tick_ns"] <= (sql["end_ns"] or request["end_ns"])
                    and any(
                        a["pid"] == sql["pid"] and a["wait_event_type"] == "Lock"
                        for a in w.get("activity", [])
                    )
                ]
                if hits:
                    correlated.append(
                        {
                            "request_id": request["request_id"],
                            "phase_ids": sql["phase_ids"],
                            "pid": sql["pid"],
                            "statement_class": sql["statement_class"],
                            "static_sha256": sql["static_sha256"],
                            "observed_lock_ticks": len(hits),
                            "first_last_observed_span_ms": (max(hits) - min(hits)) / 1e6,
                        }
                    )
        cells.append(
            {
                "profile": profile,
                "operation": operation,
                "requests": len(subset),
                "http_statuses": dict(Counter(str(r.get("http_status")) for r in subset)),
                "queries_started": stats([len(r["sql"]) for r in subset]),
                "queries_unfinished": sum(s["end_ns"] is None for r in subset for s in r["sql"]),
                "sql_total_ms": stats(
                    [
                        sum(
                            (s["end_ns"] - s["start_ns"]) / 1e6
                            for s in r["sql"]
                            if s["end_ns"] is not None
                        )
                        for r in subset
                    ]
                ),
                "connection_hold_ms": stats(
                    [sum((h["end_ns"] - h["start_ns"]) / 1e6 for h in r["holds"]) for r in subset]
                ),
                "statement_class_counts": dict(statement_classes),
                "lock_statement_envelope_ms": stats(
                    [
                        (s["end_ns"] - s["start_ns"]) / 1e6
                        for s in lock_envelopes
                        if s["end_ns"] is not None
                    ]
                ),
                "pool": pool,
                "phases": perphase,
                "actual_pg_lock_correlations": correlated,
            }
        )

off_report, on_report = read(off / "latency-summary.json"), read(on / "latency-summary.json")
deltas = []
for original, observed in zip(off_report["cells"], on_report["cells"], strict=True):
    assert (
        original["concurrency"] == observed["concurrency"]
        and original["operation"] == observed["operation"]
    )
    deltas.append(
        {
            "concurrency": original["concurrency"],
            "operation": original["operation"],
            "off_samples": original["samples"],
            "on_samples": observed["samples"],
            "off_failures": original["failures"],
            "on_failures": observed["failures"],
            "off_p95_ms": original["p95_ms"],
            "on_p95_ms": observed["p95_ms"],
            "p95_delta_ms": (observed["p95_ms"] - original["p95_ms"])
            if original["p95_ms"] is not None and observed["p95_ms"] is not None
            else None,
        }
    )
cost = read(on / "phase-recorder-cost.json")
report = {
    "off_status": off_report["status"],
    "on_status": on_report["status"],
    "source_and_helper_unchanged_each": all(
        read(g / "source-before.json") == read(g / "source-after.json") for g in (off, on)
    ),
    "source_and_helper_equal_between_pair": read(off / "source-before.json")
    == read(on / "source-before.json"),
    "original_samples_jsonl_equal_json": all(
        lines(g / "samples.jsonl") == read(g / "samples.json") for g in (off, on)
    ),
    "observer_requests_match_completed_http": len(requests) == len(lines(on / "samples.jsonl")),
    "observer": read(on / "phase-observer-summary.json"),
    "monitor": read(on / "pg-monitor-summary.json"),
    "monitor_process": read(on / "monitor-process.json"),
    "latency_deltas": deltas,
    "phase_cells": cells,
    "observer_serialization_ms": stats([c["serialize_ms"] for c in cost]),
    "observer_append_flush_ms": stats([c["append_flush_ms"] for c in cost]),
    "backend_pids_missing": sum(s["pid"] is None for r in requests for s in r["sql"]),
    "max_application_checked_out": max(
        (p[t]["checked_out"] for r in requests for p in r["pool"] for t in ("before", "after")),
        default=0,
    ),
    "sampled_actual_lock_rows": sum(len(w.get("locks", [])) for w in waits),
    "limits": (
        "Paired independent fresh DB runs, not randomized causal attribution. OFF "
        "unchanged-oracle load is acceptance authority. ON observes extra wrapper/recorder/"
        "monitor CPU/IO/SQL overhead. Inclusive spans overlap; exclusive spans subtract "
        "direct child interval union; independently ranked p95s are not additive. "
        "First/last lock-observation spans are sampled envelopes, not exact continuous "
        "wait duration; no lock sample does not imply zero lock wait. "
        "No body/parameter/SQL text logging; static SQL digest/class only."
    ),
}
output = root / (off_id + "_" + on_id + "_pair-summary.json")
output.write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != "phase_cells"}, indent=2))
