#!/usr/bin/env bash
# Main-only frozen OFF qualification. Per child 120s; whole HTTP child 190s.
set -euo pipefail
r19_dir=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$r19_dir/../../../.." && pwd)
cd "$repo"
stage=${1:?pre or http required}
epoch=${2:?fresh pre_eN or sole http_e1 required}
binding_name=${3:?source-binding-eN.json required}
[[ "${R19_MAIN_ADMISSION:-}" == "$stage" ]] || exit 2
[[ "$binding_name" =~ ^source-binding-e[1-9][0-9]*\.json$ ]] || exit 2
binding="$r19_dir/$binding_name"
fixture=tip054-4b-full-20261007-r5qa1
runner="$fixture-runner"
pg="$fixture-pg"
raw="$repo/v2/experiments/action_executor/raw/$fixture/r19"
evidence="$raw/$epoch"
container_evidence="/evidence/r19/$epoch"
marker="$raw/campaign-launch.json"
[[ ! -e "$evidence" ]] || { echo 'Evidence epoch already exists; no overwrite'; exit 2; }
python3 -B "$r19_dir/qualification.py" stage "$stage" "$epoch"
python3 -B "$r19_dir/qualification.py" source "$binding"
python3 -B "$r19_dir/qualification.py" review "${R19_SOURCE_REVIEW:?accepted review path}" "${R19_SOURCE_REVIEW_SHA256:?review pin}"
if [[ "$stage" == http ]]; then
  [[ ! -e "$marker" ]] || { echo 'Campaign consumed or launch unknown'; exit 2; }
  pre_epoch=${4:?same-binding passing pre_eN required}
  [[ "$pre_epoch" =~ ^pre_e[1-9][0-9]*$ ]] || exit 2
  python3 -B "$r19_dir/qualification.py" prior "$raw/$pre_epoch" "$binding"
