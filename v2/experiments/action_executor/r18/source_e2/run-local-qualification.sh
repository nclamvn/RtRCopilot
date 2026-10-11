#!/usr/bin/env bash
# Main admits source-reviewed pre/SQL only. No HTTP or native stage exists.
set -euo pipefail
r18_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$r18_dir/../../../.." && pwd)
cd "$repo"
stage=${1:?pre or sql required}
epoch=${2:?fresh stage_eN required}
binding_name=${3:?source-binding-eN.json required}
[[ "$stage" == pre || "$stage" == sql ]] || exit 2
[[ "${R18_MAIN_ADMISSION:-}" == "$stage" ]] || exit 2
[[ "$epoch" =~ ^${stage}_e[1-9][0-9]*$ ]] || exit 2
[[ "$binding_name" =~ ^source-binding-e[1-9][0-9]*\.json$ ]] || exit 2
binding="$r18_dir/$binding_name"
fixture=tip054-4b-full-20261007-r5qa1
runner="$fixture-runner"
pg="$fixture-pg"
evidence="$repo/v2/experiments/action_executor/raw/$fixture/r18/$epoch"
container_evidence="/evidence/r18/$epoch"
[[ ! -e "$evidence" ]] || { echo 'Fresh evidence epoch required'; exit 2; }
python3 -B "$r18_dir/gate.py" stage "$stage" "$epoch"
python3 -B "$r18_dir/gate.py" source "$binding"
python3 -B "$r18_dir/gate.py" review "${R18_SOURCE_REVIEW:?accepted source review path}" "${R18_SOURCE_REVIEW_SHA256:?review pin}"
if [[ "$stage" == sql ]]; then
  pre_epoch=${4:?same-binding passing pre_eN required}
  [[ "$pre_epoch" =~ ^pre_e[1-9][0-9]*$ ]] || exit 2
  python3 -B "$r18_dir/gate.py" prior "$repo/v2/experiments/action_executor/raw/$fixture/r18/$pre_epoch" "$binding"
fi
mkdir -p "$evidence/tmp" "$evidence/pytest-tmp"
cp "$binding" "$evidence/binding.json"
cp "$r18_dir/qualification.json" "$evidence/qualification.json"
if [[ "$stage" == sql ]]; then
  cp "$repo/v2/experiments/action_executor/raw/$fixture/r18/$pre_epoch/collection.stdout.txt" "$evidence/collection.stdout.txt"
