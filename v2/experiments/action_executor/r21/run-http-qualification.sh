#!/usr/bin/env bash
# Main only. Original OFF child190s including seed; other checked children120s.
set -euo pipefail
r21_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$r21_dir/../../../.." && pwd)
cd "$repo"
stage=${1:?pre or http}
[[ "$stage" == pre || "$stage" == http ]] || exit 2
[[ "${R21_MAIN_ADMISSION:-}" == "$stage" ]] || exit 2
[[ "${2:-}" =~ ^source-binding-e[1-9][0-9]*\.json$ ]] || exit 2
binding="$r21_dir/$2"
python3 -B "$r21_dir/qualification.py" source "$binding"
python3 -B "$r21_dir/qualification.py" review "${R21_SOURCE_REVIEW:?review path}" "${R21_SOURCE_REVIEW_SHA256:?review SHA}"
fixture=tip054-4b-full-20261007-r5qa1
runner="$fixture-runner"
pg="$fixture-pg"
raw="$repo/v2/experiments/action_executor/raw/$fixture/r19"
evidence="$raw/r21_${stage}_e1"
container_evidence="/evidence/r19/r21_${stage}_e1"
marker="$raw/r21-campaign-launch.json"
[[ ! -e "$evidence" ]] || exit 2
[[ "$stage" != http || ! -e "$marker" ]] || exit 2
python_path=$(command -v python3)
base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r21
  APP_ENV=test ACTION_EXECUTOR_ENABLED=false
  POSTGRES_DSN="${POSTGRES_DSN-}" INTEGRATION_DATABASE_DSN="${INTEGRATION_DATABASE_DSN-}"
  RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local OPENAI_API_KEY= ANTHROPIC_API_KEY=
  LIMITS_RATE_RENDER_MAX=30 LIMITS_RATE_DEFAULT_READ_MAX=120 LIMITS_RATE_WINDOW_SECONDS=60
  ACTION_EXECUTOR_OPERATION_TIMEOUT_SECONDS=0.9
  TMPDIR="$container_evidence/tmp" SOT_STAGING_ROOT="$container_evidence/tmp/staging"
  RESEARCH_STAGING_ROOT="$container_evidence/tmp/research"
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic)
load_env=(ACTION_EXECUTOR_ENABLED=true ACTION_WORKFLOW_DSN="${ACTION_WORKFLOW_DSN-}"
  LIMITS_RATE_RENDER_MAX=5000 LIMITS_RATE_DEFAULT_READ_MAX=5000)
# Real stdlib guard validates all caller DSNs and both derived envelopes BEFORE effects.
env -i "${base_env[@]}" "${load_env[@]}" "$python_path" -B "$r21_dir/qualification.py" environment > /dev/null
if [[ "$stage" == http ]]; then
  python3 -B "$r21_dir/qualification.py" prior "$raw/r21_pre_e1" "$binding"
  python3 -B "$r21_dir/qualification.py" review "${R21_PRE_REVIEW:?accepted PRE review}" "${R21_PRE_REVIEW_SHA256:?PRE review SHA}"
