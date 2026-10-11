#!/usr/bin/env bash
# Main only: six pure controls, one no-SQL diagnostic, one owned positive seed.
set -euo pipefail
r20_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$r20_dir/../../../.." && pwd)
cd "$repo"
[[ "${R20_MAIN_ADMISSION:-}" == bootstrap ]] || exit 2
binding="$r20_dir/${1:?source-binding-eN.json required}"
[[ "$1" =~ ^source-binding-e[1-9][0-9]*\.json$ ]] || exit 2
python3 -B "$r20_dir/env_contract.py" source "$binding"
python3 -B "$r20_dir/env_contract.py" review "${R20_SOURCE_REVIEW:?review path}" "${R20_SOURCE_REVIEW_SHA256:?review SHA}"
fixture=tip054-4b-full-20261007-r5qa1
runner="$fixture-runner"
pg="$fixture-pg"
database=rtr_tip054_r20_local_e1
evidence="$repo/v2/experiments/action_executor/raw/$fixture/r19/r20_bootstrap_e1"
container_evidence=/evidence/r19/r20_bootstrap_e1
[[ ! -e "$evidence" ]] || exit 2
python_path=$(command -v python3)
base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r20
  APP_ENV=test ACTION_EXECUTOR_ENABLED=false
  POSTGRES_DSN="${POSTGRES_DSN-}"
  INTEGRATION_DATABASE_DSN="${INTEGRATION_DATABASE_DSN-}"
  RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local OPENAI_API_KEY= ANTHROPIC_API_KEY=
  LIMITS_RATE_RENDER_MAX=30 LIMITS_RATE_DEFAULT_READ_MAX=120 LIMITS_RATE_WINDOW_SECONDS=60
  ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS=0.9
  TMPDIR="$container_evidence/tmp" SOT_STAGING_ROOT="$container_evidence/tmp/staging"
  RESEARCH_STAGING_ROOT="$container_evidence/tmp/research"
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic)
# Pure admission BEFORE all effects-bearing runtime spawn, fixture calls or CREATE.
env -i "${base_env[@]}" "$python_path" -B "$r20_dir/env_contract.py" environment > /dev/null
mkdir -p "$evidence/tmp" "$evidence/pytest-tmp"
cp "$binding" "$evidence/binding.json"
cp "$r20_dir/manifest.json" "$evidence/manifest.json"
printf '%s %s\n' "$R20_SOURCE_REVIEW" "$R20_SOURCE_REVIEW_SHA256" > "$evidence/review-pin.txt"
docker_path=$(command -v docker)
[[ "$docker_path" == /* && -x "$docker_path" ]] || exit 2
active_pid=''
active_label=''
owned_database=''
uncertain_create=''
exec_runner() { "$docker_path" exec -w /workspace/v2/apps/backend "$runner" env -i "${base_env[@]}" "$@"; }
pg_sql() { "$docker_path" exec "$pg" env PGCONNECT_TIMEOUT=5 PGOPTIONS='-c statement_timeout=10000 -c lock_timeout=5000' psql -X "$@"; }
source_check() { python3 -B "$r20_dir/env_contract.py" source "$binding"; }
fixture_check() { python3 -B "$r20_dir/env_contract.py" fixture "$repo/v2/experiments/action_executor/r12/preflight_e1/fixture-preflight.json" "$docker_path"; }
absence() {
  [[ "$database" == rtr_tip054_r20_local_e1 ]] || return 2
  pg_sql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_database WHERE datname='$database';"
}
stop_active() {
  [[ -n "$active_pid" ]] || return 0
  exec_runner /app/.venv/bin/python /work/r19/bounded.py stop "$container_evidence" "$active_label" \
    > "$evidence/$active_label-stop.stdout.txt" 2> "$evidence/$active_label-stop.stderr.txt" || return 1
  local deadline=$((SECONDS + 12))
  while kill -0 "$active_pid" 2>/dev/null && (( SECONDS < deadline )); do sleep .05; done
  if kill -0 "$active_pid" 2>/dev/null; then return 1; fi
  wait "$active_pid" || true
  python3 -B "$r20_dir/env_contract.py" drained "$evidence/$active_label.process.json" \
    > "$evidence/$active_label-stop-proof.txt" || return 1
  active_pid=''
  active_label=''
}
cleanup() {
  [[ -z "$active_pid" ]] || return 1
  [[ -z "$uncertain_create" ]] || return 1
  if [[ -n "$owned_database" ]]; then
    [[ "$owned_database" == rtr_tip054_r20_local_e1 ]] || return 2
    pg_sql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
      -c "DROP DATABASE \"$owned_database\";" > "$evidence/drop.stdout.txt" 2> "$evidence/drop.stderr.txt" || return 1
    owned_database=''
    [[ $(absence) == 0 ]] || return 1
    printf 'owned_drop 0\n' >> "$evidence/returncodes.txt"
  fi
  return 0
}
capacity() {
  df -k / > "$evidence/$1-host-disk.txt" || return 1
  "$docker_path" exec "$pg" df -k /var/lib/postgresql/data > "$evidence/$1-pg-disk.txt" || return 1
  [[ $(awk 'NR==2 {print $4}' "$evidence/$1-host-disk.txt") -ge 20971520 ]] || return 1
  [[ $(awk 'NR==2 {print $4}' "$evidence/$1-pg-disk.txt") -ge 524288 ]] || return 1
}
finish() {
  local code=$? count
  trap - EXIT INT TERM HUP
  if ! stop_active; then code=1; printf 'DRAIN_FAILED database_retained\n' >> "$evidence/returncodes.txt"
  elif ! cleanup; then code=1; printf 'OWNERSHIP_OR_CLEANUP_FAILED\n' >> "$evidence/returncodes.txt"; fi
  source_check > "$evidence/source-after.txt" || code=1
  fixture_check > "$evidence/fixture-after.txt" 2> "$evidence/fixture-after.stderr.txt" || code=1
  count=$(absence) || code=1
  printf 'final_absence %s\n' "${count:-unknown}" >> "$evidence/database-closure.txt"
  [[ "${count:-unknown}" == 0 ]] || code=1
  capacity final || code=1
  python3 -B "$r20_dir/env_contract.py" cap "$evidence" > "$evidence/cap-after.txt" || code=1
  printf 'bootstrap exit %d\n' "$code" >> "$evidence/returncodes.txt"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
source_check > "$evidence/source-before.txt"
fixture_check > "$evidence/fixture-before.txt"
[[ $(absence) == 0 ]] || exit 2
checked() {
  local label=$1 code=0
  shift
  [[ -z "$active_pid" ]] || return 1
  source_check > "$evidence/$label-source-before.txt" || return 1
  python3 -B "$r20_dir/env_contract.py" cap "$evidence" > "$evidence/$label-cap-before.txt" || return 1
  active_label="$label"
  exec_runner /app/.venv/bin/python /work/r19/bounded.py run "$container_evidence" pre "$label" "$@" \
    > "$evidence/$label-supervisor.stdout.txt" 2> "$evidence/$label-supervisor.stderr.txt" &
  active_pid=$!
  wait "$active_pid" || code=$?
  if kill -0 "$active_pid" 2>/dev/null; then return 1; fi
  printf '%s %d\n' "$label" "$code" >> "$evidence/returncodes.txt"
  python3 -B "$r20_dir/env_contract.py" child "$evidence/$label.process.json" "$code" \
    > "$evidence/$label-child-proof.txt" || return 1
  active_pid=''
  active_label=''
  source_check > "$evidence/$label-source-after.txt" || return 1
  python3 -B "$r20_dir/env_contract.py" cap "$evidence" > "$evidence/$label-cap-after.txt" || return 1
  return "$code"
}
select_group() {
  selected=()
  while IFS= read -r line; do selected+=("$line"); done < <(python3 -B "$r20_dir/env_contract.py" selectors "$1")
  [[ "${#selected[@]}" == "$2" ]]
}
common=(-c /workspace/v2/apps/backend/pyproject.toml -q -rs -p no:cacheprovider)
files=(/work/r20/env_contract.py /work/r20/test_r20_offline.py /work/r20/test_r20_bootstrap.py)
checked syntax /app/.venv/bin/python -c 'import sys; from pathlib import Path; [compile(Path(p).read_text(),p,"exec") for p in sys.argv[1:]]' "${files[@]}"
checked ruff /app/.venv/bin/ruff check --no-cache "${files[@]}"
checked format /app/.venv/bin/ruff format --check --no-cache "${files[@]}"
select_group all 8
checked collection /app/.venv/bin/python -m pytest "${common[@]}" --collect-only "${selected[@]}"
checked inventory /app/.venv/bin/python /work/r20/env_contract.py collection "$container_evidence/collection.stdout.txt"
for group in offline negative; do
  count=6; [[ "$group" != negative ]] || count=1
  select_group "$group" "$count"
  checked "$group" /app/.venv/bin/python -m pytest "${common[@]}" "--basetemp=$container_evidence/pytest-tmp/$group" "--junitxml=$container_evidence/$group.xml" "${selected[@]}"
  checked "$group-xml" /app/.venv/bin/python /work/r20/env_contract.py xml "$container_evidence/$group.xml" "$group"
done
create_domain() {
  [[ -z "$active_pid" && -z "$owned_database" && $(absence) == 0 ]] || return 2
  capacity create || return 1
  uncertain_create="$database"
  pg_sql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"$database\";" > "$evidence/create.stdout.txt" 2> "$evidence/create.stderr.txt" || return 1
  owned_database="$database"
  uncertain_create=''
}
create_domain
checked migration /usr/bin/env MIGRATION_DSN=postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r20_local_e1 /app/.venv/bin/alembic upgrade 0019_action_executor
pg_sql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 \
  -c "REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" > "$evidence/grants.txt"
select_group positive 1
checked positive /app/.venv/bin/python -m pytest "${common[@]}" "--basetemp=$container_evidence/pytest-tmp/positive" "--junitxml=$container_evidence/positive.xml" "${selected[@]}"
checked positive-xml /app/.venv/bin/python /work/r20/env_contract.py xml "$container_evidence/positive.xml" positive
