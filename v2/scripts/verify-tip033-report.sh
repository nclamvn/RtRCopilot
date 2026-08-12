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

if ! jq -e --arg build "$expected_build" '
    .runtime_build_identity == $build
    and .selected_case_ids == ["OPS-010", "SYS-007", "MTH-004", "PRD-001", "PRD-023"]
    and .metrics.total == 5
    and .metrics.passed == 5
    and .metrics.false_grounded_count == 0
    and .metrics.citation_accuracy == 1
    and .metrics.p95_latency_ms <= 25000
    and ([.results[].latency_ms] | max) < 45000
  ' "$report" >/dev/null; then
  echo "TIP-033 REPORT FAIL · build, immutable case set, quality or latency gate failed" >&2
  exit 1
fi

p95_latency="$(jq -r '.metrics.p95_latency_ms' "$report")"
max_latency="$(jq -r '[.results[].latency_ms] | max' "$report")"
echo "TIP-033 RECERTIFICATION PASS · build=$expected_build · exact_cases=5 · false_grounded=0 · citation_accuracy=1 · p95_ms=$p95_latency · max_ms=$max_latency · report=$report"
