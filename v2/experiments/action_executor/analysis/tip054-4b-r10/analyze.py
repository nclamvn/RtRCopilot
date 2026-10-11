"""R10 bounded offline wall-coverage replay. No SDK, runtime or causal model."""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

MANIFEST_SHA = "d43b8628af2ccc0154e6ed58500795b117685e67ac976c39235ee8bfccc4ed85"
BASE = "v2/experiments/action_executor/analysis/tip054-4b-r10"
RAW = "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1"
MAX_FILE, MAX_TOTAL, MAX_FILES = 32 * 1024**2, 64 * 1024**2, 80
CATEGORIES = (
    "sql", "pool_connect", "pool_do_get", "creation", "ping", "queue_get",
    "terminal_join", "terminal_io", "closed_hold", "audit_acquire",
    "known_audit_tail", "observed_final_phase",
)
INTEGRITY_KEYS = {
    "dropped", "late", "callback_errors", "unmapped_wake", "unweak_resource",
    "sampler_limit", "costs_dropped", "late_events", "open_events",
    "pending_getters", "timer_active",
}
AUDIT_SHA = "2cf9705ca791be7b1767b6ddbf200944255cebc5f5702b5b7c9776d1f3ba6597"
OPERATIONS = ("admission", "submit", "status", "cancel")
PROFILES = (1, 10, 25, 50)


def clock(value):
    if type(value) is not int or value < 0:
        raise ValueError("invalid nonnegative integer clock")
    return value


def partition(start_ns, end_ns, categories):
    """Disjoint half-open masks; missing/open spans contribute no invented time."""
    lo, hi = clock(start_ns), clock(end_ns)
    if hi <= lo:
        raise ValueError("HTTP window must have positive width")
    changes = defaultdict(Counter)
    changes[lo]; changes[hi]
    counts = {}
    for name in sorted(categories):
        count = Counter(closed=0, zero=0, open=0, outside=0, clipped=0)
        for start, end in categories[name]:
            if start is not None:
                clock(start)
            if end is not None:
                clock(end)
            if start is None or end is None:
                count["open"] += 1
                continue
            if end < start:
                raise ValueError("reversed span clock")
            count["closed"] += 1
            if end == start:
                count["zero"] += 1
                continue
            if end <= lo or start >= hi:
                count["outside"] += 1
                continue
            a, b = max(lo, start), min(hi, end)
            count["clipped"] += (a, b) != (start, end)
            changes[a][name] += 1
            changes[b][name] -= 1
        counts[name] = dict(count)
    points, active, masks, segments = sorted(changes), Counter(), Counter(), []
    for index, a in enumerate(points[:-1]):
        active.update(changes[a])
        if any(value < 0 for value in active.values()):
            raise ValueError("invalid sweep balance")
        b = points[index + 1]
        label = "|".join(sorted(name for name, n in active.items() if n > 0)) or "unclassified"
        masks[label] += b - a
        if segments and segments[-1][2] == label:
            segments[-1][1] = b
        else:
            segments.append([a, b, label])
    if sum(masks.values()) != hi - lo:
        raise ValueError("coverage conservation failed")
    return {"envelope_ns": hi - lo, "mask_ns": dict(sorted(masks.items())),
            "segments": segments, "counts": counts}


def nearest_rank(values, q=.95):
    if not 0 < q <= 1 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid quantile input")
    return sorted(values)[math.ceil(len(values) * q) - 1] if values else None


def cell(samples, profile, operation):
    rows = [r for r in samples if r["profile"] == profile and r["operation"] == operation]
    values = [r["elapsed_ms"] for r in rows]
    limit, errors = (500 if operation == "admission" else 1000), sum(not r["okay"] for r in rows)
    p95 = nearest_rank(values)
    return {"n": len(rows), "errors": errors, "p50_ms": nearest_rank(values, .5),
            "p95_ms": p95, "p99_ms": nearest_rank(values, .99), "limit_ms": limit,
            "passed": len(rows) == 100 and errors == 0 and p95 is not None and p95 <= limit}


