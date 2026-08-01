#!/usr/bin/env bash
# TIP-012 Task 5 (Builder 5) — SLO evaluation (AC-13 evidence, not prose).
# Parses k6 --summary-export JSON in load/results/ and checks each metric against
# the targets declared in docs/slo.md. Prints a pass/fail table and exits
# non-zero on ANY breach. Pure python3 stdlib (no new dependency).
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${RESULTS_DIR:-$project_root/load/results}" python3 - <<'PY'
import json
import os
import sys

results = os.environ["RESULTS_DIR"]

# (label, summary-file, metric, stat, op, target, unit) — mirrors docs/slo.md §1.
CHECKS = [
    ("S1a point read p95 (files/gaps)", "steady_read", "point_read_duration",     "p(95)", "<=", 300.0,   "ms"),
    ("S1b dashboard aggregate p95","steady_read",   "dashboard_read_duration", "p(95)", "<=", 500.0,   "ms"),
    ("S1 read error rate",         "steady_read",   "errors",                 "value", "<",  0.005,   "frac"),
    ("S5 availability",            "steady_read",   "avail_ok",               "value", ">=", 0.99,    "frac"),
    ("S2 ask p95 (fake provider)", "ask_burst",     "ask_duration",           "p(95)", "<=", 1500.0,  "ms"),
    ("S2 ask error rate",          "ask_burst",     "errors",                 "value", "<",  0.005,   "frac"),
    ("S3 upload-accept p95 (1MB)", "upload_stream", "upload_duration",        "p(95)", "<=", 2000.0,  "ms"),
    ("S3 upload error rate",       "upload_stream", "errors",                 "value", "<",  0.005,   "frac"),
    ("S6 spike-recovery read p95", "spike_recover", "read_duration_recovery", "p(95)", "<=", 300.0,   "ms"),
    ("S6 spike error rate",        "spike_recover", "errors",                 "value", "<",  0.005,   "frac"),
]

OPS = {
    "<=": lambda a, b: a <= b,
    "<":  lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    ">":  lambda a, b: a > b,
}

_cache = {}
def load(name):
    if name not in _cache:
        path = os.path.join(results, f"{name}.summary.json")
        try:
            with open(path) as fh:
                _cache[name] = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            _cache[name] = {"__error__": str(exc)}
    return _cache[name]

def measured(name, metric, stat):
    data = load(name)
    if "__error__" in data:
        return None, f"missing summary ({data['__error__'].split(':')[0]})"
    node = data.get("metrics", {}).get(metric)
    if node is None:
        return None, f"metric '{metric}' absent (no samples?)"
    val = node.get(stat)
    if val is None:
        return None, f"stat '{stat}' absent"
    return float(val), None

def fmt(val, unit):
    if val is None:
        return "n/a"
    if unit == "ms":
        return f"{val:.1f} ms"
    if unit == "frac":
        return f"{val*100:.3f} %"
    return f"{val:.3f}"

rows = []
all_pass = True
for label, name, metric, stat, op, target, unit in CHECKS:
    val, err = measured(name, metric, stat)
    if val is None:
        result, ok = f"FAIL ({err})", False
    else:
        ok = OPS[op](val, target)
        result = "PASS" if ok else "FAIL"
    all_pass = all_pass and ok
    tgt = f"{op} {fmt(target, unit)}"
    rows.append((label, fmt(val, unit), tgt, result))

w0 = max(len(r[0]) for r in rows + [("Objective", "", "", "")])
w1 = max(len(r[1]) for r in rows + [("", "Measured", "", "")])
w2 = max(len(r[2]) for r in rows + [("", "", "Target", "")])
line = "-" * (w0 + w1 + w2 + 12 + 8)
print()
print("SLO EVALUATION — k6 measured vs docs/slo.md targets")
print(line)
print(f"{'Objective':<{w0}}  {'Measured':>{w1}}  {'Target':>{w2}}  Result")
print(line)
for label, mval, tgt, result in rows:
    print(f"{label:<{w0}}  {mval:>{w1}}  {tgt:>{w2}}  {result}")
print(line)
print("VERDICT:", "PASS — all SLOs met" if all_pass else "FAIL — SLO breach")
print()
sys.exit(0 if all_pass else 1)
PY
