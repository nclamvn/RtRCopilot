#!/usr/bin/env bash
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r2}; runner="$run_id-runner"; pg="$run_id-pg"
gate_id=${TIP054_LIVE_OWNER_ID:-live_owner_frozen_r1}
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
evidence="$experiment_dir/raw/$run_id/$gate_id"; container_evidence="/evidence/$gate_id"
[[ ! -e "$evidence" ]] || exit 2
for target in "$runner" "$pg"; do [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2; done
mkdir -p "$evidence"
database="rtr_tip054_live_$gate_id"; engine="rtr_tip054_le_$gate_id"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$evidence/databases.txt"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src TMPDIR=/tmp APP_ENV=test ACTION_EXECUTOR_ENABLED=true
  POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database" INTEGRATION_DATABASE_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  MIGRATION_DSN="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database" ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
exec_runner /app/.venv/bin/alembic upgrade head > "$evidence/migrate.stdout.txt" 2> "$evidence/migrate.stderr.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only'; REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$evidence/databases.txt"
exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/source-before.json" > "$evidence/source-before.stdout.txt"
exec_runner /app/.venv/bin/python /work/native_probe.py seed "$container_evidence" > "$evidence/seed.stdout.txt" 2> "$evidence/seed.stderr.txt"
set +e
exec_runner /app/.venv/bin/python /work/live_owner_probe.py proof "$container_evidence" > "$evidence/supervisor.stdout.txt" 2> "$evidence/supervisor.stderr.txt"
code=$?
set -e
exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/source-after.json" > "$evidence/source-after.stdout.txt"
printf '{"returncode":%d}\n' "$code" > "$evidence/returncode.json"
cmp "$evidence/source-before.json" "$evidence/source-after.json"
exit "$code"