def terminal_flags(transactions):
    counts = Counter(r["terminal_kind"] for r in transactions)
    for row in transactions:
        clock(row["start_ns"])
        if row["terminal_ns"] is not None:
            clock(row["terminal_ns"])
            if row["terminal_ns"] < row["start_ns"]:
                raise ValueError("reversed terminal clock")
        if row["terminal_kind"] in {"commit_ack", "rollback_ack"} and row["terminal_ns"] is None:
            raise ValueError("ACK lacks clock")
    return {"transactions": len(transactions), "commit_ack": counts["commit_ack"],
            "rollback_ack": counts["rollback_ack"],
            "unknown": sum(n for kind, n in counts.items() if kind not in {"commit_ack", "rollback_ack"}),
            "audited_commit_ack": sum(r["terminal_kind"] == "commit_ack" and bool(r["append_spans"])
                                      for r in transactions)}


def partial_cost(values):
    for value in values:
        clock(value)
    return {"n": len(values), "sum_ns": sum(values), "p95_ns": nearest_rank(values),
            "allocation": "unkeyed_aggregate_only"}


def outer_inner(sample_elapsed_ms, start_ns, end_ns):
    clock(start_ns); clock(end_ns)
    if end_ns < start_ns or not math.isfinite(sample_elapsed_ms) or sample_elapsed_ms < 0:
        raise ValueError("invalid outer/inner clock")
    inner = (end_ns - start_ns) / 1e6
    return {"outer_ms": sample_elapsed_ms, "inner_ms": inner,
            "residual_ms": sample_elapsed_ms - inner, "label": "noncausal_scalar_gap"}


def namespace_key(namespace, identity):
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("empty identity namespace")
    return namespace, identity


def safe_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe relative path")
    path = root / relative
    if path.resolve() != path.absolute() or not path.is_relative_to(root):
        raise ValueError("symlink/path escape")
    return path


def validate_output(root, output):
    root, output = root.resolve(), output.absolute()
    base = root / BASE
    if output.exists() or output.is_symlink() or output == base or not output.is_relative_to(base):
        raise ValueError("output must be NEW non-root directory under R10")
    if output.resolve() != output or not base.is_dir():
        raise ValueError("output path symlink/escape")
    return output


def bounded_read(path, expected):
    size = path.stat().st_size
    if size != expected["bytes"] or size > MAX_FILE:
        raise ValueError("file size/cap mismatch")
    raw = path.read_bytes()
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError("input digest mismatch")
    return raw


def load_inputs(root):
    """Pinned manifest itself is the immutable literal 55-path allowlist."""
    root = root.resolve()
    manifest_path = safe_path(root, BASE + "/technical-freeze-e1/selected-inputs.json")
    if manifest_path.stat().st_size > 65536:
        raise ValueError("manifest cap")
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA:
        raise ValueError("fixed manifest pin mismatch")
    manifest = json.loads(raw)
    files = manifest["files"]
    if len(files) != 55 or len(files) > MAX_FILES or len({r["path"] for r in files}) != len(files):
        raise ValueError("fixed allowlist count/duplicate mismatch")
    total = sum(r["bytes"] for r in files)
    if total != 48484234 or total > MAX_TOTAL:
        raise ValueError("aggregate input cap/mismatch")
    off = [r["path"] for r in files if "/r9m_off_r1/run/" in r["path"]]
    if sorted(Path(r).name for r in off) != sorted(("samples.json", "samples.jsonl", "latency-summary.json", "r-controls.json")):
        raise ValueError("OFF forbidden internal inputs")
    return manifest, {r["path"]: bounded_read(safe_path(root, r["path"]), r) for r in files}


def decode(raw):
    return [json.loads(line) for line in raw.splitlines() if line] 


def request_id(row):
    if type(row["profile"]) is not int or row["profile"] not in PROFILES or row["operation"] not in OPERATIONS or type(row["case"]) is not int or not 0 <= row["case"] < 100:
        raise ValueError("sample identity invalid")
    if type(row["okay"]) is not bool:
        raise ValueError("sample outcome type")
    nearest_rank([row["elapsed_ms"]])
    return f"tip054-latency-{row['profile']}-{row['case']}-{row['operation']}"


def pair(rows):
    return [(row["start_ns"], row["end_ns"]) for row in rows]


