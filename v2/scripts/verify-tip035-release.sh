#!/usr/bin/env bash
# TIP-035 release preflight. This command is intentionally read-only apart
# from its content-free JSON report. It never prints environment values,
# credentials, questions, answers or evidence.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

runtime_env="${TIP035_RUNTIME_ENV_FILE:-.env.demo}"
pilot_env="${TIP035_PILOT_ENV_FILE:-.env.pilot}"
production_env="${TIP035_PRODUCTION_ENV_FILE:-.env.production}"
release_evidence_dir="${RTR_RELEASE_EVIDENCE_DIR:-eval/runtime}"
report="${TIP035_REPORT:-/tmp/tip035-release-preflight.json}"
gates="$(mktemp)"
trap 'rm -f "$gates"' EXIT

record() {
  local gate="$1"
  local status="$2"
  local detail="$3"
  jq -cn --arg gate "$gate" --arg status "$status" --arg detail "$detail" \
    '{gate:$gate,status:$status,detail:$detail}' >> "$gates"
}

candidate="$(./scripts/build-identity.sh)"
head_sha="$(git rev-parse --short=12 HEAD)"
if [[ "$candidate" == "$head_sha" ]]; then
  record candidate_build pass "clean committed build"
else
  record candidate_build blocked "candidate is dirty or does not match HEAD"
fi

if ./scripts/migration-gate.sh >/dev/null 2>&1; then
  record migration_graph pass "single migration head matches application pin"
else
  record migration_graph blocked "migration graph or schema pin failed"
fi

if [[ ! -f "$runtime_env" ]]; then
  record runtime_exact blocked "runtime environment file is missing"
elif ANSWER_ENV_FILE="$runtime_env" ./scripts/verify-answer-runtime.sh >/dev/null 2>&1; then
  record runtime_exact pass "running answer runtime matches candidate configuration and build"
else
  record runtime_exact blocked "runtime verifier failed or reports a different build"
fi

if [[ ! -f "$pilot_env" ]]; then
  record isolated_pilot_database blocked "isolated pilot environment has not been created"
elif PILOT_ENV_FILE="$pilot_env" ./scripts/verify-pilot-database.sh >/dev/null 2>&1; then
  record isolated_pilot_database pass "canonical-only isolated pilot database verified"
else
  record isolated_pilot_database blocked "isolated pilot database verifier failed"
fi

tip033_report="${TIP035_TIP033_REPORT:-${release_evidence_dir%/}/tip033_latency_recertification.json}"
if [[ -f "$tip033_report" ]] && jq -e --arg build "$candidate" '
    .runtime_build_identity == $build
    and .metrics.total == 5
    and .metrics.false_grounded_count == 0
    and .metrics.citation_accuracy == 1
    and .metrics.p95_latency_ms <= 25000
    and ([.results[].latency_ms] | max) < 45000
  ' "$tip033_report" >/dev/null 2>&1; then
  record tip033_latency pass "fresh five-case latency recertification passed"
else
  record tip033_latency blocked "fresh passing five-case report is absent for this build"
fi

tip034_result="${TIP035_TIP034_RESULT:-${release_evidence_dir%/}/tip034_campaign_result.json}"
tip03512_result="${TIP035_AI_SURROGATE_RESULT:-${release_evidence_dir%/}/tip035_12_ai_surrogate_result.json}"
if [[ -f "$tip034_result" ]] && jq -e --arg build "$candidate" '
    .verdict == "go"
    and .sample_size == 27
    and (.runtime_build_identities == [$build])
  ' "$tip034_result" >/dev/null 2>&1; then
  record tip034_usefulness pass "27-case usefulness campaign passed on this build"
elif [[ "${TIP035_AI_SURROGATE_APPROVED:-0}" == "1" ]] \
  && [[ -f "$tip03512_result" ]] \
  && jq -e --arg build "$candidate" '
    .verdict == "go"
    and .candidate_build == $build
    and .tester_kind == "ai_surrogate_not_human_attestation"
    and .human_usefulness_measured == false
    and .human_ledger_modified == false
    and .external_calls_executed == 0
    and .technical_capture.cases_passed == 27
    and .technical_capture.false_grounded_count == 0
    and .ui_e2e.cases_passed == 27
    and (.residual_risk | index("human_subjective_usefulness_not_measured")) != null
  ' "$tip03512_result" >/dev/null 2>&1; then
  record tip034_usefulness pass "Homeowner-approved AI-surrogate operator gate passed; human subjective usefulness remains unmeasured"
else
  record tip034_usefulness blocked "no human GO or explicitly approved AI-surrogate GO exists for this build"
fi

connector_report="eval/enterprise_corpus/connector_readiness.json"
if [[ -f "$connector_report" ]] && jq -e '.counts.active == 0' \
    "$connector_report" >/dev/null 2>&1; then
  record connector_boundary pass "enterprise connectors remain feature-off"
else
  record connector_boundary blocked "connector boundary is absent or an enterprise connector is active"
fi

if [[ ! -f "$production_env" ]]; then
  record production_configuration blocked "production environment file is missing"
elif PRODUCTION_ENV_FILE="$production_env" \
    PRODUCTION_EXPECTED_BUILD="$candidate" \
    PRODUCTION_CONFIGURATION_REPORT="${release_evidence_dir%/}/tip035_18_production_configuration.json" \
    ./scripts/verify-production-configuration.sh >/dev/null 2>&1; then
  record production_configuration pass "deployment, TLS and application production validators passed"
else
  record production_configuration blocked "deployment, TLS or application production validator failed"
fi

if [[ "${TIP035_TARGET_DRILLS_ATTESTED:-0}" == "1" ]]; then
  record target_operational_drills pass "hardened, load/SLO, restore and rollback evidence attested"
else
  record target_operational_drills blocked "target hardened/load/restore/rollback drills are not attested"
fi

if [[ "${TIP035_HOMEOWNER_GO:-0}" == "1" ]]; then
  record homeowner_go pass "Homeowner GO recorded for this cutover session"
else
  record homeowner_go blocked "Homeowner GO has not been recorded"
fi

mkdir -p "$(dirname "$report")"
jq -n \
  --arg schema_version "1" \
  --arg build "$candidate" \
  --arg generated_at "$(date -u +%FT%TZ)" \
  --slurpfile gates "$gates" '
    {
      schema_version: ($schema_version | tonumber),
      generated_at: $generated_at,
      candidate_build: $build,
      status: (if all($gates[]; .status == "pass") then "ready" else "not_ready" end),
      gates: $gates,
      blocked_gates: [$gates[] | select(.status != "pass") | .gate]
    }
  ' > "$report"

status="$(jq -r '.status' "$report")"
passed="$(jq '[.gates[] | select(.status == "pass")] | length' "$report")"
blocked="$(jq '[.gates[] | select(.status != "pass")] | length' "$report")"
echo "TIP-035 RELEASE PREFLIGHT · status=$status · pass=$passed · blocked=$blocked · build=$candidate · report=$report"
if [[ "$status" != "ready" ]]; then
  echo "Blocked gates: $(jq -r '.blocked_gates | join(",")' "$report")" >&2
  exit 1
fi
