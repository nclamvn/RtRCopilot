"""Bounded independent R21 reconstruction. Stdlib; no experiment/product imports."""

import ast
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
BASE = "v2/experiments/action_executor"
RAW = BASE + "/raw/tip054-4b-full-20261007-r5qa1/r19/r21_http_e1"
PROFILES = (1, 10, 25, 50)
OPS = ("admission", "submit", "status", "cancel")
STATUSES = dict(zip(OPS, (201, 202, 200, 202)))
STATES = dict(zip(OPS, ("contract_ready", "queued", "queued", "cancelled")))
INPUT_CAP = 33554432
OUTPUT_CAP = 131072


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    need(len(items) == len(dict(items)), "duplicate JSON keys")
    return dict(items)


def loads(data):
    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def exact(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def safe(path):
    p = Path(path)
    need(type(path) is str and path == p.as_posix() and p.parts and not p.is_absolute()
         and ".." not in p.parts, "unsafe/noncanonical input path")
    target = ROOT / p
    need(target.resolve().is_relative_to(ROOT)
         and not any((ROOT / Path(*p.parts[:i])).is_symlink() for i in range(1, len(p.parts) + 1)),
         "input escape or symlink parent")
    return target


def verify(binding):
    pinned = dict(binding["direct"])
    for path, expected in binding["links"].items():
        data = safe(path).read_bytes()
        need(sha(data) == expected, "link drift: " + path)
        pinned[path] = expected
        inventory = loads(data)["files"] if path.endswith(".json") else dict(
            (line.split("  ", 1)[1], line.split("  ", 1)[0]) for line in data.decode().splitlines())
        for name, digest in inventory.items():
            need(name not in pinned or pinned[name] == digest, "conflicting inventory pin")
            pinned[name] = digest
    size = 0
    for path, expected in pinned.items():
        target = safe(path)
        size += target.stat().st_size
        need(size <= INPUT_CAP, "complete input cap")
        need(sha(target.read_bytes()) == expected, "input drift: " + path)
    prior = loads(safe(BASE + "/r18/source-binding-e3.json").read_bytes())
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    for scope, paths in prior["scopes"].items():
        directories = ("src", "migrations") if scope == "product" else ("tests",)
        actual = []
        for directory in directories:
            for path in (ROOT / "v2/apps/backend" / directory).rglob("*"):
                rel = path.relative_to(ROOT)
                if ignored.intersection(rel.parts) or path.suffix == ".pyc":
                    continue
                need(not path.is_symlink(), "source symlink")
                if path.is_file():
                    actual.append(rel.as_posix())
        extras = [p for p in paths if not any("/" + d + "/" in p for d in directories)]
        need(sorted(actual + extras) == paths, "complete source set drift")
        need(sha("".join(pinned[p] + "  " + p + "\n" for p in paths).encode()) == prior["digests"][scope], "source recipe drift")
    return {"unique_pins": len(pinned), "bytes": size, "digests": prior["digests"]}


def quantile(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1] if values else None


def distribution(values):
    return {"n": len(values), "min": min(values) if values else None,
            **{label: quantile(values, q) for label, q in (("p50", .5), ("p95", .95), ("p99", .99))},
            "max": max(values) if values else None}


def reconstruct(rows):
    need(type(rows) is list and len(rows) <= 1600, "bounded rows")
    seen, order, position = {}, {}, -1
    fields = {"profile", "case", "operation", "elapsed_ms", "okay", "http_status", "state", "error_code"}
    for row in rows:
        need(type(row) is dict and set(row) == fields, "exact R21 HTTP schema")
        p, c, op = row["profile"], row["case"], row["operation"]
        need(type(p) is int and p in PROFILES and type(c) is int and 0 <= c < 100 and op in OPS, "typed identity")
        key, rank = (p, c, op), OPS.index(op)
        need(key not in seen and PROFILES.index(p) >= position and rank > order.get((p, c), -1), "duplicate/order")
        position, order[(p, c)] = PROFILES.index(p), rank
        need(type(row["elapsed_ms"]) in (int, float) and math.isfinite(row["elapsed_ms"]) and row["elapsed_ms"] >= 0, "finite client timer")
        need(type(row["okay"]) is bool and type(row["http_status"]) is int, "typed outcome")
        need((row["okay"] and row["http_status"] == STATUSES[op] and row["state"] == STATES[op] and row["error_code"] is None)
             or (row["okay"] is False and row["http_status"] == 503 and row["state"] is None and row["error_code"] == "action_operation_timeout"), "unknown outcome")
        for prerequisite in OPS[:min(rank, 2)]:
            need(seen.get((p, c, prerequisite), {}).get("okay") is True, "missing successful predecessor")
        if rank == 3:
            need((p, c, "status") in seen, "cancel without status")
        seen[key] = row
    expected = {(p, c, op) for p in PROFILES for c in range(100) for op in OPS}
    missing = expected - set(seen)
    need(all((p, c, "submit") in seen and not seen[(p, c, "submit")]["okay"] and op in {"status", "cancel"} for p, c, op in missing), "unknown missing descendants")
    cells = []
    for p in PROFILES:
        for op in OPS:
            selected = [r for (profile, _, operation), r in seen.items() if (profile, operation) == (p, op)]
            values = [r["elapsed_ms"] for r in selected]
            limit = 500 if op == "admission" else 1000
            cell = {"concurrency": p, "operation": op, "samples": len(values), "failures": sum(not r["okay"] for r in selected),
                    **{label + "_ms": quantile(values, q) for label, q in (("p50", .5), ("p95", .95), ("p99", .99))}, "p95_limit_ms": limit}
            cell["pass"] = len(values) == 100 and cell["failures"] == 0 and cell["p95_ms"] <= limit
            cells.append(cell)
    return seen, sorted(missing), cells


def request_logs(text):
    logs = {}
    other = Counter()
    pattern = r"tip054-latency-(1|10|25|50)-(0|[1-9][0-9]?)-(admission|submit|status|cancel)"
    uuid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    for line in text.splitlines():
        if not line.startswith("{"):
            other["non_json_lines"] += 1
            continue
        event = loads(line)
        if event.get("event") != "request":
            need("event" not in event and event.get("action") == "policy.manage_policies", "unknown JSON log event")
            other["seed_audit_events"] += 1
            continue
        need(set(event) == {"event", "request_id", "method", "path", "status", "duration_ms"}, "request log schema")
        match = re.fullmatch(pattern, event["request_id"])
        need(match is not None, "ambiguous request ID")
        p, c, op = match.groups()
        key = (int(p), int(c), op)
        need(key not in logs, "duplicate request ID")
        path = {"admission": r"/api/v1/actions/plans", "submit": r"/api/v1/actions/plans/" + uuid + "/execute",
                "status": r"/api/v1/actions/runs/" + uuid, "cancel": r"/api/v1/actions/runs/" + uuid + "/cancel"}[op]
        need(re.fullmatch(path, event["path"]) and event["method"] == ("GET" if op == "status" else "POST"), "request method/path")
        need(type(event["status"]) is int and type(event["duration_ms"]) in (int, float) and math.isfinite(event["duration_ms"]) and event["duration_ms"] >= 0, "finite typed server observation")
        logs[key] = event
    return logs, dict(other)


def analyze(binding):
    preservation = verify(binding)
    def read(name):
        return safe(RAW + "/" + name).read_bytes()
    journal = read("run/samples.jsonl")
    need(journal.endswith(b"\n"), "partial journal")
    rows = [loads(line) for line in journal.splitlines()]
    need(exact(rows, loads(read("run/samples.json"))), "JSON/JSONL disagreement")
    seen, missing, cells = reconstruct(rows)
    logs, log_counts = request_logs(read("load.stderr.txt").decode())
    need(set(logs) == set(seen), "log/row identity conservation")
    need(all(logs[key]["status"] == row["http_status"] for key, row in seen.items()), "log status disagreement")
    literals = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(safe(BASE + "/r21/qualification.py").read_text()).body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"PROFILE", "LIMITS", "CONTROLS"}}
    need(exact(loads(read("run/latency-summary.json")), {"status": "FAIL", "cells": cells, "profile": literals["PROFILE"], "limits": literals["LIMITS"]}), "full original summary")
    need(exact(loads(read("run/r-controls.json")), literals["CONTROLS"]), "OFF controls")
    process, owner = loads(read("load.process.json")), loads(read("load.owner.json"))
    need(exact(process["owner"], owner) and process["group_drained"] is True and process["reason"] == "completed" and type(process["exit_code"]) is int and type(process["original_exit_code"]) is int and process["exit_code"] == process["original_exit_code"] == 1, "original completed FAIL ownership")
    cohorts = []
    for cell in cells:
        keys = [key for key in seen if (key[0], key[2]) == (cell["concurrency"], cell["operation"])]
        failed = sorted(key[1] for key in keys if not seen[key]["okay"])
        tails = sorted(keys, key=lambda k: (-seen[k]["elapsed_ms"], k[1]))[:5]
        gaps = [seen[k]["elapsed_ms"] - logs[k]["duration_ms"] for k in keys]
        cohorts.append({"profile": cell["concurrency"], "operation": cell["operation"], "failed_cases": failed,
                        "missing_cases": [c for p, c, op in missing if (p, op) == (cell["concurrency"], cell["operation"])],
                        "failure_case_bins_20": [sum(i <= c < i + 20 for c in failed) for i in range(0, 100, 20)],
                        "client_gt_900_ms": sum(seen[k]["elapsed_ms"] > 900 for k in keys),
                        "client_gt_sla_ms": sum(seen[k]["elapsed_ms"] > cell["p95_limit_ms"] for k in keys),
                        "timeouts_at_or_below_900_ms": sum(not seen[k]["okay"] and seen[k]["elapsed_ms"] <= 900 for k in keys),
                        "server_ms": distribution([logs[k]["duration_ms"] for k in keys]),
                        "client_minus_server_boundary_ms_not_phase": distribution(gaps),
                        "negative_boundary_pairs": sum(v < 0 for v in gaps),
                        "worst5_observed": [{"case": k[1], "client_ms": seen[k]["elapsed_ms"], "server_ms": logs[k]["duration_ms"], "okay": seen[k]["okay"]} for k in tails]})
    need((len(seen), sum(not r["okay"] for r in rows), len(missing), sum(c["pass"] for c in cells)) == (1440, 87, 160, 10), "retained R21 conservation")
    need(verify(binding) == preservation, "after input preservation")
    return {"schema": "R22-offline-v1", "input_binding_sha256": sha((HERE / "input-binding.json").read_bytes()),
            "preservation": preservation, "requested": 1600, "observed": 1440, "successful": 1353, "timeouts": 87,
            "missing_descendants": 160, "matched_log_ids": len(logs), "log_counts": log_counts,
            "qualification": "FAIL_UNCHANGED", "passing_cells": 10, "cells": cells, "cohorts": cohorts,
            "limitations": "No phase timestamps; rounded middleware response-header duration differs from ASGI client response completion. No subtraction-adjusted SLA or causal attribution. C50 status/cancel describe 20 observed samples only."}


if __name__ == "__main__":
    result = analyze(loads((HERE / "input-binding.json").read_bytes()))
    output = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    need(len(output.encode()) <= OUTPUT_CAP, "compact output cap")
    print(output)
