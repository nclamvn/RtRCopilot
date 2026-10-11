#!/usr/bin/env bash
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r1}
runner="$run_id-runner"; pg="$run_id-pg"
gate_id=${TIP054_NATIVE_ID:-native_r1}
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
evidence="$experiment_dir/raw/$run_id/$gate_id"; container_evidence="/evidence/$gate_id"
[[ ! -e "$evidence" ]] || exit 2
for target in "$runner" "$pg"; do [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2; done
mkdir -p "$evidence"
index=0; executed=0
for mode in before_dispatch during_draft after_draft_commit cancel_remaining complete_draft renderer_kill; do
  index=$((index+1))
  if [[ -n "${TIP054_NATIVE_ONLY_MODE:-}" && "$mode" != "$TIP054_NATIVE_ONLY_MODE" ]]; then continue; fi
  executed=$((executed+1))
  database="rtr_tip054_n_${gate_id}_i${index}"; engine="rtr_tip054_ne_${gate_id}_i${index}"
  case_dir="$evidence/$mode"; container_case="$container_evidence/$mode"; mkdir -p "$case_dir"
  docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$case_dir/databases.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$case_dir/databases.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$case_dir/databases.txt"
  runtime="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  owner="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  engine_dsn="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
  base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src TMPDIR=/tmp APP_ENV=test
    POSTGRES_DSN="$runtime" MIGRATION_DSN="$owner" INTEGRATION_DATABASE_DSN="$runtime" ACTION_WORKFLOW_DSN="$engine_dsn" ACTION_EXECUTOR_ENABLED=true
    REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
  exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
  exec_runner /app/.venv/bin/alembic upgrade head > "$case_dir/migrate.stdout.txt" 2> "$case_dir/migrate.stderr.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only'; REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$case_dir/databases.txt"
  exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_case/source-before.json" > "$case_dir/source-before.stdout.txt"
  exec_runner /app/.venv/bin/python /work/native_probe.py seed "$container_case" > "$case_dir/seed.stdout.txt" 2> "$case_dir/seed.stderr.txt"
  set +e
  exec_runner TIP054_NATIVE_PAUSE="$mode" /app/.venv/bin/python /work/native_probe.py supervise "$container_case" > "$case_dir/supervisor.stdout.txt" 2> "$case_dir/supervisor.stderr.txt"
  code=$?
  set -e
  printf '{"returncode":%d,"mode":"%s"}\n' "$code" "$mode" > "$case_dir/returncode.json"
  exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_case/source-after.json" > "$case_dir/source-after.stdout.txt"
  [[ "$code" == 0 ]] || exit "$code"
done
[[ "$executed" -gt 0 ]]
echo "NATIVE_PROCESS_GATES_PASS scenarios=$executed actualSDKproductworker selected_mode=${TIP054_NATIVE_ONLY_MODE:-all}"
