#!/usr/bin/env bash
# TIP-012 Task 4 (D-012-06, AC-11) — local CI: the exact sequence that
# .github/workflows/verify.yml runs, executable in THIS environment. This is the
# Contractor's CI evidence where GitHub is unavailable.
#
# Stage-by-stage mirror of the local gate + the two new policy gates:
#   0  migration gate          scripts/migration-gate.sh
#   0' image / runtime policy   scripts/verify-image-policy.sh
#   a  backend lint+type+unit   ruff + mypy + pytest      (apps/backend, uv)
#   b  web  lint+type+unit+build pnpm verify:web
#   c  compose config + build
#   d  Trivy                     scripts/verify-container-vulnerabilities.sh
#   e  containerized data-integration  scripts/verify-data-integration.sh
#   f  mocked Playwright browser suite
#
# Fail-closed: set -e + explicit checks; any stage failure aborts non-zero.
#
# Sandbox compose-build workaround (parameterised, no-op on a normal machine):
#   RTR_SANDBOX_BUILD=1     → buildkit source policy + vosk mirror build-arg
# See scripts/ci-common.sh.
#
# Stage selection (default: all). Space/comma list of stage keys:
#   RTR_CI_STAGES="migration-gate image-policy backend web compose trivy data-integration browser"
# Convenience skips:
#   RTR_CI_SKIP_BROWSER=1   drop the Playwright stage (e.g. no browser download)
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
# shellcheck source=scripts/ci-common.sh
source "$project_root/scripts/ci-common.sh"

ALL_STAGES=(migration-gate image-policy backend web compose trivy data-integration browser)
requested="${RTR_CI_STAGES:-${ALL_STAGES[*]}}"
requested="${requested//,/ }"
if [[ "${RTR_CI_SKIP_BROWSER:-0}" == "1" ]]; then
  requested="${requested//browser/}"
fi

want() {
  local s
  for s in $requested; do [[ "$s" == "$1" ]] && return 0; done
  return 1
}

passed=()
skipped=()

# ---------------------------------------------------------------------------
stage_migration_gate() { "$project_root/scripts/migration-gate.sh"; }

stage_image_policy() { "$project_root/scripts/verify-image-policy.sh"; }

stage_backend() {
  if command -v uv >/dev/null 2>&1; then
    ( cd apps/backend && uv sync --frozen && uv run ruff check . && uv run mypy && uv run pytest )
  else
    docker run --rm \
      -v "$project_root/apps/backend:/app" -w /app python:3.12.4-slim \
      sh -ec 'apt-get update -qq &&
        apt-get install --no-install-recommends --yes fonts-dejavu-core >/dev/null &&
        pip install --no-cache-dir uv==0.8.11 >/dev/null &&
        uv sync --frozen && uv run ruff check . && uv run mypy && uv run pytest'
  fi
}

stage_web() {
  pnpm install --frozen-lockfile
  pnpm verify:web
}

stage_compose() {
  docker compose config --quiet
  docker compose -f compose.yaml -f compose.hardened.yaml --profile hardened config --quiet
  rtr_sandbox_prepare
  docker compose build "${RTR_COMPOSE_BUILD_ARGS[@]}"
}

stage_trivy() { "$project_root/scripts/verify-container-vulnerabilities.sh"; }

stage_data_integration() { "$project_root/scripts/verify-data-integration.sh"; }

stage_browser() {
  local port="${RTR_CI_WEB_PORT:-3100}"
  local base="${PLAYWRIGHT_BASE_URL:-}"
  local server_pid=""

  rtr_info "ensuring Playwright chromium is installed"
  if ! pnpm --filter @rtr/web exec playwright install chromium >/tmp/rtr-ci-pw-install.log 2>&1; then
    rtr_info "playwright install chromium failed (see /tmp/rtr-ci-pw-install.log)"
    rtr_die 60 "cannot install the Playwright browser in this environment"
  fi

  if [[ -n "$base" ]] && curl -fsS -o /dev/null --max-time 3 "$base/api/status"; then
    rtr_info "using existing web server at $base"
  else
    base="http://127.0.0.1:$port"
    rtr_info "starting 'next start' on $base"
    ( cd apps/web && exec pnpm exec next start --hostname 127.0.0.1 --port "$port" ) \
      >/tmp/rtr-ci-next.log 2>&1 &
    server_pid=$!
    # shellcheck disable=SC2064
    trap "kill $server_pid 2>/dev/null || true" RETURN
    local deadline=$((SECONDS + 60))
    until curl -fsS -o /dev/null --max-time 3 "$base/api/status"; do
      (( SECONDS < deadline )) || { cat /tmp/rtr-ci-next.log >&2 || true; rtr_die 61 "web server did not become ready on $base"; }
      kill -0 "$server_pid" 2>/dev/null || { cat /tmp/rtr-ci-next.log >&2 || true; rtr_die 61 "web server exited before ready"; }
      sleep 1
    done
    rtr_info "web server ready"
  fi

  PLAYWRIGHT_BASE_URL="$base" pnpm --filter @rtr/web test:browser
}

# ---------------------------------------------------------------------------
run_stage() {
  local key="$1" label="$2" fn="$3"
  if ! want "$key"; then
    rtr_stage "SKIP · $label" "not in RTR_CI_STAGES"
    skipped+=("$key")
    return 0
  fi
  rtr_stage "$label"
  "$fn"
  passed+=("$key")
}

rtr_stage "CI-LOCAL START" "stages: $requested"

run_stage migration-gate   "GATE · migration gate"                stage_migration_gate
run_stage image-policy     "GATE · image & runtime policy"        stage_image_policy
run_stage backend          "(a) backend · ruff + mypy + pytest"   stage_backend
run_stage web              "(b) web · lint + type + unit + build" stage_web
run_stage compose          "(c) compose · config + build"         stage_compose
run_stage trivy            "(d) Trivy · image vuln scan"          stage_trivy
run_stage data-integration "(e) containerized data-integration"   stage_data_integration
run_stage browser          "(f) mocked Playwright browser suite"  stage_browser

rtr_stage "CI-LOCAL PASS" "passed: ${passed[*]:-none} · skipped: ${skipped[*]:-none}"
echo "CI-LOCAL VERIFY PASS"