def marginals(coverage):
    result = {}
    for name, count in coverage["counts"].items():
        result[name] = (sum(n for mask, n in coverage["mask_ns"].items() if name in mask.split("|"))
                        if count["closed"] else None)
    return result


def validate_local(phase):
    for name in ("phases", "sql", "pool", "holds"):
        if len(phase[name]) > 4096:
            raise ValueError("per-request observation cap")
    local = {r["phase_id"]: r for r in phase["phases"]}
    if len(local) != len(phase["phases"]):
        raise ValueError("duplicate request-local phase ID")
    for row in phase["phases"]:
        if type(row["phase_id"]) is not int or row["phase_id"] < 0:
            raise ValueError("invalid request-local phase ID type")
        start = clock(row["start_ns"])
        end = row["end_ns"]
        if end is not None and clock(end) < start:
            raise ValueError("reversed local phase clock")
        if type(row["parent_ids"]) is not list or len(row["parent_ids"]) > 4096:
            raise ValueError("local parent list schema/cap")
        for parent_id in row["parent_ids"]:
            if type(parent_id) is not int or parent_id not in local or parent_id >= row["phase_id"]:
                raise ValueError("unknown/nonpreceding local parent")
            parent = local[parent_id]
            if clock(parent["start_ns"]) > start or (parent["end_ns"] is not None and end is not None and clock(parent["end_ns"]) < end):
                raise ValueError("local phase parent containment")
    for row in phase["sql"] + phase["pool"] + phase["holds"]:
        clock(row["start_ns"])
        if row["end_ns"] is not None and clock(row["end_ns"]) < row["start_ns"]:
            raise ValueError("reversed local observation clock")
        if type(row["phase_ids"]) is not list or len(row["phase_ids"]) > 4096 or any(type(key) is not int or key not in local for key in row["phase_ids"]):
            raise ValueError("cross-request/unknown phase identity")
    for row in phase["sql"]:
        sha = row["static_sha256"]
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("invalid static SQL digest")


def validate_events(phases, events):
    if any(type(r["span_id"]) is not int for r in events):
        raise ValueError("R9 span ID type")
    by_span = {r["span_id"]: r for r in events}
    if sorted(by_span) != list(range(len(events))):
        raise ValueError("R9 span graph identity")
    by_request = defaultdict(list)
    for row in events:
        if type(row["task_id"]) is not int or row["task_id"] <= 0 or type(row["resource_id"]) is not int or row["resource_id"] <= 0 or row["resource_kind"] not in {"object", "driver"}:
            raise ValueError("R9 task/resource schema")
        partition(row["start_ns"], (row["end_ns"] or row["start_ns"]) + 1, {"check": pair([row])})
        if type(row["parent_ids"]) is not list or len(row["parent_ids"]) > 4096:
            raise ValueError("R9 parent list schema/cap")
        for pid in row["parent_ids"]:
            if type(pid) is not int or pid not in by_span or pid >= row["span_id"]:
                raise ValueError("R9 unknown/nonpreceding parent")
            parent = by_span[pid]
            if parent["start_ns"] > row["start_ns"] or (parent["end_ns"] is not None and row["end_ns"] is not None and parent["end_ns"] < row["end_ns"]):
                raise ValueError("R9 parent clock containment")
        by_request[row["request_id"]].append(row)
        if row["name"] == "queue.wake_ready" and row.get("mapping") == "unique":
            getter_id = row["getter_span_id"]
            if type(getter_id) is not int or getter_id >= row["span_id"]:
                raise ValueError("getter span must precede wake")
            getter = by_span.get(getter_id)
            if getter is None or getter["name"] != "queue.get" or getter["task_id"] != row["getter_task_id"] or getter["request_id"] != row["getter_request_id"] or getter["resource_id"] != row["resource_id"] or type(row["future_id"]) is not int or row["future_id"] <= 0 or row.get("future_ready") is not True:
                raise ValueError("invalid getter/Future mapping")
            if getter["start_ns"] > row["start_ns"] or (getter["end_ns"] is not None and row["end_ns"] is not None and getter["end_ns"] < row["end_ns"]):
                raise ValueError("wake outside mapped getter lifetime")
    if set(by_request) - set(phases):
        raise ValueError("unmapped R9 request")
    for key, phase in phases.items():
        for kind in ("connect", "_do_get", "_create_connection"):
            original = Counter((r["end_ns"] is not None, r["error_type"]) for r in phase["pool"] if r["kind"] == kind)
            new = Counter((r["end_ns"] is not None, r["error_type"]) for r in by_request[key] if r["name"] == "pool." + kind)
            if original != new:
                raise ValueError("pool boundary multiset completeness")
    return by_request


