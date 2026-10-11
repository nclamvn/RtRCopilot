"""Bounded stdlib replay of direct clocks; no causal or SLA correction."""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

MAX_FILE = 160 * 1024 * 1024
MAX_TOTAL = 320 * 1024 * 1024
NAMES = (
    "pool.connect",
    "pool._do_get",
    "pool._create_connection",
    "queue.get",
    "adapter._async_ping",
    "adapter._commit_and_discard",
    "adapter._rollback_and_discard",
    "AsyncSession.close",
    "AsyncConnection.close",
    "owner.join_terminal",
)
INTEGRITY_KEYS = {
    "dropped",
    "late",
    "callback_errors",
    "unmapped_wake",
    "unweak_resource",
    "sampler_limit",
    "costs_dropped",
    "late_events",
    "open_events",
    "pending_getters",
    "timer_active",
}


def intervals(rows, lo=None, hi=None):
    result = []
    for row in rows:
        start, end = row["start_ns"], row["end_ns"]
        if end is None:
            continue
        if end < start:
            raise ValueError("negative closed clock")
        if lo is not None:
            start, end = max(start, lo), min(end, hi)
        if end > start:
            result.append((start, end))
    result.sort()
    merged = []
    for start, end in result:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def union_ms(rows, lo=None, hi=None):
    return sum(end - start for start, end in intervals(rows, lo, hi)) / 1e6


