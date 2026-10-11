#!/usr/bin/env bash
# R14 only: exact fixture, finite selection, fresh outputs, no rebuild/native/load.
set -euo pipefail
r14_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$r14_dir/../../../.." && pwd)
cd "$repo"
stage=${1:?pre or sql required}
epoch=${2:?fresh pre_eN or sql_eN required}
binding_name=${3:-candidate-source-e1.sha256}
[[ "$stage" == pre || "$stage" == sql ]] || exit 2
[[ "$epoch" =~ ^${stage}_e[1-9][0-9]*$ ]] || exit 2
[[ "$binding_name" =~ ^candidate-source-e[1-9][0-9]*\.sha256$ ]] || exit 2
fixture=tip054-4b-full-20261007-r5qa1
runner="$fixture-runner"
pg="$fixture-pg"
database=rtr_tip054_r14_local_e1
[[ "$database" == rtr_tip054_r14_local_e1 ]] || exit 2
evidence="$repo/v2/experiments/action_executor/raw/$fixture/r14/$epoch"
[[ ! -e "$evidence" ]] || { echo 'Fresh R14 evidence epoch required'; exit 2; }
mkdir -p "$evidence/tmp" "$evidence/pytest-tmp"
container_evidence="/evidence/r14/$epoch"
created=false

check_source() {
  shasum -a 256 -c "$r14_dir/$binding_name"
}
finish() {
  local code=$?
  trap - EXIT
  if [[ "$created" == true ]]; then
    local cleanup_code=0
    docker exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
      -c 'DROP DATABASE "rtr_tip054_r14_local_e1";' \
      > "$evidence/database-cleanup.stdout.txt" 2> "$evidence/database-cleanup.stderr.txt" || cleanup_code=$?
    printf 'database_cleanup %d\n' "$cleanup_code" >> "$evidence/returncodes.txt"
    [[ "$cleanup_code" == 0 ]] || code=1
  fi
  check_source > "$evidence/source-after.txt" || code=1
  printf 'stage %s exit %d\n' "$stage" "$code" >> "$evidence/returncodes.txt"
  exit "$code"
}
# Record preflight failures too; no database exists at this boundary.
trap finish EXIT
check_source > "$evidence/source-before.txt"
expected_ids=(
  cb30f7e2244c78e8b6b6a772d2fb69b4ab5ba1ff92405c6b93517c056c024432
  16f2f9e7a933ab98ba7d5aadf50b000de9c76c6f07b569ac280345cb10cc02b7
  2afbb661c6188631079f27b27ae93822c0614e8619adef6a836d17a6c613f69d
  0ec914b6cf8e95fc1c299ae39b7d4f67b1865409a14939785c9dcc228d87e9d3
)
suffixes=(runner pg redis minio)
for index in 0 1 2 3; do
  target="$fixture-${suffixes[$index]}"
  observed=$(docker inspect --format '{{.Id}} {{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}} {{index .Config.Labels "tip054.executor"}}' "$target")
  printf '%s %s\n' "$target" "$observed" >> "$evidence/fixture.txt"
  [[ "$observed" == "${expected_ids[$index]} true false 0 $fixture" ]] || exit 2
done
[[ $(docker network inspect --format '{{.Id}} {{.Internal}}' "$fixture-offline") == '49f99f89841a957ad9bcdc6bb3029ecc4dc1e97870fde8d9ae2d204d8328d550 true' ]] || exit 2
docker top "$runner" -eo pid,comm > "$evidence/runner-before.txt"
awk 'NR>1 && $2!="sh" && $2!="sleep" && $2!="ps" {bad=1} END {exit bad}' "$evidence/runner-before.txt"

base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin
  TMPDIR="$container_evidence/tmp" PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r12:/work/r9
  APP_ENV=test ACTION_EXECUTOR_ENABLED=false
  POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r14_local_e1
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only
  S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() {
  docker exec -w /workspace/v2/apps/backend "$runner" env -i "${base_env[@]}" "$@"
}
checked() {
  local label=$1
  shift
  check_source > "$evidence/source-$label-before.txt"
  local code=0
  "$@" > "$evidence/$label.stdout.txt" 2> "$evidence/$label.stderr.txt" || code=$?
  printf '%s %d\n' "$label" "$code" >> "$evidence/returncodes.txt"
  check_source > "$evidence/source-$label-after.txt"
  return "$code"
}
unit=(tests/test_action_status_fusion_unit.py
  tests/test_action_execution_unit.py::test_default_off_and_v1_immutable
  tests/test_action_execution_unit.py::test_api_timeout_cleans_async_waiter_without_result_thread)
