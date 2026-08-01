#!/usr/bin/env bash
# TIP-012 Task 1 — readiness gate for the hardened (TLS ingress) profile.
# The internal services publish no ports here, so readiness is judged the way
# a client sees it: through the ingress only. curl --resolve pins the ingress
# hostname to 127.0.0.1 so no /etc/hosts entry is needed for this script.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$project_root/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$project_root/.env"
  set +a
fi

host="${INGRESS_HOST:-rtr.local}"
https_port="${INGRESS_HTTPS_PORT:-443}"
http_port="${INGRESS_HTTP_PORT:-80}"

deadline=$((SECONDS + 180))
while (( SECONDS < deadline )); do
  status="$(curl -ksS -o /dev/null -w '%{http_code}' \
    --noproxy '*' --resolve "$host:$https_port:127.0.0.1" \
    "https://$host:$https_port/api/status" || true)"
  redirect="$(curl -sS -o /dev/null -w '%{http_code}' \
    --noproxy '*' --resolve "$host:$http_port:127.0.0.1" \
    "http://$host:$http_port/" || true)"
  worker_id="$(docker compose --project-directory "$project_root" ps -q worker)"
  clamav_id="$(docker compose --project-directory "$project_root" ps -q clamav)"
  worker_health="$(docker inspect --format '{{.State.Health.Status}}' \
    "$worker_id" 2>/dev/null || true)"
  clamav_health="$(docker inspect --format '{{.State.Health.Status}}' \
    "$clamav_id" 2>/dev/null || true)"
  if [[ "$status" == "200" && ( "$redirect" == "308" || "$redirect" == "301" ) &&
        "$worker_health" == "healthy" && "$clamav_health" == "healthy" ]]; then
    echo "READY · https $status via ingress · http->https $redirect · worker healthy · ClamAV healthy"
    exit 0
  fi
  sleep 2
done
docker compose --project-directory "$project_root" ps
echo "DỪNG: hardened stack không ready trong 180 giây" >&2
exit 1