fi
mkdir -p "$evidence/tmp" "$evidence/pytest-tmp"
cp "$binding" "$evidence/binding.json"
cp "$r19_dir/contract.json" "$evidence/contract.json"
printf '%s %s\n' "$R19_SOURCE_REVIEW" "$R19_SOURCE_REVIEW_SHA256" > "$evidence/review-pin.txt"
active_pid=''
active_label=''
owned_databases=()
owned_count=0
uncertain_database=''
docker_path=$(command -v docker)
[[ "$docker_path" == /* && -x "$docker_path" ]] || exit 2
base_env=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin
  TMPDIR="$container_evidence/tmp" PYTHONDONTWRITEBYTECODE=1
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r:/work/r19
  APP_ENV=test ACTION_EXECUTOR_ENABLED=false
  POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r19_local_e1
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only
  S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { "$docker_path" exec -w /workspace/v2/apps/backend "$runner" env -i "${base_env[@]}" "$@"; }
check_source() { python3 -B "$r19_dir/qualification.py" source "$binding"; }
fixture_check() {
  python3 -B "$r19_dir/qualification.py" fixture "$repo/v2/experiments/action_executor/r12/preflight_e1/fixture-preflight.json" "$docker_path"
}
absence() {
  [[ "$1" == rtr_tip054_r19_local_e1 || "$1" == rtr_tip054_r19_engine_e1 ]] || return 2
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_database WHERE datname='$1';"
}
stop_active() {
  [[ -n "$active_pid" ]] || return 0
  exec_runner /app/.venv/bin/python /work/r19/bounded.py stop "$container_evidence" "$active_label" \
    > "$evidence/$active_label-stop.stdout.txt" 2> "$evidence/$active_label-stop.stderr.txt" || return 1
  # Supervisor owns a SINGLE shared 10s grace; host join adds <=2s transport bookkeeping.
  local join_deadline=$((SECONDS + 12))
  while kill -0 "$active_pid" 2>/dev/null && (( SECONDS < join_deadline )); do sleep 0.05; done
  if kill -0 "$active_pid" 2>/dev/null; then return 1; fi
  wait "$active_pid" || true
  python3 -B "$r19_dir/qualification.py" drained "$evidence/$active_label.process.json" \
    > "$evidence/$active_label-stop-proof.txt" || return 1
  active_pid=''
  active_label=''
}
cleanup() {
  [[ -z "$active_pid" ]] || return 2
  local target count index
  for ((index=owned_count-1; index>=0; index--)); do
    target=${owned_databases[$index]}
    [[ "$target" == rtr_tip054_r19_local_e1 || "$target" == rtr_tip054_r19_engine_e1 ]] || return 2
    "$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
      -c "DROP DATABASE \"$target\";" > "$evidence/$target-cleanup.stdout.txt" \
      2> "$evidence/$target-cleanup.stderr.txt" || return 1
    printf 'database_cleanup %s 0\n' "$target" >> "$evidence/returncodes.txt"
    unset 'owned_databases[index]'
    owned_count=$((owned_count - 1))
    count=$(absence "$target") || return 1
    printf '%s absence_after_cleanup %s\n' "$target" "$count" >> "$evidence/database-closure.txt"
    [[ "$count" == 0 ]] || return 1
  done
  [[ -z "$uncertain_database" ]] || return 1
}
finish() {
  local code=$? count target
  trap - EXIT INT TERM HUP
  if ! stop_active; then
    printf 'owned_process_drain FAILED; databases retained\n' >> "$evidence/returncodes.txt"
    code=1
  elif ! cleanup; then
    printf 'owned_or_uncertain_database cleanup FAILED\n' >> "$evidence/returncodes.txt"
    code=1
  fi
  check_source > "$evidence/source-after.txt" || code=1
  fixture_check > "$evidence/fixture-after.txt" 2> "$evidence/fixture-after.stderr.txt" || code=1
  for target in rtr_tip054_r19_local_e1 rtr_tip054_r19_engine_e1; do
    count=$(absence "$target") || code=1
    printf '%s final_absence %s\n' "$target" "${count:-unknown}" >> "$evidence/database-closure.txt"
    [[ "${count:-unknown}" == 0 ]] || code=1
  done
  df -k / > "$evidence/host-disk-after.txt" || code=1
  "$docker_path" exec "$pg" df -k /var/lib/postgresql/data > "$evidence/pg-disk-after.txt" || code=1
  [[ $(awk 'NR==2 {print $4}' "$evidence/host-disk-after.txt") -ge 20971520 ]] || code=1
  [[ $(awk 'NR==2 {print $4}' "$evidence/pg-disk-after.txt") -ge 524288 ]] || code=1
  if [[ "$stage" == http ]]; then
    [[ -e "$marker" ]] && printf 'campaign CONSUMED_or_unknown\n' >> "$evidence/returncodes.txt"
    [[ -e "$marker" ]] || printf 'campaign known_UNLAUNCHED\n' >> "$evidence/returncodes.txt"
  fi
  python3 -B "$r19_dir/qualification.py" cap "$evidence" "$stage" > "$evidence/cap-after.txt" || code=1
  printf 'stage %s exit %d\n' "$stage" "$code" >> "$evidence/returncodes.txt"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
check_source > "$evidence/source-before.txt"
fixture_check > "$evidence/fixture-before.txt" 2> "$evidence/fixture-before.stderr.txt"
for target in rtr_tip054_r19_local_e1 rtr_tip054_r19_engine_e1; do
  count=$(absence "$target")
  printf '%s initial_absence %s\n' "$target" "$count" >> "$evidence/database-closure.txt"
  [[ "$count" == 0 ]] || exit 2
done
printf 'serving_executor OFF; isolated HTTP queueing flag true; OFF observers; no worker/provider/native; synthetic subject not OIDC\n' > "$evidence/executor-scope.txt"
checked() {
  local label=$1 code=0
  shift
  [[ -z "$active_pid" ]] || return 1
  check_source > "$evidence/source-$label-before.txt" || return 1
  python3 -B "$r19_dir/qualification.py" cap "$evidence" "$stage" > "$evidence/cap-$label-before.txt" || return 1
  active_label="$label"
  if [[ "$label" == load ]]; then
    python3 -B "$r19_dir/qualification.py" mark "$marker" "$binding" > "$evidence/launch-marker.txt" || return 1
  fi
  exec_runner /app/.venv/bin/python /work/r19/bounded.py run "$container_evidence" "$stage" "$label" "$@" \
    > "$evidence/$label-supervisor.stdout.txt" 2> "$evidence/$label-supervisor.stderr.txt" &
  active_pid=$!
  wait "$active_pid" || code=$?
  if kill -0 "$active_pid" 2>/dev/null; then return 1; fi
  printf '%s %d\n' "$label" "$code" >> "$evidence/returncodes.txt"
  python3 -B "$r19_dir/qualification.py" child "$evidence/$label.process.json" "$code" \
    > "$evidence/$label-child-admission.txt" || return 1
  active_pid=''
  active_label=''
  check_source > "$evidence/source-$label-after.txt" || return 1
  python3 -B "$r19_dir/qualification.py" cap "$evidence" "$stage" > "$evidence/cap-$label-after.txt" || return 1
  return "$code"
}
pytest_common=(-c /workspace/v2/apps/backend/pyproject.toml -q -rs -p no:cacheprovider)
files=(/work/r19/qualification.py /work/r19/bounded.py /work/r19/test_r19_offline.py)
if [[ "$stage" == pre ]]; then
  checked syntax /app/.venv/bin/python -c 'import sys; from pathlib import Path; [compile(Path(p).read_text(),p,"exec") for p in sys.argv[1:]]; print("SYNTAX_3_PASS")' "${files[@]}"
  checked pins /app/.venv/bin/python -c 'from importlib.metadata import version; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; assert version("pytest")=="8.4.1"; print("PINS_PASS")'
  checked ruff /app/.venv/bin/ruff check --no-cache "${files[@]}"
  checked format /app/.venv/bin/ruff format --check --no-cache "${files[@]}"
  selected=()
  while IFS= read -r line; do selected+=("$line"); done < <(python3 -B "$r19_dir/qualification.py" selectors)
  [[ "${#selected[@]}" == 6 ]] || exit 2
  checked collection /app/.venv/bin/python -m pytest "${pytest_common[@]}" --collect-only "${selected[@]}"
  checked inventory /app/.venv/bin/python /work/r19/qualification.py collection "$container_evidence/collection.stdout.txt"
  checked offline /app/.venv/bin/python -m pytest "${pytest_common[@]}" "--basetemp=$container_evidence/pytest-tmp/offline" "--junitxml=$container_evidence/offline.xml" "${selected[@]}"
  checked xml /app/.venv/bin/python /work/r19/qualification.py xml "$container_evidence/offline.xml"
  exit 0
fi
create() {
  local target=$1 role=$2 label=$3 existing host_kib pg_kib
  [[ -z "$active_pid" ]] || return 2
  [[ "$target:$role" == rtr_tip054_r19_local_e1:rtr_tip054_local || "$target:$role" == rtr_tip054_r19_engine_e1:rtr_tip054_engine ]] || return 2
  df -k / > "$evidence/$label-host-disk.txt" || return 1
  host_kib=$(awk 'NR==2 {print $4}' "$evidence/$label-host-disk.txt")
  "$docker_path" exec "$pg" df -k /var/lib/postgresql/data > "$evidence/$label-pg-disk.txt" || return 1
  pg_kib=$(awk 'NR==2 {print $4}' "$evidence/$label-pg-disk.txt")
  [[ "$host_kib" =~ ^[0-9]+$ && "$host_kib" -ge 20971520 ]] || return 66
  [[ "$pg_kib" =~ ^[0-9]+$ && "$pg_kib" -ge 524288 ]] || return 66
  existing=$(absence "$target") || return 1
  printf '%s existing=%s host_kib=%s pg_kib=%s\n' "$target" "$existing" "$host_kib" "$pg_kib" >> "$evidence/database-admission.txt"
  [[ "$existing" == 0 ]] || return 2
  uncertain_database="$target"
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"$target\" OWNER $role;" > "$evidence/$label-create.stdout.txt" 2> "$evidence/$label-create.stderr.txt" || return 1
  owned_databases+=("$target")
  owned_count=$((owned_count + 1))
  uncertain_database=''
}
"$docker_path" exec "$pg" psql -U rtr_tip054_local -d postgres -At -v ON_ERROR_STOP=1 \
  -c "SELECT rolname,rolcanlogin FROM pg_roles WHERE rolname IN ('rtr_app','rtr_tip054_engine') ORDER BY rolname;" > "$evidence/role-login.txt"
[[ $(sed -n '1p' "$evidence/role-login.txt") == 'rtr_app|t' && $(sed -n '2p' "$evidence/role-login.txt") == 'rtr_tip054_engine|t' && $(wc -l < "$evidence/role-login.txt") -eq 2 ]] || exit 2
create rtr_tip054_r19_local_e1 rtr_tip054_local domain
create rtr_tip054_r19_engine_e1 rtr_tip054_engine engine
checked migration /usr/bin/env MIGRATION_DSN=postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r19_local_e1 /app/.venv/bin/alembic upgrade 0019_action_executor
for target in rtr_tip054_r19_local_e1 rtr_tip054_r19_engine_e1; do
  role=rtr_app
  [[ "$target" != rtr_tip054_r19_engine_e1 ]] || role=rtr_tip054_engine
  "$docker_path" exec "$pg" psql -U rtr_tip054_local -d "$target" -v ON_ERROR_STOP=1 \
    -c "REVOKE CONNECT ON DATABASE \"$target\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$target\" TO $role;" > "$evidence/$target-permissions.txt"
done
load_code=0
checked load /usr/bin/env ACTION_EXECUTOR_ENABLED=true LIMITS_RATE_RENDER_MAX=5000 LIMITS_RATE_DEFAULT_READ_MAX=5000 \
  ACTION_WORKFLOW_DSN=postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_r19_engine_e1 \
  /app/.venv/bin/python /work/r/run_phase_baseline.py "$container_evidence/run" off || load_code=$?
[[ -z "$active_pid" ]] || exit 1
analysis_code=0
python3 -B "$r19_dir/qualification.py" analyze "$evidence" > "$evidence/reconstructed.json" 2> "$evidence/reconstructed.stderr.txt" || analysis_code=$?
printf 'analysis %d\n' "$analysis_code" >> "$evidence/returncodes.txt"
[[ "$load_code" == 0 && "$analysis_code" == 0 ]]
