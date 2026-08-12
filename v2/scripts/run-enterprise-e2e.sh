#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

env_file="${E2E_ENV_FILE:-.env.demo}"
http_report="${E2E_HTTP_REPORT:-eval/real_world/latest_http_summary.json}"
api_port="${E2E_API_PORT:-18101}"
web_port="${E2E_WEB_PORT:-3101}"
redis_database="${E2E_REDIS_DATABASE:-15}"
run_suffix="$(date -u +%Y%m%d%H%M%S)_$RANDOM"
clone_database="rtr_e2e_${run_suffix}"
api_container="rtr-e2e-api-${run_suffix}"
worker_container="rtr-e2e-worker-${run_suffix}"
web_container="rtr-e2e-web-${run_suffix}"
dump_file=""
http_runtime=""

if [[ ! -f "$env_file" ]]; then
  echo "E2E env file not found: $env_file" >&2
  exit 2
fi
if [[ ! "$clone_database" =~ ^rtr_e2e_[0-9_]+$ ]]; then
  echo "Unsafe E2E database name" >&2
  exit 2
fi
if ! [[ "$redis_database" =~ ^[0-9]+$ ]] \
  || (( redis_database < 1 || redis_database > 15 )); then
  echo "E2E_REDIS_DATABASE must be an isolated Redis DB from 1 to 15" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DSN:?POSTGRES_DSN is required}"

# Purpose-bound release campaigns must attest the immutable checkout that was
# actually built. The local demo env intentionally defaults to "development",
# so a release wrapper supplies the clean candidate explicitly instead of
# allowing that placeholder to leak into the generated evidence report.
if [[ -n "${E2E_BUILD_IDENTITY:-}" ]]; then
  if [[ ! "$E2E_BUILD_IDENTITY" =~ ^[0-9a-f]{12,64}$ ]]; then
    echo "E2E_BUILD_IDENTITY must be a clean immutable Git identity" >&2
    exit 2
  fi
  export RTR_BUILD_SHA="$E2E_BUILD_IDENTITY"
fi

e2e_case_args=()
if [[ -n "${E2E_CASE_IDS:-}" ]]; then
  IFS=',' read -r -a requested_case_ids <<<"$E2E_CASE_IDS"
  for case_id in "${requested_case_ids[@]}"; do
    if [[ ! "$case_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
      echo "E2E_CASE_IDS contains an invalid case id: $case_id" >&2
      exit 2
    fi
    e2e_case_args+=(--case-id "$case_id")
  done
  echo "E2E spend mode: targeted regression (${E2E_CASE_IDS})"
elif [[ "${E2E_APPROVE_FULL:-0}" == "1" ]]; then
  echo "E2E spend mode: approved full enterprise campaign"
else
  e2e_case_limit="${E2E_CASE_LIMIT:-12}"
  if ! [[ "$e2e_case_limit" =~ ^[1-9][0-9]*$ ]]; then
    echo "E2E_CASE_LIMIT must be a positive integer" >&2
    exit 2
  fi
  e2e_case_args=(--max-cases "$e2e_case_limit")
  echo "E2E spend mode: bounded smoke campaign (${e2e_case_limit} cases)"
fi

compose=(docker compose --env-file "$env_file")
source_e2e_runs_before=""

cleanup() {
  set +e
  docker rm -f \
    "$web_container" "$api_container" "$worker_container" >/dev/null 2>&1
  "${compose[@]}" exec -T redis redis-cli -n "$redis_database" FLUSHDB \
    >/dev/null 2>&1
  "${compose[@]}" exec -T postgres dropdb \
    --if-exists -U "$POSTGRES_USER" "$clone_database" >/dev/null 2>&1
  if [[ -n "$dump_file" ]]; then
    rm -f "$dump_file"
  fi
  if [[ "$http_runtime" == /tmp/rtr-e2e-http.* ]]; then
    rm -rf "$http_runtime"
  fi
}
trap cleanup EXIT INT TERM

dump_file="$(mktemp /tmp/rtr-e2e-db.XXXXXX)"
http_runtime="$(mktemp -d /tmp/rtr-e2e-http.XXXXXX)"

if curl -fsS "http://127.0.0.1:${web_port}/api/status" >/dev/null 2>&1 \
  || curl -fsS "http://127.0.0.1:${api_port}/health/live" >/dev/null 2>&1; then
  echo "E2E port already in use; choose E2E_WEB_PORT/E2E_API_PORT" >&2
  exit 2
fi

"${compose[@]}" up -d postgres redis minio minio-init
if [[ "${E2E_SKIP_BUILD:-0}" != "1" ]]; then
  "${compose[@]}" build api worker web
fi

source_e2e_runs_before="$(
  "${compose[@]}" exec -T postgres psql -X -At \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) FROM answer_runs WHERE request_id LIKE 'e2e-%'"
)"