fi
owned_database=''
active_pid=''
active_label=''
docker_path=$(command -v docker)
[[ "$docker_path" == /* && -x "$docker_path" ]] || exit 2
base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin
  TMPDIR="$container_evidence/tmp" PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r12:/work/r9:/work/r15:/work/r18
  APP_ENV=test ACTION_EXECUTOR_ENABLED=false
  POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r18_local_e1
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only
  S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { "$docker_path" exec -w /workspace/v2/apps/backend "$runner" env -i "${base_env[@]}" "$@"; }
check_source() { python3 -B "$r18_dir/gate.py" source "$binding"; }
fixture_check() {
  python3 -B "$r18_dir/gate.py" fixture "$repo/v2/experiments/action_executor/r12/preflight_e1/fixture-preflight.json" "$docker_path"
}
absence() {
  [[ "$1" == rtr_tip054_r15_local_e1 || "$1" == rtr_tip054_r18_local_e1 ]] || return 2
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_database WHERE datname='$1';"
}
stop_active() {
  [[ -n "$active_pid" ]] || return 0
  exec_runner /app/.venv/bin/python /work/r18/bounded.py stop "$container_evidence" "$active_label" \
    > "$evidence/$active_label-stop.stdout.txt" 2> "$evidence/$active_label-stop.stderr.txt"
  # Join exec only AFTER asking the in-container owner to TERM/KILL/drain.
  wait "$active_pid" || true
  python3 -B - "$evidence/$active_label.process.json" <<'PY'
import json
import sys
packet = json.load(open(sys.argv[1]))
assert packet["group_drained"] is True
PY
  active_pid=''
  active_label=''
}
cleanup() {
  [[ -n "$owned_database" ]] || return 0
  [[ -z "$active_pid" ]] || return 2
  local target="$owned_database" code=0 count
  [[ "$target" == rtr_tip054_r15_local_e1 || "$target" == rtr_tip054_r18_local_e1 ]] || return 2
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE \"$target\";" > "$evidence/$target-cleanup.stdout.txt" \
    2> "$evidence/$target-cleanup.stderr.txt" || code=$?
  printf 'database_cleanup %s %d\n' "$target" "$code" >> "$evidence/returncodes.txt"
  [[ "$code" == 0 ]] || return "$code"
  owned_database=''
  count=$(absence "$target")
  printf '%s absence_after_cleanup %s\n' "$target" "$count" >> "$evidence/database-closure.txt"
  [[ "$count" == 0 ]]
}
finish() {
  local code=$? count
  trap - EXIT INT TERM HUP
  # If ownership cannot be drained/proved, retain DB rather than drop under work.
  if ! stop_active; then
    printf 'owned_process_drain FAILED; database retained\n' >> "$evidence/returncodes.txt"
    code=1
  elif ! cleanup; then
    code=1
  fi
  check_source > "$evidence/source-after.txt" || code=1
  fixture_check > "$evidence/fixture-after.txt" 2> "$evidence/fixture-after.stderr.txt" || code=1
  for target in rtr_tip054_r15_local_e1 rtr_tip054_r18_local_e1; do
    count=$(absence "$target") || code=1
    printf '%s final_absence %s\n' "$target" "${count:-unknown}" >> "$evidence/database-closure.txt"
    [[ "${count:-unknown}" == 0 ]] || code=1
  done
  python3 -B "$r18_dir/gate.py" cap "$evidence" "$stage" > "$evidence/cap-after.txt" || code=1
  printf 'stage %s exit %d\n' "$stage" "$code" >> "$evidence/returncodes.txt"
  exit "$code"
}
# Cleanup and interruption handlers exist before fixture/CREATE admission.
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
check_source > "$evidence/source-before.txt"
fixture_check > "$evidence/fixture-before.txt" 2> "$evidence/fixture-before.stderr.txt"
for target in rtr_tip054_r15_local_e1 rtr_tip054_r18_local_e1; do
  count=$(absence "$target")
  printf '%s initial_absence %s\n' "$target" "$count" >> "$evidence/database-closure.txt"
  [[ "$count" == 0 ]] || exit 2
done
printf 'base_executor OFF; domain fixtures use isolated enabled settings overrides; no worker/native/provider\n' > "$evidence/executor-scope.txt"
checked() {
  local label=$1 code=0
  shift
  check_source > "$evidence/source-$label-before.txt"
  python3 -B "$r18_dir/gate.py" cap "$evidence" "$stage" > "$evidence/cap-$label-before.txt"
  active_label="$label"
  exec_runner /app/.venv/bin/python /work/r18/bounded.py run "$container_evidence" "$stage" "$label" "$@" \
    > "$evidence/$label-supervisor.stdout.txt" 2> "$evidence/$label-supervisor.stderr.txt" &
  active_pid=$!
  wait "$active_pid" || code=$?
  # An interrupted wait may return before exec. Leave ownership for EXIT drain.
  if kill -0 "$active_pid" 2>/dev/null; then return "${code:-1}"; fi
  printf '%s %d\n' "$label" "$code" >> "$evidence/returncodes.txt"
  # Exec may have crashed while its child survives. Never clear ownership on
  # client completion alone; missing/invalid records route through EXIT drain.
  python3 -B "$r18_dir/gate.py" child "$evidence/$label.process.json" "$code" \
    > "$evidence/$label-child-admission.txt" || return 1
  active_pid=''
  active_label=''
  check_source > "$evidence/source-$label-after.txt"
  python3 -B "$r18_dir/gate.py" cap "$evidence" "$stage" > "$evidence/cap-$label-after.txt"
  return "$code"
}
read_group() {
  selected=()
  while IFS= read -r line; do selected+=("$line"); done < <(python3 -B "$r18_dir/gate.py" selectors "$1")
  [[ "${#selected[@]}" == "$2" ]]
}
pytest_common=(-c /workspace/v2/apps/backend/pyproject.toml -q -rs -p no:cacheprovider -o asyncio_default_test_loop_scope=session)
files=(/work/r18/gate.py /work/r18/bounded.py /work/r18/test_r18_offline.py)
if [[ "$stage" == pre ]]; then
  checked syntax /app/.venv/bin/python -c 'import sys; from pathlib import Path; [compile(Path(p).read_text(),p,"exec") for p in sys.argv[1:]]; print("SYNTAX_3_PASS")' "${files[@]}"
  checked pins /app/.venv/bin/python -c 'from importlib.metadata import version; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; assert version("pytest")=="8.4.1"; print("PINS_PASS")'
  checked ruff /app/.venv/bin/ruff check --no-cache "${files[@]}"
  checked format /app/.venv/bin/ruff format --check --no-cache "${files[@]}"
  read_group all 52
  checked collection /app/.venv/bin/python -m pytest "${pytest_common[@]}" --collect-only "${selected[@]}"
  checked inventory /app/.venv/bin/python /work/r18/gate.py collection "$container_evidence/collection.stdout.txt"
  read_group pure 17
  checked pure /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/pure" "--junitxml=$container_evidence/pure.xml" "${selected[@]}"
  read_group offline 6
  checked offline /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/offline" "--junitxml=$container_evidence/offline.xml" "${selected[@]}"
  checked pure-xml /app/.venv/bin/python /work/r18/gate.py junit "$container_evidence/pure.xml" pure
  checked offline-xml /app/.venv/bin/python /work/r18/gate.py junit "$container_evidence/offline.xml" offline
  exit 0
fi
create() {
  local target=$1 label=$2 existing host_kib pg_kib
  [[ -z "$owned_database" && -z "$active_pid" ]] || exit 2
  [[ "$target" == rtr_tip054_r15_local_e1 || "$target" == rtr_tip054_r18_local_e1 ]] || exit 2
  df -k / > "$evidence/$label-host-disk.txt"
  host_kib=$(awk 'NR==2 {print $4}' "$evidence/$label-host-disk.txt")
  "$docker_path" exec "$pg" df -k /var/lib/postgresql/data > "$evidence/$label-pg-disk.txt"
  pg_kib=$(awk 'NR==2 {print $4}' "$evidence/$label-pg-disk.txt")
  [[ "$host_kib" =~ ^[0-9]+$ && "$host_kib" -ge 20971520 ]] || exit 66
  [[ "$pg_kib" =~ ^[0-9]+$ && "$pg_kib" -ge 524288 ]] || exit 66
  existing=$(absence "$target")
  printf '%s existing=%s host_kib=%s pg_kib=%s\n' "$target" "$existing" "$host_kib" "$pg_kib" >> "$evidence/database-admission.txt"
  [[ "$existing" == 0 ]] || exit 2
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"$target\";" > "$evidence/$label-create.stdout.txt" 2> "$evidence/$label-create.stderr.txt"
  owned_database="$target"
  current_dsn="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$target"
  owner_dsn="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$target"
  checked "$label-migration" /usr/bin/env POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" /app/.venv/bin/alembic upgrade 0019_action_executor
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d "$target" -v ON_ERROR_STOP=1 \
    -c "REVOKE CONNECT ON DATABASE \"$target\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$target\" TO rtr_app;" > "$evidence/$label-permissions.txt"
}
create rtr_tip054_r15_local_e1 old
read_group old_sql 17
checked old-sql /usr/bin/env POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" INTEGRATION_DATABASE_DSN="$current_dsn" /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/old-sql" "--junitxml=$container_evidence/old-sql.xml" "${selected[@]}"
checked old-xml /app/.venv/bin/python /work/r18/gate.py junit "$container_evidence/old-sql.xml" old_sql
cleanup
create rtr_tip054_r18_local_e1 new
read_group new_sql 12
checked new-sql /usr/bin/env POSTGRES_DSN="$current_dsn" MIGRATION_DSN="$owner_dsn" INTEGRATION_DATABASE_DSN="$current_dsn" /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/new-sql" "--junitxml=$container_evidence/new-sql.xml" "${selected[@]}"
checked new-xml /app/.venv/bin/python /work/r18/gate.py junit "$container_evidence/new-sql.xml" new_sql
cleanup
