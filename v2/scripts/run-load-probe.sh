#!/usr/bin/env bash
# TIP-012 Task 5 (Builder 5) — R1 rate-limit-under-load probe at the SHIPPED
# DEFAULT limits. Recreates the api container WITHOUT compose.load.yaml (so the
# default `default-read` quota of 120/60s applies), then drives one client IP
# past it through the ingress and asserts typed 429 + Retry-After appear with
# zero 5xx. k6's own thresholds make the run exit non-zero on failure.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

K6_IMAGE="${K6_IMAGE:-grafana/k6:0.49.0@sha256:8cd78f9d0de5f50bc8821cceecf356d5d9e839e6611c226a3fcf13c591080fbd}"
INGRESS_HOST="${INGRESS_HOST:-rtr.local}"
# Default-limits compose shape (NO compose.load.yaml).
HARDENED=(docker compose -f compose.yaml -f compose.hardened.yaml)
results="$project_root/load/results"
mkdir -p "$results"; chmod 777 "$results"

echo "== recreating api at DEFAULT rate limits (dropping compose.load.yaml) =="
MALWARE_SIGNATURE_MAX_AGE_SECONDS="${MALWARE_SIGNATURE_MAX_AGE_SECONDS:-1209600}" \
PUBLIC_BASE_URL="https://$INGRESS_HOST" INGRESS_HOST="$INGRESS_HOST" \
  "${HARDENED[@]}" --profile hardened up -d --force-recreate --no-deps api
INGRESS_HOST="$INGRESS_HOST" ./scripts/wait-ready-hardened.sh

ingress_id="$("${HARDENED[@]}" ps -q ingress)"
net_name="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$ingress_id" | head -n1)"
ingress_ip="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$v.IPAddress}}{{end}}' "$ingress_id" | head -n1)"
echo "== running rate_limit_probe (default default-read quota = 120/60s) =="
docker run --rm \
  --network "$net_name" \
  --add-host "$INGRESS_HOST:$ingress_ip" \
  -v "$project_root/load:/load:ro" \
  -v "$results:/results" \
  -e "BASE_URL=https://$INGRESS_HOST" \
  -e "PROBE_REQUESTS=${PROBE_REQUESTS:-250}" \
  -e "PROBE_VUS=${PROBE_VUS:-10}" \
  "$K6_IMAGE" run \
    --insecure-skip-tls-verify \
    --summary-export=/results/rate_limit_probe.summary.json \
    /load/rate_limit_probe.js 2>&1 | tee "$results/rate_limit_probe.log"
