"""Independent bounded offline R8 counters; no product/helper imports or runtime.

Known acknowledgements and event absence are observations, never server outcome
or causal claims. Creates a new output directory; existing outputs are refused.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("existing output refused")
    raw = args.repo / "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1"
    selected = {}

    def read(path, lines=False):
        data = path.read_bytes()
        assert len(data) <= 64 * 1024 * 1024
        selected[str(path.relative_to(args.repo))] = hashlib.sha256(data).hexdigest()
        values = [json.loads(line) for line in data.splitlines()] if lines else json.loads(data)
        if isinstance(values, list):
            assert len(values) <= 20000
        return values

    populations = []
    for epoch, mode in (("baseline_624", "off"), ("baseline_624", "on"),
                        ("candidate_56f", "on"), ("candidate_56f", "off")):
        gate = "r7_" + epoch + "_" + mode + "_r1"
        samples = read(raw / gate / "samples.json")
        summary = read(raw / gate / "latency-summary.json")
        cells = []
        for old in summary["cells"]:
            rows = [r for r in samples if (r["profile"], r["operation"]) ==
                    (old["concurrency"], old["operation"])]
            values = sorted(r["elapsed_ms"] for r in rows)
            rebuilt = {
                "concurrency": old["concurrency"], "operation": old["operation"],
                "samples": len(rows), "failures": sum(not r["okay"] for r in rows),
                "p50_ms": values[math.ceil(len(values) * .5) - 1] if values else None,
                "p95_ms": values[math.ceil(len(values) * .95) - 1] if values else None,
                "p99_ms": values[math.ceil(len(values) * .99) - 1] if values else None,
                "p95_limit_ms": 500 if old["operation"] == "admission" else 1000,
            }
            rebuilt["pass"] = (len(rows) == 100 and rebuilt["failures"] == 0 and
                               rebuilt["p95_ms"] <= rebuilt["p95_limit_ms"])
            assert rebuilt == old
            cells.append(rebuilt)
        populations.append({
            "gate": gate, "samples": len(samples),
            "failed_http": sum(not r["okay"] for r in samples),
            "pass_cells": sum(c["pass"] for c in cells),
            "fail_cells": sum(not c["pass"] for c in cells),
            "all16_quantiles_flags_exact": True, "cells": cells,
        })

    gate = raw / "r7_candidate_56f_on_r1"
    samples = read(gate / "samples.json")
    phases = read(gate / "phase-requests.jsonl", True)
    audits = read(gate / "audit-transactions.jsonl", True)
    by_id = {r["request_id"]: r for r in phases}
    assert len(by_id) == len(phases) == len(samples)
    audit_by_id = defaultdict(list)
    for a in audits:
        audit_by_id[a["request_id"]].append(a)
    failed = []
    for sample in samples:
        if sample["okay"]:
            continue
        rid = "tip054-latency-{profile}-{case}-{operation}".format(**sample)
        r = by_id[rid]
        assert r["http_status"] == sample["http_status"]
        view = [p for p in r["phases"] if p["name"] == "ExecutionService._view"]
        view_ids = {p["phase_id"] for p in view}
        view_sql = [s for s in r["sql"] if view_ids.intersection(s["phase_ids"])]
        known = [a for a in audit_by_id[rid] if a["terminal_kind"] == "commit_ack"]
        audited = [a for a in known if a["first_audit_grant_ns"] is not None]
        connect_errors = [p for p in r["pool"] if p["kind"] == "connect" and p["error_type"]]
        sql_errors = [s for s in r["sql"] if s["error_type"]]
        failed.append({
            "request_id": rid, "operation": sample["operation"],
            "http_status": sample["http_status"], "error_code": sample.get("error_code"),
            "failed_connect": len(connect_errors), "failed_sql": len(sql_errors),
            "classification": "connect" if connect_errors else "sql" if sql_errors else
                              "neither_error_event_observed",
            "closed_holds": len(r["holds"]),
            "sql_started": len(r["sql"]),
            "sql_without_end": sum(s["end_ns"] is None for s in r["sql"]),
            "any_commit_ack": len(known), "audited_commit_ack": len(audited),
            "terminal_kinds": dict(Counter(a["terminal_kind"] for a in audit_by_id[rid])),
            "views": [{"start_ns": p["start_ns"], "end_ns": p["end_ns"],
                       "error_type": p["error_type"]} for p in view],
            "view_sql_started": len(view_sql),
            "view_sql_error_events": sum(bool(s["error_type"]) for s in view_sql),
            "audited_ack_before_view": bool(audited and view and
                max(a["terminal_ns"] for a in audited) < min(p["start_ns"] for p in view)),
        })
    assert len(failed) == 19
    grouped = {}
    for operation in ("submit", "cancel", "status"):
        rows = [r for r in failed if r["operation"] == operation]
        grouped[operation] = {
            "failed_http": len(rows),
            "classification": dict(Counter(r["classification"] for r in rows)),
            "any_commit_ack_requests": sum(bool(r["any_commit_ack"]) for r in rows),
            "audited_commit_ack_requests": sum(bool(r["audited_commit_ack"]) for r in rows),
        }
    selected[str(Path(__file__).resolve().relative_to(args.repo))] = hashlib.sha256(
        Path(__file__).read_bytes()).hexdigest()
    assert all(hashlib.sha256((args.repo / path).read_bytes()).hexdigest() == digest
               for path, digest in selected.items())
    result = {
        "status": "PASS", "selected_inputs": selected, "inputs_unchanged": True,
        "populations": populations, "failed_candidate_on": failed,
        "failed_candidate_on_grouped": grouped,
        "audit_terminal_kinds": dict(Counter(a["terminal_kind"] for a in audits)),
        "limits": "Offline counterchecks only; no server rollback/cleanup/pure wait/causal/SLA inference.",
    }
    args.output.mkdir(parents=True)
    (args.output / "counterchecks.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "populations": [
        {k: v for k, v in p.items() if k != "cells"} for p in populations],
        "failed_grouped": grouped, "selected_inputs": len(selected)}, indent=2))


if __name__ == "__main__":
    main()
