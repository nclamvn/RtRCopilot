#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$project_root/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$project_root/.env"
  set +a
fi

deadline=$((SECONDS + 120))
while (( SECONDS < deadline )); do
  api="$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:${API_PORT:-8000}/health/ready || true)"
  web="$(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:${WEB_PORT:-3000}/api/status || true)"
  init="$(docker compose --project-directory "$project_root" ps \
    --all --format json minio-init 2>/dev/null || true)"
  worker_id="$(docker compose --project-directory "$project_root" ps -q worker)"
  clamav_id="$(docker compose --project-directory "$project_root" ps -q clamav)"
  worker_health="$(docker inspect --format '{{.State.Health.Status}}' \
    "$worker_id" 2>/dev/null || true)"
  clamav_health="$(docker inspect --format '{{.State.Health.Status}}' \
    "$clamav_id" 2>/dev/null || true)"
  if [[ "$api" == "200" && "$web" == "200" &&
        "$init" == *'"ExitCode":0'* &&
        "$worker_health" == "healthy" && "$clamav_health" == "healthy" ]]; then
    echo "READY · API $api · web $web · worker healthy · ClamAV healthy · MinIO initialized"
    exit 0
  fi
  sleep 2
done
docker compose --project-directory "$project_root" ps
echo "DỪNG: stack không ready trong 120 giây" >&2
exit 1
