#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

report="${TIP033_REPORT:-eval/real_world/tip033_latency_recertification.json}"
expected_build="${TIP033_EXPECTED_BUILD:-$(./scripts/build-identity.sh)}"

if [[ ! -f "$report" ]]; then
  echo "TIP-033 REPORT FAIL · report not found: $report" >&2
  exit 2
fi

if ! validation="$(python3 - "$report" "$expected_build" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
expected_build = sys.argv[2]
try:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    metrics = payload["metrics"]
    latencies = [float(row["latency_ms"]) for row in payload["results"]]
    p95_latency = float(metrics["p95_latency_ms"])
    accepted = (
        payload["runtime_build_identity"] == expected_build
        and payload["selected_case_ids"]
        == ["OPS-010", "SYS-007", "MTH-004", "PRD-001", "PRD-023"]
        and metrics["total"] == 5
        and metrics["passed"] == 5
        and metrics["false_grounded_count"] == 0
        and float(metrics["citation_accuracy"]) == 1.0
        and p95_latency <= 25_000
        and bool(latencies)
        and max(latencies) < 45_000
    )
except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
    accepted = False
if not accepted:
    raise SystemExit(1)
print(f"{p95_latency}\t{max(latencies)}")
PY
)"; then
  echo "TIP-033 REPORT FAIL · build, immutable case set, quality or latency gate failed" >&2
  exit 1
fi

IFS=$'\t' read -r p95_latency max_latency <<< "$validation"
echo "TIP-033 RECERTIFICATION PASS · build=$expected_build · exact_cases=5 · false_grounded=0 · citation_accuracy=1 · p95_ms=$p95_latency · max_ms=$max_latency · report=$report"
