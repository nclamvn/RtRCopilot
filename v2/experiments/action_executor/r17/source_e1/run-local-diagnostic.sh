#!/usr/bin/env bash
# Authoring is not admission. Main explicitly admits each retained-fixture phase.
set -euo pipefail
r17_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$r17_dir/../../../.." && pwd)
cd "$repo"
stage=${1:?pre, sql or compare required}
epoch=${2:?fresh stage_eN required}
binding_name=${3:?source-binding-eN.sha256 required}
[[ "$stage" == pre || "$stage" == sql || "$stage" == compare ]] || exit 2
[[ "${R17_MAIN_ADMISSION:-}" == "$stage" ]] || { echo 'Explicit Main stage admission required'; exit 2; }
[[ "$epoch" =~ ^${stage}_e[1-9][0-9]*$ ]] || exit 2
[[ "$binding_name" =~ ^source-binding-e[1-9][0-9]*\.sha256$ ]] || exit 2
binding="$r17_dir/$binding_name"
fixture=tip054-4b-full-20261007-r5qa1
runner="$fixture-runner"
pg="$fixture-pg"
evidence="$repo/v2/experiments/action_executor/raw/$fixture/r17/$epoch"
[[ ! -e "$evidence" ]] || { echo 'Fresh evidence epoch required'; exit 2; }
if [[ "$stage" == compare ]]; then
  [[ "$epoch" == compare_e1 ]] || exit 2
  pre_epoch=${4:?Main-selected pre_eN required}
  sql_epoch=${5:?Main-selected sql_eN required}
  [[ "$pre_epoch" =~ ^pre_e[1-9][0-9]*$ && "$sql_epoch" =~ ^sql_e[1-9][0-9]*$ ]] || exit 2
  python3 "$r17_dir/gate.py" prior "$repo/v2/experiments/action_executor/raw/$fixture/r17/$pre_epoch" pre "$binding"
  python3 "$r17_dir/gate.py" prior "$repo/v2/experiments/action_executor/raw/$fixture/r17/$sql_epoch" sql "$binding"
  python3 "$r17_dir/gate.py" review "${R17_SOURCE_REVIEW:?accepted independent source review path}" "${R17_SOURCE_REVIEW_SHA256:?review pin required}"
  # The single run cannot be repeated under a new evidence epoch/binding.
  [[ ! -e "$repo/v2/experiments/action_executor/raw/$fixture/r17/compare_e1" ]] || exit 2
fi
mkdir -p "$evidence/tmp" "$evidence/pytest-tmp"
cp "$binding" "$evidence/binding.sha256"
container_evidence="/evidence/r17/$epoch"
owned_database=''
check_source() { shasum -a 256 -c "$binding"; }
absence() {
  docker exec "$pg" psql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_database WHERE datname='$1';"
}
cleanup() {
  [[ -n "$owned_database" ]] || return 0
  local target="$owned_database" cleanup_code=0
  [[ "$target" == rtr_tip054_r15_local_e1 || "$target" == rtr_tip054_r17_local_e1 ]] || return 2
  docker exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE \"$target\";" \
    > "$evidence/$target-cleanup.stdout.txt" 2> "$evidence/$target-cleanup.stderr.txt" || cleanup_code=$?
  printf 'database_cleanup %s %d\n' "$target" "$cleanup_code" >> "$evidence/returncodes.txt"
  [[ "$cleanup_code" == 0 ]] || return "$cleanup_code"
  owned_database=''
  local count
  count=$(absence "$target")
  printf '%s absence_after_cleanup %s\n' "$target" "$count" >> "$evidence/database-closure.txt"
  [[ "$count" == 0 ]]
}
finish() {
  local code=$?
  trap - EXIT
  cleanup || code=1
  check_source > "$evidence/source-after.txt" || code=1
  docker top "$runner" -eo pid,comm > "$evidence/runner-after.txt" || code=1
  awk 'NR>1 && $2!="sh" && $2!="sleep" && $2!="ps" {bad=1} END {exit bad}' "$evidence/runner-after.txt" || code=1
  for target in rtr_tip054_r15_local_e1 rtr_tip054_r17_local_e1; do
    count=$(absence "$target") || code=1
    printf '%s final_absence %s\n' "$target" "${count:-unknown}" >> "$evidence/database-closure.txt"
    [[ "${count:-unknown}" == 0 ]] || code=1
  done
  printf 'stage %s exit %d\n' "$stage" "$code" >> "$evidence/returncodes.txt"
  exit "$code"
}
# Install BEFORE every resource check or CREATE; failure evidence is never overwritten.
trap finish EXIT
check_source > "$evidence/source-before.txt"
expected_ids=(
  cb30f7e2244c78e8b6b6a772d2fb69b4ab5ba1ff92405c6b93517c056c024432
  16f2f9e7a933ab98ba7d5aadf50b000de9c76c6f07b569ac280345cb10cc02b7
  2afbb661c6188631079f27b27ae93822c0614e8619adef6a836d17a6c613f69d
  0ec914b6cf8e95fc1c299ae39b7d4f67b1865409a14939785c9dcc228d87e9d3)
