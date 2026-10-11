"""Bounded standard-library offline interval analysis; immutable inputs only.

All derived times are per-request interval unions before nearest-rank summaries.
No runtime/product imports, SQL, network, environment or original-file writes.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

PRODUCT = "56017430e7115333f1efde05bb236397b884c043b76863502cc19dfb204d2ac9"
AUDIT = "2cf9705ca791be7b1767b6ddbf200944255cebc5f5702b5b7c9776d1f3ba6597"
RUN = "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r3qa1"
HELPERS = (
    "phase_profiler.py", "pg_monitor.py", "run_phase_baseline.py",
    "r2/audit_tail_observer.py", "r2/run_observed.py",
    "r2/summarize_audit_tail.py", "r2/run-audit-tail.sh",
    "summarize_pair.py", "source_snapshot.py", "finish_boundary.py",
    "run-baseline.sh",
)
OPS = ("admission", "submit", "status", "cancel")


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersect(left, right):
    left, right = union(left), union(right)
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


def duration(intervals):
    return sum(end - start for start, end in union(intervals)) / 1e6


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": round(values[0], 6),
            "p50": round(values[math.ceil(len(values) * .5) - 1], 6),
            "p95": round(values[math.ceil(len(values) * .95) - 1], 6),
            "max": round(values[-1], 6), "sum": round(sum(values), 6)}


def interval_rows(rows):
    return [(r["start_ns"], r["end_ns"]) for r in rows if r.get("end_ns") is not None]


def self_test():
    assert union([(0, 10), (2, 3), (8, 12), (12, 15), (20, 20)]) == [(0, 15)]
    assert intersect([(0, 10), (20, 30)], [(5, 25)]) == [(5, 10), (20, 25)]
    assert duration([(0, 10_000_000), (5_000_000, 12_000_000)]) == 12
    assert stats([3, 1, 2])["p95"] == 3
    assert duration([]) == 0
    assert duration([(0, 10_000_000)]) - duration(intersect(
        [(0, 10_000_000)], [(2_000_000, 8_000_000)])) == 4
    assert interval_rows([{"start_ns": 0, "end_ns": None}]) == []
    assert stats([]) == {"n": 0}


def analyze(repo, output):
    allowed = repo / "v2/experiments/action_executor/analysis/tip054-4b-r4"
    assert output.resolve().is_relative_to(allowed.resolve()) and not output.exists()
    output.mkdir(parents=True)
    paths = {}

    def load(relative, lines=False):
        path = repo / relative
        data = path.read_bytes()
        assert len(data) <= 100_000_000
        paths[relative] = hashlib.sha256(data).hexdigest()
        result = ([json.loads(line) for line in data.splitlines()] if lines
                  else json.loads(data))
        return result

    frozen = load(RUN + "/cleanup_560_final/before-inventory.json")
    assert frozen["product_sha256"] == PRODUCT
    frozen_rows = dict(frozen["current_raw_rows"])
    for name in HELPERS:
        relative = "v2/experiments/action_executor/r/" + name
        paths[relative] = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
    relative = "v2/experiments/action_executor/latency_probe.py"
    paths[relative] = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
    rows, result, missing, correlations = [], {}, {}, []
    for label, gate, off_gate in (
        ("baseline", "r3_baseline_e6_on_r1", "r3_baseline_e6_off_r1"),
        ("candidate", "r3_candidate_on_r1", "r3_candidate_off_r1"),
    ):
        prefix = RUN + "/" + gate + "/"
        requests = load(prefix + "phase-requests.jsonl", True)
        audit = load(prefix + "audit-transactions.jsonl", True)
        waits = load(prefix + "pg-waits.jsonl", True)
        samples = load(prefix + "samples.jsonl", True)
        assert samples == load(prefix + "samples.json")
        assert len(requests) == len(samples) <= 1600 and len(audit) <= 102400
        assert len(waits) <= 3600
        binding_prefix = RUN + "/r_bind_" + gate + "/"
        binding = load(binding_prefix + "binding-result.json")
        before, after = load(binding_prefix + "source-before.json"), load(
            binding_prefix + "source-after.json")
        assert before == after and binding["boundary_status"] == "PASS"
        for helper in HELPERS:
            key = "verification_r/" + helper
            assert before[key] == paths["v2/experiments/action_executor/r/" + helper]
        assert before["verification/latency_probe.py"] == paths[relative]
        for filename in ("phase-observer-summary.json", "audit-observer-summary.json",
                         "pg-monitor-summary.json", "monitor-process.json", "r-controls.json",
                         "returncodes.json", "audit-tail-summary.json"):
            load(prefix + filename)
        on_summary = load(prefix + "latency-summary.json")
        off_summary = load(RUN + "/" + off_gate + "/latency-summary.json")
        off_samples = load(RUN + "/" + off_gate + "/samples.jsonl", True)
        assert off_samples == load(RUN + "/" + off_gate + "/samples.json")
        off_bind = load(RUN + "/r_bind_" + off_gate + "/binding-result.json")
        assert off_bind["boundary_status"] == "PASS"
        phase_cost = load(prefix + "phase-recorder-cost.json")
        audit_cost = load(prefix + "audit-recorder-cost.json")
        audits = defaultdict(list)
        for tx in audit:
            audits[tx["request_id"]].append(tx)
        sample_by_id = {f'tip054-latency-{s["profile"]}-{s["case"]}-{s["operation"]}': s
                        for s in samples}
        assert len(sample_by_id) == len(samples)
        holds_by_op = {op: union(h for r in requests if r["operation"] == op
                                for h in interval_rows(r["holds"])) for op in OPS}
        global_events = Counter()
        for r in requests:
            for start, end in interval_rows(r["holds"]):
                global_events[start] += 1
                global_events[end] -= 1
        active, last, saturated, occupancy_ns, peak = 0, None, [], Counter(), 0
        for stamp, delta in sorted(global_events.items()):
            if last is not None:
                occupancy_ns[active] += stamp - last
                if active >= 10:
                    saturated.append((last, stamp))
            active += delta
            assert active >= 0
            peak = max(peak, active)
            last = stamp
        assert active == 0 and peak <= 10
        saturated = union(saturated)
        by_pid = defaultdict(list)
        for w in waits:
            for a in w.get("activity", []):
                if a["wait_event_type"] == "Lock":
                    by_pid[a["pid"]].append((w["tick_ns"], w["end_ns"], a["blockers"]))
        ticks = {pid: [w[0] for w in entries] for pid, entries in by_pid.items()}
        subset = []
        anomalies = Counter()
        for request in requests:
            rid = request["request_id"]
            sample = sample_by_id[rid]
            start, end = request["start_ns"], request["end_ns"]
            assert start < end and request["closed"]
            sql, hold = interval_rows(request["sql"]), interval_rows(request["holds"])
            assert all(start <= a <= b <= end for a, b in sql + hold)
            pool = {kind: [p for p in request["pool"] if p["kind"] == kind]
                    for kind in ("connect", "_do_get", "_create_connection")}
            connect, do_get, create = (interval_rows(pool[k]) for k in pool)
            txs = audits[rid]
            all_attempts = [a for t in txs for a in t["audit_attempts"]]
            attempt_spans = interval_rows(all_attempts)
            first_grant_spans = [(a["start_ns"], a["end_ns"]) for t in txs
                                 for a in t["audit_attempts"]
                                 if t["first_audit_grant_ns"] is not None
                                 and a["end_ns"] == t["first_audit_grant_ns"]]
            tails = [(t["first_audit_grant_ns"], t["terminal_ns"]) for t in txs
                     if t["first_audit_grant_ns"] is not None and t["terminal_ns"] is not None]
            logical = [(t["start_ns"], t["terminal_ns"]) for t in txs
                       if t["terminal_ns"] is not None]
            append = interval_rows([a for t in txs for a in t["append_spans"]])
            locks = interval_rows([s for s in request["sql"] if s["statement_class"]
                                   in {"row_share", "row_update", "advisory_shared",
                                       "advisory_exclusive"}])
            audit_sql = interval_rows([s for s in request["sql"] if s["static_sha256"] == AUDIT])
            anomalies["no_audit_record_requests"] += not txs
            anomalies["unknown_terminal_transactions"] += sum(t["terminal_ns"] is None for t in txs)
            anomalies["sql_without_end"] += sum(s["end_ns"] is None for s in request["sql"])
            anomalies["pool_without_end"] += sum(p["end_ns"] is None for p in request["pool"])
            successes = sum(p["error_type"] is None and p["end_ns"] is not None for p in pool["connect"])
            anomalies["connect_success_minus_closed_hold_positive"] += max(0, successes - len(hold))
            anomalies["missing_sql_pid"] += sum(s["pid"] is None for s in request["sql"])
            hits, strict, classes, digest_classes = set(), set(), Counter(), Counter()
            for statement in request["sql"]:
                pid = statement["pid"]
                if pid not in by_pid:
                    continue
                finish = statement["end_ns"] or end
                events = by_pid[pid]
                stop = bisect.bisect_right(ticks[pid], finish)
                for tick, tick_end, blockers in events[:stop]:
                    if tick_end < statement["start_ns"]:
                        continue
                    hits.add(tick)
                    if statement["start_ns"] <= tick <= finish:
                        strict.add(tick)
                    classes[statement["statement_class"]] += 1
                    digest_classes[statement["static_sha256"]] += 1
                    correlations.append({"run": label, "request_id": rid, "pid": pid,
                                         "sql_start_ns": statement["start_ns"], "sql_end_ns": finish,
                                         "statement_class": statement["statement_class"],
                                         "static_sha256": statement["static_sha256"], "tick_ns": tick,
                                         "sample_end_ns": tick_end, "blocker_count": len(blockers),
                                         "strict_tick_inside_sql": statement["start_ns"] <= tick <= finish})
            item = {"run": label, "request_id": rid, "profile": request["profile"],
                    "case": request["case"], "operation": request["operation"],
                    "http_status": request.get("http_status"), "okay": sample["okay"],
                    "request_ms": (end - start) / 1e6, "sql_count": len(request["sql"]),
                    "closed_hold_count": len(hold), "hold_union_ms": duration(hold),
                    "longest_closed_hold_ms": max(((b-a)/1e6 for a,b in hold), default=None),
                    "closed_hold_extent_ms": ((max(b for a,b in hold)-min(a for a,b in hold))/1e6
                                              if hold else None),
                    "connect_union_ms": duration(connect), "do_get_union_ms": duration(do_get),
                    "create_union_ms": duration(create),
                    "connect_outside_do_get_ms": duration(connect)-duration(intersect(connect, do_get)),
                    "do_get_outside_create_ms": duration(do_get)-duration(intersect(do_get, create)),
                    "sql_union_ms": duration(sql), "lock_sql_union_ms": duration(locks),
                    "audit_sql_union_ms": duration(audit_sql),
                    "held_sql_union_ms": duration(intersect(hold, sql)),
                    "held_non_sql_ms": duration(hold)-duration(intersect(hold, sql)),
                    "held_audit_acquisition_ms": duration(intersect(hold, attempt_spans)),
                    "held_after_firstgrant_ms": duration(intersect(hold, tails)),
                    "held_outside_grant_tail_ms": duration(hold)-duration(intersect(hold, tails)),
                    "audit_acquisition_union_ms": duration(attempt_spans),
                    "first_audit_grant_envelope_union_ms": duration(first_grant_spans),
                    "held_first_audit_grant_envelope_ms": duration(intersect(hold, first_grant_spans)),
                    "audit_append_union_ms": duration(append), "grant_tail_union_ms": duration(tails),
                    "observed_terminal_transaction_union_ms": duration(logical),
                    "logical_transactions": len(txs),
                    "logical_transactions_without_terminal_clock": sum(t["terminal_ns"] is None for t in txs),
                    "cancelled_connect_count": sum(p["error_type"] is not None for p in pool["connect"]),
                    "connect_over_closed_only_capacity10_ms": duration(intersect(connect, saturated)),
                    "pg_lock_sample_ticks": len(hits), "pg_strict_lock_sample_ticks": len(strict),
                    "pg_correlated_classes": dict(classes), "pg_correlated_static_digests": dict(digest_classes),
                    "observed_any_commit": any(t["terminal_kind"] == "commit_ack" for t in txs),
                    "observed_audited_commit": any(t["terminal_kind"] == "commit_ack" and
                                                  t["first_audit_grant_ns"] is not None for t in txs)}
            for op in OPS:
                item["connect_over_"+op+"_owner_union_ms"] = duration(intersect(connect, holds_by_op[op]))
                other_holds = [h for other in requests if other["request_id"] != rid
                               and other["operation"] == op for h in interval_rows(other["holds"])]
                item["connect_over_other_"+op+"_owner_union_ms"] = duration(intersect(connect, other_holds))
            for name in ("ActionService._snapshot", "ActionService._metadata_plan", "ExecutionService._view"):
                spans = interval_rows([p for p in request["phases"] if p["name"] == name])
                item[name+"_union_ms"] = duration(spans)
                item[name+"_held_overlap_ms"] = duration(intersect(hold, spans))
            rows.append(item)
            subset.append(item)
        numeric = [k for k,v in subset[0].items() if isinstance(v, (int,float)) and not isinstance(v,bool)]
        cells = []
        for profile in (1,10,25,50):
            for op in OPS:
                cell = [r for r in subset if r["profile"] == profile and r["operation"] == op]
                cells.append({"profile": profile, "operation": op, "requests": len(cell),
                              "failures": sum(not r["okay"] for r in cell),
                              "zero_closed_hold_records": sum(r["closed_hold_count"] == 0 for r in cell),
                              "metrics": {k: stats([r[k] for r in cell if r[k] is not None])
                                          for k in numeric if k not in {"case", "profile"}},
                              "known_audited_commit_failures": sum(not r["okay"] and r["observed_audited_commit"] for r in cell),
                              "known_any_commit_failures": sum(not r["okay"] and r["observed_any_commit"] for r in cell)})
        result[label] = {"cells": cells, "anomalies": dict(anomalies),
                         "phase_summary": load(prefix+"phase-observer-summary.json"),
                         "audit_summary": load(prefix+"audit-observer-summary.json"),
                         "on_latency": on_summary, "off_latency": off_summary,
                         "closed_only_occupancy_peak": peak,
                         "closed_only_capacity10_ms": duration(saturated),
                         "closed_only_occupancy_ms": {str(k): round(v/1e6,6) for k,v in sorted(occupancy_ns.items())},
                         "monitor_ticks": len(waits), "monitor_error_ticks": sum("error_type" in w for w in waits),
                         "sampled_lock_rows": sum(len(w.get("locks",[])) for w in waits),
                         "phase_recorder": {k: stats([r[k] for r in phase_cost]) for k in ("serialize_ms", "append_flush_ms")},
                         "audit_recorder": {k: stats([r[k] for r in audit_cost]) for k in ("serialize_ms", "append_flush_ms")}}
        print(json.dumps({"stage":"analyzed", "run":label, "requests":len(subset)}),flush=True)
    for relative, expected in paths.items():
        assert hashlib.sha256((repo/relative).read_bytes()).hexdigest()==expected
        if relative.startswith(RUN+"/") and "/cleanup_560_final/" not in relative:
            assert frozen_rows[relative.removeprefix(RUN+"/")] == expected
    def write(name, value):
        (output/name).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
    write("summary.json", {"status":"OFFLINE_DIAGNOSIS_ONLY", "runs":result,
          "limits":["Closed holds only: missing records are not zero lease time.",
                    "Transaction end_unknown lacks terminal_ns; no duration imputation.",
                    "Per-request interval unions precede nearest-rank p95; metrics overlap and are nonadditive.",
                    "Connect outside do_get is residual including pre_ping/wrapper, not pure pre_ping.",
                    "Do_get outside creation includes queue/bookkeeping, not pure queue.",
                    "Closed-only reconstructed occupancy is not complete continuous pool telemetry.",
                    "PG activity observed somewhere inside tick/end envelope; overlap correlation is not exact lock wait.",
                    "Strict tick-inside-SQL is a stricter match, not an atomic PG state sample; activity and locks are separate sampler queries.",
                    "Different fresh serial runs/case IDs are not causal matched pairs or acceptance improvement.",
                    "Recorder durations have no timestamps; cannot allocate cross-request callback blocking or correct OFF."]})
    for name, data in (("requests.jsonl",rows),("pg-correlations.jsonl",correlations)):
        with (output/name).open("x") as stream:
            for row in data:
                stream.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n")
    write("provenance.json", {"product_sha256":PRODUCT,
          "analyzer_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "input_sha256":dict(sorted(paths.items())), "input_hashes_equal_before_after":True,
          "selected_raw_match_cleanup_frozen_rows":True,
          "algorithm":"Sorted interval union/intersection, monotonic ns→ms; nearest-rank quantiles; strict and sampled-envelope PG correlations.",
          "self_tests":"8 PASS (union, intersection, overlap deduplication, quantile, empty duration, nested subtraction, nonclosed censorship, empty sample)", "runtime":"Python standard library only; no product/dependency imports or external/runtime operations."})


if __name__ == "__main__":
    self_test()
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    analyze(args.repo.resolve(),args.output.resolve())
