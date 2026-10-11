"""Deterministic bounded R8 offline analysis; no product imports or runtime calls.

Interval primitives reuse R6 methodology, not its executable/hardcoded packets.
All durations below are observed client coverage, not pure queue/server time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

RAW = "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1"
ALLOWED = "v2/experiments/action_executor/analysis/tip054-4b-r8"
RUNS = {
    "baseline_off": "r7_baseline_624_off_r1",
    "baseline_on": "r7_baseline_624_on_r1",
    "candidate_on": "r7_candidate_56f_on_r1",
    "candidate_off": "r7_candidate_56f_off_r1",
}
PRODUCTS = {
    "baseline": "624f4a7f666e998c679d0166ec538ff9e25996ee68a37c4690d07a786acef157",
    "candidate": "56fa5d71fc61efc6dd3dcae8ce0a313a5b0a7f3d410145093f45365c2704e209",
}
AUDIT = "2cf9705ca791be7b1767b6ddbf200944255cebc5f5702b5b7c9776d1f3ba6597"
OPS, PROFILES = ("admission", "submit", "status", "cancel"), (1, 10, 25, 50)
HELPERS = (
    "v2/experiments/action_executor/latency_probe.py",
    "v2/experiments/action_executor/source_snapshot.py",
    *("v2/experiments/action_executor/r/" + n for n in (
        "phase_profiler.py", "pg_monitor.py", "run_phase_baseline.py",
        "source_snapshot.py", "finish_boundary.py", "r2/run_observed.py",
        "r2/audit_tail_observer.py", "r2/summarize_audit_tail.py")),
)
MAX_FILE, MAX_TOTAL, MAX_LINES = 50_000_000, 200_000_000, 102400


def require(test, message):
    if not test:
        raise ValueError(message)


def merge(intervals):
    out = []
    for a, b in sorted(intervals):
        require(b >= a, "reversed interval")
        if a == b:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(b, out[-1][1]))
        else:
            out.append((a, b))
    return out


def intersection(left, right):
    left, right = merge(left), merge(right)
    out, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        a, b = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if a < b:
            out.append((a, b))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return out


def difference(left, right):
    out = []
    right = merge(right)
    for a, b in merge(left):
        for c, d in right:
            if d <= a:
                continue
            if c >= b:
                break
            if c > a:
                out.append((a, min(c, b)))
            a = max(a, d)
            if a >= b:
                break
        if a < b:
            out.append((a, b))
    return out


def spans(rows):
    return [(r["start_ns"], r["end_ns"]) for r in rows if r.get("end_ns") is not None]


def ms(intervals):
    return sum(b - a for a, b in merge(intervals)) / 1e6


def quantile(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1] if values else None


def stats(values):
    values = [v for v in values if v is not None]
    return {"n": len(values), **({"min": round(min(values), 6),
        "p50": round(quantile(values, .5), 6), "p95": round(quantile(values, .95), 6),
        "p99": round(quantile(values, .99), 6), "max": round(max(values), 6),
        "sum": round(sum(values), 6)} if values else {})}


def contained(a, b):
    return a[0] <= b[0] <= b[1] <= a[1]


def validate_ids(rows, field):
    require(len({r[field] for r in rows}) == len(rows), "duplicate request ID")


def output_allowed(repo, output):
    allowed = (repo / ALLOWED).resolve()
    require(output.is_relative_to(allowed) and output != allowed and not output.exists(),
            "new output directory under R8 required")


def occupancy(requests):
    events = defaultdict(Counter)
    for r in requests:
        for a, b in spans(r["holds"]):
            events[a][r["operation"]] += 1
            events[b][r["operation"]] -= 1
    current, last, peak, saturated, distribution = Counter(), None, 0, [], Counter()
    saturated_owners = Counter()
    for stamp, deltas in sorted(events.items()):
        n = sum(current.values())
        if last is not None:
            distribution[n] += stamp - last
            if n == 10:
                saturated.append((last, stamp))
                for op, count in current.items():
                    saturated_owners[op] += count * (stamp-last)
        current.update(deltas)
        require(all(v >= 0 for v in current.values()) and 0 <= sum(current.values()) <= 10,
                "closed occupancy outside cap")
        peak = max(peak, sum(current.values()))
        last = stamp
    require(sum(current.values()) == 0, "unbalanced closed occupancy")
    return saturated, {"closed_only_peak": peak, "capacity10_coverage_ms": ms(saturated),
        "closed_occupancy_ms": {str(k): v / 1e6 for k, v in sorted(distribution.items())},
        "capacity10_owner_ms_by_operation_not_wall_ms": {k:v/1e6 for k,v in sorted(saturated_owners.items())}}


def selfchecks():
    checks = [
        merge([(0, 10), (20, 30)]) == [(0, 10), (20, 30)],
        merge([(0, 10), (2, 12)]) == [(0, 12)],
        merge([(0, 10), (10, 20)]) == [(0, 20)],
        difference([(0, 20)], [(5, 10), (12, 25)]) == [(0, 5), (10, 12)],
        intersection([(0, 10), (20, 30)], [(5, 25)]) == [(5, 10), (20, 25)],
        ms(difference([(0, 10_000_000)], [(2_000_000, 8_000_000)])) == 4,
        ms([(0, 20)]) == ms(intersection([(0, 20)], [(5, 10)])) +
            ms(difference([(0, 20)], [(5, 10)])),
        quantile([1, 2, 3, 3], .95) == 3,
        stats([]) == {"n": 0}, quantile([5], .99) == 5,
        spans([{"start_ns": 0, "end_ns": None}]) == [],
        stats([None]) == {"n": 0},
        stats([None, 10])["n"] == 1,
        len([v for v in [False, True, False] if not v]) == 2,
        contained((0, 10), (8, 10)) and not contained((0, 10), (8, 12)),
    ]
    require(all(checks), "pure interval/clock/population check failed")
    failures = 0
    for operation in (lambda: merge([(10, 1)]),
                      lambda: validate_ids([{"id": "same"}, {"id": "same"}], "id"),
                      lambda: output_allowed(Path("/repo"), Path("/outside"))):
        try:
            operation()
        except ValueError:
            failures += 1
    require(failures == 3, "rejection selfcheck failed")
    fake = [{"request_id":"test", "sql":[{"pid":1,"start_ns":0,"end_ns":10,
        "static_sha256":"fake", "statement_class":"select"}]}]
    tick = [{"tick_ns":8,"end_ns":12,"activity":[{"pid":2,"wait_event_type":"Lock","blockers":[]}]}]
    require(pg_correlations("fake",fake,tick) == [], "PID reuse/exact PID exclusion")
    tick[0]["activity"][0]["pid"] = 1
    tick[0]["tick_ns"] = 11
    require(pg_correlations("fake",fake,tick) == [], "same PID disjoint-time exclusion")
    _, cap = occupancy([{"operation": "submit", "holds": [{"start_ns": 0, "end_ns": 10}]}])
    require(cap["closed_only_peak"] == 1, "occupancy selfcheck")
    return 20


def selection(repo):
    paths = set(HELPERS)
    paths.add(ALLOWED+"/analyze.py")
    paths.add("v2/experiments/action_executor/analysis/tip054-4b-r6/analyze.py")
    for gate in RUNS.values():
        base, bind = RAW + "/" + gate + "/", RAW + "/r_bind_" + gate + "/"
        paths.update(base + n for n in ("samples.json", "samples.jsonl", "latency-summary.json", "r-controls.json"))
        paths.update(bind + n for n in ("binding-result.json", "source-before.json", "source-after.json",
            "expected-product.sha256", "product-before.sha256", "product-after.sha256"))
        if "_on_" in gate:
            paths.update(base + n for n in ("phase-requests.jsonl", "audit-transactions.jsonl", "pg-waits.jsonl",
                "phase-recorder-cost.json", "audit-recorder-cost.json", "phase-observer-summary.json",
                "audit-observer-summary.json", "pg-monitor-summary.json", "monitor-process.json", "audit-tail-summary.json"))
    paths.update(RAW + "/r7_final_closure/" + n for n in ("summary.json", "closed-r7-raw.json"))
    product = set()
    for directory in ("v2/apps/backend/src", "v2/apps/backend/migrations"):
        product.update(str(p.relative_to(repo)) for p in (repo / directory).rglob("*.py"))
    product.update(("v2/apps/backend/pyproject.toml", "v2/apps/backend/uv.lock", "v2/.env.example"))
    product.update("v2/apps/backend/"+p for p in (
        "migrations/script.py.mako", "src/rtr_copilot/py.typed",
        "src/rtr_copilot/enterprise_corpus/connector_registry.json",
        "src/rtr_copilot/enterprise/release_plan.json",
        "src/rtr_copilot/rag/enterprise_ontology.json", "src/rtr_copilot/pilot/questions.json"))
    paths.update(product)
    require(len(paths) <= 450, "selected file bound")
    manifest, total = {}, 0
    for relative in sorted(paths):
        p = repo / relative
        require(p.is_file() and not p.is_symlink(), "missing/symlink selected input " + relative)
        size = p.stat().st_size
        require(size <= MAX_FILE, "file stat bound")
        total += size
        require(total <= MAX_TOTAL, "total byte bound")
        with p.open("rb") as stream:
            data = stream.read(MAX_FILE+1)
        require(len(data) == size and len(data) <= MAX_FILE, "file changed/byte bound")
        manifest[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    fingerprint = hashlib.sha256("".join(manifest[p]["sha256"] + "  " + p + "\n"
                                        for p in sorted(product)).encode()).hexdigest()
    require(fingerprint == PRODUCTS["candidate"], "whole current product fingerprint changed")
    return manifest, sorted(product), fingerprint


def read(repo, manifest, path, lines=False):
    require(path in manifest, "unselected read")
    require((repo/path).stat().st_size == manifest[path]["bytes"], "input size changed")
    with (repo/path).open("rb") as stream:
        data = stream.read(MAX_FILE+1)
    require(hashlib.sha256(data).hexdigest() == manifest[path]["sha256"], "input changed during read")
    if lines:
        require(len(data.splitlines()) <= MAX_LINES, "line bound")
        return [json.loads(v) for v in data.splitlines()]
    return json.loads(data)


def rid(sample):
    return f'tip054-latency-{sample["profile"]}-{sample["case"]}-{sample["operation"]}'


def reproduce(samples, original):
    require(len(samples) <= 1600, "HTTP bound")
    require(len({rid(s) for s in samples}) == len(samples), "duplicate HTTP ID")
    cells = []
    for p in PROFILES:
        for op in OPS:
            cohort = [s for s in samples if s["profile"] == p and s["operation"] == op]
            values, limit = [s["elapsed_ms"] for s in cohort], 500 if op == "admission" else 1000
            c = {"concurrency": p, "operation": op, "samples": len(cohort),
                "failures": sum(not s["okay"] for s in cohort), "p50_ms": quantile(values, .5),
                "p95_ms": quantile(values, .95), "p99_ms": quantile(values, .99), "p95_limit_ms": limit}
            c["pass"] = len(cohort) == 100 and c["failures"] == 0 and c["p95_ms"] <= limit
            cells.append(c)
    require(cells == original["cells"], "original16 cells not exactly reproduced")
    return {"samples": len(samples), "failed_http": sum(not s["okay"] for s in samples),
        "passed_cells": sum(c["pass"] for c in cells), "original_status": original["status"], "cells": cells}


def phase_rows(request, names):
    return [p for p in request["phases"] if p["name"] in names]


def phase_events(events, phases):
    ids = {p["phase_id"] for p in phases}
    return [e for e in events if ids.intersection(e.get("phase_ids", []))]


def request_row(gate, request, sample, txs, saturated):
    start, end = request["start_ns"], request["end_ns"]
    require(request["closed"] and end is not None and start < end, "unclosed request")
    for kind in ("holds", "sql", "pool", "phases"):
        require(len(request[kind]) <= 4096, "request event bound")
        require(all(start <= a <= b <= end for a, b in spans(request[kind])), "clock outside request")
    pool = {k: sorted([v for v in request["pool"] if v["kind"] == k], key=lambda v: v["start_ns"])
            for k in ("connect", "_do_get", "_create_connection")}
    connect, get, create = (spans(pool[k]) for k in pool)
    hold, sql = spans(request["holds"]), spans(request["sql"])
    finals = phase_rows(request, {"ActionService._metadata_plan"} if request["operation"] == "admission"
                        else {"ExecutionService._view"})
    final = spans(finals)
    final_start = min((p["start_ns"] for p in finals), default=None)
    final_end = max((p["end_ns"] for p in finals if p["end_ns"] is not None), default=None)
    fsql, fconn = phase_events(request["sql"], finals), phase_events(pool["connect"], finals)
    attempts = [a for tx in txs for a in tx["audit_attempts"]]
    grants = [(t["first_audit_grant_ns"], t["terminal_ns"]) for t in txs
              if t["first_audit_grant_ns"] is not None and t["terminal_ns"] is not None]
    terminals = [(t["start_ns"], t["terminal_ns"]) for t in txs if t["terminal_ns"] is not None]
    commits = [t for t in txs if t["terminal_kind"] == "commit_ack" and t["terminal_ns"] is not None]
    audited = [t for t in commits if t["first_audit_grant_ns"] is not None]
    prior_audited = [t["terminal_ns"] for t in audited if final_start is not None and t["terminal_ns"] <= final_start]
    require(all(start <= t["start_ns"] <= end and
        (t["terminal_ns"] is None or t["start_ns"] <= t["terminal_ns"] <= end) for t in txs), "TX clock outside request")
    roots = spans([p for p in request["phases"] if not p["parent_ids"]])
    split = defaultdict(list)
    mapped = []
    for h in sorted(request["holds"], key=lambda v: v["start_ns"]):
        if h["end_ns"] is None:
            continue
        candidates = [i for i, c in enumerate(pool["connect"])
                      if c["end_ns"] is not None and c["error_type"] is None
                      and c["start_ns"] <= h["start_ns"] <= c["end_ns"]]
        ordinal = candidates[0] if len(candidates) == 1 else None
        span = (h["start_ns"], h["end_ns"])
        mapped.append({"connect_attempt_index": ordinal, "start_ns": span[0], "end_ns": span[1]})
        if request["operation"] not in {"admission", "submit"} or ordinal is None:
            split["unassigned"].append(span)
        elif ordinal == 0:
            split["initial"].append(span)
        elif final_start is None:
            split["mutation_pre_final_or_unassigned_gap"].append(span)
        else:
            split["mutation_pre_final_or_unassigned_gap"] += intersection([span], [(start, final_start)])
            split["final_caller_coverage"] += intersection([span], final)
            split["after_final_caller_or_unassigned"] += difference(
                intersection([span], [(final_start, end)]), final)
    require(abs(ms(hold) - sum(ms(v) for v in split.values())) < .000001, "hold partition not disjoint")
    row = {"gate": gate, "request_id": request["request_id"], "profile": request["profile"],
        "case": request["case"], "operation": request["operation"], "okay": sample["okay"],
        "http_status": sample.get("http_status"), "error_code": sample.get("error_code"),
        "http_ms": sample["elapsed_ms"], "observer_ms": (end-start)/1e6,
        "sample_minus_observer_ms": sample["elapsed_ms"]-(end-start)/1e6,
        "root_union_ms": ms(roots), "outside_root_ms": ms(difference([(start, end)], roots)),
        "connect_union_ms": ms(connect), "get_union_ms": ms(get), "creation_union_ms": ms(create),
        "connect_outside_get_residual_ms": ms(difference(connect, get)),
        "get_outside_creation_residual_ms": ms(difference(get, create)),
        "connect_count": len(pool["connect"]), "creation_count": len(pool["_create_connection"]),
        "creation_only_union_ms": ms(create) if pool["_create_connection"] else None,
        "successful_connect_count": sum(c["end_ns"] is not None and c["error_type"] is None for c in pool["connect"]),
        "first_connect_ms": ms(spans(pool["connect"][:1])) if pool["connect"] else None,
        "later_connect_union_ms": ms(spans(pool["connect"][1:])),
        "connect_capacity10_ms": ms(intersection(connect, saturated)),
        "connect_started_at_checkedout10": sum(c["before"]["checked_out"] >= 10 for c in pool["connect"]),
        "hold_count": len(hold), "hold_union_ms": ms(hold),
        "hold_before_final_ms": ms(intersection(hold,[(start,final_start)])) if final_start is not None else None,
        "hold_during_final_ms": ms(intersection(hold,final)) if finals else None,
        "hold_after_final_ms": ms(intersection(hold,[(final_end,end)])) if final_end is not None else None,
        "longest_hold_ms": max(((b-a)/1e6 for a,b in hold), default=None),
        "sql_count": len(request["sql"]), "sql_union_ms": ms(sql),
        "sql_pid_missing": sum(s["pid"] is None for s in request["sql"]),
        "held_sql_ms": ms(intersection(hold, sql)), "held_non_sql_residual_ms": ms(difference(hold, sql)),
        "audit_acquisition_ms": ms(spans(attempts)), "known_grant_terminal_coverage_ms": ms(grants),
        "known_terminal_coverage_ms": ms(terminals),
        "known_grant_only_union_ms": ms(grants) if grants else None,
        "known_terminal_only_union_ms": ms(terminals) if terminals else None,
        "audited_ack_to_final_span_ms": (final_start-max(prior_audited))/1e6 if prior_audited else None,
        "audited_ack_to_final_held_coverage_ms": ms(intersection(hold,[(max(prior_audited),final_start)])) if prior_audited else None,
        "unknown_terminals": sum(t["terminal_ns"] is None for t in txs),
        "unknown_granted_terminals": sum(t["first_audit_grant_ns"] is not None and t["terminal_ns"] is None for t in txs),
        "any_commit_ack": bool(commits), "audited_commit_ack": bool(audited),
        "any_rollback_ack": any(t["terminal_kind"] == "rollback_ack" for t in txs),
        "terminal_kinds": dict(sorted(Counter(t["terminal_kind"] for t in txs).items())),
        "transactions": [{k: t[k] for k in ("transaction_number", "pid", "start_ns", "terminal_ns",
            "terminal_kind", "first_audit_grant_ns", "postgrant_sql_started")} for t in txs],
        "holds": mapped, "hold_split": {k: {"coverage_ms": ms(split[k]), "sql_overlap_ms": ms(intersection(split[k], sql)),
            "non_sql_residual_ms": ms(difference(split[k], sql))} for k in sorted(split)},
        "connect_errors": [c for c in pool["connect"] if c["error_type"] is not None],
        "sql_errors": [s for s in request["sql"] if s["error_type"] is not None],
        "phase_errors": [{k: p[k] for k in ("name", "start_ns", "end_ns", "error_type")}
                         for p in request["phases"] if p["error_type"] is not None],
        "final": {"calls": len(finals), "spans": final, "union_ms": ms(final),
            "sql_count": len(fsql), "sql_union_ms": ms(spans(fsql)), "connect_count": len(fconn),
            "connect_union_ms": ms(spans(fconn)), "errors": [p["error_type"] for p in finals],
            "held_ms": ms(intersection(hold, final)), "outside_sql_connect_residual_ms": ms(difference(final, sql+connect))},
        "open_events": {k: sum(v["end_ns"] is None for v in request[k]) for k in ("holds", "sql", "pool", "phases")}}
    row["phase_metrics"] = {}
    for name in sorted({p["name"] for p in request["phases"]}):
        selected = phase_rows(request, {name})
        ids = {p["phase_id"] for p in selected}
        children = spans([p for p in request["phases"] if p["parent_ids"] and p["parent_ids"][-1] in ids])
        row["phase_metrics"][name] = {"count": len(selected), "union_ms": ms(spans(selected)),
            "outside_children_ms": ms(difference(spans(selected), children))}
    row["sql_by_digest"] = {}
    phase_names = {p["phase_id"]:p["name"] for p in request["phases"]}
    for digest in sorted({s["static_sha256"] for s in request["sql"]}):
        chosen = [s for s in request["sql"] if s["static_sha256"] == digest]
        row["sql_by_digest"][digest] = {"count": len(chosen), "union_ms": ms(spans(chosen)),
            "class": chosen[0]["statement_class"], "unfinished": sum(s["end_ns"] is None for s in chosen),
            "innermost_phase_counts": dict(sorted(Counter(phase_names[s["phase_ids"][-1]] if s["phase_ids"] else "outside_profiled_phase"
                                                        for s in chosen).items()))}
    row["dominant_sql_digest"] = max(row["sql_by_digest"], key=lambda d: (row["sql_by_digest"][d]["union_ms"], d), default=None)
    row["outcome_class"] = None
    if not sample["okay"]:
        errors = "connect_error" if row["connect_errors"] else "sql_error" if row["sql_errors"] else "no_connect_or_sql_error"
        outcome = "audited_commit_ack" if audited else "unaudited_commit_ack" if commits else "rollback_ack" if row["any_rollback_ack"] else "no_observed_ack"
        row["outcome_class"] = outcome + "/" + errors
        row["ack_before_final"] = bool(commits and finals and max(t["terminal_ns"] for t in commits) <= min(p["start_ns"] for p in finals))
    return row


def pg_correlations(gate, requests, ticks):
    require(len(ticks) <= 3600, "PG tick bound")
    bypid = defaultdict(list)
    for r in requests:
        for s in r["sql"]:
            if s["pid"] is not None and s["end_ns"] is not None:
                bypid[s["pid"]].append((r, s))
    out = []
    for tick in ticks:
        a, b = tick["tick_ns"], tick["end_ns"]
        for activity in tick.get("activity", []):
            if activity["wait_event_type"] != "Lock":
                continue
            for r, s in bypid.get(activity["pid"], []):
                if not s["start_ns"] <= a <= s["end_ns"]:
                    continue
                blockers = sorted({q["request_id"] for pid in activity["blockers"] for q, v in bypid.get(pid, [])
                                   if q["request_id"] != r["request_id"] and contained((v["start_ns"], v["end_ns"]), (a,b))})
                out.append({"gate": gate, "request_id": r["request_id"], "pid": activity["pid"],
                    "tick_ns": a, "tick_end_ns": b, "sql_start_ns": s["start_ns"], "sql_end_ns": s["end_ns"],
                    "static_sha256": s["static_sha256"], "statement_class": s["statement_class"],
                    "whole_tick_envelope_contained": contained((s["start_ns"], s["end_ns"]), (a,b)),
                    "blocker_pids": activity["blockers"], "whole_envelope_blocker_request_candidates": blockers})
    return out


def cohorts(rows):
    p95 = quantile([r["http_ms"] for r in rows], .95)
    return {"all": rows, "success": [r for r in rows if r["okay"]], "failure": [r for r in rows if not r["okay"]],
        "http_p95_tail_with_ties": [r for r in rows if r["http_ms"] >= p95] if p95 is not None else [],
        "http_sla_exceeded": [r for r in rows if r["http_ms"] > (500 if r["operation"] == "admission" else 1000)]}


def aggregate(gate, rows):
    cells, ranks = [], []
    numeric = sorted(k for k, v in rows[0].items() if isinstance(v, (int,float)) and not isinstance(v, bool))
    numeric = sorted(set(numeric+ ["first_connect_ms", "longest_hold_ms", "known_grant_only_union_ms", "known_terminal_only_union_ms",
        "creation_only_union_ms", "audited_ack_to_final_span_ms", "audited_ack_to_final_held_coverage_ms",
        "hold_before_final_ms", "hold_during_final_ms", "hold_after_final_ms"]) - {"profile", "case", "http_status"})
    for profile in PROFILES:
        for operation in OPS:
            group = [r for r in rows if r["profile"] == profile and r["operation"] == operation]
            item = {"profile": profile, "operation": operation, "cohorts": {}}
            for label, chosen in cohorts(group).items():
                phases = sorted({p for r in chosen for p in r["phase_metrics"]})
                split = sorted({p for r in chosen for p in r["hold_split"]})
                item["cohorts"][label] = {"n": len(chosen),
                    "request_ids": [r["request_id"] for r in chosen] if label != "all" else [],
                    "metrics": {k: stats([r.get(k) for r in chosen]) for k in numeric},
                    "hold_count_histogram": dict(sorted(Counter(str(r["hold_count"]) for r in chosen).items())),
                    "outcome_classes": dict(sorted(Counter(r["outcome_class"] for r in chosen if r["outcome_class"]).items())),
                    "open_events": {k: sum(r["open_events"][k] for r in chosen) for k in ("holds", "sql", "pool", "phases")},
                    "hold_splits": {k: {m: stats([r["hold_split"][k][m] for r in chosen if k in r["hold_split"]])
                        for m in ("coverage_ms", "sql_overlap_ms", "non_sql_residual_ms")} for k in split},
                    "phases": {k: {m: stats([r["phase_metrics"][k][m] for r in chosen if k in r["phase_metrics"]])
                        for m in ("count", "union_ms", "outside_children_ms")} for k in phases},
                    "final_metrics": {k: stats([r["final"][k] for r in chosen]) for k in
                        ("calls", "union_ms", "sql_count", "sql_union_ms", "connect_count", "connect_union_ms", "held_ms", "outside_sql_connect_residual_ms")}}
                rank = []
                for digest in sorted({d for r in chosen for d in r["sql_by_digest"]}):
                    values = [r["sql_by_digest"][digest] for r in chosen if digest in r["sql_by_digest"]]
                    rank.append({"gate": gate, "profile": profile, "operation": operation, "cohort": label,
                        "digest": digest, "known_audit827004": digest == AUDIT, "statement_class": values[0]["class"],
                        "requests_with_statement": len(values), "count": sum(v["count"] for v in values),
                        "per_request_closed_union_ms": stats([v["union_ms"] for v in values]),
                        "unfinished": sum(v["unfinished"] for v in values),
                        "innermost_phase_counts": dict(sorted(sum((Counter(v["innermost_phase_counts"]) for v in values),Counter()).items())),
                        "dominant_request_count": sum(r["dominant_sql_digest"] == digest for r in chosen)})
                ranks += sorted(rank, key=lambda v: (-v["per_request_closed_union_ms"].get("sum", 0), v["digest"]))
            cells.append(item)
    return cells, ranks


LIMITS = [
    "OFF is unchanged acceptance and FAIL; ON diagnostic serial runs do not establish causal gains.",
    "Closed hold union missing/open durations are censored; initial/mutation/final split uses observed checkout mapping and final caller entry, NOT private teardown/transaction boundary.",
    "Known terminal/grant coverage across ALL requests can be empty0; known-only metrics exclude absent/unknown clocks. Unknown terminals remain missing, not rollback.",
    "connect contains nested get/creation plus pre_ping/retry/scheduling; residuals are not measured pure wait/ping/CPU.",
    "SQL envelopes are client wall-time, static dominance is association not server work or continuous lock wait.",
    "PG strict point/full-envelope matches are temporal candidates within two non-atomic sampler queries; finite50ms sampling misses short waits and PID-only attribution is forbidden.",
    "Closed occupancy is reconstructed returned-hold coverage, not complete live-pool telemetry; capacity overlap does not identify causing holder.",
    "Phase recorder cost lies after its own stamped end; audit recorder cost occurs inside transaction-end callbacks; costs have no absolute clocks for attribution/correction.",
    "No worker/provider fixture: cannot implicate DBOS/LLM. OFF has no outcome clocks; ON cannot prove OFF commit/rollback.",
    "Neither-error cancelled final-envelope residual is not proven cleanup fault; implicit wire/pre_ping/terminal tasks not separately instrumented.",
    "Admission has500ms SLA but no execution API0.9s timer; submit/status/cancel timer includes joined cleanup. No budget is raised or moved outside timing.",
    "PG sampler lacks advisory classid/objid;827004 is static-SQL SHA association, not exact sampled PG lock-object identity.",
]


def main(repo, output):
    output_allowed(repo, output)
    manifest, product_paths, product_sha = selection(repo)  # Hash BEFORE parsing/calculation.
    closure = read(repo, manifest, RAW + "/r7_final_closure/closed-r7-raw.json")
    historic = dict(closure["rows"])
    matched = {p: v["sha256"] for p, v in manifest.items() if p.startswith(RAW+"/") and p.removeprefix(RAW+"/") in historic}
    require(all(v == historic[p.removeprefix(RAW+"/")] for p,v in matched.items()), "recorded R7 raw integrity mismatch")
    result, rows, ranks, correlations, bindings = {}, [], [], [], {}
    for label, gate in RUNS.items():
        base, bind = RAW+"/"+gate+"/", RAW+"/r_bind_"+gate+"/"
        samples = read(repo, manifest, base+"samples.jsonl", True)
        require(samples == read(repo, manifest, base+"samples.json"), "sample JSONL/JSON mismatch")
        result[label] = {"population": reproduce(samples, read(repo, manifest, base+"latency-summary.json"))}
        before, after = (read(repo, manifest, bind+n) for n in ("source-before.json", "source-after.json"))
        binding = read(repo, manifest, bind+"binding-result.json")
        epoch = label.split("_")[0]
        require(before == after and len(before) == (396 if epoch == "baseline" else 400) and
            binding["boundary_status"] == "PASS" and binding["expected_product_sha256"] ==
            binding["product_before_sha256"] == binding["product_after_sha256"] == PRODUCTS[epoch], "binding epoch mismatch")
        for helper in HELPERS:
            key = "verification_r/"+helper.split("/r/",1)[1] if "/r/" in helper else "verification/"+Path(helper).name
            require(before[key] == manifest[helper]["sha256"], "helper changed")
        if epoch == "candidate":
            for path in product_paths:
                key = path.removeprefix("v2/apps/backend/") if path != "v2/.env.example" else path
                if key in before:
                    require(before[key] == manifest[path]["sha256"], "current bound product byte changed")
        bindings[label] = {"product_sha256": PRODUCTS[epoch], "binding_count": len(before), "before_after_equal": True}
        controls = read(repo, manifest, base+"r-controls.json")
        require(controls["observer"] == label.split("_")[1] and controls["pool_size"] == controls["max_overflow"] == 5 and
            controls["pre_ping"] and controls["operation_timeout_seconds"] == .9 and not controls["worker"] and not controls["provider"], "controls changed")
        if label.endswith("off"):
            continue
        requests = read(repo, manifest, base+"phase-requests.jsonl", True)
        audit = read(repo, manifest, base+"audit-transactions.jsonl", True)
        ticks = read(repo, manifest, base+"pg-waits.jsonl", True)
        validate_ids(requests, "request_id")
        sample_by_id = {rid(s): s for s in samples}
        require(len(requests) <= 1600 and {r["request_id"] for r in requests} == set(sample_by_id), "request/sample bijection")
        audits = defaultdict(list)
        for tx in audit:
            require(tx["request_id"] in sample_by_id, "unmapped TX")
            audits[tx["request_id"]].append(tx)
        require(all(len(v) <= 64 for v in audits.values()), "TX/request bound")
        saturated, capacity = occupancy(requests)
        chosen = [request_row(gate,r,sample_by_id[r["request_id"]],audits[r["request_id"]],saturated) for r in requests]
        pg = pg_correlations(gate, requests, ticks)
        byrequest = Counter(v["request_id"] for v in pg if v["whole_tick_envelope_contained"])
        for row in chosen:
            row["whole_tick_lock_candidates"] = byrequest[row["request_id"]]
        cells, sql_ranks = aggregate(gate, chosen)
        phase_summary, audit_summary = (read(repo, manifest, base+n) for n in ("phase-observer-summary.json", "audit-observer-summary.json"))
        require(phase_summary["requests"] == len(requests) and audit_summary["transactions"] == len(audit), "observer counts mismatch")
        costs = {kind: {k: stats([v[k] for v in read(repo,manifest,base+kind+"-recorder-cost.json")]) for k in ("serialize_ms", "append_flush_ms")} for kind in ("phase", "audit")}
        result[label].update({"interval_cells": cells, "closed_occupancy": capacity, "costs": costs,
            "phase_summary": phase_summary, "audit_summary": audit_summary,
            "actual_chain_after_timing": read(repo,manifest,base+"audit-tail-summary.json")["actual_chain_after_timing"],
            "pg": {"ticks": len(ticks), "errors": sum("error_type" in t for t in ticks),
                "lock_activity_samples": sum(a["wait_event_type"] == "Lock" for t in ticks for a in t.get("activity",[])),
                "point_candidates": len(pg), "whole_envelope_candidates": sum(v["whole_tick_envelope_contained"] for v in pg),
                "whole_envelope_digest_counts": dict(sorted(Counter(v["static_sha256"] for v in pg if v["whole_tick_envelope_contained"]).items()))},
            "failed_request_ids": [r["request_id"] for r in chosen if not r["okay"]],
            "failed_outcome_classes": dict(sorted(Counter(r["outcome_class"] for r in chosen if not r["okay"]).items()))})
        rows += chosen
        ranks += sql_ranks
        correlations += pg
    require(result["candidate_on"]["population"]["failed_http"] == 19, "candidate19 completeness")
    require(selection(repo)[0] == manifest, "selected before/after hashes changed")
    payloads = {
        "summary.json": {"status": "OFFLINE_DIAGNOSIS_EXECUTOR_NOT_READY", "runs": result, "limits": LIMITS, "selfchecks_passed": selfchecks()},
        "provenance.json": {"inputs_before_after_equal": True, "inputs": manifest, "selected_files": len(manifest),
            "selected_bytes": sum(v["bytes"] for v in manifest.values()), "recorded_R7_raw_hashes_matched": len(matched),
            "recorded_closure_inventory_sha256": manifest[RAW+"/r7_final_closure/closed-r7-raw.json"]["sha256"],
            "whole_product_sha256": product_sha, "whole_product_paths": product_paths, "bindings": bindings,
            "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "bounds": {"files":450,"file_bytes":MAX_FILE,"total_bytes":MAX_TOTAL,"requests":1600,"events_per_kind":4096,"tx_per_request":64,"ticks":3600,"jsonl_lines":MAX_LINES},
            "historical_integrity_distinct_from_current_rehash": True},
    }
    encoded = {name:json.dumps(value,sort_keys=True,indent=2)+"\n" for name,value in payloads.items()}
    for name, values in (("requests.jsonl",rows),("sql-rank.jsonl",ranks),("pg-correlations.jsonl",correlations)):
        encoded[name] = "".join(json.dumps(v,sort_keys=True,separators=(",",":"))+"\n" for v in values)
    require(all(len(v.encode()) <= MAX_FILE for v in encoded.values()) and sum(len(v.encode()) for v in encoded.values()) <= MAX_TOTAL, "output bound")
    output.mkdir(parents=True,exist_ok=False)
    for name,value in encoded.items():
        with (output/name).open("x",encoding="utf-8") as stream:
            stream.write(value)
    print(json.dumps({"status":"OFFLINE_ONLY","inputs":len(manifest),"requests":len(rows),"pg_candidates":len(correlations),"selfchecks":20},sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--selfcheck",action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        print(json.dumps({"selfchecks_passed":selfchecks()},sort_keys=True))
    else:
        require(args.repo is not None and args.output is not None,"repo/output required")
        selfchecks()
        main(args.repo.resolve(),args.output.resolve())
