#!/usr/bin/env bash
# Non-destructive owned-fixture gates. Per-module fresh domain AND engine DBs.
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r1}
runner="$run_id-runner"; pg="$run_id-pg"; redis="$run_id-redis"
gate_id=${TIP054_GATE_ID:-gates_$(date +%Y%m%d_%H%M%S)}
[[ "$gate_id" =~ ^[a-z0-9_]{1,40}$ ]] || exit 2
evidence="$experiment_dir/raw/$run_id/$gate_id"
[[ ! -e "$evidence" ]] || { echo 'Choose new gate id'; exit 2; }
for target in "$runner" "$pg" "$redis"; do [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2; done
mkdir -p "$evidence"
container_evidence="/evidence/$gate_id"
base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src APP_ENV=test
  POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_executor_verify
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base_env[@]}" "$@"; }
exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/source-before.json"
set +e
unit_ran=true
if [[ -n "${TIP054_ONLY_MODULE:-}" ]]; then unit_code=0; unit_ran=false
else
  exec_runner /app/.venv/bin/python -m pytest -q -rs -p no:cacheprovider --ignore-glob='*integration.py' --ignore=tests/test_action_execution_adversarial.py "--junitxml=$container_evidence/unit.xml" tests > "$evidence/unit.stdout.txt" 2> "$evidence/unit.stderr.txt"
  unit_code=$?
fi
set -e
index=0; integration_code=0
targets=("$experiment_dir"/../../apps/backend/tests/*integration.py)
if [[ -f "$experiment_dir/../../apps/backend/tests/test_action_execution_adversarial.py" ]]; then targets+=("$experiment_dir/../../apps/backend/tests/test_action_execution_adversarial.py"); fi
if [[ -n "${TIP054_ONLY_MODULE:-}" ]]; then
  [[ "$TIP054_ONLY_MODULE" =~ ^test_[a-z0-9_]+\.py$ ]] || exit 2
  targets=("$experiment_dir/../../apps/backend/tests/$TIP054_ONLY_MODULE")
fi
for test_file in "${targets[@]}"; do
  index=$((index+1)); database="rtr_tip054_exe_${gate_id}_i${index}"; engine="rtr_tip054_eng_${gate_id}_i${index}"
  [[ ${#database} -le 63 && ${#engine} -le 63 ]] || exit 2
  docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$evidence/database-$index.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$evidence/database-$index.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$evidence/database-$index.txt"
  owner="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  runtime="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  engine_dsn="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
  exec_runner MIGRATION_DSN="$owner" POSTGRES_DSN="$runtime" /app/.venv/bin/alembic upgrade head > "$evidence/migrate-$index.stdout.txt" 2> "$evidence/migrate-$index.stderr.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only'; REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$evidence/database-$index.txt"
  docker exec "$redis" redis-cli FLUSHDB > "$evidence/redis-reset-$index.txt"
  test_name=$(basename "$test_file")
  test_target="tests/$test_name"
  if [[ -n "${TIP054_TEST_SELECTOR:-}" ]]; then
    [[ "$TIP054_TEST_SELECTOR" =~ ^test_[a-z0-9_]+$ ]] || exit 2
    test_target="$test_target::$TIP054_TEST_SELECTOR"
  fi
  echo "Integration $index $test_name domain=$database engine=$engine"
  set +e
  exec_runner POSTGRES_DSN="$runtime" MIGRATION_DSN="$owner" INTEGRATION_DATABASE_DSN="$runtime" DBOS_SYSTEM_DATABASE_URL="$engine_dsn" ACTION_WORKFLOW_DSN="$engine_dsn" \
    /app/.venv/bin/python -m pytest -q -rs -p no:cacheprovider -o asyncio_default_test_loop_scope=session "--junitxml=$container_evidence/integration-$index.xml" "$test_target" > "$evidence/integration-$index.stdout.txt" 2> "$evidence/integration-$index.stderr.txt"
  code=$?
  set -e
  if [[ "$code" != 0 ]]; then integration_code=1; fi
done
set +e
exec_runner /app/.venv/bin/ruff check --no-cache src tests > "$evidence/ruff.stdout.txt" 2> "$evidence/ruff.stderr.txt"; ruff_code=$?
exec_runner /app/.venv/bin/mypy --cache-dir=/tmp/tip054-exe-mypy > "$evidence/mypy.stdout.txt" 2> "$evidence/mypy.stderr.txt"; mypy_code=$?
exec_runner /app/.venv/bin/python -c 'import rtr_copilot.api.main,rtr_copilot.worker.main; from importlib.metadata import version; assert version("dbos")=="3.2.0"; assert version("sqlalchemy")=="2.0.43"; assert version("psycopg")=="3.2.9"; print("APP_IMPORT_EXACT_PINS_PASS")' > "$evidence/import.stdout.txt" 2> "$evidence/import.stderr.txt"; import_code=$?
set -e
exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/source-after.json"
printf '{"unit_ran":%s,"unit_returncode":%d,"integration_returncode":%d,"integration_modules":%d,"ruff_returncode":%d,"mypy_returncode":%d,"import_returncode":%d}\n' "$unit_ran" "$unit_code" "$integration_code" "$index" "$ruff_code" "$mypy_code" "$import_code" > "$evidence/returncodes.json"
exec_runner /app/.venv/bin/python /work/summarize_gates.py "$container_evidence" > "$evidence/summary.stdout.txt"
[[ "$unit_code" == 0 && "$integration_code" == 0 && "$ruff_code" == 0 && "$mypy_code" == 0 && "$import_code" == 0 ]]