def wake_rows(events, grouped):
    result = defaultdict(list)
    by_span = {r["span_id"]: r for r in events}
    for wake in events:
        if wake["name"] != "queue.wake_ready":
            continue
        key = wake.get("getter_request_id") if wake.get("mapping") == "unique" else wake["request_id"]
        row = {field: wake.get(field) for field in ("span_id", "mapping", "getter_span_id", "getter_task_id", "future_id", "future_ready", "getter_request_id", "producer_request_id")}
        resumed = [r for r in grouped.get(key, ()) if r["name"] == "queue.get_nowait" and r["task_id"] == wake.get("getter_task_id") and wake.get("getter_span_id") in r["parent_ids"] and wake["end_ns"] is not None and r["start_ns"] >= wake["end_ns"]]
        first = min(resumed, key=lambda r: r["start_ns"]) if resumed else None
        getter = by_span.get(wake.get("getter_span_id")) if wake.get("mapping") == "unique" else None
        getter_end = getter["end_ns"] if getter else None
        getter_error = getter["error_type"] if getter else None
        censoring = (None if first else "getter_cancelled_without_observed_consumer" if getter_error == "CancelledError" else "getter_open_without_observed_consumer" if getter and getter_end is None else "unknown_mapping" if getter is None else "closed_getter_without_observed_consumer")
        row.update({"consumer_span_id": first["span_id"] if first else None,
                    "getter_end_ns": getter_end, "getter_error_type": getter_error,
                    "consumer_error_type": first["error_type"] if first else None,
                    "consumer_outcome": "error" if first and first["error_type"] else "returned_attempt" if first else "unobserved",
                    "censorship_reason": censoring,
                    "ready_to_consumer_ns": first["start_ns"] - wake["end_ns"] if first else None,
                    "returned_record_id": first.get("result_resource_id") if first else None,
                    "label": "scheduling_competition_envelope_not_reservation"})
        result[key].append(row)
    return result


def pg_candidates(ticks, phases):
    sql_by_pid, results = defaultdict(list), defaultdict(Counter)
    for key, phase in phases.items():
        for row in phase["sql"]:
            if row["pid"] is not None and row["end_ns"] is not None:
                sql_by_pid[row["pid"]].append((key, row))
    total = Counter()
    for tick in ticks:
        lo, hi = clock(tick["tick_ns"]), clock(tick["end_ns"])
        if hi < lo:
            raise ValueError("PG sampler reversed clock")
        if tick.get("error_type"):
            total["sampler_error_windows"] += 1
        for activity in tick.get("activity", []):
            for key, sql in sql_by_pid.get(activity["pid"], ()):
                if max(lo, sql["start_ns"]) < min(hi, sql["end_ns"]):
                    label = "Lock" if activity.get("wait_event_type") == "Lock" else "other"
                    results[key]["window_overlap_" + label] += 1
                    total["window_overlap_" + label] += 1
                    if sql["start_ns"] <= lo < sql["end_ns"]:
                        results[key]["tick_point_candidate_" + label] += 1
                    if sql["start_ns"] <= lo <= hi <= sql["end_ns"]:
                        results[key]["whole_snapshot_window_candidate_" + label] += 1
                    if label == "Lock" and sql["static_sha256"] == AUDIT_SHA:
                        results[key]["audit_digest_Lock_temporal_candidate"] += 1
    return results, dict(total)


