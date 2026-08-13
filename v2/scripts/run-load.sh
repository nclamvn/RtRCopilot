#!/usr/bin/env bash
# TIP-012 Task 5 (Builder 5) — run the k6 SLO scenarios through the ingress.
#
# k6 runs in the official pinned container, sharing the INGRESS container's
# network namespace so `https://rtr.local` resolves to Caddy directly (the
# ingress publishes on 127.0.0.1 only, so host-gateway would not reach it). Each
# scenario writes a machine-readable summary to load/results/<name>.summary.json
# (consumed by scripts/evaluate-slo.sh) and a full log to load/results/<name>.log.
#
# Prereq: the hardened stack is up WITH compose.load.yaml (raised rate limits so a
# single-IP generator measures server latency, not the per-IP quota). See
# docs/slo.md. The rate_limit_probe is NOT run here — it needs default limits;
# run it with scripts/run-load-probe.sh.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

K6_IMAGE="${K6_IMAGE:-grafana/k6:0.49.0@sha256:8cd78f9d0de5f50bc8821cceecf356d5d9e839e6611c226a3fcf13c591080fbd}"
INGRESS_HOST="${INGRESS_HOST:-rtr.local}"
COMPOSE=(docker compose -f compose.yaml -f compose.hardened.yaml -f compose.load.yaml)

results="$project_root/load/results"
mkdir -p "$results"
chmod 777 "$results"

ingress_id="$("${COMPOSE[@]}" ps -q ingress 2>/dev/null || true)"
if [[ -z "$ingress_id" ]]; then
  echo "FATAL: ingress container not running (bring up the hardened+load stack)" >&2
  exit 2
fi
# k6 attaches to the compose network and maps the ingress hostname to the
# ingress container IP (sharing the ingress netns is impossible together with
# --add-host, and the published 127.0.0.1 port is not reachable from a bridge).
net_name="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$ingress_id" | head -n1)"
ingress_ip="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$v.IPAddress}}{{end}}' "$ingress_id" | head -n1)"
if [[ -z "$net_name" || -z "$ingress_ip" ]]; then
  echo "FATAL: could not resolve ingress network/IP" >&2
  exit 2
fi
echo "ingress network=$net_name ip=$ingress_ip"

# Ensure the reproducible load fixtures exist (upload target + budget headroom).
if [[ "${SKIP_SEED:-0}" != "1" ]]; then
  INGRESS_HOST="$INGRESS_HOST" ./scripts/seed-load-fixtures.sh || {
    echo "WARN: seed-load-fixtures failed; upload scenario may be skipped" >&2; }
fi
upload_target="${UPLOAD_TARGET_ID:-}"
if [[ -z "$upload_target" && -f /tmp/upload_target_rid.txt ]]; then
  upload_target="$(cat /tmp/upload_target_rid.txt)"
fi

run_scenario() {
  local name="$1"; shift
  local envs=("$@")
  echo "==================================================================="
  echo "k6 scenario: $name  ${envs[*]}"
  echo "==================================================================="
  local docker_args=(run --rm
    --network "$net_name"
    --add-host "$INGRESS_HOST:$ingress_ip"
    -v "$project_root/load:/load:ro"
    -v "$results:/results"
    -e "BASE_URL=https://$INGRESS_HOST")
  if [[ -n "$upload_target" ]]; then
    docker_args+=(-e "UPLOAD_TARGET_ID=$upload_target")
  fi
  local kv
  for kv in "${envs[@]}"; do
    docker_args+=(-e "$kv")
  done
  docker_args+=("$K6_IMAGE" run
    --insecure-skip-tls-verify
    --summary-export="/results/$name.summary.json"
    "/load/$name.js")
  docker "${docker_args[@]}" 2>&1 | tee "$results/$name.log"
  python3 "$project_root/scripts/redact-k6-summary.py" \
    "$results/$name.summary.json"
}

# S1 (+S5 availability): mixed reads at a representative arrival rate + 1 rps
# status probe. RATE is the target authenticated-read throughput (reads/s).
run_scenario steady_read "RATE=${STEADY_RATE:-10}" "DURATION=${STEADY_DURATION:-60s}"
# S2: ask burst (fake provider).
run_scenario ask_burst "VUS=${ASK_VUS:-8}" "DURATION=${ASK_DURATION:-30s}"
# S3: 1 MB upload-accept.
run_scenario upload_stream "VUS=${UPLOAD_VUS:-5}" "DURATION=${UPLOAD_DURATION:-30s}"
# S6: spike-and-recover on the read path.
run_scenario spike_recover "BASE_VUS=${BASE_VUS:-5}" "SPIKE_VUS=${SPIKE_VUS:-40}"

echo
echo "All SLO scenarios complete. Summaries in load/results/*.summary.json"
echo "Evaluate with: scripts/evaluate-slo.sh"
