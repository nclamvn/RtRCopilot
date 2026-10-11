#!/usr/bin/env bash
# =============================================================================
# TIP-013B · LOCAL/dev one-command demo runner  (NOT production)
# =============================================================================
# Brings up an ISOLATED RtR Copilot pilot stack on the Homeowner's own machine,
# activates
# the curated real-kernel batch (219 facts) through the REAL curator-gated
# publish gate, indexes it for RAG, and serves a reachable browser UI at
# http://localhost:3000.
#
# Everything here is LOCAL/dev:
#   * identity  = dev-OIDC (no corporate IdP; a click-through login)
#   * signing   = a random SOT_SIGNING_SECRET generated on first run and reused
#   * database  = a dedicated compose project/volume, never the dev database
# It fabricates NO production credentials and claims NO production readiness.
#
# Requirements on the Homeowner's machine:
#   * Docker + Docker Compose v2      (`docker compose version`)
#   * this repo checked out
#   * the READ-ONLY kernel snapshot (registry/*.yaml) — point --kernel-root at it
#
# Usage:
#   scripts/local-demo.sh --kernel-root /path/to/kernel-real   # full bring-up
#   scripts/local-demo.sh --kernel-root /path/to/kernel-real --down   # tear down
#
# Idempotent: re-running re-uses the generated secret, the onboard step is
# idempotent (no double activation), and reindex is a no-op once drained.
# =============================================================================
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

PILOT_PROJECT_NAME="${PILOT_PROJECT_NAME:-rtr-copilot-pilot}"
PILOT_ENV_FILE="${PILOT_ENV_FILE:-.env.pilot}"
PILOT_BASE_ENV_FILE="${PILOT_BASE_ENV_FILE:-}"

# ---- args -------------------------------------------------------------------
KERNEL_ROOT="${KERNEL_ROOT:-}"
ACTION="up"
for ((i = 1; i <= $#; i++)); do
  arg="${!i}"
  case "$arg" in
    --kernel-root) next=$((i + 1)); KERNEL_ROOT="${!next}"; i=$next ;;
    --down) ACTION="down" ;;
    -h|--help) grep -E '^# ' "$0" | sed 's/^# //'; exit 0 ;;
  esac
done

compose() {
  docker compose -p "$PILOT_PROJECT_NAME" --env-file "$PILOT_ENV_FILE" "$@"
}

if [[ "$ACTION" == "down" ]]; then
  echo "==> Tearing down isolated pilot '$PILOT_PROJECT_NAME' (pilot volumes only)…"
  compose down -v || true
  echo "Done. (kept $PILOT_ENV_FILE so the signing secret is stable on next run)"
  exit 0
fi

# ---- locate the kernel snapshot --------------------------------------------
if [[ -z "$KERNEL_ROOT" ]]; then
  for cand in "./kernel-real" "../kernel-real" "$HOME/kernel-real" "/home/claude/kernel-real"; do
    [[ -d "$cand/registry" ]] && KERNEL_ROOT="$cand" && break
  done
fi
if [[ -z "$KERNEL_ROOT" || ( ! -f "$KERNEL_ROOT/registry/specs.yaml" && ! -f "$KERNEL_ROOT/specs.yaml" ) ]]; then
  echo "ERROR: kernel snapshot not found. Pass --kernel-root /path/to/kernel-real" >&2
  echo "       (the directory that contains registry/specs.yaml etc.)" >&2
  exit 1
fi
KERNEL_ROOT="$(cd "$KERNEL_ROOT" && pwd)"
echo "==> kernel snapshot: $KERNEL_ROOT (read-only)"

# Resolve the configuration before any infrastructure is created. A quality
# profile using OpenAI embeddings exports canonical corpus text during the
# reindex step; a general request to start a pilot must never imply permission
# for that separate disclosure purpose.
if [[ -z "$PILOT_BASE_ENV_FILE" ]]; then
  PILOT_BASE_ENV_FILE=".env"
  [[ -f .env.demo ]] && PILOT_BASE_ENV_FILE=".env.demo"
fi
effective_env="$PILOT_BASE_ENV_FILE"
[[ -f "$PILOT_ENV_FILE" ]] && effective_env="$PILOT_ENV_FILE"
if [[ ! -f "$effective_env" ]]; then
  echo "ERROR: pilot source environment not found: $effective_env" >&2
  exit 2
fi
embedding_provider="$(awk -F= '$1 == "RAG_EMBEDDING_PROVIDER" {value=substr($0, index($0, "=") + 1)} END {print value}' "$effective_env")"
embedding_provider="${embedding_provider:-offline}"
if [[ "$embedding_provider" == "openai" && "${PILOT_APPROVE_EXTERNAL_CORPUS:-0}" != "1" ]]; then
  echo "PILOT START BLOCKED · semantic indexing would send the governed pilot corpus to the configured OpenAI endpoint" >&2
  echo "Set PILOT_APPROVE_EXTERNAL_CORPUS=1 only after purpose-bound corpus export approval." >&2
  exit 2
fi