suffixes=(runner pg redis minio)
for index in 0 1 2 3; do
  target="$fixture-${suffixes[$index]}"
  observed=$(docker inspect --format '{{.Id}} {{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}} {{index .Config.Labels "tip054.executor"}}' "$target")
  printf '%s %s\n' "$target" "$observed" >> "$evidence/fixture.txt"
  [[ "$observed" == "${expected_ids[$index]} true false 0 $fixture" ]] || exit 2
done
[[ $(docker network inspect --format '{{.Id}} {{.Internal}}' "$fixture-offline") == '49f99f89841a957ad9bcdc6bb3029ecc4dc1e97870fde8d9ae2d204d8328d550 true' ]] || exit 2
[[ $(docker inspect --format '{{.Config.Image}}' "$runner") == rtr-tip054-local-qa:20261006 ]] || exit 2
docker top "$runner" -eo pid,comm > "$evidence/runner-before.txt"
awk 'NR>1 && $2!="sh" && $2!="sleep" && $2!="ps" {bad=1} END {exit bad}' "$evidence/runner-before.txt"
base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin
  TMPDIR="$container_evidence/tmp" PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r12:/work/r9:/work/r15:/work/r17
  APP_ENV=test ACTION_EXECUTOR_ENABLED=false
  POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r17_local_e1
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only
  S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec -w /workspace/v2/apps/backend "$runner" env -i "${base_env[@]}" "$@"; }
checked() {
  local label=$1 code=0
  shift
  check_source > "$evidence/source-$label-before.txt"
  "$@" > "$evidence/$label.stdout.txt" 2> "$evidence/$label.stderr.txt" || code=$?
  printf '%s %d\n' "$label" "$code" >> "$evidence/returncodes.txt"
  check_source > "$evidence/source-$label-after.txt"
  return "$code"
}
unit=(tests/test_action_status_fusion_unit.py tests/test_action_standard_status_factory_unit.py
  tests/test_action_execution_unit.py::test_default_off_and_v1_immutable
  tests/test_action_execution_unit.py::test_api_timeout_cleans_async_waiter_without_result_thread)
sql=(tests/test_action_status_fusion_integration.py tests/test_action_standard_status_factory_integration.py
  tests/test_action_execution_adversarial.py::test_owner_status_cancel_survive_revoked_source_but_content_does_not
  tests/test_action_execution_adversarial.py::test_sql_budget_deadline_attempts_and_foreign_ownership_are_immutable
  tests/test_action_two_lease_review_integration.py::test_create_two_physical_leases_three_fresh_tx_and_lock_release
  tests/test_action_two_lease_review_integration.py::test_submit_retained_final_reads_concurrent_cancel
  tests/test_action_two_lease_review_integration.py::test_original_final_query_lock_timeout_preserves_commit_no_replay
  tests/test_action_two_lease_review_integration.py::test_real_commit_ack_delivery_fault_blocks_final_and_replay
  /work/r12/test_minimal_observer_builder_integration.py::test_real_r0_admission_and_submit_keep_queries_leases_and_durable_outputs)