def quantile(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def validate_boundaries(phases, events):
    by_span = {row["span_id"]: row for row in events}
    if len(by_span) != len(events) or sorted(by_span) != list(range(len(events))):
        raise ValueError("numeric span IDs not unique/contiguous")
    for row in events:
        if not isinstance(row["task_id"], int) or row["task_id"] <= 0:
            raise ValueError("missing observed task identity")
        if not isinstance(row["resource_id"], int) or row["resource_id"] <= 0:
            raise ValueError("missing observed resource identity")
        if row["resource_kind"] not in {"object", "driver"}:
            raise ValueError("resource identity kind unknown")
        if row["error_type"] is not None and not isinstance(row["error_type"], str):
            raise ValueError("outcome type schema invalid")
        if row["end_ns"] is not None and row["end_ns"] < row["start_ns"]:
            raise ValueError("negative event lifetime")
        for parent_id in row["parent_ids"]:
            if parent_id not in by_span or parent_id >= row["span_id"]:
                raise ValueError("unknown/nonpreceding parent span")
            parent = by_span[parent_id]
            if parent["start_ns"] > row["start_ns"]:
                raise ValueError("child begins before parent")
            if (
                parent["end_ns"] is not None
                and row["end_ns"] is not None
                and parent["end_ns"] < row["end_ns"]
            ):
                raise ValueError("child ends after parent")
        if row["name"] == "queue.wake_ready" and row.get("mapping") == "unique":
            getter_id = row["getter_span_id"]
            if getter_id not in by_span or getter_id >= row["span_id"]:
                raise ValueError("unknown getter span")
            getter = by_span[getter_id]
            if (
                getter["name"] != "queue.get"
                or getter["task_id"] != row["getter_task_id"]
                or getter["resource_id"] != row["resource_id"]
                or getter["request_id"] != row["getter_request_id"]
                or not isinstance(row["future_id"], int)
                or row["future_id"] <= 0
            ):
                raise ValueError("getter/Future identity mapping inconsistent")
    grouped = defaultdict(list)
    for row in events:
        grouped[row["request_id"]].append(row)
    for request in phases:
        for kind in ("connect", "_do_get", "_create_connection"):
            original = [row for row in request["pool"] if row["kind"] == kind]
            observed = [
                row for row in grouped[request["request_id"]] if row["name"] == "pool." + kind
            ]

            def signature(rows):
                return Counter((row["end_ns"] is not None, row["error_type"]) for row in rows)

            if signature(original) != signature(observed):
                raise ValueError("per-HTTP original/new pool boundary completeness mismatch")


def load(root):
    filenames = (
        "pool-boundaries.json",
        "phase-requests.jsonl",
        "samples.json",
        "samples.jsonl",
        "latency-summary.json",
        "audit-transactions.jsonl",
        "r9-source-seal.json",
    )
    parsed, seals, total = {}, {}, 0
    for name in filenames:
        path = root / name
        size = path.stat().st_size
        total += size
        if size > MAX_FILE or total > MAX_TOTAL:
            raise ValueError("input byte bounds exceeded")
        raw = path.read_bytes()
        seals[name] = {"bytes": size, "sha256": hashlib.sha256(raw).hexdigest()}
        parsed[name] = (
            [json.loads(line) for line in raw.splitlines()]
            if name.endswith(".jsonl")
            else json.loads(raw)
        )
    if parsed["samples.json"] != parsed["samples.jsonl"]:
        raise ValueError("original sample representations differ")
    return parsed, seals


def analyze(data):
    samples, phases = data["samples.json"], data["phase-requests.jsonl"]
    boundary = data["pool-boundaries.json"]
    if len(samples) > 1600 or len(phases) > 1600 or len(boundary["events"]) > 250000:
        raise ValueError("count bounds exceeded")
    if len(boundary["ticks"]) > 9000 or len(boundary["costs"]) > 510000:
        raise ValueError("observer count bounds exceeded")
    validate_boundaries(phases, boundary["events"])
    sample_map = {}
    for row in samples:
        key = f"tip054-latency-{row['profile']}-{row['case']}-{row['operation']}"
        if key in sample_map:
            raise ValueError("duplicate sample identity")
        sample_map[key] = row
    phase_map = {row["request_id"]: row for row in phases}
    if len(phase_map) != len(phases) or phase_map.keys() != sample_map.keys():
        raise ValueError("phase/sample population not bijective")
    grouped, audited, wakes = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in boundary["events"]:
        if row["request_id"] not in sample_map:
            raise ValueError("unmapped numeric boundary request")
        grouped[row["request_id"]].append(row)
        if row["name"] == "queue.wake_ready" and row.get("mapping") == "unique":
            getter_key = row["getter_request_id"]
            if getter_key not in sample_map:
                raise ValueError("unmapped proved getter request")
            wakes[getter_key].append(row)
    for row in data["audit-transactions.jsonl"]:
        if row["request_id"] not in sample_map:
            raise ValueError("unmapped audit request")
        audited[row["request_id"]].append(row)
    results, failures, cells = [], [], []
    for key in sorted(sample_map):
        sample, phase, events = sample_map[key], phase_map[key], grouped[key]
        start, end = phase["start_ns"], phase["end_ns"]
        if end is None:
            raise ValueError("unclosed original HTTP envelope")
        row = {"request_id": key, "sample": sample, "http_phase_ns": [start, end], "boundaries": {}}
        for name in NAMES:
            selected = [item for item in events if item["name"] == name]
            closed = [item for item in selected if item["end_ns"] is not None]
            row["boundaries"][name] = {
                "started": len(selected),
                "closed": len(closed),
                "open": len(selected) - len(closed),
                "closed_coverage_ms": union_ms(closed, start, end) if closed else None,
                "errors": dict(
                    sorted(
                        Counter(
                            item["error_type"] for item in selected if item["error_type"]
                        ).items()
                    )
                ),
            }
        # Readiness->consumer get_nowait is a scheduling/competition envelope,
        # not exact enqueue, resource reservation or isolated scheduler time.
        ready = []
        for wake in wakes[key]:
            if wake["getter_request_id"] != key or wake["end_ns"] is None:
                continue
            resumed = [
                item
                for item in events
                if item["name"] == "queue.get_nowait"
                and item["task_id"] == wake["getter_task_id"]
                and wake["getter_span_id"] in item["parent_ids"]
                and item["start_ns"] >= wake["end_ns"]
            ]
            if resumed:
                item = min(resumed, key=lambda item: item["start_ns"])
                ready.append(
                    {
                        "wake_span_id": wake["span_id"],
                        "consumer_span_id": item["span_id"],
                        "future_id": wake["future_id"],
                        "getter_task_id": wake["getter_task_id"],
                        "returned_record_id": item.get("result_resource_id"),
                        "ready_to_consumer_ms": (item["start_ns"] - wake["end_ns"]) / 1e6,
                    }
                )
        row["wake_ready_envelopes"] = ready
        row["physical_holds"] = {
            "closed": len(phase["holds"]),
            "closed_union_ms": union_ms(phase["holds"], start, end) if phase["holds"] else None,
        }
        tx = audited[key]
        row["known_terminals"] = dict(sorted(Counter(item["terminal_kind"] for item in tx).items()))
        row["audited_commit_ack"] = any(
            item["terminal_kind"] == "commit_ack" and item["append_spans"] for item in tx
        )
        row["any_commit_ack"] = any(item["terminal_kind"] == "commit_ack" for item in tx)
        active_ticks = [
            tick["actual_ns"] - tick["scheduled_ns"]
            for tick in boundary["ticks"]
            if start <= tick["actual_ns"] <= end
        ]
        row["observed_tick_max_lateness_ms"] = max(active_ticks) / 1e6 if active_ticks else None
        row["terminal_scope"] = [
            {
                field: item.get(field)
                for field in (
                    "span_id",
                    "name",
                    "task_id",
                    "owner_task_id",
                    "terminal_task_id",
                    "captured_resource_id",
                    "start_ns",
                    "end_ns",
                    "error_type",
                )
            }
            for item in events
            if item["name"].startswith("owner.")
            or item["name"] in {"AsyncSession.close", "AsyncConnection.close"}
        ]
        row["failed_events"] = [item for item in events if item["error_type"]]
        results.append(row)
        if not sample["okay"]:
            failures.append(row)
    for profile in (1, 10, 25, 50):
        for operation in ("admission", "submit", "status", "cancel"):
            rows = [
                row
                for row in results
                if row["sample"]["profile"] == profile and row["sample"]["operation"] == operation
            ]
            threshold = quantile([row["sample"]["elapsed_ms"] for row in rows])
            tail = (
                [row["request_id"] for row in rows if row["sample"]["elapsed_ms"] >= threshold]
                if threshold is not None
                else []
            )
            cell = {
                "concurrency": profile,
                "operation": operation,
                "samples": len(rows),
                "failures": sum(not row["sample"]["okay"] for row in rows),
                "p95_ms": threshold,
                "tail_ge_nearest_rank95_ids": tail,
                "direct_boundaries": {},
            }
            limit = 500 if operation == "admission" else 1000
            cell["pass"] = len(rows) == 100 and cell["failures"] == 0 and threshold <= limit
            original = next(
                item
                for item in data["latency-summary.json"]["cells"]
                if item["concurrency"] == profile and item["operation"] == operation
            )
            if any(
                cell[field] != original[field]
                for field in ("samples", "failures", "p95_ms", "pass")
            ):
                raise ValueError("original cell oracle mismatch")
            for name in NAMES:
                known = [
                    row["boundaries"][name]["closed_coverage_ms"]
                    for row in rows
                    if row["boundaries"][name]["closed_coverage_ms"] is not None
                ]
                cell["direct_boundaries"][name] = {
                    "known_request_count": len(known),
                    "known_coverage_p95_ms": quantile(known),
                }
            cells.append(cell)
    integrity = boundary["integrity"]
    if set(integrity) != INTEGRITY_KEYS:
        raise ValueError("observer integrity schema changed")
    return (
        results,
        failures,
        {
            "requests": len(results),
            "failed_requests": len(failures),
            "cells": cells,
            "observer_integrity": integrity,
            "observer_integrity_pass": not any(integrity.values()),
            "original_pool_boundary_multiset_completeness_and_span_graph": True,
            "recording_cost_ns": {
                "count": len(boundary["costs"]),
                "sum": sum(boundary["costs"]),
                "p95": quantile(boundary["costs"]),
            },
            "limits": [
                "Direct envelopes are not isolated driver/server time; "
                "nested coverage nonadditive.",
                "Queue get entry is not Future enqueue. "
                "Ready notification is not record reservation.",
                "Missing/open/unknown endpoints excluded from known-duration cohorts, "
                "never zero-filled.",
                "Timer lateness is observer global evidence, not request causality; "
                "no correction/subtraction.",
                "Recording costs cover begin/finish/tick only, omit "
                "preparation/mapping/safe-container overhead; nested costs nonadditive.",
                "ACK is client observed; unknown terminal and HTTP timeout are not rollback.",
                "No OFF commit outcome inferred. "
                "Original admission SLA and downstream timer differ.",
            ],
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("new analysis output required")
    data, before = load(args.input)
    requests, failures, summary = analyze(data)
    _, after = load(args.input)
    if before != after:
        raise ValueError("selected inputs changed")
    args.output.mkdir()
    packets = {
        "requests.json": requests,
        "failed.json": failures,
        "summary.json": summary,
        "provenance.json": {
            "before": before,
            "after": after,
            "unchanged": True,
            "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    }
    for name, packet in packets.items():
        with (args.output / name).open("x") as stream:
            json.dump(packet, stream, sort_keys=True, indent=2)
            stream.write("\n")
    print(
        json.dumps(
            {
                "requests": len(requests),
                "failures": len(failures),
                "observer_integrity_pass": summary["observer_integrity_pass"],
            },
            sort_keys=True,
        )
    )
    if not summary["observer_integrity_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
