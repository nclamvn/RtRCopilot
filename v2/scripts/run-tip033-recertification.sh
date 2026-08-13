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
release_evidence_dir="${RTR_RELEASE_EVIDENCE_DIR:-eval/runtime}"
export E2E_HTTP_REPORT="${E2E_HTTP_REPORT:-${release_evidence_dir%/}/tip033_latency_recertification.json}"
export E2E_CONCURRENCY="${E2E_CONCURRENCY:-1}"
export E2E_SKIP_BROWSER="${E2E_SKIP_BROWSER:-1}"
export E2E_SKIP_BUILD="${E2E_SKIP_BUILD:-1}"
./scripts/assert-release-evidence-path.sh "$E2E_HTTP_REPORT" >/dev/null
candidate_build="$(./scripts/build-identity.sh)"
if [[ ! "$candidate_build" =~ ^[0-9a-f]{12,64}$ ]]; then
  echo "TIP-033 RECERTIFICATION BLOCKED · release candidate must be clean and committed: $candidate_build" >&2
  exit 2
fi
export E2E_BUILD_IDENTITY="$candidate_build"

./scripts/run-enterprise-e2e.sh
TIP033_REPORT="$E2E_HTTP_REPORT" TIP033_EXPECTED_BUILD="$candidate_build" \
  ./scripts/verify-tip033-report.sh