"${compose[@]}" exec -T postgres pg_dump \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$dump_file"
"${compose[@]}" exec -T postgres createdb \
  -U "$POSTGRES_USER" "$clone_database"
"${compose[@]}" exec -T postgres pg_restore --no-owner \
  -U "$POSTGRES_USER" -d "$clone_database" <"$dump_file"

runtime_dsn="${POSTGRES_DSN%/*}/${clone_database}"

"${compose[@]}" run -d --no-deps \
  --name "$worker_container" \
  -e POSTGRES_DSN="$runtime_dsn" \
  -e REDIS_URL="redis://redis:6379/${redis_database}" worker >/dev/null

"${compose[@]}" run -d --no-deps \
  --name "$api_container" \
  -e POSTGRES_DSN="$runtime_dsn" \
  -e REDIS_URL="redis://redis:6379/${redis_database}" \
  -e LIMITS_RATE_ASK_MAX=1000 \
  -e LIMITS_RATE_AUTH_MAX=1000 \
  -e RAG_EXPOSE_DECISION_DIAGNOSTICS=1 \
  -e PUBLIC_BASE_URL="http://127.0.0.1:${web_port}" \
  -p "127.0.0.1:${api_port}:8000" api >/dev/null

"${compose[@]}" run -d --no-deps \
  --name "$web_container" \
  -e API_INTERNAL_URL="http://${api_container}:8000" \
  -p "127.0.0.1:${web_port}:3000" web >/dev/null

wait_for_url() {
  local label="$1"
  local url="$2"
  local container="$3"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "E2E readiness failed: $label" >&2
  docker logs --tail 120 "$container" >&2 || true
  return 1
}

wait_for_url \
  "isolated API" \
  "http://127.0.0.1:${api_port}/health/operational" \
  "$api_container"
wait_for_url \
  "isolated web" \
  "http://127.0.0.1:${web_port}/api/status" \
  "$web_container"

mkdir -p "$(dirname "$http_report")"
python3 -m venv "$http_runtime"
"$http_runtime/bin/python" -m pip install \
  --disable-pip-version-check --quiet "httpx==0.28.1"
campaign_status=0
browser_status=0

if [[ "${E2E_SKIP_HTTP:-0}" != "1" ]]; then
  set +e
  "$http_runtime/bin/python" eval/run_real_world_acceptance.py \
      --base-url "http://127.0.0.1:${web_port}" \
      --concurrency "${E2E_CONCURRENCY:-3}" \
      --request-timeout "${E2E_REQUEST_TIMEOUT:-150}" \
      ${e2e_case_args[@]+"${e2e_case_args[@]}"} \
    >"$http_report"
  campaign_status=$?
  set -e

  jq '{passed,gates,metrics:{total:.metrics.total,passed:.metrics.passed,
    failed:.metrics.failed,overall_pass_rate:.metrics.overall_pass_rate,
    grounded_success_rate:.metrics.grounded_success_rate,
    citation_accuracy:.metrics.citation_accuracy,
    honest_null_precision:.metrics.honest_null_precision,
    false_grounded_count:.metrics.false_grounded_count,
    follow_up_pass_rate:.metrics.follow_up_pass_rate,
    p95_latency_ms:.metrics.p95_latency_ms,
    domains:.metrics.domains}}' "$http_report"
else
  echo "Skipping HTTP acceptance campaign (E2E_SKIP_HTTP=1)"
fi

if [[ "${E2E_SKIP_BROWSER:-0}" != "1" ]]; then
  set +e
  if [[ -n "${E2E_LIVE_GREP:-}" ]]; then
    PLAYWRIGHT_BASE_URL="http://127.0.0.1:${web_port}" \
      pnpm --filter @rtr/web exec playwright test \
        --config playwright.live.config.ts --grep "$E2E_LIVE_GREP"
  else
    PLAYWRIGHT_BASE_URL="http://127.0.0.1:${web_port}" \
      pnpm --filter @rtr/web test:browser:live
  fi
  browser_status=$?
  set -e
else
  echo "Skipping browser campaign (E2E_SKIP_BROWSER=1)"
fi

source_e2e_runs_after="$(
  "${compose[@]}" exec -T postgres psql -X -At \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) FROM answer_runs WHERE request_id LIKE 'e2e-%'"
)"
if [[ "$source_e2e_runs_before" != "$source_e2e_runs_after" ]]; then
  echo "E2E isolation failure: source database received E2E answer runs" >&2
  exit 1
fi

if (( campaign_status != 0 || browser_status != 0 )); then
  echo "ENTERPRISE E2E FAIL · campaign_status=$campaign_status · browser_status=$browser_status · report=$http_report" >&2
  exit 1
fi

echo "ENTERPRISE E2E PASS · isolated_db=$clone_database · report=$http_report"