# ---- preflight --------------------------------------------------------------
command -v docker >/dev/null || { echo "ERROR: docker not found" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose v2 required" >&2; exit 1; }
export RTR_BUILD_SHA="${RTR_BUILD_SHA:-$(./scripts/build-identity.sh)}"

# ---- build the pilot env (compose reads the isolated env file) -------------
# Reuse the base .env values (internal compose hostnames) and OVERLAY the LOCAL
# demo bits: dev-OIDC on, a freshly generated signing secret (persisted so the
# stack is stable across restarts), and a fresh demo database name.
if [[ ! -f "$PILOT_ENV_FILE" ]]; then
  echo "==> Generating $PILOT_ENV_FILE with a random SOT_SIGNING_SECRET…"
  SECRET="$(docker run --rm python:3.12-alpine python -c 'import secrets;print(secrets.token_hex(32))' 2>/dev/null \
            || python3 -c 'import secrets;print(secrets.token_hex(32))')"
  # Reuse the approved quality configuration when available. The copied file
  # is ignored by Git and the pilot gets a separate compose namespace/volumes.
  source_env="$PILOT_BASE_ENV_FILE"
  cp "$source_env" "$PILOT_ENV_FILE"
  {
    echo ""
    echo "# ---- TIP-013B LOCAL demo overlay (generated $(date -u +%FT%TZ)) ----"
    echo "APP_ENV=development"
    echo "DEV_OIDC_ENABLED=true"
    echo "SESSION_COOKIE_SECURE=false"
    echo "EXPECTED_SCHEMA_REVISION=0018_action_contracts"
    echo "SOT_SIGNING_SECRET=${SECRET}"
    echo "SOT_STAGING_ROOT=/tmp/rtr-sot-staging"
    echo "API_PORT=18100"
    echo "WEB_PORT=3100"
    echo "MINIO_CONSOLE_PORT=9101"
    echo "PUBLIC_BASE_URL=http://127.0.0.1:3100"
  } >> "$PILOT_ENV_FILE"
else
  echo "==> Reusing $PILOT_ENV_FILE (stable pilot identity and volumes)."
fi

# ---- 1) infra: postgres + redis + minio (+ bucket) --------------------------
echo "==> [1/6] Building images and starting isolated infra…"
if [[ "${RTR_REBUILD:-}" == "1" ]]; then compose build --no-cache api web; else compose build api web; fi
compose up -d postgres redis minio minio-init clamav
echo "    waiting for infra health…"
compose up -d --wait postgres redis minio clamav

# ---- 2) migrate to head -----------------------------------------------------
echo "==> [2/6] Migrating database to head (alembic upgrade head)…"
compose run --rm migrate

# ---- 3) + 4) + 5) emit(real-signed) → seed curator → activate → reindex -----
# Run the whole activation inside ONE backend container so the emitted staging
# packages, the seeded curator and the onboard --apply share the same env and
# filesystem. The kernel snapshot and the eval/ tooling (not baked into the
# image) are mounted read-only.
echo "==> [3/6] Emitting real-signed curated packages (219 ready)…"
echo "==> [4/6] Seeding curator/owner subjects + activating through the gate…"
echo "==> [5/6] Reindexing so RAG can answer…"
compose run --rm \
  -v "$KERNEL_ROOT":/kernel:ro \
  -v "$project_root/eval":/app/eval:ro \
  api sh -ec '
    python /app/eval/migrate/run_migration.py \
      --curated --emit \
      --kernel-root /kernel \
      --out "$SOT_STAGING_ROOT" \
      --manifest-out /tmp/manifest.json \
      --report-json /tmp/emit-report.json \
      --expect-total 259 \
      --expect-ready 219
    python /app/eval/demo/seed_curator.py
    python -m rtr_copilot.commands.onboard_batch \
      --manifest /tmp/manifest.json --apply --approve --report /tmp/ledger.json
    python /app/eval/demo/run_reindex.py
    python -m rtr_copilot.commands.reindex_file_chunks
    echo "---- activation ledger ----"
    python -c "import json;l=json.load(open(\"/tmp/ledger.json\"));print(\"status=\"+l[\"status\"],\"activated=\"+str(l[\"activated_count\"]))"
  '

# ---- 6) app: api + worker + web --------------------------------------------
echo "==> [6/6] Starting api + worker + web…"
echo "    runtime build: $RTR_BUILD_SHA"
compose up -d --wait --build --force-recreate api worker web || compose up -d --build --force-recreate api worker web

WEB_PORT="$(grep -E '^WEB_PORT=' "$PILOT_ENV_FILE" | tail -1 | cut -d= -f2 || echo 3100)"
WEB_PORT="${WEB_PORT:-3000}"

cat <<EOF

=============================================================================
  LOCAL demo is UP  —  open:  http://localhost:${WEB_PORT}
=============================================================================
  * Isolated project: ${PILOT_PROJECT_NAME} (never shares dev volumes).
  * This is a LOCAL/pilot stack (dev-OIDC, locally-generated signing secret).
  * Login: click "Sign in" — dev-OIDC logs you in as staff@rtrobotics.com
    (role: staff) with NO password. It is NOT a corporate account.
  * 219 real kernel facts are live and answerable with citations + the
    soft-fact confidence caveat. Try, in the Copilot ask box:
        - "Maximum payload capacity"   (HERA payload — grounded)
        - "HERA MTOW"                  (HC-001 — grounded + caveat)
        - "VEGA giá bao nhiêu"         (VEGA price — grounded + caveat)
  * API:   http://localhost:$(grep -E '^API_PORT=' "$PILOT_ENV_FILE" | tail -1 | cut -d= -f2 || echo 18100)
  * Tear down:  scripts/local-demo.sh --down
=============================================================================
EOF