sql=(tests/test_action_status_fusion_integration.py
  tests/test_action_execution_adversarial.py::test_owner_status_cancel_survive_revoked_source_but_content_does_not
  tests/test_action_execution_adversarial.py::test_sql_budget_deadline_attempts_and_foreign_ownership_are_immutable
  tests/test_action_two_lease_review_integration.py::test_create_two_physical_leases_three_fresh_tx_and_lock_release
  tests/test_action_two_lease_review_integration.py::test_submit_retained_final_reads_concurrent_cancel
  tests/test_action_two_lease_review_integration.py::test_original_final_query_lock_timeout_preserves_commit_no_replay
  tests/test_action_two_lease_review_integration.py::test_real_commit_ack_delivery_fault_blocks_final_and_replay
  /work/r12/test_minimal_observer_builder_integration.py::test_real_r0_admission_and_submit_keep_queries_leases_and_durable_outputs)

if [[ "$stage" == pre ]]; then
  checked syntax exec_runner /app/.venv/bin/python -c 'from pathlib import Path; files=[Path("src/rtr_copilot/actions/execution.py"),Path("tests/test_action_status_fusion_unit.py"),Path("tests/test_action_status_fusion_integration.py")]; [compile(p.read_text(),str(p),"exec") for p in files]; print("SYNTAX_3_PASS")'
  checked pins exec_runner /app/.venv/bin/python -c 'from importlib.metadata import version; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; print("SQLALCHEMY_2_0_43_ASYNCPG_0_30_0")'
  checked ruff exec_runner /app/.venv/bin/ruff check --no-cache src/rtr_copilot/actions/execution.py tests/test_action_status_fusion_unit.py tests/test_action_status_fusion_integration.py
  checked format exec_runner /app/.venv/bin/ruff format --check --no-cache src/rtr_copilot/actions/execution.py tests/test_action_status_fusion_unit.py tests/test_action_status_fusion_integration.py
  checked mypy exec_runner /app/.venv/bin/mypy --cache-dir=/dev/null --follow-imports=silent src/rtr_copilot/actions/execution.py
  checked collection exec_runner /app/.venv/bin/python -m pytest --collect-only -q -p no:cacheprovider -o asyncio_default_test_loop_scope=session "${unit[@]}" "${sql[@]}"
  checked unit exec_runner /app/.venv/bin/python -m pytest -q -rs -p no:cacheprovider -o asyncio_default_test_loop_scope=session \
    "--basetemp=$container_evidence/pytest-tmp" "--junitxml=$container_evidence/unit.xml" "${unit[@]}"
else
  df -k / > "$evidence/host-disk.txt"
  host_free_kib=$(awk 'NR==2 {print $4}' "$evidence/host-disk.txt")
  [[ "$host_free_kib" =~ ^[0-9]+$ && "$host_free_kib" -ge 20971520 ]] || exit 66
  docker exec "$pg" df -k /var/lib/postgresql/data > "$evidence/pg-disk.txt"
  pg_free_kib=$(awk 'NR==2 {print $4}' "$evidence/pg-disk.txt")
  [[ "$pg_free_kib" =~ ^[0-9]+$ && "$pg_free_kib" -ge 524288 ]] || exit 66
  existing=$(docker exec "$pg" psql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_database WHERE datname='rtr_tip054_r14_local_e1';")
  printf 'declared_database=%s existing=%s min_pg_free_kib=524288 actual=%s\n' \
    "$database" "$existing" "$pg_free_kib" > "$evidence/database-admission.txt"
  [[ "$existing" == 0 ]] || exit 2
  docker exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c 'CREATE DATABASE "rtr_tip054_r14_local_e1";' > "$evidence/database-create.txt"
  created=true
  owner=postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r14_local_e1
  checked migration exec_runner MIGRATION_DSN="$owner" /app/.venv/bin/alembic upgrade 0019_action_executor
  docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 \
    -c 'REVOKE CONNECT ON DATABASE "rtr_tip054_r14_local_e1" FROM PUBLIC; GRANT CONNECT ON DATABASE "rtr_tip054_r14_local_e1" TO rtr_app;' \
    > "$evidence/database-permissions.txt"
  checked sql exec_runner MIGRATION_DSN="$owner" \
    INTEGRATION_DATABASE_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r14_local_e1 \
    /app/.venv/bin/python -m pytest -q -rs -p no:cacheprovider -o asyncio_default_test_loop_scope=session \
    "--basetemp=$container_evidence/pytest-tmp" "--junitxml=$container_evidence/sql.xml" "${sql[@]}"
fi
