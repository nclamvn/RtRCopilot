#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

# These five cases cover the three historical semantic/provider failures plus
# the two most visible usefulness contracts (entity dossier and full catalog).
readonly bounded_cases="OPS-010,SYS-007,MTH-004,PRD-001,PRD-023"
if [[ "${TIP032_APPROVE_EXTERNAL:-0}" != "1" ]]; then
  echo "TIP-032 RECERTIFICATION BLOCKED · set TIP032_APPROVE_EXTERNAL=1 only after approving export of these five internal test questions/evidence to the configured endpoint" >&2
  echo "Cases: $bounded_cases" >&2
  exit 2
fi
if [[ "${E2E_CASE_IDS:-$bounded_cases}" != "$bounded_cases" ]]; then
  echo "TIP-032 RECERTIFICATION BLOCKED · case set is immutable: $bounded_cases" >&2
  exit 2
fi

export E2E_CASE_IDS="$bounded_cases"
export E2E_HTTP_REPORT="${E2E_HTTP_REPORT:-eval/real_world/tip032_bounded_recertification.json}"
export E2E_CONCURRENCY="${E2E_CONCURRENCY:-1}"
export E2E_SKIP_BROWSER="${E2E_SKIP_BROWSER:-1}"

./scripts/run-enterprise-e2e.sh

actual_cases="$(jq -r '.metrics.total' "$E2E_HTTP_REPORT")"
false_grounded="$(jq -r '.metrics.false_grounded_count' "$E2E_HTTP_REPORT")"
if [[ "$actual_cases" != "5" || "$false_grounded" != "0" ]]; then
  echo "TIP-032 RECERTIFICATION FAIL · cases=$actual_cases false_grounded=$false_grounded" >&2
  exit 1
fi
echo "TIP-032 RECERTIFICATION PASS · exact_cases=5 · false_grounded=0 · report=$E2E_HTTP_REPORT"