def aggregate(rows):
    observed = [r for r in rows if r["population"] == "ON"]
    coverage = {}
    for name in CATEGORIES:
        values = [r["coverage_marginal_ns"][name] / 1e6 for r in observed if r["coverage_marginal_ns"][name] is not None]
        coverage[name] = {"known_n": len(values), "known_p95_ms": nearest_rank(values)}
    known_envelopes = [r for r in observed if r.get("coverage")]
    dominance = {
        name: sum(r["coverage_marginal_ns"][name] is not None and
                  r["coverage_marginal_ns"][name] * 2 >= r["coverage"]["envelope_ns"]
                  for r in known_envelopes)
        for name in CATEGORIES
    }
    return {"n": len(rows), "errors": sum(not r["sample"]["okay"] for r in rows),
            "ON_observed_requests": len(observed),
            "ids": [r["request_id"] for r in rows], "ON_known_coverage": coverage,
            "ON_category_at_least_half_HTTP_count": dominance,
            "terminal_observation": "ON_client_observed_ACK" if observed else "unobserved_or_empty_cohort",
            "commit_ack_requests": sum(bool(r.get("terminal", {}).get("commit_ack")) for r in observed) if observed else None,
            "audited_commit_ack_requests": sum(bool(r.get("terminal", {}).get("audited_commit_ack")) for r in observed) if observed else None,
            "failed_endpoint_classes": dict(sorted(Counter(r.get("endpoint_class", "unobserved") for r in rows if not r["sample"]["okay"]).items()))}


