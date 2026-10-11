#!/usr/bin/env bash
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r1}
runner="$run_id-runner"; pg="$run_id-pg"
gate_id=${TIP054_MIGRATION_ID:-migration_r1}
[[ "$gate_id" =~ ^[a-z0-9_]{1,30}$ ]] || exit 2
evidence="$experiment_dir/raw/$run_id/$gate_id"; container_evidence="/evidence/$gate_id"
[[ ! -e "$evidence" ]] || exit 2
for target in "$runner" "$pg"; do [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2; done
mkdir -p "$evidence"
database="rtr_tip054_exe_$gate_id"; engine="rtr_tip054_eng_$gate_id"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$evidence/databases.txt"
runtime="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
owner="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
engine_dsn="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src TMPDIR=/tmp APP_ENV=test
  POSTGRES_DSN="$runtime" MIGRATION_DSN="$owner" INTEGRATION_DATABASE_DSN="$runtime" ACTION_WORKFLOW_DSN="$engine_dsn" ACTION_EXECUTOR_ENABLED=true
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
# Current serving source requires0019. Populate only legacy domains under current
# schema, then downgrade empty executor tables to obtain genuine populated0018.
exec_runner /app/.venv/bin/alembic upgrade 0019_action_executor > "$evidence/initial-upgrade0019.stdout.txt" 2> "$evidence/initial-upgrade0019.stderr.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only'; REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$evidence/databases.txt"
for mode in seed seed-context seed-actions; do
  exec_runner /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py "$mode" > "$evidence/$mode.stdout.txt" 2> "$evidence/$mode.stderr.txt"
done
exec_runner /app/.venv/bin/alembic downgrade 0018_action_contracts > "$evidence/initial-downgrade0018.stdout.txt" 2> "$evidence/initial-downgrade0018.stderr.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py snapshot "$container_evidence/old0018.json" > "$evidence/snapshot0018.stdout.txt"
exec_runner /app/.venv/bin/alembic upgrade 0019_action_executor > "$evidence/upgrade0019.stdout.txt" 2> "$evidence/upgrade0019.stderr.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py verify "$container_evidence/old0018.json" > "$evidence/verify0018-after-up.stdout.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py seed-execution "$container_evidence/execution-seed.json" > "$evidence/execution-seed.stdout.txt" 2> "$evidence/execution-seed.stderr.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py grants "$container_evidence/runtime-grants.json" > "$evidence/runtime-grants.stdout.txt" 2> "$evidence/runtime-grants.stderr.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py snapshot "$container_evidence/old-plus-v2.json" > "$evidence/snapshot-v2.stdout.txt"
exec_runner /app/.venv/bin/alembic downgrade 0018_action_contracts > "$evidence/downgrade0018.stdout.txt" 2> "$evidence/downgrade0018.stderr.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py verify "$container_evidence/old-plus-v2.json" > "$evidence/survivors-after-down.stdout.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('action_executions','action_step_attempts','action_execution_receipts','action_execution_events','action_source_links');" | tee "$evidence/new-tables-after-down.txt" | grep -qx 0
exec_runner /app/.venv/bin/alembic upgrade 0019_action_executor > "$evidence/reupgrade0019.stdout.txt" 2> "$evidence/reupgrade0019.stderr.txt"
exec_runner /app/.venv/bin/python /work/migration_proof.py verify "$container_evidence/old-plus-v2.json" > "$evidence/survivors-after-reup.stdout.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -Atc 'SELECT (SELECT count(*) FROM action_executions)+(SELECT count(*) FROM action_step_attempts)+(SELECT count(*) FROM action_execution_receipts)+(SELECT count(*) FROM action_execution_events)+(SELECT count(*) FROM action_source_links);' | tee "$evidence/new-rows-after-reup.txt" | grep -qx 0
echo 'MIGRATION_PASS populated0018→0019→0018→0019 olddomainallrowsretained newexecutiondatadroppedbydowngrade_notrestore'
