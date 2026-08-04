#!/usr/bin/env bash
# TIP-012 Task 4 (D-012-07, AC-12) — versioned deploy of the hardened stack.
#
# Sequence (fail-closed at every step):
#   build → tag images :<version> → migration gate → migrate → rolling up -d
#   (hardened profile) → health gate (through the ingress) → record version.
#
# Version resolution (first non-empty wins):
#   $1  →  $RTR_DEPLOY_VERSION  →  git rev-parse --short HEAD
#
# Image model: compose builds `rtr-copilot-v2-<svc>:latest`. A deploy tags those
# as `rtr-copilot-v2-<svc>:<version>` (the rollback anchor) and runs `:latest`.
# rollback.sh re-points `:latest` at a previously-tagged version. No compose edit
# is needed and the whole thing is idempotent.
#
# Sandbox build workaround (parameterised, no-op on a normal machine):
#   RTR_SANDBOX_BUILD=1  (or set RTR_BUILD_SOURCE_POLICY / RTR_VOSK_MODEL_URL)
# See scripts/ci-common.sh.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
# shellcheck source=scripts/ci-common.sh
source "$project_root/scripts/ci-common.sh"

INGRESS_HOST="${INGRESS_HOST:-rtr.local}"
PUBLIC_BASE_URL="${RTR_DEPLOY_PUBLIC_BASE_URL:-https://$INGRESS_HOST}"
PROJECT="${RTR_PROJECT_NAME:-rtr-copilot-v2}"
SERVICES=(api worker web migrate)
HARDENED_COMPOSE=(docker compose -f compose.yaml -f compose.hardened.yaml)

deploy_dir="$project_root/deploy"
current_file="$deploy_dir/current-version"
previous_file="$deploy_dir/previous-version"
ledger="$deploy_dir/versions.log"
mkdir -p "$deploy_dir"

version="${1:-${RTR_DEPLOY_VERSION:-}}"
if [[ -z "$version" ]]; then
  version="$(git rev-parse --short HEAD 2>/dev/null || true)"
fi
[[ -n "$version" ]] || rtr_die 10 "no version given and 'git rev-parse --short HEAD' produced nothing"
# Docker tag charset guard (fail-closed on an unusable tag).
[[ "$version" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] || rtr_die 10 "invalid version tag: '$version'"

git_sha="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
export RTR_BUILD_SHA="${RTR_BUILD_SHA:-$git_sha}"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
rtr_stage "DEPLOY $version" "git=$git_sha host=$INGRESS_HOST base=$PUBLIC_BASE_URL"

# ---- Stage 1: build ------------------------------------------------------
rtr_stage "1/6 BUILD" "docker compose build (hardened profile)"
rtr_sandbox_prepare
"${HARDENED_COMPOSE[@]}" --profile tools --profile hardened build "${RTR_COMPOSE_BUILD_ARGS[@]}"

# ---- Stage 2: tag images :<version> -------------------------------------
rtr_stage "2/6 TAG" "tag built images :$version"
for svc in "${SERVICES[@]}"; do
  src="$PROJECT-$svc:latest"
  dst="$PROJECT-$svc:$version"
  docker image inspect "$src" >/dev/null 2>&1 || rtr_die 11 "expected built image missing: $src"
  docker tag "$src" "$dst"
  rtr_info "tagged $dst"
done

# ---- Stage 3: migration gate --------------------------------------------
rtr_stage "3/6 MIGRATION GATE" "single head == pin, no divergence"
"$project_root/scripts/migration-gate.sh"

# ---- Stage 4: migrate ----------------------------------------------------
rtr_stage "4/6 MIGRATE" "bring infra up, alembic upgrade head"
"${HARDENED_COMPOSE[@]}" up -d postgres redis minio minio-init clamav
"${HARDENED_COMPOSE[@]}" --profile tools run --rm migrate

# ---- Stage 5: rolling up + health gate ----------------------------------
rtr_stage "5/6 ROLLING UP" "up -d hardened profile behind the ingress"
PUBLIC_BASE_URL="$PUBLIC_BASE_URL" INGRESS_HOST="$INGRESS_HOST" \
  "${HARDENED_COMPOSE[@]}" --profile hardened up -d api worker web ingress

rtr_stage "5/6 HEALTH GATE" "wait-ready-hardened (through the ingress)"
health_start=$SECONDS
INGRESS_HOST="$INGRESS_HOST" "$project_root/scripts/wait-ready-hardened.sh"
health_elapsed=$(( SECONDS - health_start ))
rtr_info "health gate green in ${health_elapsed}s"

# ---- Stage 6: record -----------------------------------------------------
rtr_stage "6/6 RECORD" "update version ledger"
prev_recorded=""
[[ -f "$current_file" ]] && prev_recorded="$(cat "$current_file")"
# Only advance previous-version when we truly moved to a new version, so a
# redeploy of the same version keeps a real rollback target.
if [[ -n "$prev_recorded" && "$prev_recorded" != "$version" ]]; then
  printf '%s\n' "$prev_recorded" > "$previous_file"
fi
printf '%s\n' "$version" > "$current_file"
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\tdeploy\tversion=%s\tgit=%s\tprev=%s\thealth_s=%s\tstarted=%s\n' \
  "$finished" "$version" "$git_sha" "${prev_recorded:-none}" "$health_elapsed" "$started" >> "$ledger"

rtr_info "current-version = $version"
rtr_info "previous-version = $( [[ -f "$previous_file" ]] && cat "$previous_file" || echo none )"
rtr_stage "DEPLOY OK" "version $version healthy (health gate ${health_elapsed}s)"
