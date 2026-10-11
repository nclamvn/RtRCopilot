#!/usr/bin/env bash
# Fresh ordinary SQL module; scheduling-only independent tests, no SDK/load.
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")/.." && pwd)
run_id=${TIP054_FULL_RUN_ID:?owned fixture required}
gate_id=${TIP054_GATE_ID:?unique gate required}
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
runner="$run_id-runner"; pg="$run_id-pg"
for target in "$runner" "$pg"; do
  [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2
done
evidence="$experiment_dir/raw/$run_id/$gate_id"; output="/evidence/$gate_id"
[[ ! -e "$evidence" ]] || exit 2
mkdir -p "$evidence"
database="rtr_tip054_rp_$gate_id"; engine="rtr_tip054_rpe_$gate_id"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$evidence/databases.txt"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src APP_ENV=test
  POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database" INTEGRATION_DATABASE_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  MIGRATION_DSN="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database" ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
exec_runner /app/.venv/bin/alembic upgrade head > "$evidence/migrate.stdout.txt" 2> "$evidence/migrate.stderr.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$evidence/databases.txt"
set +e
exec_runner timeout --signal=TERM --kill-after=10 90 /app/.venv/bin/python /work/r/nonleaf_probe.py "$output" > "$evidence/integration-1.stdout.txt" 2> "$evidence/integration-1.stderr.txt"
code=$?
set -e
printf '{"exit_code":%d,"limits":"Real Repo/Policy/scheduling repro; transparent observer, no rowlock/SDK certificate"}\n' "$code" > "$evidence/returncode.json"
exit "$code"