offline=(/work/r17/test_r17_offline.py)
new_sql=(/work/r17/test_r17_sql.py)
campaign=(/work/r17/test_r17_campaign.py::test_one_fixed_800_checkout_lifecycle_campaign)
files=(/work/r17/diagnostic.py /work/r17/observer.py /work/r17/gate.py /work/r17/test_r17_offline.py /work/r17/test_r17_sql.py /work/r17/test_r17_campaign.py)
pytest_common=(-q -rs -p no:cacheprovider -o asyncio_default_test_loop_scope=session)
if [[ "$stage" == pre ]]; then
  checked syntax exec_runner /app/.venv/bin/python -c 'import sys; from pathlib import Path; [compile(Path(p).read_text(),p,"exec") for p in sys.argv[1:]]; print("SYNTAX_6_PASS")' "${files[@]}"
  checked pins exec_runner /app/.venv/bin/python -c 'from importlib.metadata import version; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; print("PINS_PASS")'
  checked ruff exec_runner /app/.venv/bin/ruff check --no-cache "${files[@]}"
  checked format exec_runner /app/.venv/bin/ruff format --check --no-cache "${files[@]}"
  checked collection exec_runner /app/.venv/bin/python -m pytest --collect-only -q -p no:cacheprovider -o asyncio_default_test_loop_scope=session "${unit[@]}" "${sql[@]}" "${offline[@]}" "${new_sql[@]}"
  checked campaign-collection exec_runner /app/.venv/bin/python -m pytest --collect-only -q -p no:cacheprovider -o asyncio_default_test_loop_scope=session "${campaign[@]}"
  checked inventory python3 "$r17_dir/gate.py" collection "$repo/v2/experiments/action_executor/raw/$fixture/r15/pre_e1/collection.stdout.txt" "$evidence/collection.stdout.txt" "$evidence/campaign-collection.stdout.txt"
  checked old-unit exec_runner /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/old-unit" "--junitxml=$container_evidence/old-unit.xml" "${unit[@]}"
  checked offline exec_runner /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/offline" "--junitxml=$container_evidence/offline.xml" "${offline[@]}"
  checked xml python3 -c 'import sys; sys.path.insert(0,sys.argv[1]); from gate import junit; junit(sys.argv[2],16); junit(sys.argv[3],8); print("24_ZERO_SKIP_PASS")' "$r17_dir" "$evidence/old-unit.xml" "$evidence/offline.xml"
  exit 0
fi
create() {
  local database=$1 label=$2 existing host_free_kib pg_free_kib
  [[ -z "$owned_database" ]] || exit 2
  [[ "$database" == rtr_tip054_r15_local_e1 || "$database" == rtr_tip054_r17_local_e1 ]] || exit 2
  df -k / > "$evidence/$label-host-disk.txt"
  host_free_kib=$(awk 'NR==2 {print $4}' "$evidence/$label-host-disk.txt")
  [[ "$host_free_kib" =~ ^[0-9]+$ && "$host_free_kib" -ge 20971520 ]] || exit 66
  docker exec "$pg" df -k /var/lib/postgresql/data > "$evidence/$label-pg-disk.txt"
  pg_free_kib=$(awk 'NR==2 {print $4}' "$evidence/$label-pg-disk.txt")
  [[ "$pg_free_kib" =~ ^[0-9]+$ && "$pg_free_kib" -ge 524288 ]] || exit 66
  existing=$(absence "$database")
  printf '%s existing=%s host_kib=%s pg_kib=%s\n' "$database" "$existing" "$host_free_kib" "$pg_free_kib" >> "$evidence/database-admission.txt"
  [[ "$existing" == 0 ]] || exit 2
  docker exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"$database\";" > "$evidence/$label-create.txt"
  owned_database="$database"
  current_dsn="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  owner_dsn="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
  checked "$label-migration" exec_runner POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" /app/.venv/bin/alembic upgrade 0019_action_executor
  docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 \
    -c "REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" > "$evidence/$label-permissions.txt"
}
if [[ "$stage" == sql ]]; then
  create rtr_tip054_r15_local_e1 old
  checked old-sql exec_runner POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" INTEGRATION_DATABASE_DSN="$current_dsn" /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/old-sql" "--junitxml=$container_evidence/old-sql.xml" "${sql[@]}"
  checked old-xml python3 "$r17_dir/gate.py" junit "$evidence/old-sql.xml" 17
  cleanup
  create rtr_tip054_r17_local_e1 r17
  checked r17-sql exec_runner POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" INTEGRATION_DATABASE_DSN="$current_dsn" /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/r17-sql" "--junitxml=$container_evidence/r17-sql.xml" "${new_sql[@]}"
  checked r17-xml python3 "$r17_dir/gate.py" junit "$evidence/r17-sql.xml" 3
else
  create rtr_tip054_r17_local_e1 compare
  checked compare exec_runner POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" INTEGRATION_DATABASE_DSN="$current_dsn" R17_EVIDENCE="$container_evidence" /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/campaign" "--junitxml=$container_evidence/compare.xml" "${campaign[@]}"
  checked reconstruction python3 "$r17_dir/diagnostic.py" "$evidence"
  checked compare-xml python3 "$r17_dir/gate.py" junit "$evidence/compare.xml" 1
fi
