#!/usr/bin/env bash
# TIP-035.18 content-free production configuration gate.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

env_file="${PRODUCTION_ENV_FILE:-.env.production}"
expected_build="${PRODUCTION_EXPECTED_BUILD:-$(./scripts/build-identity.sh)}"
report="${PRODUCTION_CONFIGURATION_REPORT:-eval/runtime/tip035_18_production_configuration.json}"
report="$(./scripts/assert-release-evidence-path.sh "$report")"

mkdir -p "$(dirname "$report")"
validator_status=0
python3 scripts/validate_production_env.py \
  --env-file "$env_file" \
  --expected-build "$expected_build" \
  --output "$report" >/dev/null || validator_status=$?

compose_status="blocked"
application_status="blocked"
additional_errors='[]'
if [[ "$validator_status" == "0" ]]; then
  if docker compose --env-file "$env_file" config --quiet >/dev/null 2>&1; then
    compose_status="pass"
  else
    additional_errors='["compose:materialization_failed"]'
  fi

  if [[ "$compose_status" == "pass" ]]; then
    if docker compose --env-file "$env_file" run --rm --no-deps -T api \
      python -c 'from rtr_copilot.config import get_settings; s=get_settings(); assert s.app_env == "production"' \
      >/dev/null 2>&1; then
      application_status="pass"
    else
      additional_errors='["application_settings:rejected"]'
    fi
  fi
fi

tmp_report="$(mktemp)"
trap 'rm -f "$tmp_report"' EXIT
jq \
  --arg compose_status "$compose_status" \
  --arg application_status "$application_status" \
  --argjson additional_errors "$additional_errors" '
    .checks.compose_materialization = ($compose_status == "pass")
    | .checks.application_settings = ($application_status == "pass")
    | .errors = ((.errors + $additional_errors) | unique | sort)
    | .status = (if (.errors | length) == 0 then "pass" else "blocked" end)
  ' "$report" > "$tmp_report"
mv "$tmp_report" "$report"
trap - EXIT

status="$(jq -r '.status' "$report")"
error_count="$(jq '.errors | length' "$report")"
echo "TIP-035.18 PRODUCTION CONFIG · status=$status · errors=$error_count · build=$expected_build · report=$report"
[[ "$status" == "pass" ]]