fi
mkdir -p "$evidence/tmp" "$evidence/pytest-tmp"
cp "$binding" "$evidence/binding.json"
cp "$r21_dir/contract.json" "$evidence/contract.json"
printf '%s %s\n' "$R21_SOURCE_REVIEW" "$R21_SOURCE_REVIEW_SHA256" > "$evidence/review-pin.txt"
docker_path=$(command -v docker)
[[ "$docker_path" == /* && -x "$docker_path" ]] || exit 2
active_pid=''
active_label=''
owned_databases=()
owned_count=0
uncertain_database=''
exec_runner() { "$docker_path" exec -w /workspace/v2/apps/backend "$runner" env -i "${base_env[@]}" "$@"; }
pg_sql() { "$docker_path" exec "$pg" env PGCONNECT_TIMEOUT=5 PGOPTIONS='-c statement_timeout=10000 -c lock_timeout=5000' psql -X "$@"; }
source_check() { python3 -B "$r21_dir/qualification.py" source "$binding"; }
fixture_check() { python3 -B "$r21_dir/qualification.py" fixture "$repo/v2/experiments/action_executor/r12/preflight_e1/fixture-preflight.json" "$docker_path"; }
absence() {
  [[ "$1" == rtr_tip054_r21_local_e1 || "$1" == rtr_tip054_r21_engine_e1 ]] || return 2
  pg_sql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_database WHERE datname='$1';"
}
stop_active() {
  [[ -n "$active_pid" ]] || return 0
  exec_runner /app/.venv/bin/python /work/r19/bounded.py stop "$container_evidence" "$active_label" \
    > "$evidence/$active_label-stop.stdout.txt" 2> "$evidence/$active_label-stop.stderr.txt" || return 1
  local deadline=$((SECONDS + 12))
  while kill -0 "$active_pid" 2>/dev/null && (( SECONDS < deadline )); do sleep .05; done
  if kill -0 "$active_pid" 2>/dev/null; then return 1; fi
  wait "$active_pid" || true
  python3 -B "$r21_dir/qualification.py" drained "$evidence/$active_label.process.json" \
    > "$evidence/$active_label-stop-proof.txt" || return 1
  active_pid=''
  active_label=''
}
cleanup() {
  [[ -z "$active_pid" && -z "$uncertain_database" ]] || return 1
  local target index
  for ((index=owned_count-1; index>=0; index--)); do
    target=${owned_databases[$index]}
    [[ "$target" == rtr_tip054_r21_local_e1 || "$target" == rtr_tip054_r21_engine_e1 ]] || return 2
    pg_sql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE \"$target\";" \
      > "$evidence/$target-drop.stdout.txt" 2> "$evidence/$target-drop.stderr.txt" || return 1
    unset 'owned_databases[index]'
    owned_count=$((owned_count - 1))
    [[ $(absence "$target") == 0 ]] || return 1
    printf 'owned_drop %s 0\n' "$target" >> "$evidence/returncodes.txt"
  done
  return 0
}
capacity() {
  df -k / > "$evidence/$1-host-disk.txt" || return 1
  "$docker_path" exec "$pg" df -k /var/lib/postgresql/data > "$evidence/$1-pg-disk.txt" || return 1
  [[ $(awk 'NR==2 {print $4}' "$evidence/$1-host-disk.txt") -ge 20971520 ]] || return 1
  [[ $(awk 'NR==2 {print $4}' "$evidence/$1-pg-disk.txt") -ge 524288 ]] || return 1
}
finish() {
  local code=$? count target
  trap - EXIT INT TERM HUP
  if ! stop_active; then code=1; printf 'DRAIN_FAILED databases_retained\n' >> "$evidence/returncodes.txt"
  elif ! cleanup; then code=1; printf 'OWNERSHIP_OR_CLEANUP_FAILED\n' >> "$evidence/returncodes.txt"; fi
  source_check > "$evidence/source-after.txt" || code=1
  fixture_check > "$evidence/fixture-after.txt" 2> "$evidence/fixture-after.stderr.txt" || code=1
  for target in rtr_tip054_r21_local_e1 rtr_tip054_r21_engine_e1; do
    count=$(absence "$target") || code=1
    printf '%s final_absence %s\n' "$target" "${count:-unknown}" >> "$evidence/database-closure.txt"
    [[ "${count:-unknown}" == 0 ]] || code=1
  done
  capacity final || code=1
  python3 -B "$r21_dir/qualification.py" cap "$evidence" "$stage" > "$evidence/cap-after.txt" || code=1
  [[ ! -e "$marker" ]] || printf 'campaign CONSUMED_or_unknown\n' >> "$evidence/returncodes.txt"
  printf 'stage %s exit %d\n' "$stage" "$code" >> "$evidence/returncodes.txt"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
source_check > "$evidence/source-before.txt"
fixture_check > "$evidence/fixture-before.txt"
for target in rtr_tip054_r21_local_e1 rtr_tip054_r21_engine_e1; do
  [[ $(absence "$target") == 0 ]] || exit 2
done
checked() {
  local label=$1 code=0
  shift
  [[ -z "$active_pid" ]] || return 1
  source_check > "$evidence/$label-source-before.txt" || return 1
  python3 -B "$r21_dir/qualification.py" cap "$evidence" "$stage" > "$evidence/$label-cap-before.txt" || return 1
  active_label="$label"
  if [[ "$label" == load ]]; then
    python3 -B "$r21_dir/qualification.py" mark "$marker" "$binding" > "$evidence/launch-marker.txt" || return 1
  fi
  exec_runner /app/.venv/bin/python /work/r19/bounded.py run "$container_evidence" "$stage" "$label" "$@" \
    > "$evidence/$label-supervisor.stdout.txt" 2> "$evidence/$label-supervisor.stderr.txt" &
  active_pid=$!
  wait "$active_pid" || code=$?
  if kill -0 "$active_pid" 2>/dev/null; then return 1; fi
  printf '%s %d\n' "$label" "$code" >> "$evidence/returncodes.txt"
  python3 -B "$r21_dir/qualification.py" child "$evidence/$label.process.json" "$code" > "$evidence/$label-child-proof.txt" || return 1
  active_pid=''
  active_label=''
  source_check > "$evidence/$label-source-after.txt" || return 1
  python3 -B "$r21_dir/qualification.py" cap "$evidence" "$stage" > "$evidence/$label-cap-after.txt" || return 1
  return "$code"
}
select_group() {
  selected=()
  while IFS= read -r line; do selected+=("$line"); done < <(python3 -B "$r21_dir/qualification.py" selectors "$1")
  [[ "${#selected[@]}" == "$2" ]]
}
common=(-c /workspace/v2/apps/backend/pyproject.toml -q -rs -p no:cacheprovider)
files=(/work/r21/qualification.py /work/r21/test_r21_offline.py /work/r21/test_r21_envelope.py)
if [[ "$stage" == pre ]]; then
  checked syntax /app/.venv/bin/python -c 'import sys; from pathlib import Path; [compile(Path(p).read_text(),p,"exec") for p in sys.argv[1:]]' "${files[@]}"
  checked pins /app/.venv/bin/python -c 'from importlib.metadata import version; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; assert version("pytest")=="8.4.1"'
  checked ruff /app/.venv/bin/ruff check --no-cache --config /workspace/v2/apps/backend/pyproject.toml "${files[@]}"
  checked format /app/.venv/bin/ruff format --check --no-cache --config /workspace/v2/apps/backend/pyproject.toml "${files[@]}"
  select_group all 7
  checked collection /app/.venv/bin/python -m pytest "${common[@]}" --collect-only "${selected[@]}"
  checked inventory /app/.venv/bin/python /work/r21/qualification.py collection "$container_evidence/collection.stdout.txt"
  for group in offline envelope; do
    count=6; [[ "$group" != envelope ]] || count=1
    select_group "$group" "$count"
    if [[ "$group" == envelope ]]; then
      checked "$group" /usr/bin/env "${load_env[@]}" /app/.venv/bin/python -m pytest "${common[@]}" "--basetemp=$container_evidence/pytest-tmp/$group" "--junitxml=$container_evidence/$group.xml" "${selected[@]}"
    else
      checked "$group" /app/.venv/bin/python -m pytest "${common[@]}" "--basetemp=$container_evidence/pytest-tmp/$group" "--junitxml=$container_evidence/$group.xml" "${selected[@]}"
    fi
    checked "$group-xml" /app/.venv/bin/python /work/r21/qualification.py xml "$container_evidence/$group.xml" "$group"
  done
  exit 0
fi
create() {
  local target=$1 role=$2 label=$3
  [[ -z "$active_pid" && -z "$uncertain_database" ]] || return 2
  [[ "$target:$role" == rtr_tip054_r21_local_e1:rtr_tip054_local || "$target:$role" == rtr_tip054_r21_engine_e1:rtr_tip054_engine ]] || return 2
  capacity "$label" || return 1
  [[ $(absence "$target") == 0 ]] || return 2
  pg_sql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT rolname,rolcanlogin FROM pg_roles WHERE rolname IN ('rtr_app','rtr_tip054_engine') ORDER BY rolname;" > "$evidence/$label-role-login.txt" || return 1
  [[ $(sed -n '1p' "$evidence/$label-role-login.txt") == 'rtr_app|t' && $(sed -n '2p' "$evidence/$label-role-login.txt") == 'rtr_tip054_engine|t' && $(wc -l < "$evidence/$label-role-login.txt") -eq 2 ]] || return 2
  uncertain_database="$target"
  pg_sql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$target\" OWNER $role;" \
    > "$evidence/$label-create.stdout.txt" 2> "$evidence/$label-create.stderr.txt" || return 1
  owned_databases+=("$target")
  owned_count=$((owned_count + 1))
  uncertain_database=''
}
create rtr_tip054_r21_local_e1 rtr_tip054_local domain
create rtr_tip054_r21_engine_e1 rtr_tip054_engine engine
checked migration /usr/bin/env MIGRATION_DSN=postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r21_local_e1 /app/.venv/bin/alembic upgrade 0019_action_executor
for target in rtr_tip054_r21_local_e1 rtr_tip054_r21_engine_e1; do
  role=rtr_app; [[ "$target" != rtr_tip054_r21_engine_e1 ]] || role=rtr_tip054_engine
  pg_sql -U rtr_tip054_local -d "$target" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$target\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$target\" TO $role;" > "$evidence/$target-grants.txt"
done
printf 'serving_executor OFF; synthetic queueing true; observer OFF; no workers/providers/native; synthetic subject not OIDC\n' > "$evidence/executor-scope.txt"
load_code=0
checked load /usr/bin/env "${load_env[@]}" /app/.venv/bin/python /work/r/run_phase_baseline.py "$container_evidence/run" off || load_code=$?
[[ -z "$active_pid" ]] || exit 1
# Post-timer, post-drain administrative proof; retained even when load fails.
post_code=0
pg_sql -U rtr_tip054_local -d rtr_tip054_r21_engine_e1 -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','p');" > "$evidence/engine-user-tables.txt" 2> "$evidence/engine-user-tables.stderr.txt" || post_code=1
[[ $(cat "$evidence/engine-user-tables.txt") == 0 ]] || post_code=1
pg_sql -U rtr_tip054_local -d rtr_tip054_r21_local_e1 -At -v ON_ERROR_STOP=1 -c "SELECT coalesce(sum(spent_tool_calls),0),(SELECT count(*) FROM action_step_attempts),(SELECT count(*) FROM action_execution_receipts),(SELECT count(*) FROM action_source_links),(SELECT count(*) FROM action_execution_events WHERE event_type='attempt_charged'),count(*) FILTER(WHERE owner_token IS NOT NULL OR lease_expires_at IS NOT NULL OR state IN ('running','waiting')) FROM action_executions;" > "$evidence/domain-no-worker-effects.txt" 2> "$evidence/domain-no-worker-effects.stderr.txt" || post_code=1
[[ $(cat "$evidence/domain-no-worker-effects.txt") == '0|0|0|0|0|0' ]] || post_code=1
printf 'postload %d\n' "$post_code" >> "$evidence/returncodes.txt"
analysis_code=0
python3 -B "$r21_dir/qualification.py" analyze "$evidence" > "$evidence/reconstructed.json" 2> "$evidence/reconstructed.stderr.txt" || analysis_code=$?
printf 'analysis %d\n' "$analysis_code" >> "$evidence/returncodes.txt"
[[ "$load_code" == 0 && "$post_code" == 0 && "$analysis_code" == 0 ]]
