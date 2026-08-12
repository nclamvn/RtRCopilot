#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

# TIP-033 reuses the exact TIP-032 truth oracle to compare latency without
# expanding the approved disclosure surface or moving the quality goalposts.
readonly bounded_cases="OPS-010,SYS-007,MTH-004,PRD-001,PRD-023"
if [[ "${TIP033_APPROVE_EXTERNAL:-0}" != "1" ]]; then
  echo "TIP-033 RECERTIFICATION BLOCKED · set TIP033_APPROVE_EXTERNAL=1 only after approving export of these five internal test questions/evidence to the configured endpoint" >&2
  echo "Cases: $bounded_cases" >&2
  exit 2
fi
if [[ "${E2E_CASE_IDS:-$bounded_cases}" != "$bounded_cases" ]]; then
  echo "TIP-033 RECERTIFICATION BLOCKED · case set is immutable: $bounded_cases" >&2
  exit 2
fi

export E2E_CASE_IDS="$bounded_cases"
export E2E_HTTP_REPORT="${E2E_HTTP_REPORT:-eval/real_world/tip033_latency_recertification.json}"
export E2E_CONCURRENCY="${E2E_CONCURRENCY:-1}"
export E2E_SKIP_BROWSER="${E2E_SKIP_BROWSER:-1}"

./scripts/run-enterprise-e2e.sh

actual_cases="$(jq -r '.metrics.total' "$E2E_HTTP_REPORT")"
false_grounded="$(jq -r '.metrics.false_grounded_count' "$E2E_HTTP_REPORT")"
citation_accuracy="$(jq -r '.metrics.citation_accuracy' "$E2E_HTTP_REPORT")"
p95_latency="$(jq -r '.metrics.p95_latency_ms' "$E2E_HTTP_REPORT")"
max_latency="$(jq -r '[.results[].latency_ms] | max' "$E2E_HTTP_REPORT")"
if [[ "$actual_cases" != "5" || "$false_grounded" != "0" \
    || "$citation_accuracy" != "1" ]]; then
  echo "TIP-033 RECERTIFICATION FAIL · cases=$actual_cases false_grounded=$false_grounded citation_accuracy=$citation_accuracy" >&2
  exit 1
fi
if ! awk -v value="$p95_latency" 'BEGIN { exit !(value <= 25000) }'; then
  echo "TIP-033 RECERTIFICATION FAIL · p95_ms=$p95_latency target_ms=25000" >&2
  exit 1
fi
if ! awk -v value="$max_latency" 'BEGIN { exit !(value < 45000) }'; then
  echo "TIP-033 RECERTIFICATION FAIL · max_ms=$max_latency ceiling_ms=45000" >&2
  exit 1
fi
echo "TIP-033 RECERTIFICATION PASS · exact_cases=5 · false_grounded=0 · citation_accuracy=1 · p95_ms=$p95_latency · report=$E2E_HTTP_REPORT"
