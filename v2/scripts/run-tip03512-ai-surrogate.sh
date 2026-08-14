#!/usr/bin/env bash
# Local-only AI-surrogate operator campaign. No external provider is called.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

release_evidence_dir="${RTR_RELEASE_EVIDENCE_DIR:-eval/runtime}"
technical_report="${TIP03512_TECHNICAL_REPORT:-${release_evidence_dir%/}/tip034_pilot_capture.json}"
ui_report="${TIP03512_UI_REPORT:-${release_evidence_dir%/}/tip035_12_ai_surrogate_ui.json}"
result_report="${TIP03512_RESULT:-${release_evidence_dir%/}/tip035_12_ai_surrogate_result.json}"
plan="eval/pilot/tip035_12_ai_surrogate_plan.json"
manifest="eval/pilot/tip034_campaign.json"
source_suite="eval/real_world/cases.json"
human_ledger="eval/pilot/tip034_observations.json"

./scripts/assert-release-evidence-path.sh "$technical_report" >/dev/null
./scripts/assert-release-evidence-path.sh "$ui_report" >/dev/null
./scripts/assert-release-evidence-path.sh "$result_report" >/dev/null
candidate_build="$(./scripts/build-identity.sh)"
if [[ ! "$candidate_build" =~ ^[0-9a-f]{12,64}$ ]]; then
  echo "TIP-035.12 BLOCKED · candidate must be clean and committed: $candidate_build" >&2
  exit 2
fi
if [[ ! -f "$technical_report" ]]; then
  echo "TIP-035.12 BLOCKED · build-bound TIP-034 technical capture is missing" >&2
  exit 2
fi
if ! jq -e --arg build "$candidate_build" '
    .runtime_build_identity == $build
    and .metrics.total == 27
    and .metrics.passed == 27
    and .metrics.false_grounded_count == 0
  ' "$technical_report" >/dev/null 2>&1; then
  echo "TIP-035.12 BLOCKED · technical capture does not pass on candidate $candidate_build" >&2
  exit 2
fi

AI_SURROGATE_BUILD_IDENTITY="$candidate_build" \
AI_SURROGATE_UI_OUTPUT="$ui_report" \
  pnpm test:browser:ai-surrogate

host_uid="$(id -u)"
host_gid="$(id -g)"
docker compose run --rm --no-deps -T --user "$host_uid:$host_gid" \
  -v "$project_root/eval:/app/eval" api \
  python -m rtr_copilot.commands.evaluate_ai_surrogate \
  --plan "/app/$plan" \
  --manifest "/app/$manifest" \
  --source-suite "/app/$source_suite" \
  --technical-report "/app/$technical_report" \
  --ui-result "/app/$ui_report" \
  --human-ledger "/app/$human_ledger" \
  --output "/app/$result_report"

echo "TIP-035.12 AI-SURROGATE GO · not a human attestation · report=$result_report"
