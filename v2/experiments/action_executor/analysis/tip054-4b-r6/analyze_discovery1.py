"""Bounded, deterministic R6 offline falsification; standard library only.

Reads selected preserved evidence, never imports product or R4 executable code.
New output directory required. Monotonic intervals are unioned per request BEFORE
ranking. Observed residuals are not pure queue, ping, CPU or corrected latency.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

RAW = "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1"
ALLOWED = "v2/experiments/action_executor/analysis/tip054-4b-r6"
EPOCHS = {
    "baseline_560": "56017430e7115333f1efde05bb236397b884c043b76863502cc19dfb204d2ac9",
    "candidate_624": "624f4a7f666e998c679d0166ec538ff9e25996ee68a37c4690d07a786acef157",
}
OPS = ("admission", "submit", "status", "cancel")
PROFILES = (1, 10, 25, 50)
AUDIT = "2cf9705ca791be7b1767b6ddbf200944255cebc5f5702b5b7c9776d1f3ba6597"
HELPERS = (
    "v2/experiments/action_executor/latency_probe.py",
    "v2/experiments/action_executor/source_snapshot.py",
    *("v2/experiments/action_executor/r/" + name for name in (
        "phase_profiler.py", "pg_monitor.py", "run_phase_baseline.py",
        "source_snapshot.py", "finish_boundary.py", "r2/run_observed.py",
        "r2/audit_tail_observer.py", "r2/summarize_audit_tail.py")),
)
MAX_FILE = 50_000_000
MAX_TOTAL = 150_000_000
MAX_EVENTS = 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


def merge(intervals):
    result = []
    for start, end in sorted(intervals):
        require(end >= start, "reversed interval")
        if end == start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersection(left, right):
    left, right = merge(left), merge(right)
    output, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if start < end:
            output.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return output


def ms(intervals):
    return sum(end - start for start, end in merge(intervals)) / 1e6


def residual(left, right):
    return ms(left) - ms(intersection(left, right))


def spans(rows):
    return [(r["start_ns"], r["end_ns"]) for r in rows if r.get("end_ns") is not None]


def quantile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1] if values else None


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": round(min(values), 6),
            "p50": round(quantile(values, .5), 6),
            "p95": round(quantile(values, .95), 6),
            "p99": round(quantile(values, .99), 6),
            "max": round(max(values), 6), "sum": round(sum(values), 6)}


def selfchecks():
    require(merge([(0, 10), (2, 4), (8, 12), (12, 15)]) == [(0, 15)], "union")
    require(intersection([(0, 10), (20, 30)], [(5, 25)]) == [(5, 10), (20, 25)], "intersection")
    require(ms([(0, 10_000_000), (5_000_000, 12_000_000)]) == 12, "dedup")
    require(residual([(0, 10_000_000)], [(2_000_000, 8_000_000)]) == 4, "nested residual")
    require(quantile([1, 3, 2], .95) == 3, "nearest rank")
    require(stats([]) == {"n": 0}, "missing population")
    require(spans([{"start_ns": 1, "end_ns": None}]) == [], "open censoring")
    require(quantile([0, 1000], .95) == 1000, "failure retained in rank")
    require(ms(intersection([(0, 20)], [(5, 10), (7, 15)])) == .00001, "overlap")
    require(ms([]) == 0, "observed empty union only")
    try:
        merge([(10, 1)])
    except ValueError:
        pass
    else:
        raise ValueError("negative interval accepted")
    require(quantile([5], .99) == 5, "singleton")
    return 12


def select(repo):
    paths = set(HELPERS)
    for epoch in EPOCHS:
        for mode in ("off", "on"):
            gate = "r5_" + epoch + "_" + mode + "_r1"
            base = RAW + "/" + gate + "/"
            for name in ("samples.json", "samples.jsonl", "latency-summary.json", "r-controls.json"):
                paths.add(base + name)
            bind = RAW + "/r_bind_" + gate + "/"
            for name in ("binding-result.json", "source-before.json", "source-after.json",
                         "expected-product.sha256", "product-before.sha256", "product-after.sha256",
                         "capacity-before.txt", "capacity-after.txt"):
                paths.add(bind + name)
            if mode == "on":
                for name in ("phase-requests.jsonl", "audit-transactions.jsonl", "pg-waits.jsonl",
                             "phase-recorder-cost.json", "audit-recorder-cost.json",
                             "phase-observer-summary.json", "audit-observer-summary.json",
                             "pg-monitor-summary.json", "monitor-process.json", "audit-tail-summary.json"):
                    paths.add(base + name)
    # Bind the actual current product sources without executing/importing them.
    root = repo / "v2/apps/backend/src"
    paths.update(str(p.relative_to(repo)) for p in root.rglob("*.py"))
    require(len(paths) <= 400, "selected file count bound")
    total, manifest = 0, {}
    for relative in sorted(paths):
        path = repo / relative
        require(path.is_file() and not path.is_symlink(), "missing/symlink input " + relative)
        size = path.stat().st_size
        require(size <= MAX_FILE, "file byte bound " + relative)
        total += size
        require(total <= MAX_TOTAL, "total byte bound")
        manifest[relative] = {"bytes": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return manifest


def load(repo, manifest, relative, lines=False):
    require(relative in manifest, "unselected input")
    data = (repo / relative).read_bytes()
    require(hashlib.sha256(data).hexdigest() == manifest[relative]["sha256"], "input changed during read")
    if lines:
        rows = data.splitlines()
        require(len(rows) <= 102400, "JSONL record bound")
        return [json.loads(row) for row in rows]
    return json.loads(data)


def rid(sample):
    return f'tip054-latency-{sample["profile"]}-{sample["case"]}-{sample["operation"]}'


def reproduction(samples, original):
    require(len(samples) <= 1600, "request population bound")
    require(len({rid(s) for s in samples}) == len(samples), "duplicate HTTP observation")
    cells = []
    for profile in PROFILES:
        for operation in OPS:
            cohort = [s for s in samples if s["profile"] == profile and s["operation"] == operation]
            values = [s["elapsed_ms"] for s in cohort]
            limit = 500 if operation == "admission" else 1000
            cell = {"concurrency": profile, "operation": operation, "samples": len(cohort),
                    "failures": sum(not s["okay"] for s in cohort),
                    "p50_ms": quantile(values, .5), "p95_ms": quantile(values, .95),
                    "p99_ms": quantile(values, .99), "p95_limit_ms": limit}
            cell["pass"] = len(cohort) == 100 and cell["failures"] == 0 and cell["p95_ms"] <= limit
            cells.append(cell)
    require(cells == original["cells"], "original cell/population/quantile mismatch")
    return {"samples": len(samples), "failed_http": sum(not s["okay"] for s in samples),
            "passed_cells": sum(c["pass"] for c in cells), "cells": cells,
            "error_codes": dict(sorted(Counter(s.get("error_code") or s.get("exception_type")
                                              for s in samples if not s["okay"]).items())),
            "original_flags_and_nearest_ranks_exact": True, "original_status": original["status"]}


def occupancy(requests):
    events = Counter()
    for request in requests:
        for start, end in spans(request["holds"]):
            events[start] += 1
            events[end] -= 1
    active, last, peak, saturated, distribution = 0, None, 0, [], Counter()
    for stamp, delta in sorted(events.items()):
        if last is not None:
            distribution[active] += stamp - last
            if active >= 10:
                saturated.append((last, stamp))
        active += delta
        require(0 <= active <= 10, "closed-only occupancy outside physical cap")
        peak = max(peak, active)
        last = stamp
    require(active == 0, "closed-only occupancy unbalanced")
    return saturated, {"closed_only_peak": peak, "closed_only_capacity10_ms": round(ms(saturated), 6),
                       "closed_only_occupancy_ms": {str(k): round(v / 1e6, 6) for k, v in sorted(distribution.items())}}


def observed(repo, manifest, gate, samples):
    prefix = RAW + "/" + gate + "/"
    get = lambda name, lines=False: load(repo, manifest, prefix + name, lines)
    requests, audit, waits = (get(name, True) for name in (
        "phase-requests.jsonl", "audit-transactions.jsonl", "pg-waits.jsonl"))
    require(len(requests) <= 1600 and len(waits) <= 3600 and len(audit) <= 102400, "record bounds")
    sample_by_id = {rid(s): s for s in samples}
    require(len(requests) == len(sample_by_id) and
            {r["request_id"] for r in requests} == set(sample_by_id), "phase/HTTP bijection")
    require(len({r["request_id"] for r in requests}) == len(requests), "duplicate phase request")
    audits = defaultdict(list)
    for tx in audit:
        require(tx["request_id"] in sample_by_id, "unmapped transaction")
        audits[tx["request_id"]].append(tx)
    require(all(len(t) <= 64 for t in audits.values()), "transaction/request bound")
    saturated, capacity = occupancy(requests)
    holds_by_op = {op: merge(h for r in requests if r["operation"] == op
                            for h in spans(r["holds"])) for op in OPS}
    pid_waits, sql_by_pid = defaultdict(list), defaultdict(list)
    for tick in waits:
        for activity in tick.get("activity", []):
            if activity["wait_event_type"] == "Lock":
                pid_waits[activity["pid"]].append((tick["tick_ns"], tick["end_ns"], activity["blockers"]))
    for request in requests:
        for statement in request["sql"]:
            if statement["pid"] is not None and statement["end_ns"] is not None:
                sql_by_pid[statement["pid"]].append((statement["start_ns"], statement["end_ns"],
                                                      request["request_id"], request["operation"]))
    tick_indexes = {pid: [v[0] for v in entries] for pid, entries in pid_waits.items()}
    rows, correlations, anomalies = [], [], Counter()
    for request in requests:
        key, start, end = request["request_id"], request["start_ns"], request["end_ns"]
        require(end is not None and start < end and request["closed"], "unclosed request")
        require(all(len(request[k]) <= MAX_EVENTS for k in ("holds", "sql", "pool", "phases")), "event bound")
        sample, txs = sample_by_id[key], audits[key]
        sql, hold, phases = spans(request["sql"]), spans(request["holds"]), spans(request["phases"])
        require(all(start <= a <= b <= end for a, b in sql + hold + phases), "event outside request")
        pool = {kind: sorted((p for p in request["pool"] if p["kind"] == kind), key=lambda p: p["start_ns"])
                for kind in ("connect", "_do_get", "_create_connection")}
        connect, do_get, create = (spans(pool[k]) for k in pool)
        attempts = [a for tx in txs for a in tx["audit_attempts"]]
        grants = [(tx["first_audit_grant_ns"], tx["terminal_ns"]) for tx in txs
                  if tx["first_audit_grant_ns"] is not None and tx["terminal_ns"] is not None]
        first_attempts = [(a["start_ns"], a["end_ns"]) for tx in txs for a in tx["audit_attempts"]
                          if tx["first_audit_grant_ns"] is not None and a["end_ns"] == tx["first_audit_grant_ns"]]
        terminal_spans = [(tx["start_ns"], tx["terminal_ns"]) for tx in txs if tx["terminal_ns"] is not None]
        root_phases = [p for p in request["phases"] if not p["parent_ids"]]
        root_spans = spans(root_phases)
        row = {"gate": gate, "request_id": key, "profile": request["profile"], "case": request["case"],
               "operation": request["operation"], "okay": sample["okay"], "http_status": sample.get("http_status"),
               "error_code": sample.get("error_code"), "http_elapsed_ms": sample["elapsed_ms"],
               "observer_request_ms": (end - start) / 1e6,
               "sample_minus_observer_wall_ms": sample["elapsed_ms"] - (end - start) / 1e6,
               "root_caller_union_ms": ms(root_spans), "request_outside_root_caller_ms": residual([(start, end)], root_spans),
               "sql_count": len(request["sql"]), "closed_hold_count": len(hold),
               "closed_hold_union_ms": ms(hold), "longest_closed_hold_ms": max(((b-a)/1e6 for a,b in hold), default=None),
               "connect_union_ms": ms(connect), "do_get_union_ms": ms(do_get), "create_union_ms": ms(create),
               "connect_outside_do_get_residual_ms": residual(connect, do_get),
               "do_get_outside_creation_residual_ms": residual(do_get, create),
               "first_connect_ms": ms(spans(pool["connect"][:1])) if pool["connect"] else None,
               "later_connect_union_ms": ms(spans(pool["connect"][1:])),
               "connect_call_count": len(pool["connect"]),
               "first_connect_error": pool["connect"][0]["error_type"] if pool["connect"] else None,
               "connect_error_count": sum(p["error_type"] is not None for p in pool["connect"]),
               "successful_connect_count": sum(p["error_type"] is None and p["end_ns"] is not None for p in pool["connect"]),
               "sql_union_ms": ms(sql), "held_sql_union_ms": ms(intersection(hold, sql)),
               "held_non_sql_residual_ms": residual(hold, sql),
               "audit_acquisition_union_ms": ms(spans(attempts)),
               "first_audit_grant_envelope_union_ms": ms(first_attempts),
               "known_grant_terminal_union_ms": ms(grants),
               "held_known_grant_terminal_ms": ms(intersection(hold, grants)),
               "audit_append_union_ms": ms(spans([a for tx in txs for a in tx["append_spans"]])),
               "known_terminal_transaction_union_ms": ms(terminal_spans),
               "transactions": len(txs), "unknown_terminal_transactions": sum(tx["terminal_ns"] is None for tx in txs),
               "unknown_granted_transactions": sum(tx["first_audit_grant_ns"] is not None and tx["terminal_ns"] is None for tx in txs),
               "connect_over_closed_capacity10_ms": ms(intersection(connect, saturated)),
               "observed_any_commit_ack": any(tx["terminal_kind"] == "commit_ack" for tx in txs),
               "observed_audited_commit_ack": any(tx["terminal_kind"] == "commit_ack" and tx["first_audit_grant_ns"] is not None for tx in txs),
               "observed_rollback_ack": any(tx["terminal_kind"] == "rollback_ack" for tx in txs)}
        for kind in ("holds", "sql", "pool", "phases"):
            row[kind + "_without_end"] = sum(v["end_ns"] is None for v in request[kind])
            anomalies[kind + "_without_end"] += row[kind + "_without_end"]
        anomalies["unknown_terminal_transactions"] += row["unknown_terminal_transactions"]
        anomalies["unknown_granted_transactions"] += row["unknown_granted_transactions"]
        anomalies["no_transaction_requests"] += not txs
        anomalies["no_closed_hold_requests"] += not hold
        anomalies["missing_sql_pid"] += sum(s["pid"] is None for s in request["sql"])
        anomalies["successful_connect_closed_hold_deficit"] += max(0, row["successful_connect_count"] - len(hold))
        for op in OPS:
            other = merge(h for other in requests if other["request_id"] != key and other["operation"] == op
                          for h in spans(other["holds"]))
            row["connect_over_other_" + op + "_closed_owners_ms"] = ms(intersection(connect, other))
        phase_names = sorted({p["name"] for p in request["phases"]})
        row["phase_metrics"] = {}
        for name in phase_names:
            selected = [p for p in request["phases"] if p["name"] == name]
            own, children = spans(selected), spans([p for p in request["phases"] if p["parent_ids"] and
                                                  p["parent_ids"][-1] in {v["phase_id"] for v in selected}])
            row["phase_metrics"][name] = {"calls": len(selected), "inclusive_union_ms": ms(own),
                                          "direct_child_exclusive_ms": residual(own, children),
                                          "held_overlap_ms": ms(intersection(own, hold))}
        hits, strict = set(), set()
        for statement in request["sql"]:
            pid = statement["pid"]
            if pid not in pid_waits:
                continue
            finish = statement["end_ns"] if statement["end_ns"] is not None else end
            for tick, tick_end, blockers in pid_waits[pid][:bisect.bisect_right(tick_indexes[pid], finish)]:
                if tick_end < statement["start_ns"]:
                    continue
                is_strict = statement["end_ns"] is not None and statement["start_ns"] <= tick <= finish
                hits.add(tick)
                if is_strict:
                    strict.add(tick)
                candidates = sorted({(v[2], v[3]) for blocker in blockers for v in sql_by_pid.get(blocker, [])
                                     if v[0] <= tick <= v[1] and v[2] != key})
                correlations.append({"gate": gate, "request_id": key, "pid": pid, "tick_ns": tick,
                                     "sample_end_ns": tick_end, "sql_start_ns": statement["start_ns"],
                                     "sql_end_ns": statement["end_ns"], "statement_class": statement["statement_class"],
                                     "static_sha256": statement["static_sha256"], "strict_tick_inside_closed_sql": is_strict,
                                     "blockers": blockers, "blocker_same_time_sql_request_candidates": candidates})
        row["pg_envelope_lock_ticks"], row["pg_strict_lock_ticks"] = len(hits), len(strict)
        rows.append(row)
    numeric = sorted(k for k, v in rows[0].items() if isinstance(v, (int, float)) and not isinstance(v, bool))
    numeric += ["longest_closed_hold_ms", "first_connect_ms"]
    numeric = sorted(set(numeric) - {"case", "profile", "http_status"})
    cells = []
    for profile in PROFILES:
        for operation in OPS:
            cohort = [r for r in rows if r["profile"] == profile and r["operation"] == operation]
            phase_names = sorted({name for r in cohort for name in r["phase_metrics"]})
            cells.append({"profile": profile, "operation": operation, "n": len(cohort),
                          "failed_http": sum(not r["okay"] for r in cohort),
                          "closed_hold_count_histogram": dict(sorted(Counter(str(r["closed_hold_count"]) for r in cohort).items())),
                          "failed_with_any_commit_ack": sum(not r["okay"] and r["observed_any_commit_ack"] for r in cohort),
                          "failed_with_audited_commit_ack": sum(not r["okay"] and r["observed_audited_commit_ack"] for r in cohort),
                          "failed_with_rollback_ack": sum(not r["okay"] and r["observed_rollback_ack"] for r in cohort),
                          "failed_without_any_terminal_ack": sum(not r["okay"] and not r["observed_any_commit_ack"] and
                                                               not r["observed_rollback_ack"] for r in cohort),
                          "metrics": {k: stats([r[k] for r in cohort]) for k in numeric},
                          "phases": {name: {k: stats([r["phase_metrics"][name][k] for r in cohort if name in r["phase_metrics"]])
                                            for k in ("calls", "inclusive_union_ms", "direct_child_exclusive_ms", "held_overlap_ms")}
                                     for name in phase_names}})
    c1 = [r for r in rows if r["profile"] == 1]
    costs = {kind: {k: stats([v[k] for v in get(kind + "-recorder-cost.json")])
                    for k in ("serialize_ms", "append_flush_ms")} for kind in ("phase", "audit")}
    audit_summary, phase_summary = get("audit-observer-summary.json"), get("phase-observer-summary.json")
    require(phase_summary["requests"] == len(rows), "phase summary population mismatch")
    require(audit_summary["transactions"] == len(audit), "audit summary population mismatch")
    return rows, correlations, {"cells": cells, "anomalies": dict(sorted(anomalies.items())), "capacity": capacity,
        "c1_counts": {op: {"n": sum(r["operation"] == op for r in c1),
                            "sql_count_histogram": dict(sorted(Counter(str(r["sql_count"]) for r in c1 if r["operation"] == op).items())),
                            "closed_hold_count_histogram": dict(sorted(Counter(str(r["closed_hold_count"]) for r in c1 if r["operation"] == op).items()))}
                      for op in OPS},
        "pg": {"ticks": len(waits), "errors": sum("error_type" in v for v in waits),
               "sampled_lock_rows": sum(len(v.get("locks", [])) for v in waits),
               "granted_lock_rows": sum(r["granted"] for v in waits for r in v.get("locks", [])),
               "correlated_rows": len(correlations), "strict_correlated_rows": sum(v["strict_tick_inside_closed_sql"] for v in correlations),
               "strict_statement_digests": dict(sorted(Counter(v["static_sha256"] for v in correlations if v["strict_tick_inside_closed_sql"]).items())),
               "blocker_request_candidate_rows": sum(bool(v["blocker_same_time_sql_request_candidates"]) for v in correlations)},
        "audit_summary": audit_summary, "phase_summary": phase_summary, "costs": costs,
        "monitor_summary": get("pg-monitor-summary.json"), "monitor_process": get("monitor-process.json"),
        "actual_chain_after_timing": get("audit-tail-summary.json")["actual_chain_after_timing"]}


LIMITS = [
    "OFF is acceptance; ON diagnostic inclusive observer costs. Serial fresh epochs are not causal matched pairs.",
    "Closed holds only, no open checkout/PID identity emission; empty observed hold union is not zero actual lease duration.",
    "Unknown terminal_ns stays missing. Known-terminal transaction/audit tails exclude unknown clocks, never impute rollback.",
    "connect contains pre_ping/retry/wrapping/scheduling; connect outside do_get is residual, not ping time.",
    "do_get includes queue/creation/bookkeeping; its outside-creation residual is not pure queue.",
    "SQL/client and held-non-SQL envelopes are not server CPU or isolated cleanup. Driver pre_ping/implicit TX wire traffic lacks SQL events.",
    "Private phase lease/release/join cleanup are not profiler phases; exact teardown or reacquire reasons are not observed.",
    "Grant completion/commit_ack are client clocks, not exact server lock release or successful HTTP delivery.",
    "PG activity/locks fetched separately within tick/end; finite50ms sampling misses short waits, PID+time correlation is not continuous wait.",
    "Closed-only occupancy reconstructed from returned records is not continuous physical pool telemetry.",
    "Recorder cost has duration but no timestamp; cross-request delay cannot be assigned or subtracted to correct OFF.",
    "No worker/provider fixture cannot implicate DBOS/LLM costs. Missing downstream samples cannot become pass or zero.",
]


def main(repo, output):
    allowed = (repo / ALLOWED).resolve()
    require(output.is_relative_to(allowed) and output != allowed and not output.exists(), "new output under R6 required")
    manifest = select(repo)  # Complete selection + before hashes BEFORE evidence parsing.
    result, rows, correlations, bindings = {}, [], [], {}
    for epoch, product in EPOCHS.items():
        result[epoch] = {}
        for mode in ("off", "on"):
            gate = "r5_" + epoch + "_" + mode + "_r1"
            prefix, binding_prefix = RAW + "/" + gate + "/", RAW + "/r_bind_" + gate + "/"
            samples = load(repo, manifest, prefix + "samples.jsonl", True)
            require(samples == load(repo, manifest, prefix + "samples.json"), "JSONL/final sample inequality")
            original = load(repo, manifest, prefix + "latency-summary.json")
            bind = load(repo, manifest, binding_prefix + "binding-result.json")
            before, after = (load(repo, manifest, binding_prefix + name) for name in ("source-before.json", "source-after.json"))
            require(before == after and bind["boundary_status"] == "PASS" and
                    bind["expected_product_sha256"] == bind["product_before_sha256"] == bind["product_after_sha256"] == product,
                    "epoch binding changed")
            require(len(before) == bind["source_binding_count"], "binding count mismatch")
            for helper in HELPERS:
                key = ("verification_r/" + helper.split("/r/", 1)[1] if "/r/" in helper
                       else "verification/" + Path(helper).name)
                require(before[key] == manifest[helper]["sha256"], "helper binding mismatch")
            if epoch == "candidate_624":
                for relative, value in manifest.items():
                    if relative.startswith("v2/apps/backend/src/"):
                        require(before[relative.removeprefix("v2/apps/backend/")] == value["sha256"], "current product byte mismatch")
            bindings[gate] = {"product_sha256": product, "binding_count": len(before), "before_after_equal": True,
                              "boundary_status": bind["boundary_status"], "original_child_gate": bind["child_gate_status"],
                              "capacity_before": (repo / (binding_prefix + "capacity-before.txt")).read_text(),
                              "capacity_after": (repo / (binding_prefix + "capacity-after.txt")).read_text()}
            controls = load(repo, manifest, prefix + "r-controls.json")
            require(controls["observer"] == mode and controls["pool_size"] == controls["max_overflow"] == 5 and
                    controls["pre_ping"] and controls["operation_timeout_seconds"] == .9, "profile changed")
            result[epoch][mode] = {"reproduction": reproduction(samples, original), "controls": controls}
            if mode == "on":
                a, b, metrics = observed(repo, manifest, gate, samples)
                rows.extend(a)
                correlations.extend(b)
                result[epoch][mode]["intervals"] = metrics
    # Final selected-input rehash; no output before immutable-input verification.
    require(select(repo) == manifest, "selected inputs changed before/after analysis")
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        with (output / name).open("x") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
    write("summary.json", {"status": "OFFLINE_FALSIFICATION_ONLY_EXECUTOR_NOT_READY", "runs": result,
                           "limits": LIMITS, "selfchecks_passed": selfchecks()})
    write("provenance.json", {"inputs_before_after_equal": True, "selected_file_count": len(manifest),
                              "total_selected_bytes": sum(v["bytes"] for v in manifest.values()), "inputs": manifest,
                              "bindings": bindings, "epochs": EPOCHS,
                              "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              "bounds": {"input_bytes": MAX_FILE, "total_bytes": MAX_TOTAL, "requests": 1600,
                                         "events_per_request_per_kind": MAX_EVENTS, "transactions": 102400,
                                         "transactions_per_request": 64, "monitor_ticks": 3600},
                              "method": "Per-request interval union/intersection before nearest rank; immutable selected inputs; no product imports.",
                              "selfchecks_passed": selfchecks()})
    for name, values in (("requests.jsonl", rows), ("pg-correlations.jsonl", correlations)):
        with (output / name).open("x") as stream:
            for value in values:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"status": "OFFLINE_ONLY", "inputs": len(manifest), "requests": len(rows),
                      "correlations": len(correlations), "selfchecks": selfchecks()}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selfchecks()
    main(args.repo.resolve(), args.output.resolve())
