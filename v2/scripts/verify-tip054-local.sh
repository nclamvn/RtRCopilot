#!/usr/bin/env bash
# Hermetic TIP-054.2/.3 verification; never reads .env or mounts a serving volume.
# Cached images only. QA package download requires explicit TIP054_INSTALL_QA=1.
# Usage: bash scripts/verify-tip054-local.sh [pytest arguments...]
# TIP054_KEEP=1 leaves labeled fixtures for independent Contractor reruns.
# TIP054_SCOPE=focused selects only new Context/Action/shared modules, isolated.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$project_root/.." && pwd)"
run_id="${TIP054_RUN_ID:-$(date +%Y%m%d_%H%M%S)_$$}"
[[ "$run_id" =~ ^[A-Za-z0-9_]+$ ]] || { echo 'Unsafe run id' >&2; exit 2; }
[[ ${#run_id} -le 32 ]] || { echo 'Run id exceeds safe database-name length' >&2; exit 2; }
owner="tip054-local-$run_id"
prefix="rtr_tip054_$run_id"
network="${prefix}_network"
pg="${prefix}_pg"
redis="${prefix}_redis"
minio="${prefix}_minio"
runner="${prefix}_runner"
database="${prefix}_verify"
[[ "$database" == rtr_tip054_* ]] || exit 2
password='rtr_tip054_synthetic_only'
qa_image="${TIP054_QA_IMAGE:-rtr-tip054-local-qa:20261006}"
scope="${TIP054_SCOPE:-full}"
[[ "$scope" == full || "$scope" == focused ]] || { echo 'Invalid TIP054_SCOPE' >&2; exit 2; }
pg_image='pgvector/pgvector:pg16'
redis_image='redis:7-alpine'
minio_image='quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z'
mc_image='minio/mc:RELEASE.2025-07-21T05-28-08Z'
for image in "$qa_image" "$pg_image" "$redis_image" "$minio_image" "$mc_image"; do
  docker image inspect "$image" >/dev/null || { echo "Missing cached image: $image" >&2; exit 2; }
done

cleanup() {
  if [[ "${TIP054_KEEP:-0}" == 1 ]]; then
    echo "Retained owned fixtures: $runner $pg $redis $minio $network (owner=$owner)"
    return
  fi
  for target in "$runner" "$pg" "$redis" "$minio"; do
    [[ "$target" == rtr_tip054_* ]] || continue
    actual="$(docker inspect -f '{{index .Config.Labels "rtr.tip054.owner"}}' "$target" 2>/dev/null || true)"
    if [[ "$actual" == "$owner" ]]; then docker rm -f -v "$target" >/dev/null; fi
  done
  actual="$(docker network inspect -f '{{index .Labels "rtr.tip054.owner"}}' "$network" 2>/dev/null || true)"
  if [[ "$actual" == "$owner" ]]; then docker network rm "$network" >/dev/null; fi
}
trap cleanup EXIT

docker network create --internal --label "rtr.tip054.owner=$owner" "$network" >/dev/null
docker run -d --name "$pg" --label "rtr.tip054.owner=$owner" --network "$network" \
  --network-alias tip054-pg -e POSTGRES_USER=rtr_tip054_local \
  -e "POSTGRES_PASSWORD=$password" -e "POSTGRES_DB=$database" "$pg_image" >/dev/null
docker run -d --name "$redis" --label "rtr.tip054.owner=$owner" --network "$network" \
  --network-alias tip054-redis "$redis_image" >/dev/null
docker run -d --name "$minio" --label "rtr.tip054.owner=$owner" --network "$network" \
  --network-alias tip054-minio -e MINIO_ROOT_USER=rtr_tip054_local \
  -e "MINIO_ROOT_PASSWORD=$password" "$minio_image" server /data >/dev/null

# Preserve the repository-relative shape expected by static source tests.
# Mount only explicitly selected source/templates/fixtures; no private .env,
# eval/runtime capture, kernel corpus, .git, Docker socket or business volume.
mounts=()
for item in src tests migrations pyproject.toml alembic.ini; do
  mounts+=(-v "$project_root/apps/backend/$item:/workspace/v2/apps/backend/$item:ro")
done
for item in scripts Makefile .gitignore .env.example compose.yaml; do
  mounts+=(-v "$project_root/$item:/workspace/v2/$item:ro")
done
for item in lib migrate parity pilot quality real_world run_eval.py run_parity.py run_real_world_acceptance.py; do
  mounts+=(-v "$project_root/eval/$item:/workspace/v2/eval/$item:ro")
done
mounts+=(-v "$repo_root/phase1_pilot/copilot_server.py:/workspace/phase1_pilot/copilot_server.py:ro")
owner_dsn="postgresql://rtr_tip054_local:$password@tip054-pg:5432/$database"
runtime_dsn="postgresql://rtr_app:$password@tip054-pg:5432/$database"
runner_network="$network"
if [[ "${TIP054_INSTALL_QA:-0}" == 1 ]]; then runner_network=bridge; fi
docker run -d --name "$runner" --label "rtr.tip054.owner=$owner" --network "$runner_network" \
  --entrypoint sh "${mounts[@]}" -w /workspace/v2/apps/backend \
  -e PYTHONPATH=/workspace/v2/apps/backend/src \
  -e "POSTGRES_DSN=$runtime_dsn" -e "MIGRATION_DSN=$owner_dsn" \
  -e "INTEGRATION_DATABASE_DSN=$runtime_dsn" \
  -e APP_ENV=test -e REDIS_URL=redis://tip054-redis:6379/0 \
  -e S3_ENDPOINT=http://tip054-minio:9000 -e S3_ACCESS_KEY=rtr_tip054_local \
  -e "S3_SECRET_KEY=$password" -e S3_BUCKET=rtr-tip054-synthetic \
  -e RAG_EMBEDDING_PROVIDER=offline -e RAG_PROVIDER_MODE=local \
  -e OPENAI_API_KEY= -e ANTHROPIC_API_KEY= \
  -e EXPECTED_SCHEMA_REVISION=0018_action_contracts \
  "$qa_image" -c 'sleep infinity' >/dev/null
if [[ "${TIP054_INSTALL_QA:-0}" == 1 ]]; then
  docker exec "$runner" /app/.venv/bin/python -m ensurepip
  docker exec "$runner" /app/.venv/bin/python -m pip install \
    pytest==8.4.1 pytest-asyncio==1.1.0 ruff==0.12.9 mypy==1.17.1
  docker network connect "$network" "$runner"
  docker network disconnect bridge "$runner"
fi
docker exec "$runner" /app/.venv/bin/python -m pytest --version
runner_exec() {
  # An empty SecretStr is not the same as absent; preserve missing-key oracles.
  docker exec "$runner" env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY "$@"
}
for attempt in $(seq 1 30); do
  if docker exec "$pg" pg_isready -U rtr_tip054_local -d "$database" >/dev/null; then break; fi
  sleep 1
done
docker exec "$pg" pg_isready -U rtr_tip054_local -d "$database" >/dev/null
minio_ready=0
for attempt in $(seq 1 30); do
  if docker run --rm --network "$network" --entrypoint sh "$mc_image" -c \
    'mc alias set local http://tip054-minio:9000 rtr_tip054_local rtr_tip054_synthetic_only && mc mb --ignore-existing local/rtr-tip054-synthetic'; then
    minio_ready=1
    break
  fi
  sleep 1
done
[[ "$minio_ready" == 1 ]] || { echo 'Synthetic MinIO startup timed out' >&2; exit 3; }
echo "Owned runner=$runner database=$database owner=$owner"
assert_schema() {
  expected_revision="$1"
  expected_context="$2"
  expected_actions="$3"
  observed="$(docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -Atc \
    "SELECT version_num FROM alembic_version;
     SELECT count(*) FROM information_schema.tables WHERE table_schema='public'
       AND table_name IN ('context_packets','memory_entries');
     SELECT count(*) FROM information_schema.tables WHERE table_schema='public'
       AND table_name IN ('capability_versions','action_plans','action_runs',
                         'action_approvals','action_events','action_receipts');
     SELECT count(*) FROM information_schema.columns WHERE table_name='render_jobs'
       AND column_name IN ('lease_token','lease_expires_at','attempt','max_attempts');")"
  [[ "$observed" == "$expected_revision"$'\n'"$expected_context"$'\n'"$expected_actions"$'\n4' ]] \
    || { echo "Schema mismatch: $observed" >&2; exit 3; }
}
docker exec "$runner" /app/.venv/bin/alembic upgrade 0016_document_render_lease
assert_schema 0016_document_render_lease 0 0
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c \
  "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only';"
runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py seed
for boundary in 0017_context_memory 0018_action_contracts; do
  docker exec "$runner" /app/.venv/bin/alembic upgrade "$boundary"
  if [[ "$boundary" == 0017_context_memory ]]; then assert_schema "$boundary" 2 0;
  else assert_schema "$boundary" 2 6; fi
  runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py verify
  if [[ "$boundary" == 0017_context_memory ]]; then
    runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py seed-context
  else
    runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py verify-context
    runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py seed-actions
  fi
done
docker exec "$runner" /app/.venv/bin/alembic downgrade 0017_context_memory
assert_schema 0017_context_memory 2 0
runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py verify
runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py verify-context
docker exec "$runner" /app/.venv/bin/alembic downgrade 0016_document_render_lease
assert_schema 0016_document_render_lease 0 0
echo 'Downgrade to 0016 intentionally drops Context/Memory and Action-domain rows; not a workflow restore proof.'
runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py verify
for boundary in 0017_context_memory 0018_action_contracts; do
  docker exec "$runner" /app/.venv/bin/alembic upgrade "$boundary"
  if [[ "$boundary" == 0017_context_memory ]]; then assert_schema "$boundary" 2 0;
  else assert_schema "$boundary" 2 6; fi
  runner_exec /app/.venv/bin/python /workspace/v2/scripts/verify_tip054_migration.py verify
done
docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -Atc \
  "SELECT has_table_privilege('rtr_app','render_jobs','SELECT'), has_table_privilege('rtr_app','render_jobs','INSERT'), has_table_privilege('rtr_app','render_jobs','UPDATE'), has_table_privilege('rtr_app','render_jobs','DELETE'), has_schema_privilege('rtr_app','public','CREATE');" | grep -qx 't|t|t|f|f'
for table in context_packets memory_entries capability_versions action_plans action_runs action_approvals action_events action_receipts; do
  expected_rights='t|t|f|f|f'
  case "$table" in memory_entries|capability_versions|action_runs|action_approvals) expected_rights='t|t|t|f|f';; esac
  observed="$(docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -Atc \
    "SELECT has_table_privilege('rtr_app','$table','SELECT'), has_table_privilege('rtr_app','$table','INSERT'), has_table_privilege('rtr_app','$table','UPDATE'), has_table_privilege('rtr_app','$table','DELETE'), has_table_privilege('rtr_app','$table','TRUNCATE');")"
  [[ "$observed" == "$expected_rights" ]] || { echo "Runtime rights mismatch: $table $observed" >&2; exit 3; }
  recreated_count="$(docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -Atc "SELECT count(*) FROM $table;")"
  [[ "$recreated_count" == 0 ]] || { echo "Unexpected restored domain rows: $table" >&2; exit 3; }
done
echo 'Migration cycle PASS: 0016 -> 0017 -> 0018 -> 0017 -> 0016 -> 0017 -> 0018; signed SOT/render/audit fingerprints preserved; eight domain table rights checked individually.'
if [[ $# == 0 ]]; then
  unit_targets=(tests)
  integration_targets=("$project_root"/apps/backend/tests/*integration.py)
  if [[ "$scope" == focused ]]; then
    unit_targets=(tests/test_context_memory_unit.py tests/test_action_contracts_unit.py tests/test_tip054_shared_unit.py)
    integration_targets=(
      "$project_root/apps/backend/tests/test_context_memory_integration.py"
      "$project_root/apps/backend/tests/test_action_contracts_integration.py"
      "$project_root/apps/backend/tests/test_tip054_shared_integration.py"
    )
  fi
  runner_exec /app/.venv/bin/python -m pytest -q -rs -p no:cacheprovider \
    --junitxml=/tmp/tip054-unit.xml --ignore-glob='*integration.py' "${unit_targets[@]}"
  # Existing governance tests deliberately activate global ontology/maintenance
  # state. A shared database in alphabetical order changes later RAG oracles.
  # Give each integration module a fresh database and its own pytest process;
  # do not weaken assertions or rely on a lucky ordering of global side effects.
  index=0
  integration_status=0
  for test_file in "${integration_targets[@]}"; do
    index=$((index + 1))
    case_database="${prefix}_i${index}"
    [[ "$case_database" =~ ^rtr_tip054_[A-Za-z0-9_]+$ ]] || exit 2
    docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 \
      -c "CREATE DATABASE \"$case_database\";" >/dev/null
    case_owner="postgresql://rtr_tip054_local:$password@tip054-pg:5432/$case_database"
    case_runtime="postgresql://rtr_app:$password@tip054-pg:5432/$case_database"
    docker exec -e "MIGRATION_DSN=$case_owner" "$runner" /app/.venv/bin/alembic upgrade head
    docker exec "$redis" redis-cli FLUSHDB >/dev/null
    test_name="$(basename "$test_file")"
    echo "Isolated integration module: $test_name database=$case_database"
    if ! docker exec -e "POSTGRES_DSN=$case_runtime" -e "MIGRATION_DSN=$case_owner" \
      -e "INTEGRATION_DATABASE_DSN=$case_runtime" "$runner" \
      env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY /app/.venv/bin/python -m pytest \
      -q -rs -p no:cacheprovider -o asyncio_default_test_loop_scope=session \
      "--junitxml=/tmp/tip054-integration-$index.xml" "tests/$test_name"; then
      integration_status=1
    fi
  done
  docker exec "$runner" /app/.venv/bin/python -c \
    'import glob, xml.etree.ElementTree as E; suites=[s for p in glob.glob("/tmp/tip054-integration-*.xml") for s in E.parse(p).getroot().iter("testsuite")]; print("INTEGRATION_TOTALS", {k:sum(int(s.get(k,"0")) for s in suites) for k in ("tests","failures","errors","skipped")})'
  [[ "$integration_status" == 0 ]] || exit 1
else
  runner_exec /app/.venv/bin/python -m pytest -q -rs -p no:cacheprovider "$@"
fi
docker exec "$runner" /app/.venv/bin/ruff check --no-cache src tests
docker exec "$runner" /app/.venv/bin/mypy --cache-dir=/tmp/rtr-tip054-mypy
