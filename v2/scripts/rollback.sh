#!/usr/bin/env bash
# TIP-012 Task 4 (D-012-07, AC-12) — rollback the hardened stack to a previously
# deployed version.
#
# Sequence (fail-closed):
#   resolve target → re-point images :latest → rolling up -d (hardened) →
#   health gate → record.  The database schema is NEVER auto-downgraded.
#
# Target resolution (first non-empty wins):
#   $1  →  $RTR_ROLLBACK_VERSION  →  deploy/previous-version
#
# See scripts/deploy.sh for the image-tag model (rollback re-points :latest at
# `rtr-copilot-v2-<svc>:<target>`, which deploy.sh left behind).
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

current=""
[[ -f "$current_file" ]] && current="$(cat "$current_file")"

target="${1:-${RTR_ROLLBACK_VERSION:-}}"
if [[ -z "$target" ]]; then
  [[ -f "$previous_file" ]] || rtr_die 20 "no rollback target: pass a version or run a deploy first (deploy/previous-version absent)"
  target="$(cat "$previous_file")"
fi
[[ -n "$target" ]] || rtr_die 20 "resolved an empty rollback target"
[[ "$target" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] || rtr_die 20 "invalid target tag: '$target'"

rtr_stage "ROLLBACK → $target" "current=${current:-unknown} host=$INGRESS_HOST"

# ---- Stage 1: verify the target images exist ----------------------------
rtr_stage "1/4 VERIFY TARGET" "images rtr-copilot-v2-*:$target present"
for svc in "${SERVICES[@]}"; do
  img="$PROJECT-$svc:$target"
  docker image inspect "$img" >/dev/null 2>&1 || rtr_die 21 "rollback target image missing: $img (was it ever deployed?)"
  rtr_info "found $img"
done

# ---- Stage 2: re-point :latest at the target ----------------------------
rtr_stage "2/4 RE-POINT" "tag :$target → :latest"
for svc in "${SERVICES[@]}"; do
  docker tag "$PROJECT-$svc:$target" "$PROJECT-$svc:latest"
  rtr_info "$PROJECT-$svc:latest → $target"
done

# ---- SCHEMA WARNING (D-012-07) ------------------------------------------
cat >&2 <<WARN

**********************************************************************
* WARNING — DATABASE SCHEMA IS NOT AUTO-DOWNGRADED BY ROLLBACK.      *
* Rolling code back to '$target' does NOT revert any forward         *
* migration the newer version applied. Current DB head is unchanged. *
* Confirm '$target' is compatible with the current schema head       *
* (make migration-check). A schema downgrade is a Homeowner          *
* decision, executed separately — never a rollback side effect.      *
* Runbook: docs/runbook.md#rollback                                  *
**********************************************************************

WARN

# ---- Stage 3: rolling up + health gate ----------------------------------
rtr_stage "3/4 ROLLING UP" "up -d hardened profile (no migrate)"
"${HARDENED_COMPOSE[@]}" up -d postgres redis minio minio-init clamav
PUBLIC_BASE_URL="$PUBLIC_BASE_URL" INGRESS_HOST="$INGRESS_HOST" \
  "${HARDENED_COMPOSE[@]}" --profile hardened up -d --force-recreate api worker web ingress

rtr_stage "3/4 HEALTH GATE" "wait-ready-hardened (through the ingress)"
health_start=$SECONDS
INGRESS_HOST="$INGRESS_HOST" "$project_root/scripts/wait-ready-hardened.sh"
health_elapsed=$(( SECONDS - health_start ))
rtr_info "health gate green in ${health_elapsed}s"

# ---- Stage 4: record -----------------------------------------------------
rtr_stage "4/4 RECORD" "update version ledger"
# The version we are leaving becomes the new previous (so a re-deploy forward is
# coherent); the target becomes current.
if [[ -n "$current" && "$current" != "$target" ]]; then
  printf '%s\n' "$current" > "$previous_file"
fi
printf '%s\n' "$target" > "$current_file"
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\trollback\tversion=%s\tfrom=%s\thealth_s=%s\tschema=not_downgraded\n' \
  "$finished" "$target" "${current:-none}" "$health_elapsed" >> "$ledger"

rtr_info "current-version = $target"
rtr_info "previous-version = $( [[ -f "$previous_file" ]] && cat "$previous_file" || echo none )"
rtr_stage "ROLLBACK OK" "version $target healthy (health gate ${health_elapsed}s) · schema NOT downgraded"
