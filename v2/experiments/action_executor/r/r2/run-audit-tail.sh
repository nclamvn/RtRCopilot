#!/usr/bin/env bash
# NEW-only driver; original gate boundary/capacity guard/profiler/load are unchanged.
set -euo pipefail
r_dir=$(cd "$(dirname "$0")/.." && pwd)
experiment_dir=$(cd "$r_dir/.." && pwd)
run_id=${TIP054_FULL_RUN_ID:?explicit owned fixture required}
gate_id=${1:?new unique gate id required}
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
runner="$run_id-runner"; pg="$run_id-pg"
export TIP054_REAL_DOCKER=$(command -v docker)
export TIP054_CAPACITY_TRACE="$experiment_dir/raw/$run_id/r_bind_$gate_id/capacity-create.jsonl"
export PATH="$r_dir/bin:$PATH"
bash "$r_dir/gate-boundary.sh" "$gate_id" begin
evidence="$experiment_dir/raw/$run_id/$gate_id"; output="/evidence/$gate_id"
[[ ! -e "$evidence" ]] || exit 2
mkdir -p "$evidence"
database="rtr_tip054_rl_$gate_id"; engine="rtr_tip054_re_$gate_id"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$evidence/databases.txt"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src TMPDIR=/tmp APP_ENV=test ACTION_EXECUTOR_ENABLED=true
  LIMITS_RATE_RENDER_MAX=5000 LIMITS_RATE_DEFAULT_READ_MAX=5000
  POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database" INTEGRATION_DATABASE_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  MIGRATION_DSN="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database" ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
exec_runner /app/.venv/bin/alembic upgrade head > "$evidence/migrate.stdout.txt" 2> "$evidence/migrate.stderr.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only'; REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$evidence/databases.txt"
set +e
exec_runner timeout --signal=TERM --kill-after=10 190 /app/.venv/bin/python /work/r/r2/run_observed.py "$output" > "$evidence/latency.stdout.txt" 2> "$evidence/latency.stderr.txt"
load_code=$?
exec_runner /app/.venv/bin/python /work/r/r2/summarize_audit_tail.py "$output" --verify-chain > "$evidence/audit-tail.stdout.txt" 2> "$evidence/audit-tail.stderr.txt"
metric_code=$?
set -e
printf '{"latency_returncode":%d,"metric_chain_returncode":%d,"observer":"extended_on"}\n' "$load_code" "$metric_code" > "$evidence/returncodes.json"
child_code=$load_code
if [[ "$metric_code" != 0 ]]; then child_code=$metric_code; fi
bash "$r_dir/gate-boundary.sh" "$gate_id" end "$child_code"
exit "$child_code"