def analyze(inputs):
    def get(pop, name):
        raw = inputs[f"{RAW}/r9m_{pop.lower()}_r1/run/{name}"]
        return decode(raw) if name.endswith(".jsonl") else json.loads(raw)

    samples = {pop: get(pop, "samples.json") for pop in ("ON", "OFF")}
    for pop, count, failures in (("ON", 1384, 133), ("OFF", 1590, 14)):
        if samples[pop] != get(pop, "samples.jsonl") or len(samples[pop]) != count or sum(not r["okay"] for r in samples[pop]) != failures:
            raise ValueError("closed population/sample representations mismatch")
        if len({request_id(r) for r in samples[pop]}) != count:
            raise ValueError("duplicate sample")
    phase_rows, boundary = get("ON", "phase-requests.jsonl"), get("ON", "pool-boundaries.json")
    phases = {r["request_id"]: r for r in phase_rows}
    if len(phases) != len(phase_rows) or set(phases) != {request_id(r) for r in samples["ON"]}:
        raise ValueError("ON phase/sample identity mismatch")
    if len(boundary["events"]) > 100000 or len(boundary["ticks"]) > 9000 or len(boundary["costs"]) > 210000 or set(boundary["integrity"]) != INTEGRITY_KEYS or any(boundary["integrity"].values()):
        raise ValueError("R9 boundary completeness/count/integrity")
    for phase in phase_rows:
        validate_local(phase)
        expected_key = f"tip054-latency-{phase['profile']}-{phase['case']}-{phase['operation']}"
        if phase["request_id"] != expected_key:
            raise ValueError("original HTTP request fields inconsistent")
    sample_map = {request_id(r): r for r in samples["ON"]}
    if any(any(phase[field] != sample_map[key][field] for field in ("profile", "case", "operation")) for key, phase in phases.items()):
        raise ValueError("sample/root request identity inconsistency")
    grouped = validate_events(phases, boundary["events"])
    wakes = wake_rows(boundary["events"], grouped)
    tx_by_request, tx_ids = defaultdict(list), set()
    for row in get("ON", "audit-transactions.jsonl"):
        if row["request_id"] not in phases or row["transaction_number"] in tx_ids:
            raise ValueError("audit request/transaction identity")
        tx_ids.add(row["transaction_number"])
        tx_by_request[row["request_id"]].append(row)
    pg, pg_total = pg_candidates(get("ON", "pg-waits.jsonl"), phases)
    holds = [(key, r) for key, phase in phases.items() for r in phase["holds"] if r["end_ns"] is not None]
    requests, sql_rank, complexity = [], defaultdict(Counter), Counter()
    for pop in ("ON", "OFF"):
        for sample in sorted(samples[pop], key=request_id):
            key = request_id(sample)
            row = {"population": pop, "request_id": key, "sample": sample}
            if pop == "OFF":
                row["internal_coverage"] = "unobserved"
                requests.append(row)
                continue
            phase, events, tx = phases[key], grouped[key], tx_by_request[key]
            lo, hi = phase["start_ns"], phase["end_ns"]
            if hi is None:
                raise ValueError("unclosed original HTTP envelope")
            cats = {name: [] for name in CATEGORIES}
            cats["sql"], cats["closed_hold"] = pair(phase["sql"]), pair(phase["holds"])
            for name, kind in (("pool_connect", "connect"), ("pool_do_get", "_do_get"), ("creation", "_create_connection")):
                cats[name] = pair([r for r in phase["pool"] if r["kind"] == kind])
            for name, event_name in (("ping", "adapter._async_ping"), ("queue_get", "queue.get"), ("terminal_join", "owner.join_terminal")):
                cats[name] = pair([r for r in events if r["name"] == event_name])
            cats["terminal_io"] = pair([r for r in events if r["name"] in {"AsyncSession.close", "AsyncConnection.close", "adapter._commit_and_discard", "adapter._rollback_and_discard"}])
            cats["audit_acquire"] = pair([a for t in tx for a in t["audit_attempts"]])
            cats["known_audit_tail"] = [(t["first_audit_grant_ns"], t["terminal_ns"]) for t in tx if t["first_audit_grant_ns"] is not None]
            cats["observed_final_phase"] = pair([r for r in phase["phases"] if r["name"] in {"actions._metadata_plan", "execution._view"} or r["name"].endswith("._metadata_plan") or r["name"].endswith("._view")])
            coverage = partition(lo, hi, cats)
            request_ticks = [r for r in boundary["ticks"] if lo <= r["actual_ns"] < hi]
            tick_lags = [clock(r["actual_ns"]) - clock(r["scheduled_ns"]) for r in request_ticks]
            if any(v < 0 for v in tick_lags):
                raise ValueError("negative scheduling lag")
            temporal_holds = [(max(lo, h["start_ns"]), min(hi, h["end_ns"])) for other, h in holds if other != key and max(lo, h["start_ns"]) < min(hi, h["end_ns"])]
            foreign = partition(lo, hi, {"other_request_closed_holds": temporal_holds})
            closed_p = sum(r["end_ns"] is not None for r in phase["phases"])
            visits = closed_p * len(phase["phases"]) + 2 * closed_p * len(phase["sql"])
            complexity["finish_phase_model_loop_visits"] += visits
            local_rank = defaultdict(list)
            for sql in phase["sql"]:
                local_rank[(sql["static_sha256"], sql["statement_class"])].append((sql["start_ns"], sql["end_ns"]))
            ranked = []
            for (digest, kind), spans in local_rank.items():
                covered = partition(lo, hi, {"sql": spans})
                n = sum(v for mask, v in covered["mask_ns"].items() if mask == "sql")
                sql_errors = Counter(r["error_type"] for r in phase["sql"] if r["static_sha256"] == digest and r["statement_class"] == kind and r["error_type"])
                ranked.append({"digest": digest, "class": kind, "known_union_ns": n, "started": len(spans), "open": covered["counts"]["sql"]["open"], "typed_errors": dict(sorted(sql_errors.items()))})
                sql_rank[(digest, kind)]["known_union_ns"] += n
                sql_rank[(digest, kind)]["requests"] += 1
            failed_sql = [r for r in phase["sql"] if r["error_type"]]
            failed_boundaries = [r for r in events if r["error_type"]]
            endpoint_groups = []
            if failed_sql:
                endpoint_groups.append("cursor_error")
            if any(r["name"] == "pool.connect" for r in failed_boundaries):
                endpoint_groups.append("connect_error")
            if any(r["name"] in {"owner.join_terminal", "owner.release_phase", "AsyncSession.close", "AsyncConnection.close", "adapter._commit_and_discard", "adapter._rollback_and_discard"} for r in failed_boundaries):
                endpoint_groups.append("terminal_envelope_error")
            endpoint_class = "|".join(endpoint_groups) or "no_cursor_connect_terminal_error_observed"
            row.update({"internal_coverage": "recorded_HTTP_wall_coverage_not_causal_path", "http_window_ns": [lo, hi], "coverage": coverage,
                        "coverage_marginal_ns": marginals(coverage), "outer_inner": outer_inner(sample["elapsed_ms"], lo, hi),
                        "terminal": terminal_flags(tx), "audit_transactions": tx,
                        "wake_envelopes": wakes.get(key, []), "pg_temporal_candidates": dict(pg[key]),
                        "scheduling_lag": {"observed_ticks": len(tick_lags), "max_ns": max(tick_lags) if tick_lags else None, "label": "finite_sampler_lateness_not_isolated_CPU"},
                        "other_request_hold_temporal_overlap_ns": foreign["mask_ns"].get("other_request_closed_holds", 0),
                        "other_request_hold_candidate_count": len(temporal_holds),
                        "closed_holds": phase["holds"], "failed_boundary_events": failed_boundaries,
                        "failed_cursor_spans": failed_sql, "endpoint_class": endpoint_class,
                        "SQL_rank": sorted(ranked, key=lambda r: (-r["known_union_ns"], r["digest"])),
                        "source_model_loop_visits": visits,
                        "unclassified_label": "missing_or_unwrapped_observation_not_CPU"})
            requests.append(row)
    cohorts, cells = {}, []
    for pop in ("ON", "OFF"):
        population = [r for r in requests if r["population"] == pop]
        cohorts[pop] = {"all": aggregate(population), "failed": aggregate([r for r in population if not r["sample"]["okay"]]), "successful": aggregate([r for r in population if r["sample"]["okay"]])}
        original = get(pop, "latency-summary.json")
        for profile in PROFILES:
            for operation in OPERATIONS:
                calculated = cell(samples[pop], profile, operation)
                old = next(r for r in original["cells"] if r["concurrency"] == profile and r["operation"] == operation)
                mapping = {"n": "samples", "errors": "failures", "limit_ms": "p95_limit_ms", "passed": "pass", "p50_ms": "p50_ms", "p95_ms": "p95_ms", "p99_ms": "p99_ms"}
                if any(calculated[k] != old[v] for k, v in mapping.items()):
                    raise ValueError("original 32-cell oracle mismatch")
                rows = [r for r in population if r["sample"]["profile"] == profile and r["sample"]["operation"] == operation]
                tail = [r for r in rows if calculated["p95_ms"] is not None and r["sample"]["elapsed_ms"] >= calculated["p95_ms"]]
                cells.append({"population": pop, "profile": profile, "operation": operation, **calculated,
                              "all": aggregate(rows), "failed": aggregate([r for r in rows if not r["sample"]["okay"]]), "successful": aggregate([r for r in rows if r["sample"]["okay"]]), "tail_ge_p95": aggregate(tail)})
    phase_cost, audit_cost = get("ON", "phase-recorder-cost.json"), get("ON", "audit-recorder-cost.json")
    if len(phase_cost) != len(phases) or {r["request_id"] for r in phase_cost} != set(phases):
        raise ValueError("phase cost key coverage")
    if any(r["transaction_number"] not in tx_ids for r in audit_cost):
        raise ValueError("audit cost transaction namespace mismatch")
    for row in phase_cost + audit_cost:
        nearest_rank([row["serialize_ms"], row["append_flush_ms"]])
    cost = {"R9": partial_cost(boundary["costs"]), "phase_keyed_without_interval": phase_cost,
            "audit_transaction_keyed_without_interval": audit_cost, "source_model": dict(complexity),
            "SQL_aggregate_association": [{"digest": d, "class": k, **n} for (d, k), n in sorted(sql_rank.items(), key=lambda p: (-p[1]["known_union_ns"], p[0]))],
            "anchors": {"phase_finalize": "r/phase_profiler.py:305-334 repeated phase/SQL scans", "phase_record": "r/phase_profiler.py:225-240 HTTP end before finalize/serialize/flush", "wake": "r9/pool_boundary_observer.py wake details pending scan + first-live waiter scan", "audit": "r/r2/audit_tail_observer.py:95-101 digest recomputed per cursor"},
            "limits": ["R9 measured begin/finish/tick costs omit preparation/mapping/stack work and have NO time/request/task tags; no positional allocation.", "Phase keyed costs occur after inner HTTP end; audit keyed costs lack absolute intervals. Never subtract costs from SLA.", "Source model loop visits are data-shape exposure, not measured CPU time; wake pending sizes were not saved."]}
    unique_wakes = [r for rows in wakes.values() for r in rows if r["mapping"] == "unique"]
    paired_wakes = [r for r in unique_wakes if r["consumer_span_id"] is not None]
    consumers = Counter(r["consumer_span_id"] for r in paired_wakes)
    errors_by_event = Counter(r["name"] for r in boundary["events"] if r["error_type"])
    summary = {"status": "OFFLINE_DIAGNOSIS_ONLY_PRODUCT_NOT_READY", "populations": {p: {"n": len(samples[p]), "errors": sum(not r["okay"] for r in samples[p]), "missing_downstream": 1600 - len(samples[p])} for p in samples},
               "cells": 32, "conservation_requests": len(phases), "PG_temporal_candidates": pg_total,
               "masks": CATEGORIES, "boundary_events": len(boundary["events"]), "costs": len(boundary["costs"]),
               "wake_accounting": {"unique_mappings": len(unique_wakes), "paired_associations": len(paired_wakes), "unpaired": len(unique_wakes) - len(paired_wakes), "distinct_consumer_attempts": len(consumers), "consumer_attempts_with_multiple_wakes": sum(n > 1 for n in consumers.values()), "unpaired_reasons": dict(sorted(Counter(r["censorship_reason"] for r in unique_wakes if r["consumer_span_id"] is None).items())), "paired_consumer_errors": dict(sorted(Counter(r["consumer_error_type"] for r in paired_wakes if r["consumer_error_type"]).items())), "label": "associations_not_distinct_delivered_records_or_reservations"},
               "typed_boundary_errors_all_requests": dict(sorted(errors_by_event.items())),
               "ALL147_failed_outcomes": {p: aggregate([r for r in requests if r["population"] == p and not r["sample"]["okay"]]) for p in samples},
               "limits": ["Recorded HTTP coverage is not causal critical path. Mask zero is unclassified, not CPU.", "OFF internal traces unobserved. ON/OFF are serial/confounded populations.", "Hold/record/driver/PID/local-phase namespaces have NO cross-source identity bridge.", "PG windows contain two non-atomic queries; overlap is candidate association, not continuous wait, advisory-object identity or server ownership.", "Queue ready is not record reservation; final phase label is callee observation, not logical TX ownership.", "ACK is client observed commit; missing/unknown terminal is not rollback. Delivery failure after ACK remains failure.", "Small own-request coverage does not exclude cross-holder congestion or earlier waits exhausting deadline.", "All root-cause and complete observer-overhead attribution remains UNRESOLVED."]}
    return requests, {"cells": cells, "whole": cohorts}, cost, summary


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = validate_output(args.root, args.output)
    source_before = Path(__file__).read_bytes()
    manifest, inputs = load_inputs(args.root)
    requests, cohorts, cost, summary = analyze(inputs)
    _, after = load_inputs(args.root)
    if inputs != after:
        raise ValueError("selected input bytes changed during replay")
    source = Path(__file__).read_bytes()
    if source != source_before:
        raise ValueError("analyzer changed during replay")
    provenance = {"manifest_sha256": MANIFEST_SHA, "selected": manifest["files"], "selected_before_after_equal": True,
                  "analyzer_sha256": hashlib.sha256(source).hexdigest(),
                  "prior_history_integrity": "Technical frozen summary35897d... independently records product/400/73/current8/7666/92; current input equality is a separate check"}
    artifacts = {"requests.jsonl": "".join(canonical(r) for r in requests),
                 "failed.jsonl": "".join(canonical(r) for r in requests if not r["sample"]["okay"]),
                 "cohorts.json": canonical(cohorts), "cost-source.json": canonical(cost),
                 "summary.json": canonical(summary), "provenance.json": canonical(provenance)}
    if sum(len(r.encode()) for r in artifacts.values()) > 64 * 1024**2:
        raise ValueError("output aggregate cap")
    output.mkdir()
    for name, value in artifacts.items():
        with (output / name).open("x", encoding="utf-8") as target:
            target.write(value)
    print(canonical({"files": {name: hashlib.sha256(value.encode()).hexdigest() for name, value in artifacts.items()}, "requests": len(requests)}), end="")


if __name__ == "__main__":
    main()
