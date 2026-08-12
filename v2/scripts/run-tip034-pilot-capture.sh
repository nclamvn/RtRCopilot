#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

# The scope is immutable.  A future operator approval authorizes only these
# questions and the evidence the configured answer runtime needs for them.
readonly campaign_cases="PRD-005,PRD-013,PRD-021,PRD-023,COM-002,COM-006,COM-008,COM-010,OPS-001,OPS-005,OPS-008,OPS-010,SYS-003,SYS-004,SYS-007,MTH-001,MTH-004,MTH-006,SAFE-003,SAFE-007,SAFE-008,CHAT-001-T1,CHAT-001-T2,CHAT-003-T1,CHAT-003-T2,CHAT-004-T1,CHAT-004-T2"
if [[ "${TIP034_APPROVE_EXTERNAL:-0}" != "1" ]]; then
  echo "TIP-034 PILOT CAPTURE BLOCKED · approve export of the immutable 27-case campaign to the configured endpoint first" >&2
  echo "Cases: $campaign_cases" >&2
  exit 2
fi
if [[ "${E2E_CASE_IDS:-$campaign_cases}" != "$campaign_cases" ]]; then
  echo "TIP-034 PILOT CAPTURE BLOCKED · case set is immutable" >&2
  exit 2
fi

export E2E_CASE_IDS="$campaign_cases"
export E2E_HTTP_REPORT="${E2E_HTTP_REPORT:-eval/real_world/tip034_pilot_capture.json}"
export E2E_CONCURRENCY="${E2E_CONCURRENCY:-1}"
export E2E_SKIP_BROWSER="${E2E_SKIP_BROWSER:-1}"

./scripts/run-enterprise-e2e.sh

actual_cases="$(jq -r '.metrics.total' "$E2E_HTTP_REPORT")"
if [[ "$actual_cases" != "27" ]]; then
  echo "TIP-034 PILOT CAPTURE FAIL · expected 27 results, got $actual_cases" >&2
  exit 1
fi
echo "TIP-034 PILOT CAPTURE COMPLETE · observations still require human usefulness, authorization and cost attestations · report=$E2E_HTTP_REPORT"
